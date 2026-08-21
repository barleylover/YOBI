from __future__ import annotations

import difflib
import json
import re
import unicodedata
from time import monotonic
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError

from app.core.config import Settings
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider
from app.genai.response_contract import parse_json_object

_ENGLISH_QUANTITY_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}
_ENGLISH_QUANTITY_UNIT_PATTERN = re.compile(
    r"(?i)\b(" + "|".join(_ENGLISH_QUANTITY_WORDS) + r")\b(?=[\s-]*(?:"
    r"servings?|portions?|pieces?|items?|bottles?|cans?|cups?|packs?|sets?|"
    r"spices?|seasonings?|varieties?|types?|kinds?|ml|g|kg)\b)"
)


def _number_tokens(value: str) -> list[str]:
    """Return literal numeric tokens for option-label identity validation."""

    return re.findall(r"\d+(?:[.,]\d+)?", value)


def _quantity_tokens(value: str, target_language: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value)
    tokens = _number_tokens(normalized)
    if target_language == "en":
        tokens.extend(
            _ENGLISH_QUANTITY_WORDS[match.group(1).casefold()]
            for match in _ENGLISH_QUANTITY_UNIT_PATTERN.finditer(normalized)
        )
    return tokens


def _ascii_source_tokens(value: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z][A-Za-z0-9.-]{1,}", value)}


def _contains_hangul(value: str) -> bool:
    return bool(re.search(r"[가-힣]", value))


def _contains_japanese_script(value: str) -> bool:
    return bool(re.search(r"[ぁ-ゖァ-ヺ一-龯々]", value))


def _normalized_text(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣ぁ-ゖァ-ヺ一-龯々]+", "", value.casefold())


_ENGLISH_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "combo",
    "for",
    "from",
    "large",
    "medium",
    "menu",
    "of",
    "original",
    "set",
    "small",
    "special",
    "the",
    "with",
}

_ENGLISH_TITLE_TOKEN_ALIASES: dict[str, set[str]] = {
    "aglio": {"garlic"},
    "olio": {"oil", "olive"},
    "slightly": {"gentle", "light", "mild"},
    "spicy": {"chili", "chilli", "heat", "hot", "spice"},
}

_REVIEW_SIGNAL_PATTERN = re.compile(
    r"(?i)(?:\breview(?:er|ers|s)?\b|\bdiner(?:s)?\b|\bcustomer(?:s)?\b|"
    r"\brating(?:s)?\b|\bfeedback\b|\bstrong marks\b|\bpositive comments\b|"
    r"\bpeople (?:said|noted|mentioned|praised|found)\b|"
    r"리뷰|후기|평점|손님|고객(?:이|들이)?\s*(?:말|평가|언급|칭찬)|"
    r"レビュー|口コミ|評価|客(?:が|から).*(?:声|評価|好評))"
)


def _contains_review_signal(value: str) -> bool:
    return bool(_REVIEW_SIGNAL_PATTERN.search(value))


def _english_title_tokens(value: str) -> set[str]:
    without_brands = re.sub(r"\[[^\]]*\]|\([^)]*(?:store|branch|restaurant)[^)]*\)", " ", value)
    tokens: set[str] = set()
    for token in re.findall(r"[A-Za-z]{3,}", without_brands.casefold()):
        if token in _ENGLISH_TITLE_STOPWORDS:
            continue
        if token.endswith("ies") and len(token) > 4:
            token = f"{token[:-3]}y"
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 3:
            token = token[:-1]
        tokens.add(token)
    return tokens


