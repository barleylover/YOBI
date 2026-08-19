#!/usr/bin/env python3
"""Build an immutable OCI menu-vector set without replacing catalog rows.

The script is intentionally separate from the destructive catalog importer.
It reads one active external catalog, computes all vectors before DML, and then
inserts exactly one immutable set keyed by catalog release and provider identity.
It never updates ``menu`` or either active release pointer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from array import array
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.rag.providers import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    OCIEmbeddingProvider,
)

VECTOR_BATCH_SIZE = OCIEmbeddingProvider.max_inputs_per_request
DML_BATCH_SIZE = 250


def _text(value: Any) -> str:
    if hasattr(value, "read"):
        return str(value.read())
    return str(value)


def semantic_text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def embedding_manifest_sha256(
    *,
    catalog_release_id: str,
    provider: EmbeddingProvider,
    rows: Sequence[tuple[str, str]],
) -> str:
    digest = hashlib.sha256()
    header = {
        "catalog_release_id": catalog_release_id,
        "embedding_dimension": provider.dimension,
        "embedding_model": provider.model,
        "embedding_version": provider.version,
        "menu_count": len(rows),
    }
    digest.update(
        json.dumps(header, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    digest.update(b"\n")
    for menu_id, semantic_text in rows:
        digest.update(menu_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(semantic_text_sha256(semantic_text).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def prepare_vector_cache(
    rows: Sequence[tuple[str, str]],
    provider: EmbeddingProvider,
    *,
    dispatch_interval_seconds: float = 0.0,
) -> tuple[Path, int, int]:
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix="yobi-menu-semantic-", suffix=".f32"
    )
    cache_path = Path(raw_path)
    vector_count = 0
    dispatch_count = 0
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            for offset in range(0, len(rows), VECTOR_BATCH_SIZE):
                if dispatch_count and dispatch_interval_seconds:
                    time.sleep(dispatch_interval_seconds)
                texts = [text for _menu_id, text in rows[offset : offset + VECTOR_BATCH_SIZE]]
                vectors = provider.embed(texts, "SEARCH_DOCUMENT")
                dispatch_count += 1
                if len(vectors) != len(texts):
                    raise RuntimeError("MENU_EMBEDDING_VECTOR_COUNT_MISMATCH")
                for vector in vectors:
                    if len(vector) != provider.dimension:
                        raise RuntimeError("MENU_EMBEDDING_DIMENSION_MISMATCH")
                    array("f", vector).tofile(handle)
                    vector_count += 1
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        cache_path.unlink(missing_ok=True)
        raise
    expected_size = vector_count * provider.dimension * array("f").itemsize
    if cache_path.stat().st_size != expected_size:
        cache_path.unlink(missing_ok=True)
        raise RuntimeError("MENU_EMBEDDING_CACHE_SIZE_MISMATCH")
    return cache_path, vector_count, dispatch_count


def _connect(settings: Settings) -> oracledb.Connection:
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise RuntimeError("ADB_DSN_AND_DB_PASSWORD_REQUIRED")
    connection = oracledb.connect(
        user=settings.db_username,
        password=password,
        dsn=dsn,
    )
    cursor = connection.cursor()
    cursor.execute("SELECT SYS_CONTEXT('USERENV','CURRENT_USER') FROM dual")
    current_user = str(cursor.fetchone()[0])
    if current_user.upper() != settings.db_username.upper() or current_user.upper() == "ADMIN":
        connection.close()
        raise RuntimeError("ORACLE_RUNTIME_USER_MISMATCH")
    cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version='014'")
    if int(cursor.fetchone()[0]) != 1:
        connection.close()
        raise RuntimeError("MIGRATION_014_NOT_APPLIED")
    return connection


def _active_catalog_snapshot(
    connection: oracledb.Connection,
    *,
    lock: bool = False,
) -> tuple[str, str, list[tuple[str, str]]]:
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT catalog_import_id,catalog_release_id
        FROM catalog_import_batch
        WHERE status='ACTIVE' AND data_origin='YOGIYO_PUBLIC_WEB'
        ORDER BY completed_at DESC FETCH FIRST 1 ROWS ONLY
        """
    )
    catalog = cursor.fetchone()
    if catalog is None:
        raise RuntimeError("ACTIVE_EXTERNAL_CATALOG_REQUIRED")
    catalog_import_id = str(catalog[0])
    catalog_release_id = str(catalog[1])
    if lock:
        cursor.execute(
            """
            SELECT catalog_import_id FROM catalog_import_batch
            WHERE catalog_import_id=:catalog_import_id AND status='ACTIVE'
            FOR UPDATE
            """,
            catalog_import_id=catalog_import_id,
        )
        if cursor.fetchone() is None:
            raise RuntimeError("ACTIVE_CATALOG_CHANGED_DURING_EMBEDDING_BUILD")
    cursor.execute(
        """
        SELECT menu_id,semantic_text FROM menu
        WHERE catalog_import_id=:catalog_import_id
        ORDER BY menu_id
        """,
        catalog_import_id=catalog_import_id,
    )
    rows = [(str(row[0]), _text(row[1])) for row in cursor.fetchall()]
    if not rows or any(not value.strip() for _menu_id, value in rows):
        raise RuntimeError("ACTIVE_CATALOG_SEMANTIC_TEXT_INCOMPLETE")
    return catalog_import_id, catalog_release_id, rows


