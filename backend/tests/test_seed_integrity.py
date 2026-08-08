from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.knowledge.catalog_seed import KNOWLEDGE_CATALOG_VERSION, KNOWLEDGE_RELEASE_ID
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
            "concepts": 29,
            "relations": 27,
            "closure": 66,
            "claims": 411,
            "documents": 29,
            "chunks": 261,
        },
        "knowledge_declared_actual_counts": {
            "concepts": 29,
            "relations": 27,
            "closure": 66,
            "claims": 411,
            "documents": 29,
            "chunks": 261,
        },
        "knowledge_embedding_model": "yobi-semantic-hash-v1",
        "knowledge_embedding_dimension": 1536,
        "knowledge_embedding_version": "2026-08-06",
        "knowledge_counts": {
            "concepts": 29,
            "relations": 27,
            "closure": 66,
            "claims": 411,
            "documents": 29,
            "chunks": 261,
            "menu_mappings": 150,
            "origin_declarations": 30,
            "merchant_ingredients": 266,
            "option_effects": 4,
        },
        "null_knowledge_chunk_vectors": 0,
        "incompatible_knowledge_chunk_metadata": 0,
        "menu_embedding_metadata": [
            {
                "model": "yobi-semantic-hash-v1",
                "dimension": 1536,
                "version": "2026-08-06",
                "count": 150,
            }
        ],
    }


def test_seed_integrity_accepts_exact_catalog() -> None:
    seed_demo.validate(valid_result())


def test_default_embedding_provider_is_pinned_even_when_genai_key_exists() -> None:
    settings = Settings(_env_file=None, oci_genai_api_key="synthetic-key")
    assert settings.oci_genai_api_key.get_secret_value() == "synthetic-key"

    provider = choose_embedding_provider(settings)

    assert isinstance(provider, DeterministicEmbeddingProvider)


def test_expected_counts_match_the_generated_seed() -> None:
    seed = seed_demo.build_seed()
    actual = {seed_key: len(seed[seed_key]) for _, _, seed_key in seed_demo.TABLE_ORDER}
    assert actual == seed_demo.EXPECTED_COUNTS


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


@pytest.mark.parametrize(("key", "value"), [("merchant_ingredients", 265), ("option_effects", 3)])
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
