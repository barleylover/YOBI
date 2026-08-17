#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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


def _require_list(response: httpx.Response, expected: int = 200) -> list[dict]:
    if response.status_code != expected:
        raise RuntimeError(f"STRUCTURED_SMOKE_HTTP_{response.status_code}")
    payload = response.json() if response.content else []
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise TypeError("STRUCTURED_SMOKE_LIST_RESPONSE_INVALID")
    return payload


def _criteria(category_code: str, option_code: str) -> dict:
    selections: dict[str, list[str]] = {
        "cuisine_origins": [],
        "flavors": [],
        "main_ingredients": [],
        "food_forms": [],
        "temperatures": [],
        "price_bands": [],
        "textures": [],
        "cooking_methods": [],
    }
    selections[category_code] = [option_code]
    return {
        "schema_version": "2",
        **selections,
        "dietary_filters": {
            "halal_certified_only": False,
            "vegan": False,
        },
        "max_spice_level": 5,
        "spice_reference_country": "KR",
    }


def _select_supported_criteria(
    client: httpx.Client,
    session_id: str,
    catalog: dict,
) -> dict:
    for category in catalog.get("categories", []):
        category_code = str(category.get("code", ""))
        if not category_code or category_code == "price_bands":
            continue
        for option in category.get("options", []):
            option_code = str(option.get("code", ""))
            if not option_code or option.get("active", True) is False:
                continue
            criteria = _criteria(category_code, option_code)
            preview = _require(
                client.post(
                    f"/api/v1/sessions/{session_id}/structured-recommendations/preview",
                    json=criteria,
                )
            )
            if int(preview.get("eligible_menu_count", 0)) >= 3:
                if not preview.get("support_manifest_sha256") or not preview.get(
                    "ranking_policy_version"
                ):
                    raise RuntimeError("STRUCTURED_SMOKE_PREVIEW_RELEASE_IDENTITY_MISSING")
                return criteria
    raise RuntimeError("STRUCTURED_SMOKE_ACTIVE_CORE_OPTION_UNAVAILABLE")


def _menu_id(recommendation: dict) -> str:
    menu = recommendation.get("menu")
    menu_id = menu.get("menu_id") if isinstance(menu, dict) else None
    if not menu_id:
        menu_id = recommendation.get("menu_id")
    if not isinstance(menu_id, str) or not menu_id:
        raise RuntimeError("STRUCTURED_SMOKE_RECOMMENDATION_MENU_ID_MISSING")
    return menu_id


def _required_option_selections(groups: list[dict]) -> list[tuple[str, list[str]]]:
    selections: list[tuple[str, list[str]]] = []
    for group in groups:
        group_id = str(group.get("option_group_id") or "")
        minimum = int(group.get("min_select") or 0)
        maximum = int(group.get("max_select") or 0)
        required = bool(group.get("required"))
        count = max(minimum, 1 if required else 0)
        if count == 0:
            continue
        if not group_id or count > maximum:
            raise RuntimeError("STRUCTURED_SMOKE_OPTION_GROUP_INVALID")
        available_ids = [
            str(item.get("option_item_id"))
            for item in group.get("items", [])
            if isinstance(item, dict)
            and item.get("available") is True
            and item.get("option_item_id")
        ]
        if len(available_ids) < count:
            raise RuntimeError("STRUCTURED_SMOKE_REQUIRED_OPTION_UNAVAILABLE")
        selections.append((group_id, available_ids[:count]))
    if selections:
        return selections
    for group in groups:
        group_id = str(group.get("option_group_id") or "")
        maximum = int(group.get("max_select") or 0)
        available_ids = [
            str(item.get("option_item_id"))
            for item in group.get("items", [])
            if isinstance(item, dict)
            and item.get("available") is True
            and item.get("option_item_id")
        ]
        if group_id and maximum > 0 and available_ids:
            return [(group_id, available_ids[:1])]
    return selections