def _existing_set(
    connection: oracledb.Connection,
    *,
    catalog_release_id: str,
    provider: EmbeddingProvider,
) -> dict[str, Any]:
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(*),COUNT(DISTINCT menu_id),
               COUNT(DISTINCT embedding_manifest_sha256),
               MIN(embedding_manifest_sha256),
               SUM(CASE WHEN embedding_vector IS NULL
                          OR LENGTH(semantic_text_sha256)<>64
                          OR LENGTH(embedding_manifest_sha256)<>64
                        THEN 1 ELSE 0 END)
        FROM menu_semantic_embedding
        WHERE catalog_release_id=:catalog_release_id
          AND embedding_model=:embedding_model
          AND embedding_version=:embedding_version
          AND embedding_dimension=:embedding_dimension
        """,
        catalog_release_id=catalog_release_id,
        embedding_model=provider.model,
        embedding_version=provider.version,
        embedding_dimension=provider.dimension,
    )
    row = cursor.fetchone()
    return {
        "row_count": int(row[0] or 0),
        "menu_count": int(row[1] or 0),
        "manifest_count": int(row[2] or 0),
        "manifest_sha256": str(row[3]) if row[3] else None,
        "invalid_count": int(row[4] or 0),
    }


def _semantic_text_hash_mismatch_count(
    connection: oracledb.Connection,
    *,
    catalog_release_id: str,
    provider: EmbeddingProvider,
    rows: Sequence[tuple[str, str]],
) -> int:
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT menu_id,semantic_text_sha256
        FROM menu_semantic_embedding
        WHERE catalog_release_id=:catalog_release_id
          AND embedding_model=:embedding_model
          AND embedding_version=:embedding_version
          AND embedding_dimension=:embedding_dimension
        ORDER BY menu_id
        """,
        catalog_release_id=catalog_release_id,
        embedding_model=provider.model,
        embedding_version=provider.version,
        embedding_dimension=provider.dimension,
    )
    stored = {str(row[0]): str(row[1]) for row in cursor.fetchall()}
    expected = {menu_id: semantic_text_sha256(text) for menu_id, text in rows}
    return len(set(stored) ^ set(expected)) + sum(
        stored[menu_id] != expected[menu_id] for menu_id in set(stored) & set(expected)
    )


