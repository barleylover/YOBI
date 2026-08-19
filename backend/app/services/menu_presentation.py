from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import Settings
from app.db.repository import YobiRepository
from app.domain.models import (
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
)
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider


def _sentence_count(value: str) -> int:
    parts = [part for part in re.split(r"(?<=[.!?。！？])\s*", value.strip()) if part]
    return max(1, len(parts))


class _GeneratedPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    menu_id: str = Field(min_length=1, max_length=160)
    yobi_short_explanation: str = Field(min_length=1, max_length=1000)
    yobi_long_explanation: str = Field(min_length=1, max_length=3000)
    review_summary: str = Field(min_length=1, max_length=1500)

    @field_validator("yobi_short_explanation")
    @classmethod
    def validate_short_length(cls, value: str) -> str:
        if not 1 <= _sentence_count(value) <= 2:
            raise ValueError("short explanation must contain one or two sentences")
        return value.strip()

    @field_validator("yobi_long_explanation")
    @classmethod
    def validate_long_length(cls, value: str) -> str:
        if not 3 <= _sentence_count(value) <= 5:
            raise ValueError("long explanation must contain three to five sentences")
        return value.strip()

    @field_validator("review_summary")
    @classmethod
    def validate_review_length(cls, value: str) -> str:
        if not 2 <= _sentence_count(value) <= 3:
            raise ValueError("review summary must contain two or three sentences")
        return value.strip()


class _PresentationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[_GeneratedPresentation] = Field(min_length=1, max_length=12)


_PRESENTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "menu_id": {"type": "string", "minLength": 1, "maxLength": 160},
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
                },
                "required": [
                    "menu_id",
                    "yobi_short_explanation",
                    "yobi_long_explanation",
                    "review_summary",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


class MenuPresentationService:
    """Generate and cache bounded, Wiki-grounded copy for merchant menu pages."""

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

    def list_presentations(
        self,
        session_id: str,
        merchant_id: str,
        request: MerchantMenuPresentationRequest,
    ) -> MerchantMenuPresentationPage:
        page = self.repository.list_merchant_menu_presentations(
            session_id, merchant_id, request
        )
        uncached = [
            item
            for item in page.items
            if item.generation_model == "DETERMINISTIC_WIKI_FALLBACK"
        ]
        if not uncached or not self.provider.configured:
            return page

        models = [self.settings.menu_localization_model]
        fallback = self.settings.oci_genai_fallback_model.strip()
        if (
            fallback
            and fallback != models[0]
            and self.provider.supports_model(fallback)
        ):
            models.append(fallback)
        if not self.provider.supports_model(models[0]):
            return page

        bounded_input = [
            {
                "menu_id": item.menu.menu_id,
                "localized_title": item.localized_title,
                "wiki_passages": item.yobi_long_explanation,
                "restaurant_source_description_ko": item.source_description,
                "review_snippets": item.review_summary,
                "visitor_country_code": item.country_preference.get("country_code", "US"),
            }
            for item in uncached
        ]
        provider_request: dict[str, Any] = {
            "instructions": (
                "Write visitor-friendly menu explanations in the same language as each localized "
                "title. Use only the supplied Wiki passages, restaurant source description, and "
                "review snippets. Country is only a cue for familiar wording, never a factual "
                "claim or ranking input. Do not invent ingredients, taste, dietary status, origin, "
                "certification, or popularity. Return one or two short sentences for the card, "
                "three to five short sentences for details, and two or three sentences summarizing "
                "only the supplied review snippets. Return every requested menu_id exactly once."
            ),
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(bounded_input, ensure_ascii=False),
                }
            ],
            "max_output_tokens": min(
                self.settings.structured_recommendation_max_output_tokens,
                self.provider.capabilities.max_output_tokens,
            ),
        }
        if self.provider.capabilities.structured_output:
            provider_request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "yobi_menu_presentations_v1",
                    "schema": _PRESENTATION_SCHEMA,
                    "strict": True,
                }
            }

        expected_ids = {item.menu.menu_id for item in uncached}
        generated: _PresentationPayload | None = None
        selected_model = models[0]
        for index, model_id in enumerate(models):
            try:
                response = self.provider.create_response(model_id, **provider_request)
                parsed = _PresentationPayload.model_validate_json(
                    str(getattr(response, "output_text", ""))
                )
                returned_ids = [item.menu_id for item in parsed.items]
                if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != expected_ids:
                    return page
                generated = parsed
                selected_model = model_id
                break
            except GenAIProviderError as exc:
                if exc.code is GenAIErrorCode.RATE_LIMIT and index + 1 < len(models):
                    continue
                return page
            except (ValidationError, ValueError, TypeError):
                return page

        if generated is None:
            return page

        updates = {item.menu_id: item for item in generated.items}
        output_items: list[MerchantMenuPresentation] = []
        for item in page.items:
            generated_item = updates.get(item.menu.menu_id)
            if generated_item is None:
                output_items.append(item)
                continue
            updated = item.model_copy(
                update={
                    "yobi_short_explanation": generated_item.yobi_short_explanation,
                    "yobi_long_explanation": generated_item.yobi_long_explanation,
                    "review_summary": generated_item.review_summary,
                    "generation_model": selected_model,
                }
            )
            self.repository.save_menu_presentation_cache(session_id, updated)
            output_items.append(updated)
        return page.model_copy(update={"items": output_items})
