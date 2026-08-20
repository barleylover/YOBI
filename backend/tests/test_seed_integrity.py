from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.concept_ranking import RANKING_POLICY_SHA256, RANKING_POLICY_VERSION
from app.knowledge.catalog_seed import KNOWLEDGE_CATALOG_VERSION, KNOWLEDGE_RELEASE_ID
from app.knowledge.preference_support import (
    SUPPORT_MANIFEST_FIELDS,
    build_synthetic_support_rows,
    support_manifest_sha256,
)
from app.rag.providers import DeterministicEmbeddingProvider, choose_embedding_provider

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("yobi_seed_demo", ROOT / "scripts" / "seed_demo.py")
assert SPEC and SPEC.loader
seed_demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_demo)


def valid_result() -> dict[str, object]:
    return {
        "counts": dict(seed_demo.EXPECTED_COUNTS),
        "null_menu_vectors": 0,
        "null_review_vectors": 0,
        "null_knowledge_vectors": 0,
        "canonical_ready": True,
        "required_groups_without_items": 0,
        "knowledge_ready": True,
        "knowledge_release_id": KNOWLEDGE_RELEASE_ID,
        "knowledge_catalog_version": KNOWLEDGE_CATALOG_VERSION,
        "knowledge_manifest_sha256": "a" * 64,
        "knowledge_expected_counts": {
            "concepts": 102,
            "relations": 99,
            "closure": 279,
            "claims": 345,
            "documents": 102,
            "chunks": 1263,
        },
        "knowledge_declared_actual_counts": {
            "concepts": 102,
            "relations": 99,
            "closure": 279,
            "claims": 345,
            "documents": 102,
            "chunks": 1263,
        },
        "knowledge_embedding_model": "yobi-semantic-hash-v1",
        "knowledge_embedding_dimension": 1536,
        "knowledge_embedding_version": "2026-08-06",
        "knowledge_counts": {
            "concepts": 102,
            "relations": 99,
            "closure": 279,
            "claims": 345,
            "documents": 102,
            "chunks": 1263,
            "menu_mappings": 600,
            "origin_declarations": 13,
            "merchant_ingredients": 120,
            "option_effects": 4,
        },
        "null_knowledge_chunk_vectors": 0,
        "incompatible_knowledge_chunk_metadata": 0,
        "menu_embedding_metadata": [
            {
                "model": "yobi-semantic-hash-v1",
                "dimension": 1536,
                "version": "2026-08-06",
                "count": 600,
            }
        ],
        "recommendation_release_family": {
            "release_family_id": "structured-rag-v1:test",
            "knowledge_release_id": KNOWLEDGE_RELEASE_ID,
            "preference_catalog_version": seed_demo.PREFERENCE_CATALOG_VERSION,
            "spice_reference_version": seed_demo.SPICE_REFERENCE_VERSION,
            "certification_release_id": seed_demo.CERTIFICATION_RELEASE_ID,
            "embedding_model": "yobi-semantic-hash-v1",
            "embedding_version": "2026-08-06",
            "support_manifest_sha256": "b" * 64,
            "ranking_policy_version": RANKING_POLICY_VERSION,
            "ranking_policy_sha256": RANKING_POLICY_SHA256,
            "status": "ACTIVE",
        },
        "concept_preference_support_count": 42,
        "invalid_concept_preference_support_count": 0,
        "computed_support_manifest_sha256": "b" * 64,
        "preference_option_count": seed_demo.EXPECTED_PREFERENCE_OPTIONS,
        "active_preference_option_count": seed_demo.EXPECTED_ACTIVE_PREFERENCE_OPTIONS,
        "spice_reference_count": seed_demo.EXPECTED_SPICE_REFERENCES,
        "halal_certification_count": seed_demo.EXPECTED_HALAL_CERTIFICATIONS,
    }


def test_seed_integrity_accepts_exact_catalog() -> None:
    seed_demo.validate(valid_result())


def test_seed_integrity_accepts_only_retained_upgrade_supersets() -> None:
    result = valid_result()
    counts = result["counts"]
    assert isinstance(counts, dict)
    for key in seed_demo.UPGRADE_RETAINED_COUNT_KEYS:
        counts[key] = seed_demo.EXPECTED_COUNTS[key] + 7
    seed_demo.validate(result)

    counts["menus"] = seed_demo.EXPECTED_COUNTS["menus"] + 1
    with pytest.raises(RuntimeError, match="SEED_COUNT_INTEGRITY_FAILED"):
        seed_demo.validate(result)


def test_seed_integrity_rejects_missing_retained_current_rows() -> None:
    result = valid_result()
    counts = result["counts"]
    assert isinstance(counts, dict)
    counts["menu_allergens"] = seed_demo.EXPECTED_COUNTS["menu_allergens"] - 1
    with pytest.raises(RuntimeError, match="SEED_COUNT_INTEGRITY_FAILED"):
        seed_demo.validate(result)


