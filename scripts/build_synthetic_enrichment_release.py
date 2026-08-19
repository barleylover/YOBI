#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.demo_enrichment import (
    GENERATOR_VERSION,
    EnrichmentMenu,
    EnrichmentOption,
    build_enrichment_rows,
    manifest_sha256,
    validate_enrichment_rows,
)


def _load_sqlite_inputs(path: Path) -> tuple[str, str, list[EnrichmentMenu], list[EnrichmentOption]]:
    SQLiteYobiRepository(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        active = connection.execute(
            """
            SELECT family.catalog_release_id,family.knowledge_release_id
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            WHERE state.state_key='ACTIVE'
            """
        ).fetchone()
        if active is None:
            raise RuntimeError("ACTIVE_RECOMMENDATION_FAMILY_REQUIRED")
        menu_rows = connection.execute(
            """
            SELECT menu.menu_id,menu.name_ko,
                   COALESCE(group_concat(feature.option_code,' '),'') AS feature_codes
            FROM menu_wiki_eligibility eligibility
            JOIN menu ON menu.menu_id=eligibility.menu_id
            LEFT JOIN menu_preference_feature feature
              ON feature.knowledge_release_id=eligibility.knowledge_release_id
             AND feature.menu_id=eligibility.menu_id
             AND feature.support_status='SUPPORTED'
            WHERE eligibility.knowledge_release_id=?
            GROUP BY menu.menu_id,menu.name_ko
            ORDER BY menu.menu_id
            """,
            (str(active["knowledge_release_id"]),),
        ).fetchall()
        menu_ids = {str(row["menu_id"]) for row in menu_rows}
        option_rows = connection.execute(
            """
            SELECT item.option_item_id,groups.menu_id,item.name_ko
            FROM menu_option_item item
            JOIN menu_option_group groups ON groups.option_group_id=item.option_group_id
            ORDER BY item.option_item_id
            """
        ).fetchall()
        menus = [
            EnrichmentMenu(
                menu_id=str(row["menu_id"]),
                name_ko=str(row["name_ko"]),
                feature_codes=tuple(str(row["feature_codes"] or "").split()),
            )
            for row in menu_rows
        ]
        options = [
            EnrichmentOption(
                option_item_id=str(row["option_item_id"]),
                menu_id=str(row["menu_id"]),
                name_ko=str(row["name_ko"]),
            )
            for row in option_rows
            if str(row["menu_id"]) in menu_ids
        ]
        return str(active["catalog_release_id"]), str(active["knowledge_release_id"]), menus, options


def _oracle_credentials(settings: Settings) -> tuple[str, str, str]:
    password = settings.db_password.get_secret_value()
    dsn = settings.adb_dsn.get_secret_value()
    if settings.db_username != "YOBI_APP" or not password or not dsn:
        raise RuntimeError("SYNTHETIC_ENRICHMENT_RUNTIME_CREDENTIALS_REQUIRED")
    return settings.db_username, password, dsn


def _load_oracle_inputs(
    settings: Settings,
) -> tuple[str, str, list[EnrichmentMenu], list[EnrichmentOption]]:
    user, password, dsn = _oracle_credentials(settings)
    with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT family.catalog_release_id,family.knowledge_release_id
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            WHERE state.state_key='ACTIVE'
            """
        )
        active = cursor.fetchone()
        if active is None:
            raise RuntimeError("ACTIVE_RECOMMENDATION_FAMILY_REQUIRED")
        catalog_release_id, knowledge_release_id = map(str, active)
        cursor.execute(
            """
            SELECT menu.menu_id,menu.name_ko,
                   LISTAGG(feature.option_code,' ') WITHIN GROUP (ORDER BY feature.option_code)
            FROM menu_wiki_eligibility eligibility
            JOIN menu ON menu.menu_id=eligibility.menu_id
            LEFT JOIN menu_preference_feature feature
              ON feature.knowledge_release_id=eligibility.knowledge_release_id
             AND feature.menu_id=eligibility.menu_id
             AND feature.support_status='SUPPORTED'
            WHERE eligibility.knowledge_release_id=:knowledge_release_id
            GROUP BY menu.menu_id,menu.name_ko
            ORDER BY menu.menu_id
            """,
            knowledge_release_id=knowledge_release_id,
        )
        menus = [
            EnrichmentMenu(str(menu_id), str(name_ko), tuple(str(features or "").split()))
            for menu_id, name_ko, features in cursor.fetchall()
        ]
        menu_ids = {menu.menu_id for menu in menus}
        cursor.execute(
            """
            SELECT item.option_item_id,groups.menu_id,item.name_ko
            FROM menu_option_item item
            JOIN menu_option_group groups ON groups.option_group_id=item.option_group_id
            JOIN menu_wiki_eligibility eligibility ON eligibility.menu_id=groups.menu_id
            WHERE eligibility.knowledge_release_id=:knowledge_release_id
            ORDER BY item.option_item_id
            """,
            knowledge_release_id=knowledge_release_id,
        )
        options = [
            EnrichmentOption(str(option_id), str(menu_id), str(name_ko))
            for option_id, menu_id, name_ko in cursor.fetchall()
            if str(menu_id) in menu_ids
        ]
    return catalog_release_id, knowledge_release_id, menus, options


def _upsert_many(
    connection: sqlite3.Connection,
    table: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ",".join(f":{column}" for column in columns)
    primary_keys = [
        str(row[1])
        for row in sorted(
            connection.execute(f"PRAGMA table_info({table})").fetchall(),
            key=lambda row: int(row[5]) if row[5] else 999,
        )
        if row[5]
    ]
    if not primary_keys:
        raise RuntimeError(f"SYNTHETIC_UPSERT_PRIMARY_KEY_REQUIRED:{table}")
    updates = ",".join(
        f"{column}=excluded.{column}" for column in columns if column not in primary_keys
    )
    connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({','.join(primary_keys)}) DO UPDATE SET {updates}",
        rows,
    )


_PROTECTED_BASE_TABLES = (
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


def _protected_base_fingerprint(connection: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    existing = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table in _PROTECTED_BASE_TABLES:
        if table not in existing:
            continue
        columns = [
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        ]
        digest.update(f"{table}:{','.join(columns)}\n".encode())
        order_by = ",".join(f'"{column}"' for column in columns)
        for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY {order_by}'):
            for value in row:
                if isinstance(value, bytes):
                    digest.update(value)
                else:
                    digest.update(str(value).encode("utf-8"))
                digest.update(b"\x1f")
            digest.update(b"\x1e")
    return digest.hexdigest()


_ORACLE_ID_COLUMNS = {
    "menu": ("menu_id",),
    "menu_source_detail": ("menu_id",),
    "menu_wiki_eligibility": ("knowledge_release_id", "menu_id"),
    "menu_embedding": ("menu_id",),
    "menu_semantic_embedding": (
        "catalog_release_id", "menu_id", "embedding_model", "embedding_version"
    ),
    "knowledge_document": ("release_id", "document_id"),
    "knowledge_chunk": ("release_id", "chunk_id"),
    "menu_concept_membership": ("knowledge_release_id", "menu_id", "concept_id"),
    "menu_dietary_attribute": ("menu_id", "attribute_id"),
    "option_dietary_conflict": ("option_item_id", "rule_code"),
    "option_ingredient_effect": (
        "release_id", "option_item_id", "ingredient_id", "effect"
    ),
}


def _oracle_base_fingerprint(connection: oracledb.Connection) -> str:
    """Hash stable identifiers and row counts without materializing vector LOBs."""
    digest = hashlib.sha256()
    cursor = connection.cursor()
    cursor.execute("SELECT LOWER(table_name) FROM user_tables")
    existing = {str(row[0]) for row in cursor.fetchall()}
    for table in _PROTECTED_BASE_TABLES:
        if table not in existing:
            continue
        id_columns = _ORACLE_ID_COLUMNS[table]
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


_ORACLE_PRIMARY_KEYS = {
    "synthetic_country_profile": ("release_id", "country_code"),
    "synthetic_menu_profile": ("release_id", "menu_id"),
    "synthetic_option_profile": ("release_id", "option_item_id"),
    "synthetic_menu_country_preference": ("release_id", "menu_id", "country_code"),
    "synthetic_review_snippet": ("review_id",),
    "menu_localization": ("release_id", "menu_id", "language_code"),
}


def _oracle_merge_many(
    cursor: oracledb.Cursor, table: str, rows: list[dict[str, Any]]
) -> None:
    if not rows:
        return
    columns = list(rows[0])
    keys = _ORACLE_PRIMARY_KEYS[table]
    source = ",".join(f":{column} {column}" for column in columns)
    match = " AND ".join(f"target.{key}=source.{key}" for key in keys)
    updates = ",".join(
        f"target.{column}=source.{column}" for column in columns if column not in keys
    )
    sql = (
        f"MERGE INTO {table} target USING (SELECT {source} FROM dual) source "
        f"ON ({match}) WHEN MATCHED THEN UPDATE SET {updates} "
        f"WHEN NOT MATCHED THEN INSERT ({','.join(columns)}) "
        f"VALUES ({','.join(f'source.{column}' for column in columns)})"
    )
    cursor.executemany(sql, rows)


def _oracle_clone_and_activate_family(
    connection: oracledb.Connection,
    *,
    release_id: str,
    manifest: str,
) -> str:
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT active_release_family_id FROM recommendation_runtime_state
        WHERE state_key='ACTIVE' FOR UPDATE
        """
    )
    active_row = cursor.fetchone()
    if active_row is None:
        raise RuntimeError("ACTIVE_RECOMMENDATION_FAMILY_REQUIRED")
    previous_family_id = str(active_row[0])
    cursor.execute(
        "SELECT * FROM recommendation_release_family WHERE release_family_id=:family_id",
        family_id=previous_family_id,
    )
    values = cursor.fetchone()
    if values is None:
        raise RuntimeError("ACTIVE_RECOMMENDATION_FAMILY_REQUIRED")
    description = cursor.description
    if description is None:
        raise RuntimeError("ACTIVE_RECOMMENDATION_FAMILY_SCHEMA_REQUIRED")
    columns = [str(item[0]).lower() for item in description]
    payload = dict(zip(columns, values))
    if payload.get("synthetic_enrichment_release_id") == release_id:
        family_id = previous_family_id
    else:
        family_id = f"{previous_family_id}-syn-{manifest[:12]}"[:160]
        payload.update(
            release_family_id=family_id,
            synthetic_enrichment_release_id=release_id,
            status="READY",
            activated_at=None,
        )
        insert_columns = list(payload)
        cursor.execute(
            "SELECT COUNT(*) FROM recommendation_release_family "
            "WHERE release_family_id=:family_id",
            family_id=family_id,
        )
        if int(cursor.fetchone()[0]) == 0:
            cursor.execute(
                f"INSERT INTO recommendation_release_family ({','.join(insert_columns)}) "
                f"VALUES ({','.join(':' + column for column in insert_columns)})",
                payload,
            )
    if previous_family_id != family_id:
        cursor.execute(
            "UPDATE recommendation_release_family SET status='READY' "
            "WHERE release_family_id=:family_id AND status='ACTIVE'",
            family_id=previous_family_id,
        )
    cursor.execute(
        "UPDATE recommendation_release_family SET status='ACTIVE',activated_at=SYSTIMESTAMP "
        "WHERE release_family_id=:family_id",
        family_id=family_id,
    )
    cursor.execute(
        "UPDATE synthetic_enrichment_release SET status='READY' "
        "WHERE status='ACTIVE' AND release_id<>:release_id",
        release_id=release_id,
    )
    cursor.execute(
        "UPDATE synthetic_enrichment_release SET status='ACTIVE',activated_at=SYSTIMESTAMP "
        "WHERE release_id=:release_id",
        release_id=release_id,
    )
    cursor.execute(
        """
        MERGE INTO synthetic_enrichment_runtime_state target
        USING (SELECT 'ACTIVE' state_key FROM dual) source
        ON (target.state_key=source.state_key)
        WHEN MATCHED THEN UPDATE SET target.active_release_id=:release_id,
          target.updated_at=SYSTIMESTAMP
        WHEN NOT MATCHED THEN INSERT (state_key,active_release_id,updated_at)
          VALUES ('ACTIVE',:release_id,SYSTIMESTAMP)
        """,
        release_id=release_id,
    )
    cursor.execute(
        "UPDATE recommendation_runtime_state SET active_release_family_id=:family_id,"
        "updated_at=SYSTIMESTAMP WHERE state_key='ACTIVE'",
        family_id=family_id,
    )
    return family_id


