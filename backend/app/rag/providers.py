from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol

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
    """Cohere Embed 4 adapter for OCI's native ``embedText`` operation.

    OCI's OpenAI-compatible ``/actions/v1`` endpoint is used for chat and
    response models, but it is not the embedding endpoint. Embeddings use the
    signed OCI SDK operation and an instance principal in production (or an
    explicit local OCI config profile for controlled backfills).
    """

    version = "oci-native-embedtext-v1"
    max_inputs_per_request = 96

    def __init__(self, settings: Settings) -> None:
        compartment_id = settings.oci_compartment_id.get_secret_value().strip()
        if not compartment_id:
            raise RuntimeError("OCI_COMPARTMENT_ID_MISSING")
        self.model = settings.oci_embed_model
        self.dimension = settings.oci_embed_dimension
        self.compartment_id = compartment_id
        self.region = settings.oci_genai_region
        self.auth_mode = settings.oci_embed_auth
        self.config_file = Path(settings.oci_embed_config_file).expanduser()
        self.config_profile = settings.oci_embed_config_profile
        self.timeout_seconds = settings.llm_timeout_seconds
        self._client: Any | None = None
        self._client_lock = Lock()

    def _client_for_request(self) -> Any:
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                import oci  # type: ignore[import-untyped]
            except ImportError as exc:  # pragma: no cover - packaging contract
                raise RuntimeError("OCI_SDK_MISSING") from exc

            endpoint = f"https://inference.generativeai.{self.region}.oci.oraclecloud.com"
            client_kwargs: dict[str, Any] = {
                "service_endpoint": endpoint,
                "retry_strategy": oci.retry.NoneRetryStrategy(),
                "timeout": (10.0, self.timeout_seconds),
            }
            if self.auth_mode == "instance_principal":
                config: dict[str, Any] = {"region": self.region}
                client_kwargs["signer"] = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            else:
                if not self.config_file.is_file():
                    raise RuntimeError("OCI_EMBED_CONFIG_FILE_MISSING")
                config = oci.config.from_file(
                    file_location=str(self.config_file),
                    profile_name=self.config_profile,
                )
                config["region"] = self.region
            self._client = oci.generative_ai_inference.GenerativeAiInferenceClient(
                config,
                **client_kwargs,
            )
            return self._client

    def _embed_batch(self, texts: list[str], mode: EmbeddingMode) -> list[list[float]]:
        try:
            from oci.generative_ai_inference.models import (  # type: ignore[import-untyped]
                EmbedTextDetails,
                OnDemandServingMode,
            )
        except ImportError as exc:  # pragma: no cover - packaging contract
            raise RuntimeError("OCI_SDK_MISSING") from exc
        details = EmbedTextDetails(
            inputs=texts,
            serving_mode=OnDemandServingMode(model_id=self.model),
            compartment_id=self.compartment_id,
            is_echo=False,
            embedding_types=["float"],
            output_dimensions=self.dimension,
            truncate="END",
            input_type=mode,
        )
        import oci  # type: ignore[import-untyped]

        response = self._client_for_request().embed_text(
            details,
            retry_strategy=oci.retry.NoneRetryStrategy(),
        )
        vectors = response.data.embeddings
        if vectors is None:
            embeddings_by_type = response.data.embeddings_by_type
            if isinstance(embeddings_by_type, dict):
                vectors = embeddings_by_type.get("float")
        return [list(vector) for vector in (vectors or [])]

    def embed(self, texts: list[str], mode: EmbeddingMode) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.max_inputs_per_request):
            vectors.extend(
                self._embed_batch(texts[offset : offset + self.max_inputs_per_request], mode)
            )
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
    if settings.oci_compartment_id.get_secret_value().strip():
        try:
            provider = OCIEmbeddingProvider(settings)
            provider.embed(["YOBI embedding smoke test"], "SEARCH_QUERY")
            return provider
        except Exception:
            if not settings.demo_fallback_enabled:
                raise
    return DeterministicEmbeddingProvider()
