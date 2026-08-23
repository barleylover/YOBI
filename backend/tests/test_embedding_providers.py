from types import SimpleNamespace

import oci
import pytest

from app.core.config import Settings
from app.db.oracle_repository import OracleYobiRepository
from app.rag.providers import (
    DeterministicEmbeddingProvider,
    OCIEmbeddingProvider,
    choose_embedding_provider,
)


class _FakeOCIClient:
    def __init__(self, dimension: int, *, typed_response: bool = False) -> None:
        self.dimension = dimension
        self.typed_response = typed_response
        self.calls: list[tuple[object, object]] = []

    def embed_text(self, details: object, *, retry_strategy: object) -> object:
        self.calls.append((details, retry_strategy))
        inputs = list(details.inputs)
        vectors = [[float(index)] * self.dimension for index, _text in enumerate(inputs)]
        if self.typed_response:
            data = SimpleNamespace(embeddings=None, embeddings_by_type={"float": vectors})
        else:
            data = SimpleNamespace(embeddings=vectors, embeddings_by_type=None)
        return SimpleNamespace(data=data)


class _OneFastRequestFailureOCIClient(_FakeOCIClient):
    def __init__(self, dimension: int) -> None:
        super().__init__(dimension)
        self.attempts = 0

    def embed_text(self, details: object, *, retry_strategy: object) -> object:
        self.attempts += 1
        if self.attempts == 1:
            raise oci.exceptions.RequestException("transient connection failure")
        return super().embed_text(details, retry_strategy=retry_strategy)


def _oci_settings() -> Settings:
    return Settings(
        oci_compartment_id="ocid1.compartment.oc1..test",
        oci_embed_model="cohere.embed-v4.0",
        oci_embed_dimension=1536,
        llm_retry_base_seconds=0,
    )


def test_oci_embedding_uses_native_embed_text_contract_and_bounds_batches() -> None:
    provider = OCIEmbeddingProvider(_oci_settings())
    fake = _FakeOCIClient(provider.dimension)
    provider._client = fake

    vectors = provider.embed([f"menu {index}" for index in range(97)], "SEARCH_DOCUMENT")

    assert len(vectors) == 97
    assert [len(details.inputs) for details, _retry in fake.calls] == [96, 1]
    first, retry_strategy = fake.calls[0]
    assert first.input_type == "SEARCH_DOCUMENT"
    assert first.output_dimensions == 1536
    assert first.embedding_types == ["float"]
    assert first.compartment_id == "ocid1.compartment.oc1..test"
    assert first.serving_mode.model_id == "cohere.embed-v4.0"
    assert isinstance(retry_strategy, oci.retry.NoneRetryStrategy)


def test_oci_embedding_rejects_wrong_provider_dimensions() -> None:
    provider = OCIEmbeddingProvider(_oci_settings())
    provider._client = _FakeOCIClient(4)

    with pytest.raises(RuntimeError, match="OCI_EMBEDDING_DIMENSION_MISMATCH"):
        provider.embed(["menu"], "SEARCH_QUERY")


def test_oci_embedding_reads_embed4_float_vectors_from_typed_response() -> None:
    provider = OCIEmbeddingProvider(_oci_settings())
    provider._client = _FakeOCIClient(provider.dimension, typed_response=True)

    vectors = provider.embed(["menu"], "SEARCH_QUERY")

    assert len(vectors) == 1
    assert len(vectors[0]) == 1536


def test_oci_embedding_retries_one_fast_request_transport_failure() -> None:
    provider = OCIEmbeddingProvider(_oci_settings())
    fake = _OneFastRequestFailureOCIClient(provider.dimension)
    provider._client = fake

    vectors = provider.embed(["menu"], "SEARCH_QUERY")

    assert len(vectors) == 1
    assert fake.attempts == 2
    assert len(fake.calls) == 1


def test_default_provider_remains_explicit_deterministic_fallback() -> None:
    provider = choose_embedding_provider(
        Settings(
            embedding_provider="deterministic",
            oci_genai_api_key="unused-chat-key",
        )
    )

    assert isinstance(provider, DeterministicEmbeddingProvider)


def test_production_oracle_rejects_deterministic_fixture_vectors() -> None:
    with pytest.raises(RuntimeError, match="PRODUCTION_ORACLE_REQUIRES_OCI_EMBEDDINGS"):
        OracleYobiRepository(
            Settings(
                app_env="production",
                demo_db_backend="oracle",
                embedding_provider="deterministic",
            )
        )
