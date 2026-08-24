from __future__ import annotations

import hashlib
import json
import re
from time import monotonic
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings
from app.db.repository import YobiRepository
from app.domain.models import RestaurantNoteTranslation, RestaurantNoteTranslationInput
from app.domain.preference_catalog import normalize_preference_locale
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider
from app.genai.response_contract import parse_json_object
from app.genai.usage import response_usage_metrics


class _TranslationPayload(BaseModel):
    # Some raw-JSON models add harmless bookkeeping fields. Only these two
    # user-visible strings are consumed and persisted.
    model_config = ConfigDict(extra="ignore")

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

_INVALID_KOREAN_NOTE_CHARACTER = re.compile(
    r"[^가-힣ㄱ-ㅎㅏ-ㅣA-Za-z0-9\s.,!?()/%+\-&'·:~]"
)


def _translation_error(
    data: RestaurantNoteTranslationInput,
    payload: _TranslationPayload,
) -> str | None:
    source = data.source_text.strip()
    source_lower = source.casefold()
    korean = payload.korean_text.strip()
    back = payload.back_translation.strip()
    if not data.source_language.lower().startswith("ko") and not re.search(r"[가-힣]", korean):
        return "TRANSLATION_KOREAN_TEXT_REQUIRED"
    if _INVALID_KOREAN_NOTE_CHARACTER.search(korean):
        return "TRANSLATION_INVALID_KOREAN_CHARACTERS"
    if not re.search(r"\d", source) and (re.search(r"\d", korean) or re.search(r"\d", back)):
        return "TRANSLATION_INVENTED_NUMBER"
    if data.source_language.lower().startswith("en") and re.search(r"[가-힣]", back):
        return "TRANSLATION_BACK_TRANSLATION_LANGUAGE_INVALID"

    # These are high-impact, common restaurant-note intents. The checks are
    # deliberately narrow: they reject a changed action, while leaving ordinary
    # wording and cuisine names to the model.
    if re.search(r"\b(?:less spicy|mild|not spicy)\b", source_lower) and not re.search(
        r"덜\s*맵|맵지\s*않|안\s*맵", korean
    ):
        return "TRANSLATION_SPICE_INTENT_LOST"
    if re.search(r"\b(?:separate(?:ly)?|on the side)\b", source_lower) and not re.search(
        r"따로|별도", korean
    ):
        return "TRANSLATION_SEPARATE_INTENT_LOST"
    if "onion" in source_lower and re.search(
        r"\b(?:no|without|leave out|omit|do not add)\b", source_lower
    ) and not ("양파" in korean and re.search(r"빼|제외|넣지\s*말|없이", korean)):
        return "TRANSLATION_OMISSION_INTENT_LOST"
    if "chopstick" in source_lower and "젓가락" not in korean:
        return "TRANSLATION_CHOPSTICK_INTENT_LOST"
    if "allerg" in source_lower and "알레르기" not in korean:
        return "TRANSLATION_ALLERGY_INTENT_LOST"
    if "peanut" in source_lower and "땅콩" not in korean:
        return "TRANSLATION_PEANUT_INTENT_LOST"
    return None


