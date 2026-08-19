#!/usr/bin/env python3
"""Measure the structured recommendation release gates without exposing row IDs.

Repository measurements call the read-only preview and ranked evidence methods
directly.  The process-cold label means a new Python process; it deliberately does
not claim that an Oracle or OS cache was flushed.  Full explanation measurements
use the normal HTTP recommendation API so the configured OCI provider remains in
the path.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations, product
from pathlib import Path
from statistics import median
from threading import Barrier
from time import monotonic, perf_counter, sleep
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"
for path in (BACKEND, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.db.repository import YobiRepository
from app.dependencies import get_repository
from app.domain.models import Profile, ProfileCreate
from app.domain.structured_recommendation import (
    RecommendationCriteriaV2,
    RecommendationMode,
)
from app.services.structured_recommendation import StructuredRecommendationService
from recommendation_http import await_recommendation_response

WARM_REQUIRED = 100
COLD_REQUIRED = 20
FULL_REQUIRED = 30
CONCURRENCY_REQUIRED = 3
PREVIEW_P95_LIMIT_MS = 500.0
RETRIEVAL_P95_LIMIT_MS = 2_000.0
COLD_P95_LIMIT_MS = 3_000.0
NO_MATCH_P95_LIMIT_MS = 2_000.0
FULL_P90_LIMIT_MS = 8_000.0
FULL_MAX_LIMIT_MS = 15_000.0
RELEASE_DISPATCH_SPACING_SECONDS = 65.0
RELEASE_PROVIDER_QUIET_SECONDS = 65.0
RECOMMENDATION_POLL_INTERVAL_SECONDS = 0.5
RECOMMENDATION_RESULT_TIMEOUT_SECONDS = 180.0


@dataclass
class RepositoryContext:
    profile: Profile
    session_id: str


@dataclass(frozen=True)
class Scenario:
    name: str
    criteria: RecommendationCriteriaV2


@dataclass
class HTTPRecommendationContext:
    client: httpx.Client
    profile_id: str
    session_id: str
    criteria_version: int
    state_version: int


@dataclass(frozen=True)
class HTTPSampleSpec:
    name: str
    scenario: Scenario
    language: str
    mode: RecommendationMode


@dataclass
class SequentialDispatchPacer:
    spacing_seconds: float
    clock: Callable[[], float] = monotonic
    sleeper: Callable[[float], None] = sleep
    previous_start: float | None = None

    def wait_for_start(self) -> None:
        if self.previous_start is not None:
            remaining = self.spacing_seconds - (self.clock() - self.previous_start)
            if remaining > 0:
                self.sleeper(remaining)
        self.previous_start = self.clock()


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 3)


def _summary(
    values: list[float],
    *,
    required: int,
    percentile: tuple[str, float] | None = None,
) -> dict[str, Any]:
    if not values:
        raise RuntimeError("PERFORMANCE_SAMPLE_EMPTY")
    result: dict[str, Any] = {
        "count": len(values),
        "median_ms": round(median(values), 3),
        "max_ms": round(max(values), 3),
        "sample_sufficiency": "sufficient" if len(values) >= required else "insufficient",
    }
    if percentile is not None and len(values) >= required:
        label, fraction = percentile
        result[f"{label}_ms"] = _percentile(values, fraction)
        result["percentile_claim"] = "valid"
    elif percentile is not None:
        result["percentile_claim"] = "not_made_insufficient_sample"
    return result


def _optional_summary(
    values: list[float],
    *,
    required: int,
    percentile: tuple[str, float] | None = None,
) -> dict[str, Any]:
    if values:
        return _summary(values, required=required, percentile=percentile)
    result: dict[str, Any] = {
        "count": 0,
        "sample_sufficiency": "insufficient",
    }
    if percentile is not None:
        result["percentile_claim"] = "not_made_insufficient_sample"
    return result


def _sanitized_token(value: Any, *, fallback: str) -> str:
    token = str(value or "").upper()
    if (
        token
        and len(token) <= 100
        and all(
            character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for character in token
        )
    ):
        return token
    return fallback


def _sanitized_counts(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _preview_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")
    elif isinstance(value, dict):
        payload = value
    else:
        raise TypeError("PREVIEW_RESPONSE_INVALID")
    required = {
        "eligible_menu_count",
        "eligible_merchant_count",
        "zero_reason_codes",
        "release_id",
        "support_manifest_sha256",
        "ranking_policy_version",
        "timing_ms",
    }
    if not required <= payload.keys():
        raise RuntimeError("PREVIEW_RESPONSE_FIELDS_MISSING")
    return payload


def _preview_signature(payload: dict[str, Any]) -> tuple[Any, ...]:
    return (
        int(payload["eligible_menu_count"]),
        int(payload["eligible_merchant_count"]),
        tuple(payload["zero_reason_codes"]),
        str(payload["release_id"]),
        str(payload["support_manifest_sha256"]),
        str(payload["ranking_policy_version"]),
    )


def _new_repository_context(
    repository: YobiRepository,
    *,
    language: str = "English",
) -> RepositoryContext:
    profile = repository.create_profile(
        ProfileCreate(
            preferred_language=language,
            nationality="South Korea" if language == "한국어" else "United States",
            age_band="Prefer not to say",
            gender="Prefer not to say",
            religion_selection="Prefer not to say",
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=1,
            favorite_foods=[],
            consent_demo_data=True,
            remember_profile=False,
        )
    )
    try:
        session = repository.create_session(profile.profile_id)
        candidates = repository.resolve_address("YOBI Myeongdong Hotel")
        candidates = [item for item in candidates if item.service_area_id]
        if not candidates:
            raise RuntimeError("PERFORMANCE_ADDRESS_CANDIDATE_MISSING")
        repository.save_address(session.session_id, candidates[0], None)
        return RepositoryContext(profile=profile, session_id=session.session_id)
    except Exception:
        repository.delete_profile(profile.profile_id)
        raise


def _delete_repository_context(
    repository: YobiRepository,
    context: RepositoryContext | None,
) -> None:
    if context is not None:
        repository.delete_profile(context.profile.profile_id)


def _criteria_for(
    selections: dict[str, list[str]],
    *,
    max_spice_level: int = 5,
    halal: bool = False,
    vegan: bool = False,
) -> RecommendationCriteriaV2:
    fields: dict[str, Any] = {
        "schema_version": "2",
        "cuisine_origins": [],
        "flavors": [],
        "main_ingredients": [],
        "food_forms": [],
        "temperatures": [],
        "price_bands": [],
        "textures": [],
        "cooking_methods": [],
        "dietary_filters": {
            "halal_certified_only": halal,
            "vegan": vegan,
        },
        "max_spice_level": max_spice_level,
        "spice_reference_country": "KR",
    }
    for category, codes in selections.items():
        fields[category] = codes
    return RecommendationCriteriaV2.model_validate(fields)


def _catalog_options(catalog: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for category in catalog.get("categories", []):
        code = str(category.get("code", ""))
        options = [
            str(option.get("code", ""))
            for option in category.get("options", [])
            if option.get("code") and option.get("active", True) is not False
        ]
        if code and options:
            result[code] = options
    return result


def _discover_scenarios(
    repository: YobiRepository,
    session_id: str,
) -> tuple[dict[str, Scenario], dict[str, Any]]:
    catalog = repository.get_preference_catalog("en")
    options = _catalog_options(catalog)
    family = repository.get_active_recommendation_release_family()
    if family is None:
        raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")

    def preview(criteria: RecommendationCriteriaV2) -> dict[str, Any]:
        return _preview_dict(
            repository.preview_recommendation(
                session_id,
                criteria,
                release_family_id=family.release_family_id,
            )
        )

    single: RecommendationCriteriaV2 | None = None
    single_category = ""
    core_categories = [code for code in options if code != "price_bands"]
    for category in core_categories:
        for option in options[category]:
            candidate = _criteria_for({category: [option]})
            if int(preview(candidate)["eligible_menu_count"]) >= 3:
                single = candidate
                single_category = category
                break
        if single is not None:
            break
    if single is None:
        raise RuntimeError("ACTIVE_CORE_SCENARIO_NOT_FOUND")

    price: RecommendationCriteriaV2 | None = None
    for option in options.get("price_bands", []):
        candidate = _criteria_for({"price_bands": [option]})
        if int(preview(candidate)["eligible_menu_count"]) >= 3:
            price = candidate
            break
    if price is None:
        raise RuntimeError("ACTIVE_PRICE_SCENARIO_NOT_FOUND")

    single_payload = single.model_dump(mode="json")
    single_code = single_payload[single_category][0]
    multi: RecommendationCriteriaV2 | None = None
    for category in core_categories:
        if category == single_category:
            continue
        for option in options[category]:
            candidate = _criteria_for(
                {single_category: [single_code], category: [option]}
            )
            if int(preview(candidate)["eligible_menu_count"]) >= 3:
                multi = candidate
                break
        if multi is not None:
            break
    if multi is None:
        for option in options.get("price_bands", []):
            candidate = _criteria_for(
                {single_category: [single_code], "price_bands": [option]}
            )
            if int(preview(candidate)["eligible_menu_count"]) >= 3:
                multi = candidate
                break
    if multi is None:
        raise RuntimeError("ACTIVE_MULTI_AND_SCENARIO_NOT_FOUND")

    no_match: RecommendationCriteriaV2 | None = None
    no_match_candidates = [
        _criteria_for({}, max_spice_level=1, halal=True, vegan=True),
        _criteria_for({}, max_spice_level=1, halal=True),
        _criteria_for({}, max_spice_level=1, vegan=True),
    ]
    category_pairs = list(combinations(core_categories[:6], 2))
    for left, right in category_pairs:
        for left_code, right_code in product(options[left][:4], options[right][:4]):
            no_match_candidates.append(
                _criteria_for(
                    {left: [left_code], right: [right_code]},
                    max_spice_level=1,
                )
            )
    for candidate in no_match_candidates[:200]:
        if int(preview(candidate)["eligible_menu_count"]) == 0:
            no_match = candidate
            break
    if no_match is None:
        raise RuntimeError("ACTIVE_NO_MATCH_SCENARIO_NOT_FOUND")

    scenarios = {
        "single": Scenario("single_category", single),
        "multi": Scenario("multi_category_and", multi),
        "price": Scenario("price_only", price),
        "no_match": Scenario("no_match", no_match),
    }
    metadata = {
        "release_id": family.release_family_id,
        "support_manifest_sha256": family.support_manifest_sha256,
        "feature_manifest_sha256": family.feature_manifest_sha256,
        "ranking_policy_version": family.ranking_policy_version,
        "catalog_version": str(catalog.get("catalog_version", "unknown")),
    }
    return scenarios, metadata


def _ranked_evidence(
    repository: YobiRepository,
    context: RepositoryContext,
    criteria: RecommendationCriteriaV2,
    *,
    mode: RecommendationMode = RecommendationMode.INITIAL,
) -> list[Any]:
    family = repository.get_active_recommendation_release_family()
    if family is None:
        raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
    pool = repository.build_recommendation_evidence_pool(
        context.session_id,
        context.profile,
        criteria,
        mode,
        100,
        release_family_id=family.release_family_id,
        eligibility_as_of=datetime.now(timezone.utc),
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    return StructuredRecommendationService._freeze_server_candidates(pool, limit=15)


def _validate_ranked_evidence(items: list[Any], *, expect_empty: bool) -> None:
    if expect_empty:
        if items:
            raise RuntimeError("NO_MATCH_EVIDENCE_NOT_EMPTY")
        return
    if not items or len(items) > 15:
        raise RuntimeError("RANKED_EVIDENCE_COUNT_INVALID")
    ranks = [getattr(item, "server_rank", None) for item in items]
    if ranks != list(range(1, len(items) + 1)):
        raise RuntimeError("SERVER_RANK_CONTRACT_INVALID")
    for item in items:
        trace = getattr(item, "ranking_trace", None)
        if not isinstance(trace, dict) or not trace:
            raise RuntimeError("RANKING_TRACE_MISSING")


def _evidence_cardinality(
    preview: dict[str, Any],
    items: list[Any],
) -> dict[str, int]:
    evidence_ids = {
        str(reference.evidence_id)
        for item in items
        for reference in getattr(item, "wiki_passages", [])
    }
    merchants = {
        str(item.menu.merchant_id)
        for item in items
        if getattr(getattr(item, "menu", None), "merchant_id", None)
    }
    return {
        "eligible_menu_count": int(preview["eligible_menu_count"]),
        "eligible_merchant_count": int(preview["eligible_merchant_count"]),
        "final_candidate_count": len(items),
        "final_merchant_count": len(merchants),
        "evidence_chunk_count": len(evidence_ids),
    }


def _run_repository_measurements(
    repository: YobiRepository,
    context: RepositoryContext,
    scenarios: dict[str, Scenario],
    warm_samples: int,
) -> dict[str, Any]:
    family = repository.get_active_recommendation_release_family()
    if family is None:
        raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
    positive = [scenarios["single"], scenarios["multi"], scenarios["price"]]
    baselines: dict[str, tuple[Any, ...]] = {}
    scenario_cardinality: dict[str, dict[str, int]] = {}
    for scenario in [*positive, scenarios["no_match"]]:
        payload = _preview_dict(
            repository.preview_recommendation(
                context.session_id,
                scenario.criteria,
                release_family_id=family.release_family_id,
            )
        )
        baselines[scenario.name] = _preview_signature(payload)
        evidence = _ranked_evidence(repository, context, scenario.criteria)
        expect_empty = scenario is scenarios["no_match"]
        _validate_ranked_evidence(evidence, expect_empty=expect_empty)
        scenario_cardinality[scenario.name] = _evidence_cardinality(payload, evidence)

    preview_wall: list[float] = []
    preview_sql: list[float] = []
    retrieval: list[float] = []
    no_match: list[float] = []
    parity_failures = 0
    scenario_measurements: dict[str, dict[str, list[float]]] = {
        scenario.name: {
            "preview_wall": [],
            "preview_reported_sql": [],
            "retrieval_support_rank_evidence": [],
        }
        for scenario in positive
    }
    for _sample_index in range(warm_samples):
        for scenario in positive:
            started = perf_counter()
            payload = _preview_dict(
                repository.preview_recommendation(
                    context.session_id,
                    scenario.criteria,
                    release_family_id=family.release_family_id,
                )
            )
            preview_elapsed = _elapsed_ms(started)
            preview_reported = float(payload["timing_ms"])
            preview_wall.append(preview_elapsed)
            preview_sql.append(preview_reported)
            scenario_measurements[scenario.name]["preview_wall"].append(
                preview_elapsed
            )
            scenario_measurements[scenario.name]["preview_reported_sql"].append(
                preview_reported
            )
            if _preview_signature(payload) != baselines[scenario.name]:
                parity_failures += 1

            started = perf_counter()
            evidence = _ranked_evidence(repository, context, scenario.criteria)
            retrieval_elapsed = _elapsed_ms(started)
            retrieval.append(retrieval_elapsed)
            scenario_measurements[scenario.name][
                "retrieval_support_rank_evidence"
            ].append(retrieval_elapsed)
            _validate_ranked_evidence(evidence, expect_empty=False)

        started = perf_counter()
        empty = _ranked_evidence(
            repository,
            context,
            scenarios["no_match"].criteria,
        )
        no_match.append(_elapsed_ms(started))
        _validate_ranked_evidence(empty, expect_empty=True)
    if parity_failures:
        raise RuntimeError("PREVIEW_COUNT_PARITY_FAILED")
    return {
        "cache_condition": "same-process-warm",
        "preview_wall": _summary(
            preview_wall,
            required=WARM_REQUIRED,
            percentile=("p95", 0.95),
        ),
        "preview_reported_sql": _summary(
            preview_sql,
            required=WARM_REQUIRED,
            percentile=("p95", 0.95),
        ),
        "retrieval_support_rank_evidence": _summary(
            retrieval,
            required=WARM_REQUIRED,
            percentile=("p95", 0.95),
        ),
        "no_match": _summary(
            no_match,
            required=WARM_REQUIRED,
            percentile=("p95", 0.95),
        ),
        "preview_count_parity_failures": parity_failures,
        "scenarios": {
            name: {
                "preview_wall": _summary(
                    values["preview_wall"],
                    required=WARM_REQUIRED,
                    percentile=("p95", 0.95),
                ),
                "preview_reported_sql": _summary(
                    values["preview_reported_sql"],
                    required=WARM_REQUIRED,
                    percentile=("p95", 0.95),
                ),
                "retrieval_support_rank_evidence": _summary(
                    values["retrieval_support_rank_evidence"],
                    required=WARM_REQUIRED,
                    percentile=("p95", 0.95),
                ),
                "cardinality": scenario_cardinality[name],
            }
            for name, values in sorted(scenario_measurements.items())
        },
        "scenario_cardinality": scenario_cardinality,
    }


def _encode_criteria(criteria: RecommendationCriteriaV2) -> str:
    raw = criteria.model_dump_json().encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_criteria(value: str) -> RecommendationCriteriaV2:
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        return RecommendationCriteriaV2.model_validate_json(raw)
    except Exception as exc:
        raise RuntimeError("COLD_CHILD_CRITERIA_INVALID") from exc


def _run_cold_child(criteria: RecommendationCriteriaV2) -> dict[str, Any]:
    repository = get_repository()
    context: RepositoryContext | None = None
    try:
        context = _new_repository_context(repository)
        family = repository.get_active_recommendation_release_family()
        if family is None:
            raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
        started = perf_counter()
        preview = _preview_dict(
            repository.preview_recommendation(
                context.session_id,
                criteria,
                release_family_id=family.release_family_id,
            )
        )
        preview_ms = _elapsed_ms(started)
        if int(preview["eligible_menu_count"]) < 1:
            raise RuntimeError("COLD_CHILD_SCENARIO_EMPTY")
        started = perf_counter()
        evidence = _ranked_evidence(repository, context, criteria)
        retrieval_ms = _elapsed_ms(started)
        _validate_ranked_evidence(evidence, expect_empty=False)
        return {"preview_ms": preview_ms, "retrieval_ms": retrieval_ms}
    finally:
        _delete_repository_context(repository, context)


def _run_process_cold(
    scenarios: dict[str, Scenario],
    cold_samples: int,
) -> dict[str, Any]:
    positive = [scenarios["single"], scenarios["multi"], scenarios["price"]]
    preview: list[float] = []
    retrieval: list[float] = []
    per_scenario: dict[str, dict[str, list[float]]] = {
        scenario.name: {"preview": [], "retrieval_support_rank_evidence": []}
        for scenario in positive
    }
    for index in range(cold_samples):
        scenario = positive[index % len(positive)]
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--cold-child",
            _encode_criteria(scenario.criteria),
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("PROCESS_COLD_CHILD_FAILED")
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        try:
            payload = json.loads(lines[-1])
            preview_elapsed = float(payload["preview_ms"])
            retrieval_elapsed = float(payload["retrieval_ms"])
            preview.append(preview_elapsed)
            retrieval.append(retrieval_elapsed)
            per_scenario[scenario.name]["preview"].append(preview_elapsed)
            per_scenario[scenario.name]["retrieval_support_rank_evidence"].append(
                retrieval_elapsed
            )
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("PROCESS_COLD_CHILD_OUTPUT_INVALID") from exc
    return {
        "cache_condition": "process-cold/db-cache-unspecified",
        "preview": _summary(
            preview,
            required=COLD_REQUIRED,
            percentile=("p95", 0.95),
        ),
        "retrieval_support_rank_evidence": _summary(
            retrieval,
            required=COLD_REQUIRED,
            percentile=("p95", 0.95),
        ),
        "scenarios": {
            name: {
                "preview": _summary(
                    values["preview"],
                    required=COLD_REQUIRED,
                    percentile=("p95", 0.95),
                ),
                "retrieval_support_rank_evidence": _summary(
                    values["retrieval_support_rank_evidence"],
                    required=COLD_REQUIRED,
                    percentile=("p95", 0.95),
                ),
            }
            for name, values in sorted(per_scenario.items())
            if values["preview"]
        },
    }


def _require_http(response: httpx.Response, expected: int = 200) -> dict[str, Any]:
    if response.status_code != expected:
        raise RuntimeError(f"PERFORMANCE_HTTP_{response.status_code}")
    payload = response.json() if response.content else {}
    if not isinstance(payload, dict):
        raise TypeError("PERFORMANCE_HTTP_RESPONSE_INVALID")
    return payload


def _http_setup(
    client: httpx.Client,
    *,
    language: str,
) -> tuple[str, str, dict[str, Any], int]:
    profile = _require_http(
        client.post(
            "/api/v1/profiles",
            json={
                "preferred_language": language,
                "nationality": "South Korea" if language == "한국어" else "United States",
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
    try:
        session = _require_http(
            client.post("/api/v1/sessions", json={"profile_id": profile_id}),
            201,
        )
        session_id = str(session["session_id"])
        resolved = _require_http(
            client.post(
                f"/api/v1/sessions/{session_id}/address/resolve",
                json={"text": "YOBI Myeongdong Hotel"},
            )
        )
        candidates = resolved.get("candidates", [])
        if not candidates:
            raise RuntimeError("PERFORMANCE_ADDRESS_CANDIDATE_MISSING")
        _require_http(
            client.post(
                f"/api/v1/sessions/{session_id}/address/confirm",
                json={"candidate_token": candidates[0]["candidate_token"]},
            )
        )
        locale = "ko" if language == "한국어" else "en"
        catalog = _require_http(
            client.get(f"/api/v1/recommendation/preferences/catalog?locale={locale}")
        )
        current = _require_http(client.get(f"/api/v1/sessions/{session_id}"))
        return profile_id, session_id, catalog, int(current["state_version"])
    except Exception:
        client.delete(f"/api/v1/profiles/{profile_id}")
        raise


@contextmanager
def _prepared_http_context(
    base_url: str,
    scenario: Scenario,
    *,
    language: str,
) -> Iterator[HTTPRecommendationContext]:
    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=180)
    profile_id = ""
    try:
        profile_id, session_id, catalog, state_version = _http_setup(
            client,
            language=language,
        )
        commit = _require_http(
            client.put(
                f"/api/v1/sessions/{session_id}/recommendation-criteria",
                json={
                    "criteria": scenario.criteria.model_dump(mode="json"),
                    "catalog_version": catalog["catalog_version"],
                    "expected_state_version": state_version,
                    "request_id": f"perf-criteria-{uuid4().hex}",
                },
            )
        )
        yield HTTPRecommendationContext(
            client=client,
            profile_id=profile_id,
            session_id=session_id,
            criteria_version=int(commit["criteria_version"]),
            state_version=int(commit["state_version"]),
        )
    finally:
        active_exception = sys.exc_info()[0] is not None
        try:
            if profile_id:
                response = client.delete(f"/api/v1/profiles/{profile_id}")
                if response.status_code not in {204, 404} and not active_exception:
                    raise RuntimeError("PERFORMANCE_PROFILE_CLEANUP_FAILED")
        finally:
            client.close()


def _failed_http_outcome(
    name: str,
    error_code: str,
    *,
    dispatch_attempted: bool,
    latency_ms: float | None = None,
    response_received: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "dispatch_attempted": dispatch_attempted,
        "response_received": response_received,
        "valid_recommended": False,
        "status": "NO_RESPONSE" if not response_received else "HTTP_ERROR",
        "failure_code": None,
        "rank_valid": False,
        "error_codes": [_sanitized_token(error_code, fallback="UNSAFE_ERROR")],
        "latency_ms": latency_ms,
        "result_count": 0,
        "merchant_count": 0,
        "evidence_chunk_count": 0,
    }


def _dispatch_http_recommendation(
    context: HTTPRecommendationContext,
    spec: HTTPSampleSpec,
    *,
    before_dispatch: Callable[[], None] | None = None,
    barrier: Barrier | None = None,
    timer: Callable[[], float] = perf_counter,
    deadline_clock: Callable[[], float] = monotonic,
    poll_sleeper: Callable[[float], None] = sleep,
) -> dict[str, Any]:
    try:
        if barrier is not None:
            barrier.wait(timeout=30)
        if before_dispatch is not None:
            before_dispatch()
    except Exception as exc:  # noqa: BLE001 - sanitized aggregate output only
        return _failed_http_outcome(
            spec.name,
            _safe_error_code(exc),
            dispatch_attempted=False,
        )

    started = timer()
    try:
        response = context.client.post(
            f"/api/v1/sessions/{context.session_id}/recommendations",
            json={
                "request_id": f"perf-recommend-{uuid4().hex}",
                "expected_state_version": context.state_version,
                "criteria_version": context.criteria_version,
                "mode": spec.mode.value,
            },
        )
    except Exception as exc:  # noqa: BLE001 - sanitized aggregate output only
        return _failed_http_outcome(
            spec.name,
            _safe_error_code(exc),
            dispatch_attempted=True,
            latency_ms=round((timer() - started) * 1_000, 3),
        )
    latency_ms = round((timer() - started) * 1_000, 3)
    try:
        batch = await_recommendation_response(
            context.client,
            session_id=context.session_id,
            initial_response=response,
            timeout_seconds=RECOMMENDATION_RESULT_TIMEOUT_SECONDS,
            poll_interval_seconds=RECOMMENDATION_POLL_INTERVAL_SECONDS,
            clock=deadline_clock,
            sleeper=poll_sleeper,
            error_prefix="PERFORMANCE",
        )
        latency_ms = round((timer() - started) * 1_000, 3)
    except Exception as exc:  # noqa: BLE001 - sanitized aggregate output only
        return _failed_http_outcome(
            spec.name,
            _safe_error_code(exc),
            dispatch_attempted=True,
            response_received=True,
            latency_ms=latency_ms,
        )

    try:
        context.state_version = int(batch["state_version"])
    except (KeyError, TypeError, ValueError):
        pass
    status = _sanitized_token(batch.get("status"), fallback="UNKNOWN_STATUS")
    raw_failure_code = batch.get("failure_code")
    failure_code = (
        _sanitized_token(raw_failure_code, fallback="UNSAFE_FAILURE_CODE")
        if raw_failure_code is not None
        else None
    )
    raw_recommendations = batch.get("recommendations")
    recommendations = (
        raw_recommendations if isinstance(raw_recommendations, list) else []
    )
    ranks = [item.get("rank") for item in recommendations if isinstance(item, dict)]
    rank_valid = (
        len(ranks) == len(recommendations)
        and 1 <= len(recommendations) <= 3
        and ranks == list(range(1, len(recommendations) + 1))
    )
    error_codes: list[str] = []
    if status != "RECOMMENDED":
        error_codes.append(f"STATUS_{status}")
    if failure_code is not None:
        error_codes.append(f"FAILURE_{failure_code}")
    if not rank_valid:
        error_codes.append("PUBLIC_RANK_INVALID")
    merchant_ids = {
        str(item.get("menu", {}).get("merchant_id"))
        for item in recommendations
        if isinstance(item, dict)
        and isinstance(item.get("menu"), dict)
        and item["menu"].get("merchant_id")
    }
    evidence_ids = {
        str(passage.get("evidence_id"))
        for item in recommendations
        if isinstance(item, dict)
        for passage in item.get("wiki_passages", [])
        if isinstance(passage, dict) and passage.get("evidence_id")
    }
    return {
        "name": spec.name,
        "dispatch_attempted": True,
        "response_received": True,
        "valid_recommended": not error_codes,
        "status": status,
        "failure_code": failure_code,
        "rank_valid": rank_valid,
        "error_codes": error_codes,
        "latency_ms": latency_ms,
        "result_count": len(recommendations),
        "merchant_count": len(merchant_ids),
        "evidence_chunk_count": len(evidence_ids),
    }


def _sample_groups(
    scenarios: dict[str, Scenario],
    full_samples: int,
) -> list[list[HTTPSampleSpec]]:
    cycle = [
        [
            HTTPSampleSpec(
                "single_en", scenarios["single"], "English", RecommendationMode.INITIAL
            )
        ],
        [
            HTTPSampleSpec(
                "single_ko", scenarios["single"], "한국어", RecommendationMode.INITIAL
            )
        ],
        [
            HTTPSampleSpec(
                "multi_and", scenarios["multi"], "English", RecommendationMode.INITIAL
            )
        ],
        [
            HTTPSampleSpec(
                "price_only", scenarios["price"], "English", RecommendationMode.INITIAL
            )
        ],
        [
            HTTPSampleSpec(
                "similar_seed",
                scenarios["single"],
                "English",
                RecommendationMode.INITIAL,
            ),
            HTTPSampleSpec(
                "similar", scenarios["single"], "English", RecommendationMode.SIMILAR
            ),
        ],
    ]
    groups: list[list[HTTPSampleSpec]] = []
    scheduled = 0
    cycle_index = 0
    while scheduled < full_samples:
        remaining = full_samples - scheduled
        group = cycle[cycle_index % len(cycle)][:remaining]
        groups.append(group)
        scheduled += len(group)
        cycle_index += 1
    return groups


def _run_sequential_http_samples(
    base_url: str,
    scenarios: dict[str, Scenario],
    full_samples: int,
    *,
    spacing_seconds: float,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
) -> list[dict[str, Any]]:
    pacer = SequentialDispatchPacer(spacing_seconds, clock=clock, sleeper=sleeper)
    outcomes: list[dict[str, Any]] = []
    for group in _sample_groups(scenarios, full_samples):
        first = group[0]
        completed_in_group = 0
        try:
            with _prepared_http_context(
                base_url,
                first.scenario,
                language=first.language,
            ) as context:
                for spec in group:
                    outcomes.append(
                        _dispatch_http_recommendation(
                            context,
                            spec,
                            before_dispatch=pacer.wait_for_start,
                        )
                    )
                    completed_in_group += 1
        except Exception as exc:  # noqa: BLE001 - retain sanitized partial results
            error_code = _safe_error_code(exc)
            if completed_in_group == len(group) and outcomes:
                outcomes[-1]["valid_recommended"] = False
                outcomes[-1]["error_codes"].append(error_code)
            for spec in group[completed_in_group:]:
                outcomes.append(
                    _failed_http_outcome(
                        spec.name,
                        error_code,
                        dispatch_attempted=False,
                    )
                )
    return outcomes


def _http_full_sample(
    base_url: str,
    scenario: Scenario,
    *,
    language: str,
    barrier: Barrier | None = None,
) -> dict[str, Any]:
    spec = HTTPSampleSpec(
        "concurrent", scenario, language, RecommendationMode.INITIAL
    )
    try:
        with _prepared_http_context(
            base_url,
            scenario,
            language=language,
        ) as context:
            return _dispatch_http_recommendation(context, spec, barrier=barrier)
    except Exception as exc:  # noqa: BLE001 - retain sanitized concurrent result
        if barrier is not None:
            barrier.abort()
        return _failed_http_outcome(
            spec.name,
            _safe_error_code(exc),
            dispatch_attempted=False,
        )


def _outcome_counts(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    error_codes = [
        str(code)
        for outcome in outcomes
        for code in outcome.get("error_codes", [])
    ]
    return {
        "dispatch_attempted": sum(
            bool(outcome.get("dispatch_attempted")) for outcome in outcomes
        ),
        "responses": sum(bool(outcome.get("response_received")) for outcome in outcomes),
        "valid_recommended": sum(
            bool(outcome.get("valid_recommended")) for outcome in outcomes
        ),
        "status_counts": _sanitized_counts(
            [str(outcome.get("status", "UNKNOWN_STATUS")) for outcome in outcomes]
        ),
        "failure_code_counts": _sanitized_counts(
            [
                str(outcome["failure_code"])
                for outcome in outcomes
                if outcome.get("failure_code") is not None
            ]
        ),
        "error_code_counts": _sanitized_counts(error_codes),
        "rank_invalid": sum(not bool(outcome.get("rank_valid")) for outcome in outcomes),
    }


def _summarize_sequential_outcomes(
    outcomes: list[dict[str, Any]],
    *,
    requested: int,
) -> dict[str, Any]:
    valid = [outcome for outcome in outcomes if outcome.get("valid_recommended")]
    valid_latencies = [float(outcome["latency_ms"]) for outcome in valid]
    returned_latencies = [
        float(outcome["latency_ms"])
        for outcome in outcomes
        if outcome.get("latency_ms") is not None
    ]
    counts = _outcome_counts(outcomes)
    scenarios: dict[str, Any] = {}
    for name in sorted({str(outcome["name"]) for outcome in outcomes}):
        named = [outcome for outcome in outcomes if outcome["name"] == name]
        named_valid = [outcome for outcome in named if outcome.get("valid_recommended")]
        cardinality: dict[str, dict[str, int]] = {}
        for field, output_name in (
            ("result_count", "final_candidate_count"),
            ("merchant_count", "final_merchant_count"),
            ("evidence_chunk_count", "evidence_chunk_count"),
        ):
            values = [int(outcome[field]) for outcome in named_valid]
            if values:
                cardinality[output_name] = {"min": min(values), "max": max(values)}
        scenarios[name] = {
            "requested": len(named),
            "valid_recommended": len(named_valid),
            "status_counts": _outcome_counts(named)["status_counts"],
            "latency": _optional_summary(
                [float(outcome["latency_ms"]) for outcome in named_valid],
                required=FULL_REQUIRED,
            ),
            "cardinality_range": cardinality,
        }
    return {
        "target": "normal-http-provider-path",
        "provider_outcomes": {
            "requested": requested,
            "observed": len(outcomes),
            **counts,
        },
        "dispatch_latency_all_responses": _optional_summary(
            returned_latencies,
            required=FULL_REQUIRED,
            percentile=("p90", 0.90),
        ),
        "full_explanation": _optional_summary(
            valid_latencies,
            required=FULL_REQUIRED,
            percentile=("p90", 0.90),
        ),
        "scenarios": scenarios,
    }


def _summarize_concurrent_outcomes(
    outcomes: list[dict[str, Any]],
    *,
    requested: int,
) -> dict[str, Any]:
    valid = [outcome for outcome in outcomes if outcome.get("valid_recommended")]
    counts = _outcome_counts(outcomes)
    errors = requested - len(valid)
    return {
        "requested": requested,
        "observed": len(outcomes),
        "completed": len(valid),
        "errors": errors,
        "error_rate": round(errors / requested, 6),
        **counts,
        "latency": _optional_summary(
            [float(outcome["latency_ms"]) for outcome in valid],
            required=CONCURRENCY_REQUIRED,
        ),
    }


def _run_full_http(
    base_url: str,
    scenarios: dict[str, Scenario],
    full_samples: int,
    concurrency: int,
    *,
    sequential_spacing_seconds: float = 0.0,
    quiet_period_seconds: float = 0.0,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
) -> dict[str, Any]:
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=30) as client:
        ready = _require_http(client.get("/readyz"))
        if ready.get("status") != "ready":
            raise RuntimeError("PERFORMANCE_TARGET_NOT_READY")

    if quiet_period_seconds > 0:
        sleeper(quiet_period_seconds)
    sequential_outcomes = _run_sequential_http_samples(
        base_url,
        scenarios,
        full_samples,
        spacing_seconds=sequential_spacing_seconds,
        clock=clock,
        sleeper=sleeper,
    )
    result = _summarize_sequential_outcomes(
        sequential_outcomes,
        requested=full_samples,
    )

    if quiet_period_seconds > 0:
        sleeper(quiet_period_seconds)
    barrier = Barrier(concurrency)
    concurrent_outcomes: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _http_full_sample,
                base_url,
                scenarios["single"],
                language="한국어" if index % 2 else "English",
                barrier=barrier,
            )
            for index in range(concurrency)
        ]
        for future in as_completed(futures):
            try:
                concurrent_outcomes.append(future.result())
            except Exception as exc:  # noqa: BLE001 - sanitized aggregate output only
                concurrent_outcomes.append(
                    _failed_http_outcome(
                        "concurrent",
                        _safe_error_code(exc),
                        dispatch_attempted=False,
                    )
                )
    result["concurrency"] = _summarize_concurrent_outcomes(
        concurrent_outcomes,
        requested=concurrency,
    )
    return result


def _gate(
    name: str,
    measurement: dict[str, Any],
    field: str,
    limit_ms: float,
) -> dict[str, Any]:
    if measurement.get("sample_sufficiency") != "sufficient" or field not in measurement:
        return {
            "name": name,
            "status": "INCONCLUSIVE",
            "reason": "INSUFFICIENT_SAMPLE_NO_PERCENTILE_CLAIM",
        }
    observed = float(measurement[field])
    return {
        "name": name,
        "status": "PASS" if observed <= limit_ms else "FAIL",
        "observed_ms": observed,
        "limit_ms": limit_ms,
    }


def _repository_gates(repository_result: dict[str, Any]) -> list[dict[str, Any]]:
    gates = [
        _gate(
            "warm_preview_p95",
            repository_result["preview_wall"],
            "p95_ms",
            PREVIEW_P95_LIMIT_MS,
        ),
        _gate(
            "warm_retrieval_p95",
            repository_result["retrieval_support_rank_evidence"],
            "p95_ms",
            RETRIEVAL_P95_LIMIT_MS,
        ),
        _gate(
            "warm_no_match_p95",
            repository_result["no_match"],
            "p95_ms",
            NO_MATCH_P95_LIMIT_MS,
        ),
    ]
    for name, measurements in sorted(repository_result["scenarios"].items()):
        gates.extend(
            (
                _gate(
                    f"warm_{name}_preview_p95",
                    measurements["preview_wall"],
                    "p95_ms",
                    PREVIEW_P95_LIMIT_MS,
                ),
                _gate(
                    f"warm_{name}_retrieval_p95",
                    measurements["retrieval_support_rank_evidence"],
                    "p95_ms",
                    RETRIEVAL_P95_LIMIT_MS,
                ),
            )
        )
    return gates


def _full_provider_gate(provider_outcomes: dict[str, Any]) -> dict[str, Any]:
    provider_complete = (
        provider_outcomes["observed"] == provider_outcomes["requested"]
        and provider_outcomes["dispatch_attempted"]
        == provider_outcomes["requested"]
        and provider_outcomes["responses"] == provider_outcomes["requested"]
        and provider_outcomes["valid_recommended"]
        == provider_outcomes["requested"]
        and provider_outcomes["status_counts"]
        == {"RECOMMENDED": provider_outcomes["requested"]}
        and not provider_outcomes["failure_code_counts"]
        and provider_outcomes["rank_invalid"] == 0
    )
    if provider_outcomes["requested"] < FULL_REQUIRED and provider_complete:
        status = "INCONCLUSIVE"
    else:
        status = "PASS" if provider_complete else "FAIL"
    return {
        "name": "full_provider_success",
        "status": status,
        "required_valid_recommended": provider_outcomes["requested"],
        "observed_valid_recommended": provider_outcomes["valid_recommended"],
        "error_code_counts": provider_outcomes["error_code_counts"],
    }


def _concurrency_gate(concurrent: dict[str, Any]) -> dict[str, Any]:
    concurrent_complete = (
        concurrent["observed"] == concurrent["requested"]
        and concurrent["dispatch_attempted"] == concurrent["requested"]
        and concurrent["responses"] == concurrent["requested"]
        and concurrent["completed"] == concurrent["requested"]
        and concurrent["errors"] == 0
    )
    if concurrent["requested"] < CONCURRENCY_REQUIRED and concurrent_complete:
        status = "INCONCLUSIVE"
    else:
        status = "PASS" if concurrent_complete else "FAIL"
    return {
        "name": "three_concurrent_error_rate",
        "status": status,
        "observed_error_rate": concurrent["error_rate"],
        "required_concurrency": CONCURRENCY_REQUIRED,
    }


def _evaluate(
    repository_result: dict[str, Any],
    cold_result: dict[str, Any],
    full_result: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = [
        *_repository_gates(repository_result),
        _gate(
            "process_cold_retrieval_p95",
            cold_result["retrieval_support_rank_evidence"],
            "p95_ms",
            COLD_P95_LIMIT_MS,
        ),
        _gate(
            "full_explanation_p90",
            full_result["full_explanation"],
            "p90_ms",
            FULL_P90_LIMIT_MS,
        ),
        _gate(
            "full_explanation_max",
            full_result["full_explanation"],
            "max_ms",
            FULL_MAX_LIMIT_MS,
        ),
    ]
    gates.append(_full_provider_gate(full_result["provider_outcomes"]))
    gates.append(_concurrency_gate(full_result["concurrency"]))
    return gates


def _evaluate_repository_only(
    repository_result: dict[str, Any],
    cold_result: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        *_repository_gates(repository_result),
        _gate(
            "process_cold_retrieval_p95",
            cold_result["retrieval_support_rank_evidence"],
            "p95_ms",
            COLD_P95_LIMIT_MS,
        ),
    ]


def _safe_error_code(exc: Exception) -> str:
    value = str(exc)
    if value and len(value) <= 100 and all(character.isupper() or character.isdigit() or character == "_" for character in value):
        return value
    return type(exc).__name__.upper()


def _resolve_provider_pacing(
    *,
    release_gate: bool,
    configured_spacing: float | None,
    configured_quiet: float | None,
) -> tuple[float, float]:
    spacing = (
        RELEASE_DISPATCH_SPACING_SECONDS
        if configured_spacing is None and release_gate
        else float(configured_spacing or 0.0)
    )
    quiet = (
        RELEASE_PROVIDER_QUIET_SECONDS
        if configured_quiet is None and release_gate
        else float(configured_quiet or 0.0)
    )
    return spacing, quiet


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.release_gate and args.repository_only:
        raise RuntimeError("RELEASE_GATE_REQUIRES_FULL_HTTP")
    if args.release_gate and (
        args.warm_samples < WARM_REQUIRED
        or args.cold_samples < COLD_REQUIRED
        or args.full_samples < FULL_REQUIRED
        or args.concurrency < CONCURRENCY_REQUIRED
    ):
        raise RuntimeError("RELEASE_GATE_SAMPLE_COUNT_TOO_SMALL")
    repository = get_repository()
    context: RepositoryContext | None = None
    configured_spacing = getattr(args, "sequential_dispatch_spacing_seconds", None)
    configured_quiet = getattr(args, "provider_quiet_seconds", None)
    sequential_spacing_seconds, quiet_period_seconds = _resolve_provider_pacing(
        release_gate=args.release_gate,
        configured_spacing=configured_spacing,
        configured_quiet=configured_quiet,
    )
    try:
        context = _new_repository_context(repository)
        scenarios, metadata = _discover_scenarios(repository, context.session_id)
        repository_result = _run_repository_measurements(
            repository,
            context,
            scenarios,
            args.warm_samples,
        )
        cold_result = _run_process_cold(scenarios, args.cold_samples)
        if args.repository_only:
            gates = _evaluate_repository_only(repository_result, cold_result)
            statuses = {gate["status"] for gate in gates}
            status = (
                "FAIL"
                if "FAIL" in statuses
                else "INCONCLUSIVE"
                if "INCONCLUSIVE" in statuses
                else "PASS"
            )
            payload = {
                "status": status,
                "measurement_contract": {
                    "warm": "same-process/per-scenario",
                    "warm_samples_per_scenario": args.warm_samples,
                    "cold": "process-cold/db-cache-unspecified",
                    "full": "not_run_repository_only",
                    "percentile_policy": (
                        "P95 emitted only at documented minimum sample counts"
                    ),
                },
                "release": metadata,
                "repository": repository_result,
                "process_cold": cold_result,
                "gates": gates,
            }
            return payload, 0 if status != "FAIL" else 1
        full_result = _run_full_http(
            args.base_url,
            scenarios,
            args.full_samples,
            args.concurrency,
            sequential_spacing_seconds=sequential_spacing_seconds,
            quiet_period_seconds=quiet_period_seconds,
        )
        gates = _evaluate(repository_result, cold_result, full_result)
        statuses = {gate["status"] for gate in gates}
        status = "FAIL" if "FAIL" in statuses else "INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "PASS"
        payload = {
            "status": status,
            "measurement_contract": {
                "warm": "same-process/per-scenario",
                "warm_samples_per_scenario": args.warm_samples,
                "cold": "process-cold/db-cache-unspecified",
                "full": "normal HTTP recommendation request including configured provider",
                "full_provider_dispatch": {
                    "sequential_requested": args.full_samples,
                    "each_recommendation_post_counted_once": True,
                    "similar_seed_is_timed_counted_sample": True,
                    "similar_reuses_seed_session": True,
                    "sequential_start_spacing_seconds": sequential_spacing_seconds,
                    "quiet_before_sequential_seconds": quiet_period_seconds,
                    "quiet_before_concurrency_seconds": quiet_period_seconds,
                    "pacing_and_quiet_excluded_from_latency": True,
                    "concurrency_requested": args.concurrency,
                    "concurrency_start": "barrier-synchronized",
                },
                "percentile_policy": "P95/P90 emitted only at documented minimum sample counts",
            },
            "release": metadata,
            "repository": repository_result,
            "process_cold": cold_result,
            "http": full_result,
            "gates": gates,
        }
        return payload, 0 if status == "PASS" or (status == "INCONCLUSIVE" and not args.release_gate) else 1
    finally:
        _delete_repository_context(repository, context)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run local repository and OCI-path recommendation performance gates"
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("YOBI_SMOKE_BASE_URL", "http://127.0.0.1"),
    )
    parser.add_argument(
        "--warm-samples",
        type=int,
        default=WARM_REQUIRED,
        help="Same-process samples per positive repository scenario.",
    )
    parser.add_argument("--cold-samples", type=int, default=COLD_REQUIRED)
    parser.add_argument("--full-samples", type=int, default=FULL_REQUIRED)
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY_REQUIRED)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument(
        "--sequential-dispatch-spacing-seconds",
        type=float,
        default=None,
        help=(
            "Minimum spacing between sequential provider-dispatch starts; "
            "defaults to 65 seconds for --release-gate and zero otherwise."
        ),
    )
    parser.add_argument(
        "--provider-quiet-seconds",
        type=float,
        default=None,
        help=(
            "Quiet period before sequential and concurrent provider cohorts; "
            "defaults to 65 seconds for --release-gate and zero otherwise."
        ),
    )
    parser.add_argument(
        "--repository-only",
        action="store_true",
        help="Measure read-only preview/ranking paths without normal HTTP/provider calls.",
    )
    parser.add_argument("--cold-child", help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name in ("warm_samples", "cold_samples", "full_samples", "concurrency"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    for name in (
        "sequential_dispatch_spacing_seconds",
        "provider_quiet_seconds",
    ):
        value = getattr(args, name)
        if value is not None and value < 0:
            parser.error(f"--{name.replace('_', '-')} must be at least 0")
    try:
        if args.cold_child:
            payload = _run_cold_child(_decode_criteria(args.cold_child))
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            return
        payload, exit_code = run(args)
    except Exception as exc:  # noqa: BLE001 - emit one sanitized machine-readable failure
        payload = {"status": "FAIL", "error_code": _safe_error_code(exc)}
        exit_code = 1
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
