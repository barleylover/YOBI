from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_manage_recommendation_release",
    ROOT / "scripts" / "manage_recommendation_release.py",
)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.row: tuple[str, ...] | None = None

    def execute(self, statement: str, **parameters: Any) -> None:
        self.connection.executions.append((statement, parameters))
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("SELECT ACTIVE_RELEASE_FAMILY_ID"):
            self.row = (
                (self.connection.active_family,)
                if self.connection.active_family is not None
                else None
            )
        elif normalized.startswith("SELECT FAMILY.STATUS"):
            self.row = (
                self.connection.family_status,
                self.connection.family_knowledge,
                self.connection.knowledge_status,
            )
        elif normalized.startswith("SELECT ACTIVE_RELEASE_ID"):
            self.row = (self.connection.active_knowledge,)
        elif normalized.startswith("UPDATE RECOMMENDATION_RELEASE_FAMILY"):
            self.row = None
        elif normalized.startswith("MERGE INTO RECOMMENDATION_RUNTIME_STATE"):
            self.connection.active_family = str(parameters["family_id"])
            self.row = None
        elif normalized.startswith("DELETE FROM RECOMMENDATION_RUNTIME_STATE"):
            self.connection.active_family = None
            self.row = None
        else:  # pragma: no cover - keeps the fake deliberately narrow
            raise AssertionError(f"Unexpected SQL: {normalized}")

    def fetchone(self) -> tuple[str, ...] | None:
        return self.row


class FakeConnection:
    def __init__(
        self,
        *,
        active_family: str | None = "family-old",
        family_status: str = "READY",
        family_knowledge: str = "knowledge-target",
        knowledge_status: str = "READY",
        active_knowledge: str = "knowledge-target",
    ) -> None:
        self.active_family = active_family
        self.family_status = family_status
        self.family_knowledge = family_knowledge
        self.knowledge_status = knowledge_status
        self.active_knowledge = active_knowledge
        self.executions: list[tuple[str, dict[str, Any]]] = []
        self.events: list[str] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


def runtime_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "adb_dsn": "synthetic-dsn",
        "db_password": "synthetic-password",
        "db_username": "YOBI_APP",
    }
    values.update(overrides)
    return Settings(**values)


def test_activate_ready_family_is_cas_guarded_and_knowledge_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(manager.oracledb, "connect", lambda **_kwargs: connection)

    result = manager.activate_ready_release(
        runtime_settings(),
        "family-target",
        expected_current="family-old",
        enforce_expected=True,
    )

    assert result == "family-target"
    assert connection.active_family == "family-target"
    assert connection.events == ["commit"]
    assert any(
        "KNOWLEDGE_RUNTIME_STATE" in " ".join(statement.split()).upper()
        for statement, _ in connection.executions
    )
    assert all("family-target" not in statement for statement, _ in connection.executions)


def test_activation_rejects_knowledge_pointer_mismatch_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(active_knowledge="knowledge-other")
    monkeypatch.setattr(manager.oracledb, "connect", lambda **_kwargs: connection)

    with pytest.raises(
        manager.RecommendationReleaseError,
        match="RECOMMENDATION_KNOWLEDGE_RELEASE_MISMATCH",
    ):
        manager.activate_ready_release(runtime_settings(), "family-target")

    assert connection.active_family == "family-old"
    assert connection.events == ["rollback"]


def test_clear_active_family_is_explicit_and_cas_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(manager.oracledb, "connect", lambda **_kwargs: connection)

    manager.clear_active_release(
        runtime_settings(),
        expected_current="family-old",
        enforce_expected=True,
    )

    assert connection.active_family is None
    assert connection.events == ["commit"]


def test_manager_redacts_database_failure(
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
    assert output.err.strip() == "RECOMMENDATION_RELEASE_DATABASE_ERROR"
    assert "synthetic-dsn" not in output.err
    assert "synthetic-password" not in output.err
