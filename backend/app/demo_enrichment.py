from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.country_spice_examples import (
    COUNTRY_SPICE_EXAMPLES,
    LanguageCode,
    example_seed_hash,
)

COUNTRY_CODES = (
    "US",
    "GB",
    "CA",
    "AU",
    "NZ",
    "IE",
    "KR",
    "JP",
    "CN",
    "TW",
    "HK",
    "SG",
    "ES",
    "MX",
    "AR",
    "CO",
    "FR",
    "BE",
    "DE",
    "AT",
    "CH",
    "IT",
    "PT",
    "BR",
    "TH",
    "VN",
    "ID",
    "MY",
    "SA",
    "AE",
    "EG",
    "IN",
    "RU",
    "PH",
    "TR",
    "NL",
)
GENERATOR_VERSION = "yobi-synthetic-enrichment-v9-animal-alias-coverage"
SOURCE_TYPE = "SYNTHETIC_DEMO"
LANGUAGE_CODES: tuple[LanguageCode, ...] = ("ko", "en", "ja")

_PORK_TOKENS = (
    "PORK",
    "PORK CUTLET",
    "DONKATSU",
    "BACON",
    "HAM",
    "SAUSAGE",
    "SPAM",
    "PEPPERONI",
    "SALAMI",
    "PROSCIUTTO",
    "MORTADELLA",
    "PANCETTA",
    "CHORIZO",
    "LARD",
    "TONKATSU",
    "TONKOTSU",
    "CHASHU",
    "CHAR SIU",
    "JAMON",
    "JAMBON",
    "돼지",
    "한돈",
    "삼겹",
    "오겹살",
    "제육",
    "족발",
    "보쌈",
    "목살",
    "항정살",
    "가브리살",
    "갈매기살",
    "등뼈",
    "뼈해장국",
    "껍데기",
    "머릿고기",
    "편육",
    "수육",
    "부대찌개",
    "베이컨",
    "햄",
    "소시지",
    "스팸",
    "돈가스",
    "돈까스",
    "돈카츠",
    "돈코츠",
    "차슈",
    "하몽",
    "잠봉",
    "부타",
    "포크",
    "순대",
    "감자탕",
    "탕수육",
    "페퍼로니",
    "살라미",
    "프로슈토",
    "모르타델라",
    "판체타",
    "초리조",
    "돈육",
    "돈골",
    "돈지",
    "라드",
)
_HALAL_EXCLUSION_TOKENS = _PORK_TOKENS + (
    "ALCOHOL",
    "BEER",
    "WINE",
    "SOJU",
    "LIQUOR",
    "SAKE",
    "WHISKY",
    "WHISKEY",
    "BRANDY",
    "RUM",
    "COOKING WINE",
    "맥주",
    "소주",
    "막걸리",
    "술",
    "주류",
    "알코올",
    "와인",
    "사케",
    "청주",
    "맛술",
    "미림",
    "위스키",
    "브랜디",
    "럼주",
)
_ANIMAL_TOKENS = _PORK_TOKENS + (
    "BEEF",
    "MEAT",
    "GALBI",
    "SHORT RIB",
    "GOPCHANG",
    "DAECHANG",
    "MAKCHANG",
    "TRIPE",
    "INTESTINE",
    "BLOOD SAUSAGE",
    "CHICKEN",
    "FISH",
    "SEAFOOD",
    "EGG",
    "DAIRY",
    "돼지",
    "삼겹",
    "제육",
    "소고기",
    "쇠고기",
    "고기",
    "갈비",
    "곱창",
    "대창",
    "막창",
    "내장",
    "양곱창",
    "닭",
    "치킨",
    "생선",
    "새우",
    "오징어",
    "해물",
    "계란",
    "달걀",
    "치즈",
    "우유",
)
_HALAL_PREFERRED_TOKENS = (
    "VEGETABLE",
    "TOFU",
    "BEAN",
    "MUSHROOM",
    "POTATO",
    "FRUIT",
    "PUMPKIN",
    "CORN",
    "SWEET_POTATO",
    "RICE",
    "NOODLES",
    "SEAFOOD",
    "FISH",
    "CHICKEN",
    "채소",
    "야채",
    "두부",
    "콩",
    "버섯",
    "감자",
    "과일",
    "호박",
    "옥수수",
    "고구마",
    "밥",
    "쌀",
    "면",
    "생선",
    "해물",
    "닭",
)


