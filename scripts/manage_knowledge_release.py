#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import oracledb

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings

ACTIVE_STATE_KEY = "ACTIVE"
RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


class KnowledgeReleaseError(RuntimeError):
    """A stable operator-facing error that never contains connection details."""


def _runtime_credentials(settings: Settings) -> tuple[str, str, str]:
    if settings.db_username != "YOBI_APP":
        raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_RUNTIME_USER_REQUIRED")
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_RUNTIME_CREDENTIALS_MISSING")
    return settings.db_username, password, dsn


def _validate_release_id(release_id: str) -> str:
    if RELEASE_ID_PATTERN.fullmatch(release_id) is None:
        raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_ID_INVALID")
    return release_id


def _read_active(cursor: oracledb.Cursor, *, lock: bool = False) -> str | None:
    suffix = " FOR UPDATE" if lock else ""
    cursor.execute(
        f"""
        SELECT active_release_id
        FROM knowledge_runtime_state
        WHERE state_key=:state_key{suffix}
        """,
        state_key=ACTIVE_STATE_KEY,
    )
    row = cursor.fetchone()
    return _validate_release_id(str(row[0])) if row is not None else None


def _check_expected_active(
    actual: str | None,
    expected: str | None,
    *,
    enforce: bool,
) -> None:
    if enforce and actual != expected:
        raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_ACTIVE_MISMATCH")


def _rollback_before_commit(connection: oracledb.Connection) -> None:
    try:
        connection.rollback()
    except oracledb.Error:
        raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_ROLLBACK_FAILED") from None


def get_active_release(settings: Settings) -> str | None:
    user, password, dsn = _runtime_credentials(settings)
    try:
        with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
            cursor = connection.cursor()
            return _read_active(cursor)
    except KnowledgeReleaseError:
        raise
    except oracledb.Error:
        raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_DATABASE_ERROR") from None


def activate_ready_release(
    settings: Settings,
    release_id: str,
    *,
    expected_current: str | None = None,
    enforce_expected: bool = False,
) -> str:
    release_id = _validate_release_id(release_id)
    if expected_current is not None:
        expected_current = _validate_release_id(expected_current)
    user, password, dsn = _runtime_credentials(settings)
    try:
        with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
            committed = False
            try:
                cursor = connection.cursor()
                active_before = _read_active(cursor, lock=True)
                _check_expected_active(
                    active_before,
                    expected_current,
                    enforce=enforce_expected,
                )
                cursor.execute(
                    """
                    SELECT status
                    FROM knowledge_release
                    WHERE release_id=:release_id
                    FOR UPDATE
                    """,
                    release_id=release_id,
                )
                row = cursor.fetchone()
                if row is None:
                    raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_NOT_FOUND")
                if str(row[0]) != "READY":
                    raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_NOT_READY")

                cursor.execute(
                    """
                    MERGE INTO knowledge_runtime_state target
                    USING (SELECT :state_key state_key FROM dual) source
                    ON (target.state_key=source.state_key)
                    WHEN MATCHED THEN UPDATE SET
                      target.active_release_id=:release_id,
                      target.updated_at=SYSTIMESTAMP
                    WHEN NOT MATCHED THEN INSERT (
                      state_key,active_release_id,updated_at
                    ) VALUES (:state_key,:release_id,SYSTIMESTAMP)
                    """,
                    state_key=ACTIVE_STATE_KEY,
                    release_id=release_id,
                )
                connection.commit()
                committed = True

                if _read_active(cursor) != release_id:
                    raise KnowledgeReleaseError(
                        "KNOWLEDGE_RELEASE_ACTIVATION_READBACK_MISMATCH"
                    )
                return release_id
            except KnowledgeReleaseError:
                if not committed:
                    _rollback_before_commit(connection)
                raise
            except oracledb.Error:
                if not committed:
                    _rollback_before_commit(connection)
                raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_DATABASE_ERROR") from None
    except KnowledgeReleaseError:
        raise
    except oracledb.Error:
        raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_DATABASE_ERROR") from None


def clear_active_release(
    settings: Settings,
    *,
    expected_current: str | None = None,
    enforce_expected: bool = False,
) -> None:
    if expected_current is not None:
        expected_current = _validate_release_id(expected_current)
    user, password, dsn = _runtime_credentials(settings)
    try:
        with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
            committed = False
            try:
                cursor = connection.cursor()
                active_before = _read_active(cursor, lock=True)
                _check_expected_active(
                    active_before,
                    expected_current,
                    enforce=enforce_expected,
                )
                cursor.execute(
                    """
                    DELETE FROM knowledge_runtime_state
                    WHERE state_key=:state_key
                    """,
                    state_key=ACTIVE_STATE_KEY,
                )
                connection.commit()
                committed = True
                if _read_active(cursor) is not None:
                    raise KnowledgeReleaseError(
                        "KNOWLEDGE_RELEASE_CLEAR_READBACK_MISMATCH"
                    )
            except KnowledgeReleaseError:
                if not committed:
                    _rollback_before_commit(connection)
                raise
            except oracledb.Error:
                if not committed:
                    _rollback_before_commit(connection)
                raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_DATABASE_ERROR") from None
    except KnowledgeReleaseError:
        raise
    except oracledb.Error:
        raise KnowledgeReleaseError("KNOWLEDGE_RELEASE_DATABASE_ERROR") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the active READY knowledge release")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("get-active")
    activate = subcommands.add_parser("activate-ready")
    activate.add_argument("release_id")
    activate_expected = activate.add_mutually_exclusive_group()
    activate_expected.add_argument("--expected-current")
    activate_expected.add_argument("--expect-no-active", action="store_true")
    clear = subcommands.add_parser("clear-active")
    clear_expected = clear.add_mutually_exclusive_group()
    clear_expected.add_argument("--expected-current")
    clear_expected.add_argument("--expect-no-active", action="store_true")
    return parser


def run(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime_settings = settings or Settings()
    try:
        if args.command == "get-active":
            print(get_active_release(runtime_settings) or "")
        elif args.command == "activate-ready":
            enforce_expected = bool(args.expected_current or args.expect_no_active)
            print(
                activate_ready_release(
                    runtime_settings,
                    str(args.release_id),
                    expected_current=args.expected_current,
                    enforce_expected=enforce_expected,
                )
            )
        else:
            enforce_expected = bool(args.expected_current or args.expect_no_active)
            clear_active_release(
                runtime_settings,
                expected_current=args.expected_current,
                enforce_expected=enforce_expected,
            )
            print("CLEARED")
    except KnowledgeReleaseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
