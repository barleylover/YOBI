from __future__ import annotations

import hashlib
import json
import logging
from time import monotonic
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.logging import log_event
from app.db.repository import YobiRepository
from app.domain.models import (
    CartItemInput,
    CartItemUpdate,
    CheckoutCreate,
    DeliveryPreferenceInput,
    Profile,
)


class SearchMenusArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    budget_krw: int | None = Field(default=None, ge=0, le=200000)
    max_spiciness: int | None = Field(default=None, ge=0, le=5)
    excluded_ingredients: list[str] = Field(default_factory=list)


class CategoryArgs(SearchMenusArgs):
    servings: int = Field(default=1, ge=1, le=10)
    desired_temperature: str = Field(default="any", pattern=r"^(warm|cold|any)$")
    desired_texture: list[str] = Field(default_factory=list)
    desired_flavors: list[str] = Field(default_factory=list)


class MenuIdArgs(BaseModel):
    menu_id: str = Field(pattern=r"^menu_[a-zA-Z0-9_]+$")


class CompareArgs(BaseModel):
    category: str = Field(min_length=1, max_length=100)


class TranslateNoteArgs(BaseModel):
    user_note: str = Field(min_length=1, max_length=500)
    target_context: str = Field(default="restaurant", pattern=r"^(restaurant|courier)$")
    tone: str = Field(default="polite", pattern=r"^(polite|concise)$")


class ResolveAddressArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class CheckoutIdArgs(BaseModel):
    checkout_id: str = Field(pattern=r"^checkout_[a-f0-9]+$")


class UpdateCartArgs(BaseModel):
    action: Literal[
        "ADD_ITEM",
        "CHANGE_QUANTITY",
        "SELECT_OPTION",
        "REMOVE_OPTION",
        "REMOVE_ITEM",
        "ADD_NOTE",
        "CLEAR",
    ]
    menu_id: str | None = Field(default=None, pattern=r"^menu_[a-zA-Z0-9_]+$")
    cart_item_id: str | None = Field(default=None, pattern=r"^cartitem_[a-f0-9]+$")
    quantity: int | None = Field(default=None, ge=1, le=10)
    option_item_id: str | None = Field(default=None, pattern=r"^oi_[a-zA-Z0-9_]+$")
    option_item_ids: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=500)


class DeliveryPreferenceArgs(BaseModel):
    address_ref_id: str | None = None
    handoff_method: Literal["front_desk", "door", "meet_outside"] = "front_desk"
    cutlery: bool = False
    ring_bell: bool = False
    front_desk: bool = True
    note: str = Field(default="Please leave it at the hotel front desk.", max_length=500)


class CreateCheckoutArgs(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=100)
    payment_method: Literal["international_card", "apple_pay_demo", "paypal_demo"]


