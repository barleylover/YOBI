#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import monotonic
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import ProfileCreate
from app.domain.structured_recommendation import (
    EvidencePoolItem,
    RecommendationCriteriaV2,
    RecommendationMode,
)
from evaluation.hybrid_rank_tuning import (
    LabeledRankCandidate,
    dataset_manifest,
    evaluate_policy,
    policy_artifact,
    tune_weights,
)
from evaluation.recommendation_v2_suite import (
    SUITE_VERSION,
    RecommendationEvalQuery,
    build_query_suite,
)

LABEL_POLICY_VERSION = "source-evidence-silver-v2"
UNION_LIMIT = 20


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path.write_text(serialized, encoding="utf-8")
    return hashlib.sha256(serialized.encode()).hexdigest()


def _prepare_repository(path: Path) -> SQLiteYobiRepository:
    repository = SQLiteYobiRepository(path)
    repository.initialize()
    return repository


def _session_context(
    repository: SQLiteYobiRepository,
    locale: str,
) -> tuple[Any, Any]:
    profile = repository.create_profile(
        ProfileCreate(
            consent_demo_data=True,
            preferred_language=locale,
            dietary_rules=[],
            favorite_foods=[],
        )
    )
    session = repository.create_session(profile.profile_id)
    address = next(
        (
            candidate
            for candidate in repository.resolve_address("YOBI Myeongdong Hotel")
            if candidate.service_area_id
        ),
        None,
    )
    if address is None:
        raise RuntimeError("EVALUATION_SERVICE_AREA_UNAVAILABLE")
    repository.save_address(session.session_id, address, None)
    return profile, repository.get_session(session.session_id)


def _retrieve(
    repository: SQLiteYobiRepository,
    *,
    profile: Any,
    session: Any,
    criteria: RecommendationCriteriaV2,
) -> tuple[list[EvidencePoolItem], float]:
    family = repository.get_active_recommendation_release_family()
    if family is None:
        raise RuntimeError("EVALUATION_ACTIVE_FAMILY_MISSING")
    started = monotonic()
    pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.INITIAL,
        100,
        release_family_id=family.release_family_id,
        eligibility_as_of=datetime.now(timezone.utc),
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    return pool, round((monotonic() - started) * 1000, 6)


def _pool_payload(item: EvidencePoolItem) -> dict[str, Any]:
    components = item.ranking_trace.get("component_scores", {})
    return {
        "menu_id": item.menu.menu_id,
        "merchant_id": item.menu.merchant_id,
        "merchant_name": item.menu.merchant_name,
        "name_ko": item.menu.name_ko,
        "name_en": item.menu.name_en,
        "price": item.menu.price,
        "spice_level": item.menu.spice_level,
        "server_rank": item.server_rank,
        "retrieval_score": item.retrieval_score,
        "explicit_score": item.explicit_score,
        "semantic_score": item.semantic_score,
        "minimum_category_support": item.min_category_support,
        "direct_evidence_ratio": float(components.get("direct_evidence_ratio", 0.0)),
        "review_prior": float(components.get("review_prior", 0.5)),
        "concept_id": item.knowledge_concept_id or "",
        "criterion_evidence": [
            criterion.model_dump(mode="json") for criterion in item.criterion_evidence
        ],
    }


def _support_evidence_by_menu(
    repository: SQLiteYobiRepository,
    *,
    release_id: str,
    menu_ids: list[str],
    criteria: RecommendationCriteriaV2,
) -> dict[str, dict[str, dict[str, Any]]]:
    if not menu_ids:
        return {}
    with repository._connection() as connection:
        rows = repository._concept_support_rows(
            connection,
            release_id=release_id,
            menu_ids=menu_ids,
            criteria=criteria,
        )
    strongest: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        payload = dict(row)
        menu_id = str(payload["menu_id"])
        category = str(payload["category_code"])
        menu_support = strongest.setdefault(menu_id, {})
        current = menu_support.get(category)
        key = (
            float(payload["support_strength"]),
            str(payload["evidence_scope"]) == "MENU_DIRECT",
            str(payload["option_code"]),
        )
        if current is None or key > (
            float(current["support_strength"]),
            str(current["evidence_scope"]) == "MENU_DIRECT",
            str(current["option_code"]),
        ):
            menu_support[category] = payload
    return strongest


