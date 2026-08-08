from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.knowledge.authoring import CompiledKnowledgeRelease
from app.rag.embeddings import cosine_similarity, deterministic_embedding


@dataclass(frozen=True)
class ChunkSearchResult:
    chunk_id: str
    document_id: str
    concept_id: str
    facet: str
    content: str
    score: float


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ",".join("?" for _ in columns)
    connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        [[row[column] for column in columns] for row in rows],
    )


def load_sqlite_release(connection: sqlite3.Connection, compiled: CompiledKnowledgeRelease) -> None:
    """Load one immutable release and activate it after validation.

    The same source-derived ID may be reused idempotently only when its manifest is identical.
    This preserves local SQLite compatibility without replacing release-scoped rows in place.
    """

    now = _now()
    counts_json = json.dumps(compiled.expected_counts, sort_keys=True)
    with connection:
        existing = connection.execute(
            """
            SELECT manifest_sha256,status FROM knowledge_release WHERE release_id=?
            """,
            (compiled.release_id,),
        ).fetchone()
        if existing is not None:
            manifest_sha256, status = str(existing[0]), str(existing[1])
            if manifest_sha256 != compiled.manifest_sha256:
                raise RuntimeError("KNOWLEDGE_RELEASE_ID_COLLISION")
            if status != "READY":
                raise RuntimeError("KNOWLEDGE_RELEASE_INCOMPLETE")
            _validate_sqlite_release(connection, compiled)
            connection.execute(
                """
                INSERT INTO knowledge_runtime_state(state_key,active_release_id,updated_at)
                VALUES ('ACTIVE',?,?)
                ON CONFLICT(state_key) DO UPDATE SET
                  active_release_id=excluded.active_release_id,
                  updated_at=excluded.updated_at
                """,
                (compiled.release_id, now),
            )
            return

        connection.execute(
            """
            INSERT INTO knowledge_release (
              release_id,catalog_version,manifest_sha256,embedding_model,
              embedding_dimension,embedding_version,status,expected_counts_json,
              actual_counts_json,is_synthetic,created_at,completed_at
            ) VALUES (?,?,?,?,?,?,'LOADING',?,?,1,?,NULL)
            """,
            (
                compiled.release_id,
                compiled.catalog_version,
                compiled.manifest_sha256,
                compiled.embedding_model,
                compiled.embedding_dimension,
                compiled.embedding_version,
                counts_json,
                "{}",
                now,
            ),
        )
        _insert_rows(connection, "dish_concept", compiled.concepts)
        _insert_rows(connection, "dish_relation", compiled.relations)
        _insert_rows(connection, "dish_concept_closure", compiled.closure)
        _insert_rows(connection, "concept_claim", compiled.claims)
        _insert_rows(connection, "knowledge_document", compiled.documents)
        _insert_rows(connection, "knowledge_chunk", compiled.chunks)

        actual = _validate_sqlite_release(connection, compiled)
        connection.execute(
            """
            UPDATE knowledge_release
            SET status='READY', actual_counts_json=?, completed_at=?
            WHERE release_id=?
            """,
            (json.dumps(actual, sort_keys=True), now, compiled.release_id),
        )
        connection.execute(
            """
            INSERT INTO knowledge_runtime_state(state_key,active_release_id,updated_at)
            VALUES ('ACTIVE',?,?)
            ON CONFLICT(state_key) DO UPDATE SET
              active_release_id=excluded.active_release_id,
              updated_at=excluded.updated_at
            """,
            (compiled.release_id, now),
        )


def _validate_sqlite_release(
    connection: sqlite3.Connection,
    compiled: CompiledKnowledgeRelease,
) -> dict[str, int]:
    actual = {
        key: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE release_id = ?", (compiled.release_id,)
            ).fetchone()[0]
        )
        for key, table in (
            ("concepts", "dish_concept"),
            ("relations", "dish_relation"),
            ("closure", "dish_concept_closure"),
            ("claims", "concept_claim"),
            ("documents", "knowledge_document"),
            ("chunks", "knowledge_chunk"),
        )
    }
    if actual != compiled.expected_counts:
        raise RuntimeError("KNOWLEDGE_RELEASE_COUNT_MISMATCH")
    null_vectors = connection.execute(
        """
        SELECT COUNT(*) FROM knowledge_chunk
        WHERE release_id = ? AND embedding_vector_json IS NULL
        """,
        (compiled.release_id,),
    ).fetchone()[0]
    if int(null_vectors) != 0:
        raise RuntimeError("KNOWLEDGE_RELEASE_VECTOR_MISSING")
    return actual


def search_sqlite_chunks(
    connection: sqlite3.Connection, query: str, *, limit: int = 5
) -> list[ChunkSearchResult]:
    if not query.strip() or limit < 1:
        return []
    state = connection.execute(
        """
        SELECT r.active_release_id, k.embedding_dimension
        FROM knowledge_runtime_state r
        JOIN knowledge_release k ON k.release_id=r.active_release_id
        WHERE r.state_key='ACTIVE' AND k.status='READY'
        """
    ).fetchone()
    if state is None:
        return []
    release_id, dimension = str(state[0]), int(state[1])
    query_vector = deterministic_embedding(f"query: {query}", dimension)
    rows = connection.execute(
        """
        SELECT chunk_id,document_id,concept_id,facet,content,embedding_vector_json
        FROM knowledge_chunk
        WHERE release_id=? AND embedding_model=(
          SELECT embedding_model FROM knowledge_release WHERE release_id=?
        ) AND embedding_version=(
          SELECT embedding_version FROM knowledge_release WHERE release_id=?
        )
        """,
        (release_id, release_id, release_id),
    ).fetchall()
    scored = [
        ChunkSearchResult(
            chunk_id=str(row[0]),
            document_id=str(row[1]),
            concept_id=str(row[2]),
            facet=str(row[3]),
            content=str(row[4]),
            score=cosine_similarity(query_vector, json.loads(str(row[5]))),
        )
        for row in rows
        if row[5] is not None
    ]
    return sorted(scored, key=lambda item: (-item.score, item.chunk_id))[:limit]
