from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic import SecretStr  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.db.repository import YobiRepository  # noqa: E402
from app.db.sqlite_repository import SQLiteYobiRepository  # noqa: E402
from app.domain.dialogue import ConversationEventInput, ConversationEventType  # noqa: E402
from app.domain.models import AssistantTurn, Profile, ProfileCreate, Session  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from app.services.demo_control import DemoControl  # noqa: E402

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
DEFAULT_TRANSCRIPTS_PATH = FIXTURE_ROOT / "chatbot_golden_transcripts.json"
DEFAULT_KNOWLEDGE_PATH = FIXTURE_ROOT / "knowledge_golden_cases.json"

RECOMMENDATION_CARD_TYPES = {
    "category_recommendations",
    "menu_recommendations",
    "preset_collection",
}
SOUP_CATEGORIES = {
    "chicken kalguksu",
    "samgyetang",
    "sundubu",
    "kimchi stew",
    "gukbap",
    "seolleongtang",
    "eomuk",
}
UNSAFE_REASSURANCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "absolute_safety",
        re.compile(r"\b(?:absolutely|completely|definitely|guaranteed|100%)\s+safe\b", re.I),
    ),
    ("safe_for_you", re.compile(r"\bsafe for you\b", re.I)),
    ("allergy_safe", re.compile(r"\ballergy[- ]safe\b", re.I)),
    (
        "no_risk",
        re.compile(r"\bno\s+(?:allergy\s+|cross[- ]contamination\s+)?risk\b", re.I),
    ),
)


class FixtureError(ValueError):
    """Raised when a machine-readable golden fixture violates its schema."""


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, set):
        return sorted(_json_value(item) for item in value)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


@dataclass
class Recorder:
    metrics: dict[str, int] = field(
        default_factory=lambda: {
            "transcript_count": 0,
            "message_turn_count": 0,
            "event_count": 0,
            "knowledge_case_count": 0,
            "assertion_count": 0,
            "failure_count": 0,
            "premature_recommendation_count": 0,
            "state_persistence_failure_count": 0,
            "hard_constraint_violation_count": 0,
            "snapshot_reference_failure_count": 0,
            "conversation_event_failure_count": 0,
            "unsafe_reassurance_count": 0,
            "knowledge_failure_count": 0,
            "deferred_knowledge_assertion_count": 0,
        }
    )
    failures: list[dict[str, Any]] = field(default_factory=list)

    def check(
        self,
        condition: bool,
        *,
        case_id: str,
        step: str,
        assertion: str,
        expected: Any,
        actual: Any,
        counter: str | None = None,
    ) -> None:
        self.metrics["assertion_count"] += 1
        if condition:
            return
        self.metrics["failure_count"] += 1
        if counter:
            self.metrics[counter] += 1
        self.failures.append(
            {
                "case_id": case_id,
                "step": step,
                "assertion": assertion,
                "expected": _json_value(expected),
                "actual": _json_value(actual),
            }
        )


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FixtureError(f"{location} must be an object")
    return {str(key): item for key, item in value.items()}


def _require_list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise FixtureError(f"{location} must be an array")
    return value


def load_transcript_fixture(path: Path = DEFAULT_TRANSCRIPTS_PATH) -> dict[str, Any]:
    payload = _require_object(json.loads(path.read_text(encoding="utf-8")), "transcript fixture")
    if payload.get("schema_version") != 1:
        raise FixtureError("transcript fixture schema_version must be 1")
    transcripts = _require_list(payload.get("transcripts"), "transcripts")
    if not transcripts:
        raise FixtureError("transcripts must not be empty")
    ids: list[str] = []
    for index, raw_transcript in enumerate(transcripts):
        transcript = _require_object(raw_transcript, f"transcripts[{index}]")
        case_id = transcript.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise FixtureError(f"transcripts[{index}].id must be a non-empty string")
        ids.append(case_id)
        covers = _require_list(transcript.get("covers"), f"transcripts[{index}].covers")
        if not covers or any(not isinstance(item, str) for item in covers):
            raise FixtureError(f"transcripts[{index}].covers must contain strings")
        _require_object(transcript.get("profile", {}), f"transcripts[{index}].profile")
        steps = _require_list(transcript.get("steps"), f"transcripts[{index}].steps")
        if not steps:
            raise FixtureError(f"transcripts[{index}].steps must not be empty")
        for step_index, raw_step in enumerate(steps):
            step = _require_object(raw_step, f"transcripts[{index}].steps[{step_index}]")
            if step.get("kind") not in {"message", "event"}:
                raise FixtureError(
                    f"transcripts[{index}].steps[{step_index}].kind must be message or event"
                )
            _require_object(
                step.get("expect", {}), f"transcripts[{index}].steps[{step_index}].expect"
            )
    if len(ids) != len(set(ids)):
        raise FixtureError("transcript ids must be unique")
    return payload


