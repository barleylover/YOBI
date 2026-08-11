#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from array import array
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.seed_data import CATALOG_VERSION, build_seed
from app.knowledge.authoring import (
    CompiledKnowledgeRelease,
    reembed_release,
)
from app.knowledge.catalog_seed import (
    KNOWLEDGE_CATALOG_VERSION,
    KNOWLEDGE_RELEASE_ID,
    build_knowledge_catalog_seed,
)
from app.knowledge.oracle_store import load_oracle_release
from app.rag.providers import choose_embedding_provider

if TYPE_CHECKING:
    TableKey = str | tuple[str, ...]
    EmbeddingProviderChoice = Literal["auto", "oci", "deterministic"] | None
else:
    TableKey = Any
    EmbeddingProviderChoice = Any

TABLE_ORDER: list[tuple[str, TableKey, str]] = [
    ("service_area", "service_area_id", "service_areas"),
    ("menu_category", "category_id", "menu_categories"),
    ("merchant", "merchant_id", "merchants"),
    ("menu", "menu_id", "menus"),
    ("menu_knowledge", "knowledge_id", "knowledge"),
    ("evidence", "evidence_id", "evidence"),
    ("review_snippet", "snippet_id", "reviews"),
    ("menu_option_group", "option_group_id", "option_groups"),
    ("menu_option_item", "option_item_id", "option_items"),
    ("ingredient", "ingredient_id", "ingredients"),
    ("menu_ingredient", ("menu_id", "ingredient_id"), "menu_ingredients"),
    ("allergen", "allergen_id", "allergens"),
    ("menu_allergen", ("menu_id", "allergen_id"), "menu_allergens"),
    ("dietary_attribute", "attribute_id", "dietary_attributes"),
    (
        "menu_dietary_attribute",
        ("menu_id", "attribute_id"),
        "menu_dietary_attributes",
    ),
    (
        "option_dietary_conflict",
        ("option_item_id", "rule_code"),
        "option_dietary_conflicts",
    ),
    ("address_place", "place_id", "hotels"),
]

KNOWLEDGE_SUPPLEMENTAL_TABLES: list[tuple[str, TableKey, str]] = [
    ("menu_concept_map", ("release_id", "menu_id"), "menu_concept_maps"),
    (
        "merchant_origin_declaration",
        ("release_id", "declaration_id"),
        "merchant_origin_declarations",
    ),
    (
        "merchant_ingredient",
        ("release_id", "merchant_id", "ingredient_id", "declaration_id"),
        "merchant_ingredients",
    ),
    (
        "option_ingredient_effect",
        ("release_id", "option_item_id", "ingredient_id", "effect"),
        "option_ingredient_effects",
    ),
]

EXPECTED_COUNTS = {
    "merchants": 60,
    "menus": 600,
    "knowledge": 600,
    "evidence": 1200,
    "reviews": 2400,
    "option_groups": 1202,
    "option_items": 2405,
    "hotels": 20,
    "service_areas": 3,
    "menu_categories": 100,
    "dietary_attributes": 20,
    "menu_dietary_attributes": 1217,
    "allergens": 10,
    "menu_allergens": 595,
    "ingredients": 54,
    "menu_ingredients": 565,
    "option_dietary_conflicts": 1,
}

EXPECTED_KNOWLEDGE_COUNTS = {
    "concepts": 102,
    "relations": 100,
    "closure": 281,
    "claims": 1997,
    "documents": 102,
    "chunks": 918,
    "menu_mappings": 600,
    "origin_declarations": 13,
    "merchant_ingredients": 119,
    "option_effects": 4,
}

MENU_RELATION_TABLES = {
    "menu_ingredient": ("menu_ingredients", "ingredient_id"),
    "menu_allergen": ("menu_allergens", "allergen_id"),
    "menu_dietary_attribute": ("menu_dietary_attributes", "attribute_id"),
}


