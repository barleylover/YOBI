from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_release_gate_contract",
    ROOT / "deploy" / "release_gate_contract.py",
)
assert SPEC and SPEC.loader
release_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_gate
SPEC.loader.exec_module(release_gate)


def _pointers(prefix: str):
    return release_gate.ReleasePointers(
        application=f"{prefix}-app",
        knowledge=f"{prefix}-knowledge",
        recommendation=f"{prefix}-recommendation",
    )


def test_stage_verification_failure_keeps_all_three_pointers() -> None:
    initial = _pointers("old")
    outcome = release_gate.simulate_release(
        initial,
        _pointers("new"),
        stage_verified=False,
        completed_gates=(),
    )

    assert outcome.pointers == initial
    assert outcome.ready_marker is False
    assert outcome.restored is False


def test_post_symlink_health_failure_restores_all_three_pointers() -> None:
    initial = _pointers("old")
    outcome = release_gate.simulate_release(
        initial,
        _pointers("new"),
        stage_verified=True,
        completed_gates=(),
        fail_after_symlink=True,
    )

    assert outcome.pointers == initial
    assert outcome.ready_marker is False
    assert outcome.restored is True


def test_omitted_smoke_never_allows_ready_marker_and_restores() -> None:
    initial = _pointers("old")
    outcome = release_gate.simulate_release(
        initial,
        _pointers("new"),
        stage_verified=True,
        completed_gates=("query-plan", "source-integrity", "structured"),
    )

    assert outcome.pointers == initial
    assert outcome.ready_marker is False
    assert outcome.restored is True


def test_exact_external_gate_set_allows_candidate_ready_marker() -> None:
    candidate = _pointers("new")
    outcome = release_gate.simulate_release(
        _pointers("old"),
        candidate,
        stage_verified=True,
        completed_gates=(
            "query-plan",
            "source-integrity",
            "structured",
            "quality-five",
        ),
    )

    assert outcome.pointers == candidate
    assert outcome.ready_marker is True
    assert outcome.restored is False


def test_provisional_gate_defers_only_quality_five() -> None:
    assert release_gate.verify_provisional_external_gates(
        ("query-plan", "source-integrity", "structured")
    ) == ("query-plan", "source-integrity", "structured")

    with pytest.raises(
        release_gate.ReleaseGateError,
        match="PROVISIONAL_RELEASE_GATE_INCOMPLETE",
    ):
        release_gate.verify_provisional_external_gates(
            ("query-plan", "source-integrity")
        )
    with pytest.raises(
        release_gate.ReleaseGateError,
        match="PROVISIONAL_RELEASE_GATE_INCOMPLETE",
    ):
        release_gate.verify_provisional_external_gates(
            ("query-plan", "source-integrity", "structured", "quality-five")
        )


def test_post_review_gate_accepts_only_the_reviewed_zero_call_path() -> None:
    gates = (
        "query-plan",
        "source-integrity",
        "structured",
        "quality-five-reviewed",
    )
    assert release_gate.verify_post_review_external_gates(gates) == tuple(
        sorted(gates)
    )

    with pytest.raises(
        release_gate.ReleaseGateError,
        match="POST_REVIEW_RELEASE_GATE_INCOMPLETE",
    ):
        release_gate.verify_post_review_external_gates(
            ("query-plan", "source-integrity", "structured")
        )


def test_reviewed_quality_five_binds_exact_observation_fix_and_release(
    tmp_path: Path,
) -> None:
    evidence = (
        ROOT
        / "deploy"
        / "evidence"
        / "recommendation_quality_expansion_five_20260817.json"
    )
    result = release_gate.verify_reviewed_quality_five(
        evidence,
        fix_source_path=ROOT
        / "backend"
        / "app"
        / "services"
        / "structured_recommendation.py",
        knowledge_release_id="external-knowledge-0ffd2f53ba2e2539ee9c5a27",
        recommendation_release_family_id=(
            "external-recommendation-0ffd2f53ba2e2539ee9c5a27-71a41f074c-5515c9c687"
        ),
    )

    assert result["executed"] == 5
    assert result["normal_recommended_count"] == 4
    assert result["safe_fallback_count"] == 1
    assert result["additional_provider_dispatch_count_after_review"] == 0

    tampered = json.loads(evidence.read_text(encoding="utf-8"))
    tampered["additional_provider_dispatch_count_after_review"] = 1
    tampered_path = tmp_path / "tampered-quality-five.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        release_gate.ReleaseGateError,
        match="QUALITY_FIVE_REVIEW_COUNTS_INVALID",
    ):
        release_gate.verify_reviewed_quality_five(
            tampered_path,
            fix_source_path=ROOT
            / "backend"
            / "app"
            / "services"
            / "structured_recommendation.py",
            knowledge_release_id="external-knowledge-0ffd2f53ba2e2539ee9c5a27",
            recommendation_release_family_id=(
                "external-recommendation-0ffd2f53ba2e2539ee9c5a27-71a41f074c-5515c9c687"
            ),
        )


