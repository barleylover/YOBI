from __future__ import annotations

import json
import re
from enum import Enum
from threading import BoundedSemaphore
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import Settings
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider


class RecommendationGenerationStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    NO_MATCH = "NO_MATCH"


class MatchedCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_code: str = Field(min_length=1, max_length=80)
    selected_value_codes: list[str] = Field(min_length=1, max_length=20)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class GeneratedMenuRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1, le=3)
    menu_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    selection_reason: str = Field(min_length=1, max_length=1000)
    description: str = Field(min_length=1, max_length=2000)
    matched_criteria: list[MatchedCriterion] = Field(max_length=20)
    wiki_evidence_ids: list[str] = Field(max_length=20)
    caution_codes: list[str] = Field(max_length=20)


class RecommendationGenerationV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RecommendationGenerationStatus
    criteria_summary: str = Field(min_length=1, max_length=1000)
    recommendations: list[GeneratedMenuRecommendation] = Field(max_length=3)
    unmatched_category_codes: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_status_and_order(self) -> RecommendationGenerationV2:
        if self.status is RecommendationGenerationStatus.NO_MATCH:
            raise ValueError("Server-frozen recommendations cannot be changed to NO_MATCH")
        if not self.recommendations:
            raise ValueError("RECOMMENDED requires at least one recommendation")
        menu_ids = [item.menu_id for item in self.recommendations]
        ranks = [item.rank for item in self.recommendations]
        if len(menu_ids) != len(set(menu_ids)):
            raise ValueError("Recommendation menu IDs must be unique")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("Recommendation ranks must be contiguous and ordered")
        return self


class GeneratedRecommendationComparisonItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    menu_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=200)
    key_difference: str = Field(min_length=1, max_length=1000)
    taste_texture: str = Field(min_length=1, max_length=1000)
    ingredients_form: str = Field(min_length=1, max_length=1000)
    spice_heaviness: str = Field(min_length=1, max_length=1000)
    eating_context: str = Field(min_length=1, max_length=1000)
    best_for: str = Field(min_length=1, max_length=1000)
    unverified_dietary_info: str = Field(max_length=1000)


class GeneratedRecommendationComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2000)
    items: list[GeneratedRecommendationComparisonItem] = Field(min_length=2, max_length=3)


RECOMMENDATION_GENERATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["RECOMMENDED"]},
        "criteria_summary": {"type": "string", "minLength": 1, "maxLength": 1000},
        "recommendations": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer", "minimum": 1, "maximum": 3},
                    "menu_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "title": {"type": "string", "minLength": 1, "maxLength": 200},
                    "selection_reason": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
                    },
                    "description": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                    },
                    "matched_criteria": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {
                            "type": "object",
                            "properties": {
                                "category_code": {"type": "string"},
                                "selected_value_codes": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 20,
                                    "items": {"type": "string"},
                                },
                                "evidence_ids": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 20,
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "category_code",
                                "selected_value_codes",
                                "evidence_ids",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "wiki_evidence_ids": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                    "caution_codes": {
                        "type": "array",
                        "maxItems": 20,
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "rank",
                    "menu_id",
                    "title",
                    "selection_reason",
                    "description",
                    "matched_criteria",
                    "wiki_evidence_ids",
                    "caution_codes",
                ],
                "additionalProperties": False,
            },
        },
        "unmatched_category_codes": {
            "type": "array",
            "maxItems": 20,
            "items": {"type": "string"},
        },
    },
    "required": [
        "status",
        "criteria_summary",
        "recommendations",
        "unmatched_category_codes",
    ],
    "additionalProperties": False,
}

RECOMMENDATION_COMPARISON_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
        "items": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "menu_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "name": {"type": "string", "minLength": 1, "maxLength": 200},
                    "key_difference": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "taste_texture": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "ingredients_form": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "spice_heaviness": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "eating_context": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "best_for": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "unverified_dietary_info": {"type": "string", "maxLength": 1000},
                },
                "required": [
                    "menu_id",
                    "name",
                    "key_difference",
                    "taste_texture",
                    "ingredients_form",
                    "spice_heaviness",
                    "eating_context",
                    "best_for",
                    "unverified_dietary_info",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "items"],
    "additionalProperties": False,
}


