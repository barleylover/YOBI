#!/usr/bin/env python3
"""Build complete KO/EN/JA option localizations without a runtime LLM.

The command is read-only unless ``--apply`` is supplied. It only writes the
release-scoped localization/enrichment tables and can atomically activate a
fully validated additive release with ``--activate``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import oracledb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.option_static_localization import (
    MODEL_ID,
    PROMPT_VERSION,
    localize_option_name,
)
from build_synthetic_enrichment_release import (
    _oracle_base_fingerprint,
    _oracle_clone_and_activate_family,
    _protected_base_fingerprint,
)

LANGUAGES = ("ko", "en", "ja")
SOURCE_COPY_MODEL = "SOURCE_COPY"
BATCH_SIZE = 2_000


def _source_hash(kind: str, object_id: str, name_en: str, name_ko: str) -> str:
    payload = json.dumps(
        {
            "kind": kind,
            "object_id": object_id,
            "name_en": name_en,
            "name_ko": name_ko,
            "prompt_version": PROMPT_VERSION,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _localized_rows(
    kind: str, source_rows: Iterable[tuple[str, str, str]]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for object_id, name_en, name_ko in source_rows:
        source_hash = _source_hash(kind, object_id, name_en, name_ko)
        for language_code in LANGUAGES:
            rows.append(
                {
                    "object_id": object_id,
                    "language_code": language_code,
                    "display_name": localize_option_name(name_ko, language_code),
                    "model_id": (
                        SOURCE_COPY_MODEL if language_code == "ko" else MODEL_ID
                    ),
                    "source_hash": source_hash,
                }
            )
    return rows


def _manifest(
    base_manifest: str,
    menu_rows: Iterable[tuple[str, str, str, str]],
    group_rows: Iterable[dict[str, str]],
    item_rows: Iterable[dict[str, str]],
) -> str:
    digest = hashlib.sha256(f"{base_manifest}|{PROMPT_VERSION}\n".encode())
    for menu_id, language_code, display_name, source_hash in sorted(menu_rows):
        digest.update(
            f"M|{menu_id}|{language_code}|{display_name}|{source_hash}\n".encode()
        )
    for prefix, rows in (("G", group_rows), ("I", item_rows)):
        for row in sorted(
            rows, key=lambda value: (value["object_id"], value["language_code"])
        ):
            digest.update(
                (
                    f"{prefix}|{row['object_id']}|{row['language_code']}|"
                    f"{row['display_name']}|{row['source_hash']}\n"
                ).encode()
            )
    return digest.hexdigest()


def _validate_generated(
    groups: list[tuple[str, str, str]],
    items: list[tuple[str, str, str]],
    group_rows: list[dict[str, str]],
    item_rows: list[dict[str, str]],
) -> None:
    expected_groups = len(groups) * len(LANGUAGES)
    expected_items = len(items) * len(LANGUAGES)
    if len(group_rows) != expected_groups or len(item_rows) != expected_items:
        raise RuntimeError("OPTION_LOCALIZATION_GENERATED_COUNT_MISMATCH")
    for row in (*group_rows, *item_rows):
        display_name = row["display_name"]
        if not display_name or len(display_name) > 300:
            raise RuntimeError("OPTION_LOCALIZATION_DISPLAY_NAME_INVALID")
        if row["language_code"] in {"en", "ja"} and re.search(r"[가-힣]", display_name):
            raise RuntimeError("OPTION_LOCALIZATION_HANGUL_REMAINS")


def _sqlite_context(
    connection: sqlite3.Connection, release_id: str
) -> tuple[str, str, str, int]:
    target = connection.execute(
        "SELECT knowledge_release_id,manifest_sha256 FROM synthetic_enrichment_release "
        "WHERE release_id=?",
        (release_id,),
    ).fetchone()
    if target is None:
        raise RuntimeError("SYNTHETIC_ENRICHMENT_RELEASE_NOT_FOUND")
    active = connection.execute(
        """
        SELECT family.synthetic_enrichment_release_id
        FROM recommendation_runtime_state state
        JOIN recommendation_release_family family
          ON family.release_family_id=state.active_release_family_id
        WHERE state.state_key='ACTIVE'
        """
    ).fetchone()
    source_release_id = str(active[0]) if active and active[0] else release_id
    eligible_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM menu_wiki_eligibility WHERE knowledge_release_id=?",
            (str(target[0]),),
        ).fetchone()[0]
    )
    return str(target[0]), str(target[1]), source_release_id, eligible_count


def _sqlite_sources(
    connection: sqlite3.Connection, knowledge_release_id: str
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    groups = [
        (str(row[0]), str(row[1]), str(row[2]))
        for row in connection.execute(
            """
            SELECT groups.option_group_id,groups.name_en,groups.name_ko
            FROM menu_option_group groups
            JOIN menu_wiki_eligibility eligibility ON eligibility.menu_id=groups.menu_id
            WHERE eligibility.knowledge_release_id=? ORDER BY groups.option_group_id
            """,
            (knowledge_release_id,),
        ).fetchall()
    ]
    items = [
        (str(row[0]), str(row[1]), str(row[2]))
        for row in connection.execute(
            """
            SELECT item.option_item_id,item.name_en,item.name_ko
            FROM menu_option_item item
            JOIN menu_option_group groups ON groups.option_group_id=item.option_group_id
            JOIN menu_wiki_eligibility eligibility ON eligibility.menu_id=groups.menu_id
            WHERE eligibility.knowledge_release_id=? ORDER BY item.option_item_id
            """,
            (knowledge_release_id,),
        ).fetchall()
    ]
    return groups, items


def _copy_sqlite_menu_localizations(
    connection: sqlite3.Connection, source_release_id: str, release_id: str
) -> None:
    if source_release_id == release_id:
        return
    connection.execute(
        """
        INSERT INTO menu_localization(
          release_id,menu_id,language_code,display_name,model_id,prompt_version,
          wiki_evidence_ids_json,source_hash,validation_status,generated_at
        )
        SELECT ?,menu_id,language_code,display_name,model_id,prompt_version,
               wiki_evidence_ids_json,source_hash,validation_status,generated_at
        FROM menu_localization WHERE release_id=? AND validation_status='VALID'
        ON CONFLICT(release_id,menu_id,language_code) DO UPDATE SET
          display_name=excluded.display_name,model_id=excluded.model_id,
          prompt_version=excluded.prompt_version,
          wiki_evidence_ids_json=excluded.wiki_evidence_ids_json,
          source_hash=excluded.source_hash,validation_status=excluded.validation_status,
          generated_at=excluded.generated_at
        """,
        (release_id, source_release_id),
    )


def _upsert_sqlite_options(
    connection: sqlite3.Connection,
    table: str,
    id_column: str,
    release_id: str,
    rows: list[dict[str, str]],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        f"""
        INSERT INTO {table}(
          release_id,{id_column},language_code,display_name,model_id,source_hash,generated_at
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(release_id,{id_column},language_code) DO UPDATE SET
          display_name=excluded.display_name,model_id=excluded.model_id,
          source_hash=excluded.source_hash,generated_at=excluded.generated_at
        """,
        [
            (
                release_id,
                row["object_id"],
                row["language_code"],
                row["display_name"],
                row["model_id"],
                row["source_hash"],
                now,
            )
            for row in rows
        ],
    )


def _oracle_credentials(settings: Settings) -> tuple[str, str, str]:
    password = settings.db_password.get_secret_value()
    dsn = settings.adb_dsn.get_secret_value()
    if settings.db_username != "YOBI_APP" or not password or not dsn:
        raise RuntimeError("OPTION_LOCALIZATION_RUNTIME_CREDENTIALS_REQUIRED")
    return settings.db_username, password, dsn


def _oracle_context(
    connection: oracledb.Connection, release_id: str
) -> tuple[str, str, str, int]:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT knowledge_release_id,manifest_sha256 FROM synthetic_enrichment_release "
        "WHERE release_id=:release_id",
        release_id=release_id,
    )
    target = cursor.fetchone()
    if target is None:
        raise RuntimeError("SYNTHETIC_ENRICHMENT_RELEASE_NOT_FOUND")
    cursor.execute(
        """
        SELECT family.synthetic_enrichment_release_id
        FROM recommendation_runtime_state state
        JOIN recommendation_release_family family
          ON family.release_family_id=state.active_release_family_id
        WHERE state.state_key='ACTIVE'
        """
    )
    active = cursor.fetchone()
    source_release_id = str(active[0]) if active and active[0] else release_id
    cursor.execute(
        "SELECT COUNT(*) FROM menu_wiki_eligibility "
        "WHERE knowledge_release_id=:knowledge_release_id",
        knowledge_release_id=str(target[0]),
    )
    eligible_count = int(cursor.fetchone()[0])
    return str(target[0]), str(target[1]), source_release_id, eligible_count


def _oracle_sources(
    connection: oracledb.Connection, knowledge_release_id: str
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT groups.option_group_id,groups.name_en,groups.name_ko
        FROM menu_option_group groups
        JOIN menu_wiki_eligibility eligibility ON eligibility.menu_id=groups.menu_id
        WHERE eligibility.knowledge_release_id=:knowledge_release_id
        ORDER BY groups.option_group_id
        """,
        knowledge_release_id=knowledge_release_id,
    )
    groups = [(str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()]
    cursor.execute(
        """
        SELECT item.option_item_id,item.name_en,item.name_ko
        FROM menu_option_item item
        JOIN menu_option_group groups ON groups.option_group_id=item.option_group_id
        JOIN menu_wiki_eligibility eligibility ON eligibility.menu_id=groups.menu_id
        WHERE eligibility.knowledge_release_id=:knowledge_release_id
        ORDER BY item.option_item_id
        """,
        knowledge_release_id=knowledge_release_id,
    )
    items = [(str(row[0]), str(row[1]), str(row[2])) for row in cursor.fetchall()]
    return groups, items


def _copy_oracle_menu_localizations(
    connection: oracledb.Connection, source_release_id: str, release_id: str
) -> None:
    if source_release_id == release_id:
        return
    connection.cursor().execute(
        """
        MERGE INTO menu_localization target
        USING (
          SELECT :release_id release_id,menu_id,language_code,display_name,model_id,
                 prompt_version,wiki_evidence_ids_json,source_hash,validation_status,
                 generated_at
          FROM menu_localization
          WHERE release_id=:source_release_id AND validation_status='VALID'
        ) source
        ON (target.release_id=source.release_id AND target.menu_id=source.menu_id
            AND target.language_code=source.language_code)
        WHEN MATCHED THEN UPDATE SET
          target.display_name=source.display_name,target.model_id=source.model_id,
          target.prompt_version=source.prompt_version,
          target.wiki_evidence_ids_json=source.wiki_evidence_ids_json,
          target.source_hash=source.source_hash,
          target.validation_status=source.validation_status,
          target.generated_at=source.generated_at
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
        source_release_id=source_release_id,
    )


def _upsert_oracle_options(
    connection: oracledb.Connection,
    table: str,
    id_column: str,
    release_id: str,
    rows: list[dict[str, str]],
) -> None:
    sql = f"""
        MERGE INTO {table} target
        USING (
          SELECT :release_id release_id,:object_id {id_column},
                 :language_code language_code,:display_name display_name,
                 :model_id model_id,:source_hash source_hash,
                 :generated_at generated_at FROM dual
        ) source
        ON (target.release_id=source.release_id
            AND target.{id_column}=source.{id_column}
            AND target.language_code=source.language_code)
        WHEN MATCHED THEN UPDATE SET
          target.display_name=source.display_name,target.model_id=source.model_id,
          target.source_hash=source.source_hash,target.generated_at=source.generated_at
        WHEN NOT MATCHED THEN INSERT (
          release_id,{id_column},language_code,display_name,model_id,source_hash,generated_at
        ) VALUES (
          source.release_id,source.{id_column},source.language_code,
          source.display_name,source.model_id,source.source_hash,source.generated_at
        )
    """
    cursor = connection.cursor()
    generated_at = datetime.now(timezone.utc)
    for offset in range(0, len(rows), BATCH_SIZE):
        cursor.executemany(
            sql,
            [
                {**row, "release_id": release_id, "generated_at": generated_at}
                for row in rows[offset : offset + BATCH_SIZE]
            ],
        )


def _oracle_menu_manifest_rows(
    connection: oracledb.Connection, release_id: str
) -> list[tuple[str, str, str, str]]:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT menu_id,language_code,display_name,source_hash FROM menu_localization "
        "WHERE release_id=:release_id AND validation_status='VALID'",
        release_id=release_id,
    )
    return [
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in cursor.fetchall()
    ]


def _sqlite_menu_manifest_rows(
    connection: sqlite3.Connection, release_id: str
) -> list[tuple[str, str, str, str]]:
    return [
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in connection.execute(
            "SELECT menu_id,language_code,display_name,source_hash FROM menu_localization "
            "WHERE release_id=? AND validation_status='VALID'",
            (release_id,),
        ).fetchall()
    ]


def _validate_persisted_counts(
    menu_localizations: int,
    eligible_count: int,
    group_localizations: int,
    group_count: int,
    item_localizations: int,
    item_count: int,
) -> None:
    expected = (
        eligible_count * len(LANGUAGES),
        group_count * len(LANGUAGES),
        item_count * len(LANGUAGES),
    )
    actual = (menu_localizations, group_localizations, item_localizations)
    if actual != expected:
        raise RuntimeError(
            f"OPTION_LOCALIZATION_COVERAGE_MISMATCH:{actual!r}:{expected!r}"
        )


def _apply_sqlite(path: Path, release_id: str, activate: bool) -> dict[str, Any]:
    SQLiteYobiRepository(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        before = _protected_base_fingerprint(connection)
        knowledge_id, base_manifest, source_release_id, eligible_count = (
            _sqlite_context(connection, release_id)
        )
        groups, items = _sqlite_sources(connection, knowledge_id)
        group_rows = _localized_rows("GROUP", groups)
        item_rows = _localized_rows("ITEM", items)
        _validate_generated(groups, items, group_rows, item_rows)
        _copy_sqlite_menu_localizations(connection, source_release_id, release_id)
        _upsert_sqlite_options(
            connection,
            "option_group_localization",
            "option_group_id",
            release_id,
            group_rows,
        )
        _upsert_sqlite_options(
            connection,
            "option_item_localization",
            "option_item_id",
            release_id,
            item_rows,
        )
        menu_rows = _sqlite_menu_manifest_rows(connection, release_id)
        manifest = _manifest(base_manifest, menu_rows, group_rows, item_rows)
        counts = (
            len(menu_rows),
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM option_group_localization WHERE release_id=?",
                    (release_id,),
                ).fetchone()[0]
            ),
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM option_item_localization WHERE release_id=?",
                    (release_id,),
                ).fetchone()[0]
            ),
        )
        _validate_persisted_counts(
            counts[0], eligible_count, counts[1], len(groups), counts[2], len(items)
        )
        connection.execute(
            "UPDATE synthetic_enrichment_release SET manifest_sha256=?,status='READY' "
            "WHERE release_id=?",
            (manifest, release_id),
        )
        if activate:
            raise RuntimeError("SQLITE_ACTIVATION_USE_BUILD_ENRICHMENT_SCRIPT")
        after = _protected_base_fingerprint(connection)
        if before != after:
            raise RuntimeError("PROTECTED_BASE_TABLES_CHANGED")
    return {
        "release_id": release_id,
        "source_menu_localization_release_id": source_release_id,
        "eligible_menu_count": eligible_count,
        "option_group_count": len(groups),
        "option_item_count": len(items),
        "localization_counts": {
            "menu": counts[0],
            "option_group": counts[1],
            "option_item": counts[2],
        },
        "manifest_sha256": manifest,
        "protected_base_fingerprint_before": before,
        "protected_base_fingerprint_after": after,
        "activated": False,
    }


def _apply_oracle(
    settings: Settings, release_id: str, activate: bool
) -> dict[str, Any]:
    user, password, dsn = _oracle_credentials(settings)
    with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
        before = _oracle_base_fingerprint(connection)
        knowledge_id, base_manifest, source_release_id, eligible_count = (
            _oracle_context(connection, release_id)
        )
        groups, items = _oracle_sources(connection, knowledge_id)
        group_rows = _localized_rows("GROUP", groups)
        item_rows = _localized_rows("ITEM", items)
        _validate_generated(groups, items, group_rows, item_rows)
        _copy_oracle_menu_localizations(connection, source_release_id, release_id)
        _upsert_oracle_options(
            connection,
            "option_group_localization",
            "option_group_id",
            release_id,
            group_rows,
        )
        _upsert_oracle_options(
            connection,
            "option_item_localization",
            "option_item_id",
            release_id,
            item_rows,
        )
        menu_rows = _oracle_menu_manifest_rows(connection, release_id)
        manifest = _manifest(base_manifest, menu_rows, group_rows, item_rows)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM option_group_localization WHERE release_id=:release_id",
            release_id=release_id,
        )
        group_localizations = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT COUNT(*) FROM option_item_localization WHERE release_id=:release_id",
            release_id=release_id,
        )
        item_localizations = int(cursor.fetchone()[0])
        _validate_persisted_counts(
            len(menu_rows),
            eligible_count,
            group_localizations,
            len(groups),
            item_localizations,
            len(items),
        )
        cursor.execute(
            "UPDATE synthetic_enrichment_release SET manifest_sha256=:manifest,status='READY' "
            "WHERE release_id=:release_id",
            manifest=manifest,
            release_id=release_id,
        )
        family_id = None
        if activate:
            family_id = _oracle_clone_and_activate_family(
                connection, release_id=release_id, manifest=manifest
            )
        after = _oracle_base_fingerprint(connection)
        if before != after:
            connection.rollback()
            raise RuntimeError("PROTECTED_BASE_TABLES_CHANGED")
        connection.commit()
    return {
        "release_id": release_id,
        "source_menu_localization_release_id": source_release_id,
        "eligible_menu_count": eligible_count,
        "option_group_count": len(groups),
        "option_item_count": len(items),
        "unique_group_source_count": len({row[2].strip() for row in groups}),
        "unique_item_source_count": len({row[2].strip() for row in items}),
        "localization_counts": {
            "menu": len(menu_rows),
            "option_group": group_localizations,
            "option_item": item_localizations,
        },
        "manifest_sha256": manifest,
        "protected_base_fingerprint_before": before,
        "protected_base_fingerprint_after": after,
        "recommendation_release_family_id": family_id,
        "activated": activate,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("sqlite", "oracle"), default="sqlite")
    parser.add_argument(
        "--sqlite", type=Path, default=ROOT / "backend/data/yobi_demo.db"
    )
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    if args.activate and not args.apply:
        parser.error("--activate requires --apply")
    if not args.apply:
        print(
            json.dumps(
                {
                    "release_id": args.release_id,
                    "model_id": MODEL_ID,
                    "prompt_version": PROMPT_VERSION,
                    "applied": False,
                },
                sort_keys=True,
            )
        )
        return
    result = (
        _apply_oracle(Settings(), args.release_id, args.activate)
        if args.backend == "oracle"
        else _apply_sqlite(args.sqlite, args.release_id, args.activate)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
