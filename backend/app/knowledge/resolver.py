from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.domain.dialogue import ConstraintStrictness, MealNeedState
from app.domain.dietary import ALLERGEN_ALIASES, selected_allergies
from app.domain.knowledge import (
    ClaimStatus,
    IngredientRole,
    ResolvedAllergenClaim,
    ResolvedIngredientClaim,
    SourceScope,
)

PRESENT_STATUSES = {ClaimStatus.CONFIRMED_PRESENT, ClaimStatus.PRESUMED_PRESENT}
ALLERGY_RISK_STATUSES = PRESENT_STATUSES | {ClaimStatus.POSSIBLE, ClaimStatus.CONFLICTING}

INGREDIENT_ALIASES: dict[str, set[str]] = {
    "pork": {"ingredient_pork", "ingredient_pork_broth", "ingredient_pork_bone"},
    "shellfish": {
        "ingredient_shellfish",
        "ingredient_shrimp",
        "ingredient_crab",
        "ingredient_shellfish_stock",
    },
    "beef": {"ingredient_beef", "ingredient_beef_bone", "ingredient_beef_broth"},
    "egg": {"ingredient_egg"},
    "milk": {"ingredient_milk", "ingredient_dairy", "ingredient_dairy_cream", "ingredient_cheese"},
    "fish": {"ingredient_fish", "ingredient_fish_cake", "ingredient_fish_stock"},
    "chicken": {"ingredient_chicken", "ingredient_chicken_broth"},
    "wheat": {"ingredient_wheat", "ingredient_wheat_noodles", "ingredient_flour"},
    "soy": {"ingredient_soy", "ingredient_soy_sauce", "ingredient_gochujang"},
    "sesame": {"ingredient_sesame", "ingredient_sesame_oil"},
    "peanut": {"ingredient_peanut", "ingredient_peanuts"},
    "tree_nut": {"ingredient_tree_nut", "ingredient_tree_nuts", "ingredient_nuts"},
}

ANIMAL_INGREDIENTS = set().union(
    INGREDIENT_ALIASES["pork"],
    INGREDIENT_ALIASES["shellfish"],
    INGREDIENT_ALIASES["beef"],
    INGREDIENT_ALIASES["fish"],
    INGREDIENT_ALIASES["chicken"],
)
VEGAN_INGREDIENTS = ANIMAL_INGREDIENTS | INGREDIENT_ALIASES["egg"] | INGREDIENT_ALIASES["milk"]


