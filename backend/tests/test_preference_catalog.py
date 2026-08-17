from __future__ import annotations

from typing import Any, cast

import pytest

from app.domain.preference_catalog import (
    ALL_PREFERENCE_CODES,
    PREFERENCE_CATEGORIES,
    PREFERENCE_OPTIONS,
    SUPPORTED_LOCALES,
    PreferenceSupportEvidence,
    localized_preference_catalog,
    preference_query_aliases,
    validated_exposed_codes,
)
from app.domain.recommendation_copy import localized_recommendation_fallback_copy


def test_preference_codes_labels_aliases_and_spice_references_are_complete() -> None:
    assert len(PREFERENCE_CATEGORIES) == 8
    assert len(PREFERENCE_OPTIONS) == 50

    for locale in SUPPORTED_LOCALES:
        catalog = localized_preference_catalog(locale, exposed_codes=ALL_PREFERENCE_CODES)
        categories = cast(list[dict[str, Any]], catalog["categories"])
        assert len(categories) == 8
        assert sum(len(category["options"]) for category in categories) == 50
        assert all(category["label"].strip() for category in categories)
        assert all(
            option["label"].strip() for category in categories for option in category["options"]
        )
        references = cast(list[dict[str, Any]], catalog["spice_references"])
        assert [group["country"] for group in references] == ["KR", "US"]
        assert all(
            [level["level"] for level in group["levels"]] == [1, 2, 3, 4, 5] for group in references
        )

    assert preference_query_aliases("SPICY", "ja")[0] == "辛い"
    assert {"spicy hot chili", "매운맛"} <= set(preference_query_aliases("SPICY", "ja"))


def test_cuisine_exposure_needs_useful_coverage_and_three_reviewed_wiki_documents() -> None:
    rows = [
        PreferenceSupportEvidence(
            category_code="cuisine_origins",
            value_code="KOREAN",
            menu_id=f"menu_{index}",
            merchant_id=f"merchant_{1 + ((index - 1) % 3)}",
            document_id=f"doc_korean_{index}" if index <= 3 else None,
            source_kind="WIKI_PARAGRAPH" if index <= 3 else "MENU_CATALOG",
            review_status="REVIEWED_DEMO" if index <= 3 else "VERIFIED",
        )
        for index in range(1, 16)
    ]
    # Advertising and reviews cannot make a visually attractive but unsupported
    # preference appear in the selector.
    rows.extend(
        PreferenceSupportEvidence(
            category_code="flavors",
            value_code="SPICY",
            menu_id=f"ad_menu_{index}",
            merchant_id=f"ad_merchant_{index}",
            document_id=f"review_{index}",
            source_kind="MERCHANT_AD" if index % 2 else "REVIEW",
            review_status="VERIFIED",
        )
        for index in range(1, 8)
    )

    exposed = validated_exposed_codes(rows)
    catalog = localized_preference_catalog("한국어", exposed_codes=exposed)

    assert exposed == {"KOREAN"}
    assert catalog["locale"] == "ko"
    assert catalog["categories"] == [
        {
            "code": "cuisine_origins",
            "label": "음식 계통",
            "options": [{"code": "KOREAN", "label": "한식"}],
        }
    ]


def test_unknown_coverage_value_fails_instead_of_shipping_a_dead_chip() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_PREFERENCE_SUPPORT"):
        validated_exposed_codes(
            [
                PreferenceSupportEvidence(
                    category_code="flavors",
                    value_code="INVENTED_FLAVOR",
                    menu_id="menu_1",
                    merchant_id="merchant_1",
                    document_id="doc_1",
                    source_kind="WIKI_PARAGRAPH",
                    review_status="REVIEWED_DEMO",
                )
            ]
        )


def test_recommendation_fallback_copy_covers_all_supported_locales() -> None:
    for locale in SUPPORTED_LOCALES:
        copy = localized_recommendation_fallback_copy(locale)
        rendered = [
            copy.comparison_summary,
            copy.price_difference.format(price=9000),
            copy.general_reference.format(passage="source passage"),
            copy.general_reference_unavailable,
            copy.ingredients_unverified,
            copy.spice_reviewed.format(level=2),
            copy.spice_unavailable,
            copy.serves.format(minimum=1, maximum=2),
            copy.serves_unavailable,
            copy.best_for,
            copy.dietary_warning,
            copy.search_selection_reason,
            copy.criteria_default,
            copy.max_spice.format(level=3),
            copy.halal_only,
            copy.vegan,
        ]
        assert all(value.strip() and "=" not in value for value in rendered)
