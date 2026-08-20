from __future__ import annotations

import json
import re
from time import monotonic
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator

from app.core.config import Settings
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider
from app.genai.response_contract import parse_json_object


def _sentence_count(value: str) -> int:
    parts = [part for part in re.split(r"(?<=[.!?。！？])\s*", value.strip()) if part]
    return max(1, len(parts))


class GeneratedMenuPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    menu_id: str = Field(min_length=1, max_length=160)
    localized_subtitle: str = Field(min_length=1, max_length=500)
    yobi_short_explanation: str = Field(min_length=1, max_length=1000)
    yobi_long_explanation: str = Field(min_length=1, max_length=3000)
    review_summary: str = Field(min_length=1, max_length=1500)
    used_evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    used_source_fields: list[str] = Field(min_length=1, max_length=20)
    personalization_applied: bool = False

    @field_validator("yobi_short_explanation")
    @classmethod
    def validate_short(cls, value: str) -> str:
        if not 1 <= _sentence_count(value) <= 2:
            raise ValueError("PRESENTATION_SHORT_SENTENCE_COUNT_INVALID")
        return value.strip()

    @field_validator("yobi_long_explanation")
    @classmethod
    def validate_long(cls, value: str) -> str:
        if not 4 <= _sentence_count(value) <= 6:
            raise ValueError("PRESENTATION_LONG_SENTENCE_COUNT_INVALID")
        return value.strip()

    @field_validator("review_summary")
    @classmethod
    def validate_reviews(cls, value: str) -> str:
        if not 2 <= _sentence_count(value) <= 3:
            raise ValueError("PRESENTATION_REVIEW_SENTENCE_COUNT_INVALID")
        return value.strip()


class MenuPresentationGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    _generation_model: str | None = PrivateAttr(default=None)
    _provider_metrics: dict[str, int] = PrivateAttr(default_factory=dict)

    items: list[GeneratedMenuPresentation] = Field(min_length=1, max_length=12)

    @property
    def generation_model(self) -> str | None:
        return self._generation_model

    @property
    def provider_metrics(self) -> dict[str, int]:
        return dict(self._provider_metrics)


MENU_PRESENTATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "menu_id",
                    "localized_subtitle",
                    "yobi_short_explanation",
                    "yobi_long_explanation",
                    "review_summary",
                    "used_evidence_ids",
                    "used_source_fields",
                    "personalization_applied",
                ],
                "properties": {
                    "menu_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "localized_subtitle": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "yobi_short_explanation": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
                    },
                    "yobi_long_explanation": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 3000,
                    },
                    "review_summary": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1500,
                    },
                    "used_evidence_ids": {
                        "type": "array",
                        "maxItems": 40,
                        "items": {"type": "string"},
                    },
                    "used_source_fields": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "personalization_applied": {"type": "boolean"},
                },
            },
        }
    },
}