def _status(value: object) -> ClaimStatus:
    normalized = str(value or "UNKNOWN").upper()
    aliases = {
        "PRESENT": ClaimStatus.CONFIRMED_PRESENT,
        "VERIFIED": ClaimStatus.CONFIRMED_PRESENT,
        "RISK_SIGNAL": ClaimStatus.POSSIBLE,
        "ABSENT": ClaimStatus.CONFIRMED_ABSENT,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return ClaimStatus(normalized)
    except ValueError:
        return ClaimStatus.UNKNOWN


def _role(value: object) -> IngredientRole:
    try:
        return IngredientRole(str(value or "UNKNOWN").upper())
    except ValueError:
        return IngredientRole.UNKNOWN


def resolve_ingredient_claims(
    wiki_rows: Iterable[Mapping[str, Any]],
    menu_rows: Iterable[Mapping[str, Any]],
    option_rows: Iterable[Mapping[str, Any]] = (),
) -> list[ResolvedIngredientClaim]:
    """Resolve inherited Wiki defaults, then menu facts, then selected option effects.

    Missing rows never become CONFIRMED_ABSENT. More specific concept claims win over
    ancestors; menu and option facts are the only layers allowed to override Wiki defaults.
    """

    resolved: dict[str, ResolvedIngredientClaim] = {}
    sorted_wiki = sorted(wiki_rows, key=lambda row: int(row.get("depth") or 0))
    for row in sorted_wiki:
        ingredient_id = str(row["ingredient_id"])
        if ingredient_id in resolved:
            continue
        depth = int(row.get("depth") or 0)
        resolved[ingredient_id] = ResolvedIngredientClaim(
            ingredient_id=ingredient_id,
            name_en=str(row.get("name_en") or ingredient_id.removeprefix("ingredient_")),
            role=_role(row.get("ingredient_role")),
            status=_status(row.get("assertion_status")),
            source_scope=SourceScope.DISH_CONCEPT,
            source_id=str(row.get("claim_id") or f"wiki:{ingredient_id}"),
            source_version=str(row.get("source_version") or row.get("release_id") or "unknown"),
            confidence_band="high"
            if _role(row.get("ingredient_role")) in {IngredientRole.DEFINING, IngredientRole.CORE}
            else "medium",
            inherited=depth > 0,
        )

    for row in menu_rows:
        ingredient_id = str(row["ingredient_id"])
        previous = resolved.get(ingredient_id)
        resolved[ingredient_id] = ResolvedIngredientClaim(
            ingredient_id=ingredient_id,
            name_en=str(
                row.get("name_en")
                or (previous.name_en if previous else ingredient_id.removeprefix("ingredient_"))
            ),
            role=_role(row.get("ingredient_role") or (previous.role.value if previous else None)),
            status=_status(row.get("status")),
            source_scope=SourceScope.MENU,
            source_id=str(row.get("source_id") or f"menu:{ingredient_id}"),
            source_version=str(row.get("source_version") or "catalog"),
            confidence_band=str(row.get("confidence_band") or "high"),
            inherited=False,
        )

    for row in option_rows:
        ingredient_id = str(row["ingredient_id"])
        previous = resolved.get(ingredient_id)
        effect = str(row.get("effect") or "").upper()
        assertion = row.get("assertion_status")
        status = _status(assertion)
        if effect == "REMOVE" and status is not ClaimStatus.UNKNOWN:
            status = ClaimStatus.CONFIRMED_ABSENT
        elif effect == "ADD" and status is ClaimStatus.CONFIRMED_ABSENT:
            status = ClaimStatus.CONFIRMED_PRESENT
        resolved[ingredient_id] = ResolvedIngredientClaim(
            ingredient_id=ingredient_id,
            name_en=str(
                row.get("name_en")
                or (previous.name_en if previous else ingredient_id.removeprefix("ingredient_"))
            ),
            role=previous.role if previous else IngredientRole.OPTIONAL,
            status=status,
            source_scope=SourceScope.OPTION,
            source_id=str(
                row.get("source_id") or row.get("option_item_id") or f"option:{ingredient_id}"
            ),
            source_version=str(row.get("source_version") or row.get("release_id") or "catalog"),
            confidence_band="high",
            inherited=False,
        )
    return sorted(resolved.values(), key=lambda claim: claim.ingredient_id)


def resolve_allergen_claims(
    wiki_rows: Iterable[Mapping[str, Any]],
    menu_rows: Iterable[Mapping[str, Any]],
) -> list[ResolvedAllergenClaim]:
    resolved: dict[str, ResolvedAllergenClaim] = {}
    for row in sorted(wiki_rows, key=lambda item: int(item.get("depth") or 0)):
        allergen_id = str(row["allergen_id"])
        if allergen_id in resolved:
            continue
        depth = int(row.get("depth") or 0)
        resolved[allergen_id] = ResolvedAllergenClaim(
            allergen_id=allergen_id,
            code=str(row.get("code") or allergen_id.removeprefix("allergen_")),
            status=_status(row.get("assertion_status")),
            source_scope=SourceScope.DISH_CONCEPT,
            source_id=str(row.get("claim_id") or f"wiki:{allergen_id}"),
            source_version=str(row.get("source_version") or row.get("release_id") or "unknown"),
            confidence_band="high"
            if _status(row.get("assertion_status")) in PRESENT_STATUSES
            else "medium",
            inherited=depth > 0,
        )
    for row in menu_rows:
        allergen_id = str(row["allergen_id"])
        resolved[allergen_id] = ResolvedAllergenClaim(
            allergen_id=allergen_id,
            code=str(row.get("code") or allergen_id.removeprefix("allergen_")),
            status=_status(row.get("status")),
            source_scope=SourceScope.MENU,
            source_id=str(row.get("source_id") or row.get("evidence_id") or f"menu:{allergen_id}"),
            source_version=str(row.get("source_version") or "catalog"),
            confidence_band="high" if _status(row.get("status")) in PRESENT_STATUSES else "medium",
            inherited=False,
        )
    return sorted(resolved.values(), key=lambda claim: claim.allergen_id)


def resolve_merchant_ingredient_claims(
    rows: Iterable[Mapping[str, Any]],
) -> list[ResolvedIngredientClaim]:
    """Resolve merchant-wide declarations without promoting them to menu facts."""

    claims = [
        ResolvedIngredientClaim(
            ingredient_id=str(row["ingredient_id"]),
            name_en=str(row.get("name_en") or str(row["ingredient_id"]).removeprefix("ingredient_")),
            role=IngredientRole.UNKNOWN,
            status=_status(row.get("status")),
            source_scope=SourceScope.MERCHANT,
            source_id=str(
                row.get("source_id")
                or row.get("declaration_id")
                or f"merchant:{row['ingredient_id']}"
            ),
            source_version=str(row.get("source_version") or row.get("release_id") or "catalog"),
            confidence_band="high"
            if _status(row.get("status")) is ClaimStatus.CONFIRMED_PRESENT
            else "medium",
            inherited=False,
        )
        for row in rows
    ]
    return sorted(claims, key=lambda claim: (claim.ingredient_id, claim.source_id))


def ingredient_constraint_conflicts(
    claims: Iterable[ResolvedIngredientClaim], state: MealNeedState
) -> list[str]:
    excluded_ids: set[str] = set()
    for excluded in state.excluded_ingredients:
        excluded_ids.update(
            INGREDIENT_ALIASES.get(excluded.lower(), {f"ingredient_{excluded.lower()}"})
        )
    rules = set(state.dietary_rules) | set(state.profile_dietary_rules)
    if "vegan" in rules:
        excluded_ids.update(VEGAN_INGREDIENTS)
    elif "vegetarian" in rules:
        excluded_ids.update(ANIMAL_INGREDIENTS)
    if "halal" in rules:
        excluded_ids.update(INGREDIENT_ALIASES["pork"])
    if "no_pork" in rules:
        excluded_ids.update(INGREDIENT_ALIASES["pork"])
    if "no_shellfish" in rules:
        excluded_ids.update(INGREDIENT_ALIASES["shellfish"])
    if "no_beef" in rules:
        excluded_ids.update(INGREDIENT_ALIASES["beef"])
    return sorted(
        claim.ingredient_id
        for claim in claims
        if claim.ingredient_id in excluded_ids and claim.status in ALLERGY_RISK_STATUSES
    )


def allergen_constraint_conflicts(
    claims: Iterable[ResolvedAllergenClaim],
    state: MealNeedState,
    *,
    ignored_allergies: set[str] | None = None,
) -> list[str]:
    ignored = ignored_allergies or set()
    allergy_codes = {
        rule.removesuffix("_allergy")
        for rule in (*state.dietary_rules, *state.profile_dietary_rules)
        if rule.endswith("_allergy") and rule.removesuffix("_allergy") not in ignored
    }
    return sorted(
        claim.allergen_id
        for claim in claims
        if claim.status in ALLERGY_RISK_STATUSES
        and any(claim.code in ALLERGEN_ALIASES.get(code, {code}) for code in allergy_codes)
    )


def merchant_cross_contact_conflicts(
    claims: Iterable[ResolvedIngredientClaim],
    state: MealNeedState,
    *,
    allergy_severity: str,
) -> list[str]:
    """Treat merchant-wide ingredients only as conservative cross-contact signals.

    The declaration never proves menu presence. It becomes a hard exclusion only for
    strict requests, explicit religious/dietary rules, or severe allergies. Moderate
    and exploratory preference matching can still surface the menu with the merchant
    evidence shown separately by ``GroundedMenuKnowledge``.
    """

    active = [claim for claim in claims if claim.status in ALLERGY_RISK_STATUSES]
    if not active:
        return []
    rules = set(state.dietary_rules) | set(state.profile_dietary_rules)
    strict = state.strictness is ConstraintStrictness.STRICT
    excluded_ids: set[str] = set()
    if strict:
        for excluded in state.excluded_ingredients:
            excluded_ids.update(
                INGREDIENT_ALIASES.get(excluded.lower(), {f"ingredient_{excluded.lower()}"})
            )
    if rules.intersection({"halal", "no_pork"}):
        excluded_ids.update(INGREDIENT_ALIASES["pork"])
    if "no_shellfish" in rules:
        excluded_ids.update(INGREDIENT_ALIASES["shellfish"])
    if "no_beef" in rules:
        excluded_ids.update(INGREDIENT_ALIASES["beef"])
    if strict and "vegan" in rules:
        excluded_ids.update(VEGAN_INGREDIENTS)
    elif strict and "vegetarian" in rules:
        excluded_ids.update(ANIMAL_INGREDIENTS)
    if allergy_severity == "severe":
        for allergy in selected_allergies(rules):
            excluded_ids.update(INGREDIENT_ALIASES.get(allergy, set()))
    return sorted(
        f"merchant_cross_contact:{claim.ingredient_id}"
        for claim in active
        if claim.ingredient_id in excluded_ids
    )


def severe_allergy_conflicts(
    ingredient_claims: Iterable[ResolvedIngredientClaim],
    allergen_claims: Iterable[ResolvedAllergenClaim],
    dietary_rules: Iterable[str],
    *,
    shellfish_mastered_absence: bool = False,
) -> list[str]:
    """Fail closed when a severe selected allergy lacks explicit absence evidence.

    Known Wiki/menu risk wins for ordinary allergy claims. The one demo exception is
    the existing menu-specific ``shellfish_sauce_absent`` mastered path: it can override
    a general Wiki default, but never a menu/option-specific shellfish risk. Missing
    claims are never converted to absence.
    """

    ingredients = list(ingredient_claims)
    allergens = list(allergen_claims)
    conflicts: list[str] = []
    for allergy in sorted(selected_allergies(set(dietary_rules))):
        allergen_aliases = ALLERGEN_ALIASES.get(allergy, {allergy})
        matching_allergens = [claim for claim in allergens if claim.code in allergen_aliases]
        matching_ingredients = [
            claim
            for claim in ingredients
            if claim.ingredient_id in INGREDIENT_ALIASES.get(allergy, set())
        ]
        if allergy == "shellfish" and shellfish_mastered_absence:
            specific_allergen_risk = any(
                claim.status in ALLERGY_RISK_STATUSES
                and claim.source_scope in {SourceScope.MENU, SourceScope.OPTION}
                for claim in matching_allergens
            )
            specific_ingredient_risk = any(
                claim.status in ALLERGY_RISK_STATUSES
                and claim.source_scope in {SourceScope.MENU, SourceScope.OPTION}
                for claim in matching_ingredients
            )
            if specific_allergen_risk or specific_ingredient_risk:
                conflicts.append("shellfish:known_menu_or_option_risk")
            continue
        if any(claim.status in ALLERGY_RISK_STATUSES for claim in matching_allergens):
            conflicts.append(f"{allergy}:known_allergen_risk")
            continue
        if any(claim.status in ALLERGY_RISK_STATUSES for claim in matching_ingredients):
            conflicts.append(f"{allergy}:known_ingredient_risk")
            continue
        if not any(claim.status is ClaimStatus.CONFIRMED_ABSENT for claim in matching_allergens):
            conflicts.append(f"{allergy}:absence_unverified")
    return conflicts


SOUP_CATEGORIES = {
    "chicken kalguksu",
    "samgyetang",
    "sundubu",
    "kimchi stew",
    "gukbap",
    "seolleongtang",
    "eomuk",
}


def category_constraint_conflicts(category: str, state: MealNeedState) -> list[str]:
    normalized = category.strip().lower()
    conflicts: list[str] = []
    for excluded in {item.strip().lower() for item in state.excluded_categories}:
        if excluded == "soup" and normalized in SOUP_CATEGORIES:
            conflicts.append("category:soup")
        elif excluded and excluded in normalized:
            conflicts.append(f"category:{excluded}")
    return conflicts