@pytest.mark.parametrize(
    "member",
    (
        ".env",
        "backend/.env",
        "keys/private.pem",
        "deploy/wallet/cwallet.sso",
        "tmp/local.db",
        "backend/backend/app.py",
        "backend/tmp/output.txt",
        "frontend/.cache/result",
        "backend/.mypy_cache/3.12/cache.db",
        "backend/.ruff_cache/content",
        "data/demo.sqlite3",
        "data/demo.db-wal",
        "../outside",
        "/absolute/path",
    ),
)
def test_archive_forbidden_member_is_rejected(member: str) -> None:
    with pytest.raises(
        release_gate.ReleaseGateError,
        match="RELEASE_ARCHIVE_FORBIDDEN_MEMBER",
    ):
        release_gate.validate_archive_members(("README.md", member))


def test_archive_allows_runtime_source_and_env_example() -> None:
    assert (
        release_gate.validate_archive_members(
            (
                "README.md",
                ".env.example",
                "backend/app/main.py",
                "database/migrations/012_concept_preference_support_and_server_ranking.sql",
            )
        )
        == 4
    )


def test_deploy_shell_wires_stage_activation_restore_and_exact_gate_helper() -> None:
    source = (ROOT / "deploy" / "deploy.sh").read_text(encoding="utf-8")

    assert source.index("--stage-only") < source.index("--scope staged --verify")
    assert source.index("--scope staged --verify") < source.index(
        'sudo ln -sfn "$new_release" /opt/yobi/current'
    )
    assert source.index('sudo ln -sfn "$new_release" /opt/yobi/current') < source.index(
        "--activate-staged"
    )
    assert source.index("sudo systemctl restart yobi-api nginx") < source.index(
        "|| ! run_release_smokes"
    )
    assert source.index("|| ! run_release_smokes") < source.index(
        '|| ! write_ready_marker "$new_release"'
    )
    smoke_body = source[source.index("run_release_smokes() {") : source.index(
        "if ! sudo systemctl daemon-reload"
    )]
    assert smoke_body.index("--scope active --verify") < smoke_body.index(
        "verify-external"
    )
    assert smoke_body.index("verify-external") < smoke_body.index(
        "structured_recommendation_smoke.py"
    )
    assert smoke_body.index("structured_recommendation_smoke.py") < smoke_body.index(
        "structured_fallback_smoke.py"
    )
    assert smoke_body.index("structured_fallback_smoke.py") < smoke_body.index(
        "recommendation_quality_smoke.py"
    )
    assert smoke_body.index("structured_fallback_smoke.py") < smoke_body.index(
        "completed_release_gates+=(structured)"
    )
    assert "verify-external-gates" in smoke_body
    assert "verify-provisional-external-gates" in smoke_body
    assert "verify-reviewed-quality-five" in smoke_body
    assert "verify-post-review-external-gates" in smoke_body
    assert "--category-code cuisine_origins --option-code ITALIAN" in smoke_body
    assert "final deploy performs zero provider calls" in smoke_body
    assert 'if [[ "$provisional_deploy" == "true" ]]' in smoke_body
    assert "PROVISIONAL: quality-five release gate deferred" in smoke_body
    assert source.index('|| ! run_release_smokes') < source.index(
        'write_provisional_marker "$new_release"'
    ) < source.index('|| ! write_ready_marker "$new_release"')
    restore_body = source[source.index("restore_old_release() {") : source.index(
        "deployment_complete=false"
    )]
    assert restore_body.index("restore_knowledge_release") < restore_body.index(
        'sudo ln -sfn "$old_release" /opt/yobi/current'
    )
    assert restore_body.index("restore_recommendation_release") < restore_body.index(
        'sudo ln -sfn "$old_release" /opt/yobi/current'
    )
    assert "release_gate_contract.py\" validate-archive" in source


def test_structured_gate_covers_dynamic_mock_order_and_isolated_fallback() -> None:
    normal_source = (ROOT / "scripts" / "structured_recommendation_smoke.py").read_text(
        encoding="utf-8"
    )
    fallback_source = (ROOT / "scripts" / "structured_fallback_smoke.py").read_text(
        encoding="utf-8"
    )

    assert "menu_001_01" not in normal_source
    assert 'f"/api/v1/menus/{candidate_menu_id}/options"' in normal_source
    normal_steps = (
        '"event_type": "SELECT_MENU"',
        '"event_type": "UPDATE_OPTIONS"',
        'f"/api/v1/sessions/{session_id}/cart/items"',
        'f"/api/v1/sessions/{session_id}/delivery"',
        'f"/api/v1/sessions/{session_id}/cart/confirm"',
        'f"/api/v1/sessions/{session_id}/checkout"',
        'f"/api/v1/checkout/{checkout_id}/mock-success"',
        'f"/api/v1/orders/{order_id}"',
    )
    offsets = [normal_source.index(step) for step in normal_steps]
    assert offsets == sorted(offsets)
    assert "STRUCTURED_SMOKE_PROFILE_CASCADE_CLEANUP_FAILED" in normal_source
    assert "repository.get_checkout(checkout_id)" in normal_source
    assert "repository.get_order(order_id)" in normal_source

    assert 'isolated_control.set_mode("force_genai_timeout")' in fallback_source
    assert "get_demo_control" not in fallback_source
    assert "record.dispatch_count != 1" in fallback_source
    assert "STRUCTURED_FALLBACK_SERVER_ORDER_CHANGED" in fallback_source
    assert "STRUCTURED_FALLBACK_PAYLOAD_NOT_DETERMINISTIC" in fallback_source
    assert "STRUCTURED_FALLBACK_PROFILE_CASCADE_CLEANUP_FAILED" in fallback_source
