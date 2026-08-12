#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.dependencies import get_repository
from app.domain.structured_recommendation import RecommendationRequestStatus


def _require(response: httpx.Response, expected: int = 200) -> dict:
    if response.status_code != expected:
        raise RuntimeError(f"STRUCTURED_SMOKE_HTTP_{response.status_code}")
    payload = response.json() if response.content else {}
    if not isinstance(payload, dict):
        raise TypeError("STRUCTURED_SMOKE_RESPONSE_INVALID")
    return payload


def _contains_supported_korean_option(catalog: dict) -> bool:
    for category in catalog.get("categories", []):
        if category.get("code") != "cuisine_origins":
            continue
        return any(option.get("code") == "KOREAN" for option in category.get("options", []))
    return False


def run(base_url: str) -> None:
    criteria_request_id = f"criteria-smoke-{uuid4().hex}"
    recommendation_request_id = f"recommendation-smoke-{uuid4().hex}"
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=180) as client:
        ready = _require(client.get("/readyz"))
        if ready.get("status") != "ready":
            raise RuntimeError("STRUCTURED_SMOKE_NOT_READY")
        catalog = _require(
            client.get("/api/v1/recommendation/preferences/catalog?locale=en")
        )
        if not _contains_supported_korean_option(catalog):
            raise RuntimeError("STRUCTURED_SMOKE_KOREAN_OPTION_UNAVAILABLE")
        profile = _require(
            client.post(
                "/api/v1/profiles",
                json={
                    "preferred_language": "English",
                    "nationality": "United States",
                    "age_band": "25-34",
                    "gender": "Prefer not to say",
                    "religion_selection": "Prefer not to say",
                    "dietary_rules": [],
                    "allergy_severity": "mild",
                    "spice_tolerance": 1,
                    "favorite_foods": ["Korean food"],
                    "consent_demo_data": True,
                    "remember_profile": False,
                },
            ),
            201,
        )
        session = _require(
            client.post(
                "/api/v1/sessions",
                json={"profile_id": profile["profile_id"]},
            ),
            201,
        )
        session_id = str(session["session_id"])
        booking_response = client.get("/demo-booking.png")
        if booking_response.status_code != 200 or not booking_response.content:
            raise RuntimeError("STRUCTURED_SMOKE_BOOKING_FIXTURE_UNAVAILABLE")
        upload = _require(
            client.post(
                f"/api/v1/sessions/{session_id}/address/attachments",
                files={
                    "file": (
                        "yobi-demo-booking.png",
                        booking_response.content,
                        "image/png",
                    )
                },
            )
        )
        candidates = upload.get("candidates", [])
        if not candidates:
            raise RuntimeError("STRUCTURED_SMOKE_ADDRESS_CANDIDATE_MISSING")
        _require(
            client.post(
                f"/api/v1/sessions/{session_id}/address/confirm",
                json={"candidate_token": candidates[0]["candidate_token"]},
            )
        )
        current_session = _require(client.get(f"/api/v1/sessions/{session_id}"))
        commit = _require(
            client.put(
                f"/api/v1/sessions/{session_id}/recommendation-criteria",
                json={
                    "criteria": {
                        "schema_version": "2",
                        "cuisine_origins": ["KOREAN"],
                        "flavors": [],
                        "main_ingredients": [],
                        "food_forms": [],
                        "temperatures": [],
                        "price_bands": [],
                        "textures": [],
                        "cooking_methods": [],
                        "dietary_filters": {
                            "halal_certified_only": False,
                            "vegan": False,
                        },
                        "max_spice_level": 5,
                        "spice_reference_country": "KR",
                    },
                    "catalog_version": catalog["catalog_version"],
                    "expected_state_version": current_session["state_version"],
                    "request_id": criteria_request_id,
                },
            )
        )
        batch = _require(
            client.post(
                f"/api/v1/sessions/{session_id}/recommendations",
                json={
                    "request_id": recommendation_request_id,
                    "expected_state_version": commit["state_version"],
                    "criteria_version": commit["criteria_version"],
                    "mode": "INITIAL",
                },
            )
        )
        if batch.get("status") != "RECOMMENDED":
            raise RuntimeError("STRUCTURED_SMOKE_NORMAL_RESULT_REQUIRED")
        recommendations = batch.get("recommendations", [])
        if not recommendations or not batch.get("snapshot_id"):
            raise RuntimeError("STRUCTURED_SMOKE_RECOMMENDATIONS_MISSING")
        if not all(item.get("matched_criteria") for item in recommendations):
            raise RuntimeError("STRUCTURED_SMOKE_CRITERIA_GROUNDING_MISSING")
        if not any(item.get("wiki_passages") for item in recommendations):
            raise RuntimeError("STRUCTURED_SMOKE_WIKI_GROUNDING_MISSING")

    repository = get_repository()
    record = repository.get_recommendation_request(
        session_id,
        recommendation_request_id,
    )
    if record is None:
        raise RuntimeError("STRUCTURED_SMOKE_LEDGER_MISSING")
    if (
        record.status is not RecommendationRequestStatus.COMPLETED
        or record.dispatch_count != 1
        or record.failure_code is not None
        or record.snapshot_id != batch["snapshot_id"]
    ):
        raise RuntimeError("STRUCTURED_SMOKE_ONE_DISPATCH_LEDGER_INVALID")
    replay = repository.get_recommendation_request(session_id, recommendation_request_id)
    if replay is None or replay.dispatch_count != 1 or replay.result_json != record.result_json:
        raise RuntimeError("STRUCTURED_SMOKE_REPLAY_LEDGER_INVALID")
    print(
        "PASS: structured v2 live normal recommendation, grounded Wiki evidence, "
        f"one dispatch, and idempotent ledger; result_count={len(recommendations)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the live structured-v2 release gate")
    parser.add_argument(
        "--base-url",
        default=os.getenv("YOBI_SMOKE_BASE_URL", "http://127.0.0.1"),
    )
    args = parser.parse_args()
    run(args.base_url)


if __name__ == "__main__":
    main()