def recommendation_generation_text_config() -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": "yobi_structured_recommendation_v2",
            "description": "Grounded explanations for server-frozen menu IDs and order.",
            "schema": RECOMMENDATION_GENERATION_JSON_SCHEMA,
            "strict": True,
        }
    }


def recommendation_comparison_text_config() -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": "yobi_grounded_recommendation_comparison_v1",
            "description": "Grounded comparison of a server-frozen recommendation batch.",
            "schema": RECOMMENDATION_COMPARISON_JSON_SCHEMA,
            "strict": True,
        }
    }


_SUBJECTIVE_CRITERIA_FIELDS = (
    "cuisine_origins",
    "flavors",
    "main_ingredients",
    "food_forms",
    "temperatures",
    "textures",
    "cooking_methods",
)
_INTERNAL_ID_PATTERN = re.compile(
    r"\b(?:menu|merchant|chunk|claim|fact|concept|cert)_[A-Za-z0-9._:-]+\b",
    re.IGNORECASE,
)


class RecommendationGenerationValidator:
    """Validate explanations against the server-frozen IDs and order."""

    def __init__(self, *, result_limit: int) -> None:
        self.result_limit = result_limit

    def validate(
        self,
        result: RecommendationGenerationV2,
        *,
        criteria: dict[str, Any],
        evidence_pool: list[dict[str, Any]],
    ) -> RecommendationGenerationV2:
        if len(result.recommendations) > self.result_limit:
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        if result.status is RecommendationGenerationStatus.NO_MATCH:
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)

        pool_by_menu = {str(item.get("menu_id", "")): item for item in evidence_pool}
        expected_menu_ids = [str(item.get("menu_id", "")) for item in evidence_pool]
        actual_menu_ids = [item.menu_id for item in result.recommendations]
        if actual_menu_ids != expected_menu_ids:
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        active_categories = {
            key: {str(value) for value in criteria.get(key, [])}
            for key in _SUBJECTIVE_CRITERIA_FIELDS
            if criteria.get(key)
        }
        for recommendation in result.recommendations:
            pool_item = pool_by_menu.get(recommendation.menu_id)
            if pool_item is None:
                raise GenAIProviderError(
                    GenAIErrorCode.GROUNDING_REJECTED,
                    retryable=False,
                )
            self._reject_internal_id_leak(recommendation)
            matched_by_category = {
                matched.category_code: matched for matched in recommendation.matched_criteria
            }
            if not active_categories.keys() <= matched_by_category.keys():
                raise GenAIProviderError(
                    GenAIErrorCode.GROUNDING_REJECTED,
                    retryable=False,
                )
            criterion_evidence = pool_item.get("criterion_evidence", {})
            if not isinstance(criterion_evidence, dict):
                criterion_evidence = {}
            allowed_wiki_evidence = self._all_evidence_ids(
                pool_item.get("wiki_passages", [])
            )
            for category_code, selected_codes in active_categories.items():
                matched = matched_by_category[category_code]
                matched_codes = set(matched.selected_value_codes)
                if not matched_codes or not matched_codes <= selected_codes:
                    raise GenAIProviderError(
                        GenAIErrorCode.GROUNDING_REJECTED,
                        retryable=False,
                    )
                allowed_category_ids = self._criterion_evidence_ids(
                    criterion_evidence,
                    category_code,
                    matched_codes,
                )
                if not set(matched.evidence_ids) <= allowed_category_ids:
                    raise GenAIProviderError(
                        GenAIErrorCode.GROUNDING_REJECTED,
                        retryable=False,
                    )
            if not set(recommendation.wiki_evidence_ids) <= allowed_wiki_evidence:
                raise GenAIProviderError(
                    GenAIErrorCode.GROUNDING_REJECTED,
                    retryable=False,
                )
        return result

    @staticmethod
    def _criterion_evidence_ids(
        criterion_evidence: dict[str, Any],
        category_code: str,
        selected_codes: set[str],
    ) -> set[str]:
        category = criterion_evidence.get(category_code, {})
        if not isinstance(category, dict):
            return set()
        allowed: set[str] = set()
        for code in selected_codes:
            value = category.get(code, {})
            allowed.update(RecommendationGenerationValidator._all_evidence_ids(value))
        return allowed

    @staticmethod
    def _all_evidence_ids(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_id") and isinstance(item, str):
                    found.add(item)
                elif key.endswith("_ids") and isinstance(item, list):
                    found.update(str(candidate) for candidate in item if candidate)
                found.update(RecommendationGenerationValidator._all_evidence_ids(item))
        elif isinstance(value, list):
            for item in value:
                found.update(RecommendationGenerationValidator._all_evidence_ids(item))
        return found

    @staticmethod
    def _reject_internal_id_leak(recommendation: GeneratedMenuRecommendation) -> None:
        prose = " ".join(
            [recommendation.title, recommendation.selection_reason, recommendation.description]
        )
        if _INTERNAL_ID_PATTERN.search(prose):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)


