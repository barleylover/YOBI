from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

RANKING_POLICY_VERSION = "yobi-concept-rank-v1"
RANKING_POLICY: dict[str, Any] = {
    "version": RANKING_POLICY_VERSION,
    "eligibility": {
        "same_category": "OR",
        "cross_category": "AND",
        "review_required_is_supported": False,
    },
    "score": {
        "explicit": "mean(max_supported_strength_per_selected_category)",
        "without_soft_profile": {"explicit": 1.0, "semantic": 0.0},
        "with_soft_profile": {"explicit": 0.85, "semantic": 0.15},
    },
    "sort": [
        "score_desc",
        "min_category_support_desc",
        "reviewed_evidence_count_desc",
        "merchant_id_asc",
        "menu_id_asc",
    ],
    "diversity": {
        "relevance_window": 0.10,
        "relaxation_order": ["concept", "merchant"],
    },
}
RANKING_POLICY_SHA256 = hashlib.sha256(
    json.dumps(RANKING_POLICY, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


@dataclass(frozen=True)
class ConceptRankCandidate:
    menu_id: str
    merchant_id: str
    concept_id: str
    category_supports: dict[str, float]
    reviewed_evidence_count: int
    semantic_score: float = 0.0


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
    """Apply the complete deterministic v1 score, tie-break and diversity policy."""

    if limit < 1:
        return []
    scored: list[tuple[ConceptRankCandidate, float, float, float, float]] = []
    for candidate in candidates:
        if not candidate.category_supports:
            continue
        strengths = [max(0.0, min(1.0, value)) for value in candidate.category_supports.values()]
        explicit_score = sum(strengths) / len(strengths)
        semantic_score = max(0.0, min(1.0, candidate.semantic_score))
        score = (
            0.85 * explicit_score + 0.15 * semantic_score
            if has_soft_profile
            else explicit_score
        )
        scored.append(
            (
                candidate,
                round(explicit_score, 12),
                round(semantic_score, 12),
                round(score, 12),
                round(min(strengths), 12),
            )
        )
    scored.sort(
        key=lambda item: (
            -item[3],
            -item[4],
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
        close = [item for item in remaining if best_score - item[3] <= 0.10 + 1e-12]
        choice: tuple[ConceptRankCandidate, float, float, float, float] | None = None
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
        candidate, explicit_score, semantic_score, score, minimum = choice
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
                diversity_reason=reason,
            )
        )
        used_merchants.add(candidate.merchant_id)
        used_concepts.add(candidate.concept_id)
    return selected
