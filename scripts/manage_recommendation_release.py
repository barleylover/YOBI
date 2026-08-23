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
FAMILY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


class RecommendationReleaseError(RuntimeError):
    """Stable operator error that never exposes credentials or SQL details."""


def _runtime_credentials(settings: Settings) -> tuple[str, str, str]:
    if settings.db_username != "YOBI_APP":
        raise RecommendationReleaseError(
            "RECOMMENDATION_RELEASE_RUNTIME_USER_REQUIRED"
        )
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise RecommendationReleaseError(
            "RECOMMENDATION_RELEASE_RUNTIME_CREDENTIALS_MISSING"
        )
    return settings.db_username, password, dsn


def _validate_family_id(family_id: str) -> str:
    if FAMILY_ID_PATTERN.fullmatch(family_id) is None:
        raise RecommendationReleaseError("RECOMMENDATION_RELEASE_ID_INVALID")
    return family_id


def _read_active(cursor: oracledb.Cursor, *, lock: bool = False) -> str | None:
    suffix = " FOR UPDATE" if lock else ""
    cursor.execute(
        f"""
        SELECT active_release_family_id
        FROM recommendation_runtime_state
        WHERE state_key=:state_key{suffix}
        """,
        state_key=ACTIVE_STATE_KEY,
    )
    row = cursor.fetchone()
    return _validate_family_id(str(row[0])) if row is not None else None


def _check_expected_active(
    actual: str | None,
    expected: str | None,
    *,
    enforce: bool,
) -> None:
    if enforce and actual != expected:
        raise RecommendationReleaseError("RECOMMENDATION_RELEASE_ACTIVE_MISMATCH")


def _rollback_before_commit(connection: oracledb.Connection) -> None:
    try:
        connection.rollback()
    except oracledb.Error:
        raise RecommendationReleaseError(
            "RECOMMENDATION_RELEASE_ROLLBACK_FAILED"
        ) from None


def get_active_release(settings: Settings) -> str | None:
    user, password, dsn = _runtime_credentials(settings)
    try:
        with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
            return _read_active(connection.cursor())
    except RecommendationReleaseError:
        raise
    except oracledb.Error:
        raise RecommendationReleaseError(
            "RECOMMENDATION_RELEASE_DATABASE_ERROR"
        ) from None


def activate_ready_release(
    settings: Settings,
    family_id: str,
    *,
    expected_current: str | None = None,
    enforce_expected: bool = False,
) -> str:
    family_id = _validate_family_id(family_id)
    if expected_current is not None:
        expected_current = _validate_family_id(expected_current)
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
                    SELECT family.status,family.knowledge_release_id,knowledge.status
                    FROM recommendation_release_family family
                    JOIN knowledge_release knowledge
                      ON knowledge.release_id=family.knowledge_release_id
                    WHERE family.release_family_id=:family_id
                    FOR UPDATE
                    """,
                    family_id=family_id,
                )
                row = cursor.fetchone()
                if row is None:
                    raise RecommendationReleaseError(
                        "RECOMMENDATION_RELEASE_NOT_FOUND"
                    )
                if str(row[0]) not in {"READY", "ACTIVE"}:
                    raise RecommendationReleaseError(
                        "RECOMMENDATION_RELEASE_NOT_READY"
                    )
                if str(row[2]) != "READY":
                    raise RecommendationReleaseError(
                        "RECOMMENDATION_KNOWLEDGE_RELEASE_NOT_READY"
                    )
                cursor.execute(
                    """
                    SELECT active_release_id
                    FROM knowledge_runtime_state
                    WHERE state_key=:state_key
                    """,
                    state_key=ACTIVE_STATE_KEY,
                )
                active_knowledge = cursor.fetchone()
                if active_knowledge is None or str(active_knowledge[0]) != str(row[1]):
                    raise RecommendationReleaseError(
                        "RECOMMENDATION_KNOWLEDGE_RELEASE_MISMATCH"
                    )
                if active_before and active_before != family_id:
                    cursor.execute(
                        """
                        UPDATE recommendation_release_family
                        SET status='READY'
                        WHERE release_family_id=:active_before
                          AND status='ACTIVE'
                        """,
                        active_before=active_before,
                    )
                cursor.execute(
                    """
                    UPDATE recommendation_release_family
                    SET status='ACTIVE',activated_at=SYSTIMESTAMP
                    WHERE release_family_id=:family_id
                    """,
                    family_id=family_id,
                )
                cursor.execute(
                    """
                    MERGE INTO recommendation_runtime_state target
                    USING (SELECT :state_key state_key FROM dual) source
                    ON (target.state_key=source.state_key)
                    WHEN MATCHED THEN UPDATE SET
                      target.active_release_family_id=:family_id,
                      target.updated_at=SYSTIMESTAMP
                    WHEN NOT MATCHED THEN INSERT (
                      state_key,active_release_family_id,updated_at
                    ) VALUES (:state_key,:family_id,SYSTIMESTAMP)
                    """,
                    state_key=ACTIVE_STATE_KEY,
                    family_id=family_id,
                )
                connection.commit()
                committed = True
                if _read_active(cursor) != family_id:
                    raise RecommendationReleaseError(
                        "RECOMMENDATION_RELEASE_ACTIVATION_READBACK_MISMATCH"
                    )
                return family_id
            except RecommendationReleaseError:
                if not committed:
                    _rollback_before_commit(connection)
                raise
            except oracledb.Error:
                if not committed:
                    _rollback_before_commit(connection)
                raise RecommendationReleaseError(
                    "RECOMMENDATION_RELEASE_DATABASE_ERROR"
                ) from None
    except RecommendationReleaseError:
        raise
    except oracledb.Error:
        raise RecommendationReleaseError(
            "RECOMMENDATION_RELEASE_DATABASE_ERROR"
        ) from None


def clear_active_release(
    settings: Settings,
    *,
    expected_current: str | None = None,
    enforce_expected: bool = False,
) -> None:
    if expected_current is not None:
        expected_current = _validate_family_id(expected_current)
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
                if active_before is not None:
                    cursor.execute(
                        """
                        UPDATE recommendation_release_family
                        SET status='READY'
                        WHERE release_family_id=:family_id AND status='ACTIVE'
                        """,
                        family_id=active_before,
                    )
                cursor.execute(
                    """
                    DELETE FROM recommendation_runtime_state
                    WHERE state_key=:state_key
                    """,
                    state_key=ACTIVE_STATE_KEY,
                )
                connection.commit()
                committed = True
                if _read_active(cursor) is not None:
                    raise RecommendationReleaseError(
                        "RECOMMENDATION_RELEASE_CLEAR_READBACK_MISMATCH"
                    )
            except RecommendationReleaseError:
                if not committed:
                    _rollback_before_commit(connection)
                raise
            except oracledb.Error:
                if not committed:
                    _rollback_before_commit(connection)
                raise RecommendationReleaseError(
                    "RECOMMENDATION_RELEASE_DATABASE_ERROR"
                ) from None
    except RecommendationReleaseError:
        raise
    except oracledb.Error:
        raise RecommendationReleaseError(
            "RECOMMENDATION_RELEASE_DATABASE_ERROR"
        ) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the active READY structured recommendation release"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("get-active")
    activate = subcommands.add_parser("activate-ready")
    activate.add_argument("family_id")
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
                    str(args.family_id),
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
    except RecommendationReleaseError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
