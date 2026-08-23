from __future__ import annotations

import inspect
import json
import re
import sqlite3
from array import array
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db.browse_rankings import food_ranking_sql, synthetic_demo_ranking_metrics
from app.db.concept_query import (
    build_candidate_recall_channel_query,
    build_concept_candidate_query,
    build_concept_preview_count_query,
    build_concept_preview_query,
    build_semantic_candidate_query,
)
from app.db.oracle_repository import OracleYobiRepository
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.concept_ranking import (
    RANKING_POLICY_SHA256,
    RANKING_POLICY_VERSION,
    ConceptRankCandidate,
    candidate_channel_fusion_trace,
    merge_candidate_channels,
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
          service_area_id TEXT, min_order_amount INTEGER,
          delivery_fee INTEGER, eta_min INTEGER, eta_max INTEGER
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
        CREATE TABLE menu_preference_feature (
          knowledge_release_id TEXT, feature_id TEXT, menu_id TEXT,
          category_code TEXT, option_code TEXT, support_status TEXT,
          support_strength REAL, evidence_scope TEXT
        );
        CREATE TABLE menu_concept_membership (
          knowledge_release_id TEXT, menu_id TEXT, concept_id TEXT,
          membership_role TEXT
        );
        CREATE TABLE menu_wiki_eligibility (
          knowledge_release_id TEXT, menu_id TEXT,
          reviewed_chunk_count INTEGER, compiled_at TEXT,
          PRIMARY KEY (knowledge_release_id, menu_id)
        );
        CREATE TABLE synthetic_country_profile (
          release_id TEXT, country_code TEXT, spice_baseline INTEGER,
          familiarity_coefficient REAL,
          PRIMARY KEY (release_id, country_code)
        );
        CREATE TABLE synthetic_menu_profile (
          release_id TEXT, menu_id TEXT, spice_level INTEGER,
          halal_fit INTEGER, vegan_fit INTEGER, generation_version TEXT,
          PRIMARY KEY (release_id, menu_id)
        );
        CREATE TABLE dish_concept_closure (
          release_id TEXT, ancestor_concept_id TEXT, descendant_concept_id TEXT,
          depth INTEGER, inherit_claims INTEGER,
          PRIMARY KEY (release_id, ancestor_concept_id, descendant_concept_id)
        );
        CREATE TABLE knowledge_document (
          release_id TEXT, document_id TEXT, source_type TEXT, review_status TEXT,
          PRIMARY KEY (release_id, document_id)
        );
        CREATE TABLE knowledge_chunk (
          release_id TEXT, chunk_id TEXT, document_id TEXT, concept_id TEXT,
          facet TEXT, metadata_json TEXT,
          PRIMARY KEY (release_id, chunk_id)
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
        "INSERT OR IGNORE INTO merchant VALUES (?,?,?,?,?,?,?,?)",
        (merchant_id, merchant_id, merchant_id, "area", 15_000, 0, 20, 40),
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
    connection.execute(
        "INSERT INTO menu_concept_membership VALUES (?,?,?,?)",
        ("knowledge-v1", menu_id, concept_id, "PRIMARY"),
    )
    connection.execute(
        "INSERT OR IGNORE INTO dish_concept_closure VALUES (?,?,?,?,?)",
        ("knowledge-v1", concept_id, concept_id, 0, 1),
    )
    connection.execute(
        "INSERT OR IGNORE INTO knowledge_document VALUES (?,?,?,?)",
        ("knowledge-v1", f"document-{concept_id}", "SYNTHETIC_WIKI", "REVIEWED_DEMO"),
    )
    connection.execute(
        "INSERT OR IGNORE INTO knowledge_chunk VALUES (?,?,?,?,?,?)",
        (
            "knowledge-v1",
            f"wiki-{concept_id}",
            f"document-{concept_id}",
            concept_id,
            "character",
            '{"recommendation_visibility":"PUBLIC_RAG"}',
        ),
    )
    connection.execute(
        "INSERT INTO menu_wiki_eligibility VALUES (?,?,?,?)",
        ("knowledge-v1", menu_id, 1, "2026-08-19T00:00:00+00:00"),
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


def _query(
    criteria: RecommendationCriteriaV2,
    *,
    limit: int | None,
    synthetic_enrichment_release_id: str | None = None,
):
    return build_concept_candidate_query(
        dialect="sqlite",
        criteria=criteria,
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-v1",
        service_area_id=None,
        excluded_menu_ids=set(),
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=limit,
        synthetic_enrichment_release_id=synthetic_enrichment_release_id,
    )


def _insert_synthetic_profile(
    connection: sqlite3.Connection,
    *,
    menu_id: str,
    spice_level: int,
    halal_fit: bool = True,
    vegan_fit: bool = True,
) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO synthetic_country_profile VALUES (?,?,?,?)",
        ("enrichment-v1", "US", 3, 0.75),
    )
    connection.execute(
        "INSERT INTO synthetic_menu_profile VALUES (?,?,?,?,?,?)",
        (
            "enrichment-v1",
            menu_id,
            spice_level,
            int(halal_fit),
            int(vegan_fit),
            "synthetic-v1",
        ),
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


def test_compound_menu_cannot_mix_form_and_temperature_across_components() -> None:
    connection = _connection()
    try:
        _insert_menu(
            connection,
            menu_id="compound-menu",
            merchant_id="merchant-compound",
            concept_id="set-primary",
        )
        connection.executemany(
            "INSERT INTO menu_concept_membership VALUES (?,?,?,?)",
            [
                ("knowledge-v1", "compound-menu", "cold-noodle", "COMPONENT"),
                ("knowledge-v1", "compound-menu", "hot-cutlet", "COMPONENT"),
            ],
        )
        _support(connection, "cold-noodle", "food_forms", "NOODLES", 0.95)
        _support(connection, "cold-noodle", "temperatures", "COOL", 0.95)
        _support(connection, "hot-cutlet", "food_forms", "SOLID", 0.95)
        _support(connection, "hot-cutlet", "temperatures", "HOT", 0.95)

        query = _query(
            RecommendationCriteriaV2(food_forms=["NOODLES"], temperatures=["HOT"]),
            limit=None,
        )

        assert connection.execute(query.sql, query.parameters).fetchall() == []
    finally:
        connection.close()


def test_compound_menu_is_kept_when_one_component_coherently_matches() -> None:
    connection = _connection()
    try:
        _insert_menu(
            connection,
            menu_id="coherent-set",
            merchant_id="merchant-coherent",
            concept_id="set-primary",
        )
        connection.executemany(
            "INSERT INTO menu_concept_membership VALUES (?,?,?,?)",
            [
                ("knowledge-v1", "coherent-set", "hot-noodle", "COMPONENT"),
                ("knowledge-v1", "coherent-set", "hot-dumpling", "COMPONENT"),
            ],
        )
        _support(connection, "hot-noodle", "food_forms", "NOODLES", 0.95)
        _support(connection, "hot-noodle", "temperatures", "HOT", 0.95)
        _support(connection, "hot-dumpling", "food_forms", "SOLID", 0.85)
        _support(connection, "hot-dumpling", "temperatures", "HOT", 0.85)

        query = _query(
            RecommendationCriteriaV2(food_forms=["NOODLES"], temperatures=["HOT"]),
            limit=None,
        )
        rows = connection.execute(query.sql, query.parameters).fetchall()

        assert [row["menu_id"] for row in rows] == ["coherent-set"]
    finally:
        connection.close()


def test_wiki_eligibility_is_applied_before_candidate_ranking() -> None:
    connection = _connection()
    try:
        _insert_menu(
            connection,
            menu_id="menu-grounded",
            merchant_id="merchant-grounded",
            concept_id="grounded",
        )
        _insert_menu(
            connection,
            menu_id="menu-without-wiki",
            merchant_id="merchant-without-wiki",
            concept_id="without-wiki",
        )
        _support(connection, "grounded", "flavors", "SPICY", 0.8)
        _support(connection, "without-wiki", "flavors", "SPICY", 1.0)
        connection.execute("DELETE FROM knowledge_chunk WHERE concept_id='without-wiki'")
        connection.execute("DELETE FROM menu_wiki_eligibility WHERE menu_id='menu-without-wiki'")

        query = _query(
            RecommendationCriteriaV2(flavors=["SPICY"], max_spice_level=5),
            limit=100,
        )
        rows = connection.execute(query.sql, query.parameters).fetchall()

        assert [row["menu_id"] for row in rows] == ["menu-grounded"]
        assert "menu_wiki_eligibility" in query.sql
        assert "wiki_eligible.menu_id=menu.menu_id" in query.sql
        assert "knowledge_chunk" not in query.sql
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("spice_preference", "expected_menu_id"),
    [("LESS", "menu-less"), ("SIMILAR", "menu-similar"), ("MORE", "menu-more")],
)
def test_v3_price_spice_and_synthetic_dietary_filters(
    spice_preference: str,
    expected_menu_id: str,
) -> None:
    connection = _connection()
    try:
        for menu_id, spice_level in (
            ("menu-less", 2),
            ("menu-similar", 3),
            ("menu-more", 4),
        ):
            _insert_menu(
                connection,
                menu_id=menu_id,
                merchant_id=f"merchant-{menu_id}",
                concept_id=f"concept-{menu_id}",
            )
            _insert_synthetic_profile(
                connection,
                menu_id=menu_id,
                spice_level=spice_level,
            )

        selected_spice = {"LESS": 2, "SIMILAR": 3, "MORE": 4}[spice_preference]
        _insert_menu(
            connection,
            menu_id="menu-dietary-blocked",
            merchant_id="merchant-dietary-blocked",
            concept_id="concept-dietary-blocked",
        )
        _insert_synthetic_profile(
            connection,
            menu_id="menu-dietary-blocked",
            spice_level=selected_spice,
            halal_fit=False,
            vegan_fit=False,
        )
        _insert_menu(
            connection,
            menu_id="menu-price-blocked",
            merchant_id="merchant-price-blocked",
            concept_id="concept-price-blocked",
        )
        _insert_synthetic_profile(
            connection,
            menu_id="menu-price-blocked",
            spice_level=selected_spice,
        )

        # One otherwise matching row fails the v3 price gate and another fails
        # both synthetic dietary switches.
        connection.execute("UPDATE menu SET price=30000 WHERE menu_id='menu-price-blocked'")

        criteria = RecommendationCriteriaV2.model_validate(
            {
                "schema_version": "3",
                "price_range_krw": {"min": 8000, "max": 25000},
                "spice_preference": spice_preference,
                "spice_reference_country": "US",
                "dietary_filters": {
                    "halal_certified_only": True,
                    "vegan": True,
                },
            }
        )
        query = _query(
            criteria,
            limit=None,
            synthetic_enrichment_release_id="enrichment-v1",
        )
        rows = connection.execute(query.sql, query.parameters).fetchall()

        assert [row["menu_id"] for row in rows] == [expected_menu_id]
        assert "menu.price BETWEEN :price_min_krw AND :price_max_krw" in query.sql
        assert "synthetic_menu.spice_level" in query.sql
        assert "synthetic_halal.halal_fit=1" in query.sql
        assert "synthetic_vegan.vegan_fit=1" in query.sql
    finally:
        connection.close()


def test_v3_query_fails_closed_without_active_synthetic_release() -> None:
    criteria = RecommendationCriteriaV2.model_validate(
        {
            "schema_version": "3",
            "price_range_krw": {"min": 8000, "max": 25000},
            "spice_preference": "SIMILAR",
            "spice_reference_country": "US",
        }
    )

    query = _query(criteria, limit=None)

    assert "1=0" in query.sql
    assert "synthetic_enrichment_release_id" not in query.parameters


def test_v3_absolute_spice_range_is_inclusive_and_country_independent() -> None:
    connection = _connection()
    try:
        for level in range(1, 6):
            menu_id = f"menu-level-{level}"
            _insert_menu(
                connection,
                menu_id=menu_id,
                merchant_id=f"merchant-level-{level}",
                concept_id=f"concept-level-{level}",
            )
            _insert_synthetic_profile(connection, menu_id=menu_id, spice_level=level)

        criteria = RecommendationCriteriaV2.model_validate(
            {
                "schema_version": "3",
                "price_range_krw": {"min": 6_000, "max": 50_000},
                "spice_range": {"min": 2, "max": 4},
                "spice_preference": "MORE",
                "spice_reference_country": "ZZ",
            }
        )
        query = _query(
            criteria,
            limit=None,
            synthetic_enrichment_release_id="enrichment-v1",
        )
        rows = connection.execute(query.sql, query.parameters).fetchall()

        assert {row["menu_id"] for row in rows} == {
            "menu-level-2",
            "menu-level-3",
            "menu-level-4",
        }
        assert "synthetic_country_profile" not in query.sql
        assert query.parameters["spice_min_level"] == 2
        assert query.parameters["spice_max_level"] == 4
    finally:
        connection.close()


def test_v3_requires_ordered_price_range_and_v2_snapshot_remains_readable() -> None:
    with pytest.raises(ValueError, match="PRICE_RANGE_REQUIRED"):
        RecommendationCriteriaV2.model_validate({"schema_version": "3"})
    with pytest.raises(ValueError, match="PRICE_RANGE_ORDER_INVALID"):
        RecommendationCriteriaV2.model_validate(
            {
                "schema_version": "3",
                "price_range_krw": {"min": 25000, "max": 8000},
            }
        )
    with pytest.raises(ValueError, match="SPICE_RANGE_ORDER_INVALID"):
        RecommendationCriteriaV2.model_validate(
            {
                "schema_version": "3",
                "price_range_krw": {"min": 6_000, "max": 50_000},
                "spice_range": {"min": 4, "max": 2},
            }
        )

    restored_v2 = RecommendationCriteriaV2.model_validate(
        {
            "schema_version": "2",
            "price_bands": ["FROM_10000_TO_19999"],
            "max_spice_level": 3,
            "dietary_filters": {
                "halal_certified_only": False,
                "vegan": False,
            },
        }
    )

    assert restored_v2.schema_version == "2"
    assert restored_v2.price_range_krw is None
    assert restored_v2.max_spice_level == 3


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
    assert decisions[0].score == pytest.approx(0.575)
    assert decisions[1].diversity_reason == "merchant_relaxed_new_concept"
    assert decisions[2].diversity_reason == "concept_relaxed_new_merchant"
    assert all(
        item.trace_payload()["ranking_policy_version"] == RANKING_POLICY_VERSION
        for item in decisions
    )
    assert RANKING_POLICY_SHA256 == (
        "d557ecf2735e2cfa8e350eefa37e3686db7165c170f4d2965ee14e6bb7c688bf"
    )


def test_diversity_cannot_replace_stronger_direct_grounding() -> None:
    decisions = rank_concept_candidates(
        [
            ConceptRankCandidate(
                "direct-a",
                "merchant-1",
                "concept-1",
                {"flavor": 0.90},
                1,
                semantic_score=0.50,
                direct_evidence_ratio=1.0,
            ),
            ConceptRankCandidate(
                "general-b",
                "merchant-2",
                "concept-2",
                {"flavor": 0.95},
                1,
                semantic_score=0.50,
                direct_evidence_ratio=0.0,
            ),
            ConceptRankCandidate(
                "direct-c",
                "merchant-1",
                "concept-3",
                {"flavor": 0.88},
                1,
                semantic_score=0.50,
                direct_evidence_ratio=1.0,
            ),
        ],
        has_soft_profile=False,
        limit=3,
    )

    assert [item.menu_id for item in decisions[:2]] == ["direct-a", "direct-c"]


def test_candidate_channel_union_is_bounded_deterministic_and_order_symmetric() -> None:
    menu_feature = ["menu-a", "menu-b", "menu-c"]
    concept_support = ["menu-b", "menu-d", "menu-e"]
    semantic = ["menu-c", "menu-d", "menu-a"]

    first = merge_candidate_channels(
        [menu_feature, concept_support, semantic],
        limit=4,
    )
    permuted = merge_candidate_channels(
        [semantic, menu_feature, concept_support],
        limit=4,
    )

    assert first == permuted == ["menu-b", "menu-a", "menu-c", "menu-d"]
    assert len(first) == 4


def test_candidate_channel_fusion_trace_records_ranks_and_rrf_contributions() -> None:
    trace = candidate_channel_fusion_trace(
        {
            "MENU_FEATURE": ["menu-a", "menu-b"],
            "CONCEPT_SUPPORT": ["menu-b", "menu-c"],
            "SEMANTIC": ["menu-c", "menu-a"],
        }
    )

    assert trace["menu-a"]["channel_ranks"] == {
        "MENU_FEATURE": 1,
        "SEMANTIC": 2,
    }
    assert trace["menu-a"]["rrf_score"] == pytest.approx(1 / 61 + 1 / 62)
    assert set(trace["menu-b"]["rrf_contributions"]) == {
        "MENU_FEATURE",
        "CONCEPT_SUPPORT",
    }


def test_three_candidate_channels_are_independent_and_final_grounding_drops_auxiliary_only() -> (
    None
):
    connection = _connection()
    try:
        for suffix in ("aux", "direct", "concept"):
            _insert_menu(
                connection,
                menu_id=f"menu-{suffix}",
                merchant_id=f"merchant-{suffix}",
                concept_id=f"concept-{suffix}",
            )
        connection.executemany(
            "INSERT INTO menu_preference_feature VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    "knowledge-v1",
                    "feature-aux",
                    "menu-aux",
                    "flavors",
                    "SPICY",
                    "REVIEW_REQUIRED",
                    0.4,
                    "SECTION_CONTEXT",
                ),
                (
                    "knowledge-v1",
                    "feature-direct",
                    "menu-direct",
                    "flavors",
                    "SPICY",
                    "SUPPORTED",
                    0.9,
                    "MENU_DIRECT",
                ),
            ],
        )
        _support(connection, "concept-concept", "flavors", "SPICY", 0.7)
        criteria = RecommendationCriteriaV2(flavors=["SPICY"], max_spice_level=5)

        def menu_ids(channel: str) -> list[str]:
            query = build_concept_candidate_query(
                dialect="sqlite",
                criteria=criteria,
                knowledge_release_id="knowledge-v1",
                certification_release_id="certification-v1",
                service_area_id=None,
                excluded_menu_ids=set(),
                eligibility_as_of=datetime.now(timezone.utc),
                candidate_limit=None,
                support_channel=channel,  # type: ignore[arg-type]
            )
            return [
                str(row["menu_id"])
                for row in connection.execute(query.sql, query.parameters).fetchall()
            ]

        assert menu_ids("MENU_FEATURE") == ["menu-direct", "menu-aux"]
        assert menu_ids("CONCEPT_SUPPORT") == ["menu-concept"]
        assert menu_ids("COMBINED") == ["menu-direct", "menu-concept"]
    finally:
        connection.close()


