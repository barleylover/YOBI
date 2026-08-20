from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from threading import BoundedSemaphore
from time import monotonic, sleep
from typing import Any, cast

from openai import RateLimitError
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import log_event
from app.domain.dialogue import DialogueAct
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.prompts import prompt_for_profile
from app.genai.providers import choose_genai_provider
from app.genai.rate_limit import retry_delay_seconds
from app.genai.response_contract import (
    GroundingScope,
    UncertaintyCode,
    model_narrative_text_config,
    parse_model_narrative,
)
from app.genai.tool_registry import ToolRegistry
from app.genai.tool_schemas import select_tools


@dataclass
class AgentResult:
    text: str
    tool_results: list[tuple[str, dict[str, Any]]]
    referenced_menu_ids: list[str] | None = None
    referenced_claim_ids: list[str] | None = None
    referenced_passage_ids: list[str] | None = None
    grounding_scope: GroundingScope | None = None
    uncertainty_codes: list[UncertaintyCode] | None = None
    structured_output: bool = False
    response_kind: str | None = None
    provider_error_code: GenAIErrorCode | None = None


class AgentLoop:
    def __init__(self, settings: Settings, provider: GenAIProvider | None = None) -> None:
        self.settings = settings
        self.provider = provider or choose_genai_provider(settings)
        # Compatibility seam for existing deployment/tests that replace the cached
        # OpenAI-compatible client factory. New code should inject a provider.
        self.client_factory = getattr(self.provider, "client_factory", None)
        self.logger = logging.getLogger("yobi")
        self._cooldown_until: dict[str, float] = {}
        self._request_slots = BoundedSemaphore(settings.llm_max_concurrent_requests)

    @property
    def configured(self) -> bool:
        return self.provider.configured

    def run(
        self,
        user_text: str,
        dynamic_context: str,
        registry: ToolRegistry,
        *,
        allow_tools: bool = True,
        dialogue_act: DialogueAct | None = None,
    ) -> AgentResult:
        capabilities = self.provider.capabilities
        if not capabilities.responses_api or (allow_tools and not capabilities.function_calling):
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
        instructions = (
            f"{prompt_for_profile(self.settings.genai_prompt_profile)}"
            f"\n\nSession context:\n{dynamic_context}"
        )
        active_tools = select_tools(user_text, dialogue_act) if allow_tools else []
        max_tools = min(
            self.settings.llm_max_tools_per_request,
            capabilities.max_tools_per_request,
        )
        if len(active_tools) > max_tools:
            raise GenAIProviderError(
                GenAIErrorCode.CAPABILITY_LIMIT_EXCEEDED,
                retryable=False,
            )
        active_tool_names = {str(tool["name"]) for tool in active_tools}
        # Keep the full tool exchange client-side. The legacy OCI endpoint used by the
        # deployed demo accepts Responses input items, but its stored-response
        # continuation has proved unreliable in production. This is also an official
        # Responses API state-management pattern and keeps every function call paired
        # with its output without depending on provider retention.
        conversation: list[Any] = [{"role": "user", "content": user_text}]
        request: dict[str, Any] = {
            "instructions": instructions,
            "input": cast(Any, conversation),
            "max_output_tokens": min(
                self.settings.llm_max_output_tokens,
                capabilities.max_output_tokens,
            ),
        }
        if active_tools:
            request["tools"] = cast(Any, active_tools)
        if capabilities.structured_output:
            request["text"] = cast(Any, model_narrative_text_config())
        response, active_model = self._create_response(
            self.settings.oci_genai_model,
            **request,
        )
        self._log_response(response)
        tool_results: list[tuple[str, dict[str, Any]]] = []
        for _ in range(self.settings.tool_call_max_steps):
            output = getattr(response, "output", None)
            if output is None:
                if preserved := self._preserve_mutation_result(
                    tool_results, GenAIErrorCode.NO_TOOL_RESPONSE
                ):
                    return preserved
                raise GenAIProviderError(GenAIErrorCode.NO_TOOL_RESPONSE, retryable=False)
            calls: list[Any] = [
                item for item in output if getattr(item, "type", None) == "function_call"
            ]
            max_calls = min(
                self.settings.llm_max_tool_calls_per_response,
                capabilities.max_tool_calls_per_response,
            )
            if len(calls) > max_calls:
                if preserved := self._preserve_mutation_result(
                    tool_results, GenAIErrorCode.CAPABILITY_LIMIT_EXCEEDED
                ):
                    return preserved
                raise GenAIProviderError(
                    GenAIErrorCode.CAPABILITY_LIMIT_EXCEEDED,
                    retryable=False,
                )
            if not calls:
                text = str(getattr(response, "output_text", "")).strip()
                if not text:
                    if preserved := self._preserve_mutation_result(
                        tool_results, GenAIErrorCode.EMPTY_RESPONSE
                    ):
                        return preserved
                    raise GenAIProviderError(GenAIErrorCode.EMPTY_RESPONSE, retryable=False)
                try:
                    parsed = parse_model_narrative(text)
                except ValidationError as exc:
                    if preserved := self._preserve_mutation_result(
                        tool_results, GenAIErrorCode.GROUNDING_REJECTED
                    ):
                        return preserved
                    raise GenAIProviderError(
                        GenAIErrorCode.GROUNDING_REJECTED,
                        retryable=False,
                        cause=exc,
                    ) from exc
                if capabilities.structured_output and not parsed.structured:
                    if preserved := self._preserve_mutation_result(
                        tool_results, GenAIErrorCode.GROUNDING_REJECTED
                    ):
                        return preserved
                    raise GenAIProviderError(
                        GenAIErrorCode.GROUNDING_REJECTED,
                        retryable=False,
                    )
                return AgentResult(
                    text=parsed.narrative.message,
                    tool_results=tool_results,
                    referenced_menu_ids=parsed.narrative.referenced_menu_ids,
                    referenced_claim_ids=parsed.narrative.referenced_claim_ids,
                    referenced_passage_ids=parsed.narrative.referenced_passage_ids,
                    grounding_scope=parsed.narrative.grounding_scope,
                    uncertainty_codes=parsed.narrative.uncertainty_codes,
                    structured_output=parsed.structured,
                    response_kind=parsed.narrative.response_kind,
                )
            # The legacy OCI-compatible endpoint can include provider-specific
            # auxiliary output items alongside function calls. Only function calls
            # are valid predecessors for the matching function_call_output items.
            conversation.extend(calls)
            outputs = []
            for call in calls:
                if call.name not in active_tool_names:
                    if preserved := self._preserve_mutation_result(
                        tool_results, GenAIErrorCode.INVALID_TOOL_ARGUMENT
                    ):
                        return preserved
                    raise GenAIProviderError(
                        GenAIErrorCode.INVALID_TOOL_ARGUMENT,
                        retryable=False,
                    )
                try:
                    result = registry.execute(call.name, call.arguments)
                except (TypeError, ValueError) as exc:
                    if preserved := self._preserve_mutation_result(
                        tool_results, GenAIErrorCode.INVALID_TOOL_ARGUMENT
                    ):
                        return preserved
                    raise GenAIProviderError(
                        GenAIErrorCode.INVALID_TOOL_ARGUMENT,
                        retryable=False,
                        cause=exc,
                    ) from exc
                tool_results.append((call.name, result))
                outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(
                            {"untrusted_data": self._compact_tool_result(call.name, result)},
                            ensure_ascii=False,
                        ),
                    }
                )
            conversation.extend(outputs)
            try:
                continuation: dict[str, Any] = {
                    "instructions": instructions,
                    "input": cast(Any, conversation),
                    "max_output_tokens": min(
                        self.settings.llm_max_output_tokens,
                        capabilities.max_output_tokens,
                    ),
                }
                if active_tools:
                    continuation["tools"] = cast(Any, active_tools)
                if capabilities.structured_output:
                    continuation["text"] = cast(Any, model_narrative_text_config())
                response, active_model = self._create_response(
                    active_model,
                    **continuation,
                )
            except GenAIProviderError as exc:
                if preserved := self._preserve_mutation_result(tool_results, exc.code):
                    return preserved
                raise
            self._log_response(response)
        if preserved := self._preserve_mutation_result(
            tool_results, GenAIErrorCode.TOOL_STEP_LIMIT
        ):
            return preserved
        raise GenAIProviderError(GenAIErrorCode.TOOL_STEP_LIMIT, retryable=False)

    @staticmethod
    def _preserve_mutation_result(
        tool_results: list[tuple[str, dict[str, Any]]],
        code: GenAIErrorCode,
    ) -> AgentResult | None:
        mutation_names = {
            "update_cart",
            "update_delivery_preferences",
            "create_mock_checkout",
        }
        if not any(name in mutation_names for name, _ in tool_results):
            return None
        return AgentResult(
            text=(
                "I applied the explicit demo action on the server and preserved its "
                "authoritative result below. The language model continuation was unavailable."
            ),
            tool_results=tool_results,
            provider_error_code=code,
        )

    def _create_response(
        self,
        preferred_model: str,
        **kwargs: Any,
    ) -> tuple[Any, str]:
        input_limit = min(
            self.settings.llm_max_input_tokens,
            self.provider.capabilities.max_input_tokens,
        )
        if self._conservative_input_token_bound(kwargs) > input_limit:
            raise GenAIProviderError(
                GenAIErrorCode.CAPABILITY_LIMIT_EXCEEDED,
                retryable=False,
            )
        primary = self.settings.oci_genai_model
        fallback = self.settings.oci_genai_fallback_model
        candidates = list(dict.fromkeys([preferred_model, primary, fallback]))
        rate_limited: list[str] = []
        failures: list[GenAIProviderError] = []
        now = monotonic()
        for model in candidates:
            if not self.provider.supports_model(model):
                continue
            if self._cooldown_until.get(model, 0.0) > now:
                rate_limited.append(model)
                continue
            for attempt in range(self.settings.llm_max_retries + 1):
                try:
                    with self._request_slots:
                        response = self.provider.create_response(model, **kwargs)
                    log_event(
                        self.logger,
                        event="oci_genai_model_selected",
                        model=model,
                        provider=self.provider.capabilities.provider,
                        fallback_model_used=model != primary,
                        serving_mode=self.provider.capabilities.serving_mode.value,
                        prompt_profile=self.settings.genai_prompt_profile,
                        retry_attempt=attempt,
                    )
                    return response, model
                except GenAIProviderError as exc:
                    failures.append(exc)
                    retry_delay = 0.0
                    if exc.code is GenAIErrorCode.RATE_LIMIT:
                        cause = exc.cause
                        cooldown = (
                            retry_delay_seconds(cause)
                            if isinstance(cause, RateLimitError)
                            else 65.0
                        )
                        self._cooldown_until[model] = monotonic() + cooldown
                        rate_limited.append(model)
                    elif exc.retryable and attempt < self.settings.llm_max_retries:
                        ceiling = min(
                            self.settings.llm_retry_max_seconds,
                            self.settings.llm_retry_base_seconds * (2**attempt),
                        )
                        retry_delay = ceiling * random.uniform(0.75, 1.25)
                    else:
                        cooldown = 0.0
                    log_event(
                        self.logger,
                        event="oci_genai_provider_error",
                        model=model,
                        provider=self.provider.capabilities.provider,
                        serving_mode=self.provider.capabilities.serving_mode.value,
                        cooldown_seconds=(
                            round(cooldown, 1)
                            if exc.code is GenAIErrorCode.RATE_LIMIT
                            else None
                        ),
                        retry_delay_seconds=round(retry_delay, 3) or None,
                        retry_attempt=attempt,
                        safe_error_code=exc.code.value,
                        retryable=exc.retryable,
                    )
                    if not exc.retryable:
                        raise
                    if exc.code is GenAIErrorCode.RATE_LIMIT:
                        break
                    if retry_delay:
                        sleep(retry_delay)
        if failures:
            raise failures[-1]
        if rate_limited:
            raise GenAIProviderError(GenAIErrorCode.RATE_LIMIT, retryable=True)
        raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)

    @classmethod
    def _conservative_input_token_bound(cls, payload: dict[str, Any]) -> int:
        """Bound tokens without a model tokenizer by counting serialized UTF-8 bytes.

        OCI model tokenizers operate on byte-derived text, so serialized byte length
        is a deliberately conservative upper bound. This can reject early, but it
        cannot silently send a request larger than the declared provider contract.
        """

        def json_default(value: Any) -> Any:
            model_dump = getattr(value, "model_dump", None)
            if callable(model_dump):
                return model_dump()
            attributes = getattr(value, "__dict__", None)
            if isinstance(attributes, dict):
                return attributes
            return str(value)

        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=json_default,
        )
        return len(serialized.encode("utf-8"))

    @staticmethod
    def _compact_tool_result(name: str, result: dict[str, Any]) -> Any:
        """Keep provider continuation payloads grounded and within a small token budget."""
        if name == "search_menus":
            return {
                "menus": [
                    {
                        key: menu.get(key)
                        for key in (
                            "menu_id",
                            "merchant_id",
                            "merchant_name",
                            "name_en",
                            "name_ko",
                            "category",
                            "price",
                            "spice_level",
                            "dietary_summary",
                            "evidence_status",
                            "match_reasons",
                            "risk_hints",
                            "evidence_ids",
                        )
                    }
                    for menu in result.get("menus", [])[:4]
                    if isinstance(menu, dict)
                ]
            }
        if name == "get_dietary_evidence":
            return {
                "menu_id": result.get("menu_id"),
                "evidence": result.get("evidence", [])[:4],
                "ingredient_claims": result.get("ingredient_claims", [])[:12],
                "allergen_claims": result.get("allergen_claims", [])[:12],
                "dietary_claims": result.get("dietary_claims", [])[:12],
                "preparation_claims": result.get("preparation_claims", [])[:8],
                "merchant_ingredient_claims": result.get(
                    "merchant_ingredient_claims", []
                )[:8],
                "wiki_passages": result.get("wiki_passages", [])[:5],
                "unknown_fields": result.get("unknown_fields", [])[:6],
                "grounded_claim_ids": result.get("grounded_claim_ids", [])[:24],
                "grounded_passage_ids": result.get("grounded_passage_ids", [])[:8],
            }
        if name == "explain_menu":
            explanation = result.get("explanation", {})
            return {
                "menu": AgentLoop._sanitize_tool_result(result.get("menu", {})),
                "explanation": AgentLoop._sanitize_tool_result(explanation),
            }
        if name == "compare_merchants":
            return {"merchants": result.get("merchants", [])[:3]}
        if name == "get_menu_options":
            return {"option_groups": result.get("option_groups", [])[:6]}
        return AgentLoop._sanitize_tool_result(result)

    @staticmethod
    def _sanitize_tool_result(value: Any) -> Any:
        """Bound untrusted catalog text before it returns to the model."""
        if isinstance(value, str):
            return value[:500]
        if isinstance(value, list):
            return [AgentLoop._sanitize_tool_result(item) for item in value[:12]]
        if isinstance(value, dict):
            return {
                str(key)[:100]: AgentLoop._sanitize_tool_result(item)
                for key, item in list(value.items())[:40]
            }
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)[:500]

    def _log_response(self, response: Any) -> None:
        request_id = getattr(response, "_request_id", None)
        log_event(
            self.logger,
            event="oci_genai_response",
            provider_request_id=request_id,
            response_id=getattr(response, "id", None),
        )
