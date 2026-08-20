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
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(SCRIPTS))

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
from app.genai.presentation_generator import source_translation_is_safe
from protected_base_fingerprint import (
    oracle_base_fingerprint,
    protected_base_fingerprint,
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
            SELECT menu.menu_id,menu.name_en,menu.name_ko,
                   COALESCE(group_concat(feature.option_code,' '),'') AS feature_codes
            FROM menu_wiki_eligibility eligibility
            JOIN menu ON menu.menu_id=eligibility.menu_id
            LEFT JOIN menu_preference_feature feature
              ON feature.knowledge_release_id=eligibility.knowledge_release_id
             AND feature.menu_id=eligibility.menu_id
             AND feature.support_status='SUPPORTED'
            WHERE eligibility.knowledge_release_id=?
            GROUP BY menu.menu_id,menu.name_en,menu.name_ko
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
                name_en=str(row["name_en"] or ""),
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


def _synthetic_family_id(previous_family_id: str, release_id: str, manifest: str) -> str:
    """Create a distinct bounded family ID even when the previous ID is already 160 chars."""

    digest = hashlib.sha256(
        f"{previous_family_id}\0{release_id}\0{manifest}".encode()
    ).hexdigest()[:16]
    suffix = f"-syn-{digest}"
    return f"{previous_family_id[: 160 - len(suffix)]}{suffix}"


def _database_text(value: Any) -> str:
    reader = getattr(value, "read", None)
    return str(reader() if callable(reader) else value or "")


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
            SELECT menu.menu_id,menu.name_en,menu.name_ko,
                   LISTAGG(feature.option_code,' ') WITHIN GROUP (ORDER BY feature.option_code)
            FROM menu_wiki_eligibility eligibility
            JOIN menu ON menu.menu_id=eligibility.menu_id
            LEFT JOIN menu_preference_feature feature
              ON feature.knowledge_release_id=eligibility.knowledge_release_id
             AND feature.menu_id=eligibility.menu_id
             AND feature.support_status='SUPPORTED'
            WHERE eligibility.knowledge_release_id=:knowledge_release_id
            GROUP BY menu.menu_id,menu.name_en,menu.name_ko
            ORDER BY menu.menu_id
            """,
            knowledge_release_id=knowledge_release_id,
        )
        menus = [
            EnrichmentMenu(
                str(menu_id),
                str(name_ko),
                tuple(str(features or "").split()),
                str(name_en or ""),
            )
            for menu_id, name_en, name_ko, features in cursor.fetchall()
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


_ORACLE_PRIMARY_KEYS = {
    "synthetic_country_profile": ("release_id", "country_code"),
    "synthetic_country_spice_example": ("release_id", "country_code", "language_code"),
    "synthetic_menu_profile": ("release_id", "menu_id"),
    "synthetic_option_profile": ("release_id", "option_item_id"),
    "synthetic_menu_country_preference": ("release_id", "menu_id", "country_code"),
    "synthetic_review_snippet": ("review_id",),
    "menu_localization": ("release_id", "menu_id", "language_code"),
    "menu_source_description_localization": (
        "release_id",
        "menu_id",
        "language_code",
    ),
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


def _copy_active_menu_localizations_oracle(
    cursor: oracledb.Cursor, *, release_id: str
) -> None:
    """Carry forward validated titles and same-catalog source translations.

    Presentation prose caches remain release-local. Restaurant-description translations are
    immutable-source localizations, so the newest validated value from the same catalog can be
    reused safely when a later presentation call is unavailable or rejects one menu.
    """
    cursor.execute(
        """
        MERGE INTO menu_localization target
        USING (
          SELECT :release_id release_id,localization.menu_id,
                 localization.language_code,localization.display_name,
                 localization.model_id,localization.prompt_version,
                 localization.wiki_evidence_ids_json,localization.source_hash,
                 localization.validation_status,localization.generated_at
          FROM recommendation_runtime_state runtime_state
          JOIN recommendation_release_family family
            ON family.release_family_id=runtime_state.active_release_family_id
          JOIN menu_localization localization
            ON localization.release_id=family.synthetic_enrichment_release_id
          JOIN synthetic_menu_profile target_profile
            ON target_profile.release_id=:release_id
           AND target_profile.menu_id=localization.menu_id
          WHERE runtime_state.state_key='ACTIVE'
            AND localization.validation_status='VALID'
            AND localization.language_code IN ('en','ja')
        ) source
        ON (target.release_id=source.release_id
            AND target.menu_id=source.menu_id
            AND target.language_code=source.language_code)
        WHEN NOT MATCHED THEN INSERT (
          release_id,menu_id,language_code,display_name,model_id,prompt_version,
          wiki_evidence_ids_json,source_hash,validation_status,generated_at
        ) VALUES (
          source.release_id,source.menu_id,source.language_code,source.display_name,
          source.model_id,source.prompt_version,source.wiki_evidence_ids_json,
          source.source_hash,source.validation_status,source.generated_at
        )
        """,
        release_id=release_id,
    )
    cursor.execute(
        """
        SELECT localization.menu_id,localization.language_code,
               localization.description_text,localization.model_id,
               localization.prompt_version,localization.source_hash,
               localization.validation_status,localization.generated_at,
               menu.description
        FROM recommendation_runtime_state runtime_state
        JOIN recommendation_release_family active_family
          ON active_family.release_family_id=runtime_state.active_release_family_id
        JOIN synthetic_menu_profile target_profile
          ON target_profile.release_id=:release_id
        JOIN menu ON menu.menu_id=target_profile.menu_id
        JOIN synthetic_enrichment_release source_release
          ON source_release.catalog_release_id=active_family.catalog_release_id
         AND source_release.status IN ('READY','ACTIVE','RETIRED')
         AND source_release.release_id<>:release_id
        JOIN menu_source_description_localization localization
          ON localization.release_id=source_release.release_id
         AND localization.menu_id=target_profile.menu_id
        WHERE runtime_state.state_key='ACTIVE'
          AND localization.validation_status='VALID'
          AND localization.language_code IN ('en','ja')
        ORDER BY localization.menu_id,localization.language_code,
                 localization.generated_at DESC NULLS LAST,
                 localization.release_id DESC
        """,
        release_id=release_id,
    )
    source_rows: list[dict[str, Any]] = []
    accepted_keys: set[tuple[str, str]] = set()
    for row in cursor.fetchall():
        menu_id = str(row[0])
        language_code = str(row[1])
        key = (menu_id, language_code)
        if key in accepted_keys:
            continue
        description_text = _database_text(row[2])
        source_description = _database_text(row[8])
        if not source_translation_is_safe(
            source_description, description_text, language_code
        ):
            continue
        source_rows.append(
            {
                "release_id": release_id,
                "menu_id": menu_id,
                "language_code": language_code,
                "description_text": description_text,
                "model_id": str(row[3]),
                "prompt_version": str(row[4]),
                "source_hash": str(row[5]),
                "validation_status": str(row[6]),
                "generated_at": row[7],
            }
        )
        accepted_keys.add(key)
    _oracle_merge_many(
        cursor,
        "menu_source_description_localization",
        source_rows,
    )


def _copy_active_menu_localizations_sqlite(
    connection: sqlite3.Connection, *, release_id: str
) -> None:
    """SQLite equivalent of the release-to-release localization carry-forward."""
    connection.execute(
        """
        INSERT INTO menu_localization(
          release_id,menu_id,language_code,display_name,model_id,prompt_version,
          wiki_evidence_ids_json,source_hash,validation_status,generated_at
        )
        SELECT ?,localization.menu_id,localization.language_code,
               localization.display_name,localization.model_id,
               localization.prompt_version,localization.wiki_evidence_ids_json,
               localization.source_hash,localization.validation_status,
               localization.generated_at
        FROM recommendation_runtime_state runtime_state
        JOIN recommendation_release_family family
          ON family.release_family_id=runtime_state.active_release_family_id
        JOIN menu_localization localization
          ON localization.release_id=family.synthetic_enrichment_release_id
        JOIN synthetic_menu_profile target_profile
          ON target_profile.release_id=?
         AND target_profile.menu_id=localization.menu_id
        WHERE runtime_state.state_key='ACTIVE'
          AND localization.validation_status='VALID'
          AND localization.language_code IN ('en','ja')
        ON CONFLICT(release_id,menu_id,language_code) DO NOTHING
        """,
        (release_id, release_id),
    )
    candidates = connection.execute(
        """
        SELECT localization.menu_id,localization.language_code,
               localization.description_text,localization.model_id,
               localization.prompt_version,localization.source_hash,
               localization.validation_status,localization.generated_at,
               menu.description
        FROM recommendation_runtime_state runtime_state
        JOIN recommendation_release_family active_family
          ON active_family.release_family_id=runtime_state.active_release_family_id
        JOIN synthetic_menu_profile target_profile
          ON target_profile.release_id=?
        JOIN menu ON menu.menu_id=target_profile.menu_id
        JOIN synthetic_enrichment_release source_release
          ON source_release.catalog_release_id=active_family.catalog_release_id
         AND source_release.status IN ('READY','ACTIVE','RETIRED')
         AND source_release.release_id<>?
        JOIN menu_source_description_localization localization
          ON localization.release_id=source_release.release_id
         AND localization.menu_id=target_profile.menu_id
        WHERE runtime_state.state_key='ACTIVE'
          AND localization.validation_status='VALID'
          AND localization.language_code IN ('en','ja')
        ORDER BY localization.menu_id,localization.language_code,
                 localization.generated_at DESC,localization.release_id DESC
        """,
        (release_id, release_id),
    ).fetchall()
    source_rows: list[dict[str, Any]] = []
    accepted_keys: set[tuple[str, str]] = set()
    for row in candidates:
        menu_id = str(row[0])
        language_code = str(row[1])
        key = (menu_id, language_code)
        if key in accepted_keys:
            continue
        description_text = str(row[2])
        if not source_translation_is_safe(
            str(row[8] or ""), description_text, language_code
        ):
            continue
        source_rows.append(
            {
                "release_id": release_id,
                "menu_id": menu_id,
                "language_code": language_code,
                "description_text": description_text,
                "model_id": str(row[3]),
                "prompt_version": str(row[4]),
                "source_hash": str(row[5]),
                "validation_status": str(row[6]),
                "generated_at": str(row[7]),
            }
        )
        accepted_keys.add(key)
    _upsert_many(connection, "menu_source_description_localization", source_rows)


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
        family_id = _synthetic_family_id(previous_family_id, release_id, manifest)
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
    example_rows = [dict(row, generated_at=generated_at) for row in rows["country_examples"]]
    rows = dict(rows, localizations=localized_rows, country_examples=example_rows)
    with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
        before = oracle_base_fingerprint(connection)
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
            ("synthetic_country_spice_example", "country_examples"),
            ("synthetic_menu_profile", "menus"),
            ("synthetic_option_profile", "options"),
            ("synthetic_menu_country_preference", "preferences"),
            ("synthetic_review_snippet", "reviews"),
            ("menu_localization", "localizations"),
        ):
            _oracle_merge_many(cursor, table, rows[key])
        _copy_active_menu_localizations_oracle(cursor, release_id=release_id)
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
        after = oracle_base_fingerprint(connection)
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
    for row in rows["country_examples"]:
        row["generated_at"] = now
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        base_fingerprint_before = protected_base_fingerprint(connection)
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
            ("synthetic_country_spice_example", "country_examples"),
            ("synthetic_menu_profile", "menus"),
            ("synthetic_option_profile", "options"),
            ("synthetic_menu_country_preference", "preferences"),
            ("synthetic_review_snippet", "reviews"),
            ("menu_localization", "localizations"),
        ):
            _upsert_many(connection, table, rows[key])
        _copy_active_menu_localizations_sqlite(connection, release_id=release_id)
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
                else _synthetic_family_id(
                    str(family["release_family_id"]), release_id, manifest
                )
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
        base_fingerprint_after = protected_base_fingerprint(connection)
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