def test_optimized_channel_and_preview_queries_preserve_grounding_counts() -> None:
    connection = _connection()
    try:
        for suffix in ("direct", "concept", "unrelated"):
            _insert_menu(
                connection,
                menu_id=f"menu-{suffix}",
                merchant_id=f"merchant-{suffix}",
                concept_id=f"concept-{suffix}",
            )
        connection.execute(
            "INSERT INTO menu_preference_feature VALUES (?,?,?,?,?,?,?,?)",
            (
                "knowledge-v1",
                "feature-direct",
                "menu-direct",
                "flavors",
                "SPICY",
                "SUPPORTED",
                0.9,
                "MENU_DIRECT",
            ),
        )
        _support(connection, "concept-concept", "flavors", "SPICY", 0.7)
        criteria = RecommendationCriteriaV2(flavors=["SPICY"], max_spice_level=5)
        common = {
            "dialect": "sqlite",
            "criteria": criteria,
            "knowledge_release_id": "knowledge-v1",
            "certification_release_id": "certification-v1",
            "service_area_id": None,
            "excluded_menu_ids": set(),
            "eligibility_as_of": datetime.now(timezone.utc),
        }
        feature = build_candidate_recall_channel_query(
            **common,  # type: ignore[arg-type]
            candidate_limit=100,
            support_channel="MENU_FEATURE",
        )
        concept = build_candidate_recall_channel_query(
            **common,  # type: ignore[arg-type]
            candidate_limit=100,
            support_channel="CONCEPT_SUPPORT",
        )
        preview = build_concept_preview_count_query(**common)  # type: ignore[arg-type]

        assert [
            row["menu_id"] for row in connection.execute(feature.sql, feature.parameters).fetchall()
        ] == ["menu-direct"]
        assert [
            row["menu_id"] for row in connection.execute(concept.sql, concept.parameters).fetchall()
        ] == ["menu-concept"]
        counts = connection.execute(preview.sql, preview.parameters).fetchone()
        assert counts is not None
        assert tuple(counts) == (2, 2)
    finally:
        connection.close()


