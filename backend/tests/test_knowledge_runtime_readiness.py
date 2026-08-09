from __future__ import annotations

import inspect
import json
from array import array
from unittest.mock import MagicMock

from app.db.oracle_repository import OracleYobiRepository
from app.db.seed_data import CATALOG_VERSION
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.dialogue import ConstraintStrictness, MealNeedState
from app.domain.models import ProfileCreate
from app.rag.embeddings import deterministic_embedding


def test_sqlite_recommendation_uses_active_chunks_and_tracks_grounding(
    repository: SQLiteYobiRepository,
) -> None:
    query_vector = deterministic_embedding("query: warm savory soup")
    with repository._connection() as connection:
        ranked = repository._bulk_knowledge_passages(
            connection,
            ["menu_001_01", "menu_003_01"],
            query_vector,
        )

    assert set(ranked) == {"menu_001_01", "menu_003_01"}
    assert all(0 <= score <= 1 for score, _ in ranked.values())
    assert all(1 <= len(passage_ids) <= 3 for _, passage_ids in ranked.values())
    assert all(
        passage_id.startswith("chunk_")
        for _, passage_ids in ranked.values()
        for passage_id in passage_ids
    )

    profile = repository.create_profile(
        ProfileCreate(consent_demo_data=True, dietary_rules=[], spice_tolerance=3)
    )
    recommendations = repository.recommend_menus(
        "warm savory soup",
        profile,
        MealNeedState(max_spiciness=3),
        limit=4,
    )
    assert recommendations
    assert all(menu.grounded_claim_ids for menu in recommendations)
    assert all(menu.grounded_passage_ids for menu in recommendations)
    assert all(
        not passage_id.startswith("knowledge_")
        for menu in recommendations
        for passage_id in menu.grounded_passage_ids
    )


def test_oracle_chunk_query_contract_matches_sqlite_active_release_contract() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.description = [("MENU_ID",), ("CHUNK_ID",), ("DISTANCE",)]
    cursor.fetchall.return_value = [("menu_001_01", "chunk_one", 0.2)]

    result = OracleYobiRepository._bulk_knowledge_passages(
        connection,
        ["menu_001_01"],
        array("f", [0.0] * 1536),
    )

    sql = str(cursor.execute.call_args.args[0])
    assert "knowledge_runtime_state" in sql
    assert "knowledge_chunk" in sql
    assert "menu_concept_map" in sql
    assert "menu_knowledge" not in sql
    assert result == {"menu_001_01": (0.8, ["chunk_one"])}


def test_both_recommendation_paths_exclude_legacy_menu_knowledge_from_ranking() -> None:
    for repository_type in (SQLiteYobiRepository, OracleYobiRepository):
        source = inspect.getsource(repository_type.search_menus)
        assert "_bulk_knowledge_passages" in source
        assert "menu_knowledge" not in source
        assert "0.25 * knowledge" in source


def test_merchant_scope_is_cross_contact_not_menu_presence(
    repository: SQLiteYobiRepository,
) -> None:
    knowledge = repository.get_grounded_menu_knowledge("menu_027_02")
    merchant_pork = [
        claim
        for claim in knowledge.merchant_ingredient_claims
        if claim.ingredient_id == "ingredient_pork"
    ]

    assert merchant_pork
    assert not any(
        claim.ingredient_id == "ingredient_pork" for claim in knowledge.ingredient_claims
    )
    with repository._connection() as connection:
        strict_conflicts, strict_claim_ids = repository._menu_hard_constraint_conflicts(
            connection,
            "menu_027_02",
            MealNeedState(
                excluded_ingredients=["pork"],
                strictness=ConstraintStrictness.STRICT,
            ),
            "mild",
        )
        exploratory_conflicts, _ = repository._menu_hard_constraint_conflicts(
            connection,
            "menu_027_02",
            MealNeedState(
                excluded_ingredients=["pork"],
                strictness=ConstraintStrictness.EXPLORATORY,
            ),
            "mild",
        )

    assert "merchant_cross_contact:ingredient_pork" in strict_conflicts
    assert merchant_pork[0].source_id in strict_claim_ids
    assert "merchant_cross_contact:ingredient_pork" not in exploratory_conflicts


def test_readiness_is_derived_from_release_rows_and_exact_counts(
    repository: SQLiteYobiRepository,
) -> None:
    ready = repository.status()
    assert ready["knowledge_ready"] is True
    assert all(ready["readiness_checks"].values())

    with repository._connection() as connection:
        connection.execute(
            """
            UPDATE knowledge_release SET actual_counts_json=?
            WHERE release_id=(SELECT active_release_id FROM knowledge_runtime_state
                              WHERE state_key='ACTIVE')
            """,
            (json.dumps({"chunks": 1}),),
        )
    mismatch = repository.status()
    assert mismatch["knowledge_ready"] is False
    assert mismatch["readiness_checks"]["release_counts_exact"] is False


def test_readiness_rejects_supplemental_or_option_integrity_drift(
    repository: SQLiteYobiRepository,
) -> None:
    with repository._connection() as connection:
        connection.execute(
            """
            DELETE FROM merchant_ingredient
            WHERE rowid=(SELECT MIN(rowid) FROM merchant_ingredient)
            """
        )
        connection.execute(
            """
            UPDATE menu_option_group SET min_select=max_select+1
            WHERE option_group_id=(SELECT MIN(option_group_id) FROM menu_option_group)
            """
        )

    status = repository.status()
    assert status["knowledge_ready"] is False
    assert status["readiness_checks"]["merchant_ingredients_exact"] is False
    assert status["readiness_checks"]["required_options_valid"] is False


def test_prewarm_cache_is_invalidated_and_versioned_by_active_knowledge_release(
    repository: SQLiteYobiRepository,
) -> None:
    with repository._connection() as connection:
        active_release = str(
            connection.execute(
                """
                SELECT active_release_id FROM knowledge_runtime_state
                WHERE state_key='ACTIVE'
                """
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO explanation_cache (
              cache_key,menu_id,language,profile_signature,
              explanation_json,source_version,created_at
            ) VALUES ('stale-cache','menu_003_01','en','prewarm','{}','stale-release','old')
            """
        )

    assert repository.prewarm_explanation("menu_003_01") is True

    with repository._connection() as connection:
        rows = connection.execute(
            """
            SELECT cache_key,source_version FROM explanation_cache
            WHERE menu_id='menu_003_01' AND language='en'
              AND profile_signature='prewarm'
            """
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["source_version"] == f"{CATALOG_VERSION}:{active_release}"
    assert rows[0]["cache_key"].startswith("prewarm:menu_003_01:en:")


def test_oracle_prewarm_cache_uses_the_same_release_versioning_contract() -> None:
    source = inspect.getsource(OracleYobiRepository.prewarm_explanation)

    assert "knowledge_runtime_state" in source
    assert "DELETE FROM explanation_cache" in source
    assert 'source_version = f"{CATALOG_VERSION}:{knowledge_version}"' in source


def test_oracle_origin_query_never_uses_clob_as_a_distinct_key() -> None:
    source = inspect.getsource(OracleYobiRepository.get_grounded_menu_knowledge)

    assert "SELECT DISTINCT declaration.raw_text" not in source
    assert "SELECT declaration.raw_text,declaration.declaration_id" in source
