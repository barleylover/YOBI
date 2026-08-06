import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.dependencies import get_repository
from app.domain.models import AddressCandidate, ProfileCreate
from app.main import app
from app.services.address_ocr import AddressCandidateTokenCodec, FixtureAddressOcrAdapter


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
