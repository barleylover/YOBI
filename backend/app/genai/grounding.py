from __future__ import annotations

import re

from app.domain.models import AssistantTurn
from app.genai.contracts import GenAIErrorCode, GenAIProviderError


class GroundedResponseValidator:
    """Reject model references outside the server-owned card/result contract."""

    forbidden_user_text = (
        "search_menus",
        "recommend_menu_categories",
        "explain_menu",
        "get_dietary_evidence",
        "compare_merchants",
        "get_menu_options",
        "update_cart",
        "translate_order_note",
        "resolve_address",
        "update_delivery_preferences",
        "get_cart_preview",
        "create_mock_checkout",
        "get_mock_payment_status",
        "complete_mock_order",
        "function_call",
        "database password",
        "system prompt",
    )
    no_tool_menu_terms = (
        "tteokbokki",
        "kalguksu",
        "bibimbap",
        "gimbap",
        "samgyetang",
        "jjajangmyeon",
        "sundubu",
        "bulgogi",
        "kimchi stew",
        "japchae",
        "mandu",
        "naengmyeon",
        "dosirak",
        "gukbap",
        "hotteok",
        "seolleongtang",
        "eomuk",
    )

    def validate(
        self,
        turn: AssistantTurn,
        referenced_menu_ids: list[str] | None,
        referenced_claim_ids: list[str] | None,
    ) -> None:
        allowed_menu_ids: set[str] = set()
        allowed_claim_ids: set[str] = set()

        def visit(value: object) -> None:
            if isinstance(value, dict):
                menu_id = value.get("menu_id")
                evidence_id = value.get("evidence_id")
                if menu_id:
                    allowed_menu_ids.add(str(menu_id))
                if evidence_id:
                    allowed_claim_ids.add(str(evidence_id))
                for key in (
                    "evidence_ids",
                    "grounded_claim_ids",
                    "grounded_passage_ids",
                    "claim_ids",
                    "passage_ids",
                ):
                    source_ids = value.get(key)
                    if isinstance(source_ids, list):
                        allowed_claim_ids.update(str(item) for item in source_ids)
                for key in ("claim_id", "chunk_id"):
                    source_id = value.get(key)
                    if source_id:
                        allowed_claim_ids.add(str(source_id))
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for card in turn.cards:
            visit(card.data)
        if not set(referenced_menu_ids or []).issubset(allowed_menu_ids):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        if not set(referenced_claim_ids or []).issubset(allowed_claim_ids):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        lowered = turn.text.lower()
        if any(value in lowered for value in self.forbidden_user_text):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        if re.search(
            r"\b(?:menu|merchant|ev|claim|chunk|snapshot|option|oi|dish|ingredient|allergen)_[a-z0-9_]+\b",
            lowered,
        ):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)

    def validate_no_tool_dialogue(self, turn: AssistantTurn, response_kind: str | None) -> None:
        if turn.cards or response_kind not in {"QUESTION", "ACKNOWLEDGEMENT", "SUMMARY"}:
            raise GenAIProviderError(GenAIErrorCode.NO_TOOL_RESPONSE, retryable=False)
        lowered = turn.text.lower()
        recommendation_markers = (
            "i recommend",
            "i suggest",
            "best match",
            "top match",
            "i found a menu",
            "you should order",
            "good option",
            "great option",
            "a good choice",
            "you might like",
        )
        if any(marker in lowered for marker in recommendation_markers):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        if any(term in lowered for term in self.no_tool_menu_terms):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        if re.search(r"(?:₩|krw\s*)\d", lowered):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