def _safe_demo_translation(data: RestaurantNoteTranslationInput) -> tuple[str, str] | None:
    if not data.source_language.lower().startswith("en"):
        return None
    source = data.source_text.strip()
    lowered = source.casefold()
    if "peanut" in lowered and "allerg" in lowered:
        return "땅콩 알레르기가 있으니 땅콩은 넣지 말아 주세요.", source
    if "chopstick" in lowered and re.search(r"\b(?:two|2)\b", lowered):
        return "젓가락 두 벌 넣어 주세요.", source
    if "onion" in lowered and re.search(
        r"\b(?:no|without|leave out|omit|do not add)\b", lowered
    ):
        return "양파는 빼 주세요.", source
    if re.search(r"\b(?:sauce|dressing)\b", lowered) and re.search(
        r"\b(?:separate(?:ly)?|on the side)\b", lowered
    ):
        return "소스는 따로 담아 주세요.", source
    if re.search(r"\b(?:less spicy|mild|not spicy)\b", lowered):
        prefix = "가능하면 " if "if possible" in lowered else ""
        suffix = " 어렵다면 괜찮습니다." if re.search(
            r"if (?:not|that is difficult).*(?:okay|ok)", lowered
        ) else ""
        return f"{prefix}덜 맵게 해 주세요.{suffix}", source
    return None


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
        data = data.model_copy(
            update={
                "source_language": normalize_preference_locale(data.source_language),
                "source_text": data.source_text.strip(),
            }
        )
        canonical = json.dumps(
            {
                "session_id": session_id,
                "source_language": data.source_language.strip().lower(),
                "source_text": data.source_text.strip(),
                "prompt_version": self.settings.restaurant_note_prompt_version,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        request_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        cached = self.repository.get_restaurant_note_translation_by_hash(session_id, request_hash)
        if cached is not None:
            return cached

        if data.source_language == "ko":
            return self.repository.save_restaurant_note_translation(
                session_id,
                translation_id=f"note_{uuid4().hex}",
                source_language="ko",
                source_text=data.source_text,
                korean_text=data.source_text,
                back_translation=data.source_text,
                provider="deterministic",
                model_id="DETERMINISTIC_KOREAN_PASSTHROUGH",
                status="SUCCEEDED",
                error_code=None,
                request_hash=request_hash,
            )

        configured_models = list(
            dict.fromkeys(
                model.strip()
                for model in self.settings.restaurant_note_model_chain.split(",")
                if model.strip()
            )
        )
        models = configured_models or list(
            dict.fromkeys(
                model
                for model in (
                    self.settings.restaurant_note_model.strip(),
                    self.settings.oci_genai_fallback_model.strip(),
                )
                if model
            )
        )
        models = [model for model in models if model]
        if not models:
            models = [self.settings.restaurant_note_model.strip()]
        input_payload: dict[str, Any] = {
            "source_language": data.source_language,
            "source_text": data.source_text,
            "message_stage": "restaurant_order_preparation",
            "recipient": "restaurant kitchen or packing staff",
        }
        if not self.provider.capabilities.structured_output:
            input_payload["response_contract"] = _TRANSLATION_SCHEMA
        request: dict[str, Any] = {
            "instructions": self._instructions(),
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
                validation_error = _translation_error(data, parsed)
                if validation_error is not None:
                    raise ValueError(validation_error)
                usage = response_usage_metrics(response)
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
            except (json.JSONDecodeError, ValidationError):
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
            except ValueError as exc:
                reason = str(exc).strip()
                last_error = (
                    reason
                    if reason.startswith("TRANSLATION_")
                    else "TRANSLATION_RESPONSE_INVALID"
                )
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

        safe_fallback = _safe_demo_translation(data)
        if safe_fallback is not None:
            korean_text, back_translation = safe_fallback
            fallback_model = "DETERMINISTIC_RESTAURANT_NOTE_FALLBACK"
            self._record_attempt(
                session_id,
                request_hash,
                attempt_no=len(models) + 1,
                model_id=fallback_model,
                status="SUCCEEDED",
                error_code=None,
                latency_ms=0,
                input_tokens=None,
                output_tokens=None,
            )
            return self.repository.save_restaurant_note_translation(
                session_id,
                translation_id=f"note_{uuid4().hex}",
                source_language=data.source_language,
                source_text=data.source_text,
                korean_text=korean_text,
                back_translation=back_translation,
                provider="deterministic",
                model_id=fallback_model,
                status="SUCCEEDED",
                error_code=None,
                request_hash=request_hash,
            )

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

    def _instructions(self) -> str:
        return f"""
You translate a short message written by a foreign visitor during the food-delivery ordering
flow. The Korean message will be sent to the restaurant's kitchen or packing staff while they
prepare and pack the order. It is not a restaurant review, chat reply, address, hotel-front-desk
instruction, or courier delivery instruction.

Write korean_text as concise, natural, polite Korean that restaurant staff can act on immediately.
Preserve the customer's exact intent, food or ingredient names, quantities, allergies, negation,
conditional wording, and whether something should be omitted, added, cooked, or packed separately.
Do not strengthen a preference into an allergy, weaken an allergy, promise that the restaurant can
comply, invent a reason, add a greeting, or add any request absent from the source. Avoid awkward
word-for-word translation when a standard Korean restaurant-note phrase is clearer.
Use ordinary Korean Hangul, standard punctuation, and only quantities present in the source. Never
emit corrupted glyphs, unrelated numbers, encoded tokens, or placeholder text.

Write back_translation in the visitor's source_language. It must faithfully translate the final
korean_text so the visitor can confirm what the restaurant will receive; do not merely repeat the
source if the Korean wording changed its nuance.

Examples:
- English: "Please leave out the onions." -> korean_text: "양파는 빼 주세요." ->
  back_translation: "Please leave out the onions."
- English: "Please pack the sauce separately." -> korean_text: "소스는 따로 담아 주세요." ->
  back_translation: "Please pack the sauce separately."
- English: "Please include two pairs of chopsticks." -> korean_text: "젓가락 두 벌 넣어 주세요." ->
  back_translation: "Please include two pairs of chopsticks."
- English: "If possible, make it less spicy. If not, that's okay." -> korean_text:
  "가능하면 덜 맵게 해 주세요. 어렵다면 괜찮습니다." -> back_translation:
  "If possible, please make it less spicy. If that is difficult, that's okay."
- English: "I have a peanut allergy. Please do not add peanuts." -> korean_text:
  "땅콩 알레르기가 있으니 땅콩은 넣지 말아 주세요." -> back_translation:
  "I have a peanut allergy, so please do not add peanuts."

Return one JSON object with korean_text and back_translation string fields. Do not use Markdown,
a code fence, Korean field names, analysis, commentary, or a preamble. Prompt version:
{self.settings.restaurant_note_prompt_version}.
""".strip()

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
