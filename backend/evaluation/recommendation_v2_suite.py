from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any, Literal

from app.domain.preference_catalog import PREFERENCE_CATEGORIES

SUITE_VERSION = "yobi-recommendation-golden-v2-2026-08-18-r4"
EvalLocale = Literal["English", "한국어"]
_LOCALE_VARIANTS: tuple[tuple[str, EvalLocale], ...] = (
    ("en", "English"),
    ("ko", "한국어"),
)

_CRITERIA_LIST_FIELDS = (
    "cuisine_origins",
    "flavors",
    "main_ingredients",
    "food_forms",
    "temperatures",
    "price_bands",
    "textures",
    "cooking_methods",
)


@dataclass(frozen=True)
class RecommendationEvalQuery:
    query_id: str
    cohort: Literal[
        "single_option",
        "cross_category",
        "negative",
        "bilingual_equivalence",
    ]
    locale: EvalLocale
    criteria: dict[str, Any]
    expected_outcome: Literal["POSITIVE", "NO_MATCH"]
    pair_id: str | None = None
    split: Literal["TUNE", "HOLDOUT"] = "TUNE"

    def payload(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "cohort": self.cohort,
            "locale": self.locale,
            "criteria": self.criteria,
            "expected_outcome": self.expected_outcome,
            "pair_id": self.pair_id,
            "split": self.split,
        }


def _criteria(**updates: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "2",
        **{field: [] for field in _CRITERIA_LIST_FIELDS},
        "dietary_filters": {
            "halal_certified_only": False,
            "vegan": False,
        },
        "max_spice_level": 5,
        "spice_reference_country": "KR",
    }
    result.update(updates)
    return result


_CROSS_CASES: tuple[dict[str, Any], ...] = (
    _criteria(flavors=["SPICY"], food_forms=["NOODLES"]),
    _criteria(textures=["CRISPY"], main_ingredients=["CHICKEN"], cooking_methods=["FRIED"]),
    _criteria(flavors=["CLEAN_MILD"], food_forms=["SOUP"], temperatures=["HOT"]),
    _criteria(cuisine_origins=["ITALIAN"], food_forms=["NOODLES"]),
    _criteria(flavors=["SWEET"], temperatures=["FROZEN"], food_forms=["DESSERT_BAKERY"]),
    _criteria(cuisine_origins=["KOREAN"], food_forms=["RICE"], flavors=["NUTTY_SAVORY"]),
    _criteria(cuisine_origins=["JAPANESE"], main_ingredients=["FISH_SEAFOOD"]),
    _criteria(cuisine_origins=["AMERICAN"], food_forms=["BREAD"], cooking_methods=["GRILLED"]),
    _criteria(cuisine_origins=["CHINESE"], food_forms=["NOODLES"], cooking_methods=["STIR_FRIED"]),
    _criteria(cuisine_origins=["SOUTHEAST_ASIAN"], food_forms=["NOODLES", "SOUP"]),
    _criteria(cuisine_origins=["MEXICAN"], main_ingredients=["BEEF"]),
    _criteria(cuisine_origins=["KOREAN"], main_ingredients=["PORK"], cooking_methods=["GRILLED"]),
    _criteria(flavors=["SALTY"], main_ingredients=["FISH_SEAFOOD"]),
    _criteria(flavors=["SOUR"], food_forms=["SALAD"]),
    _criteria(flavors=["CLEAN_MILD"], main_ingredients=["VEGETABLE"], food_forms=["SALAD"]),
    _criteria(flavors=["SWEET"], cooking_methods=["BAKED"], food_forms=["DESSERT_BAKERY"]),
    _criteria(textures=["CRISPY"], food_forms=["FRIED_SNACK"], cooking_methods=["FRIED"]),
    _criteria(textures=["CHEWY"], food_forms=["NOODLES"], cooking_methods=["STIR_FRIED"]),
    _criteria(textures=["SOFT"], food_forms=["SOUP"], cooking_methods=["SIMMERED"]),
    _criteria(textures=["THICK_RICH"], food_forms=["STEW_HOTPOT"], cooking_methods=["SIMMERED"]),
)

_NEGATIVE_CASES: tuple[dict[str, Any], ...] = (
    _criteria(flavors=["SPICY"], max_spice_level=1),
    _criteria(food_forms=["NOODLES"], max_spice_level=2),
    _criteria(dietary_filters={"halal_certified_only": True, "vegan": False}),
    _criteria(dietary_filters={"halal_certified_only": False, "vegan": True}),
    _criteria(cuisine_origins=["MEXICAN"], temperatures=["FROZEN"], food_forms=["SOUP"]),
    _criteria(cuisine_origins=["ITALIAN"], food_forms=["STEW_HOTPOT"], temperatures=["FROZEN"]),
    _criteria(cuisine_origins=["JAPANESE"], food_forms=["BREAD"], temperatures=["HOT"]),
    _criteria(cuisine_origins=["AMERICAN"], food_forms=["SOUP"], textures=["CHEWY"]),
    _criteria(
        main_ingredients=["FISH_SEAFOOD"],
        food_forms=["DESSERT_BAKERY"],
        temperatures=["FROZEN"],
    ),
    _criteria(main_ingredients=["BEEF"], temperatures=["FROZEN"], food_forms=["SALAD"]),
)


