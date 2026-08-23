#!/usr/bin/env python3
"""Export recommendation impressions and feedback as immutable audit JSONL.

The exporter is read-only. It does not train, update weights, or write any row to
the application database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import Settings


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _session_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def _signal_id(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "feedback_" + hashlib.sha256(canonical.encode()).hexdigest()[:32]


def _candidate_ids(value: Any) -> list[str]:
    candidates = _json(value, [])
    if not isinstance(candidates, list):
        return []
    return list(
        dict.fromkeys(
            str(item.get("menu_id") or "")
            for item in candidates
            if isinstance(item, dict) and item.get("menu_id")
        )
    )


def derive_feedback_signals(
    request_rows: Iterable[Mapping[str, Any]],
    event_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Derive append-only signals without inferring an unobserved preference."""

    signals: list[dict[str, Any]] = []
    last_impression: dict[str, tuple[str, list[str]]] = {}
    request_to_family: dict[tuple[str, str], str] = {}
    for row in sorted(
        request_rows,
        key=lambda item: (str(item.get("created_at") or ""), str(item.get("request_id") or "")),
    ):
        session_id = str(row.get("session_id") or "")
        request_id = str(row.get("request_id") or "")
        if not session_id or not request_id:
            continue
        family_id = str(row.get("release_family_id") or "")
        request_to_family[(session_id, request_id)] = family_id
        mode = str(row.get("mode") or "INITIAL").upper()
        menu_ids = _candidate_ids(row.get("final_candidates_json"))
        previous = last_impression.get(session_id)
        if mode in {"SIMILAR", "RETRY"} and previous is not None:
            previous_request_id, previous_menu_ids = previous
            for menu_id in previous_menu_ids:
                core = {
                    "signal_type": "WEAK_NEGATIVE",
                    "signal_value": -0.25,
                    "basis": mode,
                    "session_id_hash": _session_hash(session_id),
                    "request_id": request_id,
                    "source_request_id": previous_request_id,
                    "menu_id": menu_id,
                    "release_family_id": family_id,
                    "observed_at": str(row.get("created_at") or ""),
                }
                signals.append({"signal_id": _signal_id(core), **core})
        for rank, menu_id in enumerate(menu_ids, start=1):
            core = {
                "signal_type": "IMPRESSION",
                "signal_value": 0.0,
                "basis": "SNAPSHOT_FINAL_CANDIDATE",
                "session_id_hash": _session_hash(session_id),
                "request_id": request_id,
                "source_request_id": request_id,
                "menu_id": menu_id,
                "rank": rank,
                "release_family_id": family_id,
                "observed_at": str(row.get("created_at") or ""),
            }
            signals.append({"signal_id": _signal_id(core), **core})
        if menu_ids:
            last_impression[session_id] = (request_id, menu_ids)

    for row in event_rows:
        if str(row.get("event_type") or "") != "SELECT_MENU":
            continue
        payload = _json(row.get("payload_json"), {})
        result = _json(row.get("result_json"), {})
        if not isinstance(payload, dict):
            payload = {}
        if not isinstance(result, dict):
            result = {}
        session_id = str(row.get("session_id") or "")
        request_id = str(row.get("structured_request_id") or "")
        menu_id = str(
            payload.get("menu_id")
            or result.get("selected_menu_id")
            or result.get("menu_id")
            or ""
        )
        if not session_id or not menu_id:
            continue
        core = {
            "signal_type": "EXPLICIT_SELECTION",
            "signal_value": 1.0,
            "basis": "SELECT_MENU",
            "session_id_hash": _session_hash(session_id),
            "request_id": request_id or None,
            "source_request_id": request_id or None,
            "snapshot_id": str(row.get("snapshot_id") or "") or None,
            "event_id": str(row.get("event_id") or "") or None,
            "menu_id": menu_id,
            "release_family_id": request_to_family.get(
                (session_id, request_id),
                str(row.get("release_family_id") or ""),
            ),
            "observed_at": str(row.get("created_at") or ""),
        }
        signals.append({"signal_id": _signal_id(core), **core})
    return sorted(
        signals,
        key=lambda item: (
            str(item.get("observed_at") or ""),
            str(item.get("signal_type") or ""),
            str(item.get("signal_id") or ""),
        ),
    )


