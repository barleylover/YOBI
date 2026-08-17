from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SqlDialect = Literal["sqlite", "oracle"]

# The salts deliberately emphasize different suffix positions.  Catalog menu IDs
# commonly share a long prefix, so hashing only the first characters would leave
# every deterministic demo score tied.
_REVIEW_WEIGHTS = (101, 211, 307, 401, 503, 601, 701, 809)
_ORDER_WEIGHTS = (811, 709, 607, 509, 409, 311, 223, 127)
_POPULARITY_WEIGHTS = (131, 337, 547, 751, 953, 1151, 1361, 1571)


@dataclass(frozen=True)
class FoodRankingSql:
    review_count: str
    order_count: str
    korean_popularity: str
    basis: str


def _stable_demo_metric(
    menu_id: str,
    *,
    weights: tuple[int, ...],
    length_weight: int,
    modulus: int,
    floor: int,
) -> int:
    total = len(menu_id) * length_weight
    for offset, weight in enumerate(weights, start=1):
        if offset <= len(menu_id):
            total += ord(menu_id[-offset]) * weight
    return total % modulus + floor


def synthetic_demo_ranking_metrics(menu_id: str) -> dict[str, int]:
    """Return stable, visibly distinct demo scores without claiming source facts."""

    return {
        "review_count": _stable_demo_metric(
            menu_id,
            weights=_REVIEW_WEIGHTS,
            length_weight=907,
            modulus=9_000,
            floor=100,
        ),
        "order_count": _stable_demo_metric(
            menu_id,
            weights=_ORDER_WEIGHTS,
            length_weight=919,
            modulus=90_000,
            floor=1_000,
        ),
        "korean_popularity": _stable_demo_metric(
            menu_id,
            weights=_POPULARITY_WEIGHTS,
            length_weight=977,
            modulus=10_000,
            floor=100,
        ),
    }


def _stable_demo_metric_sql(
    dialect: SqlDialect,
    menu_id: str,
    *,
    weights: tuple[int, ...],
    length_weight: int,
    modulus: int,
    floor: int,
) -> str:
    terms = [f"LENGTH({menu_id})*{length_weight}"]
    for offset, weight in enumerate(weights, start=1):
        if dialect == "sqlite":
            character = f"unicode(substr({menu_id},-{offset},1))"
        else:
            character = f"ASCII(SUBSTR({menu_id},-{offset},1))"
        terms.append(f"COALESCE({character},0)*{weight}")
    return f"(MOD({' + '.join(terms)},{modulus})+{floor})"


def food_ranking_sql(
    dialect: SqlDialect,
    *,
    menu_id: str,
    is_synthetic: str,
    menu_review_count: str,
    merchant_review_count: str,
) -> FoodRankingSql:
    """Build the identical SQLite/Oracle source-first ranking expressions."""

    missing_synthetic_source = (
        f"({is_synthetic}=1 AND COALESCE({menu_review_count},0)=0 "
        f"AND COALESCE({merchant_review_count},0)=0)"
    )
    review_demo = _stable_demo_metric_sql(
        dialect,
        menu_id,
        weights=_REVIEW_WEIGHTS,
        length_weight=907,
        modulus=9_000,
        floor=100,
    )
    order_demo = _stable_demo_metric_sql(
        dialect,
        menu_id,
        weights=_ORDER_WEIGHTS,
        length_weight=919,
        modulus=90_000,
        floor=1_000,
    )
    popularity_demo = _stable_demo_metric_sql(
        dialect,
        menu_id,
        weights=_POPULARITY_WEIGHTS,
        length_weight=977,
        modulus=10_000,
        floor=100,
    )
    return FoodRankingSql(
        review_count=(
            f"CASE WHEN {missing_synthetic_source} THEN {review_demo} "
            f"ELSE COALESCE({menu_review_count},0) END"
        ),
        order_count=(
            f"CASE WHEN {missing_synthetic_source} THEN {order_demo} "
            f"ELSE COALESCE({menu_review_count},0)*7+"
            f"COALESCE({merchant_review_count},0)*3 END"
        ),
        korean_popularity=(
            f"CASE WHEN {missing_synthetic_source} THEN {popularity_demo} "
            f"ELSE COALESCE({menu_review_count},0)+"
            f"COALESCE({merchant_review_count},0)*5 END"
        ),
        basis=(
            f"CASE WHEN {missing_synthetic_source} "
            "THEN 'DETERMINISTIC_SYNTHETIC_FALLBACK' ELSE 'SOURCE_COUNTS' END"
        ),
    )