def load_knowledge_fixture(path: Path = DEFAULT_KNOWLEDGE_PATH) -> dict[str, Any]:
    payload = _require_object(json.loads(path.read_text(encoding="utf-8")), "knowledge fixture")
    if payload.get("schema_version") != 1:
        raise FixtureError("knowledge fixture schema_version must be 1")
    _require_object(payload.get("boundary"), "knowledge boundary")
    cases = _require_list(payload.get("cases"), "knowledge cases")
    if not cases:
        raise FixtureError("knowledge cases must not be empty")
    ids: list[str] = []
    for index, raw_case in enumerate(cases):
        case = _require_object(raw_case, f"knowledge cases[{index}]")
        case_id = case.get("id")
        menu_id = case.get("menu_id")
        query = case.get("query")
        if not isinstance(case_id, str) or not case_id:
            raise FixtureError(f"knowledge cases[{index}].id must be a non-empty string")
        if not isinstance(menu_id, str) or not menu_id:
            raise FixtureError(f"knowledge cases[{index}].menu_id must be a non-empty string")
        if not isinstance(query, str) or not query:
            raise FixtureError(f"knowledge cases[{index}].query must be a non-empty string")
        ids.append(case_id)
        _require_object(
            case.get("repository_expectations"),
            f"knowledge cases[{index}].repository_expectations",
        )
        graph = _require_object(
            case.get("knowledge_graph_expectations"),
            f"knowledge cases[{index}].knowledge_graph_expectations",
        )
        concept_id = graph.get("concept_id")
        if not isinstance(concept_id, str) or not concept_id.startswith("dish_"):
            raise FixtureError(f"knowledge cases[{index}] needs a dish_ concept_id")
        facets = _require_list(
            graph.get("required_facets"),
            f"knowledge cases[{index}].knowledge_graph_expectations.required_facets",
        )
        if not facets or any(not isinstance(item, str) for item in facets):
            raise FixtureError(f"knowledge cases[{index}] required_facets must contain strings")
        claims = _require_list(
            graph.get("required_claims"),
            f"knowledge cases[{index}].knowledge_graph_expectations.required_claims",
        )
        for claim_index, raw_claim in enumerate(claims):
            claim = _require_object(raw_claim, f"knowledge cases[{index}] claim[{claim_index}]")
            required = {"claim_type", "target_id", "status", "scope", "inherited"}
            if not required.issubset(claim):
                raise FixtureError(
                    f"knowledge cases[{index}] claim[{claim_index}] lacks "
                    f"{sorted(required - set(claim))}"
                )
    if len(ids) != len(set(ids)):
        raise FixtureError("knowledge case ids must be unique")
    return payload


def _profile_from_fixture(raw: Any) -> ProfileCreate:
    overrides = _require_object(raw, "profile")
    baseline = ProfileCreate(
        consent_demo_data=True,
        dietary_rules=[],
        allergy_severity="mild",
        spice_tolerance=3,
    ).model_dump(mode="json")
    baseline.update(overrides)
    baseline["consent_demo_data"] = True
    return ProfileCreate.model_validate(baseline)


def _get_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _collect_card_menus(turn: AssistantTurn) -> list[dict[str, Any]]:
    menus: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("menu_id") and value.get("merchant_id"):
                menu_id = str(value["menu_id"])
                if menu_id not in seen:
                    seen.add(menu_id)
                    menus.append({str(key): item for key, item in value.items()})
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for card in turn.cards:
        visit(card.data)
    return menus


