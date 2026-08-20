#!/usr/bin/env python3
"""Bounded GenAI release probes for recommendation-v3.

``predeploy`` performs one staged-family selection dispatch and, on a cold cache,
one presentation dispatch. ``postdeploy`` performs five fixed public-API logical
recommendation jobs. Provider fallbacks remain disabled by the gate configuration.
Every run reserves a unique run id before dispatch and writes an immutable JSON
artifact plus SHA-256 sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter, sleep
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
for path in (BACKEND, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.core.config import Settings, get_settings
from app.dependencies import get_repository
from app.domain.structured_recommendation import (
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationRequestStatus,
)
from app.genai.presentation_generator import MenuPresentationGenerator
from app.genai.providers import choose_genai_provider
from app.genai.recommendation_generator import RecommendationGenerator
from app.services.menu_presentation import MenuPresentationService
from app.services.structured_recommendation import (
    StructuredRecommendationService,
    compact_generation_payload,
)
from recommendation_http import await_recommendation_response
from recommendation_performance_smoke import (
    Scenario,
    _criteria_for,
    _new_repository_context,
    _prepared_http_context,
)
from recommendation_quality_smoke import _validate_batch

PREDEPLOY_CASE_NAME = "predeploy_spicy_fried_chicken_en"
POSTDEPLOY_CASE_COUNT = 5
DIAGNOSTIC_FOUR_CASE_COUNT = 4
POSTDEPLOY_INTERVAL_SECONDS = 60
POSTDEPLOY_CASES = (
    (
        "postdeploy_spicy_noodles_ko",
        "한국어",
        {"flavors": ["SPICY"], "food_forms": ["NOODLES"]},
    ),
    (
        "postdeploy_crispy_chicken_fried_en",
        "English",
        {
            "textures": ["CRISPY"],
            "main_ingredients": ["CHICKEN"],
            "cooking_methods": ["FRIED"],
        },
    ),
    (
        "postdeploy_clean_mild_soup_hot_ko",
        "한국어",
        {
            "flavors": ["CLEAN_MILD"],
            "food_forms": ["SOUP"],
            "temperatures": ["HOT"],
        },
    ),
    (
        "postdeploy_italian_noodles_10k_19k_en",
        "English",
        {
            "cuisine_origins": ["ITALIAN"],
            "food_forms": ["NOODLES"],
            "price_bands": ["FROM_10000_TO_19999"],
        },
    ),
    (
        "postdeploy_sweet_frozen_dessert_ko",
        "한국어",
        {
            "flavors": ["SWEET"],
            "temperatures": ["FROZEN"],
            "food_forms": ["DESSERT_BAKERY"],
        },
    ),
)
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
TERMINAL_STATUSES = {
    RecommendationRequestStatus.COMPLETED,
    RecommendationRequestStatus.NO_RESULTS,
    RecommendationRequestStatus.NO_MATCH,
    RecommendationRequestStatus.SEARCH_FALLBACK,
    RecommendationRequestStatus.FAILED,
    RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH,
}


class CountingProvider:
    """Transparent provider proxy that counts actual create_response calls."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self.call_count = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    def create_response(self, model: str, **kwargs: Any) -> Any:
        self.call_count += 1
        return self._provider.create_response(model, **kwargs)


@dataclass(frozen=True)
class LiveCase:
    name: str
    language: str
    scenario: Scenario


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _exclusive_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _reserve_run(output_dir: Path, mode: str, run_id: str) -> tuple[Path, Path]:
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("LIVE_HARNESS_RUN_ID_INVALID")
    start_path = output_dir / f"{mode}-{run_id}.started.json"
    final_path = output_dir / f"{mode}-{run_id}.json"
    _exclusive_write(
        start_path,
        _canonical_bytes(
            {
                "schema_version": "1",
                "mode": mode,
                "run_id": run_id,
                "started_at": _utc_now(),
                "provider_retry_enabled": False,
            }
        ),
    )
    return start_path, final_path


