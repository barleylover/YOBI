#!/usr/bin/env python3
"""Prepare an isolated SQLite database for browser journeys.

This helper never touches Oracle or calls a model.  It copies the checked local
fixture database, applies additive migrations and installs a deterministic
synthetic-enrichment release.  EN/JA names are deliberately marked
``LOCAL_E2E_FIXTURE``; production localization still requires the resumable
Grok -> GPT-OSS batch command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.db.sqlite_repository import SQLiteYobiRepository
from app.demo_enrichment import (
    build_enrichment_rows,
    manifest_sha256,
    validate_enrichment_rows,
)
from build_synthetic_enrichment_release import _apply_sqlite, _load_sqlite_inputs


def _install_localization_fixtures(path: Path, release_id: str) -> int:
    generated_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            """
            SELECT profile.menu_id,menu.name_en,menu.name_ko
            FROM synthetic_menu_profile profile
            JOIN menu ON menu.menu_id=profile.menu_id
            WHERE profile.release_id=?
            ORDER BY profile.menu_id
            """,
            (release_id,),
        ).fetchall()
        localizations: list[tuple[str, ...]] = []
        for menu_id, name_en, name_ko in rows:
            source_name = str(name_en or name_ko)
            source_hash = hashlib.sha256(
                f"local-e2e|{menu_id}|{name_ko}|{source_name}".encode()
            ).hexdigest()
            for language_code in ("en", "ja"):
                localizations.append(
                    (
                        release_id,
                        str(menu_id),
                        language_code,
                        source_name,
                        "LOCAL_E2E_FIXTURE",
                        "local-e2e-only",
                        "[]",
                        source_hash,
                        "VALID",
                        generated_at,
                    )
                )
        connection.executemany(
            """
            INSERT INTO menu_localization(
              release_id,menu_id,language_code,display_name,model_id,prompt_version,
              wiki_evidence_ids_json,source_hash,validation_status,generated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(release_id,menu_id,language_code) DO UPDATE SET
              display_name=excluded.display_name,model_id=excluded.model_id,
              prompt_version=excluded.prompt_version,
              wiki_evidence_ids_json=excluded.wiki_evidence_ids_json,
              source_hash=excluded.source_hash,validation_status=excluded.validation_status,
              generated_at=excluded.generated_at
            """,
            localizations,
        )
    return len(localizations)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--release-id", default="local-e2e-enrichment-v1")
    parser.add_argument("--seed", default="yobi-local-e2e-v1")
    args = parser.parse_args()

    if not args.source.is_file():
        raise FileNotFoundError(args.source)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.source, args.destination)
    SQLiteYobiRepository(args.destination).initialize()

    catalog_release_id, knowledge_release_id, menus, options = _load_sqlite_inputs(
        args.destination
    )
    rows = build_enrichment_rows(
        release_id=args.release_id,
        seed=args.seed,
        menus=menus,
        options=options,
    )
    validate_enrichment_rows(rows, eligible_menu_count=len(menus))
    manifest = manifest_sha256(rows)
    first_before, first_after = _apply_sqlite(
        args.destination,
        release_id=args.release_id,
        catalog_release_id=catalog_release_id,
        knowledge_release_id=knowledge_release_id,
        seed=args.seed,
        rows=rows,
        manifest=manifest,
        activate=False,
    )
    localization_count = _install_localization_fixtures(args.destination, args.release_id)
    second_before, second_after = _apply_sqlite(
        args.destination,
        release_id=args.release_id,
        catalog_release_id=catalog_release_id,
        knowledge_release_id=knowledge_release_id,
        seed=args.seed,
        rows=rows,
        manifest=manifest,
        activate=True,
    )
    if len({first_before, first_after, second_before, second_after}) != 1:
        raise RuntimeError("LOCAL_E2E_PROTECTED_BASE_TABLES_CHANGED")

    print(
        json.dumps(
            {
                "release_id": args.release_id,
                "manifest_sha256": manifest,
                "eligible_menus": len(menus),
                "localization_fixtures": localization_count,
                "protected_base_fingerprint": first_before,
                "active": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
