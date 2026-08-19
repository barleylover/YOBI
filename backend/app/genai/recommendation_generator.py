from __future__ import annotations

import json
import re
from enum import Enum
from threading import BoundedSemaphore
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from app.core.config import Settings
from app.genai.contracts import GenAIErrorCode, GenAIProvider, GenAIProviderError
from app.genai.providers import choose_genai_provider


class RecommendationGenerationStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    NO_MATCH = "NO_MATCH"


GROUNDING_DIAGNOSTICS_VERSION = "yobi-grounding-diagnostics-v2"


class RecommendationGroundingRejectionStage(str, Enum):
    RESPONSE_CONTRACT = "RESPONSE_CONTRACT"
    SELECTION_POLICY = "SELECTION_POLICY"
    EVIDENCE_GROUNDING = "EVIDENCE_GROUNDING"
    HARD_CONSTRAINT = "HARD_CONSTRAINT"


class RecommendationGroundingRejectionCode(str, Enum):
    """Safe, non-prompt diagnostic reasons behind GROUNDING_REJECTED."""

    INVALID_JSON = "INVALID_JSON"
    RESPONSE_SCHEMA_INVALID = "RESPONSE_SCHEMA_INVALID"
    MODEL_RETURNED_NO_MATCH = "MODEL_RETURNED_NO_MATCH"
    RECOMMENDATION_COUNT_INVALID = "RECOMMENDATION_COUNT_INVALID"
    DUPLICATE_MENU_ID = "DUPLICATE_MENU_ID"
    RANK_ORDER_INVALID = "RANK_ORDER_INVALID"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    UNMATCHED_CATEGORY_PRESENT = "UNMATCHED_CATEGORY_PRESENT"
    MENU_OUTSIDE_SHORTLIST = "MENU_OUTSIDE_SHORTLIST"
    MERCHANT_DIVERSITY_VIOLATION = "MERCHANT_DIVERSITY_VIOLATION"
    MATCHED_CATEGORY_DUPLICATE = "MATCHED_CATEGORY_DUPLICATE"
    MATCHED_CATEGORY_SET_MISMATCH = "MATCHED_CATEGORY_SET_MISMATCH"
    SELECTED_VALUE_OUTSIDE_REQUEST = "SELECTED_VALUE_OUTSIDE_REQUEST"
    CATEGORY_EVIDENCE_NOT_OWNED = "CATEGORY_EVIDENCE_NOT_OWNED"
    WIKI_EVIDENCE_NOT_AVAILABLE = "WIKI_EVIDENCE_NOT_AVAILABLE"
    WIKI_EVIDENCE_NOT_OWNED = "WIKI_EVIDENCE_NOT_OWNED"
    INTERNAL_ID_LEAK = "INTERNAL_ID_LEAK"
    SHORTLIST_PRICE_INVALID = "SHORTLIST_PRICE_INVALID"
    PRICE_BAND_VIOLATION = "PRICE_BAND_VIOLATION"
    CRITERIA_SPICE_INVALID = "CRITERIA_SPICE_INVALID"
    SHORTLIST_SPICE_INVALID = "SHORTLIST_SPICE_INVALID"
    SPICE_LEVEL_VIOLATION = "SPICE_LEVEL_VIOLATION"
    DIETARY_CRITERIA_INVALID = "DIETARY_CRITERIA_INVALID"
    HALAL_CERTIFICATION_VIOLATION = "HALAL_CERTIFICATION_VIOLATION"
    VEGAN_STATUS_VIOLATION = "VEGAN_STATUS_VIOLATION"