@dataclass(frozen=True)
class EnrichmentMenu:
    menu_id: str
    name_ko: str
    feature_codes: tuple[str, ...] = ()
    name_en: str = ""
    description: str = ""


@dataclass(frozen=True)
class EnrichmentOption:
    option_item_id: str
    menu_id: str
    name_ko: str


def _digest(seed: str, *parts: str) -> str:
    return hashlib.sha256("|".join((seed, *parts)).encode("utf-8")).hexdigest()


def _number(seed: str, *parts: str) -> int:
    return int(_digest(seed, *parts)[:16], 16)


def _contains(text: str, tokens: tuple[str, ...]) -> bool:
    upper = text.upper()
    return any(
        (
            re.search(rf"(?<![A-Z]){re.escape(token.upper())}(?![A-Z])", upper)
            is not None
        )
        if token.isascii()
        else token.upper() in upper
        for token in tokens
    )


def has_obvious_animal_ingredient(*text_parts: str) -> bool:
    """Fail closed for obvious animal aliases in synthetic vegan demo data."""

    return _contains(" ".join(part for part in text_parts if part), _ANIMAL_TOKENS)


def build_country_profiles(release_id: str, seed: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for country_code in COUNTRY_CODES:
        value = _number(seed, "country", country_code)
        baseline = 1 + value % 5
        affinity = round(0.45 + ((value >> 8) % 5000) / 10000, 4)
        rows.append(
            {
                "release_id": release_id,
                "country_code": country_code,
                "spice_baseline": baseline,
                "affinity_score": affinity,
                "affinity_json": json.dumps(
                    {
                        "warm": round(0.4 + ((value >> 16) % 5000) / 10000, 4),
                        "savory": round(0.45 + ((value >> 24) % 4500) / 10000, 4),
                        "crisp": round(0.4 + ((value >> 32) % 5000) / 10000, 4),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
    return rows


def build_menu_profiles(
    release_id: str,
    seed: str,
    menus: Iterable[EnrichmentMenu],
) -> list[dict[str, Any]]:
    menu_list = sorted(menus, key=lambda item: item.menu_id)
    rows: list[dict[str, Any]] = []
    eligible_for_vegan: list[str] = []
    basis_by_menu: dict[str, str] = {}
    for menu in menu_list:
        basis = " ".join((menu.name_ko, menu.name_en, menu.description, *menu.feature_codes))
        basis_by_menu[menu.menu_id] = basis
        value = _number(seed, "menu", menu.menu_id)
        has_animal = has_obvious_animal_ingredient(basis)
        if not has_animal:
            eligible_for_vegan.append(menu.menu_id)
        vegan = not has_animal and value % 5 == 0
        rows.append(
            {
                "release_id": release_id,
                "menu_id": menu.menu_id,
                "spice_level": 1 + ((value >> 8) % 5),
                "halal_fit": 0,
                "vegan_fit": int(vegan),
                "source_type": SOURCE_TYPE,
                "generator_version": GENERATOR_VERSION,
                "seed_hash": _digest(seed, "menu", menu.menu_id),
            }
        )
    vegan_count = sum(int(row["vegan_fit"]) for row in rows)
    if vegan_count < 3:
        promotable = [
            menu_id
            for menu_id in eligible_for_vegan
            if not next(int(row["vegan_fit"]) for row in rows if row["menu_id"] == menu_id)
        ]
        promoted = set(promotable[: 3 - vegan_count])
        for row in rows:
            if row["menu_id"] in promoted:
                row["vegan_fit"] = 1

    # This is explicitly synthetic demo metadata, not a certification claim. Mark exactly the
    # nearest whole-menu third as a fit and favor menus whose names, source descriptions, and
    # features are most plausibly compatible: vegan/plant dishes first, then familiar
    # fish/chicken candidates. Pork/alcohol-token menus can never be promoted. The digest is only
    # a stable tie-breaker.
    target_halal_count = (len(rows) + 1) // 3
    eligible_halal = [
        row
        for row in rows
        if not _contains(
            basis_by_menu[str(row["menu_id"])],
            _HALAL_EXCLUSION_TOKENS,
        )
    ]
    if len(eligible_halal) < target_halal_count:
        raise ValueError("SYNTHETIC_HALAL_ELIGIBLE_COVERAGE_LOW")

    def halal_priority(row: dict[str, Any]) -> tuple[int, int, str]:
        menu_id = str(row["menu_id"])
        basis = basis_by_menu[menu_id]
        preferred = _contains(basis, _HALAL_PREFERRED_TOKENS)
        return (
            0 if int(row["vegan_fit"]) else 1 if preferred else 2,
            _number(seed, "halal-priority", menu_id),
            menu_id,
        )

    selected_halal = {
        str(row["menu_id"])
        for row in sorted(eligible_halal, key=halal_priority)[:target_halal_count]
    }
    for row in rows:
        row["halal_fit"] = int(str(row["menu_id"]) in selected_halal)
    return rows


def build_option_profiles(
    release_id: str,
    seed: str,
    options: Iterable[EnrichmentOption],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for option in sorted(options, key=lambda item: item.option_item_id):
        value = _number(seed, "option", option.option_item_id)
        has_pork = _contains(option.name_ko, _PORK_TOKENS)
        has_animal = _contains(option.name_ko, _ANIMAL_TOKENS)
        rows.append(
            {
                "release_id": release_id,
                "option_item_id": option.option_item_id,
                "halal_conflict": int(has_pork),
                "vegan_conflict": int(has_animal or value % 17 == 0),
                "source_type": SOURCE_TYPE,
                "seed_hash": _digest(seed, "option", option.option_item_id),
            }
        )
    return rows


def build_country_preferences(
    release_id: str,
    seed: str,
    menus: Iterable[EnrichmentMenu],
    countries: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    menu_list = sorted(menus, key=lambda item: item.menu_id)
    rows: list[dict[str, Any]] = []
    for country in countries:
        country_code = str(country["country_code"])
        affinity = float(country["affinity_score"])
        for menu in menu_list:
            value = _number(seed, "preference", menu.menu_id, country_code)
            feature_bonus = min(len(menu.feature_codes), 6)
            percent = round(54 + affinity * 24 + feature_bonus + value % 11)
            rows.append(
                {
                    "release_id": release_id,
                    "menu_id": menu.menu_id,
                    "country_code": country_code,
                    "preference_percent": min(94, max(54, percent)),
                    "sample_size": 120 + ((value >> 12) % 861),
                }
            )
    return rows


_REVIEW_TEMPLATES = (
    ("TASTE", 5, "메뉴의 중심 맛이 또렷해서 처음 먹는 사람도 편하게 즐길 수 있었어요."),
    ("TASTE", 4, "간이 과하지 않고 재료의 맛이 잘 어울렸어요."),
    ("TEXTURE", 5, "식감이 단조롭지 않아 마지막까지 맛있게 먹었어요."),
    ("VALUE", 4, "가격과 양의 균형이 괜찮아서 한 끼 메뉴로 만족스러웠어요."),
    ("PACKAGING", 4, "포장이 안정적이어서 메뉴 상태가 깔끔하게 유지됐어요."),
    ("CAVEAT", 3, "개인 취향에 따라 간이나 매운 정도가 조금 강하게 느껴질 수 있어요."),
)


def build_reviews(
    release_id: str,
    seed: str,
    menus: Iterable[EnrichmentMenu],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for menu in sorted(menus, key=lambda item: item.menu_id):
        for index, (topic, rating, template) in enumerate(_REVIEW_TEMPLATES):
            review_id = f"syn-review-{_digest(seed, menu.menu_id, str(index))[:24]}"
            rows.append(
                {
                    "review_id": review_id,
                    "release_id": release_id,
                    "menu_id": menu.menu_id,
                    "topic": topic,
                    "rating": rating,
                    "review_text": f"{menu.name_ko}: {template}",
                    "source_type": SOURCE_TYPE,
                    "display_order": index,
                    "seed_hash": _digest(seed, "review", menu.menu_id, str(index)),
                }
            )
    return rows


def build_korean_localizations(
    release_id: str,
    seed: str,
    menus: Iterable[EnrichmentMenu],
) -> list[dict[str, Any]]:
    return [
        {
            "release_id": release_id,
            "menu_id": menu.menu_id,
            "language_code": "ko",
            "display_name": menu.name_ko,
            "model_id": "SOURCE_COPY",
            "prompt_version": "menu-name-localization-v1",
            "wiki_evidence_ids_json": "[]",
            "source_hash": _digest(seed, "localization", menu.menu_id, menu.name_ko),
            "validation_status": "VALID",
        }
        for menu in sorted(menus, key=lambda item: item.menu_id)
    ]


def build_country_spice_examples(
    release_id: str,
    seed: str,
    countries: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    baselines = {
        str(country["country_code"]): int(country["spice_baseline"]) for country in countries
    }
    return [
        {
            "release_id": release_id,
            "country_code": country_code,
            "language_code": language_code,
            "representative_dish": COUNTRY_SPICE_EXAMPLES[country_code][language_code],
            "spice_baseline": baselines[country_code],
            "source_type": SOURCE_TYPE,
            "seed_hash": example_seed_hash(seed, country_code, language_code),
        }
        for country_code in sorted(baselines)
        for language_code in LANGUAGE_CODES
    ]


def manifest_sha256(rows_by_name: dict[str, list[dict[str, Any]]]) -> str:
    payload = json.dumps(rows_by_name, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_enrichment_rows(
    *,
    release_id: str,
    seed: str,
    menus: Iterable[EnrichmentMenu],
    options: Iterable[EnrichmentOption] = (),
) -> dict[str, list[dict[str, Any]]]:
    menu_list = list(menus)
    countries = build_country_profiles(release_id, seed)
    rows = {
        "countries": countries,
        "country_examples": build_country_spice_examples(release_id, seed, countries),
        "menus": build_menu_profiles(release_id, seed, menu_list),
        "options": build_option_profiles(release_id, seed, options),
        "preferences": build_country_preferences(release_id, seed, menu_list, countries),
        "reviews": build_reviews(release_id, seed, menu_list),
        "localizations": build_korean_localizations(release_id, seed, menu_list),
    }
    return rows


def validate_enrichment_rows(
    rows: dict[str, list[dict[str, Any]]],
    *,
    eligible_menu_count: int,
) -> None:
    expected = {
        "countries": len(COUNTRY_CODES),
        "country_examples": len(COUNTRY_CODES) * 3,
        "menus": eligible_menu_count,
        "preferences": eligible_menu_count * len(COUNTRY_CODES),
        "reviews": eligible_menu_count * len(_REVIEW_TEMPLATES),
        "localizations": eligible_menu_count,
    }
    for key, count in expected.items():
        if len(rows[key]) != count:
            raise ValueError(f"SYNTHETIC_ENRICHMENT_COUNT_MISMATCH:{key}:{len(rows[key])}:{count}")
    if len({row["menu_id"] for row in rows["menus"]}) != eligible_menu_count:
        raise ValueError("SYNTHETIC_ENRICHMENT_MENU_DUPLICATE")
    if eligible_menu_count >= 3:
        menu_rows = rows["menus"]
        expected_halal_count = (eligible_menu_count + 1) // 3
        actual_halal_count = sum(int(row["halal_fit"]) for row in menu_rows)
        if actual_halal_count != expected_halal_count:
            raise ValueError(
                "SYNTHETIC_HALAL_COVERAGE_NOT_ONE_THIRD:"
                f"{actual_halal_count}:{expected_halal_count}"
            )
        if sum(int(row["vegan_fit"]) for row in menu_rows) < 3:
            raise ValueError("SYNTHETIC_VEGAN_COVERAGE_LOW")