def _collect_key_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        if key in value:
            found.append(value[key])
        for item in value.values():
            found.extend(_collect_key_values(item, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_key_values(item, key))
    return found


def _category_is_excluded(category: str, exclusions: Sequence[str]) -> bool:
    lowered = category.lower()
    for exclusion in exclusions:
        normalized = exclusion.lower()
        if normalized == "soup" and lowered in SOUP_CATEGORIES:
            return True
        if normalized != "soup" and normalized in lowered:
            return True
    return False


def _candidate_menus(
    repository: SQLiteYobiRepository,
    profile: Profile,
    turn: AssistantTurn,
    recorder: Recorder,
    case_id: str,
    step_label: str,
) -> list[dict[str, Any]]:
    result = turn.recommendation_result
    if result is None:
        return []
    menus: list[dict[str, Any]] = []
    for candidate in result.candidates:
        menu = repository.get_menu(candidate.menu_id, profile)
        recorder.check(
            menu is not None,
            case_id=case_id,
            step=step_label,
            assertion="recommendation_candidate_resolves_to_catalog_menu",
            expected=True,
            actual=menu is not None,
            counter="hard_constraint_violation_count",
        )
        if menu is not None:
            menus.append(menu.model_dump(mode="json"))
    return menus


def _check_state_expectations(
    recorder: Recorder,
    case_id: str,
    step_label: str,
    state_payload: dict[str, Any],
    raw_expectation: Any,
) -> None:
    expectation = _require_object(raw_expectation, f"{case_id}.{step_label}.state")
    equals = _require_object(expectation.get("equals", {}), f"{case_id}.{step_label}.equals")
    for path, expected in equals.items():
        actual = _get_path(state_payload, path)
        recorder.check(
            actual == expected,
            case_id=case_id,
            step=step_label,
            assertion=f"state_equals:{path}",
            expected=expected,
            actual=actual,
            counter="state_persistence_failure_count",
        )
    contains = _require_object(expectation.get("contains", {}), f"{case_id}.{step_label}.contains")
    for path, raw_expected in contains.items():
        expected_items = raw_expected if isinstance(raw_expected, list) else [raw_expected]
        actual = _get_path(state_payload, path)
        condition = isinstance(actual, list) and all(item in actual for item in expected_items)
        recorder.check(
            condition,
            case_id=case_id,
            step=step_label,
            assertion=f"state_contains:{path}",
            expected=expected_items,
            actual=actual,
            counter="state_persistence_failure_count",
        )
    excludes = _require_object(expectation.get("excludes", {}), f"{case_id}.{step_label}.excludes")
    for path, raw_expected in excludes.items():
        expected_items = raw_expected if isinstance(raw_expected, list) else [raw_expected]
        actual = _get_path(state_payload, path)
        condition = isinstance(actual, list) and all(item not in actual for item in expected_items)
        recorder.check(
            condition,
            case_id=case_id,
            step=step_label,
            assertion=f"state_excludes:{path}",
            expected=expected_items,
            actual=actual,
            counter="state_persistence_failure_count",
        )


def _check_menu_expectations(
    recorder: Recorder,
    case_id: str,
    step_label: str,
    menus: list[dict[str, Any]],
    state_payload: dict[str, Any],
    raw_expectation: Any,
) -> None:
    expectation = _require_object(raw_expectation, f"{case_id}.{step_label}.menus")
    if "minimum_count" in expectation:
        minimum = int(expectation["minimum_count"])
        recorder.check(
            len(menus) >= minimum,
            case_id=case_id,
            step=step_label,
            assertion="minimum_recommendation_count",
            expected=minimum,
            actual=len(menus),
            counter="hard_constraint_violation_count",
        )
    if "maximum_price" in expectation:
        maximum = int(expectation["maximum_price"])
        violating = [menu["menu_id"] for menu in menus if int(menu["price"]) > maximum]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="maximum_price",
            expected=maximum,
            actual=violating,
            counter="hard_constraint_violation_count",
        )
    if "maximum_spiciness" in expectation:
        maximum = int(expectation["maximum_spiciness"])
        violating = [menu["menu_id"] for menu in menus if int(menu["spice_level"]) > maximum]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="maximum_spiciness",
            expected=maximum,
            actual=violating,
            counter="hard_constraint_violation_count",
        )
    groups = expectation.get("forbidden_category_groups", [])
    if not isinstance(groups, list):
        raise FixtureError(f"{case_id}.{step_label}.forbidden_category_groups must be an array")
    if groups:
        violating = [
            menu["menu_id"]
            for menu in menus
            if _category_is_excluded(str(menu["category"]), [str(item) for item in groups])
        ]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="forbidden_category_groups",
            expected=[],
            actual=violating,
            counter="hard_constraint_violation_count",
        )
    if expectation.get("all_synthetic") is True:
        violating = [menu["menu_id"] for menu in menus if menu.get("is_synthetic") is not True]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="all_recommendations_are_synthetic",
            expected=[],
            actual=violating,
            counter="hard_constraint_violation_count",
        )
    if expectation.get("exclude_rejected") is True:
        rejected = set(state_payload.get("rejected_menu_ids", []))
        violating = [menu["menu_id"] for menu in menus if menu["menu_id"] in rejected]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="rejected_menus_do_not_reappear",
            expected=[],
            actual=violating,
            counter="conversation_event_failure_count",
        )


