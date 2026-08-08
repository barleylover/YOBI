from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from evaluation.run_chatbot_acceptance import (
    DEFAULT_KNOWLEDGE_PATH,
    DEFAULT_TRANSCRIPTS_PATH,
    load_knowledge_fixture,
    load_transcript_fixture,
    main,
    run_acceptance,
)


def test_golden_transcripts_cover_required_multiturn_acceptance_paths() -> None:
    fixture = load_transcript_fixture()
    coverage = {item for transcript in fixture["transcripts"] for item in transcript["covers"]}

    assert {
        "greeting_no_cards",
        "hold",
        "unknown",
        "no_soup_persistence",
        "no_pork_persistence",
        "correction",
        "readiness",
        "explicit_recommendation",
        "second_menu_snapshot",
        "rejection",
        "selection",
        "budget",
        "spice",
        "unsafe_reassurance",
    }.issubset(coverage)
    assert all(
        step["expect"].get("card_count") == 0
        for transcript in fixture["transcripts"]
        for step in transcript["steps"]
        if step["kind"] == "message" and step["expect"].get("readiness") in {"NOT_READY", "HELD"}
    )


def test_real_chat_service_acceptance_is_passing_and_deterministic() -> None:
    first = run_acceptance()
    second = run_acceptance()

    assert first == second
    assert first["passed"] is True
    assert first["failures"] == []
    assert first["mode"] == "sqlite-real-chat-service-deterministic-fallback"
    assert first["metrics"]["transcript_count"] == 8
    assert first["metrics"]["message_turn_count"] == 15
    assert first["metrics"]["event_count"] == 2
    assert first["metrics"]["knowledge_case_count"] == 3
    assert first["metrics"]["assertion_count"] > 0
    for counter in (
        "failure_count",
        "premature_recommendation_count",
        "hard_constraint_violation_count",
        "state_persistence_failure_count",
        "snapshot_reference_failure_count",
        "conversation_event_failure_count",
        "unsafe_reassurance_count",
        "knowledge_failure_count",
    ):
        assert first["metrics"][counter] == 0


def test_failing_expectation_is_machine_readable_and_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = deepcopy(load_transcript_fixture())
    fixture["transcripts"][0]["steps"][0]["expect"]["card_count"] = 1
    path = tmp_path / "failing-transcripts.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "--transcripts",
                str(path),
                "--knowledge",
                str(DEFAULT_KNOWLEDGE_PATH),
                "--compact",
            ]
        )

    assert raised.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is False
    assert report["metrics"]["failure_count"] == 1
    assert report["failures"][0]["assertion"] == "card_count"
    assert report["failures"][0]["expected"] == 1
    assert report["failures"][0]["actual"] == 0


def test_knowledge_fixture_exposes_phase_3_and_5_contracts() -> None:
    fixture = load_knowledge_fixture()

    assert fixture["boundary"]["catalog_data"] == "SYNTHETIC_DEMO"
    assert fixture["boundary"]["wiki_data"] == "SYNTHETIC_WIKI"
    assert "Unknown" in fixture["boundary"]["safety_rule"]
    for case in fixture["cases"]:
        graph = case["knowledge_graph_expectations"]
        assert graph["enforced_by_this_runner"] is True
        assert graph["concept_id"].startswith("dish_")
        assert graph["expected_retrieval_concepts"]
        assert graph["required_facets"]
        assert graph["required_claims"]
        assert all(
            {"claim_type", "target_id", "status", "scope", "inherited"}.issubset(claim)
            for claim in graph["required_claims"]
        )
    assert DEFAULT_TRANSCRIPTS_PATH.exists()
