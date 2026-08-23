#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from array import array
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.demo_address import (
    DEMO_ADDRESS_SERVICE_AREA_ID,
    demo_address_status,
    upsert_demo_address,
)
from app.db.schema_sqlite import SCHEMA_SQL
from app.domain.preference_catalog import (
    PREFERENCE_CATALOG_VERSION,
    PREFERENCE_CATEGORIES,
    localized_spice_references,
)
from app.rag.providers import (
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    choose_embedding_provider,
)

PACKAGE_FORMAT = "yobi-external-catalog-v1"
DATA_ORIGIN = "YOGIYO_PUBLIC_WEB"
SOURCE_PLATFORM = "YOGIYO"
NORMALIZATION_CODE = "REQUIRED_SINGLE_SELECT_ZERO_LIMIT"
SPICE_REFERENCE_VERSION = f"{PREFERENCE_CATALOG_VERSION}-spice"
# OCI Cohere Embed 4 accepts up to 96 text inputs per request. Keeping the
# importer on that boundary reduces a 15,085-menu rebuild from 236 to 158
# provider dispatches without changing document order or vector identity.
VECTOR_BATCH_SIZE = 96
DML_BATCH_SIZE = 500

FILE_TABLES = {
    "merchant.jsonl": "merchant",
    "menu.jsonl": "menu",
    "menu_option_group.jsonl": "menu_option_group",
    "menu_option_item.jsonl": "menu_option_item",
    "merchant_source_detail.jsonl": "merchant_source_detail",
    "menu_source_detail.jsonl": "menu_source_detail",
    "menu_source_section.jsonl": "menu_source_section",
    "menu_source_section_item.jsonl": "menu_source_section_item",
    "source_option.jsonl": "source_option",
    "option_group_source_detail.jsonl": "option_group_source_detail",
    "catalog_source_payload.jsonl": "catalog_source_payload",
}

INSERT_COLUMNS: dict[str, tuple[str, ...]] = {
    "merchant": (
        "merchant_id",
        "service_area",
        "service_area_id",
        "name_ko",
        "name_en",
        "description",
        "delivery_fee",
        "eta_min",
        "eta_max",
        "min_order_amount",
        "flavor_profile",
        "packaging_signal",
        "is_synthetic",
        "catalog_import_id",
        "data_origin",
        "source_platform",
        "source_merchant_id",
        "source_collected_at",
    ),
    "menu": (
        "menu_id",
        "merchant_id",
        "category",
        "category_id",
        "name_ko",
        "name_en",
        "description",
        "cultural_description",
        "price",
        "serves_min",
        "serves_max",
        "spice_level",
        "dietary_tags_json",
        "allergen_tags_json",
        "semantic_text",
        "availability",
        "is_synthetic",
        "updated_at",
        "catalog_import_id",
        "data_origin",
        "source_platform",
        "source_menu_id",
        "source_section_id",
        "name_en_status",
        "cultural_description_status",
        "serves_status",
        "spice_status",
        "dietary_data_status",
    ),
    "menu_option_group": (
        "option_group_id",
        "menu_id",
        "name_en",
        "name_ko",
        "description",
        "required",
        "min_select",
        "max_select",
        "sort_order",
        "catalog_import_id",
        "source_option_group_id",
        "normalization_code",
    ),
    "menu_option_item": (
        "option_item_id",
        "option_group_id",
        "name_en",
        "name_ko",
        "description",
        "price_delta",
        "availability",
        "dietary_conflict",
        "sort_order",
        "catalog_import_id",
        "source_option_item_key",
    ),
    "merchant_source_detail": (
        "merchant_id",
        "catalog_import_id",
        "latitude",
        "longitude",
        "distance_m",
        "vertical_type",
        "vertical_sub_type",
        "current_open_status",
        "review_average",
        "review_count",
        "review_image_count",
        "review_reply_count",
        "franchise_json",
        "vendor_categories_json",
        "tags_json",
        "image_json",
        "serving_type_json",
        "representative_menus_json",
        "operational_json",
    ),
    "menu_source_detail": (
        "menu_id",
        "catalog_import_id",
        "source_section_id",
        "review_count",
        "liquor",
        "is_adult",
        "verified_adult",
        "soldout",
        "stock_amount",
        "thumbnail_json",
        "badges_json",
        "announcement_json",
        "price_json",
        "point",
        "point_promotions_json",
        "operational_json",
    ),
    "menu_source_section": (
        "source_section_key",
        "catalog_import_id",
        "merchant_id",
        "source_section_id",
        "section_type",
        "title",
        "description",
        "liquor",
        "is_adult",
        "disposable",
        "additional_discounted",
        "sort_order",
    ),
    "menu_source_section_item": (
        "source_section_key",
        "menu_id",
        "sort_order",
    ),
    "source_option": (
        "source_option_key",
        "catalog_import_id",
        "merchant_id",
        "source_option_id",
        "name_ko",
        "description",
        "origin_price",
        "final_price",
        "discount_percent",
        "soldout",
        "stock_amount",
        "deposit_json",
        "reusable_packaging",
        "source_json",
    ),
    "option_group_source_detail": (
        "option_group_id",
        "catalog_import_id",
        "source_option_group_id",
        "multiple_limit",
        "available_quantity",
        "available_multiple",
        "original_min_select",
        "original_max_select",
        "badges_json",
        "tooltip_message",
        "source_json",
    ),
    "catalog_source_payload": (
        "payload_id",
        "catalog_import_id",
        "entity_type",
        "source_entity_id",
        "payload_sha256",
        "raw_payload",
    ),
}

JSON_COLUMNS = frozenset(
    {
        "dietary_tags_json",
        "allergen_tags_json",
        "franchise_json",
        "vendor_categories_json",
        "tags_json",
        "image_json",
        "serving_type_json",
        "representative_menus_json",
        "operational_json",
        "thumbnail_json",
        "badges_json",
        "announcement_json",
        "price_json",
        "point_promotions_json",
        "deposit_json",
        "source_json",
        "raw_payload",
    }
)

ORACLE_CLOB_COLUMNS = frozenset(
    {
        "dietary_tags_json",
        "allergen_tags_json",
        "semantic_text",
        "franchise_json",
        "vendor_categories_json",
        "tags_json",
        "image_json",
        "serving_type_json",
        "representative_menus_json",
        "operational_json",
        "thumbnail_json",
        "badges_json",
        "announcement_json",
        "price_json",
        "point_promotions_json",
        "deposit_json",
        "source_json",
        "raw_payload",
    }
)

