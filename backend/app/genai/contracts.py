from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class GenAIServingMode(str, Enum):
    ON_DEMAND = "on_demand"
    DEDICATED = "dedicated"


class GenAIErrorCode(str, Enum):
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_TOOL_ARGUMENT = "INVALID_TOOL_ARGUMENT"
    NO_TOOL_RESPONSE = "NO_TOOL_RESPONSE"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    GROUNDING_REJECTED = "GROUNDING_REJECTED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CAPABILITY_LIMIT_EXCEEDED = "CAPABILITY_LIMIT_EXCEEDED"
    TOOL_STEP_LIMIT = "TOOL_STEP_LIMIT"


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    serving_mode: GenAIServingMode
    responses_api: bool
    function_calling: bool
    structured_output: bool
    native_streaming: bool
    client_managed_continuation: bool
    server_managed_continuation: bool
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_tools_per_request: int = Field(gt=0)
    max_tool_calls_per_response: int = Field(gt=0)


class GenAIProviderError(RuntimeError):
    def __init__(
        self,
        code: GenAIErrorCode,
        *,
        retryable: bool,
        cause: BaseException | None = None,
        safe_metadata: dict[str, int] | None = None,
        safe_reason_code: str | None = None,
        safe_reason_stage: str | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.retryable = retryable
        self.cause = cause
        self.safe_metadata = dict(safe_metadata or {})
        self.safe_reason_code = safe_reason_code
        self.safe_reason_stage = safe_reason_stage


class GenAIProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def supports_model(self, model: str) -> bool: ...

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]: ...

    def create_response(self, model: str, **kwargs: Any) -> Any: ...
