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
    _quantity_tokens,
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


_ENGLISH_OPTION_SEMANTIC_RULES = (
    (re.compile(r"우삼겹"), re.compile(r"(?i)\bbeef\b"), re.compile(r"(?i)\bpork\b")),
    (re.compile(r"등심.*돈[까가]스|돈[까가]스.*등심"), re.compile(r"(?i)\bpork\b"), None),
    (
        re.compile(r"버팔로봉"),
        re.compile(r"(?i)\b(?:chicken|drumettes?|wings?)\b"),
        re.compile(r"(?i)\bbuns?\b"),
    ),
    (
        re.compile(r"사이다"),
        re.compile(r"(?i)\b(?:soda|soft drink|sprite)\b"),
        re.compile(r"(?i)\bcider\b"),
    ),
    (
        re.compile(r"찜.*(?:사진|이벤트|[Ee]벤트)|(?:사진|이벤트|[Ee]벤트).*찜"),
        re.compile(r"(?i)\b(?:favou?rite|save|heart)\b"),
        re.compile(r"(?i)\bsteam(?:ed|ing)?\b"),
    ),
    (
        re.compile(r"핫봉"),
        re.compile(r"(?i)\b(?:chicken|drumettes?|wings?)\b"),
        re.compile(r"(?i)\b(?:bons?|buns?)\b"),
    ),
    (
        re.compile(r"라구"),
        re.compile(r"(?i)\bragu\b"),
        re.compile(r"(?i)\brago\b"),
    ),
)


def _option_numbers_are_preserved(
    source: str,
    target: str,
    target_language: str,
) -> bool:
    expected = _number_tokens(source)
    actual = (
        _quantity_tokens(target, "en")
        if target_language == "en"
        else _number_tokens(target)
    )
    if expected == actual:
        return True

    # Korean commerce labels commonly spell out both sides of a one-to-one
    # relation ("1 order당 1 item"). Natural English compresses that safely to
    # "one item per order". The word "per" carries the implicit denominator of
    # one, so requiring the digit twice rejects an exact semantic translation.
    # Keep this exception deliberately narrow: one repeated source quantity,
    # one matching target quantity, and an explicit per-unit relation.
    return (
        target_language == "en"
        and len(expected) == 2
        and expected[0] == expected[1]
        and actual == [expected[0]]
        and re.search(r"(?i)\b(?:per|each|every)\b", target) is not None
    )