def _check_global_turn_invariants(
    recorder: Recorder,
    case_id: str,
    step_label: str,
    turn: AssistantTurn,
    state_payload: dict[str, Any],
    menus: list[dict[str, Any]],
) -> None:
    recorder.check(
        bool(turn.text.strip()),
        case_id=case_id,
        step=step_label,
        assertion="assistant_text_is_nonempty",
        expected=True,
        actual=bool(turn.text.strip()),
    )
    card_types = {card.type for card in turn.cards}
    premature = bool(
        turn.readiness is not None
        and not turn.readiness.may_recommend
        and card_types.intersection(RECOMMENDATION_CARD_TYPES)
    )
    recorder.check(
        not premature,
        case_id=case_id,
        step=step_label,
        assertion="no_recommendation_before_readiness",
        expected=False,
        actual=premature,
        counter="premature_recommendation_count",
    )

    surface = (
        turn.text
        + "\n"
        + json.dumps(
            [card.model_dump(mode="json") for card in turn.cards],
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    for pattern_id, pattern in UNSAFE_REASSURANCE_PATTERNS:
        matched = bool(pattern.search(surface))
        recorder.check(
            not matched,
            case_id=case_id,
            step=step_label,
            assertion=f"unsafe_reassurance_absent:{pattern_id}",
            expected=False,
            actual=matched,
            counter="unsafe_reassurance_count",
        )

    budget = state_payload.get("budget_krw")
    if budget is not None:
        violating = [menu["menu_id"] for menu in menus if int(menu["price"]) > int(budget)]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="persisted_budget_is_a_hard_filter",
            expected=[],
            actual=violating,
            counter="hard_constraint_violation_count",
        )
    max_spiciness = state_payload.get("max_spiciness")
    if max_spiciness is not None:
        violating = [
            menu["menu_id"] for menu in menus if int(menu["spice_level"]) > int(max_spiciness)
        ]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="persisted_spiciness_is_a_hard_filter",
            expected=[],
            actual=violating,
            counter="hard_constraint_violation_count",
        )
    exclusions = [str(item) for item in state_payload.get("excluded_categories", [])]
    if exclusions:
        violating = [
            menu["menu_id"]
            for menu in menus
            if _category_is_excluded(str(menu["category"]), exclusions)
        ]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="persisted_category_exclusions_are_hard_filters",
            expected=[],
            actual=violating,
            counter="hard_constraint_violation_count",
        )
    rejected = set(state_payload.get("rejected_menu_ids", []))
    if rejected:
        violating = [menu["menu_id"] for menu in menus if menu["menu_id"] in rejected]
        recorder.check(
            not violating,
            case_id=case_id,
            step=step_label,
            assertion="persisted_rejections_are_hard_filters",
            expected=[],
            actual=violating,
            counter="conversation_event_failure_count",
        )


def _check_message_expectations(
    recorder: Recorder,
    case_id: str,
    step_label: str,
    turn: AssistantTurn,
    session: Session,
    menus: list[dict[str, Any]],
    expectation: dict[str, Any],
    previous_candidate_ids: list[str],
    previous_snapshot_id: str | None,
) -> None:
    if "dialogue_act" in expectation:
        expected_dialogue_act = str(expectation["dialogue_act"])
        recorder.check(
            turn.dialogue_act.value == expected_dialogue_act,
            case_id=case_id,
            step=step_label,
            assertion="dialogue_act",
            expected=expected_dialogue_act,
            actual=turn.dialogue_act.value,
        )
    if "readiness" in expectation:
        expected_readiness = str(expectation["readiness"])
        actual_readiness = turn.readiness.status.value if turn.readiness else None
        recorder.check(
            actual_readiness == expected_readiness,
            case_id=case_id,
            step=step_label,
            assertion="readiness",
            expected=expected_readiness,
            actual=actual_readiness,
        )
    if "card_count" in expectation:
        expected_card_count = int(expectation["card_count"])
        recorder.check(
            len(turn.cards) == expected_card_count,
            case_id=case_id,
            step=step_label,
            assertion="card_count",
            expected=expected_card_count,
            actual=len(turn.cards),
        )
    if "card_types" in expectation:
        expected_card_types = [
            str(item) for item in _require_list(expectation["card_types"], "card_types")
        ]
        actual_card_types = [card.type for card in turn.cards]
        recorder.check(
            actual_card_types == expected_card_types,
            case_id=case_id,
            step=step_label,
            assertion="card_types",
            expected=expected_card_types,
            actual=actual_card_types,
        )
    if "snapshot" in expectation:
        expected_snapshot = str(expectation["snapshot"])
        present = turn.recommendation_snapshot_id is not None
        expected_present = expected_snapshot == "present"
        recorder.check(
            present == expected_present,
            case_id=case_id,
            step=step_label,
            assertion="recommendation_snapshot_presence",
            expected=expected_snapshot,
            actual="present" if present else "absent",
            counter="snapshot_reference_failure_count" if "reference" in expectation else None,
        )
    for fragment in expectation.get("text_contains_all", []):
        expected = str(fragment).lower()
        recorder.check(
            expected in turn.text.lower(),
            case_id=case_id,
            step=step_label,
            assertion="assistant_text_contains",
            expected=expected,
            actual=turn.text,
        )

    state_payload = session.meal_need_state.model_dump(mode="json")
    if "state" in expectation:
        _check_state_expectations(
            recorder, case_id, step_label, state_payload, expectation["state"]
        )
    if "menus" in expectation:
        _check_menu_expectations(
            recorder, case_id, step_label, menus, state_payload, expectation["menus"]
        )
    if "reference" in expectation:
        reference = _require_object(expectation["reference"], "reference")
        position = int(reference["candidate_position"])
        valid_position = 1 <= position <= len(previous_candidate_ids)
        recorder.check(
            valid_position,
            case_id=case_id,
            step=step_label,
            assertion="referenced_candidate_position_exists",
            expected=position,
            actual=len(previous_candidate_ids),
            counter="snapshot_reference_failure_count",
        )
        if valid_position:
            expected_menu_id = previous_candidate_ids[position - 1]
            card_menu_ids = [str(menu["menu_id"]) for menu in _collect_card_menus(turn)]
            recorder.check(
                expected_menu_id in card_menu_ids,
                case_id=case_id,
                step=step_label,
                assertion="reference_resolves_to_prior_snapshot_candidate",
                expected=expected_menu_id,
                actual=card_menu_ids,
                counter="snapshot_reference_failure_count",
            )
        source_positions = [
            value
            for card in turn.cards
            for value in _collect_key_values(card.data, "source_position")
        ]
        recorder.check(
            position in source_positions,
            case_id=case_id,
            step=step_label,
            assertion="reference_source_position",
            expected=position,
            actual=source_positions,
            counter="snapshot_reference_failure_count",
        )
        source_snapshots = [
            value
            for card in turn.cards
            for value in _collect_key_values(card.data, "source_snapshot_id")
        ]
        recorder.check(
            previous_snapshot_id is not None and previous_snapshot_id in source_snapshots,
            case_id=case_id,
            step=step_label,
            assertion="reference_uses_latest_snapshot_id",
            expected="latest_snapshot",
            actual="latest_snapshot" if previous_snapshot_id in source_snapshots else "other",
            counter="snapshot_reference_failure_count",
        )


