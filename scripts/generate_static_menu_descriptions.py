#!/usr/bin/env python3
"""Generate release-scoped KO/EN/JA YOGIYO description localizations.

The command is read-only unless ``--apply`` is supplied. It never changes the
catalog, Wiki, vector, or canonical menu description columns.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import oracledb

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(SCRIPTS))

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.menu_source_description_localization import (
    MODEL_ID,
    PROMPT_VERSION,
    description_source_hash,
    localize_source_description,
)
from protected_base_fingerprint import (
    oracle_base_fingerprint,
    protected_base_fingerprint,
)

LANGUAGES = ("ko", "en", "ja")


def _rows_for_sources(sources: list[tuple[str, str]]) -> list[dict[str, str]]:
    unique_translations: dict[tuple[str, str], str] = {}
    rows: list[dict[str, str]] = []
    for menu_id, source_text in sources:
        for language_code in LANGUAGES:
            key = (source_text, language_code)
            if key not in unique_translations:
                unique_translations[key] = localize_source_description(
                    source_text, language_code
                )
            rows.append(
                {
                    "menu_id": menu_id,
                    "language_code": language_code,
                    "description_text": unique_translations[key],
                    "model_id": "SOURCE_COPY" if language_code == "ko" else MODEL_ID,
                    "prompt_version": PROMPT_VERSION,
                    "source_hash": description_source_hash(source_text, language_code),
                    "validation_status": "VALID",
                }
            )
    return rows


def _validate(
    sources: list[tuple[str, str]], rows: list[dict[str, str]]
) -> dict[str, int]:
    expected = len(sources) * len(LANGUAGES)
    if len(rows) != expected:
        raise RuntimeError("MENU_DESCRIPTION_LOCALIZATION_COUNT_MISMATCH")
    if len({(row["menu_id"], row["language_code"]) for row in rows}) != expected:
        raise RuntimeError("MENU_DESCRIPTION_LOCALIZATION_DUPLICATE")
    if any(not row["description_text"].strip() for row in rows):
        raise RuntimeError("MENU_DESCRIPTION_LOCALIZATION_EMPTY")
    return {
        "source_menus": len(sources),
        "unique_descriptions": len({source for _menu_id, source in sources}),
        "localized_rows": len(rows),
    }


def _sqlite_sources(path: Path, release_id: str) -> list[tuple[str, str]]:
    SQLiteYobiRepository(path).initialize()
    with sqlite3.connect(path) as connection:
        release = connection.execute(
            "SELECT knowledge_release_id FROM synthetic_enrichment_release WHERE release_id=?",
            (release_id,),
        ).fetchone()
        if release is None:
            raise RuntimeError("SYNTHETIC_ENRICHMENT_RELEASE_NOT_FOUND")
        return [
            (str(menu_id), str(description).strip())
            for menu_id, description in connection.execute(
                """
                SELECT menu.menu_id,menu.description
                FROM menu_wiki_eligibility eligibility
                JOIN menu ON menu.menu_id=eligibility.menu_id
                WHERE eligibility.knowledge_release_id=?
                  AND TRIM(COALESCE(menu.description,''))<>''
                ORDER BY menu.menu_id
                """,
                (str(release[0]),),
            )
        ]


def _oracle_connection(settings: Settings) -> oracledb.Connection:
    password = settings.db_password.get_secret_value()
    dsn = settings.adb_dsn.get_secret_value()
    if settings.db_username != "YOBI_APP" or not password or not dsn:
        raise RuntimeError("MENU_DESCRIPTION_RUNTIME_CREDENTIALS_REQUIRED")
    return oracledb.connect(user=settings.db_username, password=password, dsn=dsn)


def _oracle_sources(settings: Settings, release_id: str) -> list[tuple[str, str]]:
    with _oracle_connection(settings) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT knowledge_release_id FROM synthetic_enrichment_release "
            "WHERE release_id=:release_id",
            release_id=release_id,
        )
        release = cursor.fetchone()
        if release is None:
            raise RuntimeError("SYNTHETIC_ENRICHMENT_RELEASE_NOT_FOUND")
        cursor.execute(
            """
            SELECT menu.menu_id,menu.description
            FROM menu_wiki_eligibility eligibility
            JOIN menu ON menu.menu_id=eligibility.menu_id
            WHERE eligibility.knowledge_release_id=:knowledge_release_id
              AND menu.description IS NOT NULL
            ORDER BY menu.menu_id
            """,
            knowledge_release_id=str(release[0]),
        )
        return [
            (
                str(menu_id),
                str(
                    description.read()
                    if hasattr(description, "read")
                    else description
                ).strip(),
            )
            for menu_id, description in cursor.fetchall()
        ]


def _apply_sqlite(
    path: Path, release_id: str, rows: list[dict[str, str]]
) -> tuple[str, str, int]:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as connection:
        before = protected_base_fingerprint(connection)
        connection.executemany(
            """
            INSERT OR IGNORE INTO menu_source_description_localization(
              release_id,menu_id,language_code,description_text,model_id,
              prompt_version,source_hash,validation_status,generated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    release_id,
                    row["menu_id"],
                    row["language_code"],
                    row["description_text"],
                    row["model_id"],
                    row["prompt_version"],
                    row["source_hash"],
                    row["validation_status"],
                    now,
                )
                for row in rows
            ],
        )
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM menu_source_description_localization "
                "WHERE release_id=? AND validation_status='VALID'",
                (release_id,),
            ).fetchone()[0]
        )
        after = protected_base_fingerprint(connection)
        if before != after:
            raise RuntimeError("PROTECTED_BASE_TABLES_CHANGED")
    return before, after, count


