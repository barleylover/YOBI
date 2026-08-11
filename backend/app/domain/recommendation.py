from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from math import ceil

from app.domain.dialogue import MealNeedState
from app.domain.models import MenuSummary

_SOUP_CATEGORIES = {
    "chicken kalguksu",
    "samgyetang",
    "sundubu",
    "kimchi stew",
    "gukbap",
    "seolleongtang",
    "eomuk",
}

_PREFERENCE_ALIASES: dict[str, tuple[str, ...]] = {
    "cold": ("cold", "chilled", "refreshing", "bright broth", "naengmyeon", "차가운", "시원한"),
    "warm": ("warm", "hot", "broth", "soup", "stew", "griddled", "따뜻한", "뜨거운"),
    "chewy": ("chewy", "springy", "rice cake", "쫄깃한"),
    "crispy": ("crispy", "crisp", "crunchy", "fried", "바삭한", "아삭한"),
    "soft": ("soft", "silky", "tender", "부드러운"),
    "savory": ("savory", "savoury", "umami", "broth", "black bean", "고소한", "감칠맛"),
    "sweet": ("sweet", "sweeter", "sugary", "달콤한"),
    "creamy": ("creamy", "cream", "milky", "크리미한", "부드러운"),
    "spicy": ("spicy", "hot sauce", "gochujang", "chilli", "chili", "매운"),
    "light": ("light", "refreshing", "bright", "clean", "담백한", "가벼운"),
    "hearty": ("hearty", "filling", "rich", "whole chicken", "든든한", "푸짐한"),
}

_TEMPERATURE_CONTRADICTIONS: dict[str, tuple[str, ...]] = {
    "cold": ("warm", "piping hot", "bubbling hot", "griddled", "따뜻한", "뜨거운"),
    "warm": ("cold", "chilled", "iced", "차가운", "시원한"),
}

WIKI_SEMANTIC_WEIGHT = 0.60
STRUCTURED_PREFERENCE_WEIGHT = 0.25
OPERATIONAL_MENU_WEIGHT = 0.15
_RETRIEVAL_WEIGHT = WIKI_SEMANTIC_WEIGHT + OPERATIONAL_MENU_WEIGHT


def _searchable_text(menu: MenuSummary) -> str:
    return " ".join(
        (menu.category, menu.name_en, menu.name_ko, menu.description, menu.cultural_description)
    ).lower()