@pytest.mark.parametrize("support_channel", ["MENU_FEATURE", "CONCEPT_SUPPORT"])
def test_oracle_grounded_channel_bind_names_match_parameters_exactly(
    support_channel: str,
) -> None:
    query = build_candidate_recall_channel_query(
        dialect="oracle",
        criteria=RecommendationCriteriaV2(flavors=["SPICY"], max_spice_level=5),
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-v1",
        service_area_id="area-1",
        excluded_menu_ids={"seen-a"},
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=100,
        support_channel=support_channel,  # type: ignore[arg-type]
    )

    assert set(re.findall(r":([A-Za-z][A-Za-z0-9_$#]*)", query.sql)) == set(query.parameters)


@pytest.mark.parametrize(
    "criteria",
    [
        RecommendationCriteriaV2(flavors=["SPICY"], max_spice_level=5),
        RecommendationCriteriaV2(price_bands=["FROM_10000_TO_19999"], max_spice_level=5),
    ],
)
def test_oracle_optimized_preview_bind_names_match_parameters_exactly(
    criteria: RecommendationCriteriaV2,
) -> None:
    query = build_concept_preview_count_query(
        dialect="oracle",
        criteria=criteria,
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-v1",
        service_area_id="area-1",
        excluded_menu_ids={"seen-a"},
        eligibility_as_of=datetime.now(timezone.utc),
    )

    assert set(re.findall(r":([A-Za-z][A-Za-z0-9_$#]*)", query.sql)) == set(query.parameters)


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


