from __future__ import annotations

from typing import Literal, Protocol

from openai import OpenAI

from app.core.config import Settings
from app.rag.embeddings import deterministic_embedding

EmbeddingMode = Literal["SEARCH_DOCUMENT", "SEARCH_QUERY"]


class EmbeddingProvider(Protocol):
    model: str
    dimension: int
    version: str

    def embed(self, texts: list[str], mode: EmbeddingMode) -> list[list[float]]: ...


class DeterministicEmbeddingProvider:
    model = "yobi-semantic-hash-v1"
    dimension = 1536
    version = "2026-08-06"

    def embed(self, texts: list[str], mode: EmbeddingMode) -> list[list[float]]:
        prefix = "document: " if mode == "SEARCH_DOCUMENT" else "query: "
        return [deterministic_embedding(prefix + text, self.dimension) for text in texts]


class OCIEmbeddingProvider:
    """OCI API-key embedding adapter using the same verified OpenAI-compatible endpoint."""

    version = "oci-cohere-v4"

    def __init__(self, settings: Settings) -> None:
        api_key = settings.oci_genai_api_key.get_secret_value()
        if not api_key:
            raise RuntimeError("OCI_GENAI_API_KEY_MISSING")
        self.model = settings.oci_embed_model
        self.dimension = settings.oci_embed_dimension
        self.client = OpenAI(
            base_url=settings.oci_genai_base_url,
            api_key=api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    def embed(self, texts: list[str], mode: EmbeddingMode) -> list[list[float]]:
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimension,
            extra_body={"input_type": mode},
        )
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        if len(vectors) != len(texts) or any(len(vector) != self.dimension for vector in vectors):
            raise RuntimeError("OCI_EMBEDDING_DIMENSION_MISMATCH")
        return vectors


def choose_embedding_provider(
    settings: Settings,
    requested: Literal["auto", "oci", "deterministic"] | None = None,
) -> EmbeddingProvider:
    requested = requested or settings.embedding_provider
    if requested == "deterministic":
        return DeterministicEmbeddingProvider()
    if requested == "oci":
        return OCIEmbeddingProvider(settings)
    if settings.oci_genai_api_key.get_secret_value():
        try:
            provider = OCIEmbeddingProvider(settings)
            provider.embed(["YOBI embedding smoke test"], "SEARCH_QUERY")
            return provider
        except Exception:
            if not settings.demo_fallback_enabled:
                raise
    return DeterministicEmbeddingProvider()