def _contains_term(text: str, term: str) -> bool:
    searchable = text
    if term == "sweet":
        searchable = searchable.replace("sweet-potato", "").replace("sweet potato", "")
    return bool(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", searchable))


def _matches_preference(text: str, preference: str) -> bool:
    normalized = preference.strip().lower()
    if not normalized:
        return False
    aliases = _PREFERENCE_ALIASES.get(normalized, (normalized,))
    return any(_contains_term(text, alias) for alias in aliases)


def _structured_preference_score(
    menu: MenuSummary,
    state: MealNeedState,
) -> tuple[float, list[str]]:
    text = _searchable_text(menu)
    scores: list[float] = []
    reasons: list[str] = []
    for preference in state.temperature_preferences:
        contradictions = _TEMPERATURE_CONTRADICTIONS.get(preference.lower(), ())
        if any(_contains_term(text, term) for term in contradictions):
            scores.append(0.0)
            continue
        if _matches_preference(text, preference):
            scores.append(1.0)
            reasons.append(f"Matches your {preference.lower()} preference")
        else:
            scores.append(0.45)

    structured_preferences = (
        state.texture_preferences,
        state.flavor_preferences,
        state.preferred_categories,
        state.positive_preferences,
    )
    for preferences in structured_preferences:
        for preference in preferences:
            if _matches_preference(text, preference):
                scores.append(1.0)
                reasons.append(f"Matches your {preference.lower()} preference")
            else:
                scores.append(0.45)

    if not scores:
        return 0.5, reasons
    return sum(scores) / len(scores), reasons


def operational_menu_signal(
    menu_similarity: float,
    *,
    price: int,
    budget: int,
    delivery_fee: int,
    eta_max: int,
) -> float:
    """Score only stable menu relevance and synthetic delivery operating data."""

    safe_budget = max(budget, 1)
    price_fit = 1.0 - 0.5 * min(price / safe_budget, 1.0)
    fee_fit = 1.0 - min(max(delivery_fee, 0), 6000) / 6000
    eta_fit = 1.0 - min(max(eta_max - 15, 0), 75) / 75
    score = (
        0.65 * max(0.0, min(1.0, menu_similarity))
        + 0.10 * price_fit
        + 0.10 * fee_fit
        + 0.15 * eta_fit
    )
    return max(0.0, min(1.0, score))


def wiki_operational_retrieval_score(
    wiki_similarity: float,
    operational_signal: float,
) -> float:
    """Normalize the 60% Wiki + 15% operational retrieval stage to ``[0, 1]``."""

    weighted = (
        WIKI_SEMANTIC_WEIGHT * max(0.0, min(1.0, wiki_similarity))
        + OPERATIONAL_MENU_WEIGHT * max(0.0, min(1.0, operational_signal))
    )
    return weighted / _RETRIEVAL_WEIGHT


def final_hybrid_recommendation_score(
    retrieval_score: float,
    structured_preference_score: float,
) -> float:
    """Compose the final 60/25/15 Wiki, preference, and operational score."""

    return max(
        0.0,
        min(
            1.0,
            _RETRIEVAL_WEIGHT * retrieval_score
            + STRUCTURED_PREFERENCE_WEIGHT * structured_preference_score,
        ),
    )


def _diversified_order(candidates: Sequence[MenuSummary], limit: int) -> list[MenuSummary]:
    remaining = list(candidates)
    selected: list[MenuSummary] = []
    category_counts: Counter[str] = Counter()
    merchant_counts: Counter[str] = Counter()
    while remaining and len(selected) < limit:
        best_index = max(
            range(len(remaining)),
            key=lambda index: (
                remaining[index].semantic_score
                - 0.10 * category_counts[remaining[index].category.lower()]
                - 0.04 * merchant_counts[remaining[index].merchant_id],
                remaining[index].semantic_score,
                -remaining[index].price,
            ),
        )
        menu = remaining.pop(best_index)
        selected.append(menu)
        category_counts[menu.category.lower()] += 1
        merchant_counts[menu.merchant_id] += 1
    return selected


def rerank_menu_candidates(
    candidates: Sequence[MenuSummary],
    state: MealNeedState,
    merchant_areas: Mapping[str, str],
    limit: int,
) -> list[MenuSummary]:
    """Apply the shared deterministic post-retrieval recommendation contract."""

    excluded_categories = {
        value.strip().lower() for value in state.excluded_categories if value.strip()
    }
    rejected = set(state.rejected_menu_ids)
    ranked: list[MenuSummary] = []
    for menu in candidates:
        category = menu.category.lower()
        if menu.menu_id in rejected:
            continue
        if "soup" in excluded_categories and category in _SOUP_CATEGORIES:
            continue
        if any(excluded in category for excluded in excluded_categories if excluded != "soup"):
            continue
        if state.service_area_id and merchant_areas.get(menu.merchant_id) != state.service_area_id:
            continue

        searchable = _searchable_text(menu)
        if any(_matches_preference(searchable, value) for value in state.negative_preferences):
            continue

        portions = ceil((state.party_size or 1) / max(menu.serves_max, 1))
        estimated_total = menu.price * portions
        if state.budget_krw is not None and estimated_total > state.budget_krw:
            continue

        structured_score, preference_reasons = _structured_preference_score(menu, state)
        reasons = list(dict.fromkeys([*menu.match_reasons, *preference_reasons]))
        if state.party_size is not None:
            party_label = "person" if state.party_size == 1 else "people"
            reasons.append(
                f"Plan {portions} portion{'s' if portions != 1 else ''} "
                f"for {state.party_size} {party_label} (estimated ₩{estimated_total:,})"
            )
        ranked.append(
            menu.model_copy(
                update={
                    "semantic_score": round(
                        final_hybrid_recommendation_score(
                            menu.semantic_score,
                            structured_score,
                        ),
                        4,
                    ),
                    "match_reasons": reasons,
                }
            )
        )

    ranked.sort(key=lambda item: (item.semantic_score, -item.price), reverse=True)
    return _diversified_order(ranked, min(limit, len(ranked)))