def _silver_label(
    query: RecommendationEvalQuery,
    *,
    criteria: RecommendationCriteriaV2,
    support: dict[str, dict[str, Any]],
    appears_in_new_pool: bool,
) -> tuple[int, str]:
    if query.expected_outcome == "NO_MATCH":
        return 0, "QUERY_EXPECTS_NO_MATCH"
    selected_categories = set(criteria.subjective_groups())
    if not selected_categories:
        return (3, "OBJECTIVE_FILTER_MATCH") if appears_in_new_pool else (0, "NOT_ELIGIBLE")
    if not selected_categories <= set(support):
        return 0, "SELECTED_CATEGORY_EVIDENCE_MISSING"
    scopes = {str(support[category]["evidence_scope"]) for category in selected_categories}
    strengths = [float(support[category]["support_strength"]) for category in selected_categories]
    if scopes == {"MENU_DIRECT"} and min(strengths) >= 0.8:
        return 3, "ALL_CATEGORIES_DIRECT_SOURCE_EVIDENCE"
    if "MENU_DIRECT" in scopes:
        return 2, "MIXED_DIRECT_AND_GENERAL_EVIDENCE"
    # Reviewed concept evidence is an explicitly allowed, discounted final
    # grounding channel in the release contract. It is relevant (2), while
    # strong all-direct menu evidence remains the ideal label (3).
    return 2, "GENERAL_CONCEPT_EVIDENCE_ONLY_DISCOUNTED"


