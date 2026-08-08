from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    response_kind: Literal[
        "QUESTION", "ACKNOWLEDGEMENT", "SUMMARY", "GROUNDED_RESULT"
    ] | None = None
    referenced_menu_ids: list[str] = Field(default_factory=list)
    referenced_claim_ids: list[str] = Field(default_factory=list)


class ParsedNarrative(BaseModel):
    narrative: ModelNarrative
    structured: bool


MODEL_NARRATIVE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "minLength": 1, "maxLength": 2000},
        "response_kind": {
            "type": "string",
            "enum": ["QUESTION", "ACKNOWLEDGEMENT", "SUMMARY", "GROUNDED_RESULT"],
        },
        "referenced_menu_ids": {"type": "array", "items": {"type": "string"}},
        "referenced_claim_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "message",
        "response_kind",
        "referenced_menu_ids",
        "referenced_claim_ids",
    ],
    "additionalProperties": False,
}


def model_narrative_text_config() -> dict[str, Any]:
    """Responses API text format used only when the provider advertises support."""

    return {
        "format": {
            "type": "json_schema",
            "name": "yobi_narrative",
            "description": "A grounded, user-facing YOBI dialogue response.",
            "schema": MODEL_NARRATIVE_JSON_SCHEMA,
            "strict": True,
        }
    }


def parse_model_narrative(raw: str) -> ParsedNarrative:
    """Normalize provider text; server-owned cards remain the factual authority."""

    stripped = raw.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return ParsedNarrative(
            narrative=ModelNarrative(message=stripped),
            structured=False,
        )
    if not isinstance(value, dict):
        return ParsedNarrative(
            narrative=ModelNarrative(message=stripped),
            structured=False,
        )
    return ParsedNarrative(
        narrative=ModelNarrative.model_validate(value),
        structured=True,
    )
