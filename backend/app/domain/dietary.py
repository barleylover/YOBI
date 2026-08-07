from __future__ import annotations

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
