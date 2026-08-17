from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.domain.structured_recommendation import RecommendationRequestStatus

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_recommendation_v2_live_harness",
    ROOT / "scripts" / "recommendation_v2_live_harness.py",
)
assert SPEC and SPEC.loader
live_harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live_harness
SPEC.loader.exec_module(live_harness)

POSTDEPLOY_CASES = live_harness.POSTDEPLOY_CASES
_case_definitions = live_harness._case_definitions
_expected_predeploy_run_id = live_harness._expected_predeploy_run_id
_record_errors = live_harness._record_errors
_ready_errors = live_harness._ready_errors
_reserve_run = live_harness._reserve_run
_reuse_completed_predeploy = live_harness._reuse_completed_predeploy
_settings_errors = live_harness._settings_errors
_write_artifact = live_harness._write_artifact


def _record() -> SimpleNamespace:
    evidence_pool = [
        {
            "menu": {"menu_id": f"menu-{index}", "merchant_id": f"merchant-{index}"},
            "criterion_evidence": [
                {
                    "category_code": "flavors",
                    "selected_value_code": "SPICY",
                    "evidence": [{"evidence_id": f"flavor-{index}"}],
                },
                {
                    "category_code": "food_forms",
                    "selected_value_code": "NOODLES",
                    "evidence": [{"evidence_id": f"form-{index}"}],
                },
            ],
        }
        for index in range(15)
    ]
    return SimpleNamespace(
        status=RecommendationRequestStatus.COMPLETED,
        dispatch_count=1,
        evidence_pool_json=evidence_pool,
        final_candidates_json=[
            {
                "rank": index + 1,
                "menu_id": f"menu-{index}",
                "merchant_id": f"merchant-{index}",
            }
            for index in range(3)
        ],
        ranking_trace_json={"selection_status": "GROK_SELECTED"},
        ranking_policy_version="yobi-hybrid-rank-v2",
        support_manifest_sha256="a" * 64,
        feature_manifest_sha256="b" * 64,
    )


def test_live_harness_fixes_the_exact_one_plus_five_cases() -> None:
    cases = _case_definitions()

    assert len(POSTDEPLOY_CASES) == len(cases) == 5
    assert [case.language for case in cases] == [
        "한국어",
        "English",
        "한국어",
        "English",
        "한국어",
    ]
    assert cases[0].scenario.criteria.flavors == ["SPICY"]
    assert cases[0].scenario.criteria.food_forms == ["NOODLES"]
    assert cases[1].scenario.criteria.cooking_methods == ["FRIED"]
    assert cases[2].scenario.criteria.temperatures == ["HOT"]
    assert cases[3].scenario.criteria.price_bands == ["FROM_10000_TO_19999"]
    assert cases[4].scenario.criteria.food_forms == ["DESSERT_BAKERY"]


def test_live_harness_requires_the_frozen_runtime_configuration() -> None:
    assert _settings_errors(Settings()) == []
    assert "CONFIG_RETRY_DISABLED_INVALID" in _settings_errors(
        Settings(llm_max_retries=1)
    )


def test_live_harness_rechecks_ledger_shortlist_and_evidence() -> None:
    criteria = _case_definitions()[0].scenario.criteria
    record = _record()

    assert _record_errors(record, criteria) == []

    record.evidence_pool_json[0]["criterion_evidence"] = []
    record.ranking_trace_json["selection_status"] = "DETERMINISTIC_FALLBACK"
    assert _record_errors(record, criteria) == [
        "FINAL_SELECTED_CATEGORY_EVIDENCE_MISSING",
        "GROK_SELECTION_STATUS_INVALID",
    ]


def test_ready_contract_exposes_only_bounded_structured_metadata() -> None:
    ready = {
        "status": "ready",
        "structured_recommendation": {
            "model_id": "xai.grok-4.3",
            "selection_enabled": True,
            "candidate_limit": 100,
            "shortlist_limit": 15,
            "ranking_policy_version": "yobi-hybrid-rank-v2",
            "feature_count": 62_826,
            "feature_manifest_sha256": "c" * 64,
            "ready": True,
        },
    }

    assert _ready_errors(ready) == []
    ready["structured_recommendation"]["shortlist_limit"] = 14
    assert _ready_errors(ready) == ["SHORTLIST_LIMIT_INVALID"]


def test_live_artifacts_are_immutable_and_sha_bound(tmp_path) -> None:
    _start, final = _reserve_run(tmp_path, "postdeploy", "release-1")
    digest = _write_artifact(final, {"status": "PASS"})

    assert len(digest) == 64
    assert final.with_suffix(".json.sha256").read_text().startswith(digest)
    with pytest.raises(FileExistsError):
        _reserve_run(tmp_path, "postdeploy", "release-1")


def test_completed_predeploy_probe_is_reused_without_another_call(tmp_path) -> None:
    family_id = "family-v2"
    run_id = _expected_predeploy_run_id(family_id)
    _start, final = _reserve_run(tmp_path, "predeploy", run_id)
    digest = _write_artifact(
        final,
        {
            "gate": "recommendation-v2-predeploy-one",
            "status": "PASS",
            "release_family_id": family_id,
            "provider_call_count": 1,
            "provider_retry_count": 0,
            "error_codes": [],
        },
    )

    assert _reuse_completed_predeploy(final, release_family_id=family_id) == digest
    assert _reuse_completed_predeploy(final, release_family_id="other-family") is None


def test_provisional_activation_is_zero_call_after_the_single_staged_probe() -> None:
    source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")
    assert 'YOBI_ZERO_PROVIDER_PROVISIONAL:-false' in source
    zero_branch = source.split('if [[ "$zero_provider_provisional" == "true" ]]; then', 2)[-1]
    zero_branch = zero_branch.split("return 0", 1)[0]
    assert "structured_recommendation_smoke.py" not in zero_branch
    assert "recommendation_quality_smoke.py" not in zero_branch
    assert "activated with zero post-activation provider calls" in zero_branch
    probe = source.index('"$new_release/scripts/recommendation_v2_live_harness.py" predeploy')
    activation = source.index('sudo ln -sfn "$new_release" /opt/yobi/current')
    assert probe < activation
    assert "recommendation-v2-five=pending" in source

    finalizer = (ROOT / "deploy" / "finalize_recommendation_v2_release.sh").read_text(
        encoding="utf-8"
    )
    assert 'payload.get("run_id") == f"postdeploy-{application.get(\'release_id\')}"' in finalizer
    assert '"$EVIDENCE_RELEASE_ID" == "$EXPECTED_RELEASE_ID"' in finalizer