def build_query_suite() -> list[RecommendationEvalQuery]:
    queries: list[RecommendationEvalQuery] = []
    for category in PREFERENCE_CATEGORIES:
        for option in category.options:
            for locale_suffix, locale in _LOCALE_VARIANTS:
                queries.append(
                    RecommendationEvalQuery(
                        query_id=(
                            f"single-{category.code}-{option.code}-{locale_suffix}".lower()
                        ),
                        cohort="single_option",
                        locale=locale,
                        criteria=_criteria(**{category.code: [option.code]}),
                        expected_outcome="POSITIVE",
                    )
                )

    for index, base in enumerate(_CROSS_CASES, start=1):
        cross_variants: tuple[tuple[EvalLocale, list[str]], ...] = (
            ("English", []),
            ("한국어", []),
            ("English", ["FROM_10000_TO_19999"]),
        )
        for case_variant, (locale, price_bands) in enumerate(
            cross_variants,
            start=1,
        ):
            queries.append(
                RecommendationEvalQuery(
                    query_id=f"cross-{index:02d}-{case_variant}",
                    cohort="cross_category",
                    locale=locale,
                    criteria={**base, "price_bands": price_bands},
                    expected_outcome="POSITIVE",
                )
            )

    for index, criteria in enumerate((*_NEGATIVE_CASES, *_NEGATIVE_CASES), start=1):
        queries.append(
            RecommendationEvalQuery(
                query_id=f"negative-{index:02d}",
                cohort="negative",
                locale="English" if index % 2 else "한국어",
                criteria=criteria,
                expected_outcome="NO_MATCH",
            )
        )

    for index, base in enumerate(_CROSS_CASES[:10], start=1):
        pair_id = f"equivalence-{index:02d}"
        for suffix, locale in _LOCALE_VARIANTS:
            queries.append(
                RecommendationEvalQuery(
                    query_id=f"{pair_id}-{suffix}",
                    cohort="bilingual_equivalence",
                    locale=locale,
                    criteria=base,
                    expected_outcome="POSITIVE",
                    pair_id=pair_id,
                )
            )

    if len(queries) != 200:
        raise RuntimeError(f"RECOMMENDATION_V2_SUITE_SIZE_INVALID:{len(queries)}")
    holdout_ids = {
        item.query_id
        for item in sorted(
            queries,
            key=lambda item: hashlib.sha256(
                f"{SUITE_VERSION}:{item.query_id}".encode()
            ).hexdigest(),
        )[:60]
    }
    result = [
        replace(item, split="HOLDOUT" if item.query_id in holdout_ids else "TUNE")
        for item in queries
    ]
    validate_query_suite(result)
    return result


def validate_query_suite(queries: list[RecommendationEvalQuery]) -> None:
    counts = {
        cohort: sum(item.cohort == cohort for item in queries)
        for cohort in (
            "single_option",
            "cross_category",
            "negative",
            "bilingual_equivalence",
        )
    }
    if counts != {
        "single_option": 100,
        "cross_category": 60,
        "negative": 20,
        "bilingual_equivalence": 20,
    }:
        raise RuntimeError(f"RECOMMENDATION_V2_SUITE_DISTRIBUTION_INVALID:{counts}")
    if sum(item.split == "TUNE" for item in queries) != 140:
        raise RuntimeError("RECOMMENDATION_V2_TUNE_SIZE_INVALID")
    if sum(item.split == "HOLDOUT" for item in queries) != 60:
        raise RuntimeError("RECOMMENDATION_V2_HOLDOUT_SIZE_INVALID")
    option_hits: dict[tuple[str, str], int] = {
        (category.code, option.code): 0
        for category in PREFERENCE_CATEGORIES
        for option in category.options
    }
    for item in queries:
        if item.cohort != "single_option":
            continue
        for category_code, option_codes in item.criteria.items():
            if category_code not in _CRITERIA_LIST_FIELDS:
                continue
            for option_code in option_codes:
                option_hits[(category_code, option_code)] += 1
    if set(option_hits.values()) != {2}:
        raise RuntimeError("RECOMMENDATION_V2_OPTION_COVERAGE_INVALID")
