from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.dialogue import (
    DialogueAct,
    FallbackReason,
    MealNeedState,
    ReadinessDecision,
    RecommendationResult,
)


class ChatState(str, Enum):
    ONBOARDING = "ONBOARDING"
    DISCOVERY = "DISCOVERY"
    CATEGORY_SHORTLIST = "CATEGORY_SHORTLIST"
    MENU_EXPLANATION = "MENU_EXPLANATION"
    MERCHANT_COMPARISON = "MERCHANT_COMPARISON"
    MENU_SELECTION = "MENU_SELECTION"
    MENU_OPTIONS = "MENU_OPTIONS"
    DELIVERY_ADDRESS = "DELIVERY_ADDRESS"
    DELIVERY_OPTIONS = "DELIVERY_OPTIONS"
    ORDER_REVIEW = "ORDER_REVIEW"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_COMPLETE = "PAYMENT_COMPLETE"
    ORDER_COMPLETE = "ORDER_COMPLETE"
    CLARIFICATION = "CLARIFICATION"
    SAFETY_WARNING = "SAFETY_WARNING"
    ERROR_RECOVERY = "ERROR_RECOVERY"


class EvidenceStatus(str, Enum):
    VERIFIED = "VERIFIED"
    RISK_SIGNAL = "RISK_SIGNAL"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


class ProfileCreate(BaseModel):
    preferred_language: str = "English"
    nationality: str = "United States"
    age_band: str = "Not collected"
    gender: str = "Prefer not to say"
    religion_selection: str = "No specific religion"
    # Legacy persistence fields remain readable for existing sessions, but the
    # current product does not collect or default any allergy rule.
    dietary_rules: list[str] = Field(default_factory=list)
    allergy_severity: Literal["mild", "moderate", "severe"] = "mild"
    spice_tolerance: int = Field(default=1, ge=1, le=3)
    favorite_foods: list[str] = Field(default_factory=list)
    consent_demo_data: bool
    remember_profile: bool = False

    @field_validator("dietary_rules", "favorite_foods")
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values if value.strip()]


class Profile(ProfileCreate):
    profile_id: str
    created_at: datetime


