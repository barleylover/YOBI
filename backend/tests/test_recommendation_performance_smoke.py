from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_recommendation_performance_smoke",
    ROOT / "scripts" / "recommendation_performance_smoke.py",
)
assert SPEC and SPEC.loader
performance_smoke = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = performance_smoke
SPEC.loader.exec_module(performance_smoke)


def _sufficient(p95_ms: float) -> dict[str, object]:
    return {"sample_sufficiency": "sufficient", "p95_ms": p95_ms}


def test_reduced_sample_never_emits_a_percentile_claim() -> None:
    summary = performance_smoke._summary(
        [12.5],
        required=100,
        percentile=("p95", 0.95),
    )

    assert summary == {
        "count": 1,
        "median_ms": 12.5,
        "max_ms": 12.5,
        "sample_sufficiency": "insufficient",
        "percentile_claim": "not_made_insufficient_sample",
    }


def test_repository_gates_keep_aggregate_and_fail_a_slow_scenario() -> None:
    result = {
        "preview_wall": _sufficient(450.0),
        "retrieval_support_rank_evidence": _sufficient(1_900.0),
        "no_match": _sufficient(20.0),
        "scenarios": {
            "single_category": {
                "preview_wall": _sufficient(80.0),
                "retrieval_support_rank_evidence": _sufficient(400.0),
            },
            "price_only": {
                "preview_wall": _sufficient(650.0),
                "retrieval_support_rank_evidence": _sufficient(1_500.0),
            },
        },
    }

    gates = {
        gate["name"]: gate for gate in performance_smoke._repository_gates(result)
    }

    assert gates["warm_preview_p95"]["status"] == "PASS"
    assert gates["warm_price_only_preview_p95"] == {
        "name": "warm_price_only_preview_p95",
        "status": "FAIL",
        "observed_ms": 650.0,
        "limit_ms": 500.0,
    }
    assert gates["warm_single_category_retrieval_p95"]["status"] == "PASS"


def _scenarios() -> dict[str, Any]:
    criteria = performance_smoke._criteria_for({})
    scenario = performance_smoke.Scenario("test", criteria)
    return {
        "single": scenario,
        "multi": scenario,
        "price": scenario,
        "no_match": scenario,
    }


def _valid_outcome(name: str = "single_en", latency_ms: float = 10.0) -> dict[str, Any]:
    return {
        "name": name,
        "dispatch_attempted": True,
        "response_received": True,
        "valid_recommended": True,
        "status": "RECOMMENDED",
        "failure_code": None,
        "rank_valid": True,
        "error_codes": [],
        "latency_ms": latency_ms,
        "result_count": 3,
        "merchant_count": 3,
        "evidence_chunk_count": 9,
    }


def _fallback_outcome(name: str = "single_en") -> dict[str, Any]:
    return {
        **_valid_outcome(name),
        "valid_recommended": False,
        "status": "SEARCH_FALLBACK",
        "failure_code": "PROVIDER_TIMEOUT",
        "error_codes": [
            "STATUS_SEARCH_FALLBACK",
            "FAILURE_PROVIDER_TIMEOUT",
        ],
    }


