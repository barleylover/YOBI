from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_manage_knowledge_release",
    ROOT / "scripts" / "manage_knowledge_release.py",
)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.row: tuple[str] | None = None

    def execute(self, statement: str, **parameters: Any) -> None:
        self.connection.executions.append((statement, parameters))
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("SELECT STATUS"):
            self.row = (
                (self.connection.status,) if self.connection.status is not None else None
            )
        elif normalized.startswith("MERGE INTO KNOWLEDGE_RUNTIME_STATE"):
            self.connection.active_release = str(parameters["release_id"])
            self.row = None
        elif normalized.startswith("DELETE FROM KNOWLEDGE_RUNTIME_STATE"):
            self.connection.active_release = None
            self.row = None
        elif normalized.startswith("SELECT ACTIVE_RELEASE_ID"):
            active = self.connection.readback_override or self.connection.active_release
            self.row = (active,) if active is not None else None
        else:  # pragma: no cover - protects the narrow fake contract
            raise AssertionError(f"Unexpected SQL: {normalized}")

    def fetchone(self) -> tuple[str] | None:
        return self.row


class FakeConnection:
    def __init__(
        self,
        *,
        status: str | None = "READY",
        active_release: str | None = "knowledge-demo-old",
        readback_override: str | None = None,
    ) -> None:
        self.status = status
        self.active_release = active_release
        self.readback_override = readback_override
        self.executions: list[tuple[str, dict[str, Any]]] = []
        self.events: list[str] = []
        self.closed = False

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.closed = True
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        if self.closed:
            raise AssertionError("rollback called after connection close")
        self.events.append("rollback")


def runtime_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "adb_dsn": "synthetic-dsn",
        "db_password": "synthetic-password",
        "db_username": "YOBI_APP",
    }
    values.update(overrides)
    return Settings(**values)


def test_get_active_uses_runtime_user_and_bound_state_key(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    connect_arguments: dict[str, str] = {}

    def connect(**kwargs: str) -> FakeConnection:
        connect_arguments.update(kwargs)
        return connection

    monkeypatch.setattr(manager.oracledb, "connect", connect)

    assert manager.get_active_release(runtime_settings()) == "knowledge-demo-old"
    assert connect_arguments == {
        "user": "YOBI_APP",
        "password": "synthetic-password",
        "dsn": "synthetic-dsn",
    }
    statement, parameters = connection.executions[0]
    assert ":state_key" in statement
    assert parameters == {"state_key": "ACTIVE"}


def test_activate_ready_commits_and_reads_back_with_bound_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(manager.oracledb, "connect", lambda **_kwargs: connection)
    release_id = "knowledge-demo-new"

    assert manager.activate_ready_release(runtime_settings(), release_id) == release_id
    assert connection.active_release == release_id
    assert connection.events == ["commit"]
    assert len(connection.executions) == 4
    active_sql, active_parameters = connection.executions[0]
    status_sql, status_parameters = connection.executions[1]
    merge_sql, merge_parameters = connection.executions[2]
    readback_sql, readback_parameters = connection.executions[3]
    assert "FOR UPDATE" in active_sql
    assert active_parameters == {"state_key": "ACTIVE"}
    assert "FOR UPDATE" in status_sql
    assert release_id not in status_sql
    assert status_parameters == {"release_id": release_id}
    assert release_id not in merge_sql
    assert merge_parameters == {"state_key": "ACTIVE", "release_id": release_id}
    assert ":state_key" in readback_sql
    assert readback_parameters == {"state_key": "ACTIVE"}


def test_activate_ready_rejects_non_ready_without_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(status="LOADING")
    monkeypatch.setattr(manager.oracledb, "connect", lambda **_kwargs: connection)

    with pytest.raises(manager.KnowledgeReleaseError, match="KNOWLEDGE_RELEASE_NOT_READY"):
        manager.activate_ready_release(runtime_settings(), "knowledge-demo-loading")

    assert connection.active_release == "knowledge-demo-old"
    assert connection.events == ["rollback"]


def test_activate_ready_readback_mismatch_is_reported_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(readback_override="knowledge-demo-concurrent")
    monkeypatch.setattr(manager.oracledb, "connect", lambda **_kwargs: connection)

    with pytest.raises(
        manager.KnowledgeReleaseError,
        match="KNOWLEDGE_RELEASE_ACTIVATION_READBACK_MISMATCH",
    ):
        manager.activate_ready_release(runtime_settings(), "knowledge-demo-new")

    assert connection.events == ["commit"]


def test_expected_current_guard_and_explicit_clear_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(active_release="knowledge-demo-new")
    monkeypatch.setattr(manager.oracledb, "connect", lambda **_kwargs: connection)

    with pytest.raises(
        manager.KnowledgeReleaseError,
        match="KNOWLEDGE_RELEASE_ACTIVE_MISMATCH",
    ):
        manager.activate_ready_release(
            runtime_settings(),
            "knowledge-demo-old",
            expected_current="knowledge-demo-unexpected",
            enforce_expected=True,
        )
    assert connection.events == ["rollback"]
    assert connection.active_release == "knowledge-demo-new"

    connection.events.clear()
    manager.clear_active_release(
        runtime_settings(),
        expected_current="knowledge-demo-new",
        enforce_expected=True,
    )
    assert connection.events == ["commit"]
    assert connection.active_release is None


def test_manager_requires_yobi_app_and_valid_release_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def connect(**_kwargs: str) -> FakeConnection:
        nonlocal called
        called = True
        return FakeConnection()

    monkeypatch.setattr(manager.oracledb, "connect", connect)
    with pytest.raises(
        manager.KnowledgeReleaseError,
        match="KNOWLEDGE_RELEASE_RUNTIME_USER_REQUIRED",
    ):
        manager.get_active_release(runtime_settings(db_username="OTHER_APP"))
    with pytest.raises(manager.KnowledgeReleaseError, match="KNOWLEDGE_RELEASE_ID_INVALID"):
        manager.activate_ready_release(runtime_settings(), "bad release; SELECT secret")
    assert called is False


def test_cli_reduces_database_failures_without_printing_dsn_or_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def connect(**kwargs: str) -> FakeConnection:
        raise manager.oracledb.DatabaseError(
            f"driver leak {kwargs['dsn']} {kwargs['password']}"
        )

    monkeypatch.setattr(manager.oracledb, "connect", connect)
    result = manager.run(["get-active"], runtime_settings())
    output = capsys.readouterr()

    assert result == 1
    assert output.out == ""
    assert output.err.strip() == "KNOWLEDGE_RELEASE_DATABASE_ERROR"
    assert "synthetic-dsn" not in output.err
    assert "synthetic-password" not in output.err
