#!/usr/bin/env python3
"""Resumable EN/JA menu-name generation for a synthetic enrichment release.

The command is read-only unless ``--apply`` is supplied. It never activates a
release; activation remains a separate, explicit operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import oracledb
from pydantic import BaseModel, ConfigDict, ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.genai.contracts import GenAIErrorCode, GenAIProviderError
from app.genai.providers import choose_genai_provider

BATCH_SIZE = 10
SCHEMA_ATTEMPTS_PER_MODEL = 10
WIKI_PASSAGES_PER_MENU = 1
PROMPT_VERSION = "menu-localization-v1-wiki-bounded"


class LocalizedName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    menu_id: str
    name_en: str
    name_ja: str


class LocalizationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LocalizedName]


SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["menu_id", "name_en", "name_ja"],
                "properties": {
                    "menu_id": {"type": "string"},
                    "name_en": {"type": "string"},
                    "name_ja": {"type": "string"},
                },
            },
        }
    },
}


def _source_hash(name_ko: str, passages: list[dict[str, str]]) -> str:
    payload = json.dumps(
        {"name_ko": name_ko, "passages": passages},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_name(value: str, *, language_code: str) -> str:
    name = " ".join(value.split()).strip()
    # Providers occasionally append sentence punctuation even when the JSON
    # value itself is only a food name. Normalize that harmless formatting
    # instead of exhausting every retry for the same otherwise-valid batch.
    name = name.strip(" \t\"'“”‘’").rstrip(".!?。！？").strip()
    if not name or len(name) > 200 or re.search(r"[\n\r]", name):
        raise ValueError("LOCALIZED_NAME_NOT_A_FOOD_NAME")
    if language_code == "en" and re.search(r"[가-힣]", name):
        raise ValueError("ENGLISH_LOCALIZED_NAME_CONTAINS_HANGUL")
    return name


def _parse_localization_json(raw: str) -> Any:
    stripped = raw.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = "\n".join(stripped.splitlines()[1:-1]).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and "items" in candidate:
                return candidate
        raise


def _load_pending(
    connection: sqlite3.Connection, release_id: str
) -> tuple[str, list[dict[str, Any]], int]:
    release = connection.execute(
        "SELECT knowledge_release_id FROM synthetic_enrichment_release WHERE release_id=?",
        (release_id,),
    ).fetchone()
    if release is None:
        raise RuntimeError("SYNTHETIC_ENRICHMENT_RELEASE_NOT_FOUND")
    knowledge_release_id = str(release["knowledge_release_id"])
    eligible_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM menu_wiki_eligibility WHERE knowledge_release_id=?",
            (knowledge_release_id,),
        ).fetchone()[0]
    )
    rows = connection.execute(
        """
        SELECT menu.menu_id,menu.name_ko
        FROM menu_wiki_eligibility eligibility
        JOIN menu ON menu.menu_id=eligibility.menu_id
        WHERE eligibility.knowledge_release_id=?
          AND (
            NOT EXISTS (
              SELECT 1 FROM menu_localization localization
              WHERE localization.release_id=? AND localization.menu_id=menu.menu_id
                AND localization.language_code='en'
                AND localization.validation_status='VALID'
            ) OR NOT EXISTS (
              SELECT 1 FROM menu_localization localization
              WHERE localization.release_id=? AND localization.menu_id=menu.menu_id
                AND localization.language_code='ja'
                AND localization.validation_status='VALID'
            )
          )
        ORDER BY menu.menu_id
        """,
        (knowledge_release_id, release_id, release_id),
    ).fetchall()
    pending: list[dict[str, Any]] = []
    for row in rows:
        passages = [
            {"evidence_id": str(passage["chunk_id"]), "content": str(passage["content"])}
            for passage in connection.execute(
                """
                SELECT DISTINCT chunk.chunk_id,chunk.content
                FROM menu_concept_membership membership
                JOIN dish_concept_closure closure
                  ON closure.release_id=membership.knowledge_release_id
                 AND closure.descendant_concept_id=membership.concept_id
                 AND closure.inherit_claims=1
                JOIN knowledge_chunk chunk
                  ON chunk.release_id=closure.release_id
                 AND chunk.concept_id=closure.ancestor_concept_id
                WHERE membership.knowledge_release_id=? AND membership.menu_id=?
                ORDER BY chunk.chunk_id LIMIT 1
                """,
                (knowledge_release_id, row["menu_id"]),
            ).fetchall()
        ]
        if not passages:
            raise RuntimeError(f"WIKI_PASSAGE_REQUIRED:{row['menu_id']}")
        pending.append(
            {
                "menu_id": str(row["menu_id"]),
                "name_ko": str(row["name_ko"]),
                "wiki_passages": passages,
            }
        )
    return knowledge_release_id, pending, eligible_count


def _oracle_credentials(settings: Settings) -> tuple[str, str, str]:
    password = settings.db_password.get_secret_value()
    dsn = settings.adb_dsn.get_secret_value()
    if settings.db_username != "YOBI_APP" or not password or not dsn:
        raise RuntimeError("MENU_LOCALIZATION_RUNTIME_CREDENTIALS_REQUIRED")
    return settings.db_username, password, dsn


def _load_pending_oracle(
    connection: oracledb.Connection, release_id: str
) -> tuple[str, list[dict[str, Any]], int]:
    cursor = connection.cursor()
    cursor.execute(
        "SELECT knowledge_release_id FROM synthetic_enrichment_release "
        "WHERE release_id=:release_id",
        release_id=release_id,
    )
    release = cursor.fetchone()
    if release is None:
        raise RuntimeError("SYNTHETIC_ENRICHMENT_RELEASE_NOT_FOUND")
    knowledge_release_id = str(release[0])
    cursor.execute(
        "SELECT COUNT(*) FROM menu_wiki_eligibility "
        "WHERE knowledge_release_id=:knowledge_release_id",
        knowledge_release_id=knowledge_release_id,
    )
    eligible_count = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT menu.menu_id,menu.name_ko
        FROM menu_wiki_eligibility eligibility
        JOIN menu ON menu.menu_id=eligibility.menu_id
        WHERE eligibility.knowledge_release_id=:knowledge_release_id
          AND (
            NOT EXISTS (
              SELECT 1 FROM menu_localization localization
              WHERE localization.release_id=:release_id
                AND localization.menu_id=menu.menu_id
                AND localization.language_code='en'
                AND localization.validation_status='VALID'
            ) OR NOT EXISTS (
              SELECT 1 FROM menu_localization localization
              WHERE localization.release_id=:release_id
                AND localization.menu_id=menu.menu_id
                AND localization.language_code='ja'
                AND localization.validation_status='VALID'
            )
          )
        ORDER BY menu.menu_id
        """,
        knowledge_release_id=knowledge_release_id,
        release_id=release_id,
    )
    menu_rows = cursor.fetchall()
    pending: list[dict[str, Any]] = []
    for menu_id, name_ko in menu_rows:
        cursor.execute(
            """
            SELECT chunk.chunk_id,chunk.content
              FROM menu_concept_membership membership
              JOIN dish_concept_closure closure
                ON closure.release_id=membership.knowledge_release_id
               AND closure.descendant_concept_id=membership.concept_id
               AND closure.inherit_claims=1
              JOIN knowledge_chunk chunk
                ON chunk.release_id=closure.release_id
               AND chunk.concept_id=closure.ancestor_concept_id
              WHERE membership.knowledge_release_id=:knowledge_release_id
                AND membership.menu_id=:menu_id
              ORDER BY chunk.chunk_id
            """,
            knowledge_release_id=knowledge_release_id,
            menu_id=str(menu_id),
        )
        passages: list[dict[str, str]] = []
        seen_chunk_ids: set[str] = set()
        for chunk_id, content in cursor:
            evidence_id = str(chunk_id)
            if evidence_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(evidence_id)
            passages.append(
                {
                    "evidence_id": evidence_id,
                    "content": str(content.read() if hasattr(content, "read") else content),
                }
            )
            if len(passages) == WIKI_PASSAGES_PER_MENU:
                break
        if not passages:
            raise RuntimeError(f"WIKI_PASSAGE_REQUIRED:{menu_id}")
        pending.append(
            {
                "menu_id": str(menu_id),
                "name_ko": str(name_ko),
                "wiki_passages": passages,
            }
        )
    return knowledge_release_id, pending, eligible_count