def run(base_url: str) -> None:
    criteria_request_id = f"criteria-smoke-{uuid4().hex}"
    recommendation_request_id = f"recommendation-smoke-{uuid4().hex}"
    profile_id: str | None = None
    session_id: str | None = None
    checkout_id: str | None = None
    order_id: str | None = None
    recommendations: list[dict] = []
    selected_option_count = 0
    repository = get_repository()
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=180) as client:
            ready = _require(client.get("/readyz"))
            if ready.get("status") != "ready":
                raise RuntimeError("STRUCTURED_SMOKE_NOT_READY")
            catalog = _require(
                client.get("/api/v1/recommendation/preferences/catalog?locale=en")
            )
            profile = _require(
                client.post(
                    "/api/v1/profiles",
                    json={
                        "preferred_language": "English",
                        "nationality": "United States",
                        "age_band": "Prefer not to say",
                        "gender": "Prefer not to say",
                        "religion_selection": "Prefer not to say",
                        "dietary_rules": [],
                        "allergy_severity": "mild",
                        "spice_tolerance": 1,
                        "favorite_foods": [],
                        "consent_demo_data": True,
                        "remember_profile": False,
                    },
                ),
                201,
            )
            profile_id = str(profile["profile_id"])
            session = _require(
                client.post(
                    "/api/v1/sessions",
                    json={"profile_id": profile_id},
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
            address = _require(
                client.post(
                    f"/api/v1/sessions/{session_id}/address/confirm",
                    json={"candidate_token": candidates[0]["candidate_token"]},
                )
            )
            criteria = _select_supported_criteria(client, session_id, catalog)
            current_session = _require(client.get(f"/api/v1/sessions/{session_id}"))
            commit = _require(
                client.put(
                    f"/api/v1/sessions/{session_id}/recommendation-criteria",
                    json={
                        "criteria": criteria,
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

            selected_menu_id = ""
            option_groups: list[dict] = []
            option_selections: list[tuple[str, list[str]]] = []
            for recommendation in recommendations:
                candidate_menu_id = _menu_id(recommendation)
                candidate_groups = _require_list(
                    client.get(f"/api/v1/menus/{candidate_menu_id}/options")
                )
                if not candidate_groups:
                    continue
                candidate_selections = _required_option_selections(candidate_groups)
                if candidate_selections:
                    selected_menu_id = candidate_menu_id
                    option_groups = candidate_groups
                    option_selections = candidate_selections
                    break
            if not selected_menu_id or not option_groups or not option_selections:
                raise RuntimeError("STRUCTURED_SMOKE_SELECTABLE_OPTION_MENU_MISSING")
            selected = _require(
                client.post(
                    f"/api/v1/sessions/{session_id}/events",
                    json={
                        "event_type": "SELECT_MENU",
                        "snapshot_id": batch["snapshot_id"],
                        "menu_id": selected_menu_id,
                        "expected_state_version": batch["state_version"],
                        "idempotency_key": f"select-smoke-{uuid4().hex}",
                    },
                )
            )
            if selected.get("selected_menu_id") != selected_menu_id:
                raise RuntimeError("STRUCTURED_SMOKE_MENU_SELECTION_FAILED")
            option_item_ids: list[str] = []
            state_version = int(selected["state_version"])
            for option_group_id, group_item_ids in option_selections:
                option_state = _require(
                    client.post(
                        f"/api/v1/sessions/{session_id}/events",
                        json={
                            "event_type": "UPDATE_OPTIONS",
                            "menu_id": selected_menu_id,
                            "option_group_id": option_group_id,
                            "option_item_ids": group_item_ids,
                            "expected_state_version": state_version,
                            "idempotency_key": f"option-smoke-{uuid4().hex}",
                        },
                    )
                )
                state_version = int(option_state["state_version"])
                option_item_ids.extend(group_item_ids)
            selected_option_count = len(option_item_ids)
            if selected_option_count == 0:
                raise RuntimeError("STRUCTURED_SMOKE_OPTION_SELECTION_UNAVAILABLE")

            cart = _require(
                client.post(
                    f"/api/v1/sessions/{session_id}/cart/items",
                    headers={"Idempotency-Key": f"cart-smoke-{uuid4().hex}"},
                    json={
                        "menu_id": selected_menu_id,
                        "quantity": 1,
                        "option_item_ids": option_item_ids,
                        "user_note": "Please prepare this demo order as selected.",
                    },
                )
            )
            if not cart.get("items") or int(cart.get("total_price", 0)) <= 0:
                raise RuntimeError("STRUCTURED_SMOKE_CART_ITEM_FAILED")
            minimum = int(cart.get("minimum_order_amount", 0))
            if int(cart.get("minimum_order_shortfall", 0)) > 0:
                line = cart["items"][0]
                per_item = int(line["line_total"]) // int(line["quantity"])
                quantity = (minimum + per_item - 1) // per_item if per_item > 0 else 11
                if quantity > 10:
                    raise RuntimeError("STRUCTURED_SMOKE_MINIMUM_ORDER_UNREACHABLE")
                cart = _require(
                    client.patch(
                        f"/api/v1/sessions/{session_id}/cart/items/{line['cart_item_id']}",
                        json={"quantity": max(1, quantity)},
                    )
                )
            cart = _require(
                client.patch(
                    f"/api/v1/sessions/{session_id}/delivery",
                    json={
                        "address_ref_id": address["address_ref_id"],
                        "handoff_method": "front_desk",
                        "cutlery": False,
                        "ring_bell": False,
                        "front_desk": True,
                        "user_note": (
                            "Please leave it at the fixed demo hotel front desk. "
                            "No disposable cutlery."
                        ),
                    },
                )
            )
            if cart.get("ready_to_checkout") is not True:
                raise RuntimeError("STRUCTURED_SMOKE_CART_NOT_READY")
            confirmed = _require(
                client.post(f"/api/v1/sessions/{session_id}/cart/confirm")
            )
            if confirmed.get("confirmed") is not True:
                raise RuntimeError("STRUCTURED_SMOKE_CART_CONFIRM_FAILED")
            checkout = _require(
                client.post(
                    f"/api/v1/sessions/{session_id}/checkout",
                    json={
                        "idempotency_key": f"checkout-smoke-{uuid4().hex}",
                        "payment_method": "international_card",
                    },
                )
            )
            checkout_id = str(checkout["checkout_id"])
            paid = _require(
                client.post(f"/api/v1/checkout/{checkout_id}/mock-success")
            )
            if paid.get("status") != "SUCCEEDED" or not paid.get("order_id"):
                raise RuntimeError("STRUCTURED_SMOKE_MOCK_CHECKOUT_FAILED")
            order_id = str(paid["order_id"])
            order = _require(client.get(f"/api/v1/orders/{order_id}"))
            if order.get("order_status") != "CONFIRMED" or order.get("is_synthetic") is not True:
                raise RuntimeError("STRUCTURED_SMOKE_ORDER_CONFIRMATION_FAILED")

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
        if (
            replay is None
            or replay.dispatch_count != 1
            or replay.result_json != record.result_json
        ):
            raise RuntimeError("STRUCTURED_SMOKE_REPLAY_LEDGER_INVALID")
    finally:
        primary_error = sys.exc_info()[0] is not None
        cleanup_ok = True
        if profile_id is not None:
            cleanup_ok = repository.delete_profile(profile_id)
            if session_id is not None and repository.get_session(session_id) is not None:
                cleanup_ok = False
            if checkout_id is not None and repository.get_checkout(checkout_id) is not None:
                cleanup_ok = False
            if order_id is not None and repository.get_order(order_id) is not None:
                cleanup_ok = False
        if not cleanup_ok and not primary_error:
            raise RuntimeError("STRUCTURED_SMOKE_PROFILE_CASCADE_CLEANUP_FAILED")

    print(
        json.dumps(
            {
                "status": "PASS",
                "gate": "structured-normal-order",
                "recommendation_count": len(recommendations),
                "selected_option_count": selected_option_count,
                "generation_dispatch_count": 1,
                "mock_checkout_status": "SUCCEEDED",
                "order_status": "CONFIRMED",
                "profile_cascade_cleanup": True,
            },
            sort_keys=True,
        )
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