def test_full_schedule_dispatches_exactly_requested_and_reuses_similar_session(
    monkeypatch: Any,
) -> None:
    prepared_contexts: list[object] = []
    dispatched: list[tuple[object, str, str]] = []

    @contextmanager
    def fake_prepared_context(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        context = object()
        prepared_contexts.append(context)
        yield context

    def fake_dispatch(
        context: object,
        spec: Any,
        *,
        before_dispatch: Any = None,
        barrier: Any = None,
        timer: Any = None,
    ) -> dict[str, Any]:
        del barrier, timer
        if before_dispatch is not None:
            before_dispatch()
        dispatched.append((context, spec.name, spec.mode.value))
        return _valid_outcome(spec.name)

    monkeypatch.setattr(
        performance_smoke,
        "_prepared_http_context",
        fake_prepared_context,
    )
    monkeypatch.setattr(
        performance_smoke,
        "_dispatch_http_recommendation",
        fake_dispatch,
    )

    outcomes = performance_smoke._run_sequential_http_samples(
        "http://example.invalid",
        _scenarios(),
        30,
        spacing_seconds=0.0,
        clock=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )

    assert len(outcomes) == 30
    assert len(dispatched) == 30
    assert len(prepared_contexts) == 25
    assert sum(mode == "INITIAL" for _, _, mode in dispatched) == 25
    assert sum(mode == "SIMILAR" for _, _, mode in dispatched) == 5
    for index, (context, name, mode) in enumerate(dispatched):
        if name == "similar":
            seed_context, seed_name, seed_mode = dispatched[index - 1]
            assert (seed_context, seed_name, seed_mode) == (
                context,
                "similar_seed",
                "INITIAL",
            )
            assert mode == "SIMILAR"


def test_release_pacing_defaults_only_apply_to_release_gate() -> None:
    assert performance_smoke._resolve_provider_pacing(
        release_gate=False,
        configured_spacing=None,
        configured_quiet=None,
    ) == (0.0, 0.0)
    assert performance_smoke._resolve_provider_pacing(
        release_gate=True,
        configured_spacing=None,
        configured_quiet=None,
    ) == (65.0, 65.0)
    assert performance_smoke._resolve_provider_pacing(
        release_gate=True,
        configured_spacing=1.5,
        configured_quiet=2.5,
    ) == (1.5, 2.5)


def test_dispatch_pacing_is_outside_measured_latency() -> None:
    current = [0.0]

    class FakeClient:
        def post(self, path: str, json: dict[str, Any]) -> httpx.Response:
            del path, json
            current[0] += 2.0
            return httpx.Response(
                200,
                json={
                    "state_version": 4,
                    "status": "RECOMMENDED",
                    "failure_code": None,
                    "recommendations": [
                        {
                            "rank": 1,
                            "menu": {"merchant_id": "merchant"},
                            "wiki_passages": [{"evidence_id": "evidence"}],
                        }
                    ],
                },
            )

    context = performance_smoke.HTTPRecommendationContext(
        client=FakeClient(),
        profile_id="profile",
        session_id="session",
        criteria_version=1,
        state_version=3,
    )
    spec = performance_smoke.HTTPSampleSpec(
        "single_en",
        _scenarios()["single"],
        "English",
        performance_smoke.RecommendationMode.INITIAL,
    )

    outcome = performance_smoke._dispatch_http_recommendation(
        context,
        spec,
        before_dispatch=lambda: current.__setitem__(0, current[0] + 65.0),
        timer=lambda: current[0],
    )

    assert outcome["valid_recommended"] is True
    assert outcome["latency_ms"] == 2_000.0


def test_async_dispatch_polls_the_same_persisted_request() -> None:
    calls: list[tuple[str, str]] = []
    current = [0.0]

    class FakeClient:
        def post(self, path: str, json: dict[str, Any]) -> httpx.Response:
            del json
            calls.append(("POST", path))
            current[0] += 0.1
            return httpx.Response(
                202,
                json={
                    "request_id": "request-async",
                    "state_version": 3,
                    "status": "PENDING",
                    "recommendations": [],
                },
            )

        def get(self, path: str) -> httpx.Response:
            calls.append(("GET", path))
            current[0] += 1.4
            return httpx.Response(
                200,
                json={
                    "request_id": "request-async",
                    "state_version": 4,
                    "status": "RECOMMENDED",
                    "failure_code": None,
                    "recommendations": [
                        {
                            "rank": 1,
                            "menu": {"merchant_id": "merchant"},
                            "wiki_passages": [{"evidence_id": "evidence"}],
                        }
                    ],
                },
            )

    context = performance_smoke.HTTPRecommendationContext(
        client=FakeClient(),
        profile_id="profile",
        session_id="session",
        criteria_version=1,
        state_version=3,
    )
    spec = performance_smoke.HTTPSampleSpec(
        "single_en",
        _scenarios()["single"],
        "English",
        performance_smoke.RecommendationMode.INITIAL,
    )

    outcome = performance_smoke._dispatch_http_recommendation(
        context,
        spec,
        timer=lambda: current[0],
        deadline_clock=lambda: current[0],
        poll_sleeper=lambda _seconds: None,
    )

    assert outcome["valid_recommended"] is True
    assert outcome["latency_ms"] == 1_500.0
    assert calls == [
        ("POST", "/api/v1/sessions/session/recommendations"),
        (
            "GET",
            "/api/v1/sessions/session/recommendation-requests/request-async",
        ),
    ]


def test_one_fallback_fails_full_provider_gate_but_retains_29_metrics() -> None:
    outcomes = [_valid_outcome(latency_ms=float(index + 1)) for index in range(29)]
    outcomes.append(_fallback_outcome())

    result = performance_smoke._summarize_sequential_outcomes(
        outcomes,
        requested=30,
    )
    gate = performance_smoke._full_provider_gate(result["provider_outcomes"])

    assert result["dispatch_latency_all_responses"]["count"] == 30
    assert result["full_explanation"]["count"] == 29
    assert result["full_explanation"]["percentile_claim"] == (
        "not_made_insufficient_sample"
    )
    assert result["provider_outcomes"]["status_counts"] == {
        "RECOMMENDED": 29,
        "SEARCH_FALLBACK": 1,
    }
    assert result["provider_outcomes"]["failure_code_counts"] == {
        "PROVIDER_TIMEOUT": 1
    }
    assert gate["status"] == "FAIL"
    assert gate["observed_valid_recommended"] == 29


def test_concurrent_search_fallback_is_an_error() -> None:
    result = performance_smoke._summarize_concurrent_outcomes(
        [_valid_outcome(), _fallback_outcome(), _valid_outcome()],
        requested=3,
    )
    gate = performance_smoke._concurrency_gate(result)

    assert result["completed"] == 2
    assert result["errors"] == 1
    assert result["error_rate"] == 0.333333
    assert result["status_counts"] == {
        "RECOMMENDED": 2,
        "SEARCH_FALLBACK": 1,
    }
    assert gate["status"] == "FAIL"