def _runtime_pointers(connection: oracledb.Connection) -> tuple[str | None, str | None]:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT active_release_id FROM knowledge_runtime_state WHERE state_key='ACTIVE'"
    )
    knowledge = cursor.fetchone()
    cursor.execute(
        "SELECT active_release_family_id FROM recommendation_runtime_state "
        "WHERE state_key='ACTIVE'"
    )
    recommendation = cursor.fetchone()
    return (
        str(knowledge[0]) if knowledge else None,
        str(recommendation[0]) if recommendation else None,
    )


def apply_embedding_set(
    settings: Settings,
    provider: EmbeddingProvider,
    *,
    expected_catalog_release_id: str | None = None,
    dispatch_interval_seconds: float = 0.0,
) -> dict[str, Any]:
    with _connect(settings) as read_connection:
        _catalog_import_id, catalog_release_id, rows = _active_catalog_snapshot(
            read_connection
        )
        if expected_catalog_release_id and catalog_release_id != expected_catalog_release_id:
            raise RuntimeError("CATALOG_RELEASE_ID_MISMATCH")
        manifest = embedding_manifest_sha256(
            catalog_release_id=catalog_release_id,
            provider=provider,
            rows=rows,
        )
        existing = _existing_set(
            read_connection,
            catalog_release_id=catalog_release_id,
            provider=provider,
        )
        semantic_hash_mismatches = _semantic_text_hash_mismatch_count(
            read_connection,
            catalog_release_id=catalog_release_id,
            provider=provider,
            rows=rows,
        )
    if existing["row_count"]:
        if (
            existing["row_count"] == len(rows)
            and existing["menu_count"] == len(rows)
            and existing["manifest_count"] == 1
            and existing["manifest_sha256"] == manifest
            and existing["invalid_count"] == 0
            and semantic_hash_mismatches == 0
        ):
            return {
                "status": "PASS",
                "operation": "ALREADY_PRESENT",
                "catalog_release_id": catalog_release_id,
                "embedding_model": provider.model,
                "embedding_version": provider.version,
                "embedding_dimension": provider.dimension,
                "embedding_manifest_sha256": manifest,
                "menu_count": len(rows),
                "semantic_text_hash_mismatch_count": 0,
                "provider_dispatch_count": 0,
                "pointers_changed": False,
            }
        raise RuntimeError("IMMUTABLE_MENU_EMBEDDING_SET_INCOMPLETE_OR_CONFLICTING")

    cache_path, vector_count, dispatch_count = prepare_vector_cache(
        rows,
        provider,
        dispatch_interval_seconds=dispatch_interval_seconds,
    )
    if vector_count != len(rows):
        cache_path.unlink(missing_ok=True)
        raise RuntimeError("MENU_EMBEDDING_VECTOR_COUNT_MISMATCH")
    try:
        with _connect(settings) as connection:
            pointers_before = _runtime_pointers(connection)
            _locked_import_id, locked_release_id, locked_rows = _active_catalog_snapshot(
                connection, lock=True
            )
            locked_manifest = embedding_manifest_sha256(
                catalog_release_id=locked_release_id,
                provider=provider,
                rows=locked_rows,
            )
            if locked_release_id != catalog_release_id or locked_manifest != manifest:
                raise RuntimeError("ACTIVE_CATALOG_CHANGED_DURING_EMBEDDING_BUILD")
            if _existing_set(
                connection,
                catalog_release_id=catalog_release_id,
                provider=provider,
            )["row_count"]:
                raise RuntimeError("MENU_EMBEDDING_SET_CREATED_CONCURRENTLY")
            cursor = connection.cursor()
            inserted = 0
            created_at = datetime.now(timezone.utc)
            with cache_path.open("rb") as vector_handle:
                payload: list[dict[str, Any]] = []
                for menu_id, semantic_text in locked_rows:
                    vector = array("f")
                    try:
                        vector.fromfile(vector_handle, provider.dimension)
                    except EOFError as exc:
                        raise RuntimeError("MENU_EMBEDDING_CACHE_TRUNCATED") from exc
                    payload.append(
                        {
                            "catalog_release_id": catalog_release_id,
                            "menu_id": menu_id,
                            "embedding_model": provider.model,
                            "embedding_version": provider.version,
                            "embedding_dimension": provider.dimension,
                            "semantic_text_sha256": semantic_text_sha256(semantic_text),
                            "embedding_manifest_sha256": manifest,
                            "embedding_vector": vector,
                            "created_at": created_at,
                        }
                    )
                    if len(payload) >= DML_BATCH_SIZE:
                        cursor.executemany(
                            """
                            INSERT INTO menu_semantic_embedding(
                              catalog_release_id,menu_id,embedding_model,embedding_version,
                              embedding_dimension,semantic_text_sha256,
                              embedding_manifest_sha256,embedding_vector,created_at
                            ) VALUES (
                              :catalog_release_id,:menu_id,:embedding_model,:embedding_version,
                              :embedding_dimension,:semantic_text_sha256,
                              :embedding_manifest_sha256,:embedding_vector,:created_at
                            )
                            """,
                            payload,
                        )
                        inserted += len(payload)
                        payload = []
                if payload:
                    cursor.executemany(
                        """
                        INSERT INTO menu_semantic_embedding(
                          catalog_release_id,menu_id,embedding_model,embedding_version,
                          embedding_dimension,semantic_text_sha256,
                          embedding_manifest_sha256,embedding_vector,created_at
                        ) VALUES (
                          :catalog_release_id,:menu_id,:embedding_model,:embedding_version,
                          :embedding_dimension,:semantic_text_sha256,
                          :embedding_manifest_sha256,:embedding_vector,:created_at
                        )
                        """,
                        payload,
                    )
                    inserted += len(payload)
                if vector_handle.read(1):
                    raise RuntimeError("MENU_EMBEDDING_CACHE_HAS_TRAILING_DATA")
            verified = _existing_set(
                connection,
                catalog_release_id=catalog_release_id,
                provider=provider,
            )
            semantic_hash_mismatches = _semantic_text_hash_mismatch_count(
                connection,
                catalog_release_id=catalog_release_id,
                provider=provider,
                rows=locked_rows,
            )
            if (
                inserted != len(rows)
                or verified["row_count"] != len(rows)
                or verified["menu_count"] != len(rows)
                or verified["manifest_count"] != 1
                or verified["manifest_sha256"] != manifest
                or verified["invalid_count"] != 0
                or semantic_hash_mismatches != 0
                or _runtime_pointers(connection) != pointers_before
            ):
                raise RuntimeError("MENU_EMBEDDING_SET_VERIFICATION_FAILED")
            connection.commit()
            pointers_changed = _runtime_pointers(connection) != pointers_before
    finally:
        cache_path.unlink(missing_ok=True)
    if pointers_changed:
        raise RuntimeError("MENU_EMBEDDING_BACKFILL_CHANGED_POINTERS")
    return {
        "status": "PASS",
        "operation": "INSERTED_IMMUTABLE_SET",
        "catalog_release_id": catalog_release_id,
        "embedding_model": provider.model,
        "embedding_version": provider.version,
        "embedding_dimension": provider.dimension,
        "embedding_manifest_sha256": manifest,
        "menu_count": len(rows),
        "semantic_text_hash_mismatch_count": 0,
        "provider_dispatch_count": dispatch_count,
        "expected_provider_dispatch_count": math.ceil(len(rows) / VECTOR_BATCH_SIZE),
        "pointers_changed": False,
    }