class PreparedSeed:
    def __init__(
        self,
        *,
        seed: dict[str, list[dict[str, Any]]],
        provider: Any,
        menu_vectors: list[list[float]],
        review_vectors: list[list[float]],
        knowledge_vectors: list[list[float]],
        compiled_knowledge: CompiledKnowledgeRelease,
    ) -> None:
        self.seed = seed
        self.provider = provider
        self.menu_vectors = menu_vectors
        self.review_vectors = review_vectors
        self.knowledge_vectors = knowledge_vectors
        self.compiled_knowledge = compiled_knowledge


def _merge(
    cursor: oracledb.Cursor,
    table: str,
    key: str | tuple[str, ...],
    row: dict[str, Any],
) -> None:
    keys = (key,) if isinstance(key, str) else key
    columns = list(row)
    updates = [column for column in columns if column not in keys]
    source_columns = ", ".join(f":{column} AS {column}" for column in keys)
    match = " AND ".join(f"target.{column} = source.{column}" for column in keys)
    sql = f"""
        MERGE INTO {table} target
        USING (SELECT {source_columns} FROM dual) source
        ON ({match})
        WHEN MATCHED THEN UPDATE SET {", ".join(f"target.{c} = :{c}" for c in updates)}
        WHEN NOT MATCHED THEN INSERT ({", ".join(columns)})
        VALUES ({", ".join(":" + c for c in columns)})
    """
    cursor.execute(sql, row)


def _delete_stale_menu_relation_rows(
    cursor: oracledb.Cursor,
    *,
    table: str,
    value_column: str,
    menu_ids: list[str],
    rows: list[dict[str, Any]],
) -> None:
    """Delete relation keys retired from deterministic seed menus, not whole tables."""

    allowed_by_menu: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        allowed_by_menu[str(row["menu_id"])].append(str(row[value_column]))
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for menu_id in menu_ids:
        allowed = tuple(sorted(set(allowed_by_menu[menu_id])))
        grouped[len(allowed)].append(
            {
                "menu_id": menu_id,
                **{f"allowed_{index}": value for index, value in enumerate(allowed)},
            }
        )
    for allowed_count, parameters in grouped.items():
        absent_clause = (
            f" AND {value_column} NOT IN "
            f"({','.join(f':allowed_{index}' for index in range(allowed_count))})"
            if allowed_count
            else ""
        )
        cursor.executemany(
            f"DELETE FROM {table} WHERE menu_id=:menu_id{absent_clause}",
            parameters,
        )


def _delete_stale_option_conflicts(
    cursor: oracledb.Cursor,
    *,
    menu_ids: list[str],
    rows: list[dict[str, Any]],
) -> None:
    allowed = sorted(
        {
            (str(row["option_item_id"]), str(row["rule_code"]))
            for row in rows
        }
    )
    allowed_clause = (
        " AND NOT ("
        + " OR ".join(
            f"(conflict.option_item_id=:allowed_item_{index} "
            f"AND conflict.rule_code=:allowed_rule_{index})"
            for index in range(len(allowed))
        )
        + ")"
        if allowed
        else ""
    )
    shared_allowed = {
        bind: value
        for index, pair in enumerate(allowed)
        for bind, value in (
            (f"allowed_item_{index}", pair[0]),
            (f"allowed_rule_{index}", pair[1]),
        )
    }
    cursor.executemany(
        """
        DELETE FROM option_dietary_conflict conflict
        WHERE EXISTS (
          SELECT 1
          FROM menu_option_item item
          JOIN menu_option_group option_group
            ON option_group.option_group_id=item.option_group_id
          WHERE item.option_item_id=conflict.option_item_id
            AND option_group.menu_id=:menu_id
        )
        """
        + allowed_clause,
        [{"menu_id": menu_id, **shared_allowed} for menu_id in menu_ids],
    )


