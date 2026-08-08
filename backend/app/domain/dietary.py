from __future__ import annotations

from app.domain.dialogue import MealNeedState

ALLERGEN_ALIASES: dict[str, set[str]] = {
    "shellfish": {"shellfish", "shellfish_risk"},
    "fish": {"fish", "fish_cake"},
    "milk": {"milk", "dairy"},
    "egg": {"egg"},
    "peanut": {"peanut", "peanuts"},
    "tree_nut": {"tree_nut", "tree_nuts", "nuts"},
    "wheat": {"wheat", "gluten"},
    "soy": {"soy", "soya"},
    "sesame": {"sesame"},
}

# Explicit user-selected religion rules for the demo. These rules are deliberately
# narrow: they are never inferred from nationality, ethnicity, language, or location.
# ``halal`` is a constraint signal, not a certification claim; YOBI must continue to
# describe merchant certification as unknown unless a separate factual source exists.
RELIGION_DIETARY_RULES: dict[str, tuple[str, ...]] = {
    "islam": ("halal", "no_pork"),
    "judaism": ("no_pork", "no_shellfish", "kosher_certification_unverified"),
    "hinduism": ("no_beef",),
}

RULE_EXCLUDED_INGREDIENTS: dict[str, tuple[str, ...]] = {
    "halal": ("pork",),
    "no_pork": ("pork",),
    "no_shellfish": ("shellfish",),
    "no_beef": ("beef",),
}


def selected_allergies(dietary_rules: set[str]) -> set[str]:
    return {
        rule.removesuffix("_allergy")
        for rule in dietary_rules
        if rule.endswith("_allergy") and rule.removesuffix("_allergy") in ALLERGEN_ALIASES
    }


def known_allergen_conflicts(allergen_tags: set[str], dietary_rules: set[str]) -> set[str]:
    normalized_tags = {tag.lower() for tag in allergen_tags}
    return {
        allergy
        for allergy in selected_allergies(dietary_rules)
        if normalized_tags.intersection(ALLERGEN_ALIASES[allergy])
    }


def religion_dietary_rules(religion_selection: str) -> tuple[str, ...]:
    """Return only rules tied to an explicit profile selection.

    Profile nationality is intentionally not accepted by this function, which keeps
    the no-inference boundary visible at the API level.
    """

    return RELIGION_DIETARY_RULES.get(religion_selection.strip().lower(), ())


def apply_profile_constraints(
    state: MealNeedState,
    profile_dietary_rules: list[str],
    religion_selection: str,
) -> MealNeedState:
    """Merge current profile and explicit religion rules into authoritative meal state."""

    updated = state.model_copy(deep=True)
    # Profile rules from the previous turn are not conversation rules. Remove that
    # prior snapshot before installing the current profile so an allergy deleted in
    # profile settings does not remain as a stale hidden constraint.
    prior_profile_rules = set(updated.profile_dietary_rules)
    conversation_rules = [rule for rule in updated.dietary_rules if rule not in prior_profile_rules]
    prior_profile_ingredients = {
        ingredient
        for rule in prior_profile_rules
        for ingredient in RULE_EXCLUDED_INGREDIENTS.get(rule, ())
    }
    updated.excluded_ingredients = [
        ingredient
        for ingredient in updated.excluded_ingredients
        if ingredient not in prior_profile_ingredients
    ]
    profile_rules = list(
        dict.fromkeys(
            [
                *(rule.strip().lower() for rule in profile_dietary_rules if rule.strip()),
                *religion_dietary_rules(religion_selection),
            ]
        )
    )
    updated.profile_dietary_rules = profile_rules
    updated.dietary_rules = list(dict.fromkeys([*conversation_rules, *profile_rules]))
    for rule in updated.dietary_rules:
        for ingredient in RULE_EXCLUDED_INGREDIENTS.get(rule, ()):
            if ingredient not in updated.excluded_ingredients:
                updated.excluded_ingredients.append(ingredient)
    return updated
