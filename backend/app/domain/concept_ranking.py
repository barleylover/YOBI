from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

RANKING_POLICY_VERSION = "yobi-hybrid-rank-v2"
RANKING_SCORE_WEIGHTS = {
    "explicit": 0.35,
    "minimum_category_support": 0.20,
    "semantic": 0.25,
    "direct_evidence_ratio": 0.15,
    "review_prior": 0.05,
}
RANKING_POLICY: dict[str, Any] = {
    "version": RANKING_POLICY_VERSION,
    "candidate_generation": {
        "channels": ["MENU_FEATURE", "CONCEPT_SUPPORT", "SEMANTIC"],
        "per_channel_limit": 100,
        "bounded_union_limit": 100,
        "fusion": "RRF_K60",
        "semantic_only_final_allowed": False,
    },
    "eligibility": {
        "same_category": "OR",
        "cross_category": "AND",
        "review_required_is_supported": False,
    },
    "score": {
        "explicit": "mean(max_supported_strength_per_selected_category)",
        "minimum_category_support": "minimum(max_supported_strength_per_selected_category)",
        "direct_evidence_ratio": "direct_supported_categories/selected_categories",
        "review_prior": "bayesian_shrinkage_to_neutral_quality_prior",
        "weights": dict(RANKING_SCORE_WEIGHTS),
        "constraints": {
            "explicit_plus_minimum_at_least": 0.55,
            "semantic_at_most": 0.25,
            "review_prior_at_most": 0.05,
            "grid_step": 0.05,
        },
    },
    "sort": [
        "score_desc",
        "min_category_support_desc",
        "direct_evidence_ratio_desc",
        "reviewed_evidence_count_desc",
        "merchant_id_asc",
        "menu_id_asc",
    ],
    "diversity": {
        "relevance_window": 0.05,
        "evidence_quality_guard": "max_direct_evidence_ratio_within_window",
        "relaxation_order": ["concept", "merchant"],
    },
}
RANKING_POLICY_SHA256 = hashlib.sha256(
    json.dumps(RANKING_POLICY, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


def merge_candidate_channels(
    channels: Sequence[Sequence[str]],
    *,
    limit: int,
    rrf_constant: int = 60,
) -> list[str]:
    """Fuse independently ranked channel IDs into one deterministic bounded union."""

    if limit < 1 or rrf_constant < 1:
        return []
    scores: dict[str, float] = {}
    best_ranks: dict[str, int] = {}
    for channel in channels:
        for rank, menu_id in enumerate(dict.fromkeys(channel), start=1):
            scores[menu_id] = scores.get(menu_id, 0.0) + 1.0 / (rrf_constant + rank)
            best_ranks[menu_id] = min(best_ranks.get(menu_id, rank), rank)
    return sorted(
        scores,
        key=lambda menu_id: (-scores[menu_id], best_ranks[menu_id], menu_id),
    )[:limit]


def candidate_channel_fusion_trace(
    channels: Mapping[str, Sequence[str]],
    *,
    rrf_constant: int = 60,
) -> dict[str, dict[str, Any]]:
    """Expose deterministic per-channel ranks and RRF contributions for audit."""

    if rrf_constant < 1:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for channel_name, channel in channels.items():
        for rank, menu_id in enumerate(dict.fromkeys(channel), start=1):
            payload = result.setdefault(
                menu_id,
                {"channel_ranks": {}, "rrf_contributions": {}},
            )
            contribution = round(1.0 / (rrf_constant + rank), 12)
            payload["channel_ranks"][channel_name] = rank
            payload["rrf_contributions"][channel_name] = contribution
    for payload in result.values():
        payload["rrf_score"] = round(
            sum(payload["rrf_contributions"].values()),
            12,
        )
    return result


@dataclass(frozen=True)
class ConceptRankCandidate:
    menu_id: str
    merchant_id: str
    concept_id: str
    category_supports: dict[str, float]
    reviewed_evidence_count: int
    semantic_score: float = 0.0
    direct_evidence_ratio: float = 0.0
    review_prior: float = 0.5


@dataclass(frozen=True)
class ConceptRankDecision:
    rank: int
    menu_id: str
    merchant_id: str
    concept_id: str
    explicit_score: float
    semantic_score: float
    score: float
    min_category_support: float
    reviewed_evidence_count: int
    direct_evidence_ratio: float
    review_prior: float
    diversity_reason: str

    def trace_payload(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "menu_id": self.menu_id,
            "merchant_id": self.merchant_id,
            "concept_id": self.concept_id,
            "component_scores": {
                "explicit_score": self.explicit_score,
                "semantic_score": self.semantic_score,
                "final_score": self.score,
                "min_category_support": self.min_category_support,
                "reviewed_evidence_count": self.reviewed_evidence_count,
                "direct_evidence_ratio": self.direct_evidence_ratio,
                "review_prior": self.review_prior,
            },
            "tie_break": [self.merchant_id, self.menu_id],
            "diversity_reason": self.diversity_reason,
            "ranking_policy_version": RANKING_POLICY_VERSION,
        }


def rank_concept_candidates(
    candidates: list[ConceptRankCandidate],
    *,
    has_soft_profile: bool,
    limit: int,
) -> list[ConceptRankDecision]:
    """Apply the deterministic hybrid-v2 score, tie-break and diversity policy."""

    if limit < 1:
        return []
    scored: list[
        tuple[ConceptRankCandidate, float, float, float, float, float, float]
    ] = []
    for candidate in candidates:
        if not candidate.category_supports:
            continue
        strengths = [max(0.0, min(1.0, value)) for value in candidate.category_supports.values()]
        explicit_score = sum(strengths) / len(strengths)
        semantic_score = max(0.0, min(1.0, candidate.semantic_score))
        minimum = min(strengths)
        direct_ratio = max(0.0, min(1.0, candidate.direct_evidence_ratio))
        review_prior = max(0.0, min(1.0, candidate.review_prior))
        # `has_soft_profile` remains in the signature for repository compatibility.
        # Hybrid v2 always applies the same auditable release policy.
        _ = has_soft_profile
        score = (
            RANKING_SCORE_WEIGHTS["explicit"] * explicit_score
            + RANKING_SCORE_WEIGHTS["minimum_category_support"] * minimum
            + RANKING_SCORE_WEIGHTS["semantic"] * semantic_score
            + RANKING_SCORE_WEIGHTS["direct_evidence_ratio"] * direct_ratio
            + RANKING_SCORE_WEIGHTS["review_prior"] * review_prior
        )
        scored.append(
            (
                candidate,
                round(explicit_score, 12),
                round(semantic_score, 12),
                round(score, 12),
                round(minimum, 12),
                round(direct_ratio, 12),
                round(review_prior, 12),
            )
        )
    scored.sort(
        key=lambda item: (
            -item[3],
            -item[4],
            -item[5],
            -item[0].reviewed_evidence_count,
            item[0].merchant_id,
            item[0].menu_id,
        )
    )

    selected: list[ConceptRankDecision] = []
    used_merchants: set[str] = set()
    used_concepts: set[str] = set()
    remaining = list(scored)
    while remaining and len(selected) < limit:
        best_score = remaining[0][3]
        close = [item for item in remaining if best_score - item[3] <= 0.05 + 1e-12]
        strongest_direct_ratio = max(item[5] for item in close)
        # Diversity may trade at most 0.05 of relevance, but it must not replace
        # stronger menu-level grounding with weaker concept-only grounding.
        close = [
            item for item in close if item[5] >= strongest_direct_ratio - 1e-12
        ]
        choice: tuple[
            ConceptRankCandidate, float, float, float, float, float, float
        ] | None = None
        reason = "base_order"
        preference_groups = (
            (
                "new_merchant_and_concept",
                lambda item: item[0].merchant_id not in used_merchants
                and item[0].concept_id not in used_concepts,
            ),
            (
                "merchant_relaxed_new_concept",
                lambda item: item[0].concept_id not in used_concepts,
            ),
            (
                "concept_relaxed_new_merchant",
                lambda item: item[0].merchant_id not in used_merchants,
            ),
            ("diversity_exhausted", lambda _item: True),
        )
        for candidate_reason, predicate in preference_groups:
            choice = next((item for item in close if predicate(item)), None)
            if choice is not None:
                reason = candidate_reason
                break
        assert choice is not None
        remaining.remove(choice)
        (
            candidate,
            explicit_score,
            semantic_score,
            score,
            minimum,
            direct_ratio,
            review_prior,
        ) = choice
        selected.append(
            ConceptRankDecision(
                rank=len(selected) + 1,
                menu_id=candidate.menu_id,
                merchant_id=candidate.merchant_id,
                concept_id=candidate.concept_id,
                explicit_score=explicit_score,
                semantic_score=semantic_score,
                score=score,
                min_category_support=minimum,
                reviewed_evidence_count=candidate.reviewed_evidence_count,
                direct_evidence_ratio=direct_ratio,
                review_prior=review_prior,
                diversity_reason=reason,
            )
        )
        used_merchants.add(candidate.merchant_id)
        used_concepts.add(candidate.concept_id)
    return selected


def bayesian_review_prior(
    review_count: int,
    review_average: float | None,
    *,
    prior_mean: float = 0.5,
    prior_strength: float = 20.0,
) -> float:
    """Shrink a 0-5 review average toward neutral when evidence is sparse."""

    count = max(0, int(review_count))
    observed = prior_mean if review_average is None else max(0.0, min(1.0, review_average / 5.0))
    return round(
        (observed * count + prior_mean * prior_strength) / (count + prior_strength),
        12,
    )