def test_oracle_semantic_channel_is_hard_filtered_bounded_and_vector_ranked() -> None:
    query = build_semantic_candidate_query(
        dialect="oracle",
        criteria=RecommendationCriteriaV2(
            flavors=["SPICY"],
            price_bands=["FROM_10000_TO_19999"],
            max_spice_level=3,
        ),
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-v1",
        service_area_id="area-1",
        excluded_menu_ids={"seen-a"},
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=100,
        query_vector=array("f", [0.0] * 1536),
        semantic_embedding_model="cohere.embed-v4.0",
        semantic_embedding_version="oci-native-embedtext-v1",
        semantic_embedding_dimension=1536,
        catalog_release_id="catalog-v1",
    )
    lowered = query.sql.lower()

    assert "vector_distance(semantic_embedding.embedding_vector,:query_vector,cosine)" in lowered
    assert "fetch first :candidate_limit rows only" in lowered
    assert "menu.availability='available'" in lowered
    assert "coalesce(source_detail.soldout,0)=0" in lowered
    assert "menu.spice_level<=:max_spice_level" in lowered
    assert "join menu_semantic_embedding semantic_embedding" in lowered
    assert "semantic_embedding.embedding_model=:semantic_embedding_model" in lowered
    assert "semantic_embedding.embedding_version=:semantic_embedding_version" in lowered
    assert "semantic_embedding.embedding_dimension=:semantic_embedding_dimension" in lowered
    assert "semantic_embedding.catalog_release_id=:semantic_catalog_release_id" in lowered
    assert "concept_preference_support" not in lowered
    assert set(re.findall(r":([A-Za-z][A-Za-z0-9_$#]*)", query.sql)) == set(query.parameters)


