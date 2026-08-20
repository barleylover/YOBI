from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from app.domain.dialogue import (
    ConversationEventInput,
    ConversationEventResult,
    DialogueAct,
    MealNeedState,
    RecommendationSnapshot,
)
from app.domain.knowledge import GroundedMenuKnowledge
from app.domain.models import (
    AddressCandidate,
    AssistantTurn,
    CartItemInput,
    CartItemUpdate,
    CartPreview,
    Checkout,
    CheckoutCreate,
    DeliveryPreferenceInput,
    Evidence,
    MenuPresentationCacheEntry,
    MenuSummary,
    MerchantComparison,
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
    OptionGroup,
    Order,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    RestaurantNoteTranslation,
    Session,
)
from app.domain.structured_recommendation import (
    EvidencePoolItem,
    FeaturedMenuCollection,
    FoodRankingCollection,
    FoodRankingSort,
    LiveRecommendationMenuState,
    RecommendationCriteriaCommit,
    RecommendationCriteriaRecord,
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationPreviewV2,
    RecommendationReleaseFamily,
    RecommendationRequestInput,
    RecommendationRequestRecord,
    RecommendationRequestStatus,
)


class YobiRepository(Protocol):
    def initialize(self) -> None: ...

    def create_profile(self, data: ProfileCreate) -> Profile: ...

    def get_profile(self, profile_id: str) -> Profile | None: ...

    def update_profile(self, profile_id: str, data: ProfileUpdate) -> Profile | None: ...

    def delete_profile(self, profile_id: str) -> bool: ...

    def create_session(self, profile_id: str) -> Session: ...

    def get_session(self, session_id: str) -> Session | None: ...

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str,
        message_id: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
    ) -> str: ...

    def list_messages(self, session_id: str) -> list[dict[str, Any]]: ...

    def update_dialogue_state(
        self,
        session_id: str,
        dialogue_act: DialogueAct,
        meal_need_state: MealNeedState,
        state: str,
        expected_state_version: int,
    ) -> Session: ...

    def commit_chat_turn(
        self,
        session_id: str,
        expected_state_version: int,
        user_message_id: str,
        user_text: str,
        user_created_at: datetime,
        assistant_turn: AssistantTurn,
        meal_need_state: MealNeedState,
        dialogue_act: DialogueAct,
        snapshot: RecommendationSnapshot | None = None,
        request_id: str | None = None,
        intent: str | None = None,
    ) -> Session: ...

    def save_recommendation_snapshot(self, snapshot: RecommendationSnapshot) -> None: ...

    def get_recommendation_snapshot(
        self, session_id: str, snapshot_id: str | None = None
    ) -> RecommendationSnapshot | None: ...

    def save_recommendation_criteria(
        self,
        session_id: str,
        commit: RecommendationCriteriaCommit,
    ) -> RecommendationCriteriaRecord: ...

    def get_recommendation_criteria(
        self,
        session_id: str,
        version: int | None = None,
    ) -> RecommendationCriteriaRecord | None: ...

    def reserve_recommendation_request(
        self,
        session_id: str,
        data: RecommendationRequestInput,
        request_hash: str,
    ) -> RecommendationRequestRecord: ...

    def mark_recommendation_dispatched(
        self,
        session_id: str,
        request_id: str,
        evidence_pool: list[EvidencePoolItem],
    ) -> RecommendationRequestRecord: ...

    def mark_recommendation_provider_called(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationRequestRecord: ...

    def record_recommendation_provider_attempt(
        self,
        session_id: str,
        request_id: str,
        *,
        attempt_no: int,
        provider: str,
        model_id: str,
        status: str,
        error_code: str | None,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        attempt_role: str = "SELECTION",
    ) -> None: ...

    def record_restaurant_note_translation_attempt(
        self,
        session_id: str,
        request_hash: str,
        *,
        attempt_no: int,
        provider: str,
        model_id: str,
        status: str,
        error_code: str | None,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None: ...

    def cancel_recommendation_request(self, session_id: str, request_id: str) -> bool: ...

    def get_restaurant_note_translation_by_hash(
        self, session_id: str, request_hash: str
    ) -> RestaurantNoteTranslation | None: ...

    def save_restaurant_note_translation(
        self,
        session_id: str,
        *,
        translation_id: str,
        source_language: str,
        source_text: str,
        korean_text: str | None,
        back_translation: str | None,
        provider: str,
        model_id: str,
        status: str,
        error_code: str | None,
        request_hash: str,
    ) -> RestaurantNoteTranslation: ...

    def complete_recommendation_request(
        self,
        session_id: str,
        request_id: str,
        status: RecommendationRequestStatus,
        *,
        result_json: dict[str, Any] | None = None,
        snapshot: RecommendationSnapshot | None = None,
        failure_code: str | None = None,
        provider_metrics: dict[str, int] | None = None,
        grounding_rejection_code: str | None = None,
        grounding_rejection_stage: str | None = None,
        grounding_rejection_detail: str | None = None,
    ) -> RecommendationRequestRecord: ...

    def get_recommendation_request(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationRequestRecord | None: ...

    def get_latest_recommendation_request(
        self,
        session_id: str,
        *,
        active_only: bool = False,
    ) -> RecommendationRequestRecord | None: ...

    def get_live_recommendation_menu_states(
        self,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        release_family_id: str,
        menu_ids: list[str],
        *,
        at: datetime,
    ) -> dict[str, LiveRecommendationMenuState]: ...

    def build_recommendation_evidence_pool(
        self,
        session_id: str,
        profile: Profile,
        criteria: RecommendationCriteriaV2,
        mode: RecommendationMode,
        limit: int,
        *,
        release_family_id: str,
        eligibility_as_of: datetime,
        raw_hits_per_value: int,
        passages_per_menu: int,
    ) -> list[EvidencePoolItem]: ...

    def get_recommendation_retrieval_metrics(self, session_id: str) -> dict[str, Any]: ...

    def preview_recommendation(
        self,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        *,
        release_family_id: str | None = None,
        exclude_history: bool = False,
    ) -> RecommendationPreviewV2: ...

    def save_recommendation_comparison(
        self,
        session_id: str,
        recommendation_request_id: str,
        comparison_request_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]: ...

    def get_recommendation_comparison(
        self,
        session_id: str,
        recommendation_request_id: str,
        comparison_request_id: str,
    ) -> dict[str, Any] | None: ...

    def get_active_recommendation_release_family(
        self,
    ) -> RecommendationReleaseFamily | None: ...

    def list_valid_halal_certified_menu_ids(
        self,
        *,
        at: datetime | None = None,
    ) -> set[str]: ...

    def get_preference_catalog(self, locale: str) -> dict[str, Any]: ...

    def list_food_rankings(
        self,
        session_id: str,
        sort: FoodRankingSort,
        limit: int,
    ) -> FoodRankingCollection: ...

    def list_kpop_demon_hunters_feature(
        self,
        session_id: str,
    ) -> FeaturedMenuCollection: ...

    def apply_conversation_event(
        self, session_id: str, event: ConversationEventInput
    ) -> ConversationEventResult: ...

    def set_session_selection(
        self, session_id: str, state: str, menu_id: str | None, merchant_id: str | None
    ) -> None: ...

    def search_menus(
        self,
        query: str,
        profile: Profile,
        budget_krw: int | None,
        max_spiciness: int | None,
        excluded_ingredients: list[str],
        limit: int = 4,
    ) -> list[MenuSummary]: ...

    def recommend_menus(
        self,
        query: str,
        profile: Profile,
        meal_need_state: MealNeedState,
        limit: int = 4,
    ) -> list[MenuSummary]: ...

    def get_menu(self, menu_id: str, profile: Profile) -> MenuSummary | None: ...

    def get_category_knowledge_source(self, category: str) -> str | None: ...

    def list_merchant_menus(
        self,
        merchant_id: str,
        profile: Profile,
        excluded_menu_ids: list[str],
        limit: int = 12,
        meal_need_state: MealNeedState | None = None,
    ) -> list[MenuSummary]: ...

    def get_evidence(self, menu_id: str) -> list[Evidence]: ...

    def get_grounded_menu_knowledge(
        self,
        menu_id: str,
        query: str = "",
        option_item_ids: list[str] | None = None,
    ) -> GroundedMenuKnowledge: ...

    def compare_merchants(
        self,
        category: str,
        profile: Profile,
        limit: int = 3,
        meal_need_state: MealNeedState | None = None,
    ) -> list[MerchantComparison]: ...

    def get_options(self, menu_id: str, session_id: str | None = None) -> list[OptionGroup]: ...

    def option_localizations_complete(
        self,
        session_id: str,
        menu_id: str,
        group_ids: list[str],
        item_ids: list[str],
        prompt_version: str,
    ) -> bool: ...

    def load_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        prompt_version: str,
    ) -> tuple[dict[str, str], dict[str, str]]: ...

    def save_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        group_names: dict[str, str],
        item_names: dict[str, str],
        model_id: str,
        prompt_version: str,
    ) -> None: ...

    def save_menu_runtime_localizations(
        self,
        session_id: str,
        menu_id: str,
        localized_title: str,
        localized_source_description: str,
        model_id: str,
        prompt_version: str,
    ) -> None: ...

    def list_merchant_menu_presentations(
        self,
        session_id: str,
        merchant_id: str,
        request: MerchantMenuPresentationRequest,
    ) -> MerchantMenuPresentationPage: ...

    def save_menu_presentation_cache(
        self, session_id: str, presentation: MerchantMenuPresentation
    ) -> None: ...

    def get_menu_presentation_cache(self, cache_key: str) -> MenuPresentationCacheEntry | None: ...

    def save_menu_presentation_cache_entry(self, entry: MenuPresentationCacheEntry) -> None: ...

    def acquire_menu_presentation_lease(
        self,
        cache_key: str,
        owner_token: str,
        *,
        expires_at: datetime,
    ) -> bool: ...

    def finish_menu_presentation_lease(
        self,
        cache_key: str,
        owner_token: str,
        *,
        error_code: str | None = None,
    ) -> None: ...

    def resolve_address(
        self, text: str, file_hash: str | None = None
    ) -> list[AddressCandidate]: ...

    def get_address_candidate(self, place_id: str) -> AddressCandidate | None: ...

    def save_address(
        self,
        session_id: str,
        candidate: AddressCandidate,
        source_image_hash: str | None = None,
    ) -> str: ...

    def get_session_service_area(self, session_id: str) -> str | None: ...

    def add_cart_item(
        self,
        session_id: str,
        item: CartItemInput,
        agent_request_key: str | None = None,
    ) -> CartPreview: ...

    def update_cart_item(
        self, session_id: str, cart_item_id: str, item: CartItemUpdate
    ) -> CartPreview: ...

    def delete_cart_item(self, session_id: str, cart_item_id: str) -> CartPreview: ...

    def get_cart(self, session_id: str) -> CartPreview: ...

    def update_delivery(
        self, session_id: str, preference: DeliveryPreferenceInput
    ) -> CartPreview: ...

    def confirm_cart(self, session_id: str) -> CartPreview: ...

    def create_checkout(self, session_id: str, data: CheckoutCreate) -> Checkout: ...

    def get_checkout(self, checkout_id: str) -> Checkout | None: ...

    def update_checkout(self, checkout_id: str, status: str) -> Checkout: ...

    def get_order(self, order_id: str) -> Order | None: ...

    def reset_session(self, session_id: str) -> None: ...

    def prewarm_explanation(self, menu_id: str) -> bool: ...

    def record_audit(
        self,
        session_id: str | None,
        tool: str,
        input_payload: str,
        evidence_ids: list[str],
        output_status: str,
        latency_ms: int,
        fallback_used: bool,
        safe_error_code: str | None = None,
    ) -> None: ...

    def status(self) -> dict[str, object]: ...
