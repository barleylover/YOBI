from __future__ import annotations

from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.core.config import Settings
from app.genai.client import OciGenAIClient
from app.genai.contracts import (
    GenAIErrorCode,
    GenAIProviderError,
    GenAIServingMode,
    ProviderCapabilities,
)


def classify_provider_error(exc: BaseException) -> GenAIProviderError:
    if isinstance(exc, RateLimitError):
        return GenAIProviderError(GenAIErrorCode.RATE_LIMIT, retryable=True, cause=exc)
    if isinstance(exc, (APITimeoutError, TimeoutError)):
        return GenAIProviderError(GenAIErrorCode.TIMEOUT, retryable=True, cause=exc)
    if isinstance(exc, (APIConnectionError, ConnectionError)):
        return GenAIProviderError(GenAIErrorCode.NETWORK_ERROR, retryable=True, cause=exc)
    if isinstance(exc, APIStatusError):
        status_code = exc.status_code
        if status_code == 429:
            return GenAIProviderError(GenAIErrorCode.RATE_LIMIT, retryable=True, cause=exc)
        if status_code in {408, 504}:
            return GenAIProviderError(GenAIErrorCode.TIMEOUT, retryable=True, cause=exc)
        return GenAIProviderError(
            GenAIErrorCode.PROVIDER_UNAVAILABLE,
            retryable=status_code >= 500,
            cause=exc,
        )
    return GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False, cause=exc)


class OciResponsesProvider:
    """OCI Responses adapter with explicit serving-mode and capability contracts."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client_factory = OciGenAIClient(settings)

    @property
    def configured(self) -> bool:
        if not self.client_factory.configured:
            return False
        if self.serving_mode is GenAIServingMode.DEDICATED:
            return bool(self.settings.oci_genai_endpoint_id)
        return True

    @property
    def serving_mode(self) -> GenAIServingMode:
        return GenAIServingMode(self.settings.oci_genai_serving_mode)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider=self.settings.genai_provider,
            serving_mode=self.serving_mode,
            responses_api=True,
            function_calling=True,
            structured_output=self.settings.oci_genai_structured_output_enabled,
            native_streaming=self.settings.oci_genai_streaming_enabled,
            client_managed_continuation=True,
            server_managed_continuation=False,
        )

    def supports_model(self, model: str) -> bool:
        if self.serving_mode is GenAIServingMode.ON_DEMAND:
            return True
        if model == self.settings.oci_genai_model:
            return bool(self.settings.oci_genai_endpoint_id)
        if model == self.settings.oci_genai_fallback_model:
            return bool(self.settings.oci_genai_fallback_endpoint_id)
        return False

    def normalize_model(self, model: str) -> str:
        if self.serving_mode is GenAIServingMode.ON_DEMAND:
            return model
        if model == self.settings.oci_genai_model and self.settings.oci_genai_endpoint_id:
            return self.settings.oci_genai_endpoint_id
        if (
            model == self.settings.oci_genai_fallback_model
            and self.settings.oci_genai_fallback_endpoint_id
        ):
            return self.settings.oci_genai_fallback_endpoint_id
        raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
        return {"model": self.normalize_model(model), **kwargs}

    def create_response(self, model: str, **kwargs: Any) -> Any:
        if not self.configured or not self.supports_model(model):
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
        try:
            client = self.client_factory.build()
            return client.responses.create(**self.normalize_request(model, **kwargs))
        except GenAIProviderError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc) from exc


def choose_genai_provider(settings: Settings) -> OciResponsesProvider:
    if settings.genai_provider == "oci":
        return OciResponsesProvider(settings)
    raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
