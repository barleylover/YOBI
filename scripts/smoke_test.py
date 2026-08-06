from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("YOBI_SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def require(response: httpx.Response, expected: int = 200) -> dict:
    if response.status_code != expected:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        ready = require(client.get("/readyz"))
        assert ready["status"] == "ready"

        profile = require(
            client.post(
                "/api/v1/profiles",
                json={
                    "preferred_language": "English",
                    "nationality": "United States",
                    "age_band": "25-34",
                    "gender": "Prefer not to say",
                    "religion_selection": "No specific religion",
                    "dietary_rules": ["shellfish_allergy"],
                    "allergy_severity": "severe",
                    "spice_tolerance": 1,
                    "favorite_foods": ["creamy pasta", "chicken noodle soup"],
                    "consent_demo_data": True,
                    "remember_profile": False,
                },
            ),
            201,
        )
        session = require(
            client.post("/api/v1/sessions", json={"profile_id": profile["profile_id"]}),
            201,
        )
        session_id = session["session_id"]

        turn = require(
            client.post(
                f"/api/v1/sessions/{session_id}/messages",
                json={
                    "content": (
                        "I saw people eating some red rice cake dish on the street. "
                        "What is that? Can I order it?"
                    )
                },
            )
        )
        assert turn["fallback_used"] is True or turn["cards"]
        assert "avoid" in turn["text"].lower()
        assert any(card["type"] == "dietary_evidence" for card in turn["cards"])

        cart = require(
            client.post(
                f"/api/v1/sessions/{session_id}/cart/items",
                json={
                    "menu_id": "menu_001_01",
                    "quantity": 1,
                    "option_item_ids": [
                        "oi_001_01_spice_mild",
                        "oi_001_01_size_regular",
                        "oi_001_01_cheese_add",
                        "oi_001_01_fishcake_remove",
                    ],
                    "user_note": "As mild as possible, please.",
                },
            )
        )
        assert cart["total_price"] > 0

        booking = ROOT / "frontend" / "public" / "demo-booking.png"
        with booking.open("rb") as handle:
            upload = require(
                client.post(
                    f"/api/v1/sessions/{session_id}/address/attachments",
                    files={"file": ("yobi-demo-booking.png", handle, "image/png")},
                )
            )
        assert upload["candidates"]
        address = require(
            client.post(
                f"/api/v1/sessions/{session_id}/address/confirm",
                json={"candidate_token": upload["candidates"][0]["candidate_token"]},
            )
        )
        cart = require(
            client.patch(
                f"/api/v1/sessions/{session_id}/delivery",
                json={
                    "address_ref_id": address["address_ref_id"],
                    "handoff_method": "front_desk",
                    "cutlery": False,
                    "ring_bell": False,
                    "front_desk": True,
                    "user_note": (
                        "Please leave it at the hotel front desk. No disposable cutlery."
                    ),
                },
            )
        )
        assert cart["ready_to_checkout"] is True
        require(client.post(f"/api/v1/sessions/{session_id}/cart/confirm"))
        checkout = require(
            client.post(
                f"/api/v1/sessions/{session_id}/checkout",
                json={
                    "idempotency_key": f"smoke-{uuid4().hex}",
                    "payment_method": "international_card",
                },
            )
        )
        paid = require(client.post(f"/api/v1/checkout/{checkout['checkout_id']}/mock-success"))
        assert paid["status"] == "SUCCEEDED" and paid["order_id"]
        order = require(client.get(f"/api/v1/orders/{paid['order_id']}"))
        assert order["order_status"] == "CONFIRMED"

    print("PASS: health, evidence, cart, address upload, delivery, mock payment, and order")


if __name__ == "__main__":
    main()
