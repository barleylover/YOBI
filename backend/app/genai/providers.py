from __future__ import annotations

from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.core.config import Settings
from app.genai.admission import ModelAdmissionCooldown, SharedModelAdmissionController
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
        if not self.client_factory.configured or not self.settings.oci_genai_model.strip():
            return False
        if self.serving_mode is GenAIServingMode.DEDICATED:
            return bool(self.settings.oci_genai_endpoint_id.strip())
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
            max_input_tokens=self.settings.oci_genai_max_input_tokens,
            max_output_tokens=self.settings.oci_genai_max_output_tokens,
            max_tools_per_request=self.settings.oci_genai_max_tools_per_request,
            max_tool_calls_per_response=self.settings.oci_genai_max_tool_calls_per_response,
        )

    def supports_model(self, model: str) -> bool:
        if self.serving_mode is GenAIServingMode.ON_DEMAND:
            return bool(model.strip())
        if model == self.settings.oci_genai_model:
            return bool(self.settings.oci_genai_endpoint_id.strip())
        if model == self.settings.oci_genai_fallback_model:
            return bool(self.settings.oci_genai_fallback_endpoint_id.strip())
        return False

    def normalize_model(self, model: str) -> str:
        if self.serving_mode is GenAIServingMode.ON_DEMAND:
            if not model.strip():
                raise GenAIProviderError(
                    GenAIErrorCode.PROVIDER_UNAVAILABLE,
                    retryable=False,
                )
            return model
        if model == self.settings.oci_genai_model and self.settings.oci_genai_endpoint_id.strip():
            return self.settings.oci_genai_endpoint_id
        if (
            model == self.settings.oci_genai_fallback_model
            and self.settings.oci_genai_fallback_endpoint_id.strip()
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
            normalized = self.normalize_request(model, **kwargs)
            if not self.settings.oci_genai_admission_control_enabled:
                return client.responses.create(**normalized)
            return SharedModelAdmissionController.run(
                endpoint=self.settings.oci_genai_base_url,
                model=str(normalized["model"]),
                max_concurrent=self.settings.oci_genai_max_concurrent_requests_per_model,
                min_interval_seconds=self.settings.oci_genai_min_interval_seconds,
                default_cooldown_seconds=(
                    self.settings.oci_genai_rate_limit_cooldown_seconds
                ),
                call=lambda: client.responses.create(**normalized),
            )
        except ModelAdmissionCooldown as exc:
            raise GenAIProviderError(
                GenAIErrorCode.RATE_LIMIT,
                retryable=True,
                cause=exc,
                safe_metadata={
                    "admission_cooldown_remaining_ms": int(
                        exc.remaining_seconds * 1000
                    )
                },
            ) from exc
        except GenAIProviderError:
            raise
        except Exception as exc:
            classified = classify_provider_error(exc)
            if classified.code is GenAIErrorCode.RATE_LIMIT:
                retry_after = SharedModelAdmissionController._retry_after_seconds(exc)
                if retry_after is not None:
                    classified.safe_metadata["retry_after_ms"] = int(retry_after * 1000)
            raise classified from exc


def choose_genai_provider(settings: Settings) -> OciResponsesProvider:
    if settings.genai_provider == "oci":
        return OciResponsesProvider(settings)
    raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)


def genai_configuration_errors(settings: Settings) -> list[str]:
    """Return sanitized fail-closed errors for required GenAI configurations."""
    required = (
        settings.app_env == "production"
        or settings.oci_genai_serving_mode == GenAIServingMode.DEDICATED.value
    )
    if not required:
        return []

    try:
        provider = choose_genai_provider(settings)
        capabilities = provider.capabilities
    except (GenAIProviderError, ValueError):
        return ["PROVIDER_UNSUPPORTED"]

    errors: list[str] = []
    if not settings.oci_genai_api_key.get_secret_value().strip():
        errors.append("API_KEY_MISSING")
    if not settings.oci_genai_base_url.startswith("https://"):
        errors.append("BASE_URL_INVALID")
    if not settings.oci_genai_region.strip():
        errors.append("REGION_MISSING")
    if not settings.oci_genai_model.strip():
        errors.append("PRIMARY_MODEL_MISSING")
    if not settings.structured_recommendation_model.strip():
        errors.append("STRUCTURED_MODEL_MISSING")
    if not settings.oci_genai_fallback_model.strip():
        errors.append("FALLBACK_MODEL_MISSING")
    if not provider.configured:
        errors.append("PROVIDER_NOT_CONFIGURED")
    if not provider.supports_model(settings.oci_genai_model):
        errors.append("PRIMARY_MODEL_UNAVAILABLE")
    if (
        settings.structured_recommendation_model.strip()
        and not provider.supports_model(settings.structured_recommendation_model)
    ):
        errors.append("STRUCTURED_MODEL_UNAVAILABLE")
    if (
        settings.menu_presentation_model.strip()
        and not provider.supports_model(settings.menu_presentation_model)
    ):
        errors.append("PRESENTATION_MODEL_UNAVAILABLE")
    if (
        settings.oci_genai_fallback_model.strip()
        and not provider.supports_model(settings.oci_genai_fallback_model)
    ):
        errors.append("FALLBACK_MODEL_UNAVAILABLE")
    if (
        settings.option_localization_model.strip()
        and not provider.supports_model(settings.option_localization_model)
    ):
        errors.append("OPTION_LOCALIZATION_MODEL_UNAVAILABLE")
    if provider.serving_mode is GenAIServingMode.DEDICATED:
        if not settings.oci_genai_endpoint_id.strip():
            errors.append("PRIMARY_ENDPOINT_MISSING")
        if (
            settings.oci_genai_fallback_model.strip()
            and not settings.oci_genai_fallback_endpoint_id.strip()
        ):
            errors.append("FALLBACK_ENDPOINT_MISSING")
    if not capabilities.responses_api:
        errors.append("RESPONSES_API_UNSUPPORTED")
    if not capabilities.function_calling:
        errors.append("FUNCTION_CALLING_UNSUPPORTED")
    if settings.llm_max_input_tokens > capabilities.max_input_tokens:
        errors.append("INPUT_LIMIT_INCOMPATIBLE")
    if settings.recommendation_selection_max_output_tokens > capabilities.max_output_tokens:
        errors.append("SELECTION_OUTPUT_LIMIT_INCOMPATIBLE")
    if settings.structured_recommendation_max_output_tokens > capabilities.max_output_tokens:
        errors.append("STRUCTURED_OUTPUT_LIMIT_INCOMPATIBLE")
    if settings.llm_max_output_tokens > capabilities.max_output_tokens:
        errors.append("OUTPUT_LIMIT_INCOMPATIBLE")
    if settings.menu_presentation_max_output_tokens > capabilities.max_output_tokens:
        errors.append("PRESENTATION_OUTPUT_LIMIT_INCOMPATIBLE")
    if settings.option_localization_max_output_tokens > capabilities.max_output_tokens:
        errors.append("OPTION_LOCALIZATION_OUTPUT_LIMIT_INCOMPATIBLE")
    if settings.llm_max_tools_per_request > capabilities.max_tools_per_request:
        errors.append("TOOL_SCHEMA_LIMIT_INCOMPATIBLE")
    if settings.llm_max_tool_calls_per_response > capabilities.max_tool_calls_per_response:
        errors.append("TOOL_CALL_LIMIT_INCOMPATIBLE")
    return errors