def verify_embedding_set(
    settings: Settings,
    provider: EmbeddingProvider,
    *,
    expected_catalog_release_id: str | None = None,
) -> dict[str, Any]:
    with _connect(settings) as connection:
        _catalog_import_id, catalog_release_id, rows = _active_catalog_snapshot(connection)
        if expected_catalog_release_id and catalog_release_id != expected_catalog_release_id:
            raise RuntimeError("CATALOG_RELEASE_ID_MISMATCH")
        manifest = embedding_manifest_sha256(
            catalog_release_id=catalog_release_id,
            provider=provider,
            rows=rows,
        )
        existing = _existing_set(
            connection,
            catalog_release_id=catalog_release_id,
            provider=provider,
        )
        semantic_hash_mismatches = _semantic_text_hash_mismatch_count(
            connection,
            catalog_release_id=catalog_release_id,
            provider=provider,
            rows=rows,
        )
    passed = bool(
        existing["row_count"] == len(rows)
        and existing["menu_count"] == len(rows)
        and existing["manifest_count"] == 1
        and existing["manifest_sha256"] == manifest
        and existing["invalid_count"] == 0
        and semantic_hash_mismatches == 0
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "operation": "VERIFY_ONLY",
        "catalog_release_id": catalog_release_id,
        "embedding_model": provider.model,
        "embedding_version": provider.version,
        "embedding_dimension": provider.dimension,
        "embedding_manifest_sha256": manifest,
        "expected_menu_count": len(rows),
        "observed_menu_count": existing["menu_count"],
        "semantic_text_hash_mismatch_count": semantic_hash_mismatches,
        "provider_dispatch_count": 0,
        "pointers_changed": False,
    }


