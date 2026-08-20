from __future__ import annotations

import pytest

from evaluation.hybrid_rank_tuning import (
    INITIAL_WEIGHTS,
    HybridRankWeights,
    LabeledRankCandidate,
    evaluate_policy,
    grid_policies,
    policy_artifact,
    tune_weights,
)


def _row(menu_id: str, *, relevance: int, explicit: float, semantic: float):
    return LabeledRankCandidate(
        query_id="query-a",
        menu_id=menu_id,
        merchant_id=f"merchant-{menu_id}",
        concept_id=f"concept-{menu_id}",
        explicit=explicit,
        minimum_category_support=explicit,
        semantic=semantic,
        direct_evidence_ratio=1.0 if relevance >= 2 else 0.0,
        review_prior=0.5,
        relevance=relevance,
        query_expected_positive=True,
        retrieval_latency_ms=10.0,
    )


def test_grid_contains_initial_policy_and_all_constraints_hold() -> None:
    policies = list(grid_policies())

    assert INITIAL_WEIGHTS in policies
    assert policies
    assert all(
        policy.explicit + policy.minimum_category_support >= 0.55
        and policy.semantic <= 0.25
        and policy.review_prior <= 0.05
        and round(sum(policy.payload().values()), 10) == 1.0
        for policy in policies
    )


def test_policy_metrics_and_artifact_are_deterministic() -> None:
    rows = [
        _row("a", relevance=3, explicit=1.0, semantic=0.1),
        _row("b", relevance=2, explicit=0.8, semantic=0.2),
        _row("c", relevance=1, explicit=0.2, semantic=1.0),
        _row("d", relevance=0, explicit=0.1, semantic=0.9),
    ]
    result = evaluate_policy(rows, INITIAL_WEIGHTS)
    artifact = policy_artifact(
        result,
        dataset_manifest_sha256="a" * 64,
        query_count=1,
    )

    assert result.precision_at_3 == pytest.approx(2 / 3)
    assert result.ndcg_at_3 == 1.0
    assert result.recall_at_20 == 1.0
    assert len(artifact["policy_sha256"]) == 64


def test_invalid_weight_policy_is_rejected() -> None:
    invalid = HybridRankWeights(0.2, 0.2, 0.4, 0.15, 0.05)

    try:
        invalid.validate()
    except ValueError as exc:
        assert str(exc) in {
            "HYBRID_EXPLICIT_MINIMUM_WEIGHT_TOO_LOW",
            "HYBRID_SEMANTIC_WEIGHT_TOO_HIGH",
        }
    else:
        raise AssertionError("invalid policy should be rejected")


def test_tuning_keeps_initial_policy_when_quality_and_latency_are_tied() -> None:
    rows = [
        _row("a", relevance=3, explicit=1.0, semantic=1.0),
        _row("b", relevance=2, explicit=1.0, semantic=1.0),
        _row("c", relevance=1, explicit=1.0, semantic=1.0),
    ]

    assert tune_weights(rows).weights == INITIAL_WEIGHTS


def test_negative_queries_use_false_positive_rate_without_diluting_precision() -> None:
    positive = [
        _row("a", relevance=3, explicit=1.0, semantic=0.2),
        _row("b", relevance=2, explicit=0.9, semantic=0.2),
        _row("c", relevance=2, explicit=0.8, semantic=0.2),
    ]
    negative = [
        LabeledRankCandidate(
            query_id="query-negative",
            menu_id="negative-a",
            merchant_id="merchant-negative",
            concept_id="concept-negative",
            explicit=0.8,
            minimum_category_support=0.8,
            semantic=0.2,
            direct_evidence_ratio=1.0,
            review_prior=0.5,
            relevance=0,
            query_expected_positive=False,
        )
    ]

    result = evaluate_policy(
        [*positive, *negative],
        INITIAL_WEIGHTS,
        expected_queries={"query-a": True, "query-negative": False},
    )

    assert result.precision_at_3 == 1.0
    assert result.negative_false_positive_rate == 1.0