def test_seed_script_type_aliases_are_runtime_compatible_with_python39() -> None:
    assert seed_demo.TableKey is Any
    assert seed_demo.EmbeddingProviderChoice is Any


def test_seed_json_reader_accepts_oracle_native_json_and_lob_values() -> None:
    expected = {"concepts": 29, "chunks": 261}
    lob = MagicMock()
    lob.read.return_value = expected

    assert seed_demo._json_value(expected) == expected
    assert seed_demo._json_value('{"concepts": 29, "chunks": 261}') == expected
    assert seed_demo._json_value(lob) == expected


def test_default_embedding_provider_is_pinned_even_when_genai_key_exists() -> None:
    settings = Settings(_env_file=None, oci_genai_api_key="synthetic-key")
    assert settings.oci_genai_api_key.get_secret_value() == "synthetic-key"

    provider = choose_embedding_provider(settings)

    assert isinstance(provider, DeterministicEmbeddingProvider)


def test_expected_counts_match_the_generated_seed() -> None:
    seed = seed_demo.build_seed()
    actual = {seed_key: len(seed[seed_key]) for _, _, seed_key in seed_demo.TABLE_ORDER}
    assert actual == seed_demo.EXPECTED_COUNTS


def test_menu_allergens_reference_only_the_current_allergen_catalog() -> None:
    seed = seed_demo.build_seed()

    assert {
        str(row["allergen_id"]) for row in seed["menu_allergens"]
    } <= {str(row["allergen_id"]) for row in seed["allergens"]}


