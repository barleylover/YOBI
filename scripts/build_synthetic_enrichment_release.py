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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

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
    parser.add_argument("--sqlite", type=Path, default=ROOT / "backend/data/yobi_demo.db")
    parser.add_argument("--release-id", default="synthetic-enrichment-v1")
    parser.add_argument("--seed", default="yobi-realistic-demo-v1")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    if args.activate and not args.apply:
        parser.error("--activate requires --apply")

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
    if args.apply:
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
                "protected_base_fingerprint_before": base_fingerprint_before,
                "protected_base_fingerprint_after": base_fingerprint_after,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
