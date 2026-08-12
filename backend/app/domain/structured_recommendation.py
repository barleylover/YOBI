from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models import MenuSummary

PreferenceCategoryCode = Literal[
    "cuisine_origins",
    "flavors",
    "main_ingredients",
    "food_forms",
    "temperatures",
    "price_bands",
    "textures",
    "cooking_methods",
]
SpiceReferenceCountry = Literal["KR", "US"]
VeganEvidenceStatus = Literal[
    "LIKELY_FIT",
    "POSSIBLE_WITH_CHECKS",
    "CONFLICT",
    "UNKNOWN",
]


def _normalized_codes(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))


class DietaryFiltersV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    halal_certified_only: bool = False
    vegan: bool = False


class RecommendationCriteriaV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2"] = "2"
    cuisine_origins: list[str] = Field(default_factory=list, max_length=20)
    flavors: list[str] = Field(default_factory=list, max_length=20)
    main_ingredients: list[str] = Field(default_factory=list, max_length=20)
    food_forms: list[str] = Field(default_factory=list, max_length=20)
    temperatures: list[str] = Field(default_factory=list, max_length=20)
    price_bands: list[str] = Field(default_factory=list, max_length=10)
    textures: list[str] = Field(default_factory=list, max_length=20)
    cooking_methods: list[str] = Field(default_factory=list, max_length=20)
    dietary_filters: DietaryFiltersV2 = Field(default_factory=DietaryFiltersV2)
    max_spice_level: int = Field(ge=1, le=5)
    spice_reference_country: SpiceReferenceCountry = "KR"

    @field_validator(
        "cuisine_origins",
        "flavors",
        "main_ingredients",
        "food_forms",
        "temperatures",
        "price_bands",
        "textures",
        "cooking_methods",
    )
    @classmethod
    def normalize_codes(cls, values: list[str]) -> list[str]:
        return _normalized_codes(values)

    @model_validator(mode="after")
    def reject_objective_conflicts(self) -> RecommendationCriteriaV2:
        selected_ingredients = set(self.main_ingredients)
        if self.dietary_filters.halal_certified_only and "PORK" in selected_ingredients:
            raise ValueError("HALAL_PORK_CRITERIA_CONFLICT")
        if self.dietary_filters.vegan and selected_ingredients & {
            "BEEF",
            "PORK",
            "CHICKEN",
            "FISH_SEAFOOD",
        }:
            raise ValueError("VEGAN_ANIMAL_INGREDIENT_CRITERIA_CONFLICT")
        return self

    def subjective_groups(self) -> dict[str, list[str]]:
        return {
            category: list(getattr(self, category))
            for category in (
                "cuisine_origins",
                "flavors",
                "main_ingredients",
                "food_forms",
                "temperatures",
                "textures",
                "cooking_methods",
            )
            if getattr(self, category)
        }

    @property
    def has_explicit_preference(self) -> bool:
        return bool(
            self.subjective_groups()
            or self.price_bands
            or self.dietary_filters.halal_certified_only
            or self.dietary_filters.vegan
        )


class RecommendationCriteriaCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: RecommendationCriteriaV2
    catalog_version: str = Field(min_length=1, max_length=160)
    expected_state_version: int = Field(ge=0)
    request_id: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class RecommendationCriteriaRecord(BaseModel):
    session_id: str
    criteria: RecommendationCriteriaV2
    criteria_version: int = Field(ge=1)
    state_version: int = Field(ge=0)
    criteria_hash: str
    request_id: str
    created_at: datetime


class RecommendationCriteriaCommitResult(BaseModel):
    session_id: str
    criteria: RecommendationCriteriaV2
    criteria_version: int = Field(ge=1)
    state_version: int = Field(ge=0)
    criteria_hash: str
    created_at: datetime


class RecommendationMode(str, Enum):
    INITIAL = "INITIAL"
    SIMILAR = "SIMILAR"
    RETRY = "RETRY"


class RecommendationRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    expected_state_version: int = Field(ge=0)
    criteria_version: int = Field(ge=1)
    mode: RecommendationMode = RecommendationMode.INITIAL


class RecommendationRequestStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    NO_RESULTS = "NO_RESULTS"
    NO_MATCH = "NO_MATCH"
    SEARCH_FALLBACK = "SEARCH_FALLBACK"
    FAILED = "FAILED"
    UNKNOWN_AFTER_DISPATCH = "UNKNOWN_AFTER_DISPATCH"


class RecommendationRequestRecord(BaseModel):
    request_id: str
    session_id: str
    request_hash: str
    criteria_version: int
    mode: RecommendationMode
    status: RecommendationRequestStatus
    state_version: int = Field(ge=0)
    release_family_id: str = Field(min_length=1, max_length=160)
    eligibility_as_of: datetime
    snapshot_id: str | None = None
    evidence_pool_json: list[dict[str, Any]] = Field(default_factory=list)
    result_json: dict[str, Any] | None = None
    dispatch_count: int = Field(default=0, ge=0, le=1)
    failure_code: str | None = None
    created_at: datetime
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None
    duplicate: bool = False