_REJECTION_STAGE_BY_CODE = {
    **{
        code: RecommendationGroundingRejectionStage.RESPONSE_CONTRACT
        for code in (
            RecommendationGroundingRejectionCode.INVALID_JSON,
            RecommendationGroundingRejectionCode.RESPONSE_SCHEMA_INVALID,
            RecommendationGroundingRejectionCode.MODEL_RETURNED_NO_MATCH,
            RecommendationGroundingRejectionCode.RECOMMENDATION_COUNT_INVALID,
            RecommendationGroundingRejectionCode.DUPLICATE_MENU_ID,
            RecommendationGroundingRejectionCode.RANK_ORDER_INVALID,
        )
    },
    **{
        code: RecommendationGroundingRejectionStage.SELECTION_POLICY
        for code in (
            RecommendationGroundingRejectionCode.RESULT_LIMIT_EXCEEDED,
            RecommendationGroundingRejectionCode.UNMATCHED_CATEGORY_PRESENT,
            RecommendationGroundingRejectionCode.MENU_OUTSIDE_SHORTLIST,
            RecommendationGroundingRejectionCode.MERCHANT_DIVERSITY_VIOLATION,
        )
    },
    **{
        code: RecommendationGroundingRejectionStage.EVIDENCE_GROUNDING
        for code in (
            RecommendationGroundingRejectionCode.MATCHED_CATEGORY_DUPLICATE,
            RecommendationGroundingRejectionCode.MATCHED_CATEGORY_SET_MISMATCH,
            RecommendationGroundingRejectionCode.SELECTED_VALUE_OUTSIDE_REQUEST,
            RecommendationGroundingRejectionCode.CATEGORY_EVIDENCE_NOT_OWNED,
            RecommendationGroundingRejectionCode.WIKI_EVIDENCE_NOT_AVAILABLE,
            RecommendationGroundingRejectionCode.WIKI_EVIDENCE_NOT_OWNED,
            RecommendationGroundingRejectionCode.INTERNAL_ID_LEAK,
        )
    },
    **{
        code: RecommendationGroundingRejectionStage.HARD_CONSTRAINT
        for code in (
            RecommendationGroundingRejectionCode.SHORTLIST_PRICE_INVALID,
            RecommendationGroundingRejectionCode.PRICE_BAND_VIOLATION,
            RecommendationGroundingRejectionCode.CRITERIA_SPICE_INVALID,
            RecommendationGroundingRejectionCode.SHORTLIST_SPICE_INVALID,
            RecommendationGroundingRejectionCode.SPICE_LEVEL_VIOLATION,
            RecommendationGroundingRejectionCode.DIETARY_CRITERIA_INVALID,
            RecommendationGroundingRejectionCode.HALAL_CERTIFICATION_VIOLATION,
            RecommendationGroundingRejectionCode.VEGAN_STATUS_VIOLATION,
        )
    },
}


def _grounding_rejected(
    reason: RecommendationGroundingRejectionCode,
    *,
    cause: BaseException | None = None,
    safe_metadata: dict[str, int] | None = None,
    safe_reason_detail: str | None = None,
) -> GenAIProviderError:
    return GenAIProviderError(
        GenAIErrorCode.GROUNDING_REJECTED,
        retryable=False,
        cause=cause,
        safe_metadata=safe_metadata,
        safe_reason_code=reason.value,
        safe_reason_stage=_REJECTION_STAGE_BY_CODE[reason].value,
        safe_reason_detail=safe_reason_detail,
    )


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
    caution_codes: list[str] = Field(max_length=20)