def _english_title_coverage_is_sufficient(title: str, explanation: str) -> bool:
    required = _english_title_tokens(title)
    if not required:
        return True
    actual = _english_title_tokens(explanation)
    # The server already renders the immutable localized title. Presentation
    # prose must retain the core listing identity, but natural explanations may
    # translate foreign culinary terms (aglio -> garlic) or omit a cuisine
    # adjective (Italian cheese pizza -> cheese pizza). Requiring an exact 75%
    # token echo rejected grounded copy without adding safety. Half coverage
    # still rejects generic family prose that drops specific ingredients.
    minimum = max(1, (len(required) + 1) // 2)
    matched = sum(
        token in actual or bool(_ENGLISH_TITLE_TOKEN_ALIASES.get(token, set()) & actual)
        for token in required
    )
    return matched >= minimum


_OPTION_CONTROL_RULES = (
    (re.compile(r"추가"), re.compile(r"(?i)add|extra|additional"), re.compile(r"追加")),
    (
        # `곱빼기` means a large/double serving. A bare `빼` substring rule
        # misclassified it as the verb "remove" and rejected correct model
        # translations such as "Large serving".
        re.compile(r"제외|(?<!곱)빼"),
        re.compile(r"(?i)remove|exclude|without|no\s"),
        re.compile(r"除外|抜き|なし"),
    ),
    (
        re.compile(r"비조리"),
        re.compile(r"(?i)uncooked|not cooked|unprepared"),
        re.compile(r"未調理|非加熱"),
    ),
    (
        re.compile(r"(?<![비미])조리"),
        re.compile(r"(?i)cooked|cooking|prepared"),
        re.compile(r"調理"),
    ),
    (
        re.compile(r"안함|없음|미선택"),
        re.compile(r"(?i)none|no|without|not|skip"),
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


def _looks_like_japanese_phonetic_copy(source: str, target: str) -> bool:
    """Reject old all-katakana Korean transliterations masquerading as translations."""

    if len(re.findall(r"[가-힣]", source)) < 8:
        return False
    japanese = re.findall(r"[ぁ-ヿ一-龯]", target)
    if len(japanese) < 8:
        return False
    katakana = len(re.findall(r"[ァ-ヿ]", target))
    hiragana = len(re.findall(r"[ぁ-ゟ]", target))
    kanji = len(re.findall(r"[一-龯]", target))
    return katakana / len(japanese) >= 0.7 and hiragana <= 1 and kanji <= 1


def source_translation_is_safe(source: str, target: str, language: str) -> bool:
    """Validate a reusable restaurant-description translation without an LLM call."""

    source = source.strip()
    target = target.strip()
    if not source or not target:
        return False
    if language == "ko":
        return target == source
    if _contains_hangul(target):
        return False
    if language == "en":
        return not _looks_like_english_phonetic_copy(source, target)
    if language == "ja":
        return _contains_japanese_script(target) and not _looks_like_japanese_phonetic_copy(
            source, target
        )
    return False


class GeneratedOptionLocalization(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=1, max_length=160)
    display_name: str = Field(min_length=1, max_length=300)


class GeneratedComponentMention(BaseModel):
    model_config = ConfigDict(extra="ignore")

    component_id: str = Field(min_length=1, max_length=160)
    mention_text: str = Field(min_length=2, max_length=300)


class GeneratedMenuPresentation(BaseModel):
    # OCI raw-JSON models occasionally add harmless bookkeeping keys even when
    # instructed not to. Only the declared fields are consumed by the server.
    model_config = ConfigDict(extra="ignore")

    menu_id: str = Field(min_length=1, max_length=160)
    localized_title: str = Field(min_length=1, max_length=300)
    # Raw-JSON providers can occasionally omit a non-identity field. The
    # service replaces an empty field with server-grounded deterministic copy,
    # so a missing subtitle must not discard the rest of a valid menu item.
    localized_subtitle: str = Field(default="", max_length=500)
    localized_source_description: str = Field(default="", max_length=4000)
    yobi_short_explanation: str = Field(default="", max_length=1000)
    yobi_long_explanation: str = Field(default="", max_length=3000)
    review_summary: str = Field(default="", max_length=1500)
    used_evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    used_source_fields: list[str] = Field(default_factory=list, max_length=20)
    yobi_used_evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    review_used_ids: list[str] = Field(default_factory=list, max_length=40)
    yobi_used_source_fields: list[str] = Field(default_factory=list, max_length=20)
    review_used_source_fields: list[str] = Field(default_factory=list, max_length=20)
    personalization_applied: bool = False
    covered_component_ids: list[str] = Field(default_factory=list, max_length=40)
    component_mentions: list[GeneratedComponentMention] = Field(default_factory=list, max_length=40)
    option_group_localizations: list[GeneratedOptionLocalization] = Field(
        default_factory=list, max_length=100
    )
    option_item_localizations: list[GeneratedOptionLocalization] = Field(
        default_factory=list, max_length=500
    )


class MenuPresentationGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    _generation_model: str | None = PrivateAttr(default=None)
    _provider_metrics: dict[str, int] = PrivateAttr(default_factory=dict)
    _item_errors: dict[str, str] = PrivateAttr(default_factory=dict)
    _field_fallbacks: dict[str, list[str]] = PrivateAttr(default_factory=dict)

    items: list[GeneratedMenuPresentation] = Field(min_length=1, max_length=12)

    @property
    def generation_model(self) -> str | None:
        return self._generation_model

    @property
    def provider_metrics(self) -> dict[str, int]:
        return dict(self._provider_metrics)

    @property
    def item_errors(self) -> dict[str, str]:
        return dict(self._item_errors)

    @property
    def field_fallbacks(self) -> dict[str, list[str]]:
        return {menu_id: list(fields) for menu_id, fields in self._field_fallbacks.items()}


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
                    "yobi_used_evidence_ids",
                    "review_used_ids",
                    "yobi_used_source_fields",
                    "review_used_source_fields",
                    "personalization_applied",
                    "covered_component_ids",
                    "component_mentions",
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
                    "yobi_used_evidence_ids": {
                        "type": "array",
                        "maxItems": 40,
                        "items": {"type": "string"},
                    },
                    "review_used_ids": {
                        "type": "array",
                        "maxItems": 40,
                        "items": {"type": "string"},
                    },
                    "yobi_used_source_fields": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "review_used_source_fields": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "personalization_applied": {"type": "boolean"},
                    "covered_component_ids": {
                        "type": "array",
                        "maxItems": 40,
                        "items": {"type": "string"},
                    },
                    "component_mentions": {
                        "type": "array",
                        "maxItems": 40,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["component_id", "mention_text"],
                            "properties": {
                                "component_id": {"type": "string", "minLength": 1},
                                "mention_text": {
                                    "type": "string",
                                    "minLength": 2,
                                    "maxLength": 300,
                                },
                            },
                        },
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
        primary = self.settings.menu_presentation_model.strip()
        models = [primary]
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
                    "name": "yobi_grounded_menu_presentation_v6",
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
            raw_result = parse_json_object(str(getattr(response, "output_text", "")))
            raw_items = raw_result.get("items")
            if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 12:
                raise ValueError("PRESENTATION_SCHEMA_INVALID")
            item_errors: dict[str, str] = {}
            field_fallbacks: dict[str, list[str]] = {}
            generated_by_id: dict[str, GeneratedMenuPresentation] = {}
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                menu_id = str(raw_item.get("menu_id") or "")
                # Menu identity is server-owned. Unknown rows and duplicate
                # attempts are harmless when at least one valid row exists for
                # a requested menu, so discard them instead of losing the rest
                # of a useful Grok batch.
                if menu_id not in expected or menu_id in generated_by_id:
                    continue
                try:
                    generated_by_id[menu_id] = GeneratedMenuPresentation.model_validate(raw_item)
                    item_errors.pop(menu_id, None)
                except ValidationError as exc:
                    item_errors.setdefault(menu_id, self._validation_reason(exc))
            for menu_id in expected:
                if menu_id not in generated_by_id:
                    item_errors.setdefault(menu_id, "PRESENTATION_MENU_MISSING")
            generated_items = [
                generated_by_id[menu_id] for menu_id in expected if menu_id in generated_by_id
            ]
            if not generated_items:
                raise ValueError(next(iter(item_errors.values())))
            result = MenuPresentationGeneration(items=generated_items)
            for generated in result.items:
                source = expected[generated.menu_id]
                fallback_fields: list[str] = []
                target_language = {
                    "한국어": "ko",
                    "日本語": "ja",
                }.get(locale, "en")
                if generated.option_group_localizations or generated.option_item_localizations:
                    # Option strings are generated by the dedicated ordered
                    # option translator. Ignore accidental card-model output
                    # while retaining the menu prose that is safe to display.
                    generated.option_group_localizations = []
                    generated.option_item_localizations = []
                    fallback_fields.append("option_localizations")
                source_description = str(source.get("source_description_ko") or "")
                if bool(source_description) != bool(generated.localized_source_description):
                    generated.localized_source_description = ""
                    fallback_fields.append("localized_source_description")
                elif source_description and not source_translation_is_safe(
                    source_description,
                    generated.localized_source_description,
                    target_language,
                ):
                    generated.localized_source_description = ""
                    fallback_fields.append("localized_source_description")
                expected_title = (
                    str(source["menu_title_ko"])
                    if target_language == "ko"
                    else str(source["localized_title"])
                )
                if generated.localized_title != expected_title:
                    # The exact localized title is immutable server data. A
                    # punctuation or spelling drift from Grok does not require
                    # discarding its otherwise grounded explanations.
                    generated.localized_title = expected_title
                    fallback_fields.append("localized_title")
                for field_name in (
                    "localized_subtitle",
                    "yobi_short_explanation",
                    "yobi_long_explanation",
                    "review_summary",
                ):
                    if not str(getattr(generated, field_name) or "").strip():
                        fallback_fields.append(field_name)
                if _contains_review_signal(
                    f"{generated.yobi_short_explanation} {generated.yobi_long_explanation}"
                ):
                    generated.yobi_short_explanation = ""
                    generated.yobi_long_explanation = ""
                    fallback_fields.extend(["yobi_short_explanation", "yobi_long_explanation"])
                for field_name in (
                    "localized_subtitle",
                    "localized_source_description",
                    "yobi_short_explanation",
                    "yobi_long_explanation",
                    "review_summary",
                ):
                    value = str(getattr(generated, field_name) or "")
                    invalid_script = target_language in {"en", "ja"} and _contains_hangul(value)
                    if (
                        target_language == "ja"
                        and value
                        and field_name != "localized_source_description"
                    ):
                        invalid_script = invalid_script or not _contains_japanese_script(value)
                    if invalid_script:
                        setattr(generated, field_name, "")
                        fallback_fields.append(field_name)
                if sorted(
                    _quantity_tokens(generated.localized_source_description, target_language)
                ) != sorted(_quantity_tokens(source_description, "ko")):
                    generated.localized_source_description = ""
                    fallback_fields.append("localized_source_description")
                translated_source_folded = generated.localized_source_description.casefold()
                if any(
                    token not in translated_source_folded
                    for token in _ascii_source_tokens(source_description)
                ):
                    generated.localized_source_description = ""
                    fallback_fields.append("localized_source_description")
                allowed_yobi_evidence = {
                    str(item.get("evidence_id"))
                    for field in ("wiki_passages", "menu_facts")
                    for item in source.get(field, [])
                    if isinstance(item, dict) and item.get("evidence_id")
                }
                allowed_review_evidence = {
                    str(item.get("review_id"))
                    for item in source.get("synthetic_reviews", [])
                    if isinstance(item, dict) and item.get("review_id")
                }
                # Evidence/source arrays are untrusted bookkeeping, not prose.
                # Canonicalize them from the server-owned payload instead of
                # rejecting otherwise safe user-visible copy for an omitted or
                # extra ID.
                generated.yobi_used_evidence_ids = sorted(allowed_yobi_evidence)
                generated.review_used_ids = sorted(allowed_review_evidence)
                generated.used_evidence_ids = sorted(
                    allowed_yobi_evidence | allowed_review_evidence
                )
                expected_review_fields = (
                    {"synthetic_reviews"} if source.get("synthetic_reviews") else set()
                )
                required_yobi_fields = {"menu_title_ko", "localized_title"}
                if source.get("source_description_ko"):
                    required_yobi_fields.add("source_description_ko")
                if source.get("wiki_passages"):
                    required_yobi_fields.add("wiki_passages")
                if generated.personalization_applied:
                    required_yobi_fields.add("country_preference")
                if source.get("menu_components"):
                    required_yobi_fields.add("menu_components")
                required_source_fields = {"menu_title_ko", "localized_title"}
                if source.get("source_description_ko"):
                    required_source_fields.add("source_description_ko")
                if source.get("wiki_passages"):
                    required_source_fields.add("wiki_passages")
                if source.get("synthetic_reviews"):
                    required_source_fields.add("synthetic_reviews")
                if generated.personalization_applied:
                    required_source_fields.add("country_preference")
                if source.get("menu_components"):
                    required_source_fields.add("menu_components")
                # The server owns these provenance arrays. Their model-returned
                # spelling/order cannot make safe prose fail validation.
                generated.yobi_used_source_fields = sorted(required_yobi_fields)
                generated.review_used_source_fields = sorted(expected_review_fields)
                generated.used_source_fields = sorted(required_source_fields)
                component_by_id = {
                    str(component.get("component_id")): component
                    for component in source.get("menu_components", [])
                    if isinstance(component, dict) and component.get("component_id")
                }
                explanatory_copy = _normalized_text(
                    " ".join(
                        (
                            generated.localized_subtitle,
                            generated.yobi_short_explanation,
                            generated.yobi_long_explanation,
                        )
                    )
                )
                valid_mentions: list[GeneratedComponentMention] = []
                seen_component_ids: set[str] = set()
                for mention in generated.component_mentions:
                    component = component_by_id.get(mention.component_id)
                    normalized_mention = _normalized_text(mention.mention_text)
                    if (
                        component is None
                        or mention.component_id in seen_component_ids
                        or not normalized_mention
                        or normalized_mention not in explanatory_copy
                    ):
                        continue
                    if target_language == "en" and not _english_title_coverage_is_sufficient(
                        str(component.get("name_en") or ""), mention.mention_text
                    ):
                        continue
                    valid_mentions.append(mention)
                    seen_component_ids.add(mention.component_id)
                generated.component_mentions = valid_mentions
                generated.covered_component_ids = sorted(seen_component_ids)
                if seen_component_ids != set(component_by_id):
                    fallback_fields.append("component_metadata")
                if fallback_fields:
                    field_fallbacks[generated.menu_id] = sorted(set(fallback_fields))
            if item_errors:
                result.items = [item for item in result.items if item.menu_id not in item_errors]
                result._item_errors = item_errors
                if not result.items:
                    raise ValueError(next(iter(item_errors.values())))
            result._field_fallbacks = field_fallbacks
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
You are YOBI's grounded menu explainer. Another model already selected the menus. Return exactly
one JSON object matching the supplied schema, written in {locale}, with every requested menu_id
exactly once. Never add, remove, reorder, rank, or replace a menu.

Ground every user-visible sentence in this priority order:
1. localized_title and menu_title_ko identify the exact listing.
2. source_description_ko describes this restaurant's listing and must not be generalized away.
3. menu_facts describe this listing when explicitly supplied.
4. wiki_passages explain the general food concept only. They never prove this restaurant's exact
   recipe, ingredients, certification, popularity, availability, or preparation.

Field rules:
- Copy localized_title exactly, character for character.
- localized_subtitle is one concise phrase that helps a foreign visitor understand this exact
  listing. It may equal the title when no supported clarification is available.
- localized_source_description is a faithful, natural translation of source_description_ko, not a
  summary or phonetic transliteration. If the source is empty, return an empty string. Preserve
  every literal digit, unit, Latin brand name, and product code exactly.
- yobi_short_explanation and yobi_long_explanation explain the food using only the title,
  restaurant description, menu facts, Wiki passages, components, and a supported country cue.
  Aim for 1-2 concise sentences in the short field and 2-5 in the long field, but prioritize
  accuracy and natural language over sentence count. Never use synthetic_reviews and never mention
  reviewers, diners, customers, ratings, feedback, praise, comments, or what people said.
- review_summary is the only review field. Base it exclusively on synthetic_reviews. If none are
  supplied, state neutrally that no review summary is available; do not invent sentiment.
- For a compound listing, explain each supplied menu_component without transferring one
  component's ingredient, temperature, texture, or cooking method to another. Return its supplied
  component_id once in covered_component_ids and copy a matching visible phrase into
  component_mentions. These arrays are bookkeeping; the server will canonicalize them.
- option_group_localizations and option_item_localizations must both be empty arrays.
- Evidence/source arrays may contain only IDs and source-field names present in the input. The
  server owns and canonicalizes this bookkeeping.

Country and language may guide familiar wording, but never force a country mention, stereotype a
nationality, or invent an analogy. Do not invent ingredients, taste, cooking method, certification,
dietary safety, popularity, orders, restaurant practice, or availability. Do not expose internal
IDs in prose. Do not emit Markdown, analysis, or a preamble.

Before returning, silently verify: all menu IDs are present once; every localized_title is copied;
YOBI fields contain no review language; YOGIYO digits/units/Latin tokens are unchanged; no Korean
Hangul remains in English or Japanese output; Japanese prose uses natural Japanese script.
Prompt version:
{self.settings.menu_presentation_prompt_version}.
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
