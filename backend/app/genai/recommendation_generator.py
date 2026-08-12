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

    rank: int = Field(ge=1, le=5)
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
    recommendations: list[GeneratedMenuRecommendation] = Field(max_length=5)
    unmatched_category_codes: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_status_and_order(self) -> RecommendationGenerationV2:
        if self.status is RecommendationGenerationStatus.NO_MATCH:
            if self.recommendations:
                raise ValueError("NO_MATCH must not include recommendations")
            return self
        if not self.recommendations:
            raise ValueError("RECOMMENDED requires at least one recommendation")
        menu_ids = [item.menu_id for item in self.recommendations]
        ranks = [item.rank for item in self.recommendations]
        if len(menu_ids) != len(set(menu_ids)):
            raise ValueError("Recommendation menu IDs must be unique")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("Recommendation ranks must be contiguous and ordered")
        return self


RECOMMENDATION_GENERATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["RECOMMENDED", "NO_MATCH"]},
        "criteria_summary": {"type": "string", "minLength": 1, "maxLength": 1000},
        "recommendations": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer", "minimum": 1, "maximum": 5},
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


def recommendation_generation_text_config() -> dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": "yobi_structured_recommendation_v2",
            "description": "Evidence-pool-bound menu choices and grounded explanations.",
            "schema": RECOMMENDATION_GENERATION_JSON_SCHEMA,
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
    """Validate one model response without using a second model or changing its order."""

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
            return result

        pool_by_menu = {str(item.get("menu_id", "")): item for item in evidence_pool}
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
        self._request_slots = BoundedSemaphore(settings.llm_max_concurrent_requests)
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
        capabilities = self.provider.capabilities
        if not capabilities.responses_api:
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
        if not self.provider.configured or not self.provider.supports_model(
            self.settings.oci_genai_model
        ):
            raise GenAIProviderError(GenAIErrorCode.PROVIDER_UNAVAILABLE, retryable=False)

        instructions = self._instructions(locale)
        payload = {
            "criteria": criteria,
            "soft_profile_context": soft_profile_context,
            "evidence_pool": evidence_pool,
            "final_recommendation_count": self.settings.recommendation_result_limit,
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
                self.settings.llm_max_output_tokens,
                capabilities.max_output_tokens,
            ),
        }
        if capabilities.structured_output:
            request["text"] = recommendation_generation_text_config()
        self._enforce_input_limit(request)
        try:
            with self._request_slots:
                response = self.provider.create_response(
                    self.settings.oci_genai_model,
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

The server has already applied objective eligibility for delivery area, current availability,
price bands, maximum spice, explicit halal certification scope, and confirmed vegan conflicts.
Never weaken or revisit those decisions. Every final menu_id must be copied from evidence_pool.

Select up to {self.settings.recommendation_result_limit} menus and rank them yourself. Retrieval
order and scores are recall signals, not the final order. Choose the menus that best satisfy the
user's explicit criteria as a whole. Values inside one category mean OR; every non-empty subjective
category must be supported for each selected menu. Soft profile context may improve relevance but
must never override explicit criteria.

For every matched category, cite only evidence IDs attached to that menu and selected value. Use
the supplied Wiki prose for the explanation. General Wiki prose describes the food generally; it
does not prove a specific restaurant recipe. Do not invent ingredients, prices, availability,
certifications, restaurants, options, or cultural facts. Do not expose internal IDs in prose.
Allergy and allergen guidance is outside this recommendation product. Do not make allergy-safety,
allergen-absence, or cross-contact claims even if incidental Wiki prose mentions uncertainty.

If no pool menu has evidence for all active subjective categories, return status NO_MATCH with an
empty recommendations array. Do not silently relax criteria. Do not ask questions, call tools,
request more data, or emit Markdown fences. This request must choose candidates and explain them in
one response. Prompt profile: {self.settings.recommendation_prompt_version}.
""".strip()