def _apply_oracle(
    settings: Settings,
    *,
    release_id: str,
    catalog_release_id: str,
    knowledge_release_id: str,
    seed: str,
    rows: dict[str, list[dict[str, Any]]],
    manifest: str,
    activate: bool,
) -> tuple[str, str, str | None]:
    user, password, dsn = _oracle_credentials(settings)
    generated_at = datetime.now(timezone.utc)
    localized_rows = [dict(row, generated_at=generated_at) for row in rows["localizations"]]
    rows = dict(rows, localizations=localized_rows)
    with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
        before = _oracle_base_fingerprint(connection)
        cursor = connection.cursor()
        cursor.execute(
            """
            MERGE INTO synthetic_enrichment_release target
            USING (SELECT :release_id release_id FROM dual) source
            ON (target.release_id=source.release_id)
            WHEN MATCHED THEN UPDATE SET
              target.catalog_release_id=:catalog_release_id,
              target.knowledge_release_id=:knowledge_release_id,
              target.seed_value=:seed_value,
              target.generator_version=:generator_version,
              target.manifest_sha256=:manifest_sha256
            WHEN NOT MATCHED THEN INSERT (
              release_id,catalog_release_id,knowledge_release_id,seed_value,
              generator_version,manifest_sha256,status,created_at
            ) VALUES (
              :release_id,:catalog_release_id,:knowledge_release_id,:seed_value,
              :generator_version,:manifest_sha256,'LOADING',SYSTIMESTAMP
            )
            """,
            release_id=release_id,
            catalog_release_id=catalog_release_id,
            knowledge_release_id=knowledge_release_id,
            seed_value=seed,
            generator_version=GENERATOR_VERSION,
            manifest_sha256=manifest,
        )
        for table, key in (
            ("synthetic_country_profile", "countries"),
            ("synthetic_menu_profile", "menus"),
            ("synthetic_option_profile", "options"),
            ("synthetic_menu_country_preference", "preferences"),
            ("synthetic_review_snippet", "reviews"),
            ("menu_localization", "localizations"),
        ):
            _oracle_merge_many(cursor, table, rows[key])
        cursor.execute(
            """
            SELECT COUNT(*) FROM menu_localization
            WHERE release_id=:release_id AND validation_status='VALID'
              AND language_code IN ('ko','en','ja')
            """,
            release_id=release_id,
        )
        ready = int(cursor.fetchone()[0]) == len(rows["menus"]) * 3
        cursor.execute(
            "UPDATE synthetic_enrichment_release SET status=:status "
            "WHERE release_id=:release_id AND status<>'ACTIVE'",
            status="READY" if ready else "LOADING",
            release_id=release_id,
        )
        family_id = None
        if activate:
            if not ready:
                raise RuntimeError("LOCALIZATION_RELEASE_NOT_READY")
            family_id = _oracle_clone_and_activate_family(
                connection, release_id=release_id, manifest=manifest
            )
        after = _oracle_base_fingerprint(connection)
        if before != after:
            connection.rollback()
            raise RuntimeError("PROTECTED_BASE_TABLES_CHANGED")
        connection.commit()
    return before, after, family_id


