from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.knowledge.authoring import CompiledKnowledgeRelease
from app.knowledge.oracle_store import load_oracle_release


def _empty_release() -> CompiledKnowledgeRelease:
    return CompiledKnowledgeRelease(
        release_id="knowledge-demo-0123456789abcdef01234567",
        catalog_version="test-catalog-v1",
        manifest_sha256="a" * 64,
        expected_counts={
            "concepts": 0,
            "relations": 0,
            "closure": 0,
            "claims": 0,
            "documents": 0,
            "chunks": 0,
        },
        concepts=[],
        relations=[],
        closure=[],
        claims=[],
        documents=[],
        chunks=[],
    )


def _sql_calls(cursor: MagicMock) -> list[str]:
    return [str(call.args[0]).strip() for call in cursor.execute.call_args_list]


def test_oracle_loader_does_not_commit_and_activates_only_after_validation() -> None:
    compiled = _empty_release()
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [None, *((0,) for _ in range(7))]

    load_oracle_release(connection, compiled)

    sql = _sql_calls(cursor)
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()
    assert any("INSERT INTO knowledge_release" in statement for statement in sql)
    ready_index = next(index for index, statement in enumerate(sql) if "SET status='READY'" in statement)
    active_index = next(
        index for index, statement in enumerate(sql) if "MERGE INTO knowledge_runtime_state" in statement
    )
    assert ready_index < active_index


def test_oracle_loader_rejects_manifest_collision_without_touching_active_release() -> None:
    compiled = _empty_release()
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = ("different-manifest", "READY")

    with pytest.raises(RuntimeError, match="KNOWLEDGE_RELEASE_ID_COLLISION"):
        load_oracle_release(connection, compiled)

    sql = _sql_calls(cursor)
    connection.commit.assert_not_called()
    assert any(statement == "ROLLBACK TO yobi_knowledge_release_load" for statement in sql)
    assert not any("INSERT INTO knowledge_release" in statement for statement in sql)
    assert not any("MERGE INTO knowledge_runtime_state" in statement for statement in sql)


def test_oracle_loader_rejects_incomplete_existing_release_without_activation() -> None:
    compiled = _empty_release()
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = (compiled.manifest_sha256, "LOADING")

    with pytest.raises(RuntimeError, match="KNOWLEDGE_RELEASE_INCOMPLETE"):
        load_oracle_release(connection, compiled)

    sql = _sql_calls(cursor)
    connection.commit.assert_not_called()
    assert any(statement == "ROLLBACK TO yobi_knowledge_release_load" for statement in sql)
    assert not any("MERGE INTO knowledge_runtime_state" in statement for statement in sql)


def test_oracle_loader_rolls_back_partial_new_release_before_activation() -> None:
    compiled = _empty_release()
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.side_effect = [None, (1,), *((0,) for _ in range(6))]

    with pytest.raises(RuntimeError, match="KNOWLEDGE_RELEASE_COUNT_MISMATCH"):
        load_oracle_release(connection, compiled)

    sql = _sql_calls(cursor)
    connection.commit.assert_not_called()
    assert any(statement == "ROLLBACK TO yobi_knowledge_release_load" for statement in sql)
    assert not any("MERGE INTO knowledge_runtime_state" in statement for statement in sql)
