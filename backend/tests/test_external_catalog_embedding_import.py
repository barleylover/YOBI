from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_import_external_catalog",
    ROOT / "scripts" / "import_external_catalog.py",
)
assert SPEC and SPEC.loader
catalog_import = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = catalog_import
SPEC.loader.exec_module(catalog_import)


class RecordingEmbeddingProvider:
    model = "cohere.embed-v4.0"
    dimension = 4
    version = "test-native-v1"

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


def test_external_catalog_vector_cache_uses_oci_embed_batch_boundary(
    tmp_path: Path,
) -> None:
    package = tmp_path / "catalog.zip"
    rows = [
        json.dumps({"semantic_text": f"menu semantic text {index}"})
        for index in range(97)
    ]
    with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("menu.jsonl", "\n".join(rows) + "\n")
    provider = RecordingEmbeddingProvider()

    cache_path, vector_count = catalog_import.prepare_vector_cache(package, provider)
    try:
        assert vector_count == 97
        assert provider.batch_sizes == [96, 1]
        assert cache_path.stat().st_size == 97 * provider.dimension * 4
    finally:
        cache_path.unlink(missing_ok=True)
