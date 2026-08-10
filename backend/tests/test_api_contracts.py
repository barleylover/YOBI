from collections.abc import Iterator
from math import ceil
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db.sqlite_repository import SQLiteYobiRepository
from app.dependencies import get_repository
from app.domain.dialogue import DialogueAct, MealNeedState
from app.domain.models import MenuSummary, Profile, ProfileCreate
from app.main import app


@pytest.fixture
def api_client(repository: SQLiteYobiRepository) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repository
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_merchant_menu_endpoint_uses_scoped_repository_query(
    api_client: TestClient,
    repository: SQLiteYobiRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, spice_tolerance=3)
    )
    session = repository.create_session(profile.profile_id)
    original_list = repository.list_merchant_menus
    call: dict[str, Any] = {}

    def forbid_global_recommendation(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("merchant menu endpoint must not call recommend_menus")

    def record_scoped_query(
        merchant_id: str,
        query_profile: Profile,
        excluded_menu_ids: list[str],
        limit: int = 12,
        meal_need_state: MealNeedState | None = None,
    ) -> list[MenuSummary]:
        call.update(
            merchant_id=merchant_id,
            profile=query_profile,
            excluded_menu_ids=excluded_menu_ids,
            limit=limit,
            meal_need_state=meal_need_state,
        )
        return original_list(
            merchant_id,
            query_profile,
            excluded_menu_ids,
            limit,
            meal_need_state,
        )

    monkeypatch.setattr(repository, "recommend_menus", forbid_global_recommendation)
    monkeypatch.setattr(repository, "list_merchant_menus", record_scoped_query)

    response = api_client.get(
        f"/api/v1/sessions/{session.session_id}/merchants/mer_001/menus",
        params={"exclude": "menu_001_01"},
    )

    assert response.status_code == 200
    assert call == {
        "merchant_id": "mer_001",
        "profile": profile,
        "excluded_menu_ids": ["menu_001_01"],
        "limit": 12,
        "meal_need_state": session.meal_need_state,
    }
    assert all(menu["merchant_id"] == "mer_001" for menu in response.json())
    assert all(menu["menu_id"] != "menu_001_01" for menu in response.json())


def test_merchant_menu_endpoint_preserves_current_session_constraints(
    api_client: TestClient,
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, spice_tolerance=3, dietary_rules=[])
    )
    session = repository.create_session(profile.profile_id)
    repository.update_dialogue_state(
        session.session_id,
        DialogueAct.REVISE,
        MealNeedState(
            max_spiciness=1,
            excluded_categories=["soup"],
            negative_preferences=["sweet"],
            party_size=4,
            budget_krw=23_000,
        ),
        session.state.value,
        session.state_version,
    )

    response = api_client.get(
        f"/api/v1/sessions/{session.session_id}/merchants/mer_003/menus"
    )

    assert response.status_code == 200
    menus = response.json()
    assert menus
    assert all(menu["spice_level"] <= 1 for menu in menus)
    assert all(
        menu["category"].lower()
        not in {
            "chicken kalguksu",
            "samgyetang",
            "sundubu",
            "kimchi stew",
            "gukbap",
            "seolleongtang",
            "eomuk",
        }
        for menu in menus
    )
    assert all(
        menu["price"] * ceil(4 / max(menu["serves_max"], 1)) <= 23_000
        for menu in menus
    )
    assert all(
        "sweet"
        not in " ".join(
            (menu["category"], menu["name_en"], menu["description"])
        ).lower().replace("sweet-potato", "").replace("sweet potato", "")
        for menu in menus
    )


def test_manual_address_inherits_exact_canonical_service_area(
    api_client: TestClient,
    repository: SQLiteYobiRepository,
) -> None:
    canonical = repository.get_address_candidate("hotel_demo_01")
    assert canonical is not None
    assert canonical.service_area_id is not None
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    session = repository.create_session(profile.profile_id)

    response = api_client.post(
        f"/api/v1/sessions/{session.session_id}/address/confirm",
        json={
            "manual": {
                "hotel_name": canonical.hotel_name,
                "road_address": f"  {canonical.road_address.replace(' ', '   ')}  ",
                "postal_code": f" {canonical.postal_code} ",
                "city": canonical.city.upper(),
                "delivery_hint": "Front desk",
            }
        },
    )

    assert response.status_code == 200
    with repository._connection() as connection:
        saved = connection.execute(
            """
            SELECT source_type, place_id, service_area_id, extraction_confidence
            FROM address_ref WHERE address_ref_id = ?
            """,
            (response.json()["address_ref_id"],),
        ).fetchone()
    assert saved is not None
    assert saved["source_type"] == "manual"
    assert saved["place_id"] is None
    assert saved["service_area_id"] == canonical.service_area_id
    assert saved["extraction_confidence"] >= 0.8