def _prune_stale_catalog_dimensions(
    cursor: oracledb.Cursor,
    seed: dict[str, list[dict[str, Any]]],
) -> None:
    """Prune retired dimensions only when no runtime or historical release still needs them."""

    for table, id_column, seed_key, references in (
        (
            "menu_category",
            "category_id",
            "menu_categories",
            ("SELECT 1 FROM menu WHERE menu.category_id=target.category_id",),
        ),
        (
            "ingredient",
            "ingredient_id",
            "ingredients",
            (
                (
                    "SELECT 1 FROM menu_ingredient fact "
                    "WHERE fact.ingredient_id=target.ingredient_id"
                ),
                (
                    "SELECT 1 FROM concept_claim claim "
                    "WHERE claim.ingredient_id=target.ingredient_id"
                ),
                (
                    "SELECT 1 FROM merchant_ingredient fact "
                    "WHERE fact.ingredient_id=target.ingredient_id"
                ),
                (
                    "SELECT 1 FROM option_ingredient_effect effect "
                    "WHERE effect.ingredient_id=target.ingredient_id"
                ),
            ),
        ),
        (
            "allergen",
            "allergen_id",
            "allergens",
            (
                (
                    "SELECT 1 FROM menu_allergen fact "
                    "WHERE fact.allergen_id=target.allergen_id"
                ),
                (
                    "SELECT 1 FROM concept_claim claim "
                    "WHERE claim.allergen_id=target.allergen_id"
                ),
            ),
        ),
        (
            "dietary_attribute",
            "attribute_id",
            "dietary_attributes",
            (
                (
                    "SELECT 1 FROM menu_dietary_attribute fact "
                    "WHERE fact.attribute_id=target.attribute_id"
                ),
                (
                    "SELECT 1 FROM concept_claim claim "
                    "WHERE claim.attribute_id=target.attribute_id"
                ),
            ),
        ),
    ):
        allowed = {
            f"allowed_{index}": str(row[id_column])
            for index, row in enumerate(seed[seed_key])
        }
        reference_guards = "".join(
            f" AND NOT EXISTS ({reference})" for reference in references
        )
        cursor.execute(
            f"DELETE FROM {table} target WHERE target.{id_column} NOT IN "
            f"({','.join(':' + bind for bind in allowed)}){reference_guards}",
            allowed,
        )


def _json_value(value: Any) -> Any:
    raw = value.read() if hasattr(value, "read") else value
    return json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw


