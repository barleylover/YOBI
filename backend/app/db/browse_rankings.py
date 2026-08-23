from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

SqlDialect = Literal["sqlite", "oracle"]

# The salts deliberately emphasize different suffix positions.  Catalog menu IDs
# commonly share a long prefix, so hashing only the first characters would leave
# every deterministic demo score tied.
_REVIEW_WEIGHTS = (101, 211, 307, 401, 503, 601, 701, 809)
_ORDER_WEIGHTS = (811, 709, 607, 509, 409, 311, 223, 127)
_POPULARITY_WEIGHTS = (131, 337, 547, 751, 953, 1151, 1361, 1571)


# These are the five concepts used by the small English-only feature screen.
# A concept can be absent from the response when the current delivery area or
# the session's hard constraints leave no safe, orderable menu.  The frontend
# keeps that slot visible as unavailable instead of substituting another dish.
KPOP_DEMON_HUNTERS_DEMO_DISHES = (
    "Gimbap",
    "Tteokbokki",
    "Hotteok",
    "Naengmyeon",
    "Eomuk",
)


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


def select_diverse_ranking_rows(rows: Sequence[Any], limit: int) -> list[Any]:
    """Keep prepared ranking order while avoiding a one-merchant demo wall.

    The first pass admits one menu per merchant and one per mapped dish concept.
    The second pass still keeps merchants unique but allows a repeated concept.
    Only the final fill pass allows repeated merchants.  The selected membership
    is finally projected back into the original metric order, so this remains a
    deterministic presentation policy rather than a new popularity model.
    """

    bounded_limit = max(0, limit)
    if bounded_limit == 0:
        return []

    selected: list[Any] = []
    selected_menu_ids: set[str] = set()
    selected_merchants: set[str] = set()
    selected_dishes: set[str] = set()

    def admit(row: Any) -> None:
        menu_id = str(row["menu_id"])
        selected.append(row)
        selected_menu_ids.add(menu_id)
        selected_merchants.add(str(row["merchant_id"]))
        selected_dishes.add(str(row["dish_name"] or row["concept_id"]))

    def in_metric_order() -> list[Any]:
        ordered: list[Any] = []
        emitted_menu_ids: set[str] = set()
        for row in rows:
            menu_id = str(row["menu_id"])
            if menu_id not in selected_menu_ids or menu_id in emitted_menu_ids:
                continue
            ordered.append(row)
            emitted_menu_ids.add(menu_id)
            if len(ordered) == bounded_limit:
                break
        return ordered

    for row in rows:
        merchant_id = str(row["merchant_id"])
        dish_name = str(row["dish_name"] or row["concept_id"])
        if merchant_id in selected_merchants or dish_name in selected_dishes:
            continue
        admit(row)
        if len(selected) == bounded_limit:
            return in_metric_order()

    for row in rows:
        menu_id = str(row["menu_id"])
        merchant_id = str(row["merchant_id"])
        if menu_id in selected_menu_ids or merchant_id in selected_merchants:
            continue
        admit(row)
        if len(selected) == bounded_limit:
            return in_metric_order()

    for row in rows:
        if str(row["menu_id"]) in selected_menu_ids:
            continue
        admit(row)
        if len(selected) == bounded_limit:
            return in_metric_order()

    return in_metric_order()


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
    """Build identical SQLite/Oracle ranking expressions for the prepared demo."""

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
            f"ELSE {order_demo}+COALESCE({menu_review_count},0)*7+"
            f"COALESCE({merchant_review_count},0)*3 END"
        ),
        korean_popularity=(
            f"CASE WHEN {missing_synthetic_source} THEN {popularity_demo} "
            f"ELSE {popularity_demo}+COALESCE({menu_review_count},0)+"
            f"COALESCE({merchant_review_count},0)*5 END"
        ),
        basis=(
            f"CASE WHEN {missing_synthetic_source} "
            "THEN 'DETERMINISTIC_SYNTHETIC_FALLBACK' ELSE 'SOURCE_COUNTS' END"
        ),
    )
