from __future__ import annotations

import hashlib
import json
from time import monotonic
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.db.repository import YobiRepository
from app.domain.models import RestaurantNoteTranslation, RestaurantNoteTranslationInput
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider
from app.genai.response_contract import parse_json_object


class _TranslationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    korean_text: str = Field(min_length=1, max_length=500)
    back_translation: str = Field(min_length=1, max_length=500)


_TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "korean_text": {"type": "string", "minLength": 1, "maxLength": 500},
        "back_translation": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "required": ["korean_text", "back_translation"],
    "additionalProperties": False,
}


class RestaurantNoteTranslationService:
    """Translate a visitor note through a configured, audited OCI model chain."""

    def __init__(
        self,
        repository: YobiRepository,
        settings: Settings,
        *,
        provider: GenAIProvider | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.provider = provider or choose_genai_provider(settings)

    def translate(
        self,
        session_id: str,
        data: RestaurantNoteTranslationInput,
    ) -> RestaurantNoteTranslation:
        canonical = json.dumps(
            {
                "session_id": session_id,
                "source_language": data.source_language.strip().lower(),
                "source_text": data.source_text.strip(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        cached = self.repository.get_restaurant_note_translation_by_hash(
            session_id, request_hash
        )
        if cached is not None:
            return cached

        models = list(
            dict.fromkeys(
                model.strip()
                for model in self.settings.restaurant_note_model_chain.split(",")
                if model.strip()
            )
        )
        models = list(
            dict.fromkeys(
                [
                    *models,
                    self.settings.restaurant_note_model.strip(),
                    self.settings.oci_genai_fallback_model.strip(),
                ]
            )
        )
        models = [model for model in models if model]
        input_payload: dict[str, Any] = {
            "source_language": data.source_language,
            "source_text": data.source_text,
        }
        if not self.provider.capabilities.structured_output:
            input_payload["response_contract"] = _TRANSLATION_SCHEMA
        request: dict[str, Any] = {
            "instructions": (
                "Translate the visitor's restaurant note into natural, polite Korean. "
                "Preserve names, quantities, negation, and requests exactly. Also translate "
                "the Korean result back into the source language for confirmation. Return exactly "
                "one JSON object with only korean_text and back_translation string fields. Do not "
                "use Markdown, a code fence, Korean field names, commentary, or additional keys."
            ),
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(input_payload, ensure_ascii=False),
                }
            ],
            "max_output_tokens": min(700, self.provider.capabilities.max_output_tokens),
        }
        if self.provider.capabilities.structured_output:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "yobi_restaurant_note_translation_v1",
                    "schema": _TRANSLATION_SCHEMA,
                    "strict": True,
                }
            }

        last_model = models[0]
        last_error = GenAIErrorCode.PROVIDER_UNAVAILABLE.value
        for index, model_id in enumerate(models):
            last_model = model_id
            attempt_started = monotonic()
            try:
                if not self.provider.configured or not self.provider.supports_model(model_id):
                    raise GenAIProviderError(
                        GenAIErrorCode.PROVIDER_UNAVAILABLE,
                        retryable=True,
                    )
                response = self.provider.create_response(model_id, **request)
                raw = str(getattr(response, "output_text", "")).strip()
                parsed = _TranslationPayload.model_validate(parse_json_object(raw))
                if (
                    not data.source_language.lower().startswith("ko")
                    and not any("가" <= character <= "힣" for character in parsed.korean_text)
                ):
                    raise ValueError("TRANSLATION_KOREAN_TEXT_REQUIRED")
                usage = self._usage(response)
                self._record_attempt(
                    session_id,
                    request_hash,
                    attempt_no=index + 1,
                    model_id=model_id,
                    status="SUCCEEDED",
                    error_code=None,
                    latency_ms=int((monotonic() - attempt_started) * 1000),
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                )
                return self.repository.save_restaurant_note_translation(
                    session_id,
                    translation_id=f"note_{uuid4().hex}",
                    source_language=data.source_language,
                    source_text=data.source_text,
                    korean_text=parsed.korean_text,
                    back_translation=parsed.back_translation,
                    provider=self.settings.genai_provider,
                    model_id=model_id,
                    status="SUCCEEDED",
                    error_code=None,
                    request_hash=request_hash,
                )
            except GenAIProviderError as exc:
                last_error = exc.code.value
                self._record_attempt(
                    session_id,
                    request_hash,
                    attempt_no=index + 1,
                    model_id=model_id,
                    status="FAILED",
                    error_code=last_error,
                    latency_ms=int((monotonic() - attempt_started) * 1000),
                    input_tokens=None,
                    output_tokens=None,
                )
                fallback_allowed = exc.code in {
                    GenAIErrorCode.RATE_LIMIT,
                    GenAIErrorCode.TIMEOUT,
                    GenAIErrorCode.NETWORK_ERROR,
                    GenAIErrorCode.PROVIDER_UNAVAILABLE,
                }
                if fallback_allowed and index + 1 < len(models):
                    continue
                break
            except (json.JSONDecodeError, ValidationError, ValueError):
                last_error = "TRANSLATION_RESPONSE_INVALID"
                self._record_attempt(
                    session_id,
                    request_hash,
                    attempt_no=index + 1,
                    model_id=model_id,
                    status="FAILED",
                    error_code=last_error,
                    latency_ms=int((monotonic() - attempt_started) * 1000),
                    input_tokens=None,
                    output_tokens=None,
                )
                if index + 1 < len(models):
                    continue
                break

        return self.repository.save_restaurant_note_translation(
            session_id,
            translation_id=f"note_{uuid4().hex}",
            source_language=data.source_language,
            source_text=data.source_text,
            korean_text=None,
            back_translation=None,
            provider=self.settings.genai_provider,
            model_id=last_model,
            status="FAILED",
            error_code=last_error,
            request_hash=request_hash,
        )

    def _record_attempt(
        self,
        session_id: str,
        request_hash: str,
        *,
        attempt_no: int,
        model_id: str,
        status: str,
        error_code: str | None,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        recorder = getattr(self.repository, "record_restaurant_note_translation_attempt", None)
        if not callable(recorder):
            return
        recorder(
            session_id,
            request_hash,
            attempt_no=attempt_no,
            provider=self.settings.genai_provider,
            model_id=model_id,
            status=status,
            error_code=error_code,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    @staticmethod
    def _usage(response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        result: dict[str, int] = {}
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                result[key] = value
        return result
