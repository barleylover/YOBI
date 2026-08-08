from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import RateLimitError

from app.core.config import Settings
from app.genai.agent_loop import AgentLoop
from app.genai.contracts import (
    GenAIErrorCode,
    GenAIProviderError,
    GenAIServingMode,
    ProviderCapabilities,
)
from app.genai.providers import OciResponsesProvider, classify_provider_error
from app.genai.tool_registry import ToolRegistry


def _rate_limit() -> RateLimitError:
    request = httpx.Request("POST", "https://example.invalid/responses")
    response = httpx.Response(429, headers={"retry-after": "10"}, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def test_on_demand_provider_preserves_legacy_model_request_and_capabilities() -> None:
    settings = Settings(oci_genai_api_key="test-key")
    provider = OciResponsesProvider(settings)

    request = provider.normalize_request(
        settings.oci_genai_model,
        instructions="system contract",
        input=[{"role": "user", "content": "hello"}],
        tools=[],
    )

    assert request["model"] == "xai.grok-4.3"
    assert request["instructions"] == "system contract"
    assert provider.configured is True
    assert provider.capabilities.serving_mode is GenAIServingMode.ON_DEMAND
    assert provider.capabilities.responses_api is True
    assert provider.capabilities.function_calling is True
    assert provider.capabilities.client_managed_continuation is True
    assert provider.capabilities.server_managed_continuation is False


def test_dedicated_provider_normalizes_logical_models_to_endpoint_ocids() -> None:
    settings = Settings(
        oci_genai_api_key="test-key",
        oci_genai_serving_mode="dedicated",
        oci_genai_endpoint_id="ocid1.generativeaiendpoint.primary",
        oci_genai_fallback_endpoint_id="ocid1.generativeaiendpoint.fallback",
        oci_genai_structured_output_enabled=True,
        oci_genai_streaming_enabled=True,
    )
    provider = OciResponsesProvider(settings)

    primary = provider.normalize_request(settings.oci_genai_model, input="hello")
    fallback = provider.normalize_request(settings.oci_genai_fallback_model, input="hello")

    assert primary["model"] == "ocid1.generativeaiendpoint.primary"
    assert fallback["model"] == "ocid1.generativeaiendpoint.fallback"
    assert provider.capabilities.serving_mode is GenAIServingMode.DEDICATED
    assert provider.capabilities.structured_output is True
    assert provider.capabilities.native_streaming is True
    assert provider.supports_model("unknown-model") is False


@pytest.mark.parametrize(
    ("cause", "code", "retryable"),
    [
        (_rate_limit(), GenAIErrorCode.RATE_LIMIT, True),
        (TimeoutError("slow"), GenAIErrorCode.TIMEOUT, True),
        (ConnectionError("offline"), GenAIErrorCode.NETWORK_ERROR, True),
        (RuntimeError("bad config"), GenAIErrorCode.PROVIDER_UNAVAILABLE, False),
    ],
)
def test_provider_error_classification_is_stable(
    cause: BaseException, code: GenAIErrorCode, retryable: bool
) -> None:
    error = classify_provider_error(cause)

    assert error.code is code
    assert error.retryable is retryable
    assert error.cause is cause
    assert str(error) == code.value


def test_agent_fallback_is_bounded_and_keeps_provider_error_taxonomy(
    repository: Any, profile_data: Any
) -> None:
    profile = repository.create_profile(profile_data)

    class FakeResponses:
        def __init__(self) -> None:
            self.models: list[str] = []

        def create(self, **kwargs: Any) -> Any:
            model = str(kwargs["model"])
            self.models.append(model)
            if model == "xai.grok-4.3":
                raise TimeoutError("primary timed out")
            return SimpleNamespace(id="fallback", output=[], output_text="Fallback answer")

    responses = FakeResponses()
    agent = AgentLoop(Settings(oci_genai_api_key="test-key", llm_max_retries=0))
    agent.client_factory.build = lambda: SimpleNamespace(responses=responses)  # type: ignore[method-assign]

    result = agent.run("something mild", "state=DISCOVERY", ToolRegistry(repository, profile))

    assert result.text == "Fallback answer"
    assert responses.models == ["xai.grok-4.3", "openai.gpt-oss-120b"]


def test_agent_raises_last_retryable_error_after_each_model_once(
    repository: Any, profile_data: Any
) -> None:
    profile = repository.create_profile(profile_data)

    class FakeResponses:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs: Any) -> Any:
            self.calls += 1
            raise ConnectionError("offline")

    responses = FakeResponses()
    agent = AgentLoop(Settings(oci_genai_api_key="test-key", llm_max_retries=0))
    agent.client_factory.build = lambda: SimpleNamespace(responses=responses)  # type: ignore[method-assign]

    with pytest.raises(GenAIProviderError) as caught:
        agent.run("something mild", "state=DISCOVERY", ToolRegistry(repository, profile))

    assert caught.value.code is GenAIErrorCode.NETWORK_ERROR
    assert responses.calls == 2


