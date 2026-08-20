from __future__ import annotations

import json
from array import array
from datetime import datetime, timezone
from typing import Any

import oracledb

from app.knowledge.authoring import CompiledKnowledgeRelease


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _insert_rows(
    cursor: oracledb.Cursor,
    table: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    columns = list(rows[0])
    cursor.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) "
        f"VALUES ({','.join(':' + column for column in columns)})",
        rows,
    )


def _validate_release_contents(
    cursor: oracledb.Cursor,
    compiled: CompiledKnowledgeRelease,
) -> dict[str, int]:
    table_names = {
        "concepts": "dish_concept",
        "relations": "dish_relation",
        "closure": "dish_concept_closure",
        "claims": "concept_claim",
        "documents": "knowledge_document",
        "chunks": "knowledge_chunk",
    }
    actual: dict[str, int] = {}
    for key, table in table_names.items():
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE release_id=:release_id",
            release_id=compiled.release_id,
        )
        actual[key] = int(cursor.fetchone()[0])
    if actual != compiled.expected_counts:
        raise RuntimeError("KNOWLEDGE_RELEASE_COUNT_MISMATCH")
    cursor.execute(
        """
        SELECT COUNT(*) FROM knowledge_chunk
        WHERE release_id=:release_id AND embedding_vector IS NULL
        """,
        release_id=compiled.release_id,
    )
    if int(cursor.fetchone()[0]) != 0:
        raise RuntimeError("KNOWLEDGE_RELEASE_VECTOR_MISSING")
    return actual


def _activate_release(
    cursor: oracledb.Cursor,
    release_id: str,
    now: datetime,
) -> None:
    cursor.execute(
        """
        MERGE INTO knowledge_runtime_state target
        USING (SELECT 'ACTIVE' state_key FROM dual) source
        ON (target.state_key=source.state_key)
        WHEN MATCHED THEN UPDATE SET
          target.active_release_id=:release_id,target.updated_at=:updated_at
        WHEN NOT MATCHED THEN INSERT (state_key,active_release_id,updated_at)
          VALUES ('ACTIVE',:release_id,:updated_at)
        """,
        release_id=release_id,
        updated_at=now,
    )


def load_oracle_release(
    connection: oracledb.Connection,
    compiled: CompiledKnowledgeRelease,
    *,
    activate: bool = True,
) -> None:
    """Load an immutable release inside the caller-owned transaction.

    The function never commits. A savepoint removes its own partial work on failure while
    preserving any earlier work in the outer seed transaction. Existing releases are reusable
    only when their manifest is identical and their status is already ``READY``. Callers that
    stage and independently verify a release can pass ``activate=False`` and move the runtime
    pointer in a later transaction.
    """

    cursor = connection.cursor()
    now = _now()
    counts_json = json.dumps(compiled.expected_counts, sort_keys=True)
    cursor.execute("SAVEPOINT yobi_knowledge_release_load")
    try:
        cursor.execute(
            """
            SELECT manifest_sha256,status
            FROM knowledge_release
            WHERE release_id=:release_id
            """,
            release_id=compiled.release_id,
        )
        existing = cursor.fetchone()
        if existing is not None:
            manifest_sha256, status = str(existing[0]), str(existing[1])
            if manifest_sha256 != compiled.manifest_sha256:
                raise RuntimeError("KNOWLEDGE_RELEASE_ID_COLLISION")
            if status != "READY":
                raise RuntimeError("KNOWLEDGE_RELEASE_INCOMPLETE")
            _validate_release_contents(cursor, compiled)
            if activate:
                _activate_release(cursor, compiled.release_id, now)
            return

        cursor.execute(
            """
            INSERT INTO knowledge_release (
              release_id,catalog_version,manifest_sha256,embedding_model,embedding_dimension,
              embedding_version,status,expected_counts_json,actual_counts_json,is_synthetic,
              created_at,completed_at
            ) VALUES (
              :release_id,:catalog_version,:manifest_sha256,:embedding_model,:embedding_dimension,
              :embedding_version,'LOADING',:expected_counts_json,'{}',1,:created_at,NULL
            )
            """,
            release_id=compiled.release_id,
            catalog_version=compiled.catalog_version,
            manifest_sha256=compiled.manifest_sha256,
            embedding_model=compiled.embedding_model,
            embedding_dimension=compiled.embedding_dimension,
            embedding_version=compiled.embedding_version,
            expected_counts_json=counts_json,
            created_at=now,
        )
        _insert_rows(cursor, "dish_concept", compiled.concepts)
        _insert_rows(cursor, "dish_relation", compiled.relations)
        _insert_rows(cursor, "dish_concept_closure", compiled.closure)
        _insert_rows(cursor, "concept_claim", compiled.claims)
        _insert_rows(cursor, "knowledge_document", compiled.documents)
        chunk_rows: list[dict[str, Any]] = []
        for source in compiled.chunks:
            row = dict(source)
            vector_json = str(row.pop("embedding_vector_json"))
            row["embedding_vector"] = array("f", json.loads(vector_json))
            chunk_rows.append(row)
        _insert_rows(cursor, "knowledge_chunk", chunk_rows)

        actual = _validate_release_contents(cursor, compiled)
        cursor.execute(
            """
            UPDATE knowledge_release
            SET status='READY',actual_counts_json=:counts,completed_at=:completed_at
            WHERE release_id=:release_id AND status='LOADING'
            """,
            counts=json.dumps(actual, sort_keys=True),
            completed_at=now,
            release_id=compiled.release_id,
        )
        if activate:
            _activate_release(cursor, compiled.release_id, now)
    except BaseException:
        cursor.execute("ROLLBACK TO yobi_knowledge_release_load")
        raise