def _provider(
    settings: Settings, requested: Literal["oci", "deterministic"]
) -> EmbeddingProvider:
    if requested == "deterministic":
        return DeterministicEmbeddingProvider()
    return OCIEmbeddingProvider(settings)


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, oracledb.DatabaseError) and exc.args:
        code = getattr(exc.args[0], "code", None)
        return f"ORACLE_{code}" if isinstance(code, int) else "ORACLE_DATABASE_ERROR"
    if type(exc).__name__ == "ServiceError" and type(exc).__module__.startswith("oci."):
        status = getattr(exc, "status", None)
        raw_code = str(getattr(exc, "code", "SERVICE_ERROR"))
        safe_code = re.sub(r"[^A-Za-z0-9]+", "_", raw_code).strip("_").upper()
        if isinstance(status, int) and safe_code:
            return f"OCI_{status}_{safe_code}"
        return "OCI_SERVICE_ERROR"
    value = str(exc)
    if value and all(character.isupper() or character.isdigit() or character == "_" for character in value):
        return value
    return type(exc).__name__.upper()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or verify an immutable, non-destructive menu semantic-vector set."
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("oci", "deterministic"),
        default="oci",
    )
    parser.add_argument("--expected-catalog-release-id")
    parser.add_argument(
        "--dispatch-interval-seconds",
        type=float,
        default=1.0,
        help="Fixed delay between OCI document batches; no automatic retry is performed.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    try:
        if not 0.0 <= args.dispatch_interval_seconds <= 60.0:
            raise RuntimeError("MENU_EMBEDDING_DISPATCH_INTERVAL_INVALID")
        settings = Settings()
        provider = _provider(settings, args.embedding_provider)
        if args.apply and settings.app_env == "production" and isinstance(
            provider, DeterministicEmbeddingProvider
        ):
            raise RuntimeError("PRODUCTION_MENU_EMBEDDING_REQUIRES_OCI")
        if args.apply:
            result = apply_embedding_set(
                settings,
                provider,
                expected_catalog_release_id=args.expected_catalog_release_id,
                dispatch_interval_seconds=args.dispatch_interval_seconds,
            )
        else:
            result = verify_embedding_set(
                settings,
                provider,
                expected_catalog_release_id=args.expected_catalog_release_id,
            )
        exit_code = 0 if result["status"] == "PASS" else 1
    except Exception as exc:  # noqa: BLE001 - print one non-secret error code
        result = {"status": "FAIL", "error_code": _safe_error_code(exc)}
        exit_code = 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
