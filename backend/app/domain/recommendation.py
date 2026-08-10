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
    "cold": ("cold", "chilled", "refreshing", "bright broth", "naengmyeon"),
    "warm": ("warm", "hot", "broth", "soup", "stew", "griddled"),
    "chewy": ("chewy", "springy", "rice cake"),
    "crispy": ("crispy", "crisp", "crunchy", "fried"),
    "soft": ("soft", "silky", "tender"),
    "savory": ("savory", "savoury", "umami", "broth", "black bean"),
    "sweet": ("sweet", "sweeter", "sugary"),
    "creamy": ("creamy", "cream", "milky"),
    "spicy": ("spicy", "hot sauce", "gochujang", "chilli", "chili"),
    "light": ("light", "refreshing", "bright", "clean"),
    "hearty": ("hearty", "filling", "rich", "whole chicken"),
}

_TEMPERATURE_CONTRADICTIONS: dict[str, tuple[str, ...]] = {
    "cold": ("warm", "piping hot", "bubbling hot", "griddled"),
    "warm": ("cold", "chilled", "iced"),
}


def _searchable_text(menu: MenuSummary) -> str:
    return " ".join(
        (menu.category, menu.name_en, menu.description, menu.cultural_description)
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


def _preference_score(
    menu: MenuSummary,
    state: MealNeedState,
) -> tuple[float, list[str]]:
    text = _searchable_text(menu)
    score_delta = 0.0
    reasons: list[str] = []
    for preference in state.temperature_preferences:
        contradictions = _TEMPERATURE_CONTRADICTIONS.get(preference.lower(), ())
        if any(_contains_term(text, term) for term in contradictions):
            score_delta -= 0.18
            continue
        if _matches_preference(text, preference):
            score_delta += 0.24
            reasons.append(f"Matches your {preference.lower()} preference")

    weighted_preferences = (
        (state.texture_preferences, 0.10),
        (state.flavor_preferences, 0.14),
        (state.preferred_categories, 0.10),
        (state.positive_preferences, 0.08),
    )
    for preferences, weight in weighted_preferences:
        for preference in preferences:
            if _matches_preference(text, preference):
                score_delta += weight
                reasons.append(f"Matches your {preference.lower()} preference")

    return score_delta, reasons


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

        score_delta, preference_reasons = _preference_score(menu, state)
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
                        max(0.0, min(1.0, menu.semantic_score + score_delta)), 4
                    ),
                    "match_reasons": reasons,
                }
            )
        )

    ranked.sort(key=lambda item: (item.semantic_score, -item.price), reverse=True)
    return _diversified_order(ranked, min(limit, len(ranked)))