def _run_event_step(
    recorder: Recorder,
    repository: SQLiteYobiRepository,
    case_id: str,
    step_index: int,
    step: dict[str, Any],
    session: Session,
    latest_snapshot_id: str | None,
    latest_candidate_ids: list[str],
) -> Session:
    step_label = f"event[{step_index}]"
    recorder.metrics["event_count"] += 1
    position = int(step.get("candidate_position", 0))
    valid_position = 1 <= position <= len(latest_candidate_ids)
    recorder.check(
        valid_position,
        case_id=case_id,
        step=step_label,
        assertion="event_candidate_position_exists",
        expected=position,
        actual=len(latest_candidate_ids),
        counter="conversation_event_failure_count",
    )
    recorder.check(
        latest_snapshot_id is not None,
        case_id=case_id,
        step=step_label,
        assertion="event_has_latest_snapshot",
        expected=True,
        actual=latest_snapshot_id is not None,
        counter="conversation_event_failure_count",
    )
    if not valid_position or latest_snapshot_id is None:
        return session
    candidate_id = latest_candidate_ids[position - 1]
    event_type = ConversationEventType(str(step["event_type"]))
    idempotency_key = (
        "eval-"
        + hashlib.sha256(f"{case_id}:{step_index}:{event_type.value}".encode()).hexdigest()[:20]
    )
    event = ConversationEventInput(
        event_type=event_type,
        snapshot_id=latest_snapshot_id,
        menu_id=candidate_id,
        expected_state_version=session.state_version,
        idempotency_key=idempotency_key,
    )
    try:
        result = repository.apply_conversation_event(session.session_id, event)
    except Exception as exc:
        recorder.check(
            False,
            case_id=case_id,
            step=step_label,
            assertion="conversation_event_executes",
            expected="success",
            actual=f"{type(exc).__name__}:{exc}",
            counter="conversation_event_failure_count",
        )
        return session
    updated = repository.get_session(session.session_id)
    recorder.check(
        updated is not None,
        case_id=case_id,
        step=step_label,
        assertion="conversation_event_persists_session",
        expected=True,
        actual=updated is not None,
        counter="conversation_event_failure_count",
    )
    if updated is None:
        return session
    recorder.check(
        result.state_version == session.state_version + 1,
        case_id=case_id,
        step=step_label,
        assertion="conversation_event_advances_state_version",
        expected=session.state_version + 1,
        actual=result.state_version,
        counter="conversation_event_failure_count",
    )
    expectation = _require_object(step.get("expect", {}), f"{case_id}.{step_label}.expect")
    if "dialogue_act" in expectation:
        expected = str(expectation["dialogue_act"])
        recorder.check(
            updated.dialogue_act.value == expected,
            case_id=case_id,
            step=step_label,
            assertion="event_dialogue_act",
            expected=expected,
            actual=updated.dialogue_act.value,
            counter="conversation_event_failure_count",
        )
    if "candidate_in_state" in expectation:
        field_name = str(expectation["candidate_in_state"])
        state_payload = updated.meal_need_state.model_dump(mode="json")
        if field_name == "selected_menu_id":
            actual: Any = state_payload.get(field_name)
            condition = actual == candidate_id
        else:
            actual = state_payload.get(field_name)
            condition = isinstance(actual, list) and candidate_id in actual
        recorder.check(
            condition,
            case_id=case_id,
            step=step_label,
            assertion=f"event_candidate_in_state:{field_name}",
            expected=candidate_id,
            actual=actual,
            counter="conversation_event_failure_count",
        )
    if "selected_candidate" in expectation:
        expected_selected = bool(expectation["selected_candidate"])
        actual_selected = updated.selected_menu_id == candidate_id
        recorder.check(
            actual_selected == expected_selected,
            case_id=case_id,
            step=step_label,
            assertion="event_selected_candidate",
            expected=expected_selected,
            actual=actual_selected,
            counter="conversation_event_failure_count",
        )
    if step.get("repeat_once") is True:
        duplicate = repository.apply_conversation_event(session.session_id, event)
        recorder.check(
            duplicate.duplicate is True,
            case_id=case_id,
            step=step_label,
            assertion="conversation_event_is_idempotent",
            expected=True,
            actual=duplicate.duplicate,
            counter="conversation_event_failure_count",
        )
        recorder.check(
            duplicate.event_id == result.event_id
            and duplicate.state_version == result.state_version,
            case_id=case_id,
            step=step_label,
            assertion="duplicate_event_does_not_advance_state",
            expected=result.state_version,
            actual=duplicate.state_version,
            counter="conversation_event_failure_count",
        )
    return updated


