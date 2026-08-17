from __future__ import annotations

import inspect
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.browse_rankings import food_ranking_sql, synthetic_demo_ranking_metrics
from app.db.concept_query import build_concept_candidate_query, build_concept_preview_query
from app.db.oracle_repository import OracleYobiRepository
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.concept_ranking import (
    RANKING_POLICY_SHA256,
    RANKING_POLICY_VERSION,
    ConceptRankCandidate,
    rank_concept_candidates,
)
from app.domain.structured_recommendation import RecommendationCriteriaV2

ROOT = Path(__file__).resolve().parents[2]


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE merchant (
          merchant_id TEXT PRIMARY KEY, name_en TEXT, name_ko TEXT,
          service_area_id TEXT, delivery_fee INTEGER, eta_min INTEGER, eta_max INTEGER
        );
        CREATE TABLE menu (
          menu_id TEXT PRIMARY KEY, merchant_id TEXT, name_en TEXT, name_ko TEXT,
          category TEXT, description TEXT, cultural_description TEXT, price INTEGER,
          spice_level INTEGER, spice_status TEXT, dietary_data_status TEXT,
          serves_min INTEGER, serves_max INTEGER, is_synthetic INTEGER,
          availability TEXT
        );
        CREATE TABLE menu_source_detail (
          menu_id TEXT PRIMARY KEY, liquor INTEGER, is_adult INTEGER,
          verified_adult INTEGER, soldout INTEGER
        );
        CREATE TABLE menu_concept_map (
          menu_id TEXT, release_id TEXT, concept_id TEXT,
          mapping_status TEXT, confidence_band TEXT
        );
        CREATE TABLE concept_preference_support (
          knowledge_release_id TEXT, concept_id TEXT, category_code TEXT,
          option_code TEXT, support_status TEXT, support_strength REAL,
          evidence_chunk_id TEXT
        );
        """
    )
    return connection


def _insert_menu(
    connection: sqlite3.Connection,
    *,
    menu_id: str,
    merchant_id: str,
    concept_id: str,
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO merchant VALUES (?,?,?,?,?,?,?)",
        (merchant_id, merchant_id, merchant_id, "area", 0, 20, 40),
    )
    connection.execute(
        "INSERT INTO menu VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            menu_id,
            merchant_id,
            menu_id,
            menu_id,
            "food",
            "",
            "",
            12_000,
            3,
            "REVIEWED",
            "REVIEWED",
            1,
            1,
            1,
            "AVAILABLE",
        ),
    )
    connection.execute(
        "INSERT INTO menu_source_detail VALUES (?,?,?,?,?)",
        (menu_id, 0, 0, 0, 0),
    )
    connection.execute(
        "INSERT INTO menu_concept_map VALUES (?,?,?,?,?)",
        (menu_id, "knowledge-v1", concept_id, "MAPPED", "high"),
    )


def _support(
    connection: sqlite3.Connection,
    concept_id: str,
    category: str,
    option: str,
    strength: float,
) -> None:
    connection.execute(
        "INSERT INTO concept_preference_support VALUES (?,?,?,?,?,?,?)",
        (
            "knowledge-v1",
            concept_id,
            category,
            option,
            "SUPPORTED",
            strength,
            f"chunk-{concept_id}-{category}-{option}",
        ),
    )


def _query(criteria: RecommendationCriteriaV2, *, limit: int | None):
    return build_concept_candidate_query(
        dialect="sqlite",
        criteria=criteria,
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-v1",
        service_area_id=None,
        excluded_menu_ids=set(),
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=limit,
    )


def test_same_category_is_max_or_then_cross_categories_are_and() -> None:
    connection = _connection()
    try:
        _insert_menu(connection, menu_id="menu-a", merchant_id="merchant-a", concept_id="a")
        _insert_menu(connection, menu_id="menu-b", merchant_id="merchant-b", concept_id="b")
        _insert_menu(connection, menu_id="menu-c", merchant_id="merchant-c", concept_id="c")
        _support(connection, "a", "flavors", "SPICY", 0.9)
        _support(connection, "a", "flavors", "SWEET", 0.2)
        _support(connection, "a", "food_forms", "NOODLES", 0.8)
        _support(connection, "b", "flavors", "SPICY", 0.7)
        _support(connection, "b", "food_forms", "NOODLES", 0.8)
        _support(connection, "c", "flavors", "SWEET", 0.95)
        query = _query(
            RecommendationCriteriaV2(
                flavors=["SPICY", "SWEET"],
                food_forms=["NOODLES"],
                max_spice_level=5,
            ),
            limit=None,
        )

        rows = connection.execute(query.sql, query.parameters).fetchall()

        assert [row["menu_id"] for row in rows] == ["menu-a", "menu-b"]
        assert rows[0]["explicit_score"] == pytest.approx(0.85)
        assert rows[1]["explicit_score"] == pytest.approx(0.75)
        assert "MAX(support_strength) AS category_support" in query.sql
        assert "COUNT(DISTINCT support.category_code)" in query.sql
    finally:
        connection.close()


def test_candidate_window_caps_each_merchant_at_twenty_five_percent() -> None:
    connection = _connection()
    try:
        for merchant_index, count in enumerate((100, 12, 12, 12), start=1):
            merchant_id = f"merchant-{merchant_index}"
            for menu_index in range(count):
                concept_id = f"concept-{merchant_index}-{menu_index}"
                _insert_menu(
                    connection,
                    menu_id=f"menu-{merchant_index}-{menu_index:03d}",
                    merchant_id=merchant_id,
                    concept_id=concept_id,
                )
                _support(connection, concept_id, "flavors", "SAVORY", 1.0)
        query = _query(
            RecommendationCriteriaV2(flavors=["SAVORY"], max_spice_level=5),
            limit=24,
        )

        rows = connection.execute(query.sql, query.parameters).fetchall()

        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row["merchant_id"])] = counts.get(str(row["merchant_id"]), 0) + 1
        assert len(rows) == 24
        assert set(counts.values()) == {6}
        assert query.parameters["per_merchant_limit"] == 6
    finally:
        connection.close()


def test_exact_score_tiebreak_and_concept_first_diversity_relaxation() -> None:
    decisions = rank_concept_candidates(
        [
            ConceptRankCandidate("a", "merchant-1", "concept-1", {"flavor": 1.0}, 2),
            ConceptRankCandidate("b", "merchant-1", "concept-2", {"flavor": 0.96}, 2),
            ConceptRankCandidate("c", "merchant-2", "concept-1", {"flavor": 0.99}, 2),
        ],
        has_soft_profile=False,
        limit=3,
    )

    assert [item.menu_id for item in decisions] == ["a", "b", "c"]
    assert decisions[0].score == 1.0
    assert decisions[1].diversity_reason == "merchant_relaxed_new_concept"
    assert decisions[2].diversity_reason == "concept_relaxed_new_merchant"
    assert all(item.trace_payload()["ranking_policy_version"] == RANKING_POLICY_VERSION for item in decisions)
    assert RANKING_POLICY_SHA256 == (
        "5515c9c6877641a111e29ba418890b166b84374101877005749257eae826e191"
    )


def test_oracle_query_is_bounded_sql_first_and_has_no_unused_binds() -> None:
    criteria = RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        price_bands=["UNDER_10000"],
        max_spice_level=5,
    )
    query = build_concept_candidate_query(
        dialect="oracle",
        criteria=criteria,
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-unused",
        service_area_id="area-1",
        excluded_menu_ids={"seen-b", "seen-a"},
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=24,
    )
    lowered = query.sql.lower()

    assert "fetch first :candidate_limit rows only" in lowered
    assert "row_number() over" in lowered
    assert "menu.*" not in lowered
    assert "vector" not in lowered
    assert "cosine" not in lowered
    assert "certification_release_id" not in query.parameters
    assert "eligibility_as_of" not in query.parameters
    assert query.parameters["excluded_menu_0"] == "seen-a"
    assert query.parameters["excluded_menu_1"] == "seen-b"


@pytest.mark.parametrize(
    "criteria",
    [
        RecommendationCriteriaV2(
            cuisine_origins=["KOREAN"],
            max_spice_level=5,
        ),
        RecommendationCriteriaV2(
            price_bands=["UNDER_10000"],
            max_spice_level=5,
        ),
    ],
    ids=["subjective", "objective-price-only"],
)
def test_oracle_candidate_and_preview_bind_names_match_parameters_exactly(
    criteria: RecommendationCriteriaV2,
) -> None:
    candidate = build_concept_candidate_query(
        dialect="oracle",
        criteria=criteria,
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-v1",
        service_area_id="area-1",
        excluded_menu_ids={"seen-a"},
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=24,
    )
    preview = build_concept_preview_query(candidate)

    for query in (candidate, preview):
        placeholders = set(re.findall(r":([A-Za-z][A-Za-z0-9_$#]*)", query.sql))
        assert placeholders == set(query.parameters)


@pytest.mark.parametrize("dialect", ["sqlite", "oracle"])
def test_exact_only_query_preaggregates_reviewed_concepts_before_menu_join(
    dialect: str,
) -> None:
    query = build_concept_candidate_query(
        dialect=dialect,  # type: ignore[arg-type]
        criteria=RecommendationCriteriaV2(
            price_bands=["UNDER_10000"],
            max_spice_level=5,
        ),
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-v1",
        service_area_id="area-1",
        excluded_menu_ids=set(),
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=24,
    )
    preview = build_concept_preview_query(query)
    lowered = query.sql.lower()

    assert "objective_concept as" in lowered
    assert "join objective_concept objective_support" in lowered
    assert "join knowledge_chunk objective_chunk" not in lowered
    assert "group by menu.menu_id" not in lowered
    assert "count(distinct chunk.chunk_id)" in lowered
    assert "from qualified" in preview.sql.lower()
    assert "candidate_limit" not in preview.parameters
    assert "per_merchant_limit" not in preview.parameters


def test_synthetic_demo_ranking_sql_is_stable_and_source_counts_take_priority() -> None:
    expressions = food_ranking_sql(
        "sqlite",
        menu_id="menu_id",
        is_synthetic="is_synthetic",
        menu_review_count="menu_reviews",
        merchant_review_count="merchant_reviews",
    )
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            f"""
            SELECT {expressions.review_count} review_count,
                   {expressions.order_count} order_count,
                   {expressions.korean_popularity} korean_popularity,
                   {expressions.basis} basis
            FROM (SELECT ? menu_id,1 is_synthetic,0 menu_reviews,0 merchant_reviews)
            """,
            ("menu-synthetic-000123",),
        ).fetchone()
        assert row is not None
        assert dict(row) == {
            **synthetic_demo_ranking_metrics("menu-synthetic-000123"),
            "basis": "DETERMINISTIC_SYNTHETIC_FALLBACK",
        }

        source_row = connection.execute(
            f"""
            SELECT {expressions.review_count} review_count,
                   {expressions.order_count} order_count,
                   {expressions.korean_popularity} korean_popularity,
                   {expressions.basis} basis
            FROM (SELECT 'menu-source' menu_id,1 is_synthetic,
                         42 menu_reviews,5 merchant_reviews)
            """
        ).fetchone()
        assert source_row is not None
        assert dict(source_row) == {
            "review_count": 42,
            "order_count": 309,
            "korean_popularity": 67,
            "basis": "SOURCE_COUNTS",
        }
    finally:
        connection.close()

    oracle = food_ranking_sql(
        "oracle",
        menu_id="menu.menu_id",
        is_synthetic="menu.is_synthetic",
        menu_review_count="source.review_count",
        merchant_review_count="merchant_source.review_count",
    )
    assert "ASCII(SUBSTR(menu.menu_id,-1,1))" in oracle.review_count
    assert "unicode(" not in oracle.review_count


def test_blind_server_rank_golden_summary_matches_exact_policy() -> None:
    fixture = json.loads(
        (
            ROOT
            / "backend"
            / "evaluation"
            / "fixtures"
            / "server_rank_golden_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert fixture["baseline_boundary"]["old_path_outcome"] == "NO_MATCH"
    assert fixture["server_policy"]["sha256"] == RANKING_POLICY_SHA256
    for case in fixture["golden_cases"]:
        decisions = rank_concept_candidates(
            [
                ConceptRankCandidate(
                    menu_id=item["menu_id"],
                    merchant_id=item["merchant_id"],
                    concept_id=item["concept_id"],
                    category_supports=item["supports"],
                    reviewed_evidence_count=item["reviewed_evidence_count"],
                )
                for item in case["candidates"]
            ],
            has_soft_profile=False,
            limit=3,
        )

        assert [item.menu_id for item in decisions] == case["expected_order"]
        assert len({item.merchant_id for item in decisions}) == case[
            "expected_distinct_merchants"
        ]
        assert len({item.concept_id for item in decisions}) == case[
            "expected_distinct_concepts"
        ]
        assert all(0 <= item.score <= 1 for item in decisions)
    assert all(
        row["expected_server_ids_unchanged"] for row in fixture["llm_fault_matrix"]
    )
    assert fixture["latency_evidence"]["oci_benchmark_required_for_release_claim"] is True


def test_featured_collection_has_same_bounded_hard_filter_shape_in_both_databases() -> None:
    sqlite_source = inspect.getsource(SQLiteYobiRepository.list_kpop_demon_hunters_feature)
    oracle_source = inspect.getsource(OracleYobiRepository.list_kpop_demon_hunters_feature)

    for source in (sqlite_source, oracle_source):
        assert "concept_rank<=20" in source
        assert "_menu_hard_constraint_conflicts" in source
        assert "seen_dishes" in source
        assert "mapping.confidence_band='high'" in source
        assert "menu.availability='AVAILABLE'" in source