def test_grounding_query_can_restrict_the_semantic_union_before_final_ranking() -> None:
    query = build_concept_candidate_query(
        dialect="sqlite",
        criteria=RecommendationCriteriaV2(flavors=["SPICY"], max_spice_level=5),
        knowledge_release_id="knowledge-v1",
        certification_release_id="certification-v1",
        service_area_id=None,
        excluded_menu_ids=set(),
        eligibility_as_of=datetime.now(timezone.utc),
        candidate_limit=None,
        included_menu_ids=["menu-b", "menu-a", "menu-b"],
    )

    assert "menu.menu_id IN (:included_menu_0,:included_menu_1)" in query.sql
    assert query.parameters["included_menu_0"] == "menu-b"
    assert query.parameters["included_menu_1"] == "menu-a"


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
        RecommendationCriteriaV2.model_validate(
            {
                "schema_version": "3",
                "price_range_krw": {"min": 8000, "max": 25000},
                "spice_preference": "SIMILAR",
                "spice_reference_country": "US",
                "dietary_filters": {
                    "halal_certified_only": True,
                    "vegan": True,
                },
            }
        ),
    ],
    ids=["subjective", "objective-price-only", "v3-synthetic-objectives"],
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
        synthetic_enrichment_release_id="enrichment-v1",
    )
    preview = build_concept_preview_query(candidate)

    for query in (candidate, preview):
        placeholders = set(re.findall(r":([A-Za-z][A-Za-z0-9_$#]*)", query.sql))
        assert placeholders == set(query.parameters)


