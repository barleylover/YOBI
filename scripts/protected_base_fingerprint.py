from __future__ import annotations

import hashlib
import sqlite3

import oracledb

PROTECTED_BASE_TABLES = (
    "menu",
    "menu_source_detail",
    "menu_wiki_eligibility",
    "menu_embedding",
    "menu_semantic_embedding",
    "knowledge_document",
    "knowledge_chunk",
    "menu_concept_membership",
    "menu_dietary_attribute",
    "option_dietary_conflict",
    "option_ingredient_effect",
)


def protected_base_fingerprint(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    existing = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table in PROTECTED_BASE_TABLES:
        if table not in existing:
            continue
        columns = [
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        ]
        digest.update(f"{table}:{','.join(columns)}\n".encode())
        order_by = ",".join(f'"{column}"' for column in columns)
        for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY {order_by}'):
            for value in row:
                digest.update(value if isinstance(value, bytes) else str(value).encode())
                digest.update(b"\x1f")
            digest.update(b"\x1e")
    return digest.hexdigest()


ORACLE_ID_COLUMNS = {
    "menu": ("menu_id",),
    "menu_source_detail": ("menu_id",),
    "menu_wiki_eligibility": ("knowledge_release_id", "menu_id"),
    "menu_embedding": ("menu_id",),
    "menu_semantic_embedding": (
        "catalog_release_id",
        "menu_id",
        "embedding_model",
        "embedding_version",
    ),
    "knowledge_document": ("release_id", "document_id"),
    "knowledge_chunk": ("release_id", "chunk_id"),
    "menu_concept_membership": ("knowledge_release_id", "menu_id", "concept_id"),
    "menu_dietary_attribute": ("menu_id", "attribute_id"),
    "option_dietary_conflict": ("option_item_id", "rule_code"),
    "option_ingredient_effect": (
        "release_id",
        "option_item_id",
        "ingredient_id",
        "effect",
    ),
}


def oracle_base_fingerprint(connection: oracledb.Connection) -> str:
    """Hash stable identifiers and row counts without materializing vector LOBs."""

    digest = hashlib.sha256()
    cursor = connection.cursor()
    cursor.execute("SELECT LOWER(table_name) FROM user_tables")
    existing = {str(row[0]) for row in cursor.fetchall()}
    for table in PROTECTED_BASE_TABLES:
        if table not in existing:
            continue
        id_columns = ORACLE_ID_COLUMNS[table]
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        digest.update(f"{table}:{int(cursor.fetchone()[0])}\n".encode())
        cursor.execute(
            f"SELECT {','.join(id_columns)} FROM {table} "
            f"ORDER BY {','.join(id_columns)}"
        )
        for row in cursor:
            digest.update("\x1f".join(str(value) for value in row).encode("utf-8"))
            digest.update(b"\x1e")
    return digest.hexdigest()