DELETE_ORDER = (
    "mock_order",
    "mock_checkout",
    "delivery_preference",
    "cart_item",
    "cart",
    "address_ref",
    "structured_recommendation_request",
    "session_recommendation_criteria",
    "conversation_event",
    "recommendation_snapshot",
    "chat_message",
    "chat_session",
    "user_profile",
    "explanation_cache",
    "audit_log",
    "recommendation_runtime_state",
    "recommendation_release_family",
    "knowledge_runtime_state",
    "merchant_certification",
    "option_ingredient_effect",
    "merchant_ingredient",
    "merchant_origin_declaration",
    "menu_preference_feature_evidence",
    "menu_preference_feature",
    "menu_wiki_eligibility",
    "menu_concept_membership",
    "concept_preference_support",
    "menu_concept_map",
    "knowledge_chunk",
    "knowledge_document",
    "concept_claim",
    "dish_concept_closure",
    "dish_relation",
    "dish_concept",
    "knowledge_release",
    "option_dietary_conflict",
    "menu_dietary_attribute",
    "menu_allergen",
    "menu_ingredient",
    "menu_knowledge",
    "evidence",
    "review_snippet",
    "menu_source_section_item",
    "option_group_source_detail",
    "menu_source_section",
    "menu_source_detail",
    "source_option",
    "merchant_source_detail",
    "catalog_source_payload",
    "menu_option_item",
    "menu_option_group",
    "menu_semantic_embedding",
    "menu",
    "menu_category",
    "merchant",
    "address_place",
    "service_area",
    "ingredient",
    "allergen",
    "dietary_attribute",
    "catalog_import_batch",
)

PREFLIGHT_TABLES = (
    "user_profile",
    "chat_session",
    "chat_message",
    "recommendation_snapshot",
    "cart",
    "cart_item",
    "mock_checkout",
    "mock_order",
    "merchant",
    "menu",
    "menu_option_group",
    "menu_option_item",
    "review_snippet",
    "evidence",
    "menu_knowledge",
    "knowledge_release",
    "recommendation_release_family",
    "merchant_certification",
    "address_place",
)

RUNTIME_EMPTY_TABLES = (
    "user_profile",
    "chat_session",
    "chat_message",
    "recommendation_snapshot",
    "conversation_event",
    "session_recommendation_criteria",
    "structured_recommendation_request",
    "cart",
    "cart_item",
    "delivery_preference",
    "mock_checkout",
    "mock_order",
    "address_ref",
    "review_snippet",
    "evidence",
    "menu_knowledge",
    "merchant_certification",
    "menu_ingredient",
    "menu_allergen",
    "menu_dietary_attribute",
    "option_dietary_conflict",
    "merchant_ingredient",
    "merchant_origin_declaration",
    "option_ingredient_effect",
)

