from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


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


class GenAIProviderError(RuntimeError):
    def __init__(
        self,
        code: GenAIErrorCode,
        *,
        retryable: bool,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.retryable = retryable
        self.cause = cause


class GenAIProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def supports_model(self, model: str) -> bool: ...

    def normalize_request(self, model: str, **kwargs: Any) -> dict[str, Any]: ...

    def create_response(self, model: str, **kwargs: Any) -> Any: ...
