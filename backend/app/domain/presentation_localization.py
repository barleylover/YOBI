from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.preference_catalog import SUPPORTED_LOCALES, normalize_preference_locale

SupportedPresentationLocale = Literal[
    "en",
    "ko",
    "ja",
    "zh-CN",
    "zh-TW",
    "es",
    "fr",
    "de",
    "it",
    "pt",
    "th",
    "vi",
    "id",
    "ar",
    "hi",
    "ru",
]
SpiceRelationship = Literal["LESS", "SIMILAR", "MORE"]

SUPPORTED_PRESENTATION_LOCALES = cast(tuple[SupportedPresentationLocale, ...], SUPPORTED_LOCALES)

PRESENTATION_LOCALE_LABELS: dict[SupportedPresentationLocale, str] = {
    "en": "English",
    "ko": "한국어",
    "ja": "日本語",
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "pt": "Português",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
    "ar": "العربية",
    "hi": "हिन्दी",
    "ru": "Русский",
}

GENERIC_LOCALIZED_TITLES = frozenset({"korean menu", "韓国料理メニュー"})

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
_METRIC_UNIT_PATTERN = re.compile(
    r"(?i)\d+(?:[.,]\d+)?\s*(kg|mg|ml|cl|dl|g|l)\b"
)

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

_LATIN_PRESENTATION_LOCALES = frozenset({"en", "es", "fr", "de", "it", "pt", "vi", "id"})
_SCRIPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "ja": re.compile(r"[ぁ-ゖァ-ヺ一-龯々]"),
    "zh-CN": re.compile(r"[一-龯]"),
    "zh-TW": re.compile(r"[一-龯]"),
    "th": re.compile(r"[\u0E00-\u0E7F]"),
    "ar": re.compile(r"[\u0600-\u06FF]"),
    "hi": re.compile(r"[\u0900-\u097F]"),
    "ru": re.compile(r"[\u0400-\u04FF]"),
}
_LATIN_PATTERN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ž]", re.UNICODE)


def normalize_presentation_locale(value: str) -> SupportedPresentationLocale:
    return cast(SupportedPresentationLocale, normalize_preference_locale(value))


def presentation_locale_label(value: str) -> str:
    return PRESENTATION_LOCALE_LABELS[normalize_presentation_locale(value)]


def normalize_country_code(value: str | None) -> str | None:
    normalized = str(value or "").strip().upper()
    if len(normalized) != 2 or normalized == "ZZ" or not normalized.isalpha():
        return None
    return normalized


def is_generic_localized_title(value: str | None) -> bool:
    normalized = " ".join(str(value or "").split()).casefold()
    return normalized in GENERIC_LOCALIZED_TITLES


def contains_hangul(value: str) -> bool:
    return bool(re.search(r"[가-힣]", value))


def text_uses_target_script(value: str, locale: str) -> bool:
    """Return whether non-empty prose contains the requested locale's writing system."""

    normalized_locale = normalize_presentation_locale(locale)
    text = value.strip()
    if not text:
        return False
    if normalized_locale == "ko":
        return contains_hangul(text)
    if contains_hangul(text):
        return False
    if normalized_locale in _LATIN_PRESENTATION_LOCALES:
        return bool(_LATIN_PATTERN.search(text))
    return bool(_SCRIPT_PATTERNS[normalized_locale].search(text))


def _number_tokens(value: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", value)


def _quantity_tokens(value: str, target_language: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value)
    tokens = _number_tokens(normalized)
    del target_language
    tokens.extend(
        _ENGLISH_QUANTITY_WORDS[match.group(1).casefold()]
        for match in _ENGLISH_QUANTITY_UNIT_PATTERN.finditer(normalized)
    )
    return tokens


def _metric_unit_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value)
    return [match.group(1).casefold() for match in _METRIC_UNIT_PATTERN.finditer(normalized)]


