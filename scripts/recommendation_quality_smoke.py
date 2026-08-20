#!/usr/bin/env python3
"""Run exactly five grounded recommendation quality checks over public HTTP."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import monotonic, perf_counter, sleep
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(SCRIPTS))

from recommendation_http import await_recommendation_response
from recommendation_performance_smoke import (
    Scenario,
    _catalog_options,
    _criteria_for,
    _http_setup,
    _prepared_http_context,
    _require_http,
)

QUALITY_SAMPLE_COUNT = 5
DEFAULT_SPACING_SECONDS = 65.0
EXPANSION_CUISINE_CODES = (
    "JAPANESE",
    "ITALIAN",
    "AMERICAN",
    "SOUTHEAST_ASIAN",
    "MEXICAN",
)
QUALITY_CASE_LANGUAGES = {
    "JAPANESE": "한국어",
    "ITALIAN": "English",
    "AMERICAN": "English",
    "SOUTHEAST_ASIAN": "한국어",
    "MEXICAN": "English",
}
_HANGUL = re.compile(r"[가-힣]")
_UNSAFE_GENERATED_MARKERS = (
    "comparison_basis=",
    "general_food_reference=",
    "placeholder",
    "todo",
)


@dataclass(frozen=True)
class QualityCase:
    name: str
    scenario: Scenario
    language: str


def _preview(client: httpx.Client, session_id: str, criteria: Any) -> dict[str, Any]:
    return _require_http(
        client.post(
            f"/api/v1/sessions/{session_id}/structured-recommendations/preview",
            json=criteria.model_dump(mode="json"),
        )
    )


def _discover_scenarios(base_url: str) -> tuple[dict[str, Scenario], dict[str, str]]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=180) as client:
        profile_id = ""
        try:
            profile_id, session_id, catalog, _ = _http_setup(
                client,
                language="English",
            )
            options = _catalog_options(catalog)
            available_cuisines = set(options.get("cuisine_origins", []))
            scenarios: dict[str, Scenario] = {}
            for cuisine_code in EXPANSION_CUISINE_CODES:
                if cuisine_code not in available_cuisines:
                    raise RuntimeError("QUALITY_EXPANSION_CUISINE_NOT_EXPOSED")
                candidate = _criteria_for({"cuisine_origins": [cuisine_code]})
                preview = _preview(client, session_id, candidate)
                if (
                    int(preview["eligible_menu_count"]) < 3
                    or int(preview["eligible_merchant_count"]) < 3
                ):
                    raise RuntimeError("QUALITY_EXPANSION_CUISINE_POOL_TOO_SMALL")
                scenarios[cuisine_code] = Scenario(
                    f"cuisine_{cuisine_code.casefold()}", candidate
                )
            return (
                scenarios,
                {
                    "catalog_version": str(catalog.get("catalog_version", "unknown")),
                },
            )
        finally:
            if profile_id:
                client.delete(f"/api/v1/profiles/{profile_id}")


def _price_matches(price: int, bands: list[str]) -> bool:
    if not bands:
        return True
    return any(
        (band == "UNDER_10000" and price < 10_000)
        or (band == "FROM_10000_TO_19999" and 10_000 <= price < 20_000)
        or (band == "FROM_20000_TO_29999" and 20_000 <= price < 30_000)
        or (band == "OVER_30000" and price >= 30_000)
        for band in bands
    )


def _text_is_usable(value: Any, *, minimum: int) -> bool:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        return False
    normalized = value.casefold()
    return not any(marker in normalized for marker in _UNSAFE_GENERATED_MARKERS)


def _validate_batch(
    batch: dict[str, Any],
    scenario: Scenario,
    *,
    language: str,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    recommendations = batch.get("recommendations")
    if not isinstance(recommendations, list):
        recommendations = []
    if batch.get("status") != "RECOMMENDED":
        errors.append("STATUS_NOT_RECOMMENDED")
    if batch.get("failure_code") is not None:
        errors.append("FAILURE_CODE_PRESENT")
    if not batch.get("snapshot_id"):
        errors.append("SNAPSHOT_MISSING")
    if len(recommendations) != 3:
        errors.append("RESULT_COUNT_NOT_THREE")
    if batch.get("unmatched_category_codes"):
        errors.append("UNMATCHED_CATEGORY_PRESENT")
    criteria_summary = batch.get("criteria_summary")
    if not _text_is_usable(criteria_summary, minimum=4):
        errors.append("CRITERIA_SUMMARY_INVALID")

    criteria = scenario.criteria
    required_groups = criteria.subjective_groups()
    menu_ids: list[str] = []
    merchant_ids: list[str] = []
    evidence_count = 0
    matched_group_counts: list[int] = []
    generated_text: list[str] = [str(criteria_summary or "")]
    for expected_rank, item in enumerate(recommendations, start=1):
        if not isinstance(item, dict):
            errors.append("RECOMMENDATION_OBJECT_INVALID")
            continue
        if item.get("rank") != expected_rank:
            errors.append("RANK_SEQUENCE_INVALID")
        menu = item.get("menu")
        if not isinstance(menu, dict):
            errors.append("MENU_OBJECT_INVALID")
            continue
        menu_id = str(menu.get("menu_id") or "")
        merchant_id = str(menu.get("merchant_id") or "")
        if not menu_id or not merchant_id:
            errors.append("MENU_IDENTITY_MISSING")
        menu_ids.append(menu_id)
        merchant_ids.append(merchant_id)
        try:
            price = int(str(menu.get("price")))
        except (TypeError, ValueError):
            errors.append("PRICE_INVALID")
        else:
            if price <= 0 or not _price_matches(price, criteria.price_bands):
                errors.append("PRICE_CRITERIA_MISMATCH")

        for field, minimum in (
            ("title", 2),
            ("description", 10),
        ):
            value = item.get(field)
            generated_text.append(str(value or ""))
            if not _text_is_usable(value, minimum=minimum):
                errors.append(f"{field.upper()}_INVALID")

        passages = item.get("wiki_passages")
        if not isinstance(passages, list) or not passages:
            errors.append("WIKI_EVIDENCE_MISSING")
        else:
            for passage in passages:
                if not isinstance(passage, dict) or not passage.get("evidence_id") or not str(
                    passage.get("content") or ""
                ).strip():
                    errors.append("WIKI_EVIDENCE_INVALID")
                else:
                    evidence_count += 1

        matched = item.get("matched_criteria")
        matched = matched if isinstance(matched, list) else []
        matched_groups = 0
        for category, selected_codes in required_groups.items():
            category_matches = [
                entry
                for entry in matched
                if isinstance(entry, dict) and entry.get("category_code") == category
            ]
            valid_match = any(
                {str(code) for code in entry.get("selected_value_codes", [])}
                & set(selected_codes)
                and bool(entry.get("evidence_ids"))
                for entry in category_matches
            )
            if valid_match:
                matched_groups += 1
            else:
                errors.append("SELECTED_CRITERION_EVIDENCE_MISSING")
        matched_group_counts.append(matched_groups)

    if len(set(menu_ids)) != len(menu_ids):
        errors.append("DUPLICATE_MENU")
    if len(set(merchant_ids)) != len(merchant_ids):
        errors.append("DUPLICATE_MERCHANT")
    if language == "한국어" and not _HANGUL.search(" ".join(generated_text)):
        errors.append("KOREAN_GENERATED_COPY_MISSING")

    errors = sorted(set(errors))
    digest = hashlib.sha256(
        json.dumps(menu_ids, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    return errors, {
        "result_count": len(recommendations),
        "merchant_count": len(set(merchant_ids)),
        "evidence_count": evidence_count,
        "required_group_count": len(required_groups),
        "matched_group_count_min": min(matched_group_counts, default=0),
        "selected_cuisine_codes": list(criteria.cuisine_origins),
        "menu_order_sha256": digest,
    }


def _run_case(
    base_url: str,
    case: QualityCase,
    *,
    wait_for_dispatch: Any,
) -> dict[str, Any]:
    try:
        with _prepared_http_context(
            base_url,
            case.scenario,
            language=case.language,
        ) as context:
            wait_for_dispatch()
            started = perf_counter()
            response = context.client.post(
                f"/api/v1/sessions/{context.session_id}/recommendations",
                json={
                    "request_id": f"quality-{uuid4().hex}",
                    "expected_state_version": context.state_version,
                    "criteria_version": context.criteria_version,
                    "mode": "INITIAL",
                },
            )
            batch = await_recommendation_response(
                context.client,
                session_id=context.session_id,
                initial_response=response,
                error_prefix="QUALITY",
            )
            latency_ms = round((perf_counter() - started) * 1_000, 3)
            errors, evidence = _validate_batch(
                batch,
                case.scenario,
                language=case.language,
            )
            return {
                "name": case.name,
                "language": "ko" if case.language == "한국어" else "en",
                "status": "PASS" if not errors else "FAIL",
                "latency_ms": latency_ms,
                "error_codes": errors,
                **evidence,
            }
    except Exception as exc:  # noqa: BLE001 - sanitized failure only
        return {
            "name": case.name,
            "language": "ko" if case.language == "한국어" else "en",
            "status": "FAIL",
            "latency_ms": None,
            "error_codes": [type(exc).__name__.upper()],
            "result_count": 0,
            "merchant_count": 0,
            "evidence_count": 0,
            "required_group_count": len(case.scenario.criteria.subjective_groups()),
            "matched_group_count_min": 0,
            "menu_order_sha256": None,
        }


def run(base_url: str, *, spacing_seconds: float) -> tuple[dict[str, Any], int]:
    scenarios, release = _discover_scenarios(base_url)
    cases = [
        QualityCase(
            f"expanded_{code.casefold()}",
            scenarios[code],
            QUALITY_CASE_LANGUAGES[code],
        )
        for code in EXPANSION_CUISINE_CODES
    ]
    previous_start: float | None = None

    def wait_for_dispatch() -> None:
        nonlocal previous_start
        if previous_start is not None:
            remaining = spacing_seconds - (monotonic() - previous_start)
            if remaining > 0:
                sleep(remaining)
        previous_start = monotonic()

    results = [
        _run_case(base_url, case, wait_for_dispatch=wait_for_dispatch) for case in cases
    ]
    covered_cuisines = {
        code
        for result in results
        for code in result.get("selected_cuisine_codes", [])
    }
    coverage_complete = covered_cuisines == set(EXPANSION_CUISINE_CODES)
    valid_latencies = [
        float(result["latency_ms"])
        for result in results
        if result["latency_ms"] is not None
    ]
    passed = (
        all(result["status"] == "PASS" for result in results)
        and coverage_complete
    )
    payload = {
        "status": "PASS" if passed else "FAIL",
        "gate": "recommendation-quality-five",
        "requested": QUALITY_SAMPLE_COUNT,
        "completed": sum(result["status"] == "PASS" for result in results),
        "expansion_cuisine_codes": list(EXPANSION_CUISINE_CODES),
        "expansion_cuisine_coverage_complete": coverage_complete,
        "latency_ms": {
            "median": round(median(valid_latencies), 3) if valid_latencies else None,
            "max": round(max(valid_latencies), 3) if valid_latencies else None,
            "percentile_claim": "not_made_for_five_samples",
        },
        "release": release,
        "cases": results,
    }
    return payload, 0 if passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run exactly five strict YOBI recommendation quality checks."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1")
    parser.add_argument(
        "--spacing-seconds",
        type=float,
        default=DEFAULT_SPACING_SECONDS,
    )
    args = parser.parse_args()
    if args.spacing_seconds < 0:
        parser.error("--spacing-seconds must be at least 0")
    try:
        payload, exit_code = run(args.base_url, spacing_seconds=args.spacing_seconds)
    except Exception as exc:  # noqa: BLE001 - sanitized one-line JSON only
        payload = {"status": "FAIL", "error_code": type(exc).__name__.upper()}
        exit_code = 1
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
