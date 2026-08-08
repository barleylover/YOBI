from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DialogueAct(str, Enum):
    """Server-owned meaning of the current conversational turn."""

    GREET = "GREET"
    COLLECT_NEEDS = "COLLECT_NEEDS"
    HOLD_RECOMMENDATION = "HOLD_RECOMMENDATION"
    CONFIRM_NEEDS = "CONFIRM_NEEDS"
    REQUEST_RECOMMENDATION = "REQUEST_RECOMMENDATION"
    RECOMMEND = "RECOMMEND"
    REQUEST_EXPLANATION = "REQUEST_EXPLANATION"
    EXPLAIN = "EXPLAIN"
    COMPARE = "COMPARE"
    REVISE = "REVISE"
    REJECT = "REJECT"
    SELECT = "SELECT"
    ORDER_ACTION = "ORDER_ACTION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    ERROR_RECOVERY = "ERROR_RECOVERY"


class ConstraintStrictness(str, Enum):
    STRICT = "STRICT"
    MODERATE = "MODERATE"
    EXPLORATORY = "EXPLORATORY"


class RecommendationReadiness(str, Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    EXPLICIT_REQUEST = "EXPLICIT_REQUEST"
    HELD = "HELD"


class FallbackReason(str, Enum):
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_TOOL_ARGUMENT = "INVALID_TOOL_ARGUMENT"
    NO_TOOL_RESPONSE = "NO_TOOL_RESPONSE"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    GROUNDING_REJECTED = "GROUNDING_REJECTED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


class MealNeedState(BaseModel):
    """Cumulative, server-validated meal needs for one chat session."""

    schema_version: int = 1
    turn_count: int = 0
    occasion: str | None = None
    party_size: int | None = Field(default=None, ge=1, le=20)
    budget_krw: int | None = Field(default=None, ge=1000, le=1_000_000)
    max_spiciness: int | None = Field(default=None, ge=1, le=3)
    service_area_id: str | None = None
    temperature_preferences: list[str] = Field(default_factory=list)
    texture_preferences: list[str] = Field(default_factory=list)
    flavor_preferences: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=list)
    excluded_categories: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)
    dietary_rules: list[str] = Field(default_factory=list)
    profile_dietary_rules: list[str] = Field(default_factory=list)
    positive_preferences: list[str] = Field(default_factory=list)
    negative_preferences: list[str] = Field(default_factory=list)
    shown_menu_ids: list[str] = Field(default_factory=list)
    rejected_menu_ids: list[str] = Field(default_factory=list)
    compared_menu_ids: list[str] = Field(default_factory=list)
    selected_menu_id: str | None = None
    option_selections: dict[str, list[str]] = Field(default_factory=dict)
    option_risk_acknowledged: list[str] = Field(default_factory=list)
    recommendation_hold: bool = False
    strictness: ConstraintStrictness = ConstraintStrictness.STRICT
    last_question_key: str | None = None


class PreferenceDelta(BaseModel):
    """Validated changes extracted from exactly one user turn."""

    dialogue_act: DialogueAct = DialogueAct.COLLECT_NEEDS
    occasion: str | None = None
    party_size: int | None = Field(default=None, ge=1, le=20)
    budget_krw: int | None = Field(default=None, ge=1000, le=1_000_000)
    max_spiciness: int | None = Field(default=None, ge=1, le=3)
    service_area_id: str | None = None
    add_temperature_preferences: list[str] = Field(default_factory=list)
    remove_temperature_preferences: list[str] = Field(default_factory=list)
    add_texture_preferences: list[str] = Field(default_factory=list)
    remove_texture_preferences: list[str] = Field(default_factory=list)
    add_flavor_preferences: list[str] = Field(default_factory=list)
    remove_flavor_preferences: list[str] = Field(default_factory=list)
    add_preferred_categories: list[str] = Field(default_factory=list)
    remove_preferred_categories: list[str] = Field(default_factory=list)
    add_excluded_categories: list[str] = Field(default_factory=list)
    remove_excluded_categories: list[str] = Field(default_factory=list)
    add_excluded_ingredients: list[str] = Field(default_factory=list)
    remove_excluded_ingredients: list[str] = Field(default_factory=list)
    add_dietary_rules: list[str] = Field(default_factory=list)
    remove_dietary_rules: list[str] = Field(default_factory=list)
    add_positive_preferences: list[str] = Field(default_factory=list)
    add_negative_preferences: list[str] = Field(default_factory=list)
    recommendation_hold: bool | None = None
    strictness: ConstraintStrictness | None = None
    explicit_recommendation_request: bool = False


