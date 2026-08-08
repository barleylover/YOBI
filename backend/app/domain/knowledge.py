from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class DishRelationType(str, Enum):
    IS_A = "IS_A"
    VARIANT_OF = "VARIANT_OF"
    SERVED_WITH = "SERVED_WITH"
    SIMILAR_TO = "SIMILAR_TO"


class IngredientRole(str, Enum):
    DEFINING = "DEFINING"
    CORE = "CORE"
    COMMON = "COMMON"
    OPTIONAL = "OPTIONAL"
    REGIONAL_VARIANT = "REGIONAL_VARIANT"
    UNKNOWN = "UNKNOWN"


class ClaimStatus(str, Enum):
    CONFIRMED_PRESENT = "CONFIRMED_PRESENT"
    CONFIRMED_ABSENT = "CONFIRMED_ABSENT"
    PRESUMED_PRESENT = "PRESUMED_PRESENT"
    POSSIBLE = "POSSIBLE"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


class SourceScope(str, Enum):
    DISH_CONCEPT = "DISH_CONCEPT"
    MERCHANT = "MERCHANT"
    MENU = "MENU"
    OPTION = "OPTION"
    KITCHEN = "KITCHEN"


class KnowledgeSourceKind(str, Enum):
    SYNTHETIC_WIKI = "SYNTHETIC_WIKI"
    SYNTHETIC_MERCHANT_ORIGIN = "SYNTHETIC_MERCHANT_ORIGIN"
    SYNTHETIC_MENU_FACT = "SYNTHETIC_MENU_FACT"
    LEGACY_MENU_KNOWLEDGE = "LEGACY_MENU_KNOWLEDGE"


class DishConceptAuthoring(BaseModel):
    concept_id: str = Field(pattern=r"^dish_[a-z0-9_]+$")
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    name_ko: str
    name_en: str
    category: str
    parent_concept_id: str | None = None
    version: str
    aliases: list[str] = Field(default_factory=list)
    facets: dict[str, str | list[str]]
    ingredients: list[dict[str, Any]]
    source_kind: KnowledgeSourceKind = KnowledgeSourceKind.SYNTHETIC_WIKI
    is_synthetic: bool = True

    @model_validator(mode="after")
    def validate_ingredients(self) -> DishConceptAuthoring:
        seen: set[str] = set()
        for item in self.ingredients:
            ingredient_id = str(item.get("ingredient_id", ""))
            if not ingredient_id or ingredient_id in seen:
                raise ValueError("Every authored ingredient_id must be present and unique")
            IngredientRole(str(item.get("role")))
            ClaimStatus(str(item.get("status", ClaimStatus.PRESUMED_PRESENT.value)))
            seen.add(ingredient_id)
        return self


class ResolvedIngredientClaim(BaseModel):
    ingredient_id: str
    name_en: str
    role: IngredientRole
    status: ClaimStatus
    source_scope: SourceScope
    source_id: str
    source_version: str
    confidence_band: str
    inherited: bool = False


class ResolvedAllergenClaim(BaseModel):
    allergen_id: str
    code: str
    status: ClaimStatus
    source_scope: SourceScope
    source_id: str
    source_version: str
    confidence_band: str
    inherited: bool = False


class GroundedPassage(BaseModel):
    chunk_id: str
    document_id: str
    concept_id: str | None = None
    facet: str
    content: str
    source_kind: KnowledgeSourceKind
    source_version: str
    is_synthetic: bool = True
    score: float = 0.0


class GroundedMenuKnowledge(BaseModel):
    """Server-owned facts and Wiki passages allowed in menu explanations."""

    menu_id: str
    release_id: str | None = None
    concept_id: str | None = None
    concept_lineage: list[str] = Field(default_factory=list)
    available_facets: list[str] = Field(default_factory=list)
    ingredient_claims: list[ResolvedIngredientClaim] = Field(default_factory=list)
    allergen_claims: list[ResolvedAllergenClaim] = Field(default_factory=list)
    # A merchant declaration is useful evidence about shared-kitchen/cross-contact
    # risk, but it is deliberately kept out of ``ingredient_claims``. Merchant-wide
    # presence must never be presented as proof that the ingredient is in this menu.
    merchant_ingredient_claims: list[ResolvedIngredientClaim] = Field(default_factory=list)
    passages: list[GroundedPassage] = Field(default_factory=list)
    merchant_origin_notes: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    is_synthetic: bool = True

    @property
    def claim_ids(self) -> list[str]:
        values = [claim.source_id for claim in self.ingredient_claims]
        values.extend(claim.source_id for claim in self.allergen_claims)
        values.extend(claim.source_id for claim in self.merchant_ingredient_claims)
        return list(dict.fromkeys(values))
