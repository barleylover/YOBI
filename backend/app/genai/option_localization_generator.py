from __future__ import annotations

import json
import re
from time import monotonic
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from app.core.config import Settings
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.presentation_generator import (
    _number_tokens,
    _option_control_meaning_preserved,
)
from app.genai.providers import choose_genai_provider
from app.genai.response_contract import parse_json_object


class GeneratedOptionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=300)
    item_display_names: list[str] = Field(max_length=500)


class OptionLocalizationGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    _generation_model: str | None = PrivateAttr(default=None)
    _provider_metrics: dict[str, int] = PrivateAttr(default_factory=dict)

    groups: list[GeneratedOptionGroup] = Field(max_length=100)

    @property
    def generation_model(self) -> str | None:
        return self._generation_model

    @property
    def provider_metrics(self) -> dict[str, int]:
        return dict(self._provider_metrics)


OPTION_LOCALIZATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["groups"],
    "properties": {
        "groups": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["display_name", "item_display_names"],
                "properties": {
                    "display_name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 300,
                    },
                    "item_display_names": {
                        "type": "array",
                        "maxItems": 500,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 300,
                        },
                    },
                },
            },
        }
    },
}


class OptionLocalizationGenerator:
    """Translate one selected menu's ordered option labels without model-owned IDs."""

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
        groups: list[dict[str, Any]],
        locale: str,
        on_provider_attempt: (
            Callable[[str, str, str | None, int, dict[str, int]], None] | None
        ) = None,
    ) -> OptionLocalizationGeneration:
        if not groups:
            return OptionLocalizationGeneration(groups=[])
        if len(groups) > 100 or any(len(group.get("items", [])) > 500 for group in groups):
            raise ValueError("OPTION_LOCALIZATION_BATCH_SIZE_INVALID")
        model_id = self.settings.option_localization_model.strip()
        if (
            not self.provider.configured
            or not model_id
            or not self.provider.supports_model(model_id)
        ):
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)

        input_payload: dict[str, Any] = {"groups": groups}
        if not self.provider.capabilities.structured_output:
            input_payload["response_contract"] = OPTION_LOCALIZATION_JSON_SCHEMA
        request: dict[str, Any] = {
            "instructions": self._instructions(locale),
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(
                        input_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            ],
            "max_output_tokens": min(
                self.settings.option_localization_max_output_tokens,
                self.provider.capabilities.max_output_tokens,
            ),
        }
        if self.provider.capabilities.structured_output:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "yobi_selected_menu_option_localization_v1",
                    "schema": OPTION_LOCALIZATION_JSON_SCHEMA,
                    "strict": True,
                }
            }

        started = monotonic()
        try:
            response = self.provider.create_response(model_id, **request)
        except GenAIProviderError as exc:
            if on_provider_attempt is not None:
                on_provider_attempt(
                    model_id,
                    "FAILED",
                    exc.code.value,
                    int((monotonic() - started) * 1000),
                    exc.safe_metadata,
                )
            raise

        usage = self._usage(response)
        try:
            result = OptionLocalizationGeneration.model_validate(
                parse_json_object(str(getattr(response, "output_text", "")))
            )
            if len(result.groups) != len(groups):
                raise ValueError("OPTION_LOCALIZATION_GROUP_COUNT_INVALID")
            target_language = {"한국어": "ko", "日本語": "ja"}.get(locale, "en")
            for source_group, generated_group in zip(groups, result.groups):
                source_items = list(source_group.get("items", []))
                if len(generated_group.item_display_names) != len(source_items):
                    raise ValueError("OPTION_LOCALIZATION_ITEM_COUNT_INVALID")
                pairs = [
                    (str(source_group["name_ko"]), generated_group.display_name),
                    *[
                        (str(source_item["name_ko"]), translated)
                        for source_item, translated in zip(
                            source_items,
                            generated_group.item_display_names,
                        )
                    ],
                ]
                for source_text, translated_text in pairs:
                    if _number_tokens(source_text) != _number_tokens(translated_text):
                        raise ValueError("OPTION_LOCALIZATION_NUMBER_MISMATCH")
                    if target_language == "ko" and source_text != translated_text:
                        raise ValueError("OPTION_LOCALIZATION_KOREAN_SOURCE_CHANGED")
                    if target_language != "ko" and re.search(r"[가-힣]", translated_text):
                        raise ValueError("OPTION_LOCALIZATION_HANGUL_REMAINS")
                    if target_language != "ko" and not _option_control_meaning_preserved(
                        source_text,
                        translated_text,
                        target_language,
                    ):
                        raise ValueError("OPTION_LOCALIZATION_CONTROL_MEANING_LOST")
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            reason = str(exc).strip() or "OPTION_LOCALIZATION_RESPONSE_INVALID"
            if on_provider_attempt is not None:
                on_provider_attempt(
                    model_id,
                    "FAILED",
                    reason[:120],
                    int((monotonic() - started) * 1000),
                    usage,
                )
            raise GenAIProviderError(
                GenAIErrorCode.GROUNDING_REJECTED,
                retryable=False,
                cause=exc,
                safe_reason_code=reason[:120],
                safe_reason_stage="OPTION_LOCALIZATION_VALIDATION",
            ) from exc

        if on_provider_attempt is not None:
            on_provider_attempt(
                model_id,
                "SUCCEEDED",
                None,
                int((monotonic() - started) * 1000),
                usage,
            )
        result._generation_model = model_id
        result._provider_metrics = usage
        return result

    def _instructions(self, locale: str) -> str:
        return f"""
Translate the ordered restaurant option labels into {locale}. Return exactly one JSON object that
matches the supplied schema. The server owns all option IDs and maps your strings back by position,
so never emit, invent, reorder, merge, or omit an option ID.

Return the same number of groups in the same order. Within each group, return the same number of
item_display_names in the same order. Translate for ordering accuracy, not creativity. Preserve
every Arabic digit sequence exactly, including size, quantity, spice level, doneness, inclusion,
removal, negation, and add-on meaning. Prefer natural menu wording over Korean phonetic spelling
when the meaning is translatable. Brand names may remain brand names. Do not add prices because
the server renders prices separately. Do not return Markdown or commentary. Prompt version:
{self.settings.option_localization_prompt_version}.
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