def _write_artifact(path: Path, payload: dict[str, Any]) -> str:
    encoded = _canonical_bytes(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    _exclusive_write(path, encoded)
    _exclusive_write(
        path.with_suffix(path.suffix + ".sha256"), f"{digest}  {path.name}\n".encode()
    )
    return digest


def _expected_predeploy_run_id(release_family_id: str) -> str:
    digest = hashlib.sha256(release_family_id.encode()).hexdigest()[:32]
    return f"predeploy-{digest}"


def _failed_zero_call_predeploy_is_valid(
    output_dir: Path,
    *,
    release_family_id: str,
    run_id: str,
) -> bool:
    """Validate an immutable failure that never reached the provider."""

    final_path = output_dir / f"predeploy-{run_id}.json"
    sidecar = final_path.with_suffix(final_path.suffix + ".sha256")
    if not final_path.is_file() or final_path.is_symlink() or not sidecar.is_file():
        return False
    encoded = final_path.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    if sidecar.read_text(encoding="utf-8") != f"{digest}  {final_path.name}\n":
        return False
    try:
        payload = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        payload.get("gate") == "recommendation-v2-predeploy-one"
        and payload.get("status") == "FAIL"
        and payload.get("release_family_id") == release_family_id
        and payload.get("provider_call_count") == 0
        and payload.get("provider_retry_count") == 0
    )


def _allowed_predeploy_run_ids(output_dir: Path, release_family_id: str) -> set[str]:
    base_run_id = _expected_predeploy_run_id(release_family_id)
    allowed = {base_run_id}
    previous_run_id = base_run_id
    for recovery_number in range(1, 10):
        if not _failed_zero_call_predeploy_is_valid(
            output_dir,
            release_family_id=release_family_id,
            run_id=previous_run_id,
        ):
            break
        previous_run_id = f"{base_run_id}-r{recovery_number}"
        allowed.add(previous_run_id)
    return allowed


def _reuse_completed_predeploy(
    final_path: Path,
    *,
    release_family_id: str,
) -> str | None:
    sidecar = final_path.with_suffix(final_path.suffix + ".sha256")
    if not final_path.is_file() or final_path.is_symlink() or not sidecar.is_file():
        return None
    encoded = final_path.read_bytes()
    digest = hashlib.sha256(encoded).hexdigest()
    if sidecar.read_text(encoding="utf-8") != f"{digest}  {final_path.name}\n":
        return None
    try:
        payload = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not (
        payload.get("gate") == "recommendation-v2-predeploy-one"
        and payload.get("status") == "PASS"
        and payload.get("release_family_id") == release_family_id
        and payload.get("provider_call_count") == 1
        and payload.get("provider_retry_count") == 0
        and payload.get("error_codes") == []
    ):
        return None
    return digest


def _settings_errors(settings: Settings) -> list[str]:
    checks = {
        "STRUCTURED_MODEL": settings.structured_recommendation_model == "xai.grok-4.3",
        "MAX_OUTPUT_TOKENS": settings.structured_recommendation_max_output_tokens
        == 2048,
        "CANDIDATE_LIMIT": settings.recommendation_candidate_limit == 100,
        "SHORTLIST_LIMIT": settings.recommendation_llm_shortlist_limit == 15,
        "PASSAGES_PER_MENU": settings.recommendation_llm_passages_per_menu == 2,
        "SELECTION_ENABLED": settings.recommendation_llm_selection_enabled is True,
        "CONCURRENCY": settings.structured_recommendation_max_concurrent_requests == 2,
        "TIMEOUT": settings.llm_timeout_seconds == 120.0,
        "RETRY_DISABLED": settings.llm_max_retries == 0,
        "STREAMING_DISABLED": settings.oci_genai_streaming_enabled is False,
        "RAW_JSON_VALIDATION": settings.oci_genai_structured_output_enabled is False,
    }
    return [f"CONFIG_{name}_INVALID" for name, passed in checks.items() if not passed]