def test_agent_retries_a_transient_primary_failure_before_model_fallback(
    repository: Any, profile_data: Any
) -> None:
    profile = repository.create_profile(profile_data)

    class FakeResponses:
        def __init__(self) -> None:
            self.models: list[str] = []

        def create(self, **kwargs: Any) -> Any:
            model = str(kwargs["model"])
            self.models.append(model)
            if len(self.models) == 1:
                raise TimeoutError("transient timeout")
            return SimpleNamespace(id="primary-retry", output=[], output_text="Recovered")

    responses = FakeResponses()
    agent = AgentLoop(
        Settings(
            oci_genai_api_key="test-key",
            llm_max_retries=1,
            llm_retry_base_seconds=0,
        )
    )
    agent.client_factory.build = lambda: SimpleNamespace(responses=responses)  # type: ignore[method-assign]

    result = agent.run("something mild", "state=DISCOVERY", ToolRegistry(repository, profile))

    assert result.text == "Recovered"
    assert responses.models == ["xai.grok-4.3", "xai.grok-4.3"]


def test_generation_request_does_not_use_or_mutate_embedding_configuration() -> None:
    settings = Settings(
        oci_genai_api_key="test-key",
        oci_genai_model="generation-model-v2",
        oci_embed_model="embedding-model-v1",
        oci_embed_dimension=1536,
    )
    provider = OciResponsesProvider(settings)

    request = provider.normalize_request(settings.oci_genai_model, input="hello")

    assert request["model"] == "generation-model-v2"
    assert "embedding" not in request
    assert settings.oci_embed_model == "embedding-model-v1"
    assert settings.oci_embed_dimension == 1536


def test_structured_capability_sends_strict_narrative_schema(
    repository: Any, profile_data: Any
) -> None:
    profile = repository.create_profile(profile_data)

    class CapturingProvider:
        configured = True
        capabilities = ProviderCapabilities(
            provider="test",
            serving_mode=GenAIServingMode.DEDICATED,
            responses_api=True,
            function_calling=True,
            structured_output=True,
            native_streaming=False,
            client_managed_continuation=True,
            server_managed_continuation=False,
        )

        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def supports_model(self, model: str) -> bool:
            return True

        def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]:
            return {"model": model, **kwargs}

        def create_response(self, model: str, **kwargs: Any) -> Any:
            self.requests.append(kwargs)
            return SimpleNamespace(
                id="structured",
                output=[],
                output_text=json.dumps(
                    {
                        "message": "Would you prefer something warm or light?",
                        "response_kind": "QUESTION",
                        "referenced_menu_ids": [],
                        "referenced_claim_ids": [],
                    }
                ),
            )

    provider = CapturingProvider()
    agent = AgentLoop(Settings(), provider=provider)

    result = agent.run(
        "hi",
        "state=DISCOVERY",
        ToolRegistry(repository, profile),
        allow_tools=False,
    )

    assert result.structured_output is True
    response_format = provider.requests[0]["text"]["format"]
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    assert response_format["schema"]["additionalProperties"] is False
