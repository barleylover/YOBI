from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4

from app.core.config import Settings
from app.core.logging import log_event
from app.db.repository import YobiRepository
from app.domain.models import AssistantTurn, Card, ChatState, Profile, Session
from app.genai.agent_loop import AgentLoop
from app.genai.tool_registry import ToolRegistry
from app.services.demo_control import DemoControl


class ChatService:
    def __init__(
        self,
        repository: YobiRepository,
        settings: Settings,
        demo_control: DemoControl,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.demo_control = demo_control
        self.agent = AgentLoop(settings)
        self.logger = logging.getLogger("yobi")

    def respond(self, session: Session, profile: Profile, user_text: str) -> AssistantTurn:
        started = monotonic()
        safe_error_code: str | None = None
        self.repository.save_message(session.session_id, "user", user_text, "text")
        use_fallback = (
            not self.agent.configured
            or self.demo_control.mode in {"force_fallback", "force_genai_timeout"}
        )
        if not use_fallback:
            try:
                result = self.agent.run(
                    user_text,
                    self._dynamic_context(session, profile),
                    ToolRegistry(self.repository, profile, session.session_id),
                )
                turn = self._turn_from_tool_results(session, result.text, result.tool_results)
                if not result.tool_results or not turn.cards:
                    raise RuntimeError("GENAI_GROUNDING_REQUIRED")
            except Exception as exc:
                if not self.settings.demo_fallback_enabled:
                    raise
                safe_error_code = type(exc).__name__.upper()
                use_fallback = True
        if use_fallback:
            turn = self._deterministic_turn(session, profile, user_text)
            turn.fallback_used = True
        self.repository.save_message(
            session.session_id,
            "assistant",
            turn.text,
            "assistant_turn",
        )
        evidence_ids = [
            str(item.get("evidence_id"))
            for card in turn.cards
            for item in card.data.get("evidence", [])
            if isinstance(item, dict) and item.get("evidence_id")
        ]
        latency_ms = int((monotonic() - started) * 1000)
        self.repository.record_audit(
            session.session_id,
            "assistant_turn",
            user_text,
            evidence_ids,
            "OK",
            latency_ms,
            turn.fallback_used,
            safe_error_code,
        )
        log_event(
            self.logger,
            request_id=None,
            session_id_hash=hashlib.sha256(session.session_id.encode()).hexdigest(),
            endpoint="assistant_turn",
            latency_ms=latency_ms,
            tool="assistant_turn",
            status="OK",
            evidence_count=len(evidence_ids),
            fallback=turn.fallback_used,
            safe_error_code=safe_error_code,
        )
        return turn

    def _dynamic_context(self, session: Session, profile: Profile) -> str:
        cart = self.repository.get_cart(session.session_id)
        recent_messages = self.repository.list_messages(session.session_id)[-5:]
        context = {
            "state": session.state.value,
            "language": profile.preferred_language,
            "dietary_rules": profile.dietary_rules,
            "allergy_severity": profile.allergy_severity,
            "spice_tolerance": profile.spice_tolerance,
            "favorite_foods": profile.favorite_foods,
            "selected_menu_id": session.selected_menu_id,
            "selected_merchant_id": session.selected_merchant_id,
            "cart": {
                "item_count": len(cart.items),
                "total_price_krw": cart.total_price,
                "missing_requirements": cart.missing_slots,
                "ready_to_checkout": cart.ready_to_checkout,
            },
            "recent_messages": [
                {"role": message["role"], "content": message["content"][:500]}
                for message in recent_messages
            ],
        }
        return json.dumps(context, ensure_ascii=False, separators=(",", ":"))

    def _turn_from_tool_results(
        self,
        session: Session,
        text: str,
        tool_results: list[tuple[str, dict[str, object]]],
    ) -> AssistantTurn:
        cards: list[Card] = []
        state = session.state
        for name, result in tool_results:
            if name == "recommend_menu_categories" and result.get("categories"):
                cards.append(
                    Card(
                        type="category_recommendations",
                        title="Korean food directions that fit",
                        subtitle="Grounded in the synthetic menu catalog",
                        data={"categories": result["categories"]},
                    )
                )
                state = ChatState.CATEGORY_SHORTLIST
            elif name == "search_menus" and result.get("menus"):
                cards.append(
                    Card(
                        type="menu_recommendations",
                        title="Grounded menu matches",
                        subtitle="Synthetic catalog · prices and evidence checked server-side",
                        data={"menus": result["menus"]},
                    )
                )
                state = ChatState.MENU_EXPLANATION
            elif name == "explain_menu" and result.get("menu"):
                cards.append(
                    Card(
                        type="menu_explanation",
                        title="What this dish will feel like",
                        subtitle="Taste, texture, portion, and unknowns",
                        data=result,
                    )
                )
                state = ChatState.MENU_EXPLANATION
            elif name == "get_dietary_evidence" and result.get("evidence"):
                cards.append(
                    Card(
                        type="dietary_evidence",
                        title="Dietary evidence",
                        subtitle="Evidence status is not a safety guarantee",
                        data={"evidence": result["evidence"]},
                    )
                )
                state = ChatState.SAFETY_WARNING
            elif name == "compare_merchants" and result.get("merchants"):
                cards.append(
                    Card(
                        type="merchant_comparison",
                        title="Compare the trade-offs",
                        subtitle="Same axes · synthetic demo restaurants",
                        data={"merchants": result["merchants"]},
                    )
                )
                state = ChatState.MERCHANT_COMPARISON
            elif name == "get_menu_options" and result.get("option_groups"):
                cards.append(
                    Card(
                        type="option_question",
                        title="Choose one option at a time",
                        data={"option_groups": result["option_groups"]},
                    )
                )
                state = ChatState.MENU_OPTIONS
            elif name == "translate_order_note" and result.get("korean_translation"):
                cards.append(
                    Card(
                        type="translated_note",
                        title="Review the translated note",
                        subtitle="Confirmation required before sending",
                        data=result,
                    )
                )
            elif name == "resolve_address" and result.get("candidates"):
                cards.append(
                    Card(
                        type="address_confirmation",
                        title="Confirm the delivery address",
                        subtitle="YOBI never confirms OCR output automatically",
                        data=result,
                    )
                )
                state = ChatState.DELIVERY_ADDRESS
            elif name == "get_cart_preview" and result.get("cart"):
                cards.append(
                    Card(
                        type="cart_summary",
                        title="Server-calculated cart",
                        subtitle="Prices and required slots rechecked",
                        data=result,
                    )
                )
        self.repository.set_session_selection(
            session.session_id, state.value, session.selected_menu_id, session.selected_merchant_id
        )
        return self._make_turn(text, state, cards, False)

    def _deterministic_turn(
        self, session: Session, profile: Profile, user_text: str
    ) -> AssistantTurn:
        lowered = user_text.lower()
        if any(phrase in lowered for phrase in ("walking in the rain", "warm and mild", "rainy")):
            menus = self.repository.search_menus(
                user_text,
                profile,
                15000,
                min(profile.spice_tolerance, 1),
                ["pork"] if "pork" in lowered else [],
                limit=12,
            )
            categories: list[dict[str, object]] = []
            for menu in menus:
                if any(item["category"] == menu.category for item in categories):
                    continue
                categories.append(
                    {
                        "category": menu.category,
                        "description": menu.cultural_description,
                        "match_reasons": menu.match_reasons,
                        "risk_hints": menu.risk_hints,
                        "source_ids": [menu.menu_id, menu.merchant_id],
                    }
                )
                if len(categories) == 4:
                    break
            self.repository.set_session_selection(
                session.session_id, ChatState.CATEGORY_SHORTLIST.value, None, None
            )
            return self._make_turn(
                "For something warm and gentle after the rain, I would start with a Korean "
                "chicken-noodle direction—similar in comfort to chicken noodle soup or soto "
                "ayam, but with thicker noodles. I kept the budget, pork exclusion, and spice "
                "limit as hard filters.",
                ChatState.CATEGORY_SHORTLIST,
                [
                    Card(
                        type="category_recommendations",
                        title="Warm, mild directions",
                        subtitle="Under ₩15,000 · no pork · spice 1/5 or below",
                        data={"categories": categories},
                    )
                ],
                False,
                ["Show me chicken kalguksu", "Show the mildest soup", "Try a rice dish"],
            )

        if "vegan" in lowered:
            vegan = self.repository.get_menu("menu_004_01", profile)
            assert vegan
            self.repository.set_session_selection(
                session.session_id, ChatState.SAFETY_WARNING.value, None, None
            )
            return self._make_turn(
                "Plant-forward bibimbap is a useful direction, but this synthetic menu does not "
                "verify every vegan detail or shellfish cross-contamination. Egg, meat garnish, "
                "broth, and gochujang ingredients must be confirmed, so I will not treat it as a "
                "safe match for your severe allergy.",
                ChatState.SAFETY_WARNING,
                [
                    Card(
                        type="category_recommendations",
                        title="Vegan direction—with checks still needed",
                        subtitle="Unknown is excluded from ordering for a severe allergy",
                        data={
                            "categories": [
                                {
                                    "category": "Bibimbap",
                                    "description": vegan.cultural_description,
                                    "match_reasons": [
                                        "Vegetables and sauce-on-the-side option"
                                    ],
                                    "risk_hints": [
                                        "Egg, meat garnish, broth, and gochujang need confirmation",
                                        "Shellfish cross-contamination is not verified",
                                    ],
                                    "source_ids": [vegan.menu_id, vegan.merchant_id],
                                }
                            ]
                        },
                    )
                ],
                False,
                ["Find only explicitly verified options", "Try a non-vegan mild dish"],
            )

        if "chicken kalguksu" in lowered:
            explained_menu = self.repository.get_menu("menu_003_01", profile)
            evidence = self.repository.get_evidence("menu_003_01")
            assert explained_menu
            self.repository.set_session_selection(
                session.session_id,
                ChatState.MENU_EXPLANATION.value,
                explained_menu.menu_id,
                explained_menu.merchant_id,
            )
            explanation = {
                "cultural_analogy": explained_menu.cultural_description,
                "portion": (
                    f"Usually serves {explained_menu.serves_min}-{explained_menu.serves_max}"
                ),
                "unknown_fields": explained_menu.risk_hints,
                "evidence_ids": [item.evidence_id for item in evidence],
            }
            return self._make_turn(
                "Chicken kalguksu is a warm, mild noodle-soup direction with thick handmade "
                "noodles and chicken broth. The synthetic sauce record marks shellfish absent, "
                "but kitchen cross-contamination remains unverified.",
                ChatState.MENU_EXPLANATION,
                [
                    Card(
                        type="menu_explanation",
                        title="What this dish will feel like",
                        subtitle="Taste, texture, portion, and unknowns",
                        data={
                            "menu": explained_menu.model_dump(mode="json"),
                            "explanation": explanation,
                        },
                    ),
                    Card(
                        type="menu_recommendations",
                        title="Grounded chicken kalguksu match",
                        subtitle="Synthetic demo catalog",
                        data={"menus": [explained_menu.model_dump(mode="json")]},
                    ),
                ],
                False,
                ["Choose this menu", "Show dietary evidence", "Try another mild soup"],
            )

        if any(phrase in lowered for phrase in ("red rice cake", "tteokbokki", "street")):
            classic = self.repository.get_menu("menu_002_01", profile)
            mild = self.repository.get_menu("menu_001_01", profile)
            evidence = self.repository.get_evidence("menu_002_01")
            assert classic and mild
            text = (
                "That sounds like tteokbokki: chewy rice cakes in a sweet-spicy gochujang sauce. "
                "The classic demo version is a strong 4/5 for heat. Your shellfish allergy also "
                "triggers a risk signal from synthetic review evidence, so I would avoid that one "
                "by default. I found a milder rose version; its sauce is marked seafood-free, but "
                "kitchen cross-contamination is still not verified."
            )
            cards = [
                Card(
                    type="dietary_evidence",
                    title="Why I would avoid the classic version",
                    subtitle="Risk signal · synthetic demo evidence",
                    data={
                        "menu": classic.model_dump(mode="json"),
                        "evidence": [item.model_dump(mode="json") for item in evidence],
                    },
                ),
                Card(
                    type="menu_recommendations",
                    title="A gentler alternative",
                    subtitle="Demo menu · not a safety guarantee",
                    data={"menus": [mild.model_dump(mode="json")]},
                ),
            ]
            self.repository.set_session_selection(
                session.session_id,
                ChatState.SAFETY_WARNING.value,
                mild.menu_id,
                mild.merchant_id,
            )
            return self._make_turn(
                text,
                ChatState.SAFETY_WARNING,
                cards,
                False,
                ["Compare mild rose options", "Show the evidence", "Find a different mild dish"],
            )

        if any(phrase in lowered for phrase in ("compare", "which place", "rose options")):
            comparisons = self.repository.compare_merchants("Rose tteokbokki", profile)
            text = (
                "Here are the clearest trade-offs. I would start with Seoul Rose Tteokbokki for "
                "the gentler spice level and explicit sauce evidence, while keeping the unknown "
                "cross-contamination warning visible."
            )
            card = Card(
                type="merchant_comparison",
                title="Rose tteokbokki comparison",
                subtitle="Synthetic restaurants · shared comparison axes",
                data={"merchants": [item.model_dump(mode="json") for item in comparisons]},
            )
            self.repository.set_session_selection(
                session.session_id,
                ChatState.MERCHANT_COMPARISON.value,
                "menu_001_01",
                "mer_001",
            )
            return self._make_turn(
                text,
                ChatState.MERCHANT_COMPARISON,
                [card],
                False,
                ["Choose Seoul Rose Tteokbokki", "Explain the first option"],
            )

        if any(phrase in lowered for phrase in ("choose seoul", "first place", "first option")):
            options = self.repository.get_options("menu_001_01")
            self.repository.set_session_selection(
                session.session_id, ChatState.MENU_OPTIONS.value, "menu_001_01", "mer_001"
            )
            return self._make_turn(
                "Good choice. First, pick the spice level. Mild is the recommended demo default "
                "for your 1/5 tolerance.",
                ChatState.MENU_OPTIONS,
                [
                    Card(
                        type="option_question",
                        title="1 of 4 · Spice level",
                        subtitle="One decision at a time",
                        data={"option_groups": [options[0].model_dump(mode="json")]},
                    )
                ],
                False,
                ["Mild", "Medium", "Go back"],
            )

        menus = self.repository.search_menus(
            user_text,
            profile,
            15000 if "15,000" in lowered or "15000" in lowered else None,
            profile.spice_tolerance,
            ["pork"] if "no pork" in lowered else [],
            limit=3,
        )
        return self._make_turn(
            "I translated your request into menu constraints and checked the synthetic catalog. "
            "These are the strongest current matches; unknown dietary details remain labelled.",
            ChatState.MENU_EXPLANATION,
            [
                Card(
                    type="menu_recommendations",
                    title="Grounded menu matches",
                    subtitle="Synthetic demo catalog",
                    data={"menus": [menu.model_dump(mode="json") for menu in menus]},
                )
            ],
            False,
            ["Compare these", "Something else", "Show dietary evidence"],
        )

    @staticmethod
    def _make_turn(
        text: str,
        state: ChatState,
        cards: list[Card],
        fallback_used: bool,
        suggested_replies: list[str] | None = None,
    ) -> AssistantTurn:
        return AssistantTurn(
            message_id=f"msg_{uuid4().hex}",
            text=text,
            state=state,
            cards=cards,
            suggested_replies=suggested_replies or [],
            fallback_used=fallback_used,
            created_at=datetime.now(timezone.utc),
        )