def _run_transcripts(
    recorder: Recorder,
    repository: SQLiteYobiRepository,
    fixture: dict[str, Any],
) -> tuple[list[str], list[str]]:
    transcript_ids: list[str] = []
    coverage: set[str] = set()
    transcripts = _require_list(fixture["transcripts"], "transcripts")
    recorder.metrics["transcript_count"] = len(transcripts)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        oci_genai_api_key=SecretStr(""),
        demo_fallback_enabled=True,
    )
    for raw_transcript in transcripts:
        transcript = _require_object(raw_transcript, "transcript")
        case_id = str(transcript["id"])
        transcript_ids.append(case_id)
        coverage.update(str(item) for item in _require_list(transcript["covers"], "covers"))
        profile = repository.create_profile(_profile_from_fixture(transcript.get("profile", {})))
        session = repository.create_session(profile.profile_id)
        service = ChatService(cast(YobiRepository, repository), settings, DemoControl())
        latest_snapshot_id: str | None = None
        latest_candidate_ids: list[str] = []
        for step_index, raw_step in enumerate(_require_list(transcript["steps"], "steps"), 1):
            step = _require_object(raw_step, f"{case_id}.steps[{step_index}]")
            if step["kind"] == "event":
                session = _run_event_step(
                    recorder,
                    repository,
                    case_id,
                    step_index,
                    step,
                    session,
                    latest_snapshot_id,
                    latest_candidate_ids,
                )
                continue

            step_label = f"message[{step_index}]"
            recorder.metrics["message_turn_count"] += 1
            user_text = step.get("input")
            if not isinstance(user_text, str) or not user_text.strip():
                raise FixtureError(f"{case_id}.{step_label}.input must be a non-empty string")
            previous_candidate_ids = list(latest_candidate_ids)
            previous_snapshot_id = latest_snapshot_id
            try:
                turn = service.respond(session, profile, user_text)
            except Exception as exc:
                recorder.check(
                    False,
                    case_id=case_id,
                    step=step_label,
                    assertion="chat_service_responds",
                    expected="success",
                    actual=f"{type(exc).__name__}:{exc}",
                )
                break
            persisted = repository.get_session(session.session_id)
            recorder.check(
                persisted is not None,
                case_id=case_id,
                step=step_label,
                assertion="chat_turn_persists_session",
                expected=True,
                actual=persisted is not None,
            )
            if persisted is None:
                break
            session = persisted
            menus = _candidate_menus(repository, profile, turn, recorder, case_id, step_label)
            state_payload = session.meal_need_state.model_dump(mode="json")
            _check_global_turn_invariants(recorder, case_id, step_label, turn, state_payload, menus)
            expectation = _require_object(step.get("expect", {}), f"{case_id}.{step_label}.expect")
            _check_message_expectations(
                recorder,
                case_id,
                step_label,
                turn,
                session,
                menus,
                expectation,
                previous_candidate_ids,
                previous_snapshot_id,
            )
            if turn.recommendation_result is not None:
                latest_candidate_ids = [
                    candidate.menu_id for candidate in turn.recommendation_result.candidates
                ]
                latest_snapshot_id = turn.recommendation_snapshot_id
    return transcript_ids, sorted(coverage)