class ReadinessDecision(BaseModel):
    status: RecommendationReadiness
    score: float = Field(ge=0, le=1)
    information_dimensions: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    next_question_key: str | None = None
    reason: str

    @property
    def may_recommend(self) -> bool:
        return self.status in {
            RecommendationReadiness.READY,
            RecommendationReadiness.EXPLICIT_REQUEST,
        }


class RecommendationCandidate(BaseModel):
    menu_id: str
    merchant_id: str
    rank: int = Field(ge=1)
    score: float
    match_reasons: list[str] = Field(default_factory=list)
    risk_hints: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    passage_ids: list[str] = Field(default_factory=list)


class RecommendationResult(BaseModel):
    snapshot_id: str
    candidates: list[RecommendationCandidate]
    query_summary: str
    grounded_claim_ids: list[str] = Field(default_factory=list)
    grounded_passage_ids: list[str] = Field(default_factory=list)
    synthetic_data: bool = True

    @model_validator(mode="after")
    def require_unique_ranked_candidates(self) -> RecommendationResult:
        ids = [candidate.menu_id for candidate in self.candidates]
        ranks = [candidate.rank for candidate in self.candidates]
        if len(ids) != len(set(ids)) or len(ranks) != len(set(ranks)):
            raise ValueError("Recommendation candidates and ranks must be unique")
        return self


class RecommendationSnapshot(BaseModel):
    snapshot_id: str
    session_id: str
    assistant_message_id: str
    state_version: int
    meal_need_state: MealNeedState
    result: RecommendationResult
    cards: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class ConversationEventType(str, Enum):
    SELECT_MENU = "SELECT_MENU"
    REJECT_MENU = "REJECT_MENU"
    COMPARE_MENUS = "COMPARE_MENUS"
    UPDATE_OPTIONS = "UPDATE_OPTIONS"


class ConversationEventInput(BaseModel):
    event_type: ConversationEventType
    snapshot_id: str | None = None
    menu_id: str | None = None
    menu_ids: list[str] = Field(default_factory=list)
    option_group_id: str | None = None
    option_item_ids: list[str] = Field(default_factory=list)
    risk_acknowledged: bool = False
    expected_state_version: int | None = Field(default=None, ge=0)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def validate_event_payload(self) -> ConversationEventInput:
        if self.event_type in {
            ConversationEventType.SELECT_MENU,
            ConversationEventType.REJECT_MENU,
        }:
            if not self.snapshot_id or not self.menu_id:
                raise ValueError("snapshot_id and menu_id are required for select/reject events")
        if self.event_type == ConversationEventType.COMPARE_MENUS:
            if not self.snapshot_id or len(set(self.menu_ids)) < 2:
                raise ValueError("snapshot_id and at least two unique menu_ids are required")
        if self.event_type == ConversationEventType.UPDATE_OPTIONS and (
            not self.menu_id or not self.option_group_id
        ):
            raise ValueError("menu_id and option_group_id are required for option updates")
        return self


class ConversationEventResult(BaseModel):
    event_id: str
    event_type: ConversationEventType
    state_version: int
    state: MealNeedState
    selected_menu_id: str | None = None
    selected_merchant_id: str | None = None
    selected_menu: dict[str, Any] | None = None
    duplicate: bool = False


class ConversationView(BaseModel):
    session_id: str
    state_version: int
    meal_need_state: MealNeedState
    messages: list[dict[str, Any]] = Field(default_factory=list)
    latest_snapshot: RecommendationSnapshot | None = None


DialogueSource = Literal["rule", "llm_validated", "ui_event", "preset"]
