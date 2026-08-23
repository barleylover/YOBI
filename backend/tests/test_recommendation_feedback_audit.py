from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_feedback_audit",
    ROOT / "scripts" / "export_recommendation_feedback_audit.py",
)
assert SPEC and SPEC.loader
feedback_audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = feedback_audit
SPEC.loader.exec_module(feedback_audit)


def test_feedback_export_derives_impressions_selection_and_weak_negatives() -> None:
    request_rows = [
        {
            "session_id": "session-1",
            "request_id": "request-initial",
            "mode": "INITIAL",
            "final_candidates_json": [
                {"menu_id": "menu-a"},
                {"menu_id": "menu-b"},
                {"menu_id": "menu-c"},
            ],
            "release_family_id": "family-v2",
            "created_at": "2026-08-18T00:00:00+00:00",
        },
        {
            "session_id": "session-1",
            "request_id": "request-similar",
            "mode": "SIMILAR",
            "final_candidates_json": [
                {"menu_id": "menu-d"},
                {"menu_id": "menu-e"},
                {"menu_id": "menu-f"},
            ],
            "release_family_id": "family-v2",
            "created_at": "2026-08-18T00:01:00+00:00",
        },
    ]
    event_rows = [
        {
            "event_id": "event-1",
            "session_id": "session-1",
            "snapshot_id": "snapshot-1",
            "structured_request_id": "request-initial",
            "event_type": "SELECT_MENU",
            "payload_json": {"menu_id": "menu-b"},
            "result_json": {},
            "created_at": "2026-08-18T00:02:00+00:00",
        }
    ]

    signals = feedback_audit.derive_feedback_signals(request_rows, event_rows)

    assert sum(item["signal_type"] == "IMPRESSION" for item in signals) == 6
    assert sum(item["signal_type"] == "WEAK_NEGATIVE" for item in signals) == 3
    selected = [item for item in signals if item["signal_type"] == "EXPLICIT_SELECTION"]
    assert len(selected) == 1
    assert selected[0]["menu_id"] == "menu-b"
    assert selected[0]["signal_value"] == 1.0
    assert all("session_id" not in item for item in signals)


def test_feedback_signal_derivation_is_deterministic() -> None:
    request = {
        "session_id": "session-1",
        "request_id": "request-1",
        "mode": "INITIAL",
        "final_candidates_json": [{"menu_id": "menu-a"}],
        "release_family_id": "family-v2",
        "created_at": "2026-08-18T00:00:00+00:00",
    }

    first = feedback_audit.derive_feedback_signals([request], [])
    second = feedback_audit.derive_feedback_signals([request], [])

    assert first == second
    assert first[0]["signal_id"].startswith("feedback_")
