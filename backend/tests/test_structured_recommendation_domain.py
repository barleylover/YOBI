from __future__ import annotations

import pytest

from app.domain.structured_recommendation import (
    RecommendationCriteriaV2,
    price_matches_bands,
)


@pytest.mark.parametrize(
    ("price", "band", "expected"),
    [
        (9_999, "UNDER_10000", True),
        (10_000, "UNDER_10000", False),
        (10_000, "FROM_10000_TO_19999", True),
        (19_999, "FROM_10000_TO_19999", True),
        (20_000, "FROM_10000_TO_19999", False),
        (20_000, "FROM_20000_TO_29999", True),
        (29_999, "FROM_20000_TO_29999", True),
        (30_000, "FROM_20000_TO_29999", False),
        (30_000, "OVER_30000", True),
    ],
)
def test_price_band_boundaries_are_half_open(
    price: int,
    band: str,
    expected: bool,
) -> None:
    assert price_matches_bands(price, [band]) is expected


def test_empty_or_multiple_price_bands_follow_or_semantics() -> None:
    assert price_matches_bands(15_000, []) is True
    assert price_matches_bands(25_000, ["UNDER_10000", "FROM_20000_TO_29999"]) is True
    assert price_matches_bands(15_000, ["UNKNOWN_PRICE_BAND"]) is False
    assert price_matches_bands(
        15_000,
        ["UNKNOWN_PRICE_BAND", "FROM_10000_TO_19999"],
    ) is True


def test_non_default_spice_ceiling_is_an_explicit_preference() -> None:
    assert RecommendationCriteriaV2(max_spice_level=5).has_explicit_preference is False
    assert RecommendationCriteriaV2(max_spice_level=3).has_explicit_preference is True
