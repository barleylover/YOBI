from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.models import AssistantTurn
from app.genai.contracts import GenAIErrorCode, GenAIProviderError
from app.genai.response_contract import GroundingScope, UncertaintyCode


@dataclass
class _GroundingInventory:
    menu_ids: list[str] = field(default_factory=list)
    claim_ids: set[str] = field(default_factory=set)
    passage_ids: set[str] = field(default_factory=set)
    wiki_claim_ids: set[str] = field(default_factory=set)
    menu_claim_ids: set[str] = field(default_factory=set)
    cross_contact_claim_ids: set[str] = field(default_factory=set)
    denied_claim_ids: set[str] = field(default_factory=set)
    uncertainty_codes: set[str] = field(default_factory=set)


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
        "fried chicken",
        "pizza",
        "gukbap",
        "hotteok",
        "seolleongtang",
        "eomuk",
    )
    _untrusted_containers = {
        "merchant_origin_notes",
        "merchant_description",
        "merchant_text",
        "reviews",
        "review_snippets",
    }
    _claim_list_keys = {
        "evidence_ids",
        "grounded_claim_ids",
        "claim_ids",
    }
    _passage_list_keys = {"grounded_passage_ids", "passage_ids"}

    def validate(
        self,
        turn: AssistantTurn,
        referenced_menu_ids: list[str] | None,
        referenced_claim_ids: list[str] | None,
        referenced_passage_ids: list[str] | None = None,
        grounding_scope: GroundingScope | None = None,
        uncertainty_codes: list[UncertaintyCode] | None = None,
    ) -> None:
        inventory = self._inventory(turn)
        menu_refs = referenced_menu_ids or []
        claim_refs = referenced_claim_ids or []
        passage_refs = referenced_passage_ids or []

        if not self._is_ordered_subset(menu_refs, inventory.menu_ids):
            self._reject()
        # Passage IDs were historically permitted in referenced_claim_ids. Keep
        # that read compatibility while requiring the new passage field itself to
        # contain only tool-returned Wiki chunks.
        legacy_allowed_claims = inventory.claim_ids | inventory.passage_ids
        if not set(claim_refs).issubset(legacy_allowed_claims):
            self._reject()
        if not set(passage_refs).issubset(inventory.passage_ids):
            self._reject()
        if set(claim_refs) & inventory.denied_claim_ids:
            self._reject()
        if set(passage_refs) & inventory.denied_claim_ids:
            self._reject()

        if grounding_scope is not None:
            expected_scope = self._expected_scope(
                inventory,
                menu_refs,
                claim_refs,
                passage_refs,
            )
            if grounding_scope != expected_scope:
                self._reject()
            if (
                set(claim_refs) & inventory.cross_contact_claim_ids
                and "CROSS_CONTACT_UNKNOWN" not in set(uncertainty_codes or [])
            ):
                self._reject()
        if not set(uncertainty_codes or []).issubset(inventory.uncertainty_codes):
            self._reject()

        lowered = turn.text.lower()
        if any(value in lowered for value in self.forbidden_user_text):
            self._reject()
        if re.search(
            r"\b(?:menu|merchant|ev|claim|chunk|snapshot|option|oi|dish|ingredient|allergen)_[a-z0-9_]+\b",
            lowered,
        ):
            self._reject()

    def validate_no_tool_dialogue(
        self,
        turn: AssistantTurn,
        response_kind: str | None,
        *,
        referenced_menu_ids: list[str] | None = None,
        referenced_claim_ids: list[str] | None = None,
        referenced_passage_ids: list[str] | None = None,
        grounding_scope: GroundingScope | None = None,
        uncertainty_codes: list[UncertaintyCode] | None = None,
    ) -> None:
        if turn.cards or response_kind not in {"QUESTION", "ACKNOWLEDGEMENT", "SUMMARY"}:
            raise GenAIProviderError(GenAIErrorCode.NO_TOOL_RESPONSE, retryable=False)
        if any(
            (
                referenced_menu_ids,
                referenced_claim_ids,
                referenced_passage_ids,
                uncertainty_codes,
            )
        ) or grounding_scope not in {None, "NONE"}:
            self._reject()
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
            self._reject()
        if any(term in lowered for term in self.no_tool_menu_terms):
            self._reject()
        if re.search(r"(?:₩|krw\s*)\d", lowered):
            self._reject()

    def _inventory(self, turn: AssistantTurn) -> _GroundingInventory:
        inventory = _GroundingInventory()

        def visit(value: object, container: str | None = None) -> None:
            if isinstance(value, dict):
                if container in self._untrusted_containers:
                    self._collect_denied_claim_ids(value, inventory.denied_claim_ids)
                    return

                menu_id = value.get("menu_id")
                if menu_id:
                    normalized_menu_id = str(menu_id)
                    if normalized_menu_id not in inventory.menu_ids:
                        inventory.menu_ids.append(normalized_menu_id)

                source_scope = str(value.get("source_scope") or "").upper()
                source_type = str(value.get("source_type") or "").upper()
                structured_cross_contact = (
                    container == "merchant_ingredient_claims"
                    and source_scope in {"MERCHANT", "KITCHEN"}
                )
                untrusted_source = not structured_cross_contact and (
                    source_scope in {"MERCHANT", "KITCHEN"}
                    or any(marker in source_type for marker in ("REVIEW", "MERCHANT"))
                )
                claim_id = value.get("source_id") or value.get("claim_id")
                if claim_id and (
                    container
                    in {
                        "ingredient_claims",
                        "allergen_claims",
                        "dietary_claims",
                        "preparation_claims",
                        "evidence",
                    }
                    or source_scope
                ):
                    normalized_claim_id = str(claim_id)
                    if untrusted_source:
                        inventory.denied_claim_ids.add(normalized_claim_id)
                    else:
                        inventory.claim_ids.add(normalized_claim_id)
                        if structured_cross_contact:
                            inventory.cross_contact_claim_ids.add(normalized_claim_id)
                            inventory.menu_claim_ids.add(normalized_claim_id)
                            inventory.uncertainty_codes.add("CROSS_CONTACT_UNKNOWN")
                        elif source_scope == "DISH_CONCEPT":
                            inventory.wiki_claim_ids.add(normalized_claim_id)
                        else:
                            inventory.menu_claim_ids.add(normalized_claim_id)
                        status = str(
                            value.get("status") or value.get("assertion_status") or ""
                        ).upper()
                        cross_contact = str(
                            value.get("cross_contamination_status") or ""
                        ).upper()
                        if (
                            container == "allergen_claims"
                            and source_scope == "MENU"
                            and status == "CONFIRMED_ABSENT"
                            and cross_contact == "UNKNOWN"
                        ):
                            inventory.cross_contact_claim_ids.add(normalized_claim_id)
                            inventory.uncertainty_codes.add("CROSS_CONTACT_UNKNOWN")

                evidence_id = value.get("evidence_id")
                if evidence_id:
                    normalized_evidence_id = str(evidence_id)
                    if untrusted_source:
                        inventory.denied_claim_ids.add(normalized_evidence_id)
                    else:
                        inventory.claim_ids.add(normalized_evidence_id)
                        inventory.menu_claim_ids.add(normalized_evidence_id)

                chunk_id = value.get("chunk_id")
                if chunk_id and not untrusted_source:
                    inventory.passage_ids.add(str(chunk_id))

                self._collect_uncertainty(value, source_scope, inventory)

                for key in self._claim_list_keys:
                    source_ids = value.get(key)
                    if isinstance(source_ids, list):
                        inventory.claim_ids.update(str(item) for item in source_ids)
                for key in self._passage_list_keys:
                    source_ids = value.get(key)
                    if isinstance(source_ids, list):
                        inventory.passage_ids.update(str(item) for item in source_ids)
                for key, item in value.items():
                    visit(item, key)
            elif isinstance(value, list):
                for item in value:
                    visit(item, container)

        for card in turn.cards:
            visit(card.data)

        inventory.denied_claim_ids.update(
            claim_id
            for claim_id in inventory.claim_ids
            if self._looks_untrusted_claim_id(claim_id)
            and claim_id not in inventory.cross_contact_claim_ids
        )
        inventory.claim_ids.difference_update(inventory.denied_claim_ids)
        inventory.wiki_claim_ids.difference_update(inventory.denied_claim_ids)
        inventory.menu_claim_ids.difference_update(inventory.denied_claim_ids)
        inventory.cross_contact_claim_ids.difference_update(inventory.denied_claim_ids)
        # Flat legacy evidence lists have no scope metadata. They are tied to the
        # concrete menu result, so classify only the still-unclassified IDs as menu facts.
        inventory.menu_claim_ids.update(
            inventory.claim_ids - inventory.wiki_claim_ids - inventory.passage_ids
        )
        return inventory

    @staticmethod
    def _collect_denied_claim_ids(value: object, target: set[str]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {
                    "source_id",
                    "claim_id",
                    "evidence_id",
                    "chunk_id",
                    "declaration_id",
                } and item:
                    target.add(str(item))
                else:
                    GroundedResponseValidator._collect_denied_claim_ids(item, target)
        elif isinstance(value, list):
            for item in value:
                GroundedResponseValidator._collect_denied_claim_ids(item, target)

    @staticmethod
    def _collect_uncertainty(
        value: dict[object, object],
        source_scope: str,
        inventory: _GroundingInventory,
    ) -> None:
        status = str(value.get("status") or value.get("assertion_status") or "").upper()
        if status == "POSSIBLE" and source_scope == "DISH_CONCEPT":
            inventory.uncertainty_codes.add("WIKI_POSSIBLE")
        elif status in {"UNKNOWN", "NOT_PROVIDED"} and source_scope == "DISH_CONCEPT":
            inventory.uncertainty_codes.add("WIKI_UNKNOWN")
        elif status == "NOT_PROVIDED":
            inventory.uncertainty_codes.add("MENU_DATA_NOT_PROVIDED")
        elif status == "UNKNOWN":
            inventory.uncertainty_codes.add("MENU_DATA_UNKNOWN")
        if status == "CONFLICTING":
            inventory.uncertainty_codes.add("CONFLICTING_INFORMATION")
        if str(value.get("cross_contamination_status") or "").upper() == "UNKNOWN":
            inventory.uncertainty_codes.add("CROSS_CONTACT_UNKNOWN")

        uncertain_text: list[str] = []
        for key in ("unknown_fields", "risk_hints", "dietary_warnings", "warnings"):
            item = value.get(key)
            if isinstance(item, list):
                uncertain_text.extend(str(entry) for entry in item)
            elif isinstance(item, str):
                uncertain_text.append(item)
        claim_type = str(value.get("claim_type") or "")
        if claim_type:
            uncertain_text.append(claim_type)
        lowered = " ".join(uncertain_text).lower()
        if any(
            marker in lowered
            for marker in (
                "not provided",
                "not_provided",
                "menu-specific",
                "merchant-specific recipe",
                "정보 미제공",
            )
        ):
            inventory.uncertainty_codes.add("MENU_DATA_NOT_PROVIDED")
        if any(
            marker in lowered
            for marker in (
                "cross-contact",
                "cross contact",
                "cross-contamination",
                "cross contamination",
                "교차오염",
                "교차 오염",
            )
        ):
            inventory.uncertainty_codes.add("CROSS_CONTACT_UNKNOWN")
        if "severe" in lowered and any(
            marker in lowered for marker in ("unknown", "unverified", "not provided")
        ):
            inventory.uncertainty_codes.add("SEVERE_ALLERGY_UNVERIFIED")

    @staticmethod
    def _expected_scope(
        inventory: _GroundingInventory,
        menu_refs: list[str],
        claim_refs: list[str],
        passage_refs: list[str],
    ) -> GroundingScope:
        cited_claims = set(claim_refs)
        wiki_used = bool(passage_refs) or bool(cited_claims & inventory.passage_ids) or bool(
            cited_claims & inventory.wiki_claim_ids
        )
        menu_used = bool(menu_refs) or bool(cited_claims & inventory.menu_claim_ids)
        if wiki_used and menu_used:
            return "MIXED"
        if wiki_used:
            return "WIKI_GENERAL"
        if menu_used:
            return "MENU_SPECIFIC"
        return "NONE"

    @staticmethod
    def _is_ordered_subset(references: list[str], allowed: list[str]) -> bool:
        if len(references) != len(set(references)):
            return False
        position = 0
        for reference in references:
            while position < len(allowed) and allowed[position] != reference:
                position += 1
            if position == len(allowed):
                return False
            position += 1
        return True

    @staticmethod
    def _looks_untrusted_claim_id(claim_id: str) -> bool:
        lowered = claim_id.lower()
        return lowered.startswith(("origin_", "review_", "rev_"))

    @staticmethod
    def _reject() -> None:
        raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