def _check_knowledge_cases(
    recorder: Recorder,
    repository: SQLiteYobiRepository,
    fixture: dict[str, Any],
) -> list[str]:
    cases = _require_list(fixture["cases"], "knowledge cases")
    recorder.metrics["knowledge_case_count"] = len(cases)
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            dietary_rules=[],
            allergy_severity="mild",
            spice_tolerance=3,
        )
    )
    case_ids: list[str] = []
    for raw_case in cases:
        case = _require_object(raw_case, "knowledge case")
        case_id = str(case["id"])
        case_ids.append(case_id)
        menu_id = str(case["menu_id"])
        expectation = _require_object(
            case["repository_expectations"], f"{case_id}.repository_expectations"
        )
        menu = repository.get_menu(menu_id, profile)
        recorder.check(
            menu is not None,
            case_id=case_id,
            step="repository",
            assertion="menu_exists",
            expected=True,
            actual=menu is not None,
            counter="knowledge_failure_count",
        )
        if menu is None:
            continue
        menu_payload = menu.model_dump(mode="json")
        expected_fields = _require_object(
            expectation.get("menu_fields", {}), f"{case_id}.menu_fields"
        )
        for field_name, expected in expected_fields.items():
            actual = menu_payload.get(field_name)
            recorder.check(
                actual == expected,
                case_id=case_id,
                step="repository",
                assertion=f"menu_field:{field_name}",
                expected=expected,
                actual=actual,
                counter="knowledge_failure_count",
            )
        for field_name in expectation.get("nonempty_menu_fields", []):
            actual = menu_payload.get(str(field_name))
            recorder.check(
                isinstance(actual, str) and bool(actual.strip()),
                case_id=case_id,
                step="repository",
                assertion=f"nonempty_menu_field:{field_name}",
                expected=True,
                actual=bool(actual),
                counter="knowledge_failure_count",
            )
        evidence = repository.get_evidence(menu_id)
        minimum_evidence = int(expectation.get("minimum_evidence_count", 0))
        recorder.check(
            len(evidence) >= minimum_evidence,
            case_id=case_id,
            step="repository",
            assertion="minimum_evidence_count",
            expected=minimum_evidence,
            actual=len(evidence),
            counter="knowledge_failure_count",
        )
        evidence_payloads = [item.model_dump(mode="json") for item in evidence]
        for raw_required in expectation.get("required_evidence", []):
            required = _require_object(raw_required, f"{case_id}.required_evidence")
            found = any(
                all(candidate.get(key) == value for key, value in required.items())
                for candidate in evidence_payloads
            )
            recorder.check(
                found,
                case_id=case_id,
                step="repository",
                assertion="required_evidence_claim",
                expected=required,
                actual=[
                    {
                        "claim_type": item.get("claim_type"),
                        "status": item.get("status"),
                        "source_type": item.get("source_type"),
                    }
                    for item in evidence_payloads
                ],
                counter="knowledge_failure_count",
            )
        if "required_option_groups" in expectation:
            expected_groups = set(str(item) for item in expectation["required_option_groups"])
            actual_groups = {group.name_en for group in repository.get_options(menu_id)}
            recorder.check(
                expected_groups.issubset(actual_groups),
                case_id=case_id,
                step="repository",
                assertion="required_option_groups",
                expected=sorted(expected_groups),
                actual=sorted(actual_groups),
                counter="knowledge_failure_count",
            )
        surface = json.dumps(
            {"menu": menu_payload, "evidence": evidence_payloads},
            ensure_ascii=False,
            sort_keys=True,
        )
        for pattern_id, pattern in UNSAFE_REASSURANCE_PATTERNS:
            matched = bool(pattern.search(surface))
            recorder.check(
                not matched,
                case_id=case_id,
                step="repository",
                assertion=f"unsafe_knowledge_reassurance_absent:{pattern_id}",
                expected=False,
                actual=matched,
                counter="unsafe_reassurance_count",
            )

        graph = _require_object(
            case["knowledge_graph_expectations"], f"{case_id}.knowledge_graph_expectations"
        )
        if graph.get("enforced_by_this_runner") is True:
            knowledge = repository.get_grounded_menu_knowledge(
                menu_id,
                query=str(case["query"]),
            )
            recorder.check(
                knowledge.concept_id == graph["concept_id"],
                case_id=case_id,
                step="knowledge_graph",
                assertion="mapped_concept",
                expected=graph["concept_id"],
                actual=knowledge.concept_id,
                counter="knowledge_failure_count",
            )
            expected_concepts = set(
                str(item)
                for item in _require_list(
                    graph["expected_retrieval_concepts"], "retrieval concepts"
                )
            )
            recorder.check(
                expected_concepts.issubset(set(knowledge.concept_lineage)),
                case_id=case_id,
                step="knowledge_graph",
                assertion="concept_lineage",
                expected=sorted(expected_concepts),
                actual=knowledge.concept_lineage,
                counter="knowledge_failure_count",
            )
            required_facets = set(
                str(item)
                for item in _require_list(graph["required_facets"], "required facets")
            )
            recorder.check(
                required_facets.issubset(set(knowledge.available_facets)),
                case_id=case_id,
                step="knowledge_graph",
                assertion="available_facets",
                expected=sorted(required_facets),
                actual=knowledge.available_facets,
                counter="knowledge_failure_count",
            )
            recorder.check(
                bool(knowledge.passages) and all(passage.score <= 1 for passage in knowledge.passages),
                case_id=case_id,
                step="knowledge_graph",
                assertion="vector_retrieval_returns_grounded_passages",
                expected=True,
                actual=[passage.model_dump(mode="json") for passage in knowledge.passages],
                counter="knowledge_failure_count",
            )
            claims = [
                *[claim.model_dump(mode="json") for claim in knowledge.ingredient_claims],
                *[claim.model_dump(mode="json") for claim in knowledge.allergen_claims],
            ]
            for raw_claim in _require_list(graph["required_claims"], "required claims"):
                required = _require_object(raw_claim, f"{case_id}.required_claim")
                target_key = (
                    "ingredient_id" if required["claim_type"] == "INGREDIENT" else "allergen_id"
                )
                found = any(
                    claim.get(target_key) == required["target_id"]
                    and claim.get("status") == required["status"]
                    and claim.get("source_scope") == required["scope"]
                    and claim.get("inherited") is required["inherited"]
                    for claim in claims
                )
                recorder.check(
                    found,
                    case_id=case_id,
                    step="knowledge_graph",
                    assertion=f"resolved_claim:{required['target_id']}",
                    expected=required,
                    actual=claims,
                    counter="knowledge_failure_count",
                )
        else:
            recorder.check(
                False,
                case_id=case_id,
                step="knowledge_graph",
                assertion="knowledge_graph_case_must_be_enforced",
                expected=True,
                actual=False,
                counter="knowledge_failure_count",
            )
    return case_ids