def _hard_violation_count(
    repository: SQLiteYobiRepository,
    criteria: RecommendationCriteriaV2,
    menu_ids: Iterable[str],
) -> int:
    ids = list(menu_ids)
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with repository._connection() as connection:
        rows = connection.execute(
            f"""
            SELECT menu.menu_id,menu.price,menu.spice_level,menu.spice_status,
                   menu.availability,COALESCE(source.soldout,0) soldout,
                   COALESCE(source.liquor,0) liquor,COALESCE(source.is_adult,0) is_adult,
                   COALESCE(source.verified_adult,0) verified_adult
            FROM menu
            LEFT JOIN menu_source_detail source ON source.menu_id=menu.menu_id
            WHERE menu.menu_id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        vegan_ids = {
            str(row["menu_id"])
            for row in connection.execute(
                f"""
                SELECT DISTINCT relation.menu_id
                FROM menu_dietary_attribute relation
                JOIN dietary_attribute attribute
                  ON attribute.attribute_id=relation.attribute_id
                WHERE relation.menu_id IN ({placeholders})
                  AND upper(relation.status)='VERIFIED'
                  AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                """,
                ids,
            ).fetchall()
        }
    halal_ids = (
        repository.list_valid_halal_certified_menu_ids()
        if criteria.dietary_filters.halal_certified_only
        else set()
    )
    by_id = {str(row["menu_id"]): row for row in rows}
    violations = 0
    for menu_id in ids:
        row = by_id.get(menu_id)
        if row is None:
            violations += 1
            continue
        price = int(row["price"])
        price_ok = not criteria.price_bands or any(
            {
                "UNDER_10000": price < 10_000,
                "FROM_10000_TO_19999": 10_000 <= price <= 19_999,
                "FROM_20000_TO_29999": 20_000 <= price <= 29_999,
                "OVER_30000": price >= 30_000,
            }[band]
            for band in criteria.price_bands
        )
        spice_ok = criteria.max_spice_level == 5 or (
            str(row["spice_status"]) in {"REVIEWED", "VERIFIED"}
            and row["spice_level"] is not None
            and int(row["spice_level"]) <= criteria.max_spice_level
        )
        violations += int(
            not price_ok
            or not spice_ok
            or (
                criteria.dietary_filters.halal_certified_only
                and menu_id not in halal_ids
            )
            or (criteria.dietary_filters.vegan and menu_id not in vegan_ids)
            or str(row["availability"]) != "AVAILABLE"
            or any(int(row[field] or 0) for field in ("soldout", "liquor", "is_adult", "verified_adult"))
        )
    return violations


def _dcg(values: list[int]) -> float:
    return sum((2**value - 1) / math.log2(index + 2) for index, value in enumerate(values))


def _metrics(
    queries: list[dict[str, Any]],
    labels: dict[tuple[str, str], int],
    path: str,
    split: str,
) -> dict[str, Any]:
    selected = [row for row in queries if row["split"] == split]
    precision: list[float] = []
    ndcg: list[float] = []
    recall: list[float] = []
    positive_coverage: list[bool] = []
    negative_false_positive: list[bool] = []
    hard_violations = 0
    latencies: list[float] = []
    for row in selected:
        ids = [item["menu_id"] for item in row[path]][:20]
        if row["expected_outcome"] == "POSITIVE":
            top3_relevance = [
                labels.get((row["query_id"], menu_id), 0) for menu_id in ids[:3]
            ]
            top3_relevance.extend([0] * (3 - len(top3_relevance)))
            judged = [
                label
                for (query_id, _menu_id), label in labels.items()
                if query_id == row["query_id"]
            ]
            ideal = sorted(judged, reverse=True)[:3]
            ideal.extend([0] * (3 - len(ideal)))
            ideal_dcg = _dcg(ideal)
            precision.append(sum(value >= 2 for value in top3_relevance) / 3)
            ndcg.append(_dcg(top3_relevance) / ideal_dcg if ideal_dcg else 0.0)
            relevant_total = sum(value >= 2 for value in judged)
            recall.append(
                sum(
                    labels.get((row["query_id"], menu_id), 0) >= 2
                    for menu_id in ids
                )
                / relevant_total
                if relevant_total
                else 0.0
            )
            positive_coverage.append(len(ids) >= 3)
        else:
            negative_false_positive.append(bool(ids))
        hard_violations += int(row[f"{path}_hard_violation_count"])
        latencies.append(float(row[f"{path}_latency_ms"]))
    return {
        "query_count": len(selected),
        "precision_at_3": round(mean(precision), 6),
        "ndcg_at_3": round(mean(ndcg), 6),
        "recall_at_20": round(mean(recall), 6),
        "positive_three_result_coverage": round(mean(positive_coverage), 6),
        "negative_false_positive_rate": round(mean(negative_false_positive), 6),
        "hard_constraint_violation_count": hard_violations,
        "median_latency_ms": sorted(latencies)[len(latencies) // 2],
        "max_latency_ms": max(latencies),
    }


def _representative_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    quotas = {
        "single_option": 10,
        "cross_category": 10,
        "negative": 5,
        "bilingual_equivalence": 5,
    }
    selected: list[dict[str, Any]] = []
    for cohort, count in quotas.items():
        candidates = [row for row in rows if row["cohort"] == cohort]
        selected.extend(
            sorted(candidates, key=lambda row: hashlib.sha256(row["query_id"].encode()).hexdigest())[
                :count
            ]
        )
    return sorted(selected, key=lambda row: row["query_id"])


def run(baseline_db: Path, candidate_db: Path, output_dir: Path) -> dict[str, Any]:
    baseline = _prepare_repository(baseline_db)
    candidate = _prepare_repository(candidate_db)
    baseline_context = {
        locale: _session_context(baseline, locale) for locale in ("English", "한국어")
    }
    candidate_context = {
        locale: _session_context(candidate, locale) for locale in ("English", "한국어")
    }
    candidate_family = candidate.get_active_recommendation_release_family()
    if candidate_family is None:
        raise RuntimeError("CANDIDATE_FAMILY_MISSING")
    rows: list[dict[str, Any]] = []
    labels: dict[tuple[str, str], int] = {}
    tuning_rows: list[LabeledRankCandidate] = []
    suite = build_query_suite()
    try:
        for query in suite:
            criteria = RecommendationCriteriaV2.model_validate(query.criteria)
            baseline_profile, baseline_session = baseline_context[query.locale]
            candidate_profile, candidate_session = candidate_context[query.locale]
            baseline_pool, baseline_latency = _retrieve(
                baseline,
                profile=baseline_profile,
                session=baseline_session,
                criteria=criteria,
            )
            candidate_pool, candidate_latency = _retrieve(
                candidate,
                profile=candidate_profile,
                session=candidate_session,
                criteria=criteria,
            )
            baseline_items = [_pool_payload(item) for item in baseline_pool[:UNION_LIMIT]]
            candidate_items = [_pool_payload(item) for item in candidate_pool[:UNION_LIMIT]]
            baseline_by_id = {item["menu_id"]: item for item in baseline_items}
            candidate_by_id = {item["menu_id"]: item for item in candidate_items}
            union_ids = list(
                dict.fromkeys([*baseline_by_id, *candidate_by_id])
            )
            support_by_menu = _support_evidence_by_menu(
                candidate,
                release_id=candidate_family.knowledge_release_id,
                menu_ids=union_ids,
                criteria=criteria,
            )
            adjudication: list[dict[str, Any]] = []
            for menu_id in union_ids:
                support = support_by_menu.get(menu_id, {})
                relevance, reason = _silver_label(
                    query,
                    criteria=criteria,
                    support=support,
                    appears_in_new_pool=menu_id in candidate_by_id,
                )
                labels[(query.query_id, menu_id)] = relevance
                item = candidate_by_id.get(menu_id) or baseline_by_id[menu_id]
                evidence = [
                    {
                        "category_code": category,
                        "option_code": str(value["option_code"]),
                        "evidence_scope": str(value["evidence_scope"]),
                        "support_strength": float(value["support_strength"]),
                        "evidence_id": str(value["evidence_id"]),
                        "excerpt": str(value["content"]),
                    }
                    for category, value in sorted(support.items())
                ]
                adjudication.append(
                    {
                        "menu_id": menu_id,
                        "name_ko": item["name_ko"],
                        "name_en": item["name_en"],
                        "merchant_name": item["merchant_name"],
                        "baseline_rank": baseline_by_id.get(menu_id, {}).get("server_rank"),
                        "candidate_rank": candidate_by_id.get(menu_id, {}).get("server_rank"),
                        "relevance": relevance,
                        "label_reason": reason,
                        "label_status": "AUTOMATED_EVIDENCE_PRELABEL",
                        "evidence": evidence,
                    }
                )
            for item in candidate_items:
                tuning_rows.append(
                    LabeledRankCandidate(
                        query_id=query.query_id,
                        menu_id=str(item["menu_id"]),
                        merchant_id=str(item["merchant_id"]),
                        concept_id=str(item["concept_id"]),
                        explicit=float(item["explicit_score"]),
                        minimum_category_support=float(item["minimum_category_support"]),
                        semantic=float(item["semantic_score"]),
                        direct_evidence_ratio=float(item["direct_evidence_ratio"]),
                        review_prior=float(item["review_prior"]),
                        relevance=labels[(query.query_id, str(item["menu_id"]))],
                        query_expected_positive=query.expected_outcome == "POSITIVE",
                        retrieval_latency_ms=candidate_latency,
                    )
                )
            rows.append(
                {
                    **query.payload(),
                    "baseline": baseline_items,
                    "candidate": candidate_items,
                    "baseline_latency_ms": baseline_latency,
                    "candidate_latency_ms": candidate_latency,
                    "baseline_hard_violation_count": _hard_violation_count(
                        baseline, criteria, baseline_by_id
                    ),
                    "candidate_hard_violation_count": _hard_violation_count(
                        candidate, criteria, candidate_by_id
                    ),
                    "adjudication": adjudication,
                }
            )
    finally:
        for profile, _session in baseline_context.values():
            baseline.delete_profile(profile.profile_id)
        for profile, _session in candidate_context.values():
            candidate.delete_profile(profile.profile_id)

    tuning = [row for row in tuning_rows if next(item for item in suite if item.query_id == row.query_id).split == "TUNE"]
    holdout = [row for row in tuning_rows if next(item for item in suite if item.query_id == row.query_id).split == "HOLDOUT"]
    tune_expectations = {
        item.query_id: item.expected_outcome == "POSITIVE"
        for item in suite
        if item.split == "TUNE"
    }
    holdout_expectations = {
        item.query_id: item.expected_outcome == "POSITIVE"
        for item in suite
        if item.split == "HOLDOUT"
    }
    winner = tune_weights(tuning, expected_queries=tune_expectations)
    label_rows = [
        {"query_id": query_id, "menu_id": menu_id, "relevance": relevance}
        for (query_id, menu_id), relevance in sorted(labels.items())
    ]
    label_manifest = dataset_manifest(label_rows)
    policy = policy_artifact(
        winner,
        dataset_manifest_sha256=label_manifest,
        query_count=len(tune_expectations),
    )
    policy["holdout_silver_metrics"] = evaluate_policy(
        holdout,
        winner.weights,
        expected_queries=holdout_expectations,
    ).payload()
    metrics = {
        "schema_version": "1",
        "suite_version": SUITE_VERSION,
        "label_policy_version": LABEL_POLICY_VERSION,
        "label_status": "SILVER_NOT_RELEASE_APPROVAL",
        "label_manifest_sha256": label_manifest,
        "baseline_holdout": _metrics(rows, labels, "baseline", "HOLDOUT"),
        "candidate_holdout": _metrics(rows, labels, "candidate", "HOLDOUT"),
        "candidate_tune": _metrics(rows, labels, "candidate", "TUNE"),
        "bilingual_pair_top20_set_equal_rate": round(
            mean(
                {item["menu_id"] for item in pair[0]["candidate"]}
                == {item["menu_id"] for item in pair[1]["candidate"]}
                for pair_id in {
                    row["pair_id"] for row in rows if row["pair_id"] is not None
                }
                for pair in [[row for row in rows if row["pair_id"] == pair_id]]
            ),
            6,
        ),
    }
    query_sha = _write_json(output_dir / "queries.json", [item.payload() for item in suite])
    adjudication_sha = _write_json(output_dir / "adjudication.json", rows)
    representative_sha = _write_json(
        output_dir / "representative_30.json",
        _representative_cases(rows),
    )
    metrics_sha = _write_json(output_dir / "metrics_silver.json", metrics)
    policy_sha = _write_json(output_dir / "tuning_policy_silver.json", policy)
    manifest = {
        "schema_version": "1",
        "status": "PASS",
        "approval_boundary": "SILVER_LABELS_REQUIRE_HUMAN_REVIEW_BEFORE_OCI_WRITE",
        "artifacts": {
            "queries.json": query_sha,
            "adjudication.json": adjudication_sha,
            "representative_30.json": representative_sha,
            "metrics_silver.json": metrics_sha,
            "tuning_policy_silver.json": policy_sha,
        },
        "candidate_release": {
            "knowledge_release_id": candidate_family.knowledge_release_id,
            "release_family_id": candidate_family.release_family_id,
            "feature_manifest_sha256": candidate_family.feature_manifest_sha256,
            "ranking_policy_version": candidate_family.ranking_policy_version,
        },
    }
    manifest["manifest_sha256"] = _sha256(manifest)
    _write_json(output_dir / "manifest.json", manifest)
    return {**manifest, "metrics": metrics, "tuning_policy": policy}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare legacy and hybrid-v2 recommendation retrieval on 200 frozen queries."
    )
    parser.add_argument("--baseline-db", required=True, type=Path)
    parser.add_argument("--candidate-db", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    for path in (args.baseline_db, args.candidate_db):
        if not path.is_file():
            raise SystemExit(f"EVALUATION_DATABASE_MISSING:{path}")
    result = run(args.baseline_db, args.candidate_db, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