class ProfileUpdate(BaseModel):
    preferred_language: str | None = None
    nationality: str | None = None
    age_band: str | None = None
    gender: str | None = None
    religion_selection: str | None = None
    dietary_rules: list[str] | None = None
    allergy_severity: Literal["mild", "moderate", "severe"] | None = None
    spice_tolerance: int | None = Field(default=None, ge=1, le=3)
    favorite_foods: list[str] | None = None
    consent_demo_data: bool | None = None
    remember_profile: bool | None = None

    @field_validator("dietary_rules", "favorite_foods")
    @classmethod
    def normalize_optional_list(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return [value.strip().lower() for value in values if value.strip()]


class Session(BaseModel):
    session_id: str
    profile_id: str
    state: ChatState
    selected_menu_id: str | None = None
    selected_merchant_id: str | None = None
    dialogue_act: DialogueAct = DialogueAct.COLLECT_NEEDS
    meal_need_state: MealNeedState = Field(default_factory=MealNeedState)
    state_version: int = 0
    created_at: datetime
    updated_at: datetime


class Evidence(BaseModel):
    evidence_id: str
    subject_id: str
    claim_type: str
    status: EvidenceStatus
    source_type: str
    excerpt: str
    updated_at: str
    confidence_band: Literal["high", "medium", "low"]
    suggested_action: str


class MenuSummary(BaseModel):
    menu_id: str
    merchant_id: str
    merchant_name: str
    name_en: str
    name_ko: str
    category: str
    description: str
    cultural_description: str
    price: int
    delivery_fee: int
    eta_min: int
    eta_max: int
    spice_level: int | None = None
    serves_min: int | None = None
    serves_max: int | None = None
    dietary_summary: str
    evidence_status: EvidenceStatus
    match_reasons: list[str]
    risk_hints: list[str]
    semantic_score: float
    evidence_ids: list[str] = Field(default_factory=list)
    grounded_claim_ids: list[str] = Field(default_factory=list)
    grounded_passage_ids: list[str] = Field(default_factory=list)
    is_synthetic: bool = True


class MerchantComparison(BaseModel):
    merchant_id: str
    merchant_name: str
    menu_id: str
    menu_name: str
    price: int
    delivery_fee: int
    eta: str
    portion: str
    flavor: str
    packaging_signal: str
    dietary_status: EvidenceStatus
    dietary_note: str
    best_for: str
    evidence_ids: list[str] = Field(default_factory=list)
    is_synthetic: bool = True


class OptionItem(BaseModel):
    option_item_id: str
    name_en: str
    name_ko: str
    description: str
    price_delta: int
    available: bool
    dietary_conflict: str | None = None
    conflicting_rules: list[str] = Field(default_factory=list)
    halal_certification_preserved: bool | None = None
    vegan_status: Literal[
        "LIKELY_FIT",
        "POSSIBLE_WITH_CHECKS",
        "CONFLICT",
        "UNKNOWN",
    ] | None = None
    vegan_warning: str | None = None


class OptionGroup(BaseModel):
    option_group_id: str
    name_en: str
    name_ko: str
    description: str
    required: bool
    min_select: int
    max_select: int
    items: list[OptionItem]


class Card(BaseModel):
    type: Literal[
        "category_recommendations",
        "menu_recommendations",
        "menu_explanation",
        "dietary_evidence",
        "merchant_comparison",
        "option_question",
        "address_upload",
        "address_confirmation",
        "translated_note",
        "cart_summary",
        "payment_cta",
        "order_complete",
        "error_recovery",
        "preset_collection",
    ]
    title: str
    subtitle: str | None = None
    data: dict[str, Any]


class AssistantTurn(BaseModel):
    message_id: str
    text: str
    state: ChatState
    cards: list[Card] = Field(default_factory=list)
    suggested_replies: list[str] = Field(default_factory=list)
    dialogue_act: DialogueAct = DialogueAct.COLLECT_NEEDS
    readiness: ReadinessDecision | None = None
    recommendation_result: RecommendationResult | None = None
    recommendation_snapshot_id: str | None = None
    state_version: int = 0
    fallback_used: bool = False
    fallback_reason: FallbackReason | None = None
    created_at: datetime


class UserMessage(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    intent: Literal["weekly_ranking", "kpop_demon_hunters"] | None = None
    request_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class AddressCandidate(BaseModel):
    place_id: str
    hotel_name: str
    road_address: str
    postal_code: str
    city: str
    service_area_id: str | None = None
    delivery_hint: str
    confidence: float = Field(ge=0, le=1)
    source: Literal["ocr", "canonical_fixture", "manual"]
    needs_confirmation: bool = True


class CartItemInput(BaseModel):
    menu_id: str
    quantity: int = Field(default=1, ge=1, le=10)
    option_item_ids: list[str] = Field(default_factory=list)
    user_note: str = Field(default="", max_length=500)


class CartItemUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=10)
    option_item_ids: list[str] | None = None
    user_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_change(self) -> CartItemUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one cart item field is required")
        return self


class CartLine(BaseModel):
    cart_item_id: str
    menu_id: str
    merchant_id: str
    menu_name: str
    menu_name_ko: str
    quantity: int
    unit_price: int
    options: list[dict[str, Any]]
    line_total: int


class CartPreview(BaseModel):
    cart_id: str
    session_id: str
    version: int
    items: list[CartLine]
    subtotal: int
    delivery_fee: int
    total_price: int
    missing_slots: list[str]
    dietary_warnings: list[str]
    minimum_order_amount: int = 0
    minimum_order_shortfall: int = 0
    ready_to_checkout: bool
    confirmed: bool


class DeliveryPreferenceInput(BaseModel):
    address_ref_id: str | None = None
    handoff_method: Literal["front_desk", "door", "meet_outside"] = "front_desk"
    cutlery: bool = False
    ring_bell: bool = False
    front_desk: bool = True
    user_note: str = "Please leave it at the hotel front desk."


class CheckoutCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)
    payment_method: Literal["international_card", "apple_pay_demo", "paypal_demo"]


class Checkout(BaseModel):
    checkout_id: str
    cart_id: str
    status: Literal["PENDING", "SUCCEEDED", "FAILED", "CANCELED"]
    amount: int
    payment_method: str
    payment_url: str
    order_id: str | None = None


class Order(BaseModel):
    order_id: str
    checkout_id: str
    order_status: Literal["CONFIRMED", "PREPARING", "ON_THE_WAY", "DELIVERED"]
    estimated_delivery_at: datetime
    summary: dict[str, Any]
    is_synthetic: bool = True
