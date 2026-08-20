from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ResponseKind = Literal["QUESTION", "ACKNOWLEDGEMENT", "SUMMARY", "GROUNDED_RESULT"]
GroundingScope = Literal["NONE", "WIKI_GENERAL", "MENU_SPECIFIC", "MIXED"]
UncertaintyCode = Literal[
    "WIKI_POSSIBLE",
    "WIKI_UNKNOWN",
    "MENU_DATA_NOT_PROVIDED",
    "MENU_DATA_UNKNOWN",
    "CONFLICTING_INFORMATION",
    "CROSS_CONTACT_UNKNOWN",
    "SEVERE_ALLERGY_UNVERIFIED",
]


class ModelNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    response_kind: ResponseKind | None = None
    referenced_menu_ids: list[str] = Field(default_factory=list)
    referenced_claim_ids: list[str] = Field(default_factory=list)
    # Defaults preserve parsing compatibility with providers that have not yet
    # adopted the extended contract. Structured-output providers receive all
    # fields as required properties in MODEL_NARRATIVE_JSON_SCHEMA below.
    referenced_passage_ids: list[str] = Field(default_factory=list)
    grounding_scope: GroundingScope | None = None
    uncertainty_codes: list[UncertaintyCode] = Field(default_factory=list)


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
        "referenced_passage_ids": {"type": "array", "items": {"type": "string"}},
        "grounding_scope": {
            "type": "string",
            "enum": ["NONE", "WIKI_GENERAL", "MENU_SPECIFIC", "MIXED"],
        },
        "uncertainty_codes": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "WIKI_POSSIBLE",
                    "WIKI_UNKNOWN",
                    "MENU_DATA_NOT_PROVIDED",
                    "MENU_DATA_UNKNOWN",
                    "CONFLICTING_INFORMATION",
                    "CROSS_CONTACT_UNKNOWN",
                    "SEVERE_ALLERGY_UNVERIFIED",
                ],
            },
        },
    },
    "required": [
        "message",
        "response_kind",
        "referenced_menu_ids",
        "referenced_claim_ids",
        "referenced_passage_ids",
        "grounding_scope",
        "uncertainty_codes",
    ],
    "additionalProperties": False,
}


def parse_json_object(raw: str) -> dict[str, Any]:
    """Extract one JSON object from common provider response wrappers.

    OCI-hosted models do not all honor JSON-only instructions identically.  This
    accepts fenced JSON and a short leading/trailing explanation while still
    rejecting arrays, scalar values, and multiple unrelated objects.
    """

    stripped = raw.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        value = None
        for index, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                candidate, consumed = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            trailing = stripped[index + consumed :].strip()
            if isinstance(candidate, dict) and not trailing.lstrip().startswith("{"):
                value = candidate
                break
        if value is None:
            raise
    if not isinstance(value, dict):
        raise ValueError("MODEL_RESPONSE_JSON_OBJECT_REQUIRED")
    return value


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
