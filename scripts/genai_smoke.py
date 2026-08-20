#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from openai import APIError, APIStatusError, OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.genai.client import OciGenAIClient
from app.genai.rate_limit import call_with_rate_limit_retry


def _safe_retry_notice(delay: float, attempt: int, maximum: int) -> None:
    print(
        f"OCI GenAI rate limit; retrying in {delay:.1f}s ({attempt}/{maximum}).",
        file=sys.stderr,
        flush=True,
    )


def _create(client: OpenAI, **kwargs: Any) -> Any:
    responses = client.responses
    return call_with_rate_limit_retry(
        responses.create,
        max_retries=2,
        sleep=time.sleep,
        on_retry=_safe_retry_notice,
        **kwargs,
    )


def main() -> None:
    settings = Settings()
    client = OciGenAIClient(settings).build()
    tool = {
        "type": "function",
        "name": "search_menus",
        "description": "Search grounded YOBI menu data.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "budget_krw": {"type": "integer"},
                "max_spiciness": {"type": "integer"},
                "excluded_ingredients": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query", "budget_krw", "max_spiciness", "excluded_ingredients"],
            "additionalProperties": False,
        },
    }
    conversation: list[Any] = [
        {
            "role": "user",
            "content": (
                "Find a Korean meal for one, no pork, not spicy, under 15000 KRW. "
                "Use the tool. After receiving the tool output, reply exactly "
                "YOBI_TOOL_LOOP_OK."
            ),
        }
    ]
    response = _create(
        client,
        model=settings.oci_genai_model,
        input=conversation,
        tools=[tool],
        tool_choice="required",
    )
    calls = [
        item
        for item in response.output
        if getattr(item, "type", None) == "function_call"
    ]
    if len(calls) != 1 or calls[0].name != "search_menus":
        raise SystemExit("GenAI function-call smoke did not return exactly one search_menus call")
    arguments = json.loads(calls[0].arguments)
    required = {"query", "budget_krw", "max_spiciness", "excluded_ingredients"}
    if not required.issubset(arguments):
        raise SystemExit("GenAI function-call arguments were incomplete")
    conversation += response.output
    conversation.append(
        {
            "type": "function_call_output",
            "call_id": calls[0].call_id,
            "output": json.dumps(
                {
                    "untrusted_data": {
                        "menus": [
                            {
                                "menu_id": "menu_003_01",
                                "name_en": "Chicken kalguksu",
                                "price": 12000,
                                "spice_level": 0,
                                "synthetic": True,
                            }
                        ]
                    }
                }
            ),
        }
    )
    final = _create(
        client,
        model=settings.oci_genai_model,
        input=conversation,
        tools=[tool],
    )
    if final.output_text.strip() != "YOBI_TOOL_LOOP_OK":
        raise SystemExit("GenAI multi-step function loop did not return the expected sentinel")
    print("PASS: OCI Grok function call and multi-step continuation")


def safe_main() -> None:
    try:
        main()
    except APIError as exc:
        status_code = exc.status_code if isinstance(exc, APIStatusError) else None
        code = "RATE_LIMIT" if status_code == 429 else f"HTTP_{status_code or 'ERROR'}"
        raise SystemExit(f"OCI GenAI smoke failed safely: {code}") from None
    except RuntimeError as exc:
        code = str(exc) if str(exc).startswith("GENAI_") else "GENAI_RUNTIME_ERROR"
        raise SystemExit(f"OCI GenAI smoke failed safely: {code}") from None


if __name__ == "__main__":
    safe_main()