def _generate_batch(provider: Any, settings: Settings, batch: list[dict[str, Any]]) -> tuple[LocalizationBatch, str]:
    request: dict[str, Any] = {
        "instructions": (
            "Translate each Korean food menu name into English and Japanese using only the supplied "
            "Korean name and Wiki passages. Return food names only. Never add taste, ingredient, origin, "
            "portion, popularity, or marketing modifiers that are absent from the original name. Preserve "
            "brand names and disambiguate only when the Wiki evidence makes the food concept explicit. "
            "Return exactly one JSON object matching response_contract, with no markdown, preamble, "
            "commentary, or trailing text. Return every input menu_id exactly once."
        ),
        "input": [
            {
                "role": "user",
                "content": json.dumps(
                    {"menus": batch, "response_contract": SCHEMA},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        ],
        "max_output_tokens": min(1800, provider.capabilities.max_output_tokens),
    }
    if provider.capabilities.structured_output:
        request["text"] = {
            "format": {
                "type": "json_schema",
                "name": "yobi_menu_localization_v1",
                "schema": SCHEMA,
                "strict": True,
            }
        }
    models = [settings.menu_localization_model, settings.oci_genai_fallback_model]
    for index, model_id in enumerate(models):
        for schema_attempt in range(SCHEMA_ATTEMPTS_PER_MODEL):
            try:
                response = provider.create_response(model_id, **request)
                raw = str(getattr(response, "output_text", "")).strip()
                result = LocalizationBatch.model_validate(_parse_localization_json(raw))
                expected = {str(item["menu_id"]) for item in batch}
                if (
                    {item.menu_id for item in result.items} != expected
                    or len(result.items) != len(batch)
                ):
                    raise ValueError("LOCALIZATION_BATCH_MENU_IDS_MISMATCH")
                for item in result.items:
                    _validate_name(item.name_en, language_code="en")
                    _validate_name(item.name_ja, language_code="ja")
                return result, model_id
            except GenAIProviderError as exc:
                if exc.code is GenAIErrorCode.RATE_LIMIT and index == 0:
                    break
                raise
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                if schema_attempt + 1 < SCHEMA_ATTEMPTS_PER_MODEL:
                    continue
                raise ValueError("LOCALIZATION_RESPONSE_INVALID") from exc
    raise RuntimeError("LOCALIZATION_PROVIDER_UNAVAILABLE")


def _apply_batch(
    connection: sqlite3.Connection,
    *,
    release_id: str,
    source_by_id: dict[str, dict[str, Any]],
    result: LocalizationBatch,
    model_id: str,
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple[Any, ...]] = []
    for item in result.items:
        source = source_by_id[item.menu_id]
        evidence_ids = [passage["evidence_id"] for passage in source["wiki_passages"]]
        source_hash = _source_hash(str(source["name_ko"]), source["wiki_passages"])
        for language_code, value in (("en", item.name_en), ("ja", item.name_ja)):
            rows.append(
                (
                    release_id,
                    item.menu_id,
                    language_code,
                    _validate_name(value, language_code=language_code),
                    model_id,
                    PROMPT_VERSION,
                    json.dumps(evidence_ids),
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
        rows,
    )


def _apply_batch_oracle(
    connection: oracledb.Connection,
    *,
    release_id: str,
    source_by_id: dict[str, dict[str, Any]],
    result: LocalizationBatch,
    model_id: str,
) -> None:
    generated_at = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for item in result.items:
        source = source_by_id[item.menu_id]
        evidence_ids = [passage["evidence_id"] for passage in source["wiki_passages"]]
        source_hash = _source_hash(str(source["name_ko"]), source["wiki_passages"])
        for language_code, value in (("en", item.name_en), ("ja", item.name_ja)):
            rows.append(
                {
                    "release_id": release_id,
                    "menu_id": item.menu_id,
                    "language_code": language_code,
                    "display_name": _validate_name(value, language_code=language_code),
                    "model_id": model_id,
                    "prompt_version": PROMPT_VERSION,
                    "wiki_evidence_ids_json": json.dumps(evidence_ids),
                    "source_hash": source_hash,
                    "validation_status": "VALID",
                    "generated_at": generated_at,
                }
            )
    connection.cursor().executemany(
        """
        MERGE INTO menu_localization target
        USING (SELECT :release_id release_id,:menu_id menu_id,
                      :language_code language_code,:display_name display_name,
                      :model_id model_id,:prompt_version prompt_version,
                      :wiki_evidence_ids_json wiki_evidence_ids_json,
                      :source_hash source_hash,:validation_status validation_status,
                      :generated_at generated_at FROM dual) source
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
        rows,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("sqlite", "oracle"), default="sqlite")
    parser.add_argument("--sqlite", type=Path, default=ROOT / "backend/data/yobi_demo.db")
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")

    settings = Settings()
    if args.backend == "oracle":
        user, password, dsn = _oracle_credentials(settings)
        with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
            _, pending, eligible_count = _load_pending_oracle(connection, args.release_id)
    else:
        SQLiteYobiRepository(args.sqlite).initialize()
        with sqlite3.connect(args.sqlite) as connection:
            connection.row_factory = sqlite3.Row
            _, pending, eligible_count = _load_pending(connection, args.release_id)
    planned_batches = (len(pending) + BATCH_SIZE - 1) // BATCH_SIZE
    if not args.apply:
        print(json.dumps({"release_id": args.release_id, "pending_menus": len(pending), "planned_batches": planned_batches, "applied": False}, sort_keys=True))
        return

    provider = choose_genai_provider(settings)
    completed_batches = 0
    batches = [pending[offset : offset + BATCH_SIZE] for offset in range(0, len(pending), BATCH_SIZE)]
    if args.max_batches is not None:
        batches = batches[: args.max_batches]

    def generate_one(
        batch: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], LocalizationBatch, str]:
        result, model_id = _generate_batch(provider, settings, batch)
        return batch, result, model_id

    first_generation_error: Exception | None = None
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures: list[
            Future[tuple[list[dict[str, Any]], LocalizationBatch, str]]
        ] = [executor.submit(generate_one, batch) for batch in batches]
        for future in as_completed(futures):
            try:
                batch, result, model_id = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve other completed batches
                first_generation_error = first_generation_error or exc
                continue
            if args.backend == "oracle":
                user, password, dsn = _oracle_credentials(settings)
                with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
                    _apply_batch_oracle(
                        connection,
                        release_id=args.release_id,
                        source_by_id={str(item["menu_id"]): item for item in batch},
                        result=result,
                        model_id=model_id,
                    )
                    connection.commit()
            else:
                with sqlite3.connect(args.sqlite) as connection:
                    _apply_batch(
                        connection,
                        release_id=args.release_id,
                        source_by_id={str(item["menu_id"]): item for item in batch},
                        result=result,
                        model_id=model_id,
                    )
            completed_batches += 1
            print(
                json.dumps(
                    {
                        "release_id": args.release_id,
                        "completed_batches": completed_batches,
                        "planned_batches": planned_batches,
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )
    if first_generation_error is not None:
        raise first_generation_error

    if args.backend == "oracle":
        user, password, dsn = _oracle_credentials(settings)
        with oracledb.connect(user=user, password=password, dsn=dsn) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM menu_localization
                WHERE release_id=:release_id AND validation_status='VALID'
                  AND language_code IN ('ko','en','ja')
                """,
                release_id=args.release_id,
            )
            valid_count = int(cursor.fetchone()[0])
            ready = valid_count == eligible_count * 3
            if ready:
                cursor.execute(
                    "UPDATE synthetic_enrichment_release SET status='READY' "
                    "WHERE release_id=:release_id AND status='LOADING'",
                    release_id=args.release_id,
                )
            connection.commit()
    else:
        with sqlite3.connect(args.sqlite) as connection:
            valid_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM menu_localization
                    WHERE release_id=? AND validation_status='VALID'
                      AND language_code IN ('ko','en','ja')
                    """,
                    (args.release_id,),
                ).fetchone()[0]
            )
            ready = valid_count == eligible_count * 3
            if ready:
                connection.execute(
                    "UPDATE synthetic_enrichment_release SET status='READY' WHERE release_id=?",
                    (args.release_id,),
                )
    print(json.dumps({"release_id": args.release_id, "completed_batches": completed_batches, "valid_localizations": valid_count, "expected_localizations": eligible_count * 3, "ready": ready, "applied": True}, sort_keys=True))


if __name__ == "__main__":
    main()