class MerchantCertification(BaseModel):
    certification_id: str
    merchant_id: str
    certification_type: Literal["HALAL"] = "HALAL"
    status: Literal["ACTIVE", "EXPIRED", "REVOKED"]
    issuer: str
    certificate_number: str
    valid_from: datetime
    valid_to: datetime | None = None
    scope_type: Literal["MERCHANT", "MENU"]
    scope_ref: str | None = None
    source_type: str
    source_ref: str
    last_verified_at: datetime
    is_synthetic: bool = True

    @model_validator(mode="after")
    def require_menu_scope_reference(self) -> MerchantCertification:
        if (self.scope_type == "MENU") != bool(self.scope_ref):
            raise ValueError("MENU_CERTIFICATION_SCOPE_REF_MISMATCH")
        return self


class RecommendationReleaseFamily(BaseModel):
    release_family_id: str
    knowledge_release_id: str
    catalog_release_id: str
    preference_catalog_version: str
    spice_reference_version: str
    certification_release_id: str
    embedding_model: str
    embedding_version: str
    status: Literal["LOADING", "READY", "ACTIVE", "RETIRED"]
    activated_at: datetime | None = None


class EvidenceReference(BaseModel):
    evidence_id: str
    evidence_type: Literal[
        "WIKI_PASSAGE",
        "ESSENTIAL_FACT",
        "MENU_FACT",
        "CERTIFICATION",
    ]
    content: str
    score: float | None = None


class CriterionEvidence(BaseModel):
    category_code: PreferenceCategoryCode
    selected_value_code: str
    evidence: list[EvidenceReference] = Field(min_length=1, max_length=20)


class EvidencePoolItem(BaseModel):
    menu: MenuSummary
    knowledge_concept_id: str | None = None
    criterion_evidence: list[CriterionEvidence] = Field(default_factory=list)
    wiki_passages: list[EvidenceReference] = Field(default_factory=list)
    menu_facts: list[EvidenceReference] = Field(default_factory=list)
    halal_certified: bool | None = None
    halal_scope_label: str | None = None
    vegan_status: VeganEvidenceStatus | None = None
    vegan_warning: str | None = None
    retrieval_score: float = 0.0
    knowledge_release_id: str
    catalog_release_id: str
    recommendation_release_family_id: str

    @property
    def menu_id(self) -> str:
        return self.menu.menu_id

    def generation_payload(self) -> dict[str, Any]:
        grouped: dict[str, dict[str, dict[str, Any]]] = {}
        for item in self.criterion_evidence:
            grouped.setdefault(item.category_code, {})[item.selected_value_code] = {
                "evidence_ids": [ref.evidence_id for ref in item.evidence],
                "evidence": [ref.model_dump(mode="json") for ref in item.evidence],
            }
        return {
            "menu_id": self.menu.menu_id,
            "merchant_id": self.menu.merchant_id,
            "display_name": self.menu.name_en,
            "base_price": self.menu.price,
            "spice_level": self.menu.spice_level,
            "halal_certified": self.halal_certified,
            "halal_scope_label": self.halal_scope_label,
            "vegan_status": self.vegan_status,
            "vegan_warning": self.vegan_warning,
            "criterion_evidence": grouped,
            "wiki_passages": [item.model_dump(mode="json") for item in self.wiki_passages],
            "menu_facts": [item.model_dump(mode="json") for item in self.menu_facts],
            "knowledge_release_id": self.knowledge_release_id,
            "catalog_release_id": self.catalog_release_id,
            "recommendation_release_family_id": self.recommendation_release_family_id,
        }


class LiveRecommendationMenuState(BaseModel):
    """Current server-owned projection for a previously generated menu."""

    menu: MenuSummary
    halal_certified: bool | None = None
    halal_scope_label: str | None = None
    vegan_status: VeganEvidenceStatus | None = None
    vegan_warning: str | None = None


class StructuredRecommendationView(BaseModel):
    rank: int = Field(ge=1, le=5)
    menu: MenuSummary
    title: str
    selection_reason: str
    description: str
    matched_criteria: list[dict[str, Any]] = Field(default_factory=list)
    wiki_passages: list[dict[str, Any]] = Field(default_factory=list)
    caution_codes: list[str] = Field(default_factory=list)
    halal_certified: bool | None = None
    halal_scope_label: str | None = None
    vegan_status: VeganEvidenceStatus | None = None
    vegan_warning: str | None = None


class RecommendationBatchV2(BaseModel):
    session_id: str
    request_id: str
    snapshot_id: str | None = None
    state_version: int = Field(ge=0)
    criteria_version: int = Field(ge=1)
    status: Literal[
        "PENDING",
        "RECOMMENDED",
        "NO_MATCH",
        "SEARCH_FALLBACK",
        "FAILED",
    ]
    phase: Literal["RETRIEVING", "GENERATING", "COMPLETE"] | None = None
    criteria_summary: str | None = None
    recommendations: list[StructuredRecommendationView] = Field(default_factory=list)
    unmatched_category_codes: list[str] = Field(default_factory=list)
    failure_code: str | None = None
