from __future__ import annotations

# SQLite and Oracle must enforce one demo/release cardinality contract. The fixture
# corpus is bounded at 600 menus; retain every hard-filtered candidate until the
# structured reranker has applied the complete score instead of truncating early.
RECOMMENDATION_CANDIDATE_CAP = 600
RECOMMENDATION_PASSAGE_LIMIT = 3
EXPECTED_MAPPED_MENUS = 600
EXPECTED_ORIGIN_DECLARATIONS = 13
EXPECTED_MERCHANT_INGREDIENTS = 120
EXPECTED_OPTION_EFFECTS = 4

EXPECTED_RUNTIME_COUNTS = {
    "service_area": 3,
    "menu_category": 100,
    "merchant": 60,
    "menu": 600,
    "menu_knowledge": 600,
    "menu_option_group": 1202,
    "menu_option_item": 2405,
    "review_snippet": 2400,
    "evidence": 1200,
    "address_place": 20,
    "ingredient": 48,
    "menu_ingredient": 565,
    "allergen": 8,
    "menu_allergen": 48,
    "dietary_attribute": 15,
    "menu_dietary_attribute": 1217,
    "option_dietary_conflict": 1,
}

EXTERNAL_CATALOG_COUNT_TABLES = (
    "catalog_source_payload",
    "menu",
    "menu_option_group",
    "menu_option_item",
    "menu_source_detail",
    "menu_source_section",
    "menu_source_section_item",
    "merchant",
    "merchant_source_detail",
    "option_group_source_detail",
    "source_option",
)

UPGRADE_RETAINED_RUNTIME_COUNT_KEYS = frozenset(
    {"allergen", "dietary_attribute", "ingredient", "menu_allergen"}
)


def runtime_counts_compatible(counts: dict[str, int]) -> bool:
    """Allow additive retained reference rows while keeping fixture tables exact."""

    return set(counts) == set(EXPECTED_RUNTIME_COUNTS) and all(
        actual >= expected if key in UPGRADE_RETAINED_RUNTIME_COUNT_KEYS else actual == expected
        for key, expected in EXPECTED_RUNTIME_COUNTS.items()
        for actual in (counts[key],)
    )