def _sync_oracle_runtime_to_active_family(settings: Settings) -> str | None:
    user, password, dsn = _oracle_credentials(settings)
    with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT family.synthetic_enrichment_release_id
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            WHERE state.state_key='ACTIVE'
            FOR UPDATE
            """
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("ACTIVE_RECOMMENDATION_FAMILY_REQUIRED")
        release_id = str(row[0]) if row[0] else None
        cursor.execute(
            "UPDATE synthetic_enrichment_release SET status='READY' WHERE status='ACTIVE'"
        )
        if release_id is None:
            cursor.execute(
                "DELETE FROM synthetic_enrichment_runtime_state WHERE state_key='ACTIVE'"
            )
        else:
            cursor.execute(
                "UPDATE synthetic_enrichment_release SET status='ACTIVE',"
                "activated_at=SYSTIMESTAMP WHERE release_id=:release_id",
                release_id=release_id,
            )
            cursor.execute(
                """
                MERGE INTO synthetic_enrichment_runtime_state target
                USING (SELECT 'ACTIVE' state_key FROM dual) source
                ON (target.state_key=source.state_key)
                WHEN MATCHED THEN UPDATE SET target.active_release_id=:release_id,
                  target.updated_at=SYSTIMESTAMP
                WHEN NOT MATCHED THEN INSERT (state_key,active_release_id,updated_at)
                  VALUES ('ACTIVE',:release_id,SYSTIMESTAMP)
                """,
                release_id=release_id,
            )
        connection.commit()
    return release_id


def _apply_sqlite(
    path: Path,
    *,
    release_id: str,
    catalog_release_id: str,
    knowledge_release_id: str,
    seed: str,
    rows: dict[str, list[dict[str, Any]]],
    manifest: str,
    activate: bool,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc).isoformat()
    for row in rows["localizations"]:
        row["generated_at"] = now
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        base_fingerprint_before = _protected_base_fingerprint(connection)
        connection.execute(
            """
            INSERT INTO synthetic_enrichment_release(
              release_id,catalog_release_id,knowledge_release_id,seed_value,
              generator_version,manifest_sha256,status,created_at,activated_at
            ) VALUES (?,?,?,?,?,?,?, ?,NULL)
            ON CONFLICT(release_id) DO UPDATE SET
              catalog_release_id=excluded.catalog_release_id,
              knowledge_release_id=excluded.knowledge_release_id,
              seed_value=excluded.seed_value,
              generator_version=excluded.generator_version,
              manifest_sha256=excluded.manifest_sha256
            """,
            (
                release_id,
                catalog_release_id,
                knowledge_release_id,
                seed,
                GENERATOR_VERSION,
                manifest,
                "LOADING",
                now,
            ),
        )
        for table, key in (
            ("synthetic_country_profile", "countries"),
            ("synthetic_menu_profile", "menus"),
            ("synthetic_option_profile", "options"),
            ("synthetic_menu_country_preference", "preferences"),
            ("synthetic_review_snippet", "reviews"),
            ("menu_localization", "localizations"),
        ):
            _upsert_many(connection, table, rows[key])
        eligible_count = len(rows["menus"])
        valid_localization_count = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM menu_localization
                WHERE release_id=? AND validation_status='VALID'
                  AND language_code IN ('ko','en','ja')
                """,
                (release_id,),
            ).fetchone()[0]
        )
        localizations_ready = valid_localization_count == eligible_count * 3
        active_release = connection.execute(
            """
            SELECT active_release_id FROM synthetic_enrichment_runtime_state
            WHERE state_key='ACTIVE'
            """
        ).fetchone()
        release_is_active = bool(active_release and active_release[0] == release_id)
        next_status = "ACTIVE" if release_is_active else "READY" if localizations_ready else "LOADING"
        connection.execute(
            "UPDATE synthetic_enrichment_release SET status=? WHERE release_id=?",
            (next_status, release_id),
        )
        if activate:
            if not localizations_ready:
                raise RuntimeError(
                    "LOCALIZATION_RELEASE_NOT_READY: generate all ko/en/ja menu names first"
                )
            family = connection.execute(
                """
                SELECT family.* FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE state.state_key='ACTIVE'
                """
            ).fetchone()
            if family is None:
                raise RuntimeError("ACTIVE_RECOMMENDATION_FAMILY_REQUIRED")
            family_columns = [str(column[1]) for column in connection.execute(
                "PRAGMA table_info(recommendation_release_family)"
            ).fetchall()]
            active_family_id = (
                str(family["release_family_id"])
                if family["synthetic_enrichment_release_id"] == release_id
                else f"{family['release_family_id']!s}-syn-{manifest[:12]}"[:160]
            )
            family_payload = {column: family[column] for column in family_columns}
            family_payload.update(
                {
                    "release_family_id": active_family_id,
                    "synthetic_enrichment_release_id": release_id,
                    "status": "ACTIVE",
                    "activated_at": now,
                }
            )
            columns = list(family_payload)
            placeholders = ",".join("?" for _ in columns)
            updates = ",".join(
                f"{column}=excluded.{column}"
                for column in columns
                if column != "release_family_id"
            )
            connection.execute(
                f"INSERT INTO recommendation_release_family ({','.join(columns)}) "
                f"VALUES ({placeholders}) ON CONFLICT(release_family_id) DO UPDATE SET {updates}",
                [family_payload[column] for column in columns],
            )
            connection.execute(
                "UPDATE recommendation_release_family SET status='READY' "
                "WHERE status='ACTIVE' AND release_family_id<>?",
                (active_family_id,),
            )
            connection.execute(
                """
                INSERT INTO synthetic_enrichment_runtime_state(state_key,active_release_id,updated_at)
                VALUES ('ACTIVE',?,?)
                ON CONFLICT(state_key) DO UPDATE SET
                  active_release_id=excluded.active_release_id,updated_at=excluded.updated_at
                """,
                (release_id, now),
            )
            connection.execute(
                "UPDATE synthetic_enrichment_release SET status='ACTIVE',activated_at=? "
                "WHERE release_id=?",
                (now, release_id),
            )
            connection.execute(
                """
                INSERT INTO recommendation_runtime_state(
                  state_key,active_release_family_id,updated_at
                ) VALUES ('ACTIVE',?,?)
                ON CONFLICT(state_key) DO UPDATE SET
                  active_release_family_id=excluded.active_release_family_id,
                  updated_at=excluded.updated_at
                """,
                (active_family_id, now),
            )
        base_fingerprint_after = _protected_base_fingerprint(connection)
        if base_fingerprint_before != base_fingerprint_after:
            raise RuntimeError("PROTECTED_BASE_TABLES_CHANGED")
    return base_fingerprint_before, base_fingerprint_after


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("sqlite", "oracle"), default="sqlite")
    parser.add_argument("--sqlite", type=Path, default=ROOT / "backend/data/yobi_demo.db")
    parser.add_argument("--release-id", default="synthetic-enrichment-v1")
    parser.add_argument("--seed", default="yobi-realistic-demo-v1")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--sync-runtime-to-active-family", action="store_true")
    args = parser.parse_args()
    if args.activate and not args.apply:
        parser.error("--activate requires --apply")

    if args.sync_runtime_to_active_family:
        if args.backend != "oracle" or args.apply or args.activate:
            parser.error("--sync-runtime-to-active-family requires Oracle and no apply flags")
        synced = _sync_oracle_runtime_to_active_family(Settings())
        print(json.dumps({"active_synthetic_enrichment_release_id": synced}, sort_keys=True))
        return

    settings = Settings() if args.backend == "oracle" else None
    if args.backend == "oracle":
        assert settings is not None
        catalog_release_id, knowledge_release_id, menus, options = _load_oracle_inputs(settings)
    else:
        catalog_release_id, knowledge_release_id, menus, options = _load_sqlite_inputs(args.sqlite)
    rows = build_enrichment_rows(
        release_id=args.release_id,
        seed=args.seed,
        menus=menus,
        options=options,
    )
    validate_enrichment_rows(rows, eligible_menu_count=len(menus))
    manifest = manifest_sha256(rows)
    base_fingerprint_before: str | None = None
    base_fingerprint_after: str | None = None
    family_id: str | None = None
    if args.apply:
        if args.backend == "oracle":
            assert settings is not None
            base_fingerprint_before, base_fingerprint_after, family_id = _apply_oracle(
                settings,
                release_id=args.release_id,
                catalog_release_id=catalog_release_id,
                knowledge_release_id=knowledge_release_id,
                seed=args.seed,
                rows=rows,
                manifest=manifest,
                activate=args.activate,
            )
        else:
            base_fingerprint_before, base_fingerprint_after = _apply_sqlite(
                args.sqlite,
                release_id=args.release_id,
                catalog_release_id=catalog_release_id,
                knowledge_release_id=knowledge_release_id,
                seed=args.seed,
                rows=rows,
                manifest=manifest,
                activate=args.activate,
            )
    print(
        json.dumps(
            {
                "release_id": args.release_id,
                "catalog_release_id": catalog_release_id,
                "knowledge_release_id": knowledge_release_id,
                "manifest_sha256": manifest,
                "counts": {key: len(value) for key, value in rows.items()},
                "applied": args.apply,
                "activated": args.activate,
                "recommendation_release_family_id": family_id,
                "protected_base_fingerprint_before": base_fingerprint_before,
                "protected_base_fingerprint_after": base_fingerprint_after,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
