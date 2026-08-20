from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from statistics import mean
from typing import Any

GRID_STEP = 0.05
WEIGHT_FIELDS = (
    "explicit",
    "minimum_category_support",
    "semantic",
    "direct_evidence_ratio",
    "review_prior",
)


@dataclass(frozen=True)
class HybridRankWeights:
    explicit: float
    minimum_category_support: float
    semantic: float
    direct_evidence_ratio: float
    review_prior: float

    def payload(self) -> dict[str, float]:
        return {field: getattr(self, field) for field in WEIGHT_FIELDS}

    def validate(self) -> None:
        values = self.payload()
        if not math.isclose(sum(values.values()), 1.0, abs_tol=1e-12):
            raise ValueError("HYBRID_WEIGHT_SUM_INVALID")
        if self.explicit + self.minimum_category_support < 0.55 - 1e-12:
            raise ValueError("HYBRID_EXPLICIT_MINIMUM_WEIGHT_TOO_LOW")
        if self.semantic > 0.25 + 1e-12:
            raise ValueError("HYBRID_SEMANTIC_WEIGHT_TOO_HIGH")
        if self.review_prior > 0.05 + 1e-12:
            raise ValueError("HYBRID_REVIEW_WEIGHT_TOO_HIGH")
        if any(
            value < 0
            or not math.isclose(
                round(value / GRID_STEP) * GRID_STEP,
                value,
                abs_tol=1e-12,
            )
            for value in values.values()
        ):
            raise ValueError("HYBRID_WEIGHT_GRID_INVALID")


INITIAL_WEIGHTS = HybridRankWeights(0.35, 0.20, 0.25, 0.15, 0.05)


@dataclass(frozen=True)
class LabeledRankCandidate:
    query_id: str
    menu_id: str
    merchant_id: str
    concept_id: str
    explicit: float
    minimum_category_support: float
    semantic: float
    direct_evidence_ratio: float
    review_prior: float
    relevance: int
    query_expected_positive: bool
    retrieval_latency_ms: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.relevance <= 3:
            raise ValueError("RELEVANCE_OUT_OF_RANGE")


@dataclass(frozen=True)
class TuningResult:
    weights: HybridRankWeights
    ndcg_at_3: float
    precision_at_3: float
    recall_at_20: float
    positive_three_result_coverage: float
    negative_false_positive_rate: float
    mean_retrieval_latency_ms: float

    def payload(self) -> dict[str, Any]:
        return {
            "weights": self.weights.payload(),
            "ndcg_at_3": self.ndcg_at_3,
            "precision_at_3": self.precision_at_3,
            "recall_at_20": self.recall_at_20,
            "positive_three_result_coverage": self.positive_three_result_coverage,
            "negative_false_positive_rate": self.negative_false_positive_rate,
            "mean_retrieval_latency_ms": self.mean_retrieval_latency_ms,
        }


def grid_policies() -> Iterable[HybridRankWeights]:
    units = round(1 / GRID_STEP)
    for values in product(range(units + 1), repeat=len(WEIGHT_FIELDS)):
        if sum(values) != units:
            continue
        policy = HybridRankWeights(*(round(value * GRID_STEP, 2) for value in values))
        try:
            policy.validate()
        except ValueError:
            continue
        yield policy


def candidate_score(candidate: LabeledRankCandidate, weights: HybridRankWeights) -> float:
    return round(
        weights.explicit * candidate.explicit
        + weights.minimum_category_support * candidate.minimum_category_support
        + weights.semantic * candidate.semantic
        + weights.direct_evidence_ratio * candidate.direct_evidence_ratio
        + weights.review_prior * candidate.review_prior,
        12,
    )


def _rank(
    candidates: Sequence[LabeledRankCandidate],
    weights: HybridRankWeights,
) -> list[LabeledRankCandidate]:
    remaining = sorted(
        candidates,
        key=lambda item: (
            -candidate_score(item, weights),
            -item.minimum_category_support,
            -item.direct_evidence_ratio,
            item.merchant_id,
            item.menu_id,
        ),
    )
    selected: list[LabeledRankCandidate] = []
    used_merchants: set[str] = set()
    used_concepts: set[str] = set()
    while remaining:
        best_score = candidate_score(remaining[0], weights)
        close = [
            item
            for item in remaining
            if best_score - candidate_score(item, weights) <= 0.05 + 1e-12
        ]
        strongest_direct_ratio = max(item.direct_evidence_ratio for item in close)
        close = [
            item
            for item in close
            if item.direct_evidence_ratio >= strongest_direct_ratio - 1e-12
        ]
        choice = next(
            (
                item
                for item in close
                if item.merchant_id not in used_merchants
                and item.concept_id not in used_concepts
            ),
            None,
        )
        if choice is None:
            choice = next(
                (item for item in close if item.concept_id not in used_concepts),
                None,
            )
        if choice is None:
            choice = next(
                (item for item in close if item.merchant_id not in used_merchants),
                close[0],
            )
        remaining.remove(choice)
        selected.append(choice)
        used_merchants.add(choice.merchant_id)
        used_concepts.add(choice.concept_id)
    return selected


