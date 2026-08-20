from __future__ import annotations

import difflib
import json
import re
from time import monotonic
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator

from app.core.config import Settings
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider
from app.genai.response_contract import parse_json_object


def _bounded_sentences(value: str, *, minimum: int, maximum: int, code: str) -> str:
    parts = [part for part in re.split(r"(?<=[.!?。！？])\s*", value.strip()) if part]
    if len(parts) < minimum:
        raise ValueError(code)
    return " ".join(parts[:maximum]).strip()


def _number_tokens(value: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", value)


_OPTION_CONTROL_RULES = (
    (
        re.compile(r"선택"),
        re.compile(r"(?i)select|choice|option|choose|none|add"),
        re.compile(r"選択|オプション|なし|追加"),
    ),
    (re.compile(r"추가"), re.compile(r"(?i)add|extra|additional"), re.compile(r"追加")),
    (
        re.compile(r"제외|빼"),
        re.compile(r"(?i)remove|exclude|without|no\s"),
        re.compile(r"除外|抜き|なし"),
    ),
    (
        re.compile(r"비조리"),
        re.compile(r"(?i)uncooked|not cooked|unprepared"),
        re.compile(r"未調理|非加熱"),
    ),
    (re.compile(r"조리"), re.compile(r"(?i)cooked|cooking|prepared"), re.compile(r"調理")),
    (
        re.compile(r"안함|없음|미선택"),
        re.compile(r"(?i)none|no|without|not"),
        re.compile(r"なし|ない|選択しない"),
    ),
)


def _option_control_meaning_preserved(source: str, target: str, language: str) -> bool:
    for source_pattern, english_pattern, japanese_pattern in _OPTION_CONTROL_RULES:
        if source_pattern.search(source):
            target_pattern = japanese_pattern if language == "ja" else english_pattern
            if not target_pattern.search(target):
                return False
    return True


_HANGUL_CHO = (
    "g",
    "kk",
    "n",
    "d",
    "tt",
    "r",
    "m",
    "b",
    "pp",
    "s",
    "ss",
    "",
    "j",
    "jj",
    "ch",
    "k",
    "t",
    "p",
    "h",
)
_HANGUL_JUNG = (
    "a",
    "ae",
    "ya",
    "yae",
    "eo",
    "e",
    "yeo",
    "ye",
    "o",
    "wa",
    "wae",
    "oe",
    "yo",
    "u",
    "wo",
    "we",
    "wi",
    "yu",
    "eu",
    "ui",
    "i",
)
_HANGUL_JONG = (
    "",
    "k",
    "k",
    "ks",
    "n",
    "nj",
    "nh",
    "t",
    "l",
    "lk",
    "lm",
    "lp",
    "ls",
    "lt",
    "lp",
    "lh",
    "m",
    "p",
    "ps",
    "t",
    "t",
    "ng",
    "t",
    "t",
    "k",
    "t",
    "p",
    "h",
)


def _romanize_for_quality_check(value: str) -> str:
    result: list[str] = []
    for character in value:
        code = ord(character) - 0xAC00
        if 0 <= code < 11172:
            result.extend(
                (
                    _HANGUL_CHO[code // 588],
                    _HANGUL_JUNG[(code % 588) // 28],
                    _HANGUL_JONG[code % 28],
                )
            )
        elif character.isascii() and character.isalnum():
            result.append(character.casefold())
    return "".join(result)


def _looks_like_english_phonetic_copy(source: str, target: str) -> bool:
    if len(re.findall(r"[가-힣]", source)) < 8:
        return False
    latin = "".join(character for character in target.casefold() if "a" <= character <= "z")
    if not latin:
        return False
    return difflib.SequenceMatcher(None, _romanize_for_quality_check(source), latin).ratio() >= 0.7


class GeneratedOptionLocalization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=300)


class GeneratedMenuPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    menu_id: str = Field(min_length=1, max_length=160)
    localized_title: str = Field(min_length=1, max_length=300)
    localized_subtitle: str = Field(min_length=1, max_length=500)
    localized_source_description: str = Field(max_length=4000)
    yobi_short_explanation: str = Field(min_length=1, max_length=1000)
    yobi_long_explanation: str = Field(min_length=1, max_length=3000)
    review_summary: str = Field(min_length=1, max_length=1500)
    used_evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    used_source_fields: list[str] = Field(min_length=1, max_length=20)
    personalization_applied: bool = False
    covered_component_ids: list[str] = Field(default_factory=list, max_length=40)
    option_group_localizations: list[GeneratedOptionLocalization] = Field(
        default_factory=list, max_length=100
    )
    option_item_localizations: list[GeneratedOptionLocalization] = Field(
        default_factory=list, max_length=500
    )

    @field_validator("yobi_short_explanation")
    @classmethod
    def validate_short(cls, value: str) -> str:
        return _bounded_sentences(
            value,
            minimum=1,
            maximum=2,
            code="PRESENTATION_SHORT_SENTENCE_COUNT_INVALID",
        )

    @field_validator("yobi_long_explanation")
    @classmethod
    def validate_long(cls, value: str) -> str:
        return _bounded_sentences(
            value,
            minimum=3,
            maximum=5,
            code="PRESENTATION_LONG_SENTENCE_COUNT_INVALID",
        )

    @field_validator("review_summary")
    @classmethod
    def validate_reviews(cls, value: str) -> str:
        return _bounded_sentences(
            value,
            minimum=2,
            maximum=3,
            code="PRESENTATION_REVIEW_SENTENCE_COUNT_INVALID",
        )


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
                    "localized_title",
                    "localized_subtitle",
                    "localized_source_description",
                    "yobi_short_explanation",
                    "yobi_long_explanation",
                    "review_summary",
                    "used_evidence_ids",
                    "used_source_fields",
                    "personalization_applied",
                    "covered_component_ids",
                    "option_group_localizations",
                    "option_item_localizations",
                ],
                "properties": {
                    "menu_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "localized_title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 300,
                    },
                    "localized_subtitle": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "localized_source_description": {
                        "type": "string",
                        "maxLength": 4000,
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
                    "covered_component_ids": {
                        "type": "array",
                        "maxItems": 40,
                        "items": {"type": "string"},
                    },
                    "option_group_localizations": {
                        "type": "array",
                        "maxItems": 100,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["object_id", "display_name"],
                            "properties": {
                                "object_id": {"type": "string", "minLength": 1},
                                "display_name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 300,
                                },
                            },
                        },
                    },
                    "option_item_localizations": {
                        "type": "array",
                        "maxItems": 500,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["object_id", "display_name"],
                            "properties": {
                                "object_id": {"type": "string", "minLength": 1},
                                "display_name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 300,
                                },
                            },
                        },
                    },
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

        input_payload: dict[str, Any] = {"menus": items}
        if not self.provider.capabilities.structured_output:
            input_payload["response_contract"] = MENU_PRESENTATION_JSON_SCHEMA
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
                self.settings.menu_presentation_max_output_tokens,
                self.provider.capabilities.max_output_tokens,
            ),
        }
        if self.provider.capabilities.structured_output:
            request["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "yobi_grounded_menu_presentation_v3",
                    "schema": MENU_PRESENTATION_JSON_SCHEMA,
                    "strict": True,
                }
            }

        expected = {str(item["menu_id"]): item for item in items}
        response: Any | None = None
        selected_model = primary
        selected_attempt_no = 0
        selected_started = monotonic()
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
            selected_attempt_no = attempt_no
            selected_started = started
            break
        if response is None:
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
        try:
            result = MenuPresentationGeneration.model_validate(
                parse_json_object(str(getattr(response, "output_text", "")))
            )
            returned_ids = [item.menu_id for item in result.items]
            if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != set(expected):
                raise ValueError("PRESENTATION_MENU_SET_INVALID")
            for generated in result.items:
                source = expected[generated.menu_id]
                target_language = {
                    "한국어": "ko",
                    "日本語": "ja",
                }.get(locale, "en")
                group_sources = {
                    str(group["option_group_id"]): str(group["name_ko"])
                    for group in source.get("menu_options", [])
                }
                item_sources = {
                    str(option["option_item_id"]): str(option["name_ko"])
                    for group in source.get("menu_options", [])
                    for option in group.get("items", [])
                }
                generated_groups = {
                    value.object_id: value.display_name
                    for value in generated.option_group_localizations
                }
                generated_items = {
                    value.object_id: value.display_name
                    for value in generated.option_item_localizations
                }
                if set(generated_groups) != set(group_sources):
                    raise ValueError("PRESENTATION_OPTION_GROUP_SET_INVALID")
                if set(generated_items) != set(item_sources):
                    raise ValueError("PRESENTATION_OPTION_ITEM_SET_INVALID")
                if len(generated.option_group_localizations) != len(generated_groups):
                    raise ValueError("PRESENTATION_OPTION_GROUP_DUPLICATE")
                if len(generated.option_item_localizations) != len(generated_items):
                    raise ValueError("PRESENTATION_OPTION_ITEM_DUPLICATE")
                source_description = str(source.get("source_description_ko") or "")
                if bool(source_description) != bool(generated.localized_source_description):
                    raise ValueError("PRESENTATION_SOURCE_DESCRIPTION_PRESENCE_INVALID")
                if target_language == "en" and _looks_like_english_phonetic_copy(
                    source_description, generated.localized_source_description
                ):
                    raise ValueError("PRESENTATION_SOURCE_DESCRIPTION_PHONETIC_COPY")
                translated_pairs = [
                    (str(source["menu_title_ko"]), generated.localized_title),
                    (
                        str(source.get("source_description_ko") or ""),
                        generated.localized_source_description,
                    ),
                    *[(group_sources[key], generated_groups[key]) for key in group_sources],
                    *[(item_sources[key], generated_items[key]) for key in item_sources],
                ]
                for source_text, translated_text in translated_pairs:
                    if _number_tokens(source_text) != _number_tokens(translated_text):
                        raise ValueError("PRESENTATION_TRANSLATION_NUMBER_MISMATCH")
                    if target_language == "ko" and translated_text != source_text:
                        raise ValueError("PRESENTATION_KOREAN_SOURCE_CHANGED")
                    if target_language != "ko" and re.search(r"[가-힣]", translated_text):
                        raise ValueError("PRESENTATION_TRANSLATION_HANGUL_REMAINS")
                if target_language != "ko" and any(
                    not _option_control_meaning_preserved(source_text, target_text, target_language)
                    for source_text, target_text in (
                        *[(group_sources[key], generated_groups[key]) for key in group_sources],
                        *[(item_sources[key], generated_items[key]) for key in item_sources],
                    )
                ):
                    raise ValueError("PRESENTATION_OPTION_CONTROL_MEANING_LOST")
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
                generated.used_evidence_ids = [
                    evidence_id
                    for evidence_id in generated.used_evidence_ids
                    if evidence_id in allowed_evidence
                ]
                allowed_fields = {
                    "menu_title_ko",
                    "localized_title",
                    "source_description_ko",
                    "localized_source_description",
                    "wiki_passages",
                    "menu_facts",
                    "synthetic_reviews",
                    "country_preference",
                    "menu_components",
                    "menu_options",
                }
                generated.used_source_fields = [
                    field for field in generated.used_source_fields if field in allowed_fields
                ]
                required_source_fields = {"menu_title_ko"}
                if source.get("source_description_ko"):
                    required_source_fields.add("source_description_ko")
                if source.get("menu_options"):
                    required_source_fields.add("menu_options")
                generated.used_source_fields = sorted(
                    set(generated.used_source_fields) | required_source_fields
                )
                required_components = {
                    str(component.get("component_id"))
                    for component in source.get("menu_components", [])
                    if isinstance(component, dict) and component.get("component_id")
                }
                if set(generated.covered_component_ids) != required_components:
                    raise ValueError("PRESENTATION_COMPONENT_COVERAGE_INVALID")
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            reason_code = self._validation_reason(exc)
            if on_provider_attempt is not None:
                on_provider_attempt(
                    selected_attempt_no,
                    selected_model,
                    "FAILED",
                    f"{GenAIErrorCode.GROUNDING_REJECTED.value}:{reason_code}",
                    int((monotonic() - selected_started) * 1000),
                    self._usage(response),
                )
            raise GenAIProviderError(
                GenAIErrorCode.GROUNDING_REJECTED,
                retryable=False,
                cause=exc,
                safe_reason_code=reason_code,
                safe_reason_stage="PRESENTATION_VALIDATION",
            ) from exc
        if on_provider_attempt is not None:
            on_provider_attempt(
                selected_attempt_no,
                selected_model,
                "SUCCEEDED",
                None,
                int((monotonic() - selected_started) * 1000),
                self._usage(response),
            )
        result._generation_model = selected_model
        result._provider_metrics = self._usage(response)
        return result

    @staticmethod
    def _validation_reason(exc: BaseException) -> str:
        if isinstance(exc, json.JSONDecodeError):
            return "PRESENTATION_JSON_INVALID"
        if isinstance(exc, ValidationError):
            errors = exc.errors(include_url=False)
            if not errors:
                return "PRESENTATION_SCHEMA_INVALID"
            first = errors[0]
            context = first.get("ctx") or {}
            validator_error = str(context.get("error") or "")
            match = re.search(r"PRESENTATION_[A-Z0-9_]+", validator_error)
            if match is not None:
                return match.group(0)[:100]
            error_type = str(first.get("type") or "SCHEMA_INVALID").upper()
            return f"PRESENTATION_SCHEMA_{error_type}"[:100]
        value = str(exc).strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,99}", value):
            return value
        return "PRESENTATION_VALIDATION_FAILED"

    def _instructions(self, locale: str) -> str:
        return f"""
You write YOBI menu presentation copy after another model has already selected the menus. Return
one JSON object matching the supplied schema, in {locale}, with every requested menu_id exactly
once. Never select, remove, add, reorder, or rank menus.

Translate and write each field according to its display purpose:

- localized_title is identity copy. Translate the Korean listing title faithfully and compactly.
  Preserve brands, quantities, set composition, ingredient names, spice labels, and preparation
  words. Do not summarize or add marketing language. Romanize only an established Korean dish or
  brand name that genuinely has no natural translation; translate all ordinary Korean words by
  meaning. Never turn an entire sentence or option into phonetic Korean written in Latin letters.
- localized_subtitle is explanatory copy. Paraphrase the actual menu composition in one short,
  foreign-visitor-friendly phrase. It may explain an unfamiliar term such as nakji as small
  octopus when the title or restaurant description supports that meaning, but must add no facts.
- localized_source_description is a natural translation of the YOGIYO restaurant description.
  Preserve its promotional tone, sentence meaning, quantities, cautions, and uncertainty, but do
  not transliterate ordinary prose, summarize it, or introduce claims. Return an empty string when
  the Korean source description is empty.
- option_group_localizations and option_item_localizations are order-control copy, not creative
  copy. Translate literally enough that selecting the option produces the same order. Preserve
  every object_id, number, unit, size, inclusion/removal, negation, required/optional implication,
  doneness, spice level, and extra-charge meaning. Prefer natural target-language menu wording,
  but never paraphrase away an operational distinction. Brand names may stay as brands.

Prefer explicit ingredients in the menu title and restaurant description over a generic Wiki
family description. Use Wiki passages to understand the general dish, not to overwrite this
listing. Use only supplied fields; never invent ingredients, taste, preparation, certification,
popularity, or restaurant practices.

For a compound menu, explain every item in menu_components and return every supplied component_id
exactly once in covered_component_ids. Never let one component's temperature, form, ingredient,
or cooking method describe another component.

Write yobi_short_explanation in one or two short sentences, yobi_long_explanation in three to five
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
