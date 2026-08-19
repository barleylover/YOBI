from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.db.repository import YobiRepository
from app.domain.models import RestaurantNoteTranslation, RestaurantNoteTranslationInput
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider


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
    """Translate a visitor note to Korean with a narrow two-model policy."""

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

        models = [self.settings.restaurant_note_model]
        fallback = self.settings.oci_genai_fallback_model.strip()
        if fallback and fallback != models[0]:
            models.append(fallback)
        request: dict[str, Any] = {
            "instructions": (
                "Translate the visitor's restaurant note into natural, polite Korean. "
                "Preserve names, quantities, negation, and requests exactly. Also translate "
                "the Korean result back into the source language for confirmation. Return JSON only."
            ),
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "source_language": data.source_language,
                            "source_text": data.source_text,
                        },
                        ensure_ascii=False,
                    ),
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
            try:
                if not self.provider.configured or not self.provider.supports_model(model_id):
                    raise GenAIProviderError(
                        GenAIErrorCode.PROVIDER_UNAVAILABLE,
                        retryable=False,
                    )
                response = self.provider.create_response(model_id, **request)
                raw = str(getattr(response, "output_text", "")).strip()
                parsed = _TranslationPayload.model_validate(json.loads(raw))
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
                fallback_allowed = exc.code in {
                    GenAIErrorCode.RATE_LIMIT,
                    GenAIErrorCode.TIMEOUT,
                } or (
                    exc.code is GenAIErrorCode.PROVIDER_UNAVAILABLE and exc.retryable
                )
                if fallback_allowed and index + 1 < len(models):
                    continue
                break
            except (json.JSONDecodeError, ValidationError, ValueError):
                last_error = "TRANSLATION_RESPONSE_INVALID"
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