def test_fresh_sqlite_seed_preserves_all_foreign_keys(tmp_path: Path) -> None:
    repository = SQLiteYobiRepository(tmp_path / "fresh-yobi.db")

    repository.initialize()

    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_fresh_sqlite_seed_support_manifest_and_ranking_identity_are_exact(
    tmp_path: Path,
) -> None:
    repository = SQLiteYobiRepository(tmp_path / "fresh-support.db")
    repository.initialize()

    with sqlite3.connect(repository.path) as connection:
        rows = connection.execute(
            f"SELECT {','.join(SUPPORT_MANIFEST_FIELDS)} "
            "FROM concept_preference_support "
            "ORDER BY concept_id,category_code,option_code"
        ).fetchall()
        support_rows = [
            dict(zip(SUPPORT_MANIFEST_FIELDS, row)) for row in rows
        ]
        family = connection.execute(
            """
            SELECT family.support_manifest_sha256,family.ranking_policy_version,
                   family.ranking_policy_sha256
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            WHERE state.state_key='ACTIVE'
            """
        ).fetchone()
        cited_reviewed_public = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM concept_preference_support support
                JOIN knowledge_chunk chunk
                  ON chunk.release_id=support.knowledge_release_id
                 AND chunk.chunk_id=support.evidence_chunk_id
                JOIN knowledge_document document
                  ON document.release_id=chunk.release_id
                 AND document.document_id=chunk.document_id
                WHERE document.source_type='SYNTHETIC_WIKI'
                  AND document.review_status='REVIEWED_DEMO'
                  AND lower(chunk.facet)<>'safety'
                  AND (
                    json_extract(chunk.metadata_json,'$.recommendation_visibility')='PUBLIC_RAG'
                    OR json_extract(chunk.metadata_json,'$.recommendation_visibility') IS NULL
                  )
                """
            ).fetchone()[0]
        )

    assert support_rows
    assert cited_reviewed_public == len(support_rows)
    assert family == (
        support_manifest_sha256(support_rows),
        RANKING_POLICY_VERSION,
        RANKING_POLICY_SHA256,
    )


def test_oracle_seed_uses_shared_synthetic_support_and_manifest_contract() -> None:
    assert seed_demo.build_synthetic_support_rows is build_synthetic_support_rows
    assert seed_demo.support_manifest_sha256 is support_manifest_sha256
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [
        ("concept-korean", 0, "chunk-korean", "doc-korean", "Korean cuisine dishes")
    ]
    updated_at = seed_demo.datetime(2026, 8, 16, tzinfo=seed_demo.timezone.utc)

    rows, manifest = seed_demo._seed_synthetic_concept_support(
        cursor,
        knowledge_release_id="synthetic-release",
        updated_at=updated_at,
    )
    expected = build_synthetic_support_rows(
        knowledge_release_id="synthetic-release",
        reviewed_chunks=[
            {
                "concept_id": "concept-korean",
                "depth": 0,
                "chunk_id": "chunk-korean",
                "document_id": "doc-korean",
                "content": "Korean cuisine dishes",
            }
        ],
        updated_at=updated_at,
    )

    assert rows == expected
    assert rows
    assert manifest == support_manifest_sha256(expected)
    assert any(
        "DELETE FROM concept_preference_support" in str(call.args[0])
        for call in cursor.execute.call_args_list
    )


def test_seed_transaction_commits_once_only_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    prepared = MagicMock()
    expected = valid_result()
    monkeypatch.setattr(seed_demo, "_apply_seed_transaction", lambda *_args, **_kwargs: expected)

    assert seed_demo.apply_seed(connection, prepared, fresh=False) == expected
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()


def test_seed_transaction_rolls_back_everything_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    prepared = MagicMock()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected seed failure")

    monkeypatch.setattr(seed_demo, "_apply_seed_transaction", fail)
    with pytest.raises(RuntimeError, match="injected seed failure"):
        seed_demo.apply_seed(connection, prepared, fresh=True)

    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("knowledge_embedding_model", "different-model"),
        ("knowledge_embedding_dimension", 768),
        ("knowledge_embedding_version", "different-version"),
    ],
)
def test_runtime_embedding_metadata_must_match_provider(field: str, value: object) -> None:
    provider = MagicMock(
        model="yobi-semantic-hash-v1",
        dimension=1536,
        version="2026-08-06",
    )
    result = valid_result()
    result[field] = value

    with pytest.raises(RuntimeError, match="SEED_KNOWLEDGE_EMBEDDING_COMPATIBILITY_FAILED"):
        seed_demo.validate_runtime_embedding(result, provider)


def test_runtime_menu_embedding_metadata_must_match_provider() -> None:
    provider = MagicMock(
        model="yobi-semantic-hash-v1",
        dimension=1536,
        version="2026-08-06",
    )
    result = valid_result()
    result["menu_embedding_metadata"] = []

    with pytest.raises(RuntimeError, match="SEED_MENU_EMBEDDING_COMPATIBILITY_FAILED"):
        seed_demo.validate_runtime_embedding(result, provider)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("knowledge_manifest_sha256", "short", "SEED_KNOWLEDGE_RELEASE_IDENTITY_FAILED"),
        (
            "knowledge_declared_actual_counts",
            {"chunks": 1},
            "SEED_KNOWLEDGE_DECLARED_COUNT_MISMATCH",
        ),
        (
            "incompatible_knowledge_chunk_metadata",
            1,
            "SEED_KNOWLEDGE_EMBEDDING_COMPATIBILITY_FAILED",
        ),
    ],
)
def test_knowledge_release_identity_and_declared_counts_are_exact(
    field: str, value: object, code: str
) -> None:
    result = valid_result()
    result[field] = value
    with pytest.raises(RuntimeError, match=code):
        seed_demo.validate(result)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("support_manifest_sha256", "0" * 64),
        ("ranking_policy_version", "legacy-llm-rank-v2"),
        ("ranking_policy_sha256", "0" * 64),
    ],
)
def test_seed_rejects_legacy_or_mismatched_recommendation_identity(
    field: str,
    value: str,
) -> None:
    result = valid_result()
    family = result["recommendation_release_family"]
    assert isinstance(family, dict)
    family[field] = value

    with pytest.raises(RuntimeError, match="SEED_RECOMMENDATION_RELEASE_NOT_ACTIVE"):
        seed_demo.validate(result)


def test_seed_rejects_empty_or_invalid_concept_preference_support() -> None:
    result = valid_result()
    result["concept_preference_support_count"] = 0

    with pytest.raises(
        RuntimeError,
        match="SEED_CONCEPT_PREFERENCE_SUPPORT_INTEGRITY_FAILED",
    ):
        seed_demo.validate(result)


@pytest.mark.parametrize(("key", "value"), [("merchant_ingredients", 110), ("option_effects", 3)])
def test_supplemental_release_counts_are_validated_before_commit(key: str, value: int) -> None:
    result = valid_result()
    result["knowledge_counts"][key] = value

    with pytest.raises(RuntimeError, match="SEED_KNOWLEDGE_COUNT_INTEGRITY_FAILED"):
        seed_demo.validate(result)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("null_menu_vectors", 1, "SEED_MENU_VECTOR_INTEGRITY_FAILED"),
        ("null_review_vectors", 1, "SEED_REVIEW_VECTOR_INTEGRITY_FAILED"),
        ("null_knowledge_vectors", 1, "SEED_KNOWLEDGE_VECTOR_INTEGRITY_FAILED"),
        ("canonical_ready", False, "SEED_CANONICAL_INTEGRITY_FAILED"),
        ("required_groups_without_items", 1, "SEED_REQUIRED_OPTIONS_INTEGRITY_FAILED"),
    ],
)
def test_seed_integrity_rejects_invalid_catalog(field: str, value: object, code: str) -> None:
    result = valid_result()
    result[field] = value
    with pytest.raises(RuntimeError, match=code):
        seed_demo.validate(result)
