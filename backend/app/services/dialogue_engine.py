from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.dialogue import (
    ConstraintStrictness,
    DialogueAct,
    MealNeedState,
    PreferenceDelta,
    ReadinessDecision,
    RecommendationReadiness,
)
from app.domain.dietary import apply_profile_constraints
from app.domain.models import Profile


@dataclass(frozen=True)
class DialogueUpdate:
    delta: PreferenceDelta
    state: MealNeedState
    readiness: ReadinessDecision


class DialogueEngine:
    """Small deterministic policy layer; the LLM is never the state authority."""

    _greetings = {
        "hi",
        "hello",
        "hey",
        "hi yobi",
        "hello yobi",
        "안녕",
        "안녕하세요",
    }
    _explicit_request_markers = (
        "recommend",
        "suggest",
        "what could work",
        "what should i",
        "show me",
        "find me",
        "can i order",
        "order it",
        "pick for me",
        "choose for me",
        "surprise me",
        "추천",
        "골라",
        "뭐 먹",
    )
    _hold_markers = (
        "don't recommend yet",
        "do not recommend yet",
        "no recommendations yet",
        "ask me first",
        "ask me questions first",
        "just ask me",
        "not ready for recommendations",
        "추천하지 마",
        "먼저 물어",
    )

    def update(self, current: MealNeedState, profile: Profile, text: str) -> DialogueUpdate:
        delta = self.extract_delta(text)
        state = self.merge(current, delta, profile)
        readiness = self.readiness(state, delta.explicit_recommendation_request)
        state.last_question_key = readiness.next_question_key
        return DialogueUpdate(delta=delta, state=state, readiness=readiness)

    def extract_delta(self, text: str) -> PreferenceDelta:
        lowered = " ".join(text.lower().strip().split())
        normalized_greeting = lowered.strip("!?., ")
        is_greeting = normalized_greeting in self._greetings
        indirect_hold = bool(
            re.search(
                r"\b(?:do\s+not|don['’]?t)\s+(?:want|need)\s+"
                r"(?:you\s+)?to\s+recommend(?:\s+anything)?(?:\s+yet)?\b|"
                r"\b(?:do\s+not|don['’]?t)\s+recommend\s+(?:anything\s+)?"
                r"(?:yet|right\s+now)\b",
                lowered,
            )
            or re.search(
                r"\b(?:do\s+not|don['’]?t)\s+recommend"
                r"(?:\s+(?:me\s+)?anything)?(?=[.!?,]|$)",
                lowered,
            )
            or re.search(
                r"\b(?:do\s+not|don['’]?t)\s+(?:want|need)\s+"
                r"(?:any\s+)?recommendations?(?:\s+(?:yet|right\s+now))?\b|"
                r"\b(?:do\s+not|don['’]?t)\s+give\s+me\s+"
                r"(?:any\s+)?recommendations?\b",
                lowered,
            )
        )
        held = indirect_hold or any(marker in lowered for marker in self._hold_markers)
        explicit_text = re.sub(
            r"\b(?:do\s+not|don['’]?t)\s+"
            r"(?:(?:want|need)\s+(?:you\s+)?to\s+)?recommend"
            r"(?:\s+anything)?(?:\s+(?:yet|right\s+now))?\b",
            "",
            lowered,
        )
        explicit_text = re.sub(r"추천(?:하지\s*마|하지\s*말|은?\s*말고)", "", explicit_text)
        explicit = bool(re.search(r"\brecommend\b", explicit_text)) or "추천" in explicit_text
        explicit = explicit or any(
            marker in lowered
            for marker in self._explicit_request_markers
            if marker not in {"recommend", "추천"}
        )
        correction = any(
            marker in lowered
            for marker in ("actually", "instead", "changed my mind", "정정", "아니")
        )
        comparison_negated = bool(
            re.search(
                r"\b(?:do\s+not|don['’]?t)\s+"
                r"(?:(?:want|need)\s+(?:you\s+)?to\s+)?compare\b",
                lowered,
            )
            or re.search(r"비교(?:는|은|도)?\s*(?:말고|하지)", lowered)
        )
        explanation_negated = bool(
            re.search(
                r"\b(?:do\s+not|don['’]?t)\s+"
                r"(?:(?:want|need)\s+(?:you\s+)?to\s+)?explain\b",
                lowered,
            )
            or re.search(r"설명(?:은|는|도)?\s*(?:말고|하지)", lowered)
        )
        dietary_information_question = bool(
            re.search(
                r"^(?:is|are|can|does|do)\b[^.!?]{0,80}"
                r"\b(?:vegan|vegetarian|halal)\b",
                lowered,
            )
            or re.search(r"\b(?:vegan|vegetarian|halal)\b[^.!?]{0,40}\?", lowered)
            or re.search(
                r"(?:비건|채식|할랄)[^.!?]{0,30}"
                r"(?:인가(?:요)?|가능|먹을\s*수|되나|되나요|일까|일까요|\?)",
                lowered,
            )
        )
        comparison = not comparison_negated and any(
            marker in lowered for marker in ("compare", "difference", "비교", "차이")
        )
        explanation = not explanation_negated and (
            dietary_information_question
            or any(
                marker in lowered
                for marker in (
                "explain",
                "tell me about",
                "what is",
                "describe",
                "ingredient",
                "allergen",
                "allergy",
                "how is it cooked",
                "how is it made",
                "cooking method",
                "설명",
                "어떤 음식",
                "재료",
                "성분",
                "뭐가 들어",
                "알레르기",
                "알러지",
                "어떻게 조리",
                "조리법",
                "어떻게 만들어",
                )
            )
        )
        selection = any(
            marker in lowered
            for marker in ("choose this", "i'll take", "select this", "이걸로", "선택")
        ) or bool(
            re.search(
                r"\b(?:choose|select|take|pick)\s+(?:the\s+)?(?:first|second|third|1st|2nd|3rd)(?:\s+menu)?\b",
                lowered,
            )
            or re.search(r"(?:첫|두|둘|세|셋)\s*번째\s*메뉴(?:로|를)?\s*(?:선택|골라)", lowered)
        )
        rejection = any(
            marker in lowered
            for marker in ("not that one", "reject", "show another", "다른 메뉴", "이건 싫")
        )
        order_action = any(
            marker in lowered
            for marker in (
                "add to cart",
                "show my cart",
                "show me my cart",
                "show the cart",
                "view cart",
                "view my cart",
                "open my cart",
                "see my cart",
                "check my cart",
                "cart summary",
                "what's in my cart",
                "what is in my cart",
                "checkout",
                "payment",
                "order status",
                "장바구니",
                "결제",
            )
        ) or bool(
            re.search(r"\badd\b(?:\s+\w+){0,4}\s+\b(?:to\s+)?cart\b", lowered)
            or re.search(
                r"\b(?:show|view|open|see|check|display)\s+"
                r"(?:me\s+)?(?:(?:my|the)\s+)?cart\b",
                lowered,
            )
            or re.search(r"\bwhat(?:'s| is)\s+in\s+(?:my|the)\s+cart\b", lowered)
        )

        act = DialogueAct.GREET if is_greeting else DialogueAct.COLLECT_NEEDS
        if order_action:
            act = DialogueAct.ORDER_ACTION
        elif selection:
            act = DialogueAct.SELECT
        elif rejection:
            act = DialogueAct.REJECT
        elif comparison:
            act = DialogueAct.COMPARE
        elif explanation and held:
            act = DialogueAct.REQUEST_EXPLANATION
        elif held:
            act = DialogueAct.HOLD_RECOMMENDATION
        elif explicit:
            # Negated comparison/explanation requests have already been removed,
            # so "don't compare; recommend" follows the requested action without
            # breaking ordinary requests such as "compare the recommendations".
            act = DialogueAct.REQUEST_RECOMMENDATION
        elif explanation:
            act = DialogueAct.REQUEST_EXPLANATION
        elif correction:
            act = DialogueAct.REVISE

        actual_recommendation_request = act == DialogueAct.REQUEST_RECOMMENDATION
        delta = PreferenceDelta(
            dialogue_act=act,
            explicit_recommendation_request=actual_recommendation_request,
            recommendation_hold=(
                True if held else (False if actual_recommendation_request else None)
            ),
        )

        budget_match = re.search(
            r"(?:under|below|less than|max(?:imum)?|budget(?: is| of)?|up to)\s*(?:₩|krw\s*)?([0-9][0-9,]*)",
            lowered,
        ) or re.search(r"([0-9][0-9,]*)\s*(?:won|원)\s*(?:or less|이하|까지)", lowered)
        if budget_match:
            value = int(budget_match.group(1).replace(",", ""))
            if 1_000 <= value <= 1_000_000:
                delta.budget_krw = value

        party_match = re.search(
            r"(?:for|party of)\s+([1-9]|1[0-9]|20)\s*(?:people|persons|of us)?", lowered
        )
        if party_match:
            delta.party_size = int(party_match.group(1))
        elif any(marker in lowered for marker in ("just me", "by myself", "alone", "혼자")):
            delta.party_size = 1
        elif any(marker in lowered for marker in ("two of us", "for two", "둘이", "2명")):
            delta.party_size = 2

        korean_mild_negative = bool(
            re.search(r"순한[^.!?]{0,12}(?:싫|말고|원하지\s*않|아니)", lowered)
        )
        english_mild_negative = any(
            phrase in lowered
            for phrase in (
                "not mild",
                "no mild",
                "don't want mild",
                "do not want mild",
                "mild is not okay",
                "mild is not fine",
            )
        ) or bool(
            re.search(r"\bmild(?:\s+\w+){0,2}\s+is\s+not\s+(?:okay|fine)\b", lowered)
        )
        positive_english_mild = "mild" in lowered and not english_mild_negative
        positive_korean_mild = (
            ("순한" in lowered or bool(re.search(r"순하(?:고|게)(?!\s*않)", lowered)))
            and not korean_mild_negative
        )
        if any(
            marker in lowered
            for marker in (
                "not spicy",
                "no spice",
                "don't want spicy",
                "do not want spicy",
                "can't handle spicy",
                "안 맵",
            )
        ) or positive_english_mild or positive_korean_mild:
            delta.max_spiciness = 1
        elif any(marker in lowered for marker in ("medium spicy", "moderately spicy", "보통 맵")):
            delta.max_spiciness = 2
        elif any(
            marker in lowered
            for marker in ("very spicy", "really spicy", "아주 맵", "매운 거 좋아")
        ):
            delta.max_spiciness = 3

        self._extract_sensory(delta, lowered, correction)
        if delta.restore_spice_tolerance:
            delta.max_spiciness = None
        self._extract_categories(delta, lowered)
        self._extract_constraints(
            delta,
            lowered,
            ignore_dietary_identity=dietary_information_question,
        )

        if "severe allergy" in lowered or "life-threatening" in lowered:
            delta.strictness = ConstraintStrictness.STRICT
        elif any(marker in lowered for marker in ("preference only", "not an allergy", "괜찮으면")):
            delta.strictness = ConstraintStrictness.EXPLORATORY
        return delta

    @staticmethod
    def _extract_sensory(
        delta: PreferenceDelta,
        lowered: str,
        correction: bool,
    ) -> None:
        preference_signal = any(
            marker in lowered
            for marker in (
                "want",
                "prefer",
                "like",
                "recommend",
                "not ",
                "no ",
                "don't",
                "do not",
                "avoid",
                "actually",
                "instead",
                "좋아",
                "원해",
                "싫",
                "말고",
                "추천",
            )
        )
        suggestion_question = bool(re.search(r"\b(?:how|what)\s+about\b", lowered))
        if (
            "?" in lowered
            and not preference_signal
            and not suggestion_question
            and re.search(r"\b(?:is|are|does|do|how|what)\b", lowered)
        ):
            return

        def negative_position(markers: tuple[str, ...]) -> int:
            latest = -1
            for marker in markers:
                if marker.isascii():
                    for phrase in (
                        f"not {marker}",
                        f"no {marker}",
                        f"don't want {marker}",
                        f"do not want {marker}",
                        f"don't like {marker}",
                        f"do not like {marker}",
                        f"dislike {marker}",
                        f"hate {marker}",
                        f"avoid {marker}",
                        f"instead of {marker}",
                        f"{marker} is not okay",
                        f"{marker} is not fine",
                    ):
                        latest = max(latest, lowered.rfind(phrase))
                else:
                    latest = max(
                        latest,
                        *(
                            match.start()
                            for match in re.finditer(
                                rf"{re.escape(marker)}[^.!?]{{0,12}}"
                                r"(?:싫|말고|원하지\s*않|빼)",
                                lowered,
                            )
                        ),
                        -1,
                    )
            return latest

        def positive_correction_position(markers: tuple[str, ...]) -> int:
            latest = -1
            for marker in markers:
                for phrase in (
                    f"actually {marker}",
                    f"{marker} is okay",
                    f"{marker} is fine",
                    f"i like {marker}",
                    f"i want {marker}",
                    f"i prefer {marker}",
                ):
                    latest = max(latest, lowered.rfind(phrase))
                if not marker.isascii():
                    latest = max(
                        latest,
                        *(
                            match.start()
                            for match in re.finditer(
                                rf"{re.escape(marker)}[^.!?]{{0,12}}(?:괜찮|좋아|원해)",
                                lowered,
                            )
                        ),
                        -1,
                    )
            return latest

        def is_negative(markers: tuple[str, ...]) -> bool:
            return negative_position(markers) > positive_correction_position(markers)

        def is_positive_correction(markers: tuple[str, ...]) -> bool:
            return positive_correction_position(markers) > negative_position(markers)

        temperature_markers: dict[str, tuple[str, ...]] = {
            "warm": ("warm", "hot food", "따뜻", "뜨끈"),
            "cold": ("cold", "chilled", "차가운", "시원한"),
        }
        for value, markers in temperature_markers.items():
            if not any(marker in lowered for marker in markers):
                continue
            if is_negative(markers) and not is_positive_correction(markers):
                delta.add_negative_preferences.append(value)
                delta.remove_temperature_preferences.append(value)
            else:
                delta.add_temperature_preferences.append(value)
                delta.remove_negative_preferences.append(value)
        if correction and len(set(delta.add_temperature_preferences)) == 1:
            preferred = delta.add_temperature_preferences[0]
            opposite = "cold" if preferred == "warm" else "warm"
            delta.remove_temperature_preferences.append(opposite)
        texture_markers: dict[str, tuple[str, ...]] = {
            "chewy": ("chewy", "쫄깃"),
            "crispy": ("crispy", "crunchy", "바삭"),
            "soft": ("soft", "silky", "부드러"),
        }
        for value, markers in texture_markers.items():
            if not any(marker in lowered for marker in markers):
                continue
            if is_negative(markers) and not is_positive_correction(markers):
                delta.add_negative_preferences.append(value)
                delta.remove_texture_preferences.append(value)
            else:
                delta.add_texture_preferences.append(value)
                delta.remove_negative_preferences.append(value)
        flavor_markers: dict[str, tuple[str, ...]] = {
            "savory": ("savory", "savoury", "감칠맛", "짭짤"),
            "sweet": ("sweet", "달콤", "단맛"),
            "creamy": ("creamy", "크리미", "고소"),
            "spicy": ("spicy", "매운"),
            "light": ("light", "refreshing", "가벼운", "깔끔"),
            "hearty": ("hearty", "filling", "든든"),
        }
        for value, markers in flavor_markers.items():
            if not any(marker in lowered for marker in markers):
                continue
            negative_at = negative_position(markers)
            if value == "spicy":
                negative_at = max(
                    negative_at,
                    *(lowered.rfind(marker) for marker in ("안 맵", "맵지")),
                )
            negative = negative_at > positive_correction_position(markers)
            if negative:
                delta.add_negative_preferences.append(value)
                delta.remove_flavor_preferences.append(value)
            else:
                delta.add_flavor_preferences.append(value)
                delta.remove_negative_preferences.append(value)
                if value == "spicy" and (
                    is_positive_correction(markers)
                    or any(
                        phrase in lowered
                        for phrase in (
                            "want spicy",
                            "prefer spicy",
                            "like spicy",
                            "매운 거 좋아",
                            "매운 음식 원",
                        )
                    )
                ):
                    delta.restore_spice_tolerance = True

    @staticmethod
    def _extract_categories(delta: PreferenceDelta, lowered: str) -> None:
        category_markers = {
            "soup": ("soup", "stew", "broth", "국물", "찌개", "탕"),
            "noodles": ("noodle", "면", "국수"),
            "rice": ("rice", "밥"),
            "chicken": ("chicken", "치킨", "닭"),
            "tteokbokki": ("tteokbokki", "red rice cake", "떡볶이"),
            "gimbap": ("gimbap", "kimbap", "김밥"),
            "bibimbap": ("bibimbap", "비빔밥"),
        }
        for category, markers in category_markers.items():
            if not any(marker in lowered for marker in markers):
                continue
            negative = any(
                re.search(pattern + r"\s+(?:\w+\s+){0,2}" + re.escape(marker), lowered)
                for marker in markers
                for pattern in (r"\bno", r"\bnot", r"don't want", r"do not want", r"avoid")
            ) or any(f"{marker} 말고" in lowered or f"{marker} 싫" in lowered for marker in markers)
            reversed_negative = any(
                phrase in lowered
                for phrase in (
                    f"{category} is okay",
                    f"{category} is fine",
                    f"{category} again",
                    f"{category} 괜찮",
                )
            )
            if reversed_negative:
                delta.remove_excluded_categories.append(category)
                delta.add_preferred_categories.append(category)
            elif negative:
                delta.add_excluded_categories.append(category)
                delta.remove_preferred_categories.append(category)
            else:
                delta.add_preferred_categories.append(category)

    @staticmethod
    def _extract_constraints(
        delta: PreferenceDelta,
        lowered: str,
        *,
        ignore_dietary_identity: bool = False,
    ) -> None:
        ingredient_markers = {
            "pork": ("pork", "돼지고기", "돼지"),
            "shellfish": ("shellfish", "shrimp", "prawn", "crab", "조개", "새우", "게"),
            "fish": ("fish", "생선", "어류"),
            "beef": ("beef", "소고기"),
            "egg": ("egg", "달걀", "계란"),
            "milk": ("milk", "dairy", "우유", "유제품"),
            "peanut": ("peanut", "peanuts", "땅콩"),
            "tree_nut": ("tree nut", "tree nuts", "nuts", "견과류"),
            "wheat": ("wheat", "gluten", "밀"),
            "soy": ("soy", "soya", "대두", "콩"),
            "sesame": ("sesame", "참깨", "깨"),
        }

        def contains(value: str, marker: str) -> bool:
            if marker.isascii():
                return bool(re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", value))
            return marker in value

        def marker_pattern(marker: str) -> str:
            escaped = re.escape(marker)
            return rf"(?<![a-z]){escaped}(?![a-z])" if marker.isascii() else escaped

        # Keep an allergy statement local to its semantic clause. Ingredient lists stay
        # together, while a new subject/predicate ("and I like beef") starts a new clause.
        # This prevents one allergy trigger from turning every ingredient in the turn into
        # an allergy.
        clauses = [
            clause.strip(" ,")
            for clause in re.split(
                r"[.!?;]+|\b(?:but|however|while|whereas)\b|"
                r"\band\s+(?=(?:i|we|my|our|he|she|they|it|this|that|the)\b)|"
                r",\s+(?=(?:i|we|my|our|he|she|they|it|this|that|the)\b)|"
                r"(?:하지만|그런데)",
                lowered,
            )
            if clause.strip(" ,")
        ]

        for ingredient, markers in ingredient_markers.items():
            allergy_state: str | None = None
            exclusion_state: str | None = None
            for clause in clauses:
                matched_markers = [marker for marker in markers if contains(clause, marker)]
                if not matched_markers:
                    continue

                negative_allergy_context = bool(
                    re.search(
                        r"\b(?:not|no longer|never)\s+allergic\s+to\b|"
                        r"\b(?:do not|don't|does not|doesn't)\s+have\s+"
                        r"(?:an?\s+)?allerg(?:y|ies)\b",
                        clause,
                    )
                )
                positive_allergy_context = (
                    not negative_allergy_context
                    and bool(
                        re.search(r"\ballergic\s+to\b|\ballerg(?:y|ies)\b", clause)
                        or "알레르기" in clause
                    )
                )

                corrected = negative_allergy_context
                allowed = False
                absent = False
                for marker in matched_markers:
                    pattern = marker_pattern(marker)
                    corrected = corrected or bool(
                        re.search(
                            rf"\bno\s+{pattern}\s+allerg(?:y|ies)\b|"
                            rf"\bremove\s+(?:my\s+)?{pattern}\s+allerg(?:y|ies)\b|"
                            rf"{pattern}\s+(?:is|isn't|is not|was|wasn't|was not)\s+"
                            rf"(?:an?\s+)?allerg(?:y|ies)\b|"
                            rf"{pattern}\s+allerg(?:y|ies)\s+(?:is|are)\s+"
                            rf"(?:gone|incorrect|wrong)|"
                            rf"{pattern}\s+알레르기\s+(?:아니|없)",
                            clause,
                        )
                    )
                    allowed = allowed or bool(
                        re.search(
                            rf"{pattern}\s+(?:is|are)\s+(?:okay|fine)|"
                            rf"{pattern}\s+괜찮",
                            clause,
                        )
                    )
                    absent = absent or bool(
                        re.search(
                            rf"\b(?:no|without|avoid)\s+{pattern}\b|"
                            rf"{pattern}\s+(?:빼|못\s*먹)",
                            clause,
                        )
                    )

                if corrected or allowed:
                    allergy_state = "remove"
                    exclusion_state = "remove"
                elif positive_allergy_context:
                    allergy_state = "add"
                    exclusion_state = "add"
                elif absent:
                    exclusion_state = "add"

            if allergy_state == "remove":
                delta.remove_dietary_rules.append(f"{ingredient}_allergy")
            elif allergy_state == "add":
                delta.add_dietary_rules.append(f"{ingredient}_allergy")
            if exclusion_state == "remove":
                delta.remove_excluded_ingredients.append(ingredient)
            elif exclusion_state == "add":
                delta.add_excluded_ingredients.append(ingredient)
        if ignore_dietary_identity:
            return
        if any(
            marker in lowered
            for marker in (
                "not vegan anymore",
                "no longer vegan",
                "vegan is okay",
                "비건 아니",
            )
        ):
            delta.remove_dietary_rules.append("vegan")
        elif "vegan" in lowered or "비건" in lowered:
            delta.add_dietary_rules.append("vegan")
        if "vegetarian" in lowered or "채식" in lowered:
            delta.add_dietary_rules.append("vegetarian")
        if "halal" in lowered or "할랄" in lowered:
            delta.add_dietary_rules.append("halal")

    @staticmethod
    def merge(current: MealNeedState, delta: PreferenceDelta, profile: Profile) -> MealNeedState:
        state = current.model_copy(deep=True)
        state.turn_count += 1
        state = apply_profile_constraints(state, profile.dietary_rules, profile.religion_selection)
        if not state.dietary_rules:
            state.dietary_rules = list(state.profile_dietary_rules)
        if state.max_spiciness is None:
            state.max_spiciness = profile.spice_tolerance
        for scalar in ("occasion", "party_size", "budget_krw", "max_spiciness", "service_area_id"):
            value = getattr(delta, scalar)
            if value is not None:
                setattr(state, scalar, value)
        if (
            delta.max_spiciness is None and delta.restore_spice_tolerance
        ):
            state.max_spiciness = profile.spice_tolerance
        if delta.recommendation_hold is not None:
            state.recommendation_hold = delta.recommendation_hold
        if delta.strictness is not None:
            state.strictness = delta.strictness
        for field, additions, removals in (
            (
                "temperature_preferences",
                delta.add_temperature_preferences,
                delta.remove_temperature_preferences,
            ),
            (
                "texture_preferences",
                delta.add_texture_preferences,
                delta.remove_texture_preferences,
            ),
            ("flavor_preferences", delta.add_flavor_preferences, delta.remove_flavor_preferences),
            (
                "preferred_categories",
                delta.add_preferred_categories,
                delta.remove_preferred_categories,
            ),
            (
                "excluded_categories",
                delta.add_excluded_categories,
                delta.remove_excluded_categories,
            ),
            (
                "excluded_ingredients",
                delta.add_excluded_ingredients,
                delta.remove_excluded_ingredients,
            ),
            ("dietary_rules", delta.add_dietary_rules, delta.remove_dietary_rules),
            ("positive_preferences", delta.add_positive_preferences, []),
            (
                "negative_preferences",
                delta.add_negative_preferences,
                delta.remove_negative_preferences,
            ),
        ):
            values = [value for value in getattr(state, field) if value not in set(removals)]
            for value in additions:
                normalized = value.strip().lower()
                if normalized and normalized not in values:
                    values.append(normalized)
            setattr(state, field, values)
        state.preferred_categories = [
            item
            for item in state.preferred_categories
            if item not in set(state.excluded_categories)
        ]
        return apply_profile_constraints(state, profile.dietary_rules, profile.religion_selection)

    @staticmethod
    def readiness(state: MealNeedState, explicit_request: bool) -> ReadinessDecision:
        dimensions: list[str] = []
        if state.temperature_preferences:
            dimensions.append("temperature")
        if state.texture_preferences:
            dimensions.append("texture")
        if state.flavor_preferences:
            dimensions.append("flavor")
        if state.preferred_categories:
            dimensions.append("dish_direction")
        if state.excluded_categories or state.excluded_ingredients or state.dietary_rules:
            dimensions.append("constraints")
        if state.budget_krw is not None:
            dimensions.append("budget")
        if state.party_size is not None:
            dimensions.append("party_size")
        if state.occasion:
            dimensions.append("occasion")
        positive_signal = bool(
            state.temperature_preferences
            or state.texture_preferences
            or state.flavor_preferences
            or state.preferred_categories
            or state.positive_preferences
        )
        if state.recommendation_hold:
            status = RecommendationReadiness.HELD
            reason = "The user asked YOBI to keep gathering needs before recommending."
        elif explicit_request:
            status = RecommendationReadiness.EXPLICIT_REQUEST
            reason = "The user explicitly requested a recommendation."
        elif len(dimensions) >= 3 and positive_signal:
            status = RecommendationReadiness.READY
            reason = "At least three useful need dimensions include a positive meal direction."
        else:
            status = RecommendationReadiness.NOT_READY
            reason = "More meal context is needed before showing menu candidates."

        next_question: str | None
        if not positive_signal:
            next_question = "meal_direction"
        elif not state.flavor_preferences and not state.texture_preferences:
            next_question = "taste_or_texture"
        elif state.budget_krw is None:
            next_question = "budget"
        elif state.party_size is None:
            next_question = "party_size"
        else:
            next_question = "ready_confirmation"
        if status in {RecommendationReadiness.READY, RecommendationReadiness.EXPLICIT_REQUEST}:
            next_question = None

        missing: list[str] = []
        if not positive_signal:
            missing.append("meal_direction")
        if state.budget_krw is None:
            missing.append("budget")
        if state.party_size is None:
            missing.append("party_size")
        return ReadinessDecision(
            status=status,
            score=min(1.0, len(dimensions) / 4),
            information_dimensions=dimensions,
            missing_fields=missing,
            next_question_key=next_question,
            reason=reason,
        )
