from __future__ import annotations

from typing import Protocol

from app.domain.models import (
    AddressCandidate,
    CartItemInput,
    CartItemUpdate,
    CartPreview,
    Checkout,
    CheckoutCreate,
    DeliveryPreferenceInput,
    Evidence,
    MenuSummary,
    MerchantComparison,
    OptionGroup,
    Order,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    Session,
)


class YobiRepository(Protocol):
    def initialize(self) -> None: ...

    def create_profile(self, data: ProfileCreate) -> Profile: ...

    def get_profile(self, profile_id: str) -> Profile | None: ...

    def update_profile(self, profile_id: str, data: ProfileUpdate) -> Profile | None: ...

    def delete_profile(self, profile_id: str) -> bool: ...

    def create_session(self, profile_id: str) -> Session: ...

    def get_session(self, session_id: str) -> Session | None: ...

    def save_message(self, session_id: str, role: str, content: str, message_type: str) -> str: ...

    def list_messages(self, session_id: str) -> list[dict[str, str]]: ...

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

    def get_menu(self, menu_id: str, profile: Profile) -> MenuSummary | None: ...

    def get_evidence(self, menu_id: str) -> list[Evidence]: ...

    def compare_merchants(
        self, category: str, profile: Profile, limit: int = 3
    ) -> list[MerchantComparison]: ...

    def get_options(self, menu_id: str) -> list[OptionGroup]: ...

    def resolve_address(self, text: str, file_hash: str | None = None) -> list[AddressCandidate]: ...

    def get_address_candidate(self, place_id: str) -> AddressCandidate | None: ...

    def save_address(
        self,
        session_id: str,
        candidate: AddressCandidate,
        source_image_hash: str | None = None,
    ) -> str: ...

    def add_cart_item(self, session_id: str, item: CartItemInput) -> CartPreview: ...

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
