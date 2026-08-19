from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Literal

from oci.exceptions import ServiceError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_backfill_menu_semantic_embeddings",
    ROOT / "scripts" / "backfill_menu_semantic_embeddings.py",
)
assert SPEC and SPEC.loader
backfill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backfill
SPEC.loader.exec_module(backfill)


class RecordingEmbeddingProvider:
    model = "cohere.embed-v4.0"
    dimension = 4
    version = "oci-native-test-v1"

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def embed(
        self,
        texts: list[str],
        mode: Literal["SEARCH_DOCUMENT", "SEARCH_QUERY"],
    ) -> list[list[float]]:
        assert mode == "SEARCH_DOCUMENT"
        self.batch_sizes.append(len(texts))
        return [[float(index), 0.0, 0.0, 1.0] for index, _text in enumerate(texts)]


def test_vector_cache_uses_oci_batch_boundary_and_is_complete(tmp_path: Path) -> None:
    del tmp_path
    rows = [(f"menu-{index:03d}", f"semantic text {index}") for index in range(97)]
    provider = RecordingEmbeddingProvider()

    cache_path, vector_count, dispatch_count = backfill.prepare_vector_cache(rows, provider)
    try:
        assert vector_count == 97
        assert dispatch_count == 2
        assert provider.batch_sizes == [96, 1]
        assert cache_path.stat().st_size == 97 * provider.dimension * 4
    finally:
        cache_path.unlink(missing_ok=True)


def test_vector_cache_applies_interval_only_between_dispatches(monkeypatch) -> None:
    rows = [(f"menu-{index:03d}", f"semantic text {index}") for index in range(193)]
    provider = RecordingEmbeddingProvider()
    sleeps: list[float] = []
    monkeypatch.setattr(backfill.time, "sleep", sleeps.append)

    cache_path, vector_count, dispatch_count = backfill.prepare_vector_cache(
        rows,
        provider,
        dispatch_interval_seconds=1.5,
    )
    try:
        assert vector_count == 193
        assert dispatch_count == 3
        assert provider.batch_sizes == [96, 96, 1]
        assert sleeps == [1.5, 1.5]
    finally:
        cache_path.unlink(missing_ok=True)


def test_embedding_manifest_binds_catalog_provider_menu_and_semantic_text() -> None:
    provider = RecordingEmbeddingProvider()
    rows = [("menu-a", "alpha"), ("menu-b", "beta")]

    manifest = backfill.embedding_manifest_sha256(
        catalog_release_id="catalog-v1",
        provider=provider,
        rows=rows,
    )

    assert len(manifest) == 64
    assert manifest == backfill.embedding_manifest_sha256(
        catalog_release_id="catalog-v1",
        provider=provider,
        rows=list(rows),
    )
    assert manifest != backfill.embedding_manifest_sha256(
        catalog_release_id="catalog-v1",
        provider=provider,
        rows=[("menu-a", "changed"), ("menu-b", "beta")],
    )


def test_safe_error_code_classifies_oci_status_without_message_or_request_id() -> None:
    error = ServiceError(
        429,
        "TooManyRequests",
        {"opc-request-id": "secret-request-id"},
        "sensitive provider message",
    )

    code = backfill._safe_error_code(error)

    assert code == "OCI_429_TOOMANYREQUESTS"
    assert "sensitive" not in code
    assert "secret-request-id" not in code