class RecommendationGenerator:
    """One-dispatch, no-tool generator for v2 recommendation batches."""

    def __init__(
        self,
        settings: Settings,
        provider: GenAIProvider | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider or choose_genai_provider(settings)
        self._request_slots = BoundedSemaphore(
            settings.structured_recommendation_max_concurrent_requests
        )
        self.validator = RecommendationGenerationValidator(
            result_limit=settings.recommendation_result_limit
        )

    @property
    def configured(self) -> bool:
        return self.provider.configured

    def generate(
        self,
        *,
        criteria: dict[str, Any],
        soft_profile_context: dict[str, Any],
        evidence_pool: list[dict[str, Any]],
        locale: str,
    ) -> RecommendationGenerationV2:
        if not evidence_pool:
            raise ValueError("EVIDENCE_POOL_EMPTY")
        if len(evidence_pool) > self.settings.recommendation_result_limit:
            raise ValueError("SERVER_FROZEN_CANDIDATE_LIMIT_EXCEEDED")
        capabilities = self.provider.capabilities
        if not capabilities.responses_api:
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
        if not self.provider.configured or not self.provider.supports_model(
            self.settings.structured_recommendation_model
        ):
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)

        instructions = self._instructions(locale)
        payload = {
            "criteria": criteria,
            "soft_profile_context": soft_profile_context,
            "evidence_pool": evidence_pool,
            "final_recommendation_count": len(evidence_pool),
            # Native structured output is an explicit provider capability flag. The
            # response contract must still be present when an OCI endpoint accepts
            # JSON text but does not enforce `text.format` server-side.
            "response_contract": RECOMMENDATION_GENERATION_JSON_SCHEMA,
        }
        request: dict[str, Any] = {
            "instructions": instructions,
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            ],
            "max_output_tokens": min(
                self.settings.structured_recommendation_max_output_tokens,
                capabilities.max_output_tokens,
            ),
        }
        if capabilities.structured_output:
            request["text"] = recommendation_generation_text_config()
        self._enforce_input_limit(request)
        try:
            with self._request_slots:
                response = self.provider.create_response(
                    self.settings.structured_recommendation_model,
                    **request,
                )
        except GenAIProviderError:
            raise
        except Exception as exc:
            raise GenAIProviderError(
                GenAIErrorCode.PROVIDER_UNAVAILABLE,
                retryable=False,
                cause=exc,
            ) from exc
        raw = str(getattr(response, "output_text", "")).strip()
        if not raw:
            raise GenAIProviderError(GenAIErrorCode.EMPTY_RESPONSE, retryable=False)
        try:
            parsed = self._parse_json(raw)
            result = RecommendationGenerationV2.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise GenAIProviderError(
                GenAIErrorCode.GROUNDING_REJECTED,
                retryable=False,
                cause=exc,
            ) from exc
        return self.validator.validate(
            result,
            criteria=criteria,
            evidence_pool=evidence_pool,
        )

    def compare(
        self,
        *,
        evidence_items: list[dict[str, Any]],
        locale: str,
    ) -> GeneratedRecommendationComparison:
        if not 2 <= len(evidence_items) <= 3:
            raise ValueError("COMPARISON_REQUIRES_TWO_OR_THREE_MENUS")
        capabilities = self.provider.capabilities
        if (
            not capabilities.responses_api
            or not self.provider.configured
            or not self.provider.supports_model(
                self.settings.structured_recommendation_model
            )
        ):
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
        expected_ids = [str(item.get("menu_id", "")) for item in evidence_items]
        request: dict[str, Any] = {
            "instructions": self._comparison_instructions(locale),
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "frozen_menu_evidence": evidence_items,
                            "response_contract": RECOMMENDATION_COMPARISON_JSON_SCHEMA,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            ],
            "max_output_tokens": min(
                self.settings.structured_recommendation_max_output_tokens,
                capabilities.max_output_tokens,
            ),
        }
        if capabilities.structured_output:
            request["text"] = recommendation_comparison_text_config()
        self._enforce_input_limit(request)
        try:
            with self._request_slots:
                response = self.provider.create_response(
                    self.settings.structured_recommendation_model,
                    **request,
                )
            parsed = self._parse_json(str(getattr(response, "output_text", "")).strip())
            result = GeneratedRecommendationComparison.model_validate(parsed)
        except GenAIProviderError:
            raise
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise GenAIProviderError(
                GenAIErrorCode.GROUNDING_REJECTED,
                retryable=False,
                cause=exc,
            ) from exc
        except Exception as exc:
            raise GenAIProviderError(
                GenAIErrorCode.PROVIDER_UNAVAILABLE,
                retryable=False,
                cause=exc,
            ) from exc
        if [item.menu_id for item in result.items] != expected_ids:
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        prose = " ".join(
            [
                result.summary,
                *(
                    text
                    for item in result.items
                    for text in (
                        item.name,
                        item.key_difference,
                        item.taste_texture,
                        item.ingredients_form,
                        item.spice_heaviness,
                        item.eating_context,
                        item.best_for,
                        item.unverified_dietary_info,
                    )
                ),
            ]
        )
        if _INTERNAL_ID_PATTERN.search(prose):
            raise GenAIProviderError(GenAIErrorCode.GROUNDING_REJECTED, retryable=False)
        return result

    def _enforce_input_limit(self, request: dict[str, Any]) -> None:
        serialized = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        conservative_bound = len(serialized.encode("utf-8"))
        limit = min(
            self.settings.llm_max_input_tokens,
            self.provider.capabilities.max_input_tokens,
        )
        if conservative_bound > limit:
            raise GenAIProviderError(
                GenAIErrorCode.CAPABILITY_LIMIT_EXCEEDED,
                retryable=False,
            )

    @staticmethod
    def _parse_json(raw: str) -> Any:
        stripped = raw.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1]).strip()
        return json.loads(stripped)

    def _instructions(self, locale: str) -> str:
        return f"""
You are YOBI's grounded menu recommendation model.
Return exactly one JSON object matching the provided schema and write every user-facing string in
the requested locale/language: {locale}.
Return the JSON immediately without analysis or preamble. Keep criteria_summary, title,
selection_reason, and description to one concise sentence each.

The server has already applied objective eligibility for delivery area, current availability,
price bands, maximum spice, explicit halal certification scope, and confirmed vegan conflicts.
Never weaken or revisit those decisions. Every final menu_id must be copied from evidence_pool.

The evidence_pool is the server's frozen final recommendation list. Return exactly one explanation
for every supplied menu_id, in exactly the supplied order, with contiguous ranks starting at 1.
You have no authority to add, remove, replace, rerank, or reject a menu. Values inside one category
mean OR and categories mean AND; the server has already enforced this contract.

For every matched category, cite only evidence IDs attached to that menu and selected value. Use
the supplied Wiki prose for the explanation. General Wiki prose describes the food generally; it
does not prove a specific restaurant recipe. Do not invent ingredients, prices, availability,
certifications, restaurants, options, or cultural facts. Do not expose internal IDs in prose.
Allergy and allergen guidance is outside this recommendation product. Do not make allergy-safety,
allergen-absence, or cross-contact claims even if incidental Wiki prose mentions uncertainty.

Always return status RECOMMENDED. NO_MATCH is a server decision made before this call. Do not ask
questions, call tools, request more data, or emit Markdown fences. This request only explains the
server-frozen candidates in one response. Prompt profile: {self.settings.recommendation_prompt_version}.
""".strip()

    @staticmethod
    def _comparison_instructions(locale: str) -> str:
        return f"""
You are YOBI's grounded comparison writer. Return exactly one JSON object matching the supplied
schema and write user-facing prose in {locale}. The menu IDs and their order are server-frozen;
copy every menu_id exactly once and in the supplied order. Compare only facts and general Wiki
passages in frozen_menu_evidence. General Wiki prose describes a food concept, not a restaurant's
specific recipe. Never invent ingredients, popularity, orders, ratings, certification, dietary
safety, availability, or delivery facts. Explicitly identify unverified dietary information. Do
not expose internal IDs in prose, call tools, emit Markdown, add menus, remove menus, or rerank.
""".strip()
