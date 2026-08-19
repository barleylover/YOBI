from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

COUNTRY_CODES = (
    "US", "GB", "CA", "AU", "NZ", "IE", "KR", "JP", "CN", "TW", "HK", "SG",
    "ES", "MX", "AR", "CO", "FR", "BE", "DE", "AT", "CH", "IT", "PT", "BR",
    "TH", "VN", "ID", "MY", "SA", "AE", "EG", "IN", "RU", "PH", "TR", "NL",
)
GENERATOR_VERSION = "yobi-synthetic-enrichment-v1"
SOURCE_TYPE = "SYNTHETIC_DEMO"

_ANIMAL_TOKENS = (
    "PORK", "BEEF", "CHICKEN", "FISH", "SEAFOOD", "EGG", "DAIRY",
    "돼지", "삼겹", "제육", "소고기", "쇠고기", "닭", "치킨", "생선", "새우",
    "오징어", "해물", "계란", "달걀", "치즈", "우유",
)
_PORK_TOKENS = ("PORK", "돼지", "삼겹", "제육", "족발", "보쌈", "베이컨", "햄")


@dataclass(frozen=True)
class EnrichmentMenu:
    menu_id: str
    name_ko: str
    feature_codes: tuple[str, ...] = ()


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
    return any(token.upper() in upper for token in tokens)


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
    rows: list[dict[str, Any]] = []
    eligible_for_vegan: list[str] = []
    for menu in sorted(menus, key=lambda item: item.menu_id):
        basis = " ".join((menu.name_ko, *menu.feature_codes))
        value = _number(seed, "menu", menu.menu_id)
        has_pork = _contains(basis, _PORK_TOKENS)
        has_animal = _contains(basis, _ANIMAL_TOKENS)
        if not has_animal:
            eligible_for_vegan.append(menu.menu_id)
        vegan = not has_animal and value % 5 == 0
        halal = not has_pork and (vegan or value % 3 != 0)
        rows.append(
            {
                "release_id": release_id,
                "menu_id": menu.menu_id,
                "spice_level": 1 + ((value >> 8) % 5),
                "halal_fit": int(halal),
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
                row["halal_fit"] = 1
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
        if sum(int(row["halal_fit"]) for row in menu_rows) < 3:
            raise ValueError("SYNTHETIC_HALAL_COVERAGE_LOW")
        if sum(int(row["vegan_fit"]) for row in menu_rows) < 3:
            raise ValueError("SYNTHETIC_VEGAN_COVERAGE_LOW")
        if sum(int(row["halal_fit"]) and int(row["vegan_fit"]) for row in menu_rows) < 3:
            raise ValueError("SYNTHETIC_HALAL_VEGAN_COVERAGE_LOW")