class ToolRegistry:
    def __init__(
        self, repository: YobiRepository, profile: Profile, session_id: str | None = None
    ) -> None:
        self.repository = repository
        self.profile = profile
        self.session_id = session_id
        self.logger = logging.getLogger("yobi")

    def execute(self, name: str, raw_arguments: str) -> dict[str, Any]:
        started = monotonic()
        result: dict[str, Any]
        try:
            payload = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            self._audit(name, raw_arguments, {}, started, "REJECTED", "INVALID_TOOL_ARGUMENTS_JSON")
            raise ValueError("INVALID_TOOL_ARGUMENTS_JSON") from exc

        try:
            if name == "recommend_menu_categories":
                category_args = CategoryArgs.model_validate(payload)
                menus = self.repository.search_menus(
                    category_args.query,
                    self.profile,
                    category_args.budget_krw,
                    category_args.max_spiciness,
                    category_args.excluded_ingredients,
                    limit=12,
                )
                categories: list[dict[str, Any]] = []
                for menu in menus:
                    if any(item["category"] == menu.category for item in categories):
                        continue
                    categories.append(
                        {
                            "category": menu.category,
                            "match_reasons": menu.match_reasons,
                            "risk_hints": menu.risk_hints,
                            "source_ids": [menu.menu_id, menu.merchant_id, *menu.evidence_ids],
                        }
                    )
                    if len(categories) == 4:
                        break
                result = {"categories": categories}
            elif name == "search_menus":
                search_args = SearchMenusArgs.model_validate(payload)
                result = {
                    "menus": [
                        menu.model_dump(mode="json")
                        for menu in self.repository.search_menus(
                            search_args.query,
                            self.profile,
                            search_args.budget_krw,
                            search_args.max_spiciness,
                            search_args.excluded_ingredients,
                        )
                    ]
                }
            elif name == "explain_menu":
                menu_args = MenuIdArgs.model_validate(payload)
                explained_menu = self.repository.get_menu(menu_args.menu_id, self.profile)
                if explained_menu is None:
                    raise ValueError("MENU_NOT_FOUND")
                evidence = self.repository.get_evidence(menu_args.menu_id)
                result = {
                    "menu": explained_menu.model_dump(mode="json"),
                    "explanation": {
                        "description": explained_menu.description,
                        "cultural_analogy": explained_menu.cultural_description,
                        "spice_level": explained_menu.spice_level,
                        "portion": f"{explained_menu.serves_min}-{explained_menu.serves_max} people",
                        "unknown_fields": explained_menu.risk_hints,
                        "evidence_ids": [item.evidence_id for item in evidence],
                    },
                }
            elif name == "get_dietary_evidence":
                evidence_args = MenuIdArgs.model_validate(payload)
                result = {
                    "evidence": [
                        item.model_dump(mode="json")
                        for item in self.repository.get_evidence(evidence_args.menu_id)
                    ]
                }
            elif name == "compare_merchants":
                compare_args = CompareArgs.model_validate(payload)
                result = {
                    "merchants": [
                        item.model_dump(mode="json")
                        for item in self.repository.compare_merchants(
                            compare_args.category, self.profile
                        )
                    ]
                }
            elif name == "get_menu_options":
                options_args = MenuIdArgs.model_validate(payload)
                result = {
                    "option_groups": [
                        item.model_dump(mode="json")
                        for item in self.repository.get_options(options_args.menu_id)
                    ]
                }
            elif name == "translate_order_note":
                note_args = TranslateNoteArgs.model_validate(payload)
                lowered = note_args.user_note.lower()
                translations = []
                warnings = []
                if "mild" in lowered or "not spicy" in lowered:
                    translations.append("최대한 맵지 않게 부탁드립니다.")
                if "front desk" in lowered:
                    translations.append("호텔 프런트에 맡겨 주세요.")
                if "no cutlery" in lowered or "no disposable" in lowered:
                    translations.append("일회용 수저와 포크는 필요 없습니다.")
                if not translations:
                    warnings.append("Free-form translation was not verified; review before sending.")
                result = {
                    "original": note_args.user_note,
                    "korean_translation": " ".join(translations) or "요청사항을 확인해 주세요.",
                    "back_translation": note_args.user_note,
                    "warnings": warnings,
                    "requires_confirmation": True,
                }
            elif name == "resolve_address":
                address_args = ResolveAddressArgs.model_validate(payload)
                result = {
                    "candidates": [
                        item.model_dump(mode="json")
                        for item in self.repository.resolve_address(address_args.text)
                    ],
                    "requires_confirmation": True,
                }
            elif name == "update_cart":
                if not self.session_id:
                    raise ValueError("SESSION_CONTEXT_REQUIRED")
                cart_args = UpdateCartArgs.model_validate(payload)
                result = {"cart": self._update_cart(cart_args).model_dump(mode="json")}
            elif name == "update_delivery_preferences":
                if not self.session_id:
                    raise ValueError("SESSION_CONTEXT_REQUIRED")
                delivery_args = DeliveryPreferenceArgs.model_validate(payload)
                result = {
                    "cart": self.repository.update_delivery(
                        self.session_id,
                        DeliveryPreferenceInput(
                            address_ref_id=delivery_args.address_ref_id,
                            handoff_method=delivery_args.handoff_method,
                            cutlery=delivery_args.cutlery,
                            ring_bell=delivery_args.ring_bell,
                            front_desk=delivery_args.front_desk,
                            user_note=delivery_args.note,
                        ),
                    ).model_dump(mode="json"),
                    "requires_confirmation": True,
                }
            elif name == "get_cart_preview":
                if not self.session_id:
                    raise ValueError("SESSION_CONTEXT_REQUIRED")
                result = {
                    "cart": self.repository.get_cart(self.session_id).model_dump(mode="json")
                }
            elif name == "create_mock_checkout":
                if not self.session_id:
                    raise ValueError("SESSION_CONTEXT_REQUIRED")
                create_args = CreateCheckoutArgs.model_validate(payload)
                created_checkout = self.repository.create_checkout(
                    self.session_id,
                    CheckoutCreate(
                        idempotency_key=create_args.idempotency_key,
                        payment_method=create_args.payment_method,
                    ),
                )
                result = {"checkout": created_checkout.model_dump(mode="json")}
            elif name == "get_mock_payment_status":
                status_args = CheckoutIdArgs.model_validate(payload)
                stored_checkout = self.repository.get_checkout(status_args.checkout_id)
                if stored_checkout is None:
                    raise ValueError("CHECKOUT_NOT_FOUND")
                result = {"checkout": stored_checkout.model_dump(mode="json")}
            elif name == "complete_mock_order":
                complete_args = CheckoutIdArgs.model_validate(payload)
                completed_checkout = self.repository.get_checkout(complete_args.checkout_id)
                if completed_checkout is None:
                    raise ValueError("CHECKOUT_NOT_FOUND")
                if completed_checkout.status != "SUCCEEDED" or not completed_checkout.order_id:
                    raise ValueError("PAYMENT_NOT_SUCCEEDED")
                order = self.repository.get_order(completed_checkout.order_id)
                if order is None:
                    raise ValueError("ORDER_NOT_FOUND")
                result = {"order": order.model_dump(mode="json")}
            else:
                raise ValueError("UNKNOWN_TOOL")
        except Exception as exc:
            code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__.upper()
            self._audit(name, raw_arguments, {}, started, "ERROR", code)
            raise
        self._audit(name, raw_arguments, result, started, "OK", None)
        return result

    def _update_cart(self, args: UpdateCartArgs) -> Any:
        if not self.session_id:
            raise ValueError("SESSION_CONTEXT_REQUIRED")
        if args.action == "ADD_ITEM":
            if not args.menu_id:
                raise ValueError("MENU_ID_REQUIRED")
            return self.repository.add_cart_item(
                self.session_id,
                CartItemInput(
                    menu_id=args.menu_id,
                    quantity=args.quantity or 1,
                    option_item_ids=args.option_item_ids,
                    user_note=args.note or "",
                ),
            )
        cart = self.repository.get_cart(self.session_id)
        if args.action == "CLEAR":
            for line in cart.items:
                self.repository.delete_cart_item(self.session_id, line.cart_item_id)
            return self.repository.get_cart(self.session_id)
        if not args.cart_item_id:
            raise ValueError("CART_ITEM_ID_REQUIRED")
        matched_line = next(
            (item for item in cart.items if item.cart_item_id == args.cart_item_id), None
        )
        if matched_line is None:
            raise ValueError("CART_ITEM_NOT_FOUND")
        if args.action == "REMOVE_ITEM":
            return self.repository.delete_cart_item(self.session_id, matched_line.cart_item_id)
        if args.action == "CHANGE_QUANTITY":
            if args.quantity is None:
                raise ValueError("QUANTITY_REQUIRED")
            update = CartItemUpdate(quantity=args.quantity)
        elif args.action in {"SELECT_OPTION", "REMOVE_OPTION"}:
            if not args.option_item_id:
                raise ValueError("OPTION_ITEM_ID_REQUIRED")
            current = [str(item["option_item_id"]) for item in matched_line.options]
            if args.action == "SELECT_OPTION" and args.option_item_id not in current:
                current.append(args.option_item_id)
            if args.action == "REMOVE_OPTION":
                current = [item for item in current if item != args.option_item_id]
            update = CartItemUpdate(option_item_ids=current)
        elif args.action == "ADD_NOTE":
            if args.note is None:
                raise ValueError("NOTE_REQUIRED")
            update = CartItemUpdate(user_note=args.note)
        else:
            raise ValueError("UNSUPPORTED_CART_ACTION")
        return self.repository.update_cart_item(self.session_id, matched_line.cart_item_id, update)

    def _audit(
        self,
        name: str,
        raw_arguments: str,
        result: dict[str, Any],
        started: float,
        status: str,
        error_code: str | None,
    ) -> None:
        evidence_ids = self._evidence_ids(result)
        latency_ms = int((monotonic() - started) * 1000)
        self.repository.record_audit(
            self.session_id,
            name,
            raw_arguments,
            evidence_ids,
            status,
            latency_ms,
            False,
            error_code,
        )
        log_event(
            self.logger,
            request_id=None,
            session_id_hash=(
                hashlib.sha256(self.session_id.encode()).hexdigest() if self.session_id else None
            ),
            endpoint="agent_tool",
            latency_ms=latency_ms,
            tool=name,
            status=status,
            evidence_count=len(evidence_ids),
            fallback=False,
            safe_error_code=error_code,
        )

    @staticmethod
    def _evidence_ids(value: Any) -> list[str]:
        found: list[str] = []
        if isinstance(value, dict):
            evidence_id = value.get("evidence_id")
            if evidence_id:
                found.append(str(evidence_id))
            for item in value.values():
                found.extend(ToolRegistry._evidence_ids(item))
        elif isinstance(value, list):
            for item in value:
                found.extend(ToolRegistry._evidence_ids(item))
        return list(dict.fromkeys(found))[:50]