def _case_definitions() -> list[LiveCase]:
    return [
        LiveCase(name, language, Scenario(name, _criteria_for(selections)))
        for name, language, selections in POSTDEPLOY_CASES
    ]


def _selected_ids(payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        return [], []
    menu_ids: list[str] = []
    merchant_ids: list[str] = []
    for item in recommendations:
        menu = item.get("menu") if isinstance(item, dict) else None
        menu = menu if isinstance(menu, dict) else {}
        menu_ids.append(str(item.get("menu_id") or menu.get("menu_id") or ""))
        merchant_ids.append(str(menu.get("merchant_id") or ""))
    return menu_ids, merchant_ids


def _record_errors(record: Any, criteria: RecommendationCriteriaV2) -> list[str]:
    if record is None:
        return ["REQUEST_LEDGER_MISSING"]
    errors: list[str] = []
    if record.status is not RecommendationRequestStatus.COMPLETED:
        errors.append(f"LEDGER_STATUS_{record.status.value}")
    if record.dispatch_count != 1:
        errors.append("PROVIDER_DISPATCH_COUNT_NOT_ONE")
    if len(record.evidence_pool_json) != 15:
        errors.append("SHORTLIST_COUNT_NOT_FIFTEEN")
    if len(record.final_candidates_json) != 3:
        errors.append("FINAL_CANDIDATE_COUNT_NOT_THREE")
    if record.ranking_trace_json.get("selection_status") != "GROK_SELECTED":
        errors.append("GROK_SELECTION_STATUS_INVALID")
    if record.ranking_policy_version != "yobi-hybrid-rank-v2":
        errors.append("RANKING_POLICY_INVALID")
    for digest, code in (
        (record.support_manifest_sha256, "SUPPORT_MANIFEST_INVALID"),
        (record.feature_manifest_sha256, "FEATURE_MANIFEST_INVALID"),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest == "0" * 64:
            errors.append(code)

    shortlist_ids = {
        str(item.get("menu", {}).get("menu_id") or item.get("menu_id") or "")
        for item in record.evidence_pool_json
        if isinstance(item, dict)
    }
    final_ids = [
        str(item.get("menu_id") or "") for item in record.final_candidates_json
    ]
    if (
        not final_ids
        or len(set(final_ids)) != len(final_ids)
        or not set(final_ids) <= shortlist_ids
    ):
        errors.append("FINAL_IDS_OUTSIDE_SHORTLIST")

    selected_categories = criteria.subjective_groups()
    pool_by_id = {
        str(item.get("menu", {}).get("menu_id") or item.get("menu_id") or ""): item
        for item in record.evidence_pool_json
        if isinstance(item, dict)
    }
    for menu_id in final_ids:
        item = pool_by_id.get(menu_id, {})
        evidence = item.get("criterion_evidence", [])
        evidenced_categories = {
            str(value.get("category_code"))
            for value in evidence
            if isinstance(value, dict) and value.get("evidence")
        }
        if not set(selected_categories) <= evidenced_categories:
            errors.append("FINAL_SELECTED_CATEGORY_EVIDENCE_MISSING")
    available_merchants = {
        str(item.get("menu", {}).get("merchant_id") or "")
        for item in record.evidence_pool_json
        if isinstance(item, dict)
    }
    selected_merchants = {
        str(item.get("merchant_id") or "") for item in record.final_candidates_json
    }
    if len(available_merchants) >= 3 and len(selected_merchants) != 3:
        errors.append("FINAL_MERCHANT_DIVERSITY_INVALID")
    return sorted(set(errors))


def run_predeploy(release_family_id: str, settings: Settings) -> dict[str, Any]:
    errors = _settings_errors(settings)
    repository = get_repository()
    context = None
    counting_provider = CountingProvider(choose_genai_provider(settings))
    latency_ms: float | None = None
    shortlist: list[Any] = []
    result_payload: dict[str, Any] = {}
    try:
        context = _new_repository_context(repository, language="English")
        criteria = _criteria_for(
            {
                "flavors": ["SPICY"],
                "cooking_methods": ["FRIED"],
                "main_ingredients": ["CHICKEN"],
            }
        )
        preview = repository.preview_recommendation(
            context.session_id,
            criteria,
            release_family_id=release_family_id,
        )
        if preview.eligible_menu_count < 15:
            errors.append("STAGED_SHORTLIST_POOL_TOO_SMALL")
        pool = repository.build_recommendation_evidence_pool(
            context.session_id,
            context.profile,
            criteria,
            RecommendationMode.INITIAL,
            settings.recommendation_candidate_limit,
            release_family_id=release_family_id,
            eligibility_as_of=datetime.now(timezone.utc),
            raw_hits_per_value=settings.recommendation_raw_hits_per_value,
            passages_per_menu=settings.recommendation_passages_per_menu,
        )
        shortlist = StructuredRecommendationService._freeze_server_candidates(
            pool,
            limit=settings.recommendation_llm_shortlist_limit,
        )
        if len(shortlist) != 15:
            errors.append("STAGED_SHORTLIST_COUNT_NOT_FIFTEEN")
        if not errors:
            generator = RecommendationGenerator(settings, provider=counting_provider)
            started = perf_counter()
            generated = generator.generate(
                criteria=criteria.model_dump(mode="json"),
                soft_profile_context={},
                evidence_pool=[
                    compact_generation_payload(
                        item,
                        max_wiki_passages=settings.recommendation_llm_passages_per_menu,
                    )
                    for item in shortlist
                ],
                locale="English",
            )
            latency_ms = round((perf_counter() - started) * 1_000, 3)
            pool_by_id = {item.menu.menu_id: item for item in shortlist}
            selected_evidence = [
                pool_by_id[item.menu_id] for item in generated.recommendations
            ]
            presentation_service = MenuPresentationService(
                repository,
                settings,
                generator=MenuPresentationGenerator(
                    settings,
                    provider=counting_provider,
                ),
            )
            presentations = presentation_service.present_selected(
                selected_evidence,
                session_id=context.session_id,
                language_code="en",
                country_code=context.profile.country_code or "ZZ",
            )
            result_payload = StructuredRecommendationService._validated_result_payload(
                generated,
                shortlist,
                presentations,
                max_wiki_passages=settings.recommendation_llm_passages_per_menu,
            )
            menu_ids, merchant_ids = _selected_ids(result_payload)
            if len(menu_ids) != 3 or len(set(menu_ids)) != 3:
                errors.append("PREDEPLOY_RESULT_COUNT_INVALID")
            if len({value for value in merchant_ids if value}) != 3:
                errors.append("PREDEPLOY_MERCHANT_DIVERSITY_INVALID")
    except Exception as exc:  # noqa: BLE001 - artifact contains safe type only
        errors.append(f"PREDEPLOY_{type(exc).__name__.upper()}")
    finally:
        if context is not None:
            repository.delete_profile(context.profile.profile_id)

    if counting_provider.call_count not in {1, 2}:
        errors.append("PREDEPLOY_PROVIDER_CALL_COUNT_NOT_ONE_OR_TWO")
    menu_ids, merchant_ids = _selected_ids(result_payload)
    return {
        "schema_version": "1",
        "gate": "recommendation-v2-predeploy-one",
        "status": "PASS" if not errors else "FAIL",
        "case": PREDEPLOY_CASE_NAME,
        "release_family_id": release_family_id,
        "structured_model_id": settings.structured_recommendation_model,
        "provider_call_count": counting_provider.call_count,
        "presentation_cache_state": (
            "HIT" if counting_provider.call_count == 1 else "MISS"
        ),
        "provider_retry_count": 0,
        "candidate_limit": settings.recommendation_candidate_limit,
        "shortlist_count": len(shortlist),
        "result_count": len(menu_ids),
        "merchant_count": len({value for value in merchant_ids if value}),
        "menu_order_sha256": hashlib.sha256(
            json.dumps(menu_ids, separators=(",", ":")).encode()
        ).hexdigest(),
        "latency_ms": latency_ms,
        "error_codes": sorted(set(errors)),
    }


def _ready_errors(ready: dict[str, Any]) -> list[str]:
    structured = ready.get("structured_recommendation")
    structured = structured if isinstance(structured, dict) else {}
    checks = {
        "READY_STATUS": ready.get("status") == "ready",
        "MODEL": structured.get("model_id") == "xai.grok-4.3",
        "GROUNDING_DIAGNOSTICS": structured.get("grounding_diagnostics_version")
        == "yobi-grounding-diagnostics-v2",
        "SELECTION": structured.get("selection_enabled") is True,
        "CANDIDATE_LIMIT": structured.get("candidate_limit") == 100,
        "SHORTLIST_LIMIT": structured.get("shortlist_limit") == 15,
        "PASSAGES_PER_MENU": structured.get("passages_per_menu") == 2,
        "MAX_OUTPUT_TOKENS": structured.get("max_output_tokens") == 2048,
        "RANK_POLICY": structured.get("ranking_policy_version")
        == "yobi-hybrid-rank-v2",
        "FEATURE_COUNT": int(structured.get("feature_count") or 0) > 0,
        "FEATURE_MANIFEST": bool(
            re.fullmatch(
                r"[0-9a-f]{64}", str(structured.get("feature_manifest_sha256") or "")
            )
        ),
        "STRUCTURED_READY": structured.get("ready") is True,
    }
    return [f"{name}_INVALID" for name, passed in checks.items() if not passed]


def run_postdeploy(
    base_url: str,
    repository: Any,
    *,
    run_id: str,
    cases: list[LiveCase] | None = None,
    gate: str = "recommendation-v2-postdeploy-five",
    run_id_prefix: str = "postdeploy",
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    preflight_errors: list[str] = []
    release: dict[str, Any] = {}
    cases = list(cases or _case_definitions())
    expected_case_count = len(cases)
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30) as client:
        response = client.get("/readyz")
        if response.status_code != 200:
            preflight_errors.append(f"READY_HTTP_{response.status_code}")
            ready: dict[str, Any] = {}
        else:
            ready = response.json()
            preflight_errors.extend(_ready_errors(ready))
            application_release = ready.get("release", {})
            application_release = (
                application_release if isinstance(application_release, dict) else {}
            )
            release_id = str(application_release.get("release_id") or "")
            if application_release.get("managed") is not True or run_id != (
                f"{run_id_prefix}-{release_id}"
            ):
                preflight_errors.append("RUN_ID_RELEASE_BINDING_INVALID")
            release = {
                "application": application_release,
                "database": {
                    key: ready.get("database", {}).get(key)
                    for key in (
                        "active_release_id",
                        "recommendation_release_family_id",
                        "ranking_policy_version",
                        "feature_manifest_sha256",
                    )
                },
            }

    contexts: list[tuple[LiveCase, Any, str]] = []
    with ExitStack() as stack:
        if not preflight_errors:
            for index, case in enumerate(cases, start=1):
                try:
                    context = stack.enter_context(
                        _prepared_http_context(
                            base_url,
                            case.scenario,
                            language=case.language,
                        )
                    )
                    preview_response = context.client.post(
                        f"/api/v1/sessions/{context.session_id}/structured-recommendations/preview",
                        json=case.scenario.criteria.model_dump(mode="json"),
                    )
                    if preview_response.status_code != 200:
                        raise RuntimeError("PREFLIGHT_PREVIEW_HTTP_INVALID")
                    preview = preview_response.json()
                    if int(preview.get("eligible_menu_count") or 0) < 15:
                        raise RuntimeError("PREFLIGHT_SHORTLIST_POOL_TOO_SMALL")
                    request_id = f"v2live-{index}-{hashlib.sha256(case.name.encode()).hexdigest()[:16]}"
                    contexts.append((case, context, request_id))
                except Exception as exc:  # noqa: BLE001 - no provider dispatch yet
                    preflight_errors.append(f"{case.name}:{type(exc).__name__.upper()}")
                    break

        if not preflight_errors and len(contexts) == expected_case_count:
            for case_index, (case, context, request_id) in enumerate(contexts):
                if case_index:
                    sleep(POSTDEPLOY_INTERVAL_SECONDS)
                started = perf_counter()
                batch: dict[str, Any] = {}
                transport_error: str | None = None
                try:
                    response = context.client.post(
                        f"/api/v1/sessions/{context.session_id}/recommendations",
                        json={
                            "request_id": request_id,
                            "expected_state_version": context.state_version,
                            "criteria_version": context.criteria_version,
                            "mode": "INITIAL",
                        },
                    )
                    batch = await_recommendation_response(
                        context.client,
                        session_id=context.session_id,
                        initial_response=response,
                        error_prefix="V2_LIVE",
                    )
                except Exception as exc:  # noqa: BLE001 - never redispatch
                    transport_error = type(exc).__name__.upper()
                latency_ms = round((perf_counter() - started) * 1_000, 3)
                record = repository.get_recommendation_request(
                    context.session_id,
                    request_id,
                )
                errors = []
                evidence: dict[str, Any] = {
                    "result_count": 0,
                    "merchant_count": 0,
                    "evidence_count": 0,
                    "required_group_count": len(
                        case.scenario.criteria.subjective_groups()
                    ),
                    "matched_group_count_min": 0,
                    "menu_order_sha256": None,
                }
                if transport_error:
                    errors.append(f"TRANSPORT_{transport_error}")
                if batch:
                    batch_errors, evidence = _validate_batch(
                        batch,
                        case.scenario,
                        language=case.language,
                    )
                    errors.extend(batch_errors)
                else:
                    errors.append("RESPONSE_BODY_MISSING")
                errors.extend(_record_errors(record, case.scenario.criteria))
                provider_metrics = (
                    record.ranking_trace_json.get("provider_metrics", {})
                    if record
                    else {}
                )
                provider_metrics = (
                    provider_metrics if isinstance(provider_metrics, dict) else {}
                )
                results.append(
                    {
                        "name": case.name,
                        "language": "ko" if case.language == "한국어" else "en",
                        "status": "PASS" if not errors else "FAIL",
                        "latency_ms": latency_ms,
                        "error_codes": sorted(set(errors)),
                        "dispatch_count": record.dispatch_count if record else 0,
                        "ledger_status": record.status.value if record else None,
                        "selection_status": (
                            record.ranking_trace_json.get("selection_status")
                            if record
                            else None
                        ),
                        "fallback_reason": record.failure_code if record else None,
                        "grounding_rejection_code": (
                            record.ranking_trace_json.get("grounding_rejection_code")
                            if record
                            else None
                        ),
                        "grounding_rejection_stage": (
                            record.ranking_trace_json.get("grounding_rejection_stage")
                            if record
                            else None
                        ),
                        "grounding_rejection_detail": (
                            record.ranking_trace_json.get("grounding_rejection_detail")
                            if record
                            else None
                        ),
                        "provider_metrics": provider_metrics,
                        "shortlist_count": len(record.evidence_pool_json)
                        if record
                        else 0,
                        "release_family_id": record.release_family_id
                        if record
                        else None,
                        "feature_manifest_sha256": (
                            record.feature_manifest_sha256 if record else None
                        ),
                        **evidence,
                    }
                )

    provider_call_count = sum(int(item["dispatch_count"]) for item in results)
    measured_usage = [
        item["provider_metrics"]
        for item in results
        if isinstance(item.get("provider_metrics"), dict)
        and isinstance(item["provider_metrics"].get("total_tokens"), int)
    ]
    latencies = [float(item["latency_ms"]) for item in results]
    latency_summary = {
        "median_ms": round(median(latencies), 3) if latencies else None,
        "max_ms": round(max(latencies), 3) if latencies else None,
        "percentile_claim": "not_made_for_five_samples",
        "median_target_ms": 8_000,
        "max_target_ms": 10_000,
    }
    passed = (
        not preflight_errors
        and len(results) == expected_case_count
        and provider_call_count == expected_case_count
        and all(item["status"] == "PASS" for item in results)
        and float(latency_summary["median_ms"] or 1e12) <= 8_000
        and float(latency_summary["max_ms"] or 1e12) <= 10_000
    )
    return {
        "schema_version": "1",
        "gate": gate,
        "status": "PASS" if passed else "FAIL",
        "requested": expected_case_count,
        "executed": len(results),
        "provider_call_count": provider_call_count,
        "provider_retry_count": 0,
        "dispatch_interval_seconds": POSTDEPLOY_INTERVAL_SECONDS,
        "token_usage": {
            "measured_case_count": len(measured_usage),
            "input_tokens": sum(
                int(item.get("input_tokens") or 0) for item in measured_usage
            ),
            "output_tokens": sum(
                int(item.get("output_tokens") or 0) for item in measured_usage
            ),
            "total_tokens": sum(
                int(item.get("total_tokens") or 0) for item in measured_usage
            ),
        },
        "preflight_error_codes": sorted(set(preflight_errors)),
        "latency": latency_summary,
        "release": release,
        "cases": results,
        "failure_action": (
            "FINALIZE_ZERO_CALL"
            if passed and gate == "recommendation-v2-postdeploy-five"
            else "DIAGNOSTIC_COMPLETE_NO_RELEASE_STATE_CHANGE"
            if passed
            else "KEEP_ACTIVE_PROVISIONAL_NO_AUTO_ROLLBACK"
        ),
        "manual_rollback_command": "sudo -n /opt/yobi/current/deploy/rollback.sh",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("predeploy", "postdeploy", "diagnostic-four"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/opt/yobi/shared/evidence/recommendation-v2"),
    )
    parser.add_argument("--release-family-id")
    parser.add_argument("--base-url", default="http://127.0.0.1")
    args = parser.parse_args()
    if args.mode == "predeploy" and not args.release_family_id:
        parser.error("predeploy requires --release-family-id")
    if args.mode == "predeploy":
        assert args.release_family_id is not None
        allowed_run_ids = _allowed_predeploy_run_ids(
            args.output_dir,
            args.release_family_id,
        )
        if args.run_id not in allowed_run_ids:
            parser.error("predeploy --run-id is not valid for the immutable run ledger")
    final_path = args.output_dir / f"{args.mode}-{args.run_id}.json"
    try:
        _start_path, final_path = _reserve_run(args.output_dir, args.mode, args.run_id)
    except FileExistsError:
        if args.mode == "predeploy" and args.release_family_id is not None:
            reused_digest = _reuse_completed_predeploy(
                final_path,
                release_family_id=args.release_family_id,
            )
            if reused_digest is not None:
                print(
                    json.dumps(
                        {
                            "status": "PASS",
                            "artifact": str(final_path),
                            "artifact_sha256": reused_digest,
                            "provider_call_count": 0,
                            "reused_completed_provider_call_count": 1,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                return
        raise
    if args.mode == "predeploy":
        assert args.release_family_id is not None
        payload = run_predeploy(args.release_family_id, get_settings())
    elif args.mode == "postdeploy":
        payload = run_postdeploy(args.base_url, get_repository(), run_id=args.run_id)
    else:
        payload = run_postdeploy(
            args.base_url,
            get_repository(),
            run_id=args.run_id,
            cases=_case_definitions()[:DIAGNOSTIC_FOUR_CASE_COUNT],
            gate="recommendation-v2-diagnostic-four",
            run_id_prefix="diagnostic-four",
        )
    payload.update({"run_id": args.run_id, "completed_at": _utc_now()})
    digest = _write_artifact(final_path, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "artifact": str(final_path),
                "artifact_sha256": digest,
                "provider_call_count": payload["provider_call_count"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    raise SystemExit(0 if payload["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
