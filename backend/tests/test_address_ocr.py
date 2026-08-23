import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings, get_settings
from app.db.demo_address import demo_address_row, demo_address_status, upsert_demo_address
from app.dependencies import get_repository
from app.domain.models import AddressCandidate, ProfileCreate
from app.main import app
from app.services.address_ocr import AddressCandidateTokenCodec, FixtureAddressOcrAdapter


def test_single_demo_address_fixture_is_idempotent(repository) -> None:  # type: ignore[no-untyped-def]
    with repository._connection() as connection:
        connection.execute("DELETE FROM address_place")
        upsert_demo_address(connection.cursor(), oracle=False)
        first = demo_address_status(connection.cursor())
        upsert_demo_address(connection.cursor(), oracle=False)
        second = demo_address_status(connection.cursor())
        stored = connection.execute(
            "SELECT * FROM address_place WHERE place_id='hotel_demo_01'"
        ).fetchone()

    assert first == {"total": 1, "matching": 1, "ready": True}
    assert second == first
    assert stored is not None
    expected = demo_address_row()
    assert stored["name_en"] == expected["name_en"]
    assert stored["road_address"] == expected["road_address"]
    assert stored["service_area_id"] == expected["service_area_id"]
    assert stored["is_synthetic"] == 1


def test_canonical_booking_hash_resolves_without_ocr(repository) -> None:  # type: ignore[no-untyped-def]
    expected_hash = "49f7f262d369a904b3b4ae395ec438bb5fcd98581b643dcfa32bbf4bbec08876"
    fixture = Path(__file__).resolve().parents[2] / "frontend/public/demo-booking.png"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == expected_hash

    candidates = FixtureAddressOcrAdapter().resolve_place_candidates(
        repository, "", expected_hash
    )

    assert candidates[0].place_id == "hotel_demo_01"
    assert candidates[0].confidence == 1.0
    assert candidates[0].source == "canonical_fixture"


def test_candidate_token_is_session_bound_and_tamper_evident() -> None:
    settings = Settings(app_env="test", demo_control_token="test-address-signing-secret")
    codec = AddressCandidateTokenCodec(settings)
    candidate = AddressCandidate(
        place_id="hotel_demo_01",
        hotel_name="YOBI Myeongdong Hotel",
        road_address="Synthetic road address",
        postal_code="04501",
        city="Seoul",
        delivery_hint="Front desk",
        confidence=1.0,
        source="canonical_fixture",
    )
    token = codec.encode("session_one", candidate, "a" * 64)

    claims = codec.decode(token, "session_one")

    assert claims["place_id"] == "hotel_demo_01"
    assert claims["source_image_hash"] == "a" * 64
    with pytest.raises(ValueError, match="ADDRESS_CANDIDATE_TOKEN_INVALID"):
        codec.decode(token, "session_two")
    body, signature = token.split(".", 1)
    tampered = f"{body}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    with pytest.raises(ValueError, match="ADDRESS_CANDIDATE_TOKEN_INVALID"):
        codec.decode(tampered, "session_one")


def test_upload_confirmation_uses_server_signed_candidate(repository) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(
        app_env="test",
        address_ocr_provider="fixture",
        demo_control_token="test-address-signing-secret",
    )
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    session = repository.create_session(profile.profile_id)
    fixture = Path(__file__).resolve().parents[2] / "frontend/public/demo-booking.png"
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        client = TestClient(app)
        uploaded = client.post(
            f"/api/v1/sessions/{session.session_id}/address/attachments",
            files={"file": ("yobi-demo-booking.png", fixture.read_bytes(), "image/png")},
        )
        assert uploaded.status_code == 200
        candidate = uploaded.json()["candidates"][0]
        assert candidate["place_id"] == "hotel_demo_01"
        assert candidate["confidence"] == 1.0

        confirmed = client.post(
            f"/api/v1/sessions/{session.session_id}/address/confirm",
            json={"candidate_token": candidate["candidate_token"]},
        )
        assert confirmed.status_code == 200
        with repository._connection() as connection:
            saved_hash = connection.execute(
                "SELECT source_image_hash FROM address_ref WHERE address_ref_id = ?",
                (confirmed.json()["address_ref_id"],),
            ).fetchone()[0]
        assert saved_hash == hashlib.sha256(fixture.read_bytes()).hexdigest()

        candidate["hotel_name"] = "Browser-invented hotel"
        rejected = client.post(
            f"/api/v1/sessions/{session.session_id}/address/confirm",
            json={"candidate": candidate},
        )
        assert rejected.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_arbitrary_search_and_booking_image_use_prepared_demo_address(repository) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(
        app_env="test",
        address_ocr_provider="fixture",
        demo_control_token="test-address-signing-secret",
    )
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True))
    session = repository.create_session(profile.profile_id)
    image_buffer = BytesIO()
    Image.new("RGB", (8, 8), color=(12, 34, 56)).save(image_buffer, format="PNG")
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        client = TestClient(app)
        searched = client.post(
            f"/api/v1/sessions/{session.session_id}/address/resolve",
            json={"text": "an arbitrary hotel that is not in the demo fixture"},
        )
        assert searched.status_code == 200
        assert searched.json()["low_confidence"] is False
        assert searched.json()["candidates"][0]["place_id"] == "hotel_demo_01"
        assert searched.json()["candidates"][0]["hotel_name"] == "YOBI Myeongdong Hotel"
        assert searched.json()["candidates"][0]["road_address"] == "서울특별시 중구 을지로 21"
        rendered_candidates = " ".join(
            f"{item['hotel_name']} {item['road_address']}"
            for item in searched.json()["candidates"]
        )
        assert "demo" not in rendered_candidates.lower()
        assert "데모" not in rendered_candidates
        assert "prepared YOBI Myeongdong delivery address" in searched.json()["notice"]
        assert "Demo" not in searched.json()["notice"]
        assert "manually" not in searched.json()["notice"]

        uploaded = client.post(
            f"/api/v1/sessions/{session.session_id}/address/attachments",
            files={
                "file": (
                    "unrelated-booking-image.png",
                    image_buffer.getvalue(),
                    "image/png",
                )
            },
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["low_confidence"] is False
        assert uploaded.json()["candidates"][0]["place_id"] == "hotel_demo_01"
        rendered_candidates = " ".join(
            f"{item['hotel_name']} {item['road_address']}"
            for item in uploaded.json()["candidates"]
        )
        assert "demo" not in rendered_candidates.lower()
        assert "데모" not in rendered_candidates
        assert "prepared YOBI Myeongdong delivery address" in uploaded.json()["notice"]
        assert "Demo" not in uploaded.json()["notice"]
        assert "manually" not in uploaded.json()["notice"]
    finally:
        app.dependency_overrides.clear()
