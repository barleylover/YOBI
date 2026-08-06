#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from array import array
from pathlib import Path
from typing import Any

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.seed_data import CATALOG_VERSION, build_seed
from app.rag.providers import choose_embedding_provider

TABLE_ORDER = [
    ("merchant", "merchant_id", "merchants"),
    ("menu", "menu_id", "menus"),
    ("evidence", "evidence_id", "evidence"),
    ("review_snippet", "snippet_id", "reviews"),
    ("menu_option_group", "option_group_id", "option_groups"),
    ("menu_option_item", "option_item_id", "option_items"),
    ("address_place", "place_id", "hotels"),
]

EXPECTED_COUNTS = {
    "merchants": 30,
    "menus": 150,
    "evidence": 300,
    "reviews": 600,
    "option_groups": 302,
    "option_items": 605,
    "hotels": 20,
}


def _merge(cursor: oracledb.Cursor, table: str, key: str, row: dict[str, Any]) -> None:
    columns = list(row)
    updates = [column for column in columns if column != key]
    sql = f"""
        MERGE INTO {table} target
        USING (SELECT :{key} AS {key} FROM dual) source
        ON (target.{key} = source.{key})
        WHEN MATCHED THEN UPDATE SET {', '.join(f'target.{c} = :{c}' for c in updates)}
        WHEN NOT MATCHED THEN INSERT ({', '.join(columns)})
        VALUES ({', '.join(':' + c for c in columns)})
    """
    cursor.execute(sql, row)


def _batch_embeddings(provider: Any, texts: list[str], mode: str, batch_size: int = 32) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(provider.embed(texts[start : start + batch_size], mode))
    return vectors


def verify(connection: oracledb.Connection) -> dict[str, Any]:
    cursor = connection.cursor()
    counts = {}
    for table, _, key in TABLE_ORDER:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        counts[key] = int(cursor.fetchone()[0])
    cursor.execute("SELECT COUNT(*) FROM menu WHERE embedding_vector IS NULL")
    null_vectors = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT COUNT(*) FROM menu
        WHERE menu_id IN ('menu_001_01', 'menu_002_01', 'menu_003_01')
        """
    )
    canonical = int(cursor.fetchone()[0]) == 3
    cursor.execute(
        """
        SELECT COUNT(*) FROM menu_option_group g
        WHERE g.required = 1 AND NOT EXISTS (
          SELECT 1 FROM menu_option_item i
          WHERE i.option_group_id = g.option_group_id AND i.availability = 'AVAILABLE'
        )
        """
    )
    missing_required = int(cursor.fetchone()[0])
    return {
        "catalog_version": CATALOG_VERSION,
        "counts": counts,
        "null_menu_vectors": null_vectors,
        "canonical_ready": canonical,
        "required_groups_without_items": missing_required,
    }


def validate(result: dict[str, Any]) -> None:
    if result.get("counts") != EXPECTED_COUNTS:
        raise RuntimeError("SEED_COUNT_INTEGRITY_FAILED")
    if result.get("null_menu_vectors") != 0:
        raise RuntimeError("SEED_MENU_VECTOR_INTEGRITY_FAILED")
    if result.get("canonical_ready") is not True:
        raise RuntimeError("SEED_CANONICAL_INTEGRITY_FAILED")
    if result.get("required_groups_without_items") != 0:
        raise RuntimeError("SEED_REQUIRED_OPTIONS_INTEGRITY_FAILED")


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fresh", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument("--upsert", action="store_true", help="Explicit name for the default mode")
    parser.add_argument(
        "--embedding-provider", choices=["auto", "oci", "deterministic"], default="auto"
    )
    args = parser.parse_args()
    settings = Settings()
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise SystemExit("ADB_DSN and DB_PASSWORD are required")
    with oracledb.connect(user=settings.db_username, password=password, dsn=dsn) as connection:
        if args.verify_only:
            result = verify(connection)
            validate(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        cursor = connection.cursor()
        if args.fresh:
            for table, _, _ in reversed(TABLE_ORDER):
                cursor.execute(f"DELETE FROM {table}")
            connection.commit()

        seed = build_seed()
        for table, key_column, seed_key in TABLE_ORDER:
            for row in seed[seed_key]:
                _merge(cursor, table, key_column, row)
            connection.commit()

        provider = choose_embedding_provider(settings, args.embedding_provider)
        menu_vectors = _batch_embeddings(
            provider, [row["semantic_text"] for row in seed["menus"]], "SEARCH_DOCUMENT"
        )
        for row, vector in zip(seed["menus"], menu_vectors):
            cursor.execute(
                """
                UPDATE menu SET embedding_vector = :vector, embedding_model = :model,
                  embedding_dimension = :dimension, embedding_version = :version
                WHERE menu_id = :menu_id
                """,
                vector=array("f", vector),
                model=provider.model,
                dimension=provider.dimension,
                version=provider.version,
                menu_id=row["menu_id"],
            )
        review_vectors = _batch_embeddings(
            provider, [row["review_text"] for row in seed["reviews"]], "SEARCH_DOCUMENT"
        )
        for row, vector in zip(seed["reviews"], review_vectors):
            cursor.execute(
                """
                UPDATE review_snippet SET embedding_text = :text, embedding_vector = :vector,
                  embedding_model = :model, embedding_dimension = :dimension,
                  embedding_version = :version WHERE snippet_id = :snippet_id
                """,
                text=row["review_text"],
                vector=array("f", vector),
                model=provider.model,
                dimension=provider.dimension,
                version=provider.version,
                snippet_id=row["snippet_id"],
            )
        connection.commit()
        result = verify(connection)
        validate(result)
        result["embedding_provider"] = provider.model
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
