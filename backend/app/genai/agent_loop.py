from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any, cast

from openai import RateLimitError

from app.core.config import Settings
from app.core.logging import log_event
from app.genai.client import OciGenAIClient
from app.genai.prompts import SYSTEM_PROMPT
from app.genai.rate_limit import retry_delay_seconds
from app.genai.tool_registry import ToolRegistry
from app.genai.tool_schemas import select_tools


@dataclass
class AgentResult:
    text: str
    tool_results: list[tuple[str, dict[str, Any]]]


class AgentLoop:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client_factory = OciGenAIClient(settings)
        self.logger = logging.getLogger("yobi")
        self._cooldown_until: dict[str, float] = {}

    @property
    def configured(self) -> bool:
        return self.client_factory.configured

    def run(self, user_text: str, dynamic_context: str, registry: ToolRegistry) -> AgentResult:
        client = self.client_factory.build()
        instructions = f"{SYSTEM_PROMPT}\n\nSession context:\n{dynamic_context}"
        active_tools = select_tools(user_text)
        # Keep the full tool exchange client-side. The legacy OCI endpoint used by the
        # deployed demo accepts Responses input items, but its stored-response
        # continuation has proved unreliable in production. This is also an official
        # Responses API state-management pattern and keeps every function call paired
        # with its output without depending on provider retention.
        conversation: list[Any] = [{"role": "user", "content": user_text}]
        response, active_model = self._create_response(
            client,
            self.settings.oci_genai_model,
            instructions=instructions,
            input=cast(Any, conversation),
            tools=cast(Any, active_tools),
        )
        self._log_response(response)
        tool_results: list[tuple[str, dict[str, Any]]] = []
        for _ in range(self.settings.tool_call_max_steps):
            calls: list[Any] = [
                item for item in response.output if getattr(item, "type", None) == "function_call"
            ]
            if not calls:
                text = response.output_text.strip()
                if not text:
                    raise RuntimeError("GENAI_EMPTY_RESPONSE")
                return AgentResult(text=text, tool_results=tool_results)
            conversation.extend(response.output)
            outputs = []
            for call in calls:
                result = registry.execute(call.name, call.arguments)
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
            response, active_model = self._create_response(
                client,
                active_model,
                input=cast(Any, conversation),
                tools=cast(Any, active_tools),
            )
            self._log_response(response)
        raise RuntimeError("GENAI_TOOL_STEP_LIMIT")

    def _create_response(
        self,
        client: Any,
        preferred_model: str,
        **kwargs: Any,
    ) -> tuple[Any, str]:
        primary = self.settings.oci_genai_model
        fallback = self.settings.oci_genai_fallback_model
        candidates = list(dict.fromkeys([preferred_model, primary, fallback]))
        rate_limited: list[str] = []
        now = monotonic()
        for model in candidates:
            if self._cooldown_until.get(model, 0.0) > now:
                rate_limited.append(model)
                continue
            try:
                response = client.responses.create(model=model, **kwargs)
                log_event(
                    self.logger,
                    event="oci_genai_model_selected",
                    model=model,
                    fallback_model_used=model != primary,
                )
                return response, model
            except RateLimitError as exc:
                delay = retry_delay_seconds(exc)
                self._cooldown_until[model] = monotonic() + delay
                rate_limited.append(model)
                log_event(
                    self.logger,
                    event="oci_genai_rate_limit",
                    model=model,
                    cooldown_seconds=round(delay, 1),
                    safe_error_code="RATE_LIMIT",
                )
        if rate_limited:
            raise RuntimeError("GENAI_RATE_LIMITED_ALL_MODELS")
        raise RuntimeError("GENAI_NO_MODEL_AVAILABLE")

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
            return {"evidence": result.get("evidence", [])[:4]}
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