def _sqlite_rows(path: Path, family_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        parameters: tuple[Any, ...] = (family_id,) if family_id else ()
        family_clause = "WHERE r.recommendation_release_family_id=?" if family_id else ""
        request_rows = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT r.session_id,r.request_id,r.mode,r.status,
                       r.final_candidates_json,r.created_at,
                       r.recommendation_release_family_id release_family_id
                FROM structured_recommendation_request r
                {family_clause}
                ORDER BY r.created_at,r.request_id
                """,
                parameters,
            ).fetchall()
        ]
        event_parameters: tuple[Any, ...] = (family_id,) if family_id else ()
        event_family_clause = (
            "AND r.recommendation_release_family_id=?" if family_id else ""
        )
        event_rows = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT e.event_id,e.session_id,e.snapshot_id,e.event_type,
                       e.payload_json,e.result_json,e.created_at,
                       s.structured_request_id,
                       r.recommendation_release_family_id release_family_id
                FROM conversation_event e
                LEFT JOIN recommendation_snapshot s ON s.snapshot_id=e.snapshot_id
                LEFT JOIN structured_recommendation_request r
                  ON r.request_id=s.structured_request_id
                 AND r.session_id=e.session_id
                WHERE e.event_type='SELECT_MENU'
                {event_family_clause}
                ORDER BY e.created_at,e.event_id
                """,
                event_parameters,
            ).fetchall()
        ]
        return request_rows, event_rows
    finally:
        connection.close()


def _oracle_rows(settings: Settings, family_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    import oracledb

    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if settings.db_username != "YOBI_APP" or not dsn or not password:
        raise RuntimeError("FEEDBACK_AUDIT_RUNTIME_CREDENTIALS_INVALID")
    with oracledb.connect(user=settings.db_username, password=password, dsn=dsn) as connection:
        cursor = connection.cursor()
        family_clause = (
            "WHERE r.recommendation_release_family_id=:family_id" if family_id else ""
        )
        cursor.execute(
            f"""
            SELECT r.session_id,r.request_id,r.request_mode mode,r.status,
                   r.final_candidates_json,r.created_at,
                   r.recommendation_release_family_id release_family_id
            FROM structured_recommendation_request r
            {family_clause}
            ORDER BY r.created_at,r.request_id
            """,
            family_id=family_id,
        ) if family_id else cursor.execute(
            """
            SELECT r.session_id,r.request_id,r.request_mode mode,r.status,
                   r.final_candidates_json,r.created_at,
                   r.recommendation_release_family_id release_family_id
            FROM structured_recommendation_request r
            ORDER BY r.created_at,r.request_id
            """
        )
        names = [str(value[0]).lower() for value in cursor.description]
        request_rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        event_family_clause = (
            "AND r.recommendation_release_family_id=:family_id" if family_id else ""
        )
        event_sql = f"""
            SELECT e.event_id,e.session_id,e.snapshot_id,e.event_type,
                   e.payload_json,e.result_json,e.created_at,
                   s.structured_request_id,
                   r.recommendation_release_family_id release_family_id
            FROM conversation_event e
            LEFT JOIN recommendation_snapshot s ON s.snapshot_id=e.snapshot_id
            LEFT JOIN structured_recommendation_request r
              ON r.request_id=s.structured_request_id
             AND r.session_id=e.session_id
            WHERE e.event_type='SELECT_MENU'
            {event_family_clause}
            ORDER BY e.created_at,e.event_id
            """
        if family_id:
            cursor.execute(event_sql, family_id=family_id)
        else:
            cursor.execute(event_sql)
        names = [str(value[0]).lower() for value in cursor.description]
        event_rows = [dict(zip(names, row)) for row in cursor.fetchall()]
        return request_rows, event_rows


def _write_immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def export(backend: str, output: Path, *, sqlite_path: Path, family_id: str | None) -> dict[str, Any]:
    settings = Settings()
    if backend == "sqlite":
        request_rows, event_rows = _sqlite_rows(sqlite_path, family_id)
    else:
        request_rows, event_rows = _oracle_rows(settings, family_id)
    signals = derive_feedback_signals(request_rows, event_rows)
    content = b"".join(
        (json.dumps(signal, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for signal in signals
    )
    _write_immutable(output, content)
    digest = hashlib.sha256(content).hexdigest()
    counts: dict[str, int] = {}
    for signal in signals:
        key = str(signal["signal_type"])
        counts[key] = counts.get(key, 0) + 1
    manifest = {
        "schema_version": "1",
        "policy": "AUDIT_ONLY_NO_AUTOMATIC_LEARNING",
        "backend": backend,
        "family_filter": family_id,
        "request_row_count": len(request_rows),
        "event_row_count": len(event_rows),
        "signal_count": len(signals),
        "signal_counts": dict(sorted(counts.items())),
        "jsonl_sha256": digest,
    }
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    _write_immutable(
        manifest_path,
        (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode(),
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sqlite", "oracle"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sqlite-path", type=Path, default=Path("backend/data/yobi_demo.db"))
    parser.add_argument("--release-family-id")
    args = parser.parse_args()
    manifest = export(
        args.backend,
        args.output,
        sqlite_path=args.sqlite_path,
        family_id=args.release_family_id,
    )
    print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
