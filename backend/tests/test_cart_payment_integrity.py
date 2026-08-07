import pytest

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import (
    AddressCandidate,
    CartItemInput,
    CartItemUpdate,
    CheckoutCreate,
    DeliveryPreferenceInput,
    ProfileCreate,
)


def _ready_cart(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> tuple[str, str]:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    repository.add_cart_item(
        session.session_id,
        CartItemInput(
            menu_id="menu_001_01",
            option_item_ids=[
                "oi_001_01_spice_mild",
                "oi_001_01_size_regular",
                "oi_001_01_cheese_add",
                "oi_001_01_fishcake_remove",
            ],
            user_note="As mild as possible, please.",
        ),
    )
    candidate = repository.resolve_address("YOBI Myeongdong Hotel")[0]
    address_ref_id = repository.save_address(session.session_id, candidate)
    preview = repository.update_delivery(
        session.session_id,
        DeliveryPreferenceInput(address_ref_id=address_ref_id),
    )
    assert preview.ready_to_checkout is True
    return session.session_id, preview.cart_id


def test_required_options_are_server_enforced(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    with pytest.raises(ValueError, match="REQUIRED_MENU_OPTION_MISSING"):
        repository.add_cart_item(
            session.session_id,
            CartItemInput(menu_id="menu_001_01", option_item_ids=[]),
        )


def test_checkout_and_order_are_idempotent(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)
    repository.confirm_cart(session_id)
    data = CheckoutCreate(
        idempotency_key="test-checkout-idempotency",
        payment_method="international_card",
    )
    first = repository.create_checkout(session_id, data)
    second = repository.create_checkout(session_id, data)
    assert first.checkout_id == second.checkout_id

    paid_once = repository.update_checkout(first.checkout_id, "SUCCEEDED")
    paid_twice = repository.update_checkout(first.checkout_id, "SUCCEEDED")
    assert paid_once.order_id
    assert paid_once.order_id == paid_twice.order_id


def test_cart_is_repriced_from_current_catalog_before_confirmation(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)
    before = repository.get_cart(session_id)
    with repository._connection() as connection:
        connection.execute(
            "UPDATE menu SET price = price + 700 WHERE menu_id = ?", ("menu_001_01",)
        )

    confirmed = repository.confirm_cart(session_id)

    assert confirmed.confirmed is True
    assert confirmed.subtotal == before.subtotal + 700
    assert confirmed.items[0].unit_price == before.items[0].unit_price + 700


def test_checkout_requires_reconfirmation_when_catalog_changes(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)
    repository.confirm_cart(session_id)
    with repository._connection() as connection:
        connection.execute(
            "UPDATE menu SET price = price + 500 WHERE menu_id = ?", ("menu_001_01",)
        )

    with pytest.raises(ValueError, match="CART_CHANGED_RECONFIRM_REQUIRED"):
        repository.create_checkout(
            session_id,
            CheckoutCreate(
                idempotency_key="catalog-change-reconfirm",
                payment_method="international_card",
            ),
        )

    refreshed = repository.get_cart(session_id)
    assert refreshed.confirmed is False


def test_confirmation_rejects_unavailable_option(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)
    with repository._connection() as connection:
        connection.execute(
            "UPDATE menu_option_item SET availability = 'SOLD_OUT' WHERE option_item_id = ?",
            ("oi_001_01_size_regular",),
        )

    with pytest.raises(ValueError, match="CART_OPTION_UNAVAILABLE"):
        repository.confirm_cart(session_id)


def test_confirmation_rejects_minimum_order_change(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)
    with repository._connection() as connection:
        connection.execute(
            "UPDATE merchant SET min_order_amount = 999999 WHERE merchant_id = ?",
            ("mer_001",),
        )

    with pytest.raises(ValueError, match="MINIMUM_ORDER_NOT_MET"):
        repository.confirm_cart(session_id)

    preview = repository.get_cart(session_id)
    assert preview.ready_to_checkout is False
    assert "minimum_order_amount" in preview.missing_slots
    assert preview.minimum_order_amount == 999999
    assert preview.minimum_order_shortfall == 999999 - preview.subtotal


def test_review_preview_explains_dietary_option_conflict(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    repository.add_cart_item(
        session.session_id,
        CartItemInput(
            menu_id="menu_001_01",
            option_item_ids=[
                "oi_001_01_spice_mild",
                "oi_001_01_size_regular",
                "oi_001_01_cheese_add",
                "oi_001_01_fishcake_keep",
            ],
        ),
    )
    candidate = repository.resolve_address("YOBI Myeongdong Hotel")[0]
    address_ref_id = repository.save_address(session.session_id, candidate)
    preview = repository.update_delivery(
        session.session_id,
        DeliveryPreferenceInput(address_ref_id=address_ref_id),
    )

    assert preview.ready_to_checkout is False
    assert "dietary_conflict" in preview.missing_slots
    assert "Remove Keep fish cake to continue." in preview.dietary_warnings


def test_vegan_profile_requires_verified_menu_at_review(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    vegan_profile = profile_data.model_copy(
        update={"dietary_rules": ["vegan"], "allergy_severity": "mild"}
    )
    profile = repository.create_profile(vegan_profile)
    session = repository.create_session(profile.profile_id)
    repository.add_cart_item(
        session.session_id,
        CartItemInput(
            menu_id="menu_001_01",
            option_item_ids=[
                "oi_001_01_spice_mild",
                "oi_001_01_size_regular",
                "oi_001_01_cheese_none",
                "oi_001_01_fishcake_remove",
            ],
        ),
    )
    candidate = repository.resolve_address("YOBI Myeongdong Hotel")[0]
    address_ref_id = repository.save_address(session.session_id, candidate)
    preview = repository.update_delivery(
        session.session_id,
        DeliveryPreferenceInput(address_ref_id=address_ref_id),
    )

    assert preview.ready_to_checkout is False
    assert "dietary_conflict" in preview.missing_slots
    assert any("vegan status is not verified" in warning for warning in preview.dietary_warnings)
    with pytest.raises(ValueError, match="CART_DIETARY_CONFLICT"):
        repository.confirm_cart(session.session_id)


def test_cart_item_can_be_updated_and_deleted(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)
    original = repository.get_cart(session_id)
    item_id = original.items[0].cart_item_id

    updated = repository.update_cart_item(
        session_id,
        item_id,
        CartItemUpdate(quantity=2, user_note="No disposable cutlery."),
    )

    assert updated.items[0].quantity == 2
    assert updated.items[0].line_total == original.items[0].line_total * 2
    assert updated.confirmed is False
    emptied = repository.delete_cart_item(session_id, item_id)
    assert emptied.items == []
    assert "menu" in emptied.missing_slots


def test_cart_rejects_items_from_multiple_merchants(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)

    with pytest.raises(ValueError, match="CART_MULTIPLE_MERCHANTS"):
        repository.add_cart_item(
            session_id,
            CartItemInput(
                menu_id="menu_002_01",
                option_item_ids=["oi_002_01_size_regular"],
            ),
        )


def test_payment_failure_preserves_cart_and_allows_retry(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, cart_id = _ready_cart(repository, profile_data)
    repository.confirm_cart(session_id)
    checkout = repository.create_checkout(
        session_id,
        CheckoutCreate(
            idempotency_key="test-payment-retry",
            payment_method="international_card",
        ),
    )
    failed = repository.update_checkout(checkout.checkout_id, "FAILED")
    assert failed.status == "FAILED"
    assert repository.get_cart(session_id).cart_id == cart_id
    succeeded = repository.update_checkout(checkout.checkout_id, "SUCCEEDED")
    assert succeeded.order_id is not None


def test_address_resolution_requires_confirmation(
    repository: SQLiteYobiRepository,
) -> None:
    candidate = repository.resolve_address("unknown screenshot")[0]
    assert isinstance(candidate, AddressCandidate)
    assert candidate.needs_confirmation is True
    assert candidate.confidence < 0.8