def _option_translation_error(source: str, target: str, target_language: str) -> str | None:
    if not _option_numbers_are_preserved(source, target, target_language):
        return "OPTION_LOCALIZATION_NUMBER_MISMATCH"
    if target_language == "ko" and source != target:
        return "OPTION_LOCALIZATION_KOREAN_SOURCE_CHANGED"
    if target_language != "ko" and re.search(r"[가-힣]", target):
        return "OPTION_LOCALIZATION_HANGUL_REMAINS"
    if target_language != "ko" and not _option_control_meaning_preserved(
        source,
        target,
        target_language,
    ):
        return "OPTION_LOCALIZATION_CONTROL_MEANING_LOST"
    if target_language == "en":
        for source_pattern, required_pattern, forbidden_pattern in _ENGLISH_OPTION_SEMANTIC_RULES:
            if not source_pattern.search(source):
                continue
            if not required_pattern.search(target) or (
                forbidden_pattern is not None and forbidden_pattern.search(target)
            ):
                return "OPTION_LOCALIZATION_SEMANTIC_ANCHOR_LOST"
    return None


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
        models = list(
            dict.fromkeys(
                model.strip()
                for model in self.settings.option_localization_model_chain.split(",")
                if model.strip()
            )
        )
        if not models and self.settings.option_localization_model.strip():
            models = [self.settings.option_localization_model.strip()]
        if not self.provider.configured or not models:
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

        last_error: GenAIProviderError | None = None
        merged_group_names: list[str | None] = [None] * len(groups)
        merged_item_names: list[list[str | None]] = [
            [None] * len(group.get("items", [])) for group in groups
        ]
        contributing_models: list[str] = []
        combined_usage: dict[str, int] = {}
        for model_id in models:
            started = monotonic()
            if not self.provider.supports_model(model_id):
                last_error = GenAIProviderError(
                    GenAIErrorCode.PROVIDER_UNAVAILABLE,
                    retryable=True,
                )
                if on_provider_attempt is not None:
                    on_provider_attempt(model_id, "FAILED", last_error.code.value, 0, {})
                continue
            try:
                response = self.provider.create_response(model_id, **request)
            except GenAIProviderError as exc:
                last_error = exc
                if on_provider_attempt is not None:
                    on_provider_attempt(
                        model_id,
                        "FAILED",
                        exc.code.value,
                        int((monotonic() - started) * 1000),
                        exc.safe_metadata,
                    )
                continue

            usage = self._usage(response)
            for key, value in usage.items():
                combined_usage[key] = combined_usage.get(key, 0) + value
            try:
                result = OptionLocalizationGeneration.model_validate(
                    parse_json_object(str(getattr(response, "output_text", "")))
                )
                if len(result.groups) != len(groups):
                    raise ValueError("OPTION_LOCALIZATION_GROUP_COUNT_INVALID")
                target_language = {"한국어": "ko", "日本語": "ja"}.get(locale, "en")
                validation_errors: list[str] = []
                contributed = False
                for group_index, (source_group, generated_group) in enumerate(
                    zip(groups, result.groups)
                ):
                    source_items = list(source_group.get("items", []))
                    if len(generated_group.item_display_names) != len(source_items):
                        raise ValueError("OPTION_LOCALIZATION_ITEM_COUNT_INVALID")
                    group_error = _option_translation_error(
                        str(source_group["name_ko"]),
                        generated_group.display_name,
                        target_language,
                    )
                    if group_error is None:
                        if merged_group_names[group_index] is None:
                            merged_group_names[group_index] = generated_group.display_name
                            contributed = True
                    else:
                        validation_errors.append(f"{group_error}:G{group_index}")
                    for item_index, (source_item, translated) in enumerate(
                        zip(source_items, generated_group.item_display_names)
                    ):
                        item_error = _option_translation_error(
                            str(source_item["name_ko"]),
                            translated,
                            target_language,
                        )
                        if item_error is None:
                            if merged_item_names[group_index][item_index] is None:
                                merged_item_names[group_index][item_index] = translated
                                contributed = True
                        else:
                            validation_errors.append(
                                f"{item_error}:G{group_index}:I{item_index}"
                            )
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                reason = str(exc).strip() or "OPTION_LOCALIZATION_RESPONSE_INVALID"
                last_error = GenAIProviderError(
                    GenAIErrorCode.GROUNDING_REJECTED,
                    retryable=False,
                    cause=exc,
                    safe_reason_code=reason[:120],
                    safe_reason_stage="OPTION_LOCALIZATION_VALIDATION",
                )
                if on_provider_attempt is not None:
                    on_provider_attempt(
                        model_id,
                        "FAILED",
                        reason[:120],
                        int((monotonic() - started) * 1000),
                        usage,
                    )
                continue

            if contributed:
                contributing_models.append(model_id)
            complete = all(value is not None for value in merged_group_names) and all(
                value is not None for names in merged_item_names for value in names
            )
            if not complete:
                reason = (
                    validation_errors[0]
                    if validation_errors
                    else "OPTION_LOCALIZATION_RESPONSE_INCOMPLETE"
                )
                last_error = GenAIProviderError(
                    GenAIErrorCode.GROUNDING_REJECTED,
                    retryable=False,
                    safe_reason_code=reason[:120],
                    safe_reason_stage="OPTION_LOCALIZATION_VALIDATION",
                )
                if on_provider_attempt is not None:
                    on_provider_attempt(
                        model_id,
                        "FAILED",
                        reason[:120],
                        int((monotonic() - started) * 1000),
                        usage,
                    )
                continue

            result = OptionLocalizationGeneration(
                groups=[
                    GeneratedOptionGroup(
                        display_name=str(merged_group_names[group_index]),
                        item_display_names=[str(value) for value in merged_item_names[group_index]],
                    )
                    for group_index in range(len(groups))
                ]
            )

            if on_provider_attempt is not None:
                on_provider_attempt(
                    model_id,
                    "SUCCEEDED",
                    None,
                    int((monotonic() - started) * 1000),
                    usage,
                )
            result._generation_model = "+".join(dict.fromkeys(contributing_models))
            result._provider_metrics = combined_usage
            return result

        raise last_error or GenAIProviderError(
            GenAIErrorCode.PROVIDER_UNAVAILABLE,
            retryable=False,
        )

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
the server renders prices separately. Keep literal digits when practical; ordinary English number
words are acceptable only when they preserve the same quantity and unit. Translate 우삼겹 as beef
short plate, 등심왕돈까스 as pork loin cutlet, 버팔로봉 as buffalo chicken drumettes, and Korean
사이다 as soda or soft drink, never alcoholic cider. In Yogiyo event labels, 찜 means saving or
favoriting the restaurant, never steaming food. Translate 핫봉 as hot chicken drumettes and 라구 as
ragu. Do not return Markdown or commentary. Prompt version:
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