KEY_FIELDS = {
    "merchant": ("merchant_id",),
    "menu": ("menu_id",),
    "menu_option_group": ("option_group_id",),
    "menu_option_item": ("option_item_id",),
    "merchant_source_detail": ("merchant_id",),
    "menu_source_detail": ("menu_id",),
    "menu_source_section": ("source_section_key",),
    "menu_source_section_item": ("source_section_key", "menu_id"),
    "source_option": ("source_option_key",),
    "option_group_source_detail": ("option_group_id",),
    "catalog_source_payload": ("payload_id",),
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_manifest(package_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(package_path) as archive:
        names = set(archive.namelist())
        required = {"manifest.json", "selection_manifest.json", *FILE_TABLES}
        if names != required:
            raise RuntimeError(
                f"PACKAGE_FILE_SET_MISMATCH:{canonical_json({'missing': sorted(required - names), 'extra': sorted(names - required)})}"
            )
        manifest = json.loads(archive.read("manifest.json"))
        selection = json.loads(archive.read("selection_manifest.json"))
    if manifest.get("package_format") != PACKAGE_FORMAT:
        raise RuntimeError("PACKAGE_FORMAT_UNSUPPORTED")
    if manifest.get("data_origin") != DATA_ORIGIN:
        raise RuntimeError("PACKAGE_DATA_ORIGIN_UNAPPROVED")
    if manifest.get("source_platform") != SOURCE_PLATFORM:
        raise RuntimeError("PACKAGE_SOURCE_PLATFORM_UNAPPROVED")
    if hashlib.sha256(canonical_json(selection).encode("utf-8")).hexdigest() != manifest.get(
        "selection_manifest_canonical_sha256"
    ):
        raise RuntimeError("PACKAGE_SELECTION_MANIFEST_HASH_MISMATCH")
    return manifest


def iter_jsonl(package_path: Path, filename: str) -> Iterator[dict[str, Any]]:
    with zipfile.ZipFile(package_path) as archive, archive.open(filename) as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"PACKAGE_JSON_INVALID:{filename}:{line_number}") from exc
            if not isinstance(value, dict):
                raise TypeError(f"PACKAGE_ROW_NOT_OBJECT:{filename}:{line_number}")
            yield value


def validate_package(
    package_path: Path,
    expected_package_sha256: str | None,
    expected_normalization_count: int | None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    package_sha = sha256_file(package_path)
    if expected_package_sha256 and package_sha != expected_package_sha256.lower():
        raise RuntimeError("PACKAGE_SHA256_MISMATCH")
    manifest = read_manifest(package_path)
    actual_counts: Counter[str] = Counter()
    seen: dict[str, set[tuple[str, ...]]] = {table: set() for table in FILE_TABLES.values()}
    duplicate_samples: dict[str, list[tuple[str, ...]]] = {}
    normalization_count = 0
    bad_origin_count = 0
    menu_ids: set[str] = set()
    merchant_ids: set[str] = set()
    group_ids: set[str] = set()
    for filename, table in FILE_TABLES.items():
        required_columns = set(INSERT_COLUMNS[table])
        for row in iter_jsonl(package_path, filename):
            actual_counts[table] += 1
            missing = required_columns - row.keys()
            if missing:
                raise RuntimeError(
                    f"PACKAGE_REQUIRED_COLUMN_MISSING:{filename}:{','.join(sorted(missing))}"
                )
            key = tuple(str(row[field]) for field in KEY_FIELDS[table])
            if key in seen[table]:
                duplicate_samples.setdefault(table, []).append(key)
            seen[table].add(key)
            if row.get("catalog_import_id") != manifest["catalog_import_id"]:
                raise RuntimeError(f"PACKAGE_IMPORT_ID_MISMATCH:{filename}")
            if table == "merchant":
                merchant_ids.add(str(row["merchant_id"]))
                bad_origin_count += int(
                    row.get("data_origin") != DATA_ORIGIN or int(row.get("is_synthetic", 1)) != 0
                )
            elif table == "menu":
                menu_ids.add(str(row["menu_id"]))
                bad_origin_count += int(
                    row.get("data_origin") != DATA_ORIGIN or int(row.get("is_synthetic", 1)) != 0
                )
                if row.get("name_en") is not None or row.get("spice_level") is not None:
                    raise RuntimeError("PACKAGE_UNKNOWN_MENU_VALUE_NOT_NULL")
                if not str(row.get("semantic_text") or "").strip():
                    raise RuntimeError("PACKAGE_MENU_SEMANTIC_TEXT_MISSING")
            elif table == "menu_option_group":
                group_ids.add(str(row["option_group_id"]))
                if row.get("normalization_code") == NORMALIZATION_CODE:
                    normalization_count += 1
                if int(row["max_select"]) < int(row["min_select"]):
                    raise RuntimeError("PACKAGE_OPTION_BOUNDS_INVALID")
    if duplicate_samples:
        raise RuntimeError(f"PACKAGE_DUPLICATE_KEYS:{canonical_json(duplicate_samples)}")
    if bad_origin_count:
        raise RuntimeError("PACKAGE_PROVENANCE_INVALID")
    expected_counts = {str(key): int(value) for key, value in manifest["expected_counts"].items()}
    if dict(actual_counts) != expected_counts:
        raise RuntimeError(
            f"PACKAGE_COUNT_MISMATCH:{canonical_json({'expected': expected_counts, 'actual': dict(actual_counts)})}"
        )
    if expected_normalization_count is not None and normalization_count != expected_normalization_count:
        raise RuntimeError("PACKAGE_NORMALIZATION_COUNT_MISMATCH")
    if normalization_count != int(manifest["diagnostics"]["normalization_count"]):
        raise RuntimeError("PACKAGE_NORMALIZATION_DIAGNOSTIC_MISMATCH")
    if not merchant_ids or not menu_ids or not group_ids:
        raise RuntimeError("PACKAGE_CORE_TABLE_EMPTY")
    diagnostics = {
        "counts": dict(actual_counts),
        "normalization_count": normalization_count,
        "unique_merchants": len(merchant_ids),
        "unique_menus": len(menu_ids),
        "unique_option_groups": len(group_ids),
        "package_validation_passed": True,
    }
    return manifest, package_sha, diagnostics


def prepare_vector_cache(
    package_path: Path,
    provider: EmbeddingProvider,
) -> tuple[Path, int]:
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix="yobi-catalog-vectors-", suffix=".f32"
    )
    cache_path = Path(raw_path)
    vector_count = 0
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            batch: list[str] = []
            for row in iter_jsonl(package_path, "menu.jsonl"):
                batch.append(str(row["semantic_text"]))
                if len(batch) < VECTOR_BATCH_SIZE:
                    continue
                for vector in provider.embed(batch, "SEARCH_DOCUMENT"):
                    array("f", vector).tofile(handle)
                    vector_count += 1
                batch = []
            if batch:
                for vector in provider.embed(batch, "SEARCH_DOCUMENT"):
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
        raise RuntimeError("VECTOR_CACHE_SIZE_MISMATCH")
    return cache_path, vector_count


def prepared_value(column: str, value: Any) -> Any:
    if column in JSON_COLUMNS:
        return None if value is None else canonical_json(value)
    return value


def oracle_prepared_value(column: str, value: Any) -> Any:
    if column == "source_collected_at" and isinstance(value, str):
        return datetime.fromisoformat(value)
    return prepared_value(column, value)


def batches(rows: Iterable[dict[str, Any]], size: int = DML_BATCH_SIZE) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def fetch_counts(cursor: Any, tables: Iterable[str], oracle: bool) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        row = cursor.fetchone()
        result[table] = int(row[0])
    return result


def insert_batch_row(
    cursor: Any,
    manifest: dict[str, Any],
    package_sha: str,
    diagnostics: dict[str, Any],
    oracle: bool,
) -> None:
    columns = (
        "catalog_import_id",
        "catalog_release_id",
        "data_origin",
        "source_platform",
        "source_zip_sha256",
        "source_xlsx_sha256",
        "source_summary_sha256",
        "package_sha256",
        "selection_manifest_sha256",
        "selection_algorithm_version",
        "collection_location",
        "source_collected_at",
        "selected_merchant_count",
        "expected_counts_json",
        "actual_counts_json",
        "diagnostics_json",
        "status",
        "started_at",
        "completed_at",
    )
    hashes = manifest["source_hashes"]
    row = {
        "catalog_import_id": manifest["catalog_import_id"],
        "catalog_release_id": manifest["catalog_release_id"],
        "data_origin": manifest["data_origin"],
        "source_platform": manifest["source_platform"],
        "source_zip_sha256": hashes["raw_zip_sha256"],
        "source_xlsx_sha256": hashes["normalized_xlsx_sha256"],
        "source_summary_sha256": hashes["collection_summary_sha256"],
        "package_sha256": package_sha,
        "selection_manifest_sha256": manifest["selection_manifest_sha256"],
        "selection_algorithm_version": manifest["selection_algorithm_version"],
        "collection_location": manifest["collection_location"],
        "source_collected_at": (
            datetime.fromisoformat(manifest["source_collected_at"])
            if oracle
            else manifest["source_collected_at"]
        ),
        "selected_merchant_count": int(manifest["selected_merchant_count"]),
        "expected_counts_json": canonical_json(manifest["expected_counts"]),
        "actual_counts_json": "{}",
        "diagnostics_json": canonical_json(diagnostics),
        "status": "LOADING",
        "started_at": datetime.now(timezone.utc) if oracle else now(),
        "completed_at": None,
    }
    if oracle:
        cursor.setinputsizes(
            expected_counts_json=oracledb.DB_TYPE_CLOB,
            actual_counts_json=oracledb.DB_TYPE_CLOB,
            diagnostics_json=oracledb.DB_TYPE_CLOB,
        )
        placeholders = ",".join(f":{column}" for column in columns)
        cursor.execute(
            f"INSERT INTO catalog_import_batch ({','.join(columns)}) VALUES ({placeholders})",
            row,
        )
    else:
        placeholders = ",".join("?" for _ in columns)
        cursor.execute(
            f"INSERT INTO catalog_import_batch ({','.join(columns)}) VALUES ({placeholders})",
            tuple(row[column] for column in columns),
        )


def insert_service_area(cursor: Any, manifest: dict[str, Any], oracle: bool) -> None:
    values = (
        manifest["service_area_id"],
        "서울특별시",
        "중구",
        manifest["service_area"],
        1,
    )
    if oracle:
        cursor.execute(
            "INSERT INTO service_area(service_area_id,city,district,display_name,active) VALUES (:1,:2,:3,:4,:5)",
            values,
        )
    else:
        cursor.execute(
            "INSERT INTO service_area(service_area_id,city,district,display_name,active) VALUES (?,?,?,?,?)",
            values,
        )


def insert_demo_address(cursor: Any, manifest: dict[str, Any], oracle: bool) -> None:
    if str(manifest["service_area_id"]) != DEMO_ADDRESS_SERVICE_AREA_ID:
        raise RuntimeError("DEMO_ADDRESS_SERVICE_AREA_MISMATCH")
    upsert_demo_address(cursor, oracle=oracle)


def oracle_insert_rows(
    cursor: oracledb.Cursor,
    package_path: Path,
    filename: str,
    table: str,
) -> None:
    columns = INSERT_COLUMNS[table]
    placeholders = ",".join(f":{column}" for column in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    clobs = {column: oracledb.DB_TYPE_CLOB for column in columns if column in ORACLE_CLOB_COLUMNS}
    if clobs:
        cursor.setinputsizes(**clobs)
    for raw_batch in batches(iter_jsonl(package_path, filename)):
        payload = [
            {column: oracle_prepared_value(column, row.get(column)) for column in columns}
            for row in raw_batch
        ]
        cursor.executemany(sql, payload)


def oracle_insert_menus(
    cursor: oracledb.Cursor,
    package_path: Path,
    vector_cache_path: Path,
    provider: EmbeddingProvider,
) -> int:
    columns = INSERT_COLUMNS["menu"] + (
        "embedding_vector",
        "embedding_model",
        "embedding_dimension",
        "embedding_version",
    )
    placeholders = ",".join(f":{column}" for column in columns)
    sql = f"INSERT INTO menu ({','.join(columns)}) VALUES ({placeholders})"
    cursor.setinputsizes(
        dietary_tags_json=oracledb.DB_TYPE_CLOB,
        allergen_tags_json=oracledb.DB_TYPE_CLOB,
        semantic_text=oracledb.DB_TYPE_CLOB,
    )
    inserted = 0
    with vector_cache_path.open("rb") as vector_handle:
        payload: list[dict[str, Any]] = []
        for row in iter_jsonl(package_path, "menu.jsonl"):
            vector = array("f")
            try:
                vector.fromfile(vector_handle, provider.dimension)
            except EOFError as exc:
                raise RuntimeError("VECTOR_CACHE_TRUNCATED") from exc
            prepared = {
                column: oracle_prepared_value(column, row.get(column))
                for column in INSERT_COLUMNS["menu"]
            }
            prepared.update(
                {
                    "embedding_vector": vector,
                    "embedding_model": provider.model,
                    "embedding_dimension": provider.dimension,
                    "embedding_version": provider.version,
                }
            )
            payload.append(prepared)
            if len(payload) >= DML_BATCH_SIZE:
                cursor.executemany(sql, payload)
                inserted += len(payload)
                payload = []
        if payload:
            cursor.executemany(sql, payload)
            inserted += len(payload)
        if vector_handle.read(1):
            raise RuntimeError("VECTOR_CACHE_HAS_TRAILING_DATA")
    return inserted


def sqlite_insert_rows(
    cursor: sqlite3.Cursor,
    package_path: Path,
    filename: str,
    table: str,
) -> None:
    columns = INSERT_COLUMNS[table]
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    for raw_batch in batches(iter_jsonl(package_path, filename)):
        cursor.executemany(
            sql,
            [
                tuple(prepared_value(column, row.get(column)) for column in columns)
                for row in raw_batch
            ],
        )


def insert_release_state(
    cursor: Any,
    manifest: dict[str, Any],
    oracle: bool,
    provider: EmbeddingProvider,
) -> dict[str, str]:
    selection_token = str(manifest["selection_manifest_sha256"])[:20]
    knowledge_release_id = f"external-knowledge-{selection_token}"
    recommendation_family_id = f"external-recommendation-{selection_token}"
    zero_counts = {
        "claims": 0,
        "closure": 0,
        "concepts": 0,
        "documents": 0,
        "relations": 0,
        "chunks": 0,
    }
    timestamp = datetime.now(timezone.utc) if oracle else now()
    knowledge_values = (
        knowledge_release_id,
        manifest["catalog_release_id"],
        manifest["selection_manifest_sha256"],
        provider.model,
        provider.dimension,
        provider.version,
        "READY",
        canonical_json(zero_counts),
        canonical_json(zero_counts),
        0,
        timestamp,
        timestamp,
    )
    if oracle:
        cursor.execute(
            """
            INSERT INTO knowledge_release(
              release_id,catalog_version,manifest_sha256,embedding_model,
              embedding_dimension,embedding_version,status,expected_counts_json,
              actual_counts_json,is_synthetic,created_at,completed_at
            ) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12)
            """,
            knowledge_values,
        )
        cursor.execute(
            "INSERT INTO knowledge_runtime_state(state_key,active_release_id,updated_at) VALUES ('ACTIVE',:1,:2)",
            (knowledge_release_id, timestamp),
        )
    else:
        cursor.execute(
            """
            INSERT INTO knowledge_release(
              release_id,catalog_version,manifest_sha256,embedding_model,
              embedding_dimension,embedding_version,status,expected_counts_json,
              actual_counts_json,is_synthetic,created_at,completed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            knowledge_values,
        )
        cursor.execute(
            "INSERT INTO knowledge_runtime_state(state_key,active_release_id,updated_at) VALUES ('ACTIVE',?,?)",
            (knowledge_release_id, timestamp),
        )

    certification_release_id = f"external-certifications-none-{selection_token}"
    family_values = (
        recommendation_family_id,
        knowledge_release_id,
        manifest["catalog_release_id"],
        PREFERENCE_CATALOG_VERSION,
        SPICE_REFERENCE_VERSION,
        certification_release_id,
        provider.model,
        provider.version,
        "ACTIVE",
        timestamp,
    )
    if oracle:
        cursor.execute(
            """
            INSERT INTO recommendation_release_family(
              release_family_id,knowledge_release_id,catalog_release_id,
              preference_catalog_version,spice_reference_version,
              certification_release_id,embedding_model,embedding_version,status,activated_at
            ) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10)
            """,
            family_values,
        )
        cursor.execute(
            "INSERT INTO recommendation_runtime_state(state_key,active_release_family_id,updated_at) VALUES ('ACTIVE',:1,:2)",
            (recommendation_family_id, timestamp),
        )
    else:
        cursor.execute(
            """
            INSERT INTO recommendation_release_family(
              release_family_id,knowledge_release_id,catalog_release_id,
              preference_catalog_version,spice_reference_version,
              certification_release_id,embedding_model,embedding_version,status,activated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            family_values,
        )
        cursor.execute(
            "INSERT INTO recommendation_runtime_state(state_key,active_release_family_id,updated_at) VALUES ('ACTIVE',?,?)",
            (recommendation_family_id, timestamp),
        )
    return {
        "knowledge_release_id": knowledge_release_id,
        "recommendation_release_family_id": recommendation_family_id,
    }


def insert_unmapped_menu_state(
    cursor: Any,
    package_path: Path,
    release_id: str,
    oracle: bool,
) -> None:
    timestamp = datetime.now(timezone.utc) if oracle else now()
    source_ref = "YOGIYO_PUBLIC_WEB:source-does-not-provide-reviewed-dish-concepts"
    columns = (
        "release_id",
        "menu_id",
        "concept_id",
        "mapping_status",
        "mapping_type",
        "unmapped_reason",
        "confidence_band",
        "source_type",
        "source_ref",
        "review_status",
        "is_synthetic",
        "updated_at",
    )
    if oracle:
        sql = (
            f"INSERT INTO menu_concept_map ({','.join(columns)}) VALUES "
            f"({','.join(':' + value for value in columns)})"
        )
        payload: list[dict[str, Any]] = []
        for row in iter_jsonl(package_path, "menu.jsonl"):
            payload.append(
                {
                    "release_id": release_id,
                    "menu_id": row["menu_id"],
                    "concept_id": None,
                    "mapping_status": "UNMAPPED",
                    "mapping_type": "UNMAPPED",
                    "unmapped_reason": "SOURCE_DOES_NOT_PROVIDE_REVIEWED_DISH_CONCEPT",
                    "confidence_band": "low",
                    "source_type": DATA_ORIGIN,
                    "source_ref": source_ref,
                    "review_status": "UNVERIFIED_SOURCE_ONLY",
                    "is_synthetic": 0,
                    "updated_at": timestamp,
                }
            )
            if len(payload) >= DML_BATCH_SIZE:
                cursor.executemany(sql, payload)
                payload = []
        if payload:
            cursor.executemany(sql, payload)
    else:
        sql = f"INSERT INTO menu_concept_map ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
        payload_values: list[tuple[Any, ...]] = []
        for row in iter_jsonl(package_path, "menu.jsonl"):
            payload_values.append(
                (
                    release_id,
                    row["menu_id"],
                    None,
                    "UNMAPPED",
                    "UNMAPPED",
                    "SOURCE_DOES_NOT_PROVIDE_REVIEWED_DISH_CONCEPT",
                    "low",
                    DATA_ORIGIN,
                    source_ref,
                    "UNVERIFIED_SOURCE_ONLY",
                    0,
                    timestamp,
                )
            )
            if len(payload_values) >= DML_BATCH_SIZE:
                cursor.executemany(sql, payload_values)
                payload_values = []
        if payload_values:
            cursor.executemany(sql, payload_values)


def scalar(cursor: Any, sql: str, parameters: Any = None) -> int:
    if parameters is None:
        cursor.execute(sql)
    else:
        cursor.execute(sql, parameters)
    return int(cursor.fetchone()[0])


def verify_database(
    cursor: Any,
    manifest: dict[str, Any],
    package_sha: str,
    oracle: bool,
    provider: EmbeddingProvider,
) -> dict[str, Any]:
    expected = {str(key): int(value) for key, value in manifest["expected_counts"].items()}
    counts = fetch_counts(cursor, expected, oracle)
    address_status = demo_address_status(cursor)
    checks: dict[str, bool] = {
        "package_counts_exact": counts == expected,
        "runtime_demo_rows_removed": all(
            count == 0 for count in fetch_counts(cursor, RUNTIME_EMPTY_TABLES, oracle).values()
        ),
        "menu_categories_removed": scalar(cursor, "SELECT COUNT(*) FROM menu_category") == 0,
        # General synthetic Wiki taxonomy rows may exist after the separate
        # external-knowledge build.  The source-integrity boundary is that no
        # merchant/menu-specific ingredient, allergen, dietary or certification
        # fact is invented from the public catalog.
        "source_specific_fact_rows_zero": all(
            count == 0
            for count in fetch_counts(
                cursor,
                (
                    "menu_ingredient",
                    "menu_allergen",
                    "menu_dietary_attribute",
                    "option_dietary_conflict",
                    "merchant_certification",
                    "merchant_ingredient",
                    "merchant_origin_declaration",
                    "option_ingredient_effect",
                ),
                oracle,
            ).values()
        ),
        "single_service_area": scalar(cursor, "SELECT COUNT(*) FROM service_area") == 1,
        "single_demo_address_ready": address_status["ready"] is True,
        "external_merchant_provenance": scalar(
            cursor,
            "SELECT COUNT(*) FROM merchant WHERE data_origin='YOGIYO_PUBLIC_WEB' AND is_synthetic=0",
        )
        == expected["merchant"],
        "external_menu_provenance": scalar(
            cursor,
            "SELECT COUNT(*) FROM menu WHERE data_origin='YOGIYO_PUBLIC_WEB' AND is_synthetic=0",
        )
        == expected["menu"],
        "unknown_fields_remain_null": scalar(
            cursor,
            """
            SELECT COUNT(*) FROM menu
            WHERE name_en IS NULL AND serves_min IS NULL AND serves_max IS NULL
              AND spice_level IS NULL AND name_en_status='NOT_PROVIDED'
              AND serves_status='NOT_PROVIDED' AND spice_status='NOT_PROVIDED'
            """,
        )
        == expected["menu"],
        "option_normalizations_exact": scalar(
            cursor,
            "SELECT COUNT(*) FROM menu_option_group WHERE normalization_code='REQUIRED_SINGLE_SELECT_ZERO_LIMIT'",
        )
        == int(manifest["diagnostics"]["normalization_count"]),
        "option_bounds_valid": scalar(
            cursor,
            """
            SELECT COUNT(*) FROM menu_option_group groups
            WHERE groups.min_select<0 OR groups.max_select<groups.min_select
              OR (groups.required=1 AND groups.min_select<1)
              OR (SELECT COUNT(*) FROM menu_option_item item
                  WHERE item.option_group_id=groups.option_group_id
                    AND item.availability='AVAILABLE') < groups.min_select
            """,
        )
        == 0,
        "mapping_state_fully_classified": scalar(
            cursor,
            """
            SELECT COUNT(*) FROM menu_concept_map
            WHERE release_id=(
              SELECT active_release_id FROM knowledge_runtime_state WHERE state_key='ACTIVE'
            )
            """,
        )
        == expected["menu"]
        and scalar(
            cursor,
            """
            SELECT COUNT(*) FROM menu_concept_map
            WHERE release_id=(
                    SELECT active_release_id FROM knowledge_runtime_state WHERE state_key='ACTIVE'
                  )
              AND mapping_status='UNMAPPED' AND TRIM(COALESCE(unmapped_reason,''))=''
            """,
        )
        == 0
        and scalar(
            cursor,
            """
            SELECT COUNT(*) FROM menu_concept_map
            WHERE release_id=(
                    SELECT active_release_id FROM knowledge_runtime_state WHERE state_key='ACTIVE'
                  )
              AND mapping_status='MAPPED'
              AND (confidence_band<>'high'
                   OR source_type<>'YOBI_DERIVED_DEMO_MAPPING'
                   OR review_status<>'REVIEWED_DEMO')
            """,
        )
        == 0,
        "preference_catalog_preserved": scalar(
            cursor, "SELECT COUNT(*) FROM recommendation_preference_option"
        )
        > 0,
        "spice_reference_preserved": scalar(cursor, "SELECT COUNT(*) FROM spice_reference") == 10,
        "active_knowledge_release_pointer_ready": scalar(
            cursor,
            """
            SELECT COUNT(*) FROM knowledge_runtime_state state
            JOIN knowledge_release release ON release.release_id=state.active_release_id
            WHERE state.state_key='ACTIVE' AND release.status='READY'
            """,
        )
        == 1,
        "active_source_recommendation_family": scalar(
            cursor,
            """
            SELECT COUNT(*) FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
            """,
        )
        == 1,
        "payload_hashes_present": scalar(
            cursor,
            "SELECT COUNT(*) FROM catalog_source_payload WHERE LENGTH(payload_sha256)=64",
        )
        == expected["catalog_source_payload"],
    }
    if oracle:
        checks["menu_vectors_complete"] = scalar(
            cursor,
            """
            SELECT COUNT(*) FROM menu
            WHERE embedding_vector IS NULL OR embedding_model<>:model
              OR embedding_dimension<>:dimension OR embedding_version<>:version
            """,
            {
                "model": provider.model,
                "dimension": provider.dimension,
                "version": provider.version,
            },
        ) == 0
    else:
        checks["menu_semantic_text_complete"] = scalar(
            cursor, "SELECT COUNT(*) FROM menu WHERE TRIM(COALESCE(semantic_text,''))=''"
        ) == 0

    if oracle:
        cursor.execute(
            """
            SELECT package_sha256,status,data_origin,selected_merchant_count
            FROM catalog_import_batch WHERE catalog_import_id=:catalog_import_id
            """,
            catalog_import_id=manifest["catalog_import_id"],
        )
    else:
        cursor.execute(
            """
            SELECT package_sha256,status,data_origin,selected_merchant_count
            FROM catalog_import_batch WHERE catalog_import_id=?
            """,
            (manifest["catalog_import_id"],),
        )
    batch_row = cursor.fetchone()
    checks["active_import_batch_exact"] = bool(
        batch_row
        and str(batch_row[0]) == package_sha
        and str(batch_row[1]) in {"LOADING", "ACTIVE"}
        and str(batch_row[2]) == DATA_ORIGIN
        and int(batch_row[3]) == expected["merchant"]
    )
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "counts": counts,
        "catalog_import_id": manifest["catalog_import_id"],
        "catalog_release_id": manifest["catalog_release_id"],
        "package_sha256": package_sha,
        "embedding": {
            "model": provider.model,
            "dimension": provider.dimension,
            "version": provider.version,
        },
    }


def finalize_batch(cursor: Any, manifest: dict[str, Any], verification: dict[str, Any], oracle: bool) -> None:
    timestamp = datetime.now(timezone.utc) if oracle else now()
    diagnostics = {
        **manifest["diagnostics"],
        "database_checks": verification["checks"],
        "verified_at": timestamp.isoformat() if isinstance(timestamp, datetime) else timestamp,
    }
    if oracle:
        cursor.setinputsizes(
            actual_counts_json=oracledb.DB_TYPE_CLOB,
            diagnostics_json=oracledb.DB_TYPE_CLOB,
        )
        cursor.execute(
            """
            UPDATE catalog_import_batch SET actual_counts_json=:actual_counts_json,
              diagnostics_json=:diagnostics_json,status='ACTIVE',completed_at=:completed_at
            WHERE catalog_import_id=:catalog_import_id
            """,
            actual_counts_json=canonical_json(verification["counts"]),
            diagnostics_json=canonical_json(diagnostics),
            completed_at=timestamp,
            catalog_import_id=manifest["catalog_import_id"],
        )
    else:
        cursor.execute(
            """
            UPDATE catalog_import_batch SET actual_counts_json=?,diagnostics_json=?,
              status='ACTIVE',completed_at=? WHERE catalog_import_id=?
            """,
            (
                canonical_json(verification["counts"]),
                canonical_json(diagnostics),
                timestamp,
                manifest["catalog_import_id"],
            ),
        )


def validate_oracle_varchar_capacity(
    cursor: oracledb.Cursor,
    package_path: Path,
) -> dict[str, Any]:
    cursor.execute(
        "SELECT value FROM nls_database_parameters "
        "WHERE parameter='NLS_CHARACTERSET'"
    )
    charset_row = cursor.fetchone()
    charset = str(charset_row[0]) if charset_row else ""
    if charset != "AL32UTF8":
        raise RuntimeError(f"UNSUPPORTED_ORACLE_CHARACTERSET:{charset or 'UNKNOWN'}")

    cursor.execute(
        """
        SELECT table_name,column_name,data_type,data_length,char_length,char_used
        FROM user_tab_columns
        """
    )
    column_limits: dict[tuple[str, str], tuple[int, int, str]] = {
        (str(table_name).lower(), str(column_name).lower()): (
            int(data_length),
            int(char_length),
            str(char_used or "B"),
        )
        for table_name, column_name, data_type, data_length, char_length, char_used in cursor
        if str(data_type) in {"CHAR", "VARCHAR2"}
    }
    checked_values = 0
    violations: list[str] = []
    for filename, table in FILE_TABLES.items():
        string_columns = {
            column: column_limits[(table, column)]
            for column in INSERT_COLUMNS[table]
            if (table, column) in column_limits
        }
        for row_number, row in enumerate(iter_jsonl(package_path, filename), start=1):
            for column, (data_length, char_length, char_used) in string_columns.items():
                value = row.get(column)
                if value is None:
                    continue
                text_value = str(value)
                measured = (
                    len(text_value)
                    if char_used == "C"
                    else len(text_value.encode("utf-8"))
                )
                maximum = (
                    char_length
                    if char_used == "C"
                    else data_length
                )
                checked_values += 1
                if measured > maximum:
                    violations.append(
                        f"{filename}:{row_number}:{column}:{measured}>{maximum}"
                    )
                    if len(violations) >= 20:
                        break
            if len(violations) >= 20:
                break
        if len(violations) >= 20:
            break
    if violations:
        raise RuntimeError(
            "ORACLE_VARCHAR_CAPACITY_EXCEEDED:" + ",".join(violations)
        )
    return {
        "character_set": charset,
        "checked_string_values": checked_values,
        "violations": 0,
    }


def apply_oracle(
    settings: Settings,
    package_path: Path,
    vector_cache_path: Path,
    manifest: dict[str, Any],
    package_sha: str,
    package_diagnostics: dict[str, Any],
    provider: EmbeddingProvider,
) -> dict[str, Any]:
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise RuntimeError("ADB_DSN_AND_DB_PASSWORD_REQUIRED")
    with oracledb.connect(user=settings.db_username, password=password, dsn=dsn) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT SYS_CONTEXT('USERENV','CURRENT_USER') FROM dual")
        current_user = str(cursor.fetchone()[0])
        if current_user.upper() != settings.db_username.upper() or current_user.upper() == "ADMIN":
            raise RuntimeError("ORACLE_RUNTIME_USER_MISMATCH")
        cursor.execute("SELECT COUNT(*) FROM schema_migration WHERE version='014'")
        if int(cursor.fetchone()[0]) != 1:
            raise RuntimeError("MIGRATION_014_NOT_APPLIED")
        varchar_validation = validate_oracle_varchar_capacity(cursor, package_path)
        preflight = fetch_counts(cursor, PREFLIGHT_TABLES, True)
        try:
            for table in DELETE_ORDER:
                cursor.execute(f"DELETE FROM {table}")
            insert_batch_row(cursor, manifest, package_sha, package_diagnostics, True)
            insert_service_area(cursor, manifest, True)
            insert_demo_address(cursor, manifest, True)
            oracle_insert_rows(cursor, package_path, "merchant.jsonl", "merchant")
            menu_count = oracle_insert_menus(
                cursor,
                package_path,
                vector_cache_path,
                provider,
            )
            if menu_count != int(manifest["expected_counts"]["menu"]):
                raise RuntimeError("ORACLE_MENU_INSERT_COUNT_MISMATCH")
            for filename in (
                "menu_option_group.jsonl",
                "menu_option_item.jsonl",
                "merchant_source_detail.jsonl",
                "menu_source_detail.jsonl",
                "menu_source_section.jsonl",
                "menu_source_section_item.jsonl",
                "source_option.jsonl",
                "option_group_source_detail.jsonl",
                "catalog_source_payload.jsonl",
            ):
                oracle_insert_rows(cursor, package_path, filename, FILE_TABLES[filename])
            release_state = insert_release_state(cursor, manifest, True, provider)
            insert_unmapped_menu_state(
                cursor, package_path, release_state["knowledge_release_id"], True
            )
            verification = verify_database(cursor, manifest, package_sha, True, provider)
            if not verification["pass"]:
                raise RuntimeError(f"ORACLE_IMPORT_VERIFICATION_FAILED:{canonical_json(verification['checks'])}")
            finalize_batch(cursor, manifest, verification, True)
            final_verification = verify_database(
                cursor,
                manifest,
                package_sha,
                True,
                provider,
            )
            if not final_verification["pass"]:
                raise RuntimeError("ORACLE_IMPORT_FINAL_VERIFICATION_FAILED")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    return {
        **final_verification,
        "backend": "oracle-26ai",
        "database_user": current_user,
        "preflight_counts": preflight,
        "varchar_validation": varchar_validation,
        "release_state": release_state,
        "transaction_committed": True,
    }


def ensure_sqlite_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    required = {
        "merchant": {"catalog_import_id", "data_origin", "source_platform"},
        "menu": {"catalog_import_id", "data_origin", "spice_status"},
        "menu_option_group": {"catalog_import_id", "normalization_code"},
        "menu_option_item": {"catalog_import_id", "source_option_item_key"},
    }
    for table, columns in required.items():
        actual = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if not columns.issubset(actual):
            raise RuntimeError(f"SQLITE_EXTERNAL_CATALOG_SCHEMA_MISSING:{table}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_merchant_catalog_import "
        "ON merchant(catalog_import_id,data_origin)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_menu_catalog_import "
        "ON menu(catalog_import_id,merchant_id,availability)"
    )


def ensure_sqlite_product_settings(connection: sqlite3.Connection) -> None:
    if int(connection.execute("SELECT COUNT(*) FROM recommendation_preference_option").fetchone()[0]) == 0:
        preference_rows: list[tuple[Any, ...]] = []
        for category in PREFERENCE_CATEGORIES:
            for display_order, option in enumerate(category.options):
                preference_rows.append(
                    (
                        PREFERENCE_CATALOG_VERSION,
                        category.code,
                        option.code,
                        option.labels["ko"],
                        option.labels["en"],
                        canonical_json(option.query_aliases),
                        display_order,
                        1,
                    )
                )
        connection.executemany(
            """
            INSERT INTO recommendation_preference_option(
              catalog_version,category_code,option_code,label_ko,label_en,
              query_aliases_json,display_order,active
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            preference_rows,
        )
    if int(connection.execute("SELECT COUNT(*) FROM spice_reference").fetchone()[0]) == 0:
        ko = {
            str(item["country"]): item
            for item in cast(list[dict[str, Any]], localized_spice_references("ko"))
        }
        en = {
            str(item["country"]): item
            for item in cast(list[dict[str, Any]], localized_spice_references("en"))
        }
        spice_rows: list[tuple[Any, ...]] = []
        for country in ("KR", "US"):
            ko_levels = {int(str(item["level"])): item for item in ko[country]["levels"]}
            en_levels = {int(str(item["level"])): item for item in en[country]["levels"]}
            for level in range(1, 6):
                spice_rows.append(
                    (
                        SPICE_REFERENCE_VERSION,
                        country,
                        level,
                        str(ko_levels[level]["label"]),
                        str(en_levels[level]["label"]),
                        str(ko_levels[level]["example"]),
                        str(en_levels[level]["example"]),
                    )
                )
        connection.executemany(
            """
            INSERT INTO spice_reference(
              reference_version,country_code,spice_level,label_ko,label_en,example_ko,example_en
            ) VALUES (?,?,?,?,?,?,?)
            """,
            spice_rows,
        )


def apply_sqlite(
    sqlite_path: Path,
    package_path: Path,
    manifest: dict[str, Any],
    package_sha: str,
    package_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    provider = DeterministicEmbeddingProvider()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(sqlite_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        ensure_sqlite_schema(connection)
        ensure_sqlite_product_settings(connection)
        cursor = connection.cursor()
        preflight = fetch_counts(cursor, PREFLIGHT_TABLES, False)
        connection.commit()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            for table in DELETE_ORDER:
                cursor.execute(f"DELETE FROM {table}")
            insert_batch_row(cursor, manifest, package_sha, package_diagnostics, False)
            insert_service_area(cursor, manifest, False)
            insert_demo_address(cursor, manifest, False)
            for filename, table in FILE_TABLES.items():
                sqlite_insert_rows(cursor, package_path, filename, table)
            release_state = insert_release_state(cursor, manifest, False, provider)
            insert_unmapped_menu_state(
                cursor, package_path, release_state["knowledge_release_id"], False
            )
            verification = verify_database(cursor, manifest, package_sha, False, provider)
            if not verification["pass"]:
                raise RuntimeError(f"SQLITE_IMPORT_VERIFICATION_FAILED:{canonical_json(verification['checks'])}")
            finalize_batch(cursor, manifest, verification, False)
            final_verification = verify_database(
                cursor,
                manifest,
                package_sha,
                False,
                provider,
            )
            if not final_verification["pass"]:
                raise RuntimeError("SQLITE_IMPORT_FINAL_VERIFICATION_FAILED")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    finally:
        connection.close()
    return {
        **final_verification,
        "backend": "sqlite",
        "sqlite_path": str(sqlite_path.resolve()),
        "preflight_counts": preflight,
        "release_state": release_state,
        "transaction_committed": True,
    }


def verify_only_oracle(
    settings: Settings,
    manifest: dict[str, Any],
    package_sha: str,
    provider: EmbeddingProvider,
) -> dict[str, Any]:
    dsn = settings.adb_dsn.get_secret_value()
    password = settings.db_password.get_secret_value()
    if not dsn or not password:
        raise RuntimeError("ADB_DSN_AND_DB_PASSWORD_REQUIRED")
    with oracledb.connect(user=settings.db_username, password=password, dsn=dsn) as connection:
        result = verify_database(
            connection.cursor(),
            manifest,
            package_sha,
            True,
            provider,
        )
    return {**result, "backend": "oracle-26ai", "transaction_committed": False}


def verify_only_sqlite(
    sqlite_path: Path, manifest: dict[str, Any], package_sha: str
) -> dict[str, Any]:
    provider = DeterministicEmbeddingProvider()
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        result = verify_database(
            connection.cursor(),
            manifest,
            package_sha,
            False,
            provider,
        )
    return {
        **result,
        "backend": "sqlite",
        "sqlite_path": str(sqlite_path.resolve()),
        "transaction_committed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and atomically replace the YOBI catalog from an approved package."
    )
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--backend", choices=("oracle", "sqlite"), required=True)
    parser.add_argument("--sqlite-path", type=Path)
    parser.add_argument("--expected-package-sha256")
    parser.add_argument("--expected-normalization-count", type=int)
    parser.add_argument(
        "--embedding-provider",
        choices=("deterministic", "oci"),
        help=(
            "Oracle vector provider. Defaults to EMBEDDING_PROVIDER; production "
            "catalog writes reject the deterministic fallback."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    manifest, package_sha, diagnostics = validate_package(
        args.package,
        args.expected_package_sha256,
        args.expected_normalization_count,
    )
    settings = Settings()
    oracle_provider: EmbeddingProvider | None = None
    if args.backend == "oracle" and not args.validate_only:
        oracle_provider = choose_embedding_provider(
            settings,
            args.embedding_provider or settings.embedding_provider,
        )
        if (
            args.apply
            and settings.app_env == "production"
            and isinstance(oracle_provider, DeterministicEmbeddingProvider)
        ):
            raise RuntimeError("PRODUCTION_EXTERNAL_IMPORT_REQUIRES_OCI_EMBEDDINGS")
    if args.validate_only:
        result = {
            "backend": None,
            "catalog_import_id": manifest["catalog_import_id"],
            "catalog_release_id": manifest["catalog_release_id"],
            "package_sha256": package_sha,
            "pass": True,
            "transaction_committed": False,
        }
    elif args.verify_only:
        if args.backend == "oracle":
            if oracle_provider is None:
                raise RuntimeError("ORACLE_EMBEDDING_PROVIDER_REQUIRED")
            result = verify_only_oracle(
                settings,
                manifest,
                package_sha,
                oracle_provider,
            )
        else:
            if args.sqlite_path is None:
                raise RuntimeError("SQLITE_PATH_REQUIRED")
            result = verify_only_sqlite(args.sqlite_path, manifest, package_sha)
    elif args.backend == "sqlite":
        if args.sqlite_path is None:
            raise RuntimeError("SQLITE_PATH_REQUIRED")
        result = apply_sqlite(
            args.sqlite_path,
            args.package,
            manifest,
            package_sha,
            diagnostics,
        )
    else:
        if oracle_provider is None:
            raise RuntimeError("ORACLE_EMBEDDING_PROVIDER_REQUIRED")
        vector_cache_path, vector_count = prepare_vector_cache(
            args.package,
            oracle_provider,
        )
        try:
            if vector_count != int(manifest["expected_counts"]["menu"]):
                raise RuntimeError("VECTOR_COUNT_MISMATCH")
            result = apply_oracle(
                settings,
                args.package,
                vector_cache_path,
                manifest,
                package_sha,
                diagnostics,
                oracle_provider,
            )
        finally:
            vector_cache_path.unlink(missing_ok=True)
    result["package_validation"] = diagnostics
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