def test_manual_address_outside_service_area_is_rejected_without_persistence(
    api_client: TestClient,
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    session = repository.create_session(profile.profile_id)

    response = api_client.post(
        f"/api/v1/sessions/{session.session_id}/address/confirm",
        json={
            "manual": {
                "hotel_name": "Unlisted Busan Stay",
                "road_address": "123 Outside Service Road",
                "postal_code": "99999",
                "city": "Busan",
                "delivery_hint": "Front desk",
            }
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "ADDRESS_OUTSIDE_SERVICE_AREA"}
    }
    with repository._connection() as connection:
        saved_count = connection.execute(
            "SELECT COUNT(*) FROM address_ref WHERE session_id = ?",
            (session.session_id,),
        ).fetchone()[0]
    assert saved_count == 0


def test_manual_address_uses_exact_address_when_hotel_name_is_unknown(
    api_client: TestClient,
    repository: SQLiteYobiRepository,
) -> None:
    canonical = repository.get_address_candidate("hotel_demo_01")
    assert canonical is not None
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    session = repository.create_session(profile.profile_id)

    response = api_client.post(
        f"/api/v1/sessions/{session.session_id}/address/confirm",
        json={
            "manual": {
                "hotel_name": "Unlisted Lodging",
                "road_address": f"  {canonical.road_address.replace(' ', '   ')}  ",
                "postal_code": "",
                "city": canonical.city.upper(),
                "delivery_hint": "Front desk",
            }
        },
    )

    assert response.status_code == 200
    with repository._connection() as connection:
        saved_area = connection.execute(
            "SELECT service_area_id FROM address_ref WHERE address_ref_id = ?",
            (response.json()["address_ref_id"],),
        ).fetchone()[0]
    assert saved_area == canonical.service_area_id


def test_signed_address_candidate_rejects_area_deactivated_after_resolution(
    api_client: TestClient,
    repository: SQLiteYobiRepository,
) -> None:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    session = repository.create_session(profile.profile_id)
    resolved = api_client.post(
        f"/api/v1/sessions/{session.session_id}/address/resolve",
        json={"text": "YOBI Myeongdong Hotel"},
    )
    token = resolved.json()["candidates"][0]["candidate_token"]
    with repository._connection() as connection:
        connection.execute(
            "UPDATE service_area SET active=0 WHERE service_area_id='area_myeongdong'"
        )

    response = api_client.post(
        f"/api/v1/sessions/{session.session_id}/address/confirm",
        json={"candidate_token": token},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "ADDRESS_OUTSIDE_SERVICE_AREA"}}


def test_address_save_area_race_is_normalized_to_actionable_api_error(
    api_client: TestClient,
    repository: SQLiteYobiRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    session = repository.create_session(profile.profile_id)
    resolved = api_client.post(
        f"/api/v1/sessions/{session.session_id}/address/resolve",
        json={"text": "YOBI Myeongdong Hotel"},
    )
    token = resolved.json()["candidates"][0]["candidate_token"]

    def reject_inactive_area(*_args: object, **_kwargs: object) -> str:
        raise ValueError("ADDRESS_OUTSIDE_SERVICE_AREA")

    monkeypatch.setattr(repository, "save_address", reject_inactive_area)
    response = api_client.post(
        f"/api/v1/sessions/{session.session_id}/address/confirm",
        json={"candidate_token": token},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "ADDRESS_OUTSIDE_SERVICE_AREA"}}


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/sessions/missing-session/cart", None),
        (
            "POST",
            "/api/v1/sessions/missing-session/cart/items",
            {"menu_id": "menu_001_01"},
        ),
        (
            "PATCH",
            "/api/v1/sessions/missing-session/cart/items/missing-item",
            {"quantity": 2},
        ),
        (
            "DELETE",
            "/api/v1/sessions/missing-session/cart/items/missing-item",
            None,
        ),
        ("PATCH", "/api/v1/sessions/missing-session/delivery", {}),
        ("POST", "/api/v1/sessions/missing-session/cart/confirm", None),
        (
            "POST",
            "/api/v1/sessions/missing-session/checkout",
            {
                "idempotency_key": "missing-session-checkout",
                "payment_method": "international_card",
            },
        ),
    ],
)
def test_session_scoped_cart_contract_returns_session_not_found_first(
    api_client: TestClient,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
) -> None:
    kwargs = {"json": payload} if payload is not None else {}

    response = api_client.request(method, path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "SESSION_NOT_FOUND"}}