class RecommendationGenerationV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    _provider_metrics: dict[str, int] = PrivateAttr(default_factory=dict)

    status: RecommendationGenerationStatus
    criteria_summary: str = Field(min_length=1, max_length=1000)
    recommendations: list[GeneratedMenuRecommendation] = Field(min_length=3, max_length=3)
    unmatched_category_codes: list[str] = Field(max_length=0)

    @property
    def provider_metrics(self) -> dict[str, int]:
        return dict(self._provider_metrics)

    @model_validator(mode="after")
    def validate_status_and_order(self) -> RecommendationGenerationV2:
        if self.status is RecommendationGenerationStatus.NO_MATCH:
            raise ValueError("Server-frozen recommendations cannot be changed to NO_MATCH")
        if len(self.recommendations) != 3:
            raise ValueError("RECOMMENDED requires exactly three recommendations")
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
            "minItems": 3,
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
                    "caution_codes",
                ],
                "additionalProperties": False,
            },
        },
        "unmatched_category_codes": {
            "type": "array",
            "maxItems": 0,
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
            "description": "Grounded selection of three menus from a server-validated shortlist.",
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
    """Validate a bounded three-menu selection against the server shortlist."""

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
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.RESULT_LIMIT_EXCEEDED
            )
        if result.status is RecommendationGenerationStatus.NO_MATCH:
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.MODEL_RETURNED_NO_MATCH
            )
        if result.unmatched_category_codes:
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.UNMATCHED_CATEGORY_PRESENT
            )

        pool_by_menu = {str(item.get("menu_id", "")): item for item in evidence_pool}
        actual_menu_ids = [item.menu_id for item in result.recommendations]
        if len(actual_menu_ids) != 3:
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.RECOMMENDATION_COUNT_INVALID
            )
        if not set(actual_menu_ids) <= set(pool_by_menu):
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.MENU_OUTSIDE_SHORTLIST
            )
        available_merchants = {
            str(item.get("merchant_id", "")) for item in evidence_pool if item.get("merchant_id")
        }
        selected_merchants = {
            str(pool_by_menu[menu_id].get("merchant_id", "")) for menu_id in actual_menu_ids
        }
        if len(available_merchants) >= 3 and len(selected_merchants) != 3:
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.MERCHANT_DIVERSITY_VIOLATION
            )
        active_categories = {
            key: {str(value) for value in criteria.get(key, [])}
            for key in _SUBJECTIVE_CRITERIA_FIELDS
            if criteria.get(key)
        }
        for recommendation in result.recommendations:
            pool_item = pool_by_menu.get(recommendation.menu_id)
            if pool_item is None:
                raise _grounding_rejected(
                    RecommendationGroundingRejectionCode.MENU_OUTSIDE_SHORTLIST
                )
            self._validate_hard_constraints(pool_item, criteria)
            self._reject_internal_id_leak(recommendation)
            matched_by_category = {
                matched.category_code: matched for matched in recommendation.matched_criteria
            }
            if len(matched_by_category) != len(recommendation.matched_criteria):
                raise _grounding_rejected(
                    RecommendationGroundingRejectionCode.MATCHED_CATEGORY_DUPLICATE
                )
            if matched_by_category.keys() != active_categories.keys():
                raise _grounding_rejected(
                    RecommendationGroundingRejectionCode.MATCHED_CATEGORY_SET_MISMATCH
                )
            criterion_evidence = pool_item.get("criterion_evidence", {})
            if not isinstance(criterion_evidence, dict):
                criterion_evidence = {}
            allowed_wiki_evidence = self._all_evidence_ids(
                pool_item.get("wiki_passages", [])
            )
            if not allowed_wiki_evidence:
                raise _grounding_rejected(
                    RecommendationGroundingRejectionCode.WIKI_EVIDENCE_NOT_AVAILABLE
                )
            for category_code, selected_codes in active_categories.items():
                matched = matched_by_category[category_code]
                matched_codes = set(matched.selected_value_codes)
                if not matched_codes or not matched_codes <= selected_codes:
                    raise _grounding_rejected(
                        RecommendationGroundingRejectionCode.SELECTED_VALUE_OUTSIDE_REQUEST
                    )
                allowed_category_ids = self._criterion_evidence_ids(
                    criterion_evidence,
                    category_code,
                    matched_codes,
                )
                if not set(matched.evidence_ids) <= allowed_category_ids:
                    raise _grounding_rejected(
                        RecommendationGroundingRejectionCode.CATEGORY_EVIDENCE_NOT_OWNED
                    )
        return result

    @staticmethod
    def _validate_hard_constraints(
        pool_item: dict[str, Any],
        criteria: dict[str, Any],
    ) -> None:
        """Recheck objective constraints on every model-selected shortlist item."""

        raw_price = pool_item.get("base_price")
        try:
            price = int(raw_price) if raw_price is not None else 0
        except (TypeError, ValueError):
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.SHORTLIST_PRICE_INVALID
            ) from None
        price_bands = {str(value) for value in criteria.get("price_bands", [])}
        price_matches = {
            "UNDER_10000": price < 10_000,
            "FROM_10000_TO_19999": 10_000 <= price < 20_000,
            "FROM_20000_TO_29999": 20_000 <= price < 30_000,
            "OVER_30000": price >= 30_000,
        }
        if price <= 0:
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.SHORTLIST_PRICE_INVALID
            )
        if price_bands and not any(
            price_matches.get(band, False) for band in price_bands
        ):
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.PRICE_BAND_VIOLATION
            )

        try:
            max_spice_level = int(criteria.get("max_spice_level", 5))
        except (TypeError, ValueError):
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.CRITERIA_SPICE_INVALID
            ) from None
        raw_spice_level = pool_item.get("spice_level")
        if max_spice_level < 5:
            try:
                spice_level = int(raw_spice_level) if raw_spice_level is not None else 6
            except (TypeError, ValueError):
                raise _grounding_rejected(
                    RecommendationGroundingRejectionCode.SHORTLIST_SPICE_INVALID
                ) from None
            if spice_level > max_spice_level:
                raise _grounding_rejected(
                    RecommendationGroundingRejectionCode.SPICE_LEVEL_VIOLATION
                )

        dietary = criteria.get("dietary_filters", {})
        if not isinstance(dietary, dict):
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.DIETARY_CRITERIA_INVALID
            )
        if dietary.get("halal_certified_only") is True and pool_item.get(
            "halal_certified"
        ) is not True:
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.HALAL_CERTIFICATION_VIOLATION
            )
        if dietary.get("vegan") is True and str(
            pool_item.get("vegan_status") or "UNKNOWN"
        ) not in {"LIKELY_FIT", "POSSIBLE_WITH_CHECKS"}:
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.VEGAN_STATUS_VIOLATION
            )

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
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.INTERNAL_ID_LEAK
            )


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
        before_provider_call: Callable[[], None] | None = None,
    ) -> RecommendationGenerationV2:
        if not evidence_pool:
            raise ValueError("EVIDENCE_POOL_EMPTY")
        if not 3 <= len(evidence_pool) <= self.settings.recommendation_llm_shortlist_limit:
            raise ValueError("SERVER_SHORTLIST_SIZE_INVALID")
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
            "final_recommendation_count": 3,
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
        request_metrics = self._request_metrics(request, shortlist_count=len(evidence_pool))
        self._enforce_input_limit(request, request_metrics=request_metrics)
        try:
            with self._request_slots:
                if before_provider_call is not None:
                    before_provider_call()
                response = self.provider.create_response(
                    self.settings.structured_recommendation_model,
                    **request,
                )
        except GenAIProviderError as exc:
            exc.safe_metadata = {**request_metrics, **exc.safe_metadata}
            raise
        except Exception as exc:
            raise GenAIProviderError(
                GenAIErrorCode.PROVIDER_UNAVAILABLE,
                retryable=False,
                cause=exc,
                safe_metadata=request_metrics,
            ) from exc
        provider_metrics = {
            **request_metrics,
            **self._response_usage_metrics(response),
        }
        raw = str(getattr(response, "output_text", "")).strip()
        if not raw:
            raise GenAIProviderError(
                GenAIErrorCode.EMPTY_RESPONSE,
                retryable=False,
                safe_metadata=provider_metrics,
            )
        try:
            parsed = self._parse_json(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise _grounding_rejected(
                RecommendationGroundingRejectionCode.INVALID_JSON,
                cause=exc,
                safe_metadata=provider_metrics,
            ) from exc
        try:
            result = RecommendationGenerationV2.model_validate(parsed)
        except ValidationError as exc:
            reason = self._schema_rejection_reason(parsed)
            raise _grounding_rejected(
                reason,
                cause=exc,
                safe_metadata=provider_metrics,
                safe_reason_detail=self._schema_rejection_detail(exc),
            ) from exc
        try:
            validated = self.validator.validate(
                result,
                criteria=criteria,
                evidence_pool=evidence_pool,
            )
        except GenAIProviderError as exc:
            exc.safe_metadata = {**provider_metrics, **exc.safe_metadata}
            raise
        validated._provider_metrics = provider_metrics
        return validated

    @staticmethod
    def _schema_rejection_reason(
        parsed: Any,
    ) -> RecommendationGroundingRejectionCode:
        if not isinstance(parsed, dict):
            return RecommendationGroundingRejectionCode.RESPONSE_SCHEMA_INVALID
        if parsed.get("status") == RecommendationGenerationStatus.NO_MATCH.value:
            return RecommendationGroundingRejectionCode.MODEL_RETURNED_NO_MATCH
        unmatched = parsed.get("unmatched_category_codes")
        if isinstance(unmatched, list) and unmatched:
            return RecommendationGroundingRejectionCode.UNMATCHED_CATEGORY_PRESENT
        recommendations = parsed.get("recommendations")
        if not isinstance(recommendations, list):
            return RecommendationGroundingRejectionCode.RESPONSE_SCHEMA_INVALID
        if len(recommendations) != 3:
            return RecommendationGroundingRejectionCode.RECOMMENDATION_COUNT_INVALID
        if all(isinstance(item, dict) for item in recommendations):
            menu_ids = [item.get("menu_id") for item in recommendations]
            if all(isinstance(menu_id, str) for menu_id in menu_ids) and len(
                set(menu_ids)
            ) != len(menu_ids):
                return RecommendationGroundingRejectionCode.DUPLICATE_MENU_ID
            ranks = [item.get("rank") for item in recommendations]
            if ranks != [1, 2, 3]:
                return RecommendationGroundingRejectionCode.RANK_ORDER_INVALID
        return RecommendationGroundingRejectionCode.RESPONSE_SCHEMA_INVALID

    @staticmethod
    def _schema_rejection_detail(exc: ValidationError) -> str | None:
        errors = exc.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
        if not errors:
            return None
        first = errors[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "$"
        error_type = str(first.get("type") or "validation_error")
        return f"{location}:{error_type}"[:200]

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

    @staticmethod
    def _request_metrics(
        request: dict[str, Any],
        *,
        shortlist_count: int,
    ) -> dict[str, int]:
        serialized = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        encoded = serialized.encode("utf-8")
        return {
            "request_character_count": len(serialized),
            "request_utf8_bytes": len(encoded),
            "input_token_upper_bound": len(encoded),
            "shortlist_count": shortlist_count,
            "requested_max_output_tokens": int(request.get("max_output_tokens") or 0),
        }

    @staticmethod
    def _response_usage_metrics(response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}

        def value(source: Any, key: str) -> int | None:
            raw = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                return None
            return raw

        metrics: dict[str, int] = {}
        for source_key, target_key in (
            ("input_tokens", "input_tokens"),
            ("output_tokens", "output_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            measured = value(usage, source_key)
            if measured is not None:
                metrics[target_key] = measured
        input_details = (
            usage.get("input_tokens_details")
            if isinstance(usage, dict)
            else getattr(usage, "input_tokens_details", None)
        )
        output_details = (
            usage.get("output_tokens_details")
            if isinstance(usage, dict)
            else getattr(usage, "output_tokens_details", None)
        )
        cached = value(input_details, "cached_tokens")
        reasoning = value(output_details, "reasoning_tokens")
        if cached is not None:
            metrics["cached_input_tokens"] = cached
        if reasoning is not None:
            metrics["reasoning_tokens"] = reasoning
        return metrics

    def _enforce_input_limit(
        self,
        request: dict[str, Any],
        *,
        request_metrics: dict[str, int] | None = None,
    ) -> None:
        metrics = request_metrics or self._request_metrics(request, shortlist_count=0)
        conservative_bound = metrics["input_token_upper_bound"]
        limit = min(
            self.settings.llm_max_input_tokens,
            self.provider.capabilities.max_input_tokens,
        )
        if conservative_bound > limit:
            raise GenAIProviderError(
                GenAIErrorCode.CAPABILITY_LIMIT_EXCEEDED,
                retryable=False,
                safe_metadata=metrics,
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

The evidence_pool is a server-validated shortlist, not the final order. Select and order exactly
three unique menu_id values from it, with contiguous ranks 1, 2, and 3. Prefer three different
merchants whenever the shortlist contains at least three merchants. You may not output any menu
outside the shortlist. Values inside one category mean OR and categories mean AND; every selected
menu must cite valid evidence for every selected category.

For every matched category, cite only evidence IDs attached to that menu and selected value. Use
the supplied Wiki prose for the explanation, but do not return wiki_evidence_ids; the server binds
the supplied Wiki evidence to each selected menu. General Wiki prose describes the food generally;
it does not prove a specific restaurant recipe. Do not invent ingredients, prices, availability,
certifications, restaurants, options, or cultural facts. Do not expose internal IDs in prose.
Allergy and allergen guidance is outside this recommendation product. Do not make allergy-safety,
allergen-absence, or cross-contact claims even if incidental Wiki prose mentions uncertainty.

Always return status RECOMMENDED. NO_MATCH is a server decision made before this call. Do not ask
questions, call tools, request more data, or emit Markdown fences. Set unmatched_category_codes to
exactly []. This request only explains the bounded shortlist in one response. Prompt profile:
{self.settings.recommendation_prompt_version}.
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
