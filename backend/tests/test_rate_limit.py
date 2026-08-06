from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
from openai import RateLimitError

from app.core.config import Settings
from app.genai.agent_loop import AgentLoop
from app.genai.rate_limit import call_with_rate_limit_retry, retry_delay_seconds
from app.genai.tool_registry import ToolRegistry
from app.services.chat_service import ChatService
from app.services.demo_control import DemoControl


def _rate_limit(retry_after: str | None = None) -> RateLimitError:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    request = httpx.Request("POST", "https://example.invalid/responses")
    response = httpx.Response(429, headers=headers, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def test_retry_delay_prefers_header_and_adds_jitter() -> None:
    delay = retry_delay_seconds(_rate_limit("12"), uniform=lambda start, end: 2.0)
    assert delay == 14.0


def test_retry_delay_without_header_is_between_65_and_70_seconds() -> None:
    calls: list[tuple[float, float]] = []

    def uniform(start: float, end: float) -> float:
        calls.append((start, end))
        return 67.0

    assert retry_delay_seconds(_rate_limit(), uniform=uniform) == 67.0
    assert calls == [(65.0, 70.0)]


def test_smoke_retry_is_bounded_to_two_retries() -> None:
    attempts = 0
    sleeps: list[float] = []

    def call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _rate_limit()
        return "ok"

    result = call_with_rate_limit_retry(
        call,
        max_retries=2,
        sleep=sleeps.append,
        uniform=lambda start, end: 66.0,
    )
    assert result == "ok"
    assert attempts == 3
    assert sleeps == [66.0, 66.0]


def test_runtime_rate_limit_immediately_switches_to_gpt_oss(
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
                raise _rate_limit("60")
            return SimpleNamespace(id="resp_fallback", output=[], output_text="Fallback model answer")

    responses = FakeResponses()
    agent = AgentLoop(Settings(oci_genai_api_key="test-key", llm_max_retries=0))
    agent.client_factory.build = lambda: SimpleNamespace(responses=responses)  # type: ignore[method-assign]

    result = agent.run("something mild", "state=DISCOVERY", ToolRegistry(repository, profile))

    assert result.text == "Fallback model answer"
    assert responses.models == ["xai.grok-4.3", "openai.gpt-oss-120b"]


def test_runtime_uses_deterministic_path_when_both_models_are_rate_limited(
    repository: Any, profile_data: Any
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)

    class FakeResponses:
        def create(self, **kwargs: Any) -> Any:
            raise _rate_limit()

    service = ChatService(
        repository,
        Settings(oci_genai_api_key="test-key", llm_max_retries=0),
        DemoControl(),
    )
    service.agent.client_factory.build = lambda: SimpleNamespace(responses=FakeResponses())  # type: ignore[method-assign]

    turn = service.respond(
        session,
        profile,
        "I saw a red rice cake dish on the street. Can I order it?",
    )
    assert turn.fallback_used is True
    assert "avoid" in turn.text.lower()


def test_runtime_uses_deterministic_path_for_ungrounded_model_answer(
    repository: Any, profile_data: Any
) -> None:
    profile = repository.create_profile(profile_data)
    session = repository.create_session(profile.profile_id)

    class FakeResponses:
        def create(self, **kwargs: Any) -> Any:
            return SimpleNamespace(id="resp_plain", output=[], output_text="Unverified plain answer")

    service = ChatService(
        repository,
        Settings(oci_genai_api_key="test-key", llm_max_retries=0),
        DemoControl(),
    )
    service.agent.client_factory.build = lambda: SimpleNamespace(responses=FakeResponses())  # type: ignore[method-assign]

    turn = service.respond(
        session,
        profile,
        "I saw a red rice cake dish on the street. Can I order it?",
    )
    assert turn.fallback_used is True
    assert [card.type for card in turn.cards] == ["dietary_evidence", "menu_recommendations"]
