#!/usr/bin/env python3
"""Pure, testable release-gate invariants used by the deployment shell."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REQUIRED_EXTERNAL_GATES = frozenset(
    {"query-plan", "source-integrity", "structured", "quality-five"}
)
PROVISIONAL_EXTERNAL_GATES = frozenset(
    {"query-plan", "source-integrity", "structured"}
)
POST_REVIEW_EXTERNAL_GATES = frozenset(
    {"query-plan", "source-integrity", "structured", "quality-five-reviewed"}
)
EXPANSION_QUALITY_CASES = (
    ("expanded_japanese", "JAPANESE", "PASS"),
    ("expanded_italian", "ITALIAN", "FAIL"),
    ("expanded_american", "AMERICAN", "PASS"),
    ("expanded_southeast_asian", "SOUTHEAST_ASIAN", "PASS"),
    ("expanded_mexican", "MEXICAN", "PASS"),
)
FORBIDDEN_COMPONENTS = frozenset(
    {
        "keys",
        "wallet",
        "tmp",
        "cache",
        ".cache",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


class ReleaseGateError(RuntimeError):
    """Stable failure code for deployment contract checks."""


@dataclass(frozen=True)
class ReleasePointers:
    application: str
    knowledge: str | None
    recommendation: str | None


@dataclass(frozen=True)
class SimulatedOutcome:
    pointers: ReleasePointers
    ready_marker: bool
    restored: bool


def _member_is_forbidden(member: str) -> bool:
    normalized = posixpath.normpath(member)
    path = PurePosixPath(normalized)
    parts = path.parts
    if not member or member.startswith("/") or normalized == ".." or ".." in parts:
        return True
    if any(part.startswith("._") or part == ".DS_Store" for part in parts):
        return True
    if any(part.startswith(".env") and part != ".env.example" for part in parts):
        return True
    if any(part in FORBIDDEN_COMPONENTS for part in parts):
        return True
    if any(
        parts[index : index + 2] == ("backend", "backend")
        for index in range(max(0, len(parts) - 1))
    ):
        return True
    filename = parts[-1] if parts else ""
    return (
        filename.endswith((".db", ".sqlite", ".sqlite3"))
        or ".db-" in filename
        or ".sqlite-" in filename
        or ".sqlite3-" in filename
    )


def validate_archive_members(members: Iterable[str]) -> int:
    values = [member.strip() for member in members if member.strip()]
    if not values:
        raise ReleaseGateError("RELEASE_ARCHIVE_EMPTY")
    if any(_member_is_forbidden(member) for member in values):
        raise ReleaseGateError("RELEASE_ARCHIVE_FORBIDDEN_MEMBER")
    return len(values)


def verify_external_gates(gates: Iterable[str]) -> tuple[str, ...]:
    values = tuple(gate.strip() for gate in gates if gate.strip())
    if len(values) != len(set(values)):
        raise ReleaseGateError("RELEASE_GATE_DUPLICATE")
    if set(values) != REQUIRED_EXTERNAL_GATES:
        raise ReleaseGateError("RELEASE_GATE_INCOMPLETE")
    return tuple(sorted(values))


def verify_provisional_external_gates(gates: Iterable[str]) -> tuple[str, ...]:
    """Require functional/data gates while explicitly deferring quality-five."""

    values = tuple(gate.strip() for gate in gates if gate.strip())
    if len(values) != len(set(values)):
        raise ReleaseGateError("RELEASE_GATE_DUPLICATE")
    if set(values) != PROVISIONAL_EXTERNAL_GATES:
        raise ReleaseGateError("PROVISIONAL_RELEASE_GATE_INCOMPLETE")
    return tuple(sorted(values))


def verify_post_review_external_gates(gates: Iterable[str]) -> tuple[str, ...]:
    """Accept the operator-bounded five samples only after its fix is reverified."""

    values = tuple(gate.strip() for gate in gates if gate.strip())
    if len(values) != len(set(values)):
        raise ReleaseGateError("RELEASE_GATE_DUPLICATE")
    if set(values) != POST_REVIEW_EXTERNAL_GATES:
        raise ReleaseGateError("POST_REVIEW_RELEASE_GATE_INCOMPLETE")
    return tuple(sorted(values))


def verify_reviewed_quality_five(
    evidence_path: str | Path,
    *,
    fix_source_path: str | Path,
    knowledge_release_id: str,
    recommendation_release_family_id: str,
) -> dict[str, object]:
    """Validate the immutable five-call observation and its zero-call remediation."""

    evidence_file = Path(evidence_path)
    fix_source_file = Path(fix_source_path)
    if (
        not evidence_file.is_file()
        or evidence_file.is_symlink()
        or not fix_source_file.is_file()
        or fix_source_file.is_symlink()
    ):
        raise ReleaseGateError("QUALITY_FIVE_REVIEW_FILE_INVALID")
    try:
        payload = json.loads(evidence_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseGateError("QUALITY_FIVE_REVIEW_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise ReleaseGateError("QUALITY_FIVE_REVIEW_JSON_INVALID")
    if (
        payload.get("schema_version") != "1"
        or payload.get("gate") != "recommendation-quality-five-reviewed"
        or payload.get("status") != "REVIEWED_FIX_ACCEPTED"
        or payload.get("requested") != 5
        or payload.get("executed") != 5
        or payload.get("provider_dispatch_count") != 5
        or payload.get("normal_recommended_count") != 4
        or payload.get("safe_fallback_count") != 1
        or payload.get("additional_provider_dispatch_count_after_review") != 0
    ):
        raise ReleaseGateError("QUALITY_FIVE_REVIEW_COUNTS_INVALID")

    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != 5:
        raise ReleaseGateError("QUALITY_FIVE_REVIEW_CASES_INVALID")
    expected_failure_codes = {
        "FAILURE_CODE_PRESENT",
        "SELECTED_CRITERION_EVIDENCE_MISSING",
        "STATUS_NOT_RECOMMENDED",
    }
    for case, (expected_name, expected_cuisine, expected_status) in zip(
        cases, EXPANSION_QUALITY_CASES
    ):
        if not isinstance(case, dict):
            raise ReleaseGateError("QUALITY_FIVE_REVIEW_CASES_INVALID")
        error_codes = case.get("error_codes")
        expected_errors = expected_failure_codes if expected_status == "FAIL" else set()
        if (
            case.get("name") != expected_name
            or case.get("selected_cuisine_codes") != [expected_cuisine]
            or case.get("status") != expected_status
            or set(error_codes or []) != expected_errors
            or case.get("result_count") != 3
            or case.get("merchant_count") != 3
            or not isinstance(case.get("evidence_count"), int)
            or int(case["evidence_count"]) < 3
            or not isinstance(case.get("latency_ms"), (int, float))
            or float(case["latency_ms"]) <= 0
        ):
            raise ReleaseGateError("QUALITY_FIVE_REVIEW_CASES_INVALID")

    release = payload.get("release")
    if not isinstance(release, dict) or (
        release.get("catalog_version") != "preference-catalog-2026.08.17-v3"
        or release.get("knowledge_release_id") != knowledge_release_id
        or release.get("recommendation_release_family_id")
        != recommendation_release_family_id
    ):
        raise ReleaseGateError("QUALITY_FIVE_REVIEW_RELEASE_MISMATCH")

    review = payload.get("review")
    validation = review.get("fix_validation") if isinstance(review, dict) else None
    fix_source_sha256 = hashlib.sha256(fix_source_file.read_bytes()).hexdigest()
    if not isinstance(review, dict) or not isinstance(validation, dict) or (
        review.get("accepted_failure_case") != "expanded_italian"
        or review.get("issue_code")
        != "DETERMINISTIC_FALLBACK_DROPPED_MATCHED_CRITERIA"
        or review.get("fix_source_sha256") != fix_source_sha256
        or validation.get("status") != "PASS"
        or validation.get("category_code") != "cuisine_origins"
        or validation.get("option_code") != "ITALIAN"
        or validation.get("result_count") != 3
        or validation.get("server_order_preserved") is not True
        or validation.get("selected_criterion_evidence_present_for_every_result")
        is not True
        or validation.get("actual_provider_dispatch_count") != 0
    ):
        raise ReleaseGateError("QUALITY_FIVE_REMEDIATION_INVALID")

    return {
        "executed": 5,
        "normal_recommended_count": 4,
        "safe_fallback_count": 1,
        "additional_provider_dispatch_count_after_review": 0,
        "evidence_sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
    }


def simulate_release(
    initial: ReleasePointers,
    candidate: ReleasePointers,
    *,
    stage_verified: bool,
    completed_gates: Iterable[str],
    fail_after_symlink: bool = False,
) -> SimulatedOutcome:
    """Model the fail-closed transitions the shell implements around pointer changes."""

    if not stage_verified:
        return SimulatedOutcome(initial, ready_marker=False, restored=False)
    if fail_after_symlink:
        return SimulatedOutcome(initial, ready_marker=False, restored=True)
    try:
        verify_external_gates(completed_gates)
    except ReleaseGateError:
        return SimulatedOutcome(initial, ready_marker=False, restored=True)
    return SimulatedOutcome(candidate, ready_marker=True, restored=False)


def _safe_error_code(exc: Exception) -> str:
    value = str(exc)
    if value and len(value) <= 100 and all(
        character.isupper() or character.isdigit() or character == "_"
        for character in value
    ):
        return value
    return type(exc).__name__.upper()


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate YOBI release-gate contracts.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "validate-archive",
        help="Read tar member names from stdin and reject unsafe/forbidden paths.",
    )
    subcommands.add_parser(
        "verify-external-gates",
        help="Read completed external gate names from stdin and require the exact set.",
    )
    subcommands.add_parser(
        "verify-provisional-external-gates",
        help="Require plan, source, and structured gates while deferring performance.",
    )
    subcommands.add_parser(
        "verify-post-review-external-gates",
        help="Require the exact non-provider gates after five reviewed live samples.",
    )
    reviewed = subcommands.add_parser(
        "verify-reviewed-quality-five",
        help="Validate the five-call evidence and deterministic remediation.",
    )
    reviewed.add_argument("evidence_path")
    reviewed.add_argument("--fix-source-path", required=True)
    reviewed.add_argument("--knowledge-release-id", required=True)
    reviewed.add_argument("--recommendation-release-family-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate-archive":
            payload = {
                "status": "PASS",
                "archive_member_count": validate_archive_members(sys.stdin),
            }
        elif args.command == "verify-external-gates":
            payload = {
                "status": "PASS",
                "completed_gates": verify_external_gates(sys.stdin),
            }
        elif args.command == "verify-provisional-external-gates":
            payload = {
                "status": "PASS",
                "release_status": "PROVISIONAL",
                "completed_gates": verify_provisional_external_gates(sys.stdin),
                "deferred_gate": "quality-five",
            }
        elif args.command == "verify-post-review-external-gates":
            payload = {
                "status": "PASS",
                "release_status": "FINAL",
                "completed_gates": verify_post_review_external_gates(sys.stdin),
                "provider_dispatches_during_final_deploy": 0,
            }
        else:
            payload = {
                "status": "PASS",
                **verify_reviewed_quality_five(
                    args.evidence_path,
                    fix_source_path=args.fix_source_path,
                    knowledge_release_id=args.knowledge_release_id,
                    recommendation_release_family_id=(
                        args.recommendation_release_family_id
                    ),
                ),
            }
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - emit one sanitized JSON error only
        payload = {"status": "FAIL", "error_code": _safe_error_code(exc)}
        exit_code = 1
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