def _apply_oracle(
    settings: Settings, release_id: str, rows: list[dict[str, str]]
) -> tuple[str, str, int]:
    generated_at = datetime.now(timezone.utc)
    with _oracle_connection(settings) as connection:
        before = oracle_base_fingerprint(connection)
        cursor = connection.cursor()
        cursor.executemany(
            """
            MERGE INTO menu_source_description_localization target
            USING (SELECT :release_id release_id,:menu_id menu_id,
                          :language_code language_code FROM dual) source
            ON (target.release_id=source.release_id AND target.menu_id=source.menu_id
                AND target.language_code=source.language_code)
            WHEN NOT MATCHED THEN INSERT (
              release_id,menu_id,language_code,description_text,model_id,prompt_version,
              source_hash,validation_status,generated_at
            ) VALUES (
              :release_id,:menu_id,:language_code,:description_text,:model_id,:prompt_version,
              :source_hash,:validation_status,:generated_at
            )
            """,
            [dict(row, release_id=release_id, generated_at=generated_at) for row in rows],
        )
        cursor.execute(
            "SELECT COUNT(*) FROM menu_source_description_localization "
            "WHERE release_id=:release_id AND validation_status='VALID'",
            release_id=release_id,
        )
        count = int(cursor.fetchone()[0])
        after = oracle_base_fingerprint(connection)
        if before != after:
            connection.rollback()
            raise RuntimeError("PROTECTED_BASE_TABLES_CHANGED")
        connection.commit()
    return before, after, count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("sqlite", "oracle"), default="sqlite")
    parser.add_argument("--sqlite", type=Path, default=ROOT / "backend/data/yobi_demo.db")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings() if args.backend == "oracle" else None
    sources = (
        _oracle_sources(settings, args.release_id)
        if settings is not None
        else _sqlite_sources(args.sqlite, args.release_id)
    )
    rows = _rows_for_sources(sources)
    counts = _validate(sources, rows)
    before: str | None = None
    after: str | None = None
    stored = 0
    if args.apply:
        if settings is not None:
            before, after, stored = _apply_oracle(settings, args.release_id, rows)
        else:
            before, after, stored = _apply_sqlite(args.sqlite, args.release_id, rows)
        if stored != counts["localized_rows"]:
            raise RuntimeError(
                f"MENU_DESCRIPTION_LOCALIZATION_STORED_COUNT_MISMATCH:{stored}:"
                f"{counts['localized_rows']}"
            )
    print(
        json.dumps(
            {
                "release_id": args.release_id,
                **counts,
                "stored_rows": stored,
                "applied": args.apply,
                "protected_base_fingerprint_before": before,
                "protected_base_fingerprint_after": after,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
