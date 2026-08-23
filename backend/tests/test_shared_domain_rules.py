from __future__ import annotations

import pytest

from app.domain.cart_validation import (
    CART_DIETARY_CONFLICT,
    CART_MENU_NO_LONGER_ELIGIBLE,
    deterministic_korean_order_note,
    structured_v3_cart_error,
)
from app.domain.localization import localization_ids_complete
from app.domain.structured_recommendation import RecommendationCriteriaV2


@pytest.mark.parametrize(
    ("preference", "spice_level", "expected"),
    [
        ("LESS", 2, None),
        ("LESS", 3, CART_MENU_NO_LONGER_ELIGIBLE),
        ("SIMILAR", 3, None),
        ("MORE", 4, None),
        ("MORE", 3, CART_MENU_NO_LONGER_ELIGIBLE),
    ],
)
def test_structured_v3_cart_rule_preserves_spice_semantics(
    preference: str,
    spice_level: int,
    expected: str | None,
) -> None:
    criteria = RecommendationCriteriaV2.model_validate(
        {
            "schema_version": "3",
            "price_range_krw": {"min": 10_000, "max": 20_000},
            "spice_preference": preference,
        }
    )

    assert (
        structured_v3_cart_error(
            criteria,
            price=15_000,
            spice_level=spice_level,
            country_spice_baseline=3,
            halal_fit=True,
            vegan_fit=True,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("spice_level", "expected"),
    [
        (1, CART_MENU_NO_LONGER_ELIGIBLE),
        (2, None),
        (3, None),
        (4, None),
        (5, CART_MENU_NO_LONGER_ELIGIBLE),
    ],
)
def test_structured_v3_cart_rule_uses_inclusive_absolute_spice_range(
    spice_level: int,
    expected: str | None,
) -> None:
    criteria = RecommendationCriteriaV2.model_validate(
        {
            "schema_version": "3",
            "price_range_krw": {"min": 10_000, "max": 20_000},
            "spice_range": {"min": 2, "max": 4},
            # A contradictory legacy value proves the new range takes priority.
            "spice_preference": "LESS",
        }
    )

    assert structured_v3_cart_error(
        criteria,
        price=15_000,
        spice_level=spice_level,
        country_spice_baseline=3,
        halal_fit=True,
        vegan_fit=True,
    ) == expected


def test_structured_v3_cart_rule_keeps_price_before_dietary_error_priority() -> None:
    criteria = RecommendationCriteriaV2.model_validate(
        {
            "schema_version": "3",
            "price_range_krw": {"min": 10_000, "max": 20_000},
            "dietary_filters": {"halal_certified_only": True, "vegan": True},
        }
    )

    assert (
        structured_v3_cart_error(
            criteria,
            price=9_999,
            spice_level=3,
            country_spice_baseline=3,
            halal_fit=False,
            vegan_fit=False,
        )
        == CART_MENU_NO_LONGER_ELIGIBLE
    )
    assert (
        structured_v3_cart_error(
            criteria,
            price=10_000,
            spice_level=3,
            country_spice_baseline=3,
            halal_fit=False,
            vegan_fit=False,
        )
        == CART_DIETARY_CONFLICT
    )


def test_shared_localization_and_note_fallback_rules() -> None:
    assert localization_ids_complete({"g1": "Group"}, {"i1": "Item"}, ["g1"], ["i1"])
    assert not localization_ids_complete({"g1": "Group"}, {}, ["g1"], ["i1"])
    assert deterministic_korean_order_note("Mild, front desk, no cutlery") == (
        "최대한 맵지 않게 부탁드립니다. 호텔 프런트에 맡겨 주세요. "
        "일회용 수저와 포크는 필요 없습니다."
    )


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        (
            "Please leave it at the door. Please include disposable cutlery. "
            "Please ring the bell.",
            "문 앞에 놓아 주세요. 일회용 수저와 포크를 포함해 주세요. "
            "도착하면 벨을 눌러 주세요.",
        ),
        (
            "Please meet me outside. No disposable cutlery. Please do not ring the bell.",
            "건물 밖에서 직접 전달해 주세요. 일회용 수저와 포크는 필요 없습니다. "
            "벨을 누르지 말아 주세요.",
        ),
    ],
)
def test_delivery_preference_note_fallback_covers_handoff_and_switches(
    note: str,
    expected: str,
) -> None:
    assert deterministic_korean_order_note(note) == expected
