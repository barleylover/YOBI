from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.dialogue import DialogueAct, MealNeedState
from app.domain.models import (
    AddressCandidate,
    CartItemInput,
    CartItemUpdate,
    CheckoutCreate,
    DeliveryPreferenceInput,
    ProfileCreate,
)


def _ready_cart(repository: SQLiteYobiRepository, profile_data: ProfileCreate) -> tuple[str, str]:
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


def test_concurrent_agent_cart_replay_adds_exactly_one_line(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    item = CartItemInput(
        menu_id="menu_001_01",
        option_item_ids=["oi_001_01_spice_mild", "oi_001_01_size_regular"],
        user_note="Keep it mild.",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        previews = list(
            executor.map(
                lambda _: repository.add_cart_item(
                    session.session_id, item, "agent-concurrent-cart-add-0001"
                ),
                range(2),
            )
        )

    assert [len(preview.items) for preview in previews] == [1, 1]
    assert previews[0].items[0].cart_item_id == previews[1].items[0].cart_item_id


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


def test_one_confirmed_cart_cannot_fork_into_two_checkouts_or_orders(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)
    repository.confirm_cart(session_id)

    first = repository.create_checkout(
        session_id,
        CheckoutCreate(
            idempotency_key="same-cart-attempt-one",
            payment_method="international_card",
        ),
    )
    replay_with_new_key = repository.create_checkout(
        session_id,
        CheckoutCreate(
            idempotency_key="same-cart-attempt-two",
            payment_method="apple_pay_demo",
        ),
    )

    assert replay_with_new_key.checkout_id == first.checkout_id
    assert replay_with_new_key.payment_method == first.payment_method
    first_result = repository.update_checkout(first.checkout_id, "SUCCEEDED")
    replay_result = repository.update_checkout(replay_with_new_key.checkout_id, "SUCCEEDED")
    assert first_result.order_id == replay_result.order_id


def test_checkout_idempotency_key_is_bound_to_confirmed_cart_version(
    repository: SQLiteYobiRepository, profile_data: ProfileCreate
) -> None:
    session_id, _ = _ready_cart(repository, profile_data)
    first_confirmation = repository.confirm_cart(session_id)
    first = repository.create_checkout(
        session_id,
        CheckoutCreate(
            idempotency_key="cart-version-bound-key",
            payment_method="international_card",
        ),
    )

    repository.update_cart_item(
        session_id,
        first_confirmation.items[0].cart_item_id,
        CartItemUpdate(quantity=2),
    )
    second_confirmation = repository.confirm_cart(session_id)
    assert second_confirmation.version > first_confirmation.version

    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REUSED"):
        repository.create_checkout(
            session_id,
            CheckoutCreate(
                idempotency_key="cart-version-bound-key",
                payment_method="international_card",
            ),
        )

    second = repository.create_checkout(
        session_id,
        CheckoutCreate(
            idempotency_key="cart-version-bound-key-v2",
            payment_method="international_card",
        ),
    )
    assert second.checkout_id != first.checkout_id
    assert second.amount > first.amount


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


def _direct_ready_cart(
    repository: SQLiteYobiRepository,
    profile_data: ProfileCreate,
    menu_id: str,
    option_item_ids: list[str],
    state: MealNeedState | None = None,
) -> str:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)
    if state is not None:
        repository.update_dialogue_state(
            session.session_id,
            DialogueAct.REVISE,
            state,
            session.state.value,
            session.state_version,
        )
    repository.add_cart_item(
        session.session_id,
        CartItemInput(menu_id=menu_id, option_item_ids=option_item_ids),
    )
    candidate = repository.resolve_address("YOBI Myeongdong Hotel")[0]
    address_ref_id = repository.save_address(session.session_id, candidate)
    repository.update_delivery(
        session.session_id,
        DeliveryPreferenceInput(address_ref_id=address_ref_id),
    )
    return session.session_id


def test_confirmation_blocks_direct_cart_no_soup_and_no_pork_bypass(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _direct_ready_cart(
        repository,
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        ),
        "menu_027_01",
        ["oi_027_01_size_regular"],
        MealNeedState(excluded_categories=["soup"], excluded_ingredients=["pork"]),
    )

    preview = repository.get_cart(session_id)
    assert preview.ready_to_checkout is False
    assert "dietary_conflict" in preview.missing_slots
    with pytest.raises(ValueError, match="CART_DIETARY_CONFLICT"):
        repository.confirm_cart(session_id)


def test_confirmation_blocks_explicit_islam_profile_pork_bypass(
    repository: SQLiteYobiRepository,
) -> None:
    session_id = _direct_ready_cart(
        repository,
        ProfileCreate(
            consent_demo_data=True,
            religion_selection="Islam",
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        ),
        "menu_024_01",
        ["oi_024_01_size_regular"],
    )

    preview = repository.get_cart(session_id)
    assert preview.ready_to_checkout is False
    assert "dietary_conflict" in preview.missing_slots
    with pytest.raises(ValueError, match="CART_DIETARY_CONFLICT"):
        repository.confirm_cart(session_id)


def test_confirmation_rejects_wrong_delivery_service_area(
    repository: SQLiteYobiRepository,
) -> None:
    session_id, _ = _ready_cart(
        repository,
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=["shellfish_allergy"],
            allergy_severity="severe",
            spice_tolerance=1,
        ),
    )
    with repository._connection() as connection:
        connection.execute(
            """
            UPDATE address_ref SET service_area_id='area_gangnam'
            WHERE session_id=?
            """,
            (session_id,),
        )

    preview = repository.get_cart(session_id)
    assert preview.ready_to_checkout is False
    assert "service_area" in preview.missing_slots
    with pytest.raises(ValueError, match="CART_SERVICE_AREA_MISMATCH"):
        repository.confirm_cart(session_id)


def test_selected_option_effect_is_applied_during_cart_revalidation(
    repository: SQLiteYobiRepository,
) -> None:
    with repository._connection() as connection:
        release_id = connection.execute(
            "SELECT active_release_id FROM knowledge_runtime_state WHERE state_key='ACTIVE'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT OR REPLACE INTO menu_ingredient(
              menu_id,ingredient_id,status,source_id,is_optional
            ) VALUES ('menu_001_01','ingredient_pork','CONFIRMED_PRESENT','test:pork',0)
            """
        )
        connection.execute(
            """
            INSERT INTO option_ingredient_effect(
              release_id,option_item_id,ingredient_id,effect,assertion_status,
              source_ref,is_synthetic,updated_at
            ) VALUES (?,?,?,'REMOVE','CONFIRMED_ABSENT','test:remove-pork',1,'2026-08-09')
            """,
            (release_id, "oi_001_01_cheese_none", "ingredient_pork"),
        )
    session_id = _direct_ready_cart(
        repository,
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        ),
        "menu_001_01",
        [
            "oi_001_01_spice_mild",
            "oi_001_01_size_regular",
            "oi_001_01_cheese_none",
            "oi_001_01_fishcake_remove",
        ],
        MealNeedState(excluded_ingredients=["pork"]),
    )

    assert repository.confirm_cart(session_id).confirmed is True