def _dcg(relevances: Sequence[int]) -> float:
    return sum((2**relevance - 1) / math.log2(index + 2) for index, relevance in enumerate(relevances))


def evaluate_policy(
    rows: Sequence[LabeledRankCandidate],
    weights: HybridRankWeights,
    *,
    expected_queries: Mapping[str, bool] | None = None,
) -> TuningResult:
    weights.validate()
    by_query: dict[str, list[LabeledRankCandidate]] = {}
    for row in rows:
        by_query.setdefault(row.query_id, []).append(row)
    if expected_queries is not None:
        for query_id in expected_queries:
            by_query.setdefault(query_id, [])
    ndcg_values: list[float] = []
    precision_values: list[float] = []
    recall_values: list[float] = []
    positive_coverage: list[bool] = []
    negative_false_positives: list[bool] = []
    latencies: list[float] = []
    for query_id, candidates in by_query.items():
        ranked = _rank(candidates, weights)
        top3 = ranked[:3]
        expected_positive = (
            expected_queries[query_id]
            if expected_queries is not None
            else candidates[0].query_expected_positive
        )
        if expected_positive:
            actual = [item.relevance for item in top3]
            ideal = sorted((item.relevance for item in candidates), reverse=True)[:3]
            ideal_dcg = _dcg(ideal)
            ndcg_values.append(_dcg(actual) / ideal_dcg if ideal_dcg else 0.0)
            precision_values.append(sum(value >= 2 for value in actual) / 3)
            relevant_total = sum(item.relevance >= 2 for item in candidates)
            recall_values.append(
                sum(item.relevance >= 2 for item in ranked[:20]) / relevant_total
                if relevant_total
                else 0.0
            )
            positive_coverage.append(len(top3) == 3)
        else:
            negative_false_positives.append(bool(top3))
        latencies.append(
            max(item.retrieval_latency_ms for item in candidates) if candidates else 0.0
        )
    return TuningResult(
        weights=weights,
        ndcg_at_3=round(mean(ndcg_values), 12) if ndcg_values else 0.0,
        precision_at_3=round(mean(precision_values), 12) if precision_values else 0.0,
        recall_at_20=round(mean(recall_values), 12) if recall_values else 0.0,
        positive_three_result_coverage=(
            round(mean(positive_coverage), 12) if positive_coverage else 1.0
        ),
        negative_false_positive_rate=(
            round(mean(negative_false_positives), 12)
            if negative_false_positives
            else 0.0
        ),
        mean_retrieval_latency_ms=round(mean(latencies), 6) if latencies else 0.0,
    )


def tune_weights(
    rows: Sequence[LabeledRankCandidate],
    *,
    expected_queries: Mapping[str, bool] | None = None,
) -> TuningResult:
    if not rows:
        raise ValueError("TUNING_ROWS_EMPTY")
    results = (
        evaluate_policy(rows, policy, expected_queries=expected_queries)
        for policy in grid_policies()
    )
    return max(
        results,
        key=lambda result: (
            result.ndcg_at_3,
            result.precision_at_3,
            -result.mean_retrieval_latency_ms,
            -sum(
                abs(
                    result.weights.payload()[field]
                    - INITIAL_WEIGHTS.payload()[field]
                )
                for field in WEIGHT_FIELDS
            ),
            tuple(-result.weights.payload()[field] for field in WEIGHT_FIELDS),
        ),
    )


def policy_artifact(
    result: TuningResult,
    *,
    dataset_manifest_sha256: str,
    query_count: int,
) -> dict[str, Any]:
    payload = {
        "schema_version": "1",
        "policy_version": "yobi-hybrid-rank-v2",
        "grid_step": GRID_STEP,
        "constraints": {
            "explicit_plus_minimum_at_least": 0.55,
            "semantic_at_most": 0.25,
            "review_prior_at_most": 0.05,
        },
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "query_count": query_count,
        "winner": result.payload(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {**payload, "policy_sha256": hashlib.sha256(encoded).hexdigest()}


def dataset_manifest(rows: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(list(rows), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