def _ascii_source_tokens(value: str) -> set[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*", value)
    if any(not character.isascii() for character in value):
        # Latin text embedded in Korean/Japanese/etc. source prose is normally
        # a brand or product identifier and must survive translation.
        return {token.casefold() for token in tokens}

    def looks_like_identity(token: str) -> bool:
        plain = token.replace("-", "").replace(".", "")
        return bool(
            any(character.isdigit() for character in plain)
            or "-" in token
            or "." in token
            or (len(plain) >= 2 and plain.isupper())
            or (
                any(character.islower() for character in plain)
                and any(character.isupper() for character in plain[1:])
            )
        )

    # Natural all-Latin source prose may be paraphrased or translated. Preserve
    # only tokens shaped like brand names or product codes, not every English word.
    return {token.casefold() for token in tokens if looks_like_identity(token)}


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


def _looks_like_latin_phonetic_copy(source: str, target: str) -> bool:
    if len(re.findall(r"[가-힣]", source)) < 8:
        return False
    latin = "".join(character for character in target.casefold() if "a" <= character <= "z")
    if not latin:
        return False
    return difflib.SequenceMatcher(None, _romanize_for_quality_check(source), latin).ratio() >= 0.7


def _looks_like_japanese_phonetic_copy(source: str, target: str) -> bool:
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
    locale = normalize_presentation_locale(language)
    if not source or not target:
        return False
    if locale == "ko":
        return target == source
    if not text_uses_target_script(target, locale):
        return False
    if sorted(_quantity_tokens(target, locale)) != sorted(_quantity_tokens(source, "ko")):
        return False
    source_metric_units = sorted(_metric_unit_tokens(source))
    if source_metric_units and sorted(_metric_unit_tokens(target)) != source_metric_units:
        return False
    target_folded = target.casefold()
    if any(token not in target_folded for token in _ascii_source_tokens(source)):
        return False
    if locale in _LATIN_PRESENTATION_LOCALES and _looks_like_latin_phonetic_copy(source, target):
        return False
    if locale == "ja" and _looks_like_japanese_phonetic_copy(source, target):
        return False
    return True


def persistable_menu_localization_fields(
    *,
    source_description: str,
    language_code: str,
    localized_title: str | None,
    localized_source_description: str | None,
) -> tuple[str | None, str | None]:
    """Apply the identical field-level persistence gate in both repositories."""

    title_value = str(localized_title or "").strip()
    persistable_title = (
        title_value if title_value and not is_generic_localized_title(title_value) else None
    )
    description_value = str(localized_source_description or "").strip()
    persistable_description = (
        description_value
        if source_translation_is_safe(
            source_description.strip(),
            description_value,
            language_code,
        )
        else None
    )
    return persistable_title, persistable_description


class PresentationCountryContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_country_code: str | None = Field(default=None, min_length=2, max_length=2)
    spice_reference_country_code: str | None = Field(default=None, min_length=2, max_length=2)
    representative_dish_en: str | None = Field(default=None, max_length=300)
    spice_baseline: int | None = Field(default=None, ge=1, le=5)
    menu_spice_level: int | None = Field(default=None, ge=1, le=5)
    spice_relationship: SpiceRelationship | None = None

    @field_validator("user_country_code", "spice_reference_country_code", mode="before")
    @classmethod
    def canonical_country_code(cls, value: object) -> str | None:
        return normalize_country_code(str(value) if value is not None else None)

    @field_validator("representative_dish_en", mode="before")
    @classmethod
    def strip_representative_dish(cls, value: object) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @property
    def comparison_is_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.spice_reference_country_code,
                self.representative_dish_en,
                self.spice_baseline,
                self.menu_spice_level,
                self.spice_relationship,
            )
        )


def build_presentation_country_context(
    *,
    user_country_code: str | None,
    spice_reference_country_code: str | None,
    representative_dish_en: str | None,
    spice_baseline: int | None,
    menu_spice_level: int | None,
) -> PresentationCountryContext:
    normalized_user_country = normalize_country_code(user_country_code)
    if normalized_user_country is None:
        return PresentationCountryContext()
    normalized_spice_country = normalize_country_code(spice_reference_country_code)
    normalized_dish = str(representative_dish_en or "").strip() or None
    comparison_complete = all(
        value is not None
        for value in (
            normalized_spice_country,
            normalized_dish,
            spice_baseline,
            menu_spice_level,
        )
    )
    relationship: SpiceRelationship | None = None
    if comparison_complete:
        assert spice_baseline is not None
        assert menu_spice_level is not None
        relationship = (
            "LESS"
            if menu_spice_level < spice_baseline
            else "MORE"
            if menu_spice_level > spice_baseline
            else "SIMILAR"
        )
    return PresentationCountryContext(
        user_country_code=normalized_user_country,
        spice_reference_country_code=(
            normalized_spice_country if comparison_complete else None
        ),
        representative_dish_en=normalized_dish if comparison_complete else None,
        spice_baseline=spice_baseline if comparison_complete else None,
        menu_spice_level=menu_spice_level if comparison_complete else None,
        spice_relationship=relationship,
    )