@pytest.mark.parametrize("dialect", ["sqlite", "oracle"])
def test_exact_only_query_uses_materialized_wiki_eligibility_before_menu_join(
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

    assert "objective_grounding as" in lowered
    assert "candidate_membership as" in lowered
    assert "partition by membership.menu_id" in lowered
    assert "when 'primary' then 1" in lowered
    assert "join objective_grounding objective_support" in lowered
    assert "from menu_wiki_eligibility" in lowered
    assert "join knowledge_chunk objective_chunk" not in lowered
    assert "group by menu.menu_id" not in lowered
    assert "reviewed_chunk_count" in lowered
    assert "from qualified" in preview.sql.lower()
    assert "candidate_limit" not in preview.parameters
    assert "per_merchant_limit" not in preview.parameters


def test_synthetic_demo_ranking_sql_is_stable_and_blends_source_counts() -> None:
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
        prepared_source_metrics = synthetic_demo_ranking_metrics("menu-source")
        assert dict(source_row) == {
            "review_count": 42,
            "order_count": prepared_source_metrics["order_count"] + 309,
            "korean_popularity": prepared_source_metrics["korean_popularity"] + 67,
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
            ROOT / "backend" / "evaluation" / "fixtures" / "server_rank_golden_summary.json"
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
        assert len({item.merchant_id for item in decisions}) == case["expected_distinct_merchants"]
        assert len({item.concept_id for item in decisions}) == case["expected_distinct_concepts"]
        assert all(0 <= item.score <= 1 for item in decisions)
    assert all(row["expected_server_ids_unchanged"] for row in fixture["llm_fault_matrix"])
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