class MenuPresentationGenerator:
    """Generate grounded display copy only after the selection model chooses menus."""

    def __init__(
        self,
        settings: Settings,
        provider: GenAIProvider | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider or choose_genai_provider(settings)

    @property
    def configured(self) -> bool:
        return self.provider.configured

    def generate(
        self,
        *,
        items: list[dict[str, Any]],
        locale: str,
        on_provider_attempt: (
            Callable[[int, str, str, str | None, int, dict[str, int]], None] | None
        ) = None,
    ) -> MenuPresentationGeneration:
        if not 1 <= len(items) <= 12:
            raise ValueError("PRESENTATION_BATCH_SIZE_INVALID")
        primary = self.settings.menu_localization_model.strip()
        fallback = self.settings.oci_genai_fallback_model.strip()
        models = [primary]
        if fallback and fallback != primary and self.provider.supports_model(fallback):
            models.append(fallback)
        if not self.provider.configured or not primary or not self.provider.supports_model(primary):
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)

        request: dict[str, Any] = {
            "instructions": self._instructions(locale),
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "menus": items,
                            "response_contract": MENU_PRESENTATION_JSON_SCHEMA,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            ],
            "max_output_tokens": min(
                self.settings.structured_recommendation_max_output_tokens,
                self.provider.capabilities.max_output_tokens,
            ),
        }
        if self.provider.capabilities.structured_output:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "yobi_grounded_menu_presentation_v2",
                    "schema": MENU_PRESENTATION_JSON_SCHEMA,
                    "strict": True,
                }
            }

        expected = {str(item["menu_id"]): item for item in items}
        response: Any | None = None
        selected_model = primary
        for attempt_no, model_id in enumerate(models, start=1):
            started = monotonic()
            try:
                response = self.provider.create_response(model_id, **request)
            except GenAIProviderError as exc:
                if on_provider_attempt is not None:
                    on_provider_attempt(
                        attempt_no,
                        model_id,
                        "FAILED",
                        exc.code.value,
                        int((monotonic() - started) * 1000),
                        exc.safe_metadata,
                    )
                if exc.code is GenAIErrorCode.RATE_LIMIT and attempt_no < len(models):
                    continue
                raise
            selected_model = model_id
            if on_provider_attempt is not None:
                on_provider_attempt(
                    attempt_no,
                    model_id,
                    "SUCCEEDED",
                    None,
                    int((monotonic() - started) * 1000),
                    self._usage(response),
                )
            break
        if response is None:
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
        try:
            result = MenuPresentationGeneration.model_validate(
                parse_json_object(str(getattr(response, "output_text", "")))
            )
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise GenAIProviderError(
                GenAIErrorCode.GROUNDING_REJECTED,
                retryable=False,
                cause=exc,
            ) from exc
        returned_ids = [item.menu_id for item in result.items]
        if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != set(expected):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        for generated in result.items:
            source = expected[generated.menu_id]
            allowed_evidence = {
                str(item.get("evidence_id"))
                for field in ("wiki_passages", "menu_facts")
                for item in source.get(field, [])
                if isinstance(item, dict) and item.get("evidence_id")
            }
            allowed_evidence.update(
                str(item.get("review_id"))
                for item in source.get("synthetic_reviews", [])
                if isinstance(item, dict) and item.get("review_id")
            )
            if not set(generated.used_evidence_ids) <= allowed_evidence:
                raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
            allowed_fields = {
                "menu_title_ko",
                "localized_title",
                "source_description_ko",
                "localized_source_description",
                "wiki_passages",
                "menu_facts",
                "synthetic_reviews",
                "country_preference",
            }
            if not set(generated.used_source_fields) <= allowed_fields:
                raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        result._generation_model = selected_model
        result._provider_metrics = self._usage(response)
        return result

    def _instructions(self, locale: str) -> str:
        return f"""
You write YOBI menu presentation copy after another model has already selected the menus. Return
one JSON object matching the supplied schema, in {locale}, with every requested menu_id exactly
once. Never select, remove, add, reorder, or rank menus.

The localized_title is fixed identity data and is not part of your output. Write a short
localized_subtitle that explains the actual menu composition in familiar language. Explain
unfamiliar Korean terms such as Nakji only when the Korean title or restaurant description
supports the meaning. Prefer explicit ingredients in the menu title and restaurant description
over a generic Wiki family description. Use Wiki passages to understand the general dish, not to
overwrite this listing. Use only supplied fields; never invent ingredients, taste, preparation,
certification, popularity, or restaurant practices.

Write yobi_short_explanation in one or two short sentences, yobi_long_explanation in four to six
short sentences, and review_summary in two or three sentences based only on synthetic_reviews.
Country and language may guide familiar wording or a clearly grounded analogy, but never force a
country mention, stereotype a nationality, or invent a similar food. Set personalization_applied
true only when the country cue materially changed wording. Cite only supplied evidence/review IDs
and list every source field actually used. Do not expose internal IDs in prose, emit Markdown, or
add a preamble. Prompt version: {self.settings.menu_presentation_prompt_version}.
""".strip()

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