def run_acceptance(
    transcripts_path: Path = DEFAULT_TRANSCRIPTS_PATH,
    knowledge_path: Path = DEFAULT_KNOWLEDGE_PATH,
) -> dict[str, Any]:
    transcript_fixture = load_transcript_fixture(transcripts_path)
    knowledge_fixture = load_knowledge_fixture(knowledge_path)
    recorder = Recorder()
    with tempfile.TemporaryDirectory(prefix="yobi-chatbot-acceptance-") as directory:
        repository = SQLiteYobiRepository(Path(directory) / "acceptance.db")
        repository.initialize()
        transcript_ids, coverage = _run_transcripts(recorder, repository, transcript_fixture)
        knowledge_case_ids = _check_knowledge_cases(recorder, repository, knowledge_fixture)
    return {
        "suite": "yobi-chatbot-multiturn-acceptance",
        "schema_version": 1,
        "mode": "sqlite-real-chat-service-deterministic-fallback",
        "passed": recorder.metrics["failure_count"] == 0,
        "metrics": recorder.metrics,
        "coverage": coverage,
        "transcripts": transcript_ids,
        "knowledge_cases": knowledge_case_ids,
        "failures": recorder.failures,
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run YOBI's deterministic chatbot acceptance suite"
    )
    parser.add_argument("--transcripts", type=Path, default=DEFAULT_TRANSCRIPTS_PATH)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_acceptance(args.transcripts, args.knowledge)
    except Exception as exc:
        report = {
            "suite": "yobi-chatbot-multiturn-acceptance",
            "schema_version": 1,
            "mode": "sqlite-real-chat-service-deterministic-fallback",
            "passed": False,
            "metrics": {"failure_count": 1},
            "coverage": [],
            "transcripts": [],
            "knowledge_cases": [],
            "failures": [
                {
                    "case_id": "runner",
                    "step": "startup",
                    "assertion": "fixture_and_runner_are_valid",
                    "expected": "success",
                    "actual": f"{type(exc).__name__}:{exc}",
                }
            ],
        }
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=None if args.compact else 2,
        )
    )
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