def _batch_embeddings(
    provider: Any, texts: list[str], mode: str, batch_size: int = 32
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(provider.embed(texts[start : start + batch_size], mode))
    return vectors


def verify(connection: oracledb.Connection) -> dict[str, Any]:
    cursor = connection.cursor()
    counts = {}
    for table, _, seed_key in TABLE_ORDER:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        counts[seed_key] = int(cursor.fetchone()[0])
    cursor.execute("SELECT COUNT(*) FROM menu WHERE embedding_vector IS NULL")
    null_vectors = int(cursor.fetchone()[0])
    cursor.execute("SELECT COUNT(*) FROM review_snippet WHERE embedding_vector IS NULL")
    null_review_vectors = int(cursor.fetchone()[0])
    cursor.execute("SELECT COUNT(*) FROM menu_knowledge WHERE embedding_vector IS NULL")
    null_knowledge_vectors = int(cursor.fetchone()[0])
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
        WHERE g.min_select<0 OR g.max_select<g.min_select
          OR (g.required=1 AND g.min_select<1)
          OR (SELECT COUNT(*) FROM menu_option_item i
              WHERE i.option_group_id=g.option_group_id
                AND i.availability='AVAILABLE') < g.min_select
        """
    )
    missing_required = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT release.release_id,release.catalog_version,release.manifest_sha256,
               release.status,release.expected_counts_json,release.actual_counts_json,
               release.embedding_model,
               release.embedding_dimension,release.embedding_version
        FROM knowledge_runtime_state state
        JOIN knowledge_release release ON release.release_id=state.active_release_id
        WHERE state.state_key='ACTIVE'
        """
    )
    active_knowledge = cursor.fetchone()
    knowledge_ready = bool(active_knowledge and active_knowledge[3] == "READY")
    active_release_id = str(active_knowledge[0]) if active_knowledge else None
    expected_counts = _json_value(active_knowledge[4]) if active_knowledge else {}
    declared_actual_counts = _json_value(active_knowledge[5]) if active_knowledge else {}
    knowledge_counts: dict[str, int] = {}
    for key, table in (
        ("concepts", "dish_concept"),
        ("relations", "dish_relation"),
        ("closure", "dish_concept_closure"),
        ("claims", "concept_claim"),
        ("documents", "knowledge_document"),
        ("chunks", "knowledge_chunk"),
        ("menu_mappings", "menu_concept_map"),
        ("origin_declarations", "merchant_origin_declaration"),
        ("merchant_ingredients", "merchant_ingredient"),
        ("option_effects", "option_ingredient_effect"),
    ):
        cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE release_id=:release_id",
            release_id=active_release_id or "none",
        )
        knowledge_counts[key] = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT COUNT(*) FROM knowledge_chunk
        WHERE release_id=:release_id AND embedding_vector IS NULL
        """,
        release_id=active_release_id or "none",
    )
    null_knowledge_chunk_vectors = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT COUNT(*) FROM knowledge_chunk
        WHERE release_id=:release_id AND (
          embedding_model<>:model OR embedding_dimension<>:dimension
          OR embedding_version<>:version
        )
        """,
        release_id=active_release_id or "none",
        model=str(active_knowledge[6]) if active_knowledge else "none",
        dimension=int(active_knowledge[7]) if active_knowledge else 1536,
        version=str(active_knowledge[8]) if active_knowledge else "none",
    )
    incompatible_knowledge_chunk_metadata = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT embedding_model,embedding_dimension,embedding_version,COUNT(*)
        FROM menu GROUP BY embedding_model,embedding_dimension,embedding_version
        """
    )
    menu_embedding_metadata = [
        {
            "model": str(row[0]) if row[0] is not None else None,
            "dimension": int(row[1]) if row[1] is not None else None,
            "version": str(row[2]) if row[2] is not None else None,
            "count": int(row[3]),
        }
        for row in cursor.fetchall()
    ]
    return {
        "catalog_version": CATALOG_VERSION,
        "counts": counts,
        "null_menu_vectors": null_vectors,
        "null_review_vectors": null_review_vectors,
        "null_knowledge_vectors": null_knowledge_vectors,
        "canonical_ready": canonical,
        "required_groups_without_items": missing_required,
        "knowledge_ready": knowledge_ready,
        "knowledge_release_id": active_release_id,
        "knowledge_catalog_version": str(active_knowledge[1]) if active_knowledge else None,
        "knowledge_manifest_sha256": str(active_knowledge[2]) if active_knowledge else None,
        "knowledge_expected_counts": expected_counts,
        "knowledge_declared_actual_counts": declared_actual_counts,
        "knowledge_embedding_model": str(active_knowledge[6]) if active_knowledge else None,
        "knowledge_embedding_dimension": int(active_knowledge[7]) if active_knowledge else None,
        "knowledge_embedding_version": str(active_knowledge[8]) if active_knowledge else None,
        "knowledge_counts": knowledge_counts,
        "null_knowledge_chunk_vectors": null_knowledge_chunk_vectors,
        "incompatible_knowledge_chunk_metadata": incompatible_knowledge_chunk_metadata,
        "menu_embedding_metadata": menu_embedding_metadata,
    }


def validate(result: dict[str, Any]) -> None:
    if result.get("counts") != EXPECTED_COUNTS:
        raise RuntimeError("SEED_COUNT_INTEGRITY_FAILED")
    if result.get("null_menu_vectors") != 0:
        raise RuntimeError("SEED_MENU_VECTOR_INTEGRITY_FAILED")
    if result.get("null_review_vectors") != 0:
        raise RuntimeError("SEED_REVIEW_VECTOR_INTEGRITY_FAILED")
    if result.get("null_knowledge_vectors") != 0:
        raise RuntimeError("SEED_KNOWLEDGE_VECTOR_INTEGRITY_FAILED")
    if result.get("canonical_ready") is not True:
        raise RuntimeError("SEED_CANONICAL_INTEGRITY_FAILED")
    if result.get("required_groups_without_items") != 0:
        raise RuntimeError("SEED_REQUIRED_OPTIONS_INTEGRITY_FAILED")
    if result.get("knowledge_ready") is not True:
        raise RuntimeError("SEED_KNOWLEDGE_RELEASE_NOT_READY")
    if (
        result.get("knowledge_release_id") != KNOWLEDGE_RELEASE_ID
        or result.get("knowledge_catalog_version") != KNOWLEDGE_CATALOG_VERSION
        or len(str(result.get("knowledge_manifest_sha256") or "")) != 64
    ):
        raise RuntimeError("SEED_KNOWLEDGE_RELEASE_IDENTITY_FAILED")
    if result.get("knowledge_counts") != EXPECTED_KNOWLEDGE_COUNTS:
        raise RuntimeError("SEED_KNOWLEDGE_COUNT_INTEGRITY_FAILED")
    observed_release_counts = {
        key: result["knowledge_counts"][key]
        for key in ("concepts", "relations", "closure", "claims", "documents", "chunks")
    }
    if not (
        result.get("knowledge_expected_counts")
        == result.get("knowledge_declared_actual_counts")
        == observed_release_counts
    ):
        raise RuntimeError("SEED_KNOWLEDGE_DECLARED_COUNT_MISMATCH")
    if result.get("null_knowledge_chunk_vectors") != 0:
        raise RuntimeError("SEED_KNOWLEDGE_VECTOR_INTEGRITY_FAILED")
    if result.get("incompatible_knowledge_chunk_metadata") != 0:
        raise RuntimeError("SEED_KNOWLEDGE_EMBEDDING_COMPATIBILITY_FAILED")
    if result.get("knowledge_embedding_dimension") != 1536:
        raise RuntimeError("SEED_KNOWLEDGE_EMBEDDING_COMPATIBILITY_FAILED")


def validate_runtime_embedding(result: dict[str, Any], provider: Any) -> None:
    if (
        result.get("knowledge_embedding_model") != provider.model
        or result.get("knowledge_embedding_dimension") != provider.dimension
        or result.get("knowledge_embedding_version") != provider.version
    ):
        raise RuntimeError("SEED_KNOWLEDGE_EMBEDDING_COMPATIBILITY_FAILED")
    if result.get("menu_embedding_metadata") != [
        {
            "model": provider.model,
            "dimension": provider.dimension,
            "version": provider.version,
            "count": EXPECTED_COUNTS["menus"],
        }
    ]:
        raise RuntimeError("SEED_MENU_EMBEDDING_COMPATIBILITY_FAILED")


def prepare_seed(settings: Settings, embedding_provider: EmbeddingProviderChoice) -> PreparedSeed:
    """Build every deterministic row and external embedding before opening a DB transaction."""

    seed = build_seed()
    provider = choose_embedding_provider(settings, embedding_provider)
    menu_vectors = _batch_embeddings(
        provider,
        [row["semantic_text"] for row in seed["menus"]],
        "SEARCH_DOCUMENT",
    )
    review_vectors = _batch_embeddings(
        provider,
        [row["review_text"] for row in seed["reviews"]],
        "SEARCH_DOCUMENT",
    )
    knowledge_vectors = _batch_embeddings(
        provider,
        [row["embedding_text"] for row in seed["knowledge"]],
        "SEARCH_DOCUMENT",
    )
    catalog = build_knowledge_catalog_seed(seed["menus"])
    chunk_vectors = _batch_embeddings(
        provider,
        [row["embedding_text"] for row in catalog.compiled_release.chunks],
        "SEARCH_DOCUMENT",
    )
    for rows, vectors in (
        (seed["menus"], menu_vectors),
        (seed["reviews"], review_vectors),
        (seed["knowledge"], knowledge_vectors),
        (catalog.compiled_release.chunks, chunk_vectors),
    ):
        if len(rows) != len(vectors) or any(len(vector) != provider.dimension for vector in vectors):
            raise RuntimeError("SEED_EMBEDDING_COUNT_OR_DIMENSION_MISMATCH")

    compiled = reembed_release(
        catalog.compiled_release,
        chunk_vectors,
        model=provider.model,
        dimension=provider.dimension,
        version=provider.version,
    )
    supplemental_release_ids = {
        str(row["release_id"])
        for _, _, seed_key in KNOWLEDGE_SUPPLEMENTAL_TABLES
        for row in seed[seed_key]
    }
    if supplemental_release_ids != {compiled.release_id}:
        raise RuntimeError("SEED_KNOWLEDGE_RELEASE_ID_MISMATCH")
    return PreparedSeed(
        seed=seed,
        provider=provider,
        menu_vectors=menu_vectors,
        review_vectors=review_vectors,
        knowledge_vectors=knowledge_vectors,
        compiled_knowledge=compiled,
    )


def _apply_seed_transaction(
    connection: oracledb.Connection,
    prepared: PreparedSeed,
    *,
    fresh: bool,
) -> dict[str, Any]:
    """Apply base catalog, vectors, and knowledge release without committing."""

    cursor = connection.cursor()
    seed = prepared.seed
    provider = prepared.provider
    if fresh:
        for table in (
            "knowledge_runtime_state",
            "merchant_ingredient",
            "merchant_origin_declaration",
            "option_ingredient_effect",
            "menu_concept_map",
            "knowledge_chunk",
            "knowledge_document",
            "concept_claim",
            "dish_concept_closure",
            "dish_relation",
            "dish_concept",
            "knowledge_release",
        ):
            cursor.execute(f"DELETE FROM {table}")
        for table, _, _ in reversed(TABLE_ORDER):
            cursor.execute(f"DELETE FROM {table}")

    menu_ids = [str(row["menu_id"]) for row in seed["menus"]]
    for table, (seed_key, value_column) in MENU_RELATION_TABLES.items():
        _delete_stale_menu_relation_rows(
            cursor,
            table=table,
            value_column=value_column,
            menu_ids=menu_ids,
            rows=seed[seed_key],
        )
    _delete_stale_option_conflicts(
        cursor,
        menu_ids=menu_ids,
        rows=seed["option_dietary_conflicts"],
    )

    for table, key_column, seed_key in TABLE_ORDER:
        for row in seed[seed_key]:
            _merge(cursor, table, key_column, row)

    for row, vector in zip(seed["menus"], prepared.menu_vectors):
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
    for row, vector in zip(seed["reviews"], prepared.review_vectors):
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
    for row, vector in zip(seed["knowledge"], prepared.knowledge_vectors):
        cursor.execute(
            """
            UPDATE menu_knowledge SET embedding_vector = :vector, embedding_model = :model,
              embedding_dimension = :dimension, embedding_version = :version
            WHERE knowledge_id = :knowledge_id
            """,
            vector=array("f", vector),
            model=provider.model,
            dimension=provider.dimension,
            version=provider.version,
            knowledge_id=row["knowledge_id"],
        )

    load_oracle_release(connection, prepared.compiled_knowledge)
    for table, key_column, seed_key in KNOWLEDGE_SUPPLEMENTAL_TABLES:
        for row in seed[seed_key]:
            _merge(cursor, table, key_column, row)
    _prune_stale_catalog_dimensions(cursor, seed)
    result = verify(connection)
    result["embedding_provider"] = provider.model
    validate(result)
    validate_runtime_embedding(result, provider)
    return result


def apply_seed(
    connection: oracledb.Connection,
    prepared: PreparedSeed,
    *,
    fresh: bool,
) -> dict[str, Any]:
    """Commit exactly once after all seed writes and integrity checks, otherwise roll back."""

    try:
        result = _apply_seed_transaction(connection, prepared, fresh=fresh)
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fresh", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument("--upsert", action="store_true", help="Explicit name for the default mode")
    parser.add_argument(
        "--embedding-provider",
        choices=["auto", "oci", "deterministic"],
        default=None,
        help="Override EMBEDDING_PROVIDER; production deployments should use an explicit pin",
    )
    args = parser.parse_args()
    settings = Settings()
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise SystemExit("ADB_DSN and DB_PASSWORD are required")

    if args.verify_only:
        with oracledb.connect(
            user=settings.db_username,
            password=password,
            dsn=dsn,
        ) as connection:
            result = verify(connection)
            validate(result)
    else:
        prepared = prepare_seed(settings, args.embedding_provider)
        with oracledb.connect(
            user=settings.db_username,
            password=password,
            dsn=dsn,
        ) as connection:
            result = apply_seed(connection, prepared, fresh=args.fresh)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
