import pytest

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import (
    AddressCandidate,
    CartItemInput,
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
