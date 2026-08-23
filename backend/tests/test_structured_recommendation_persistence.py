from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from inspect import getsource
from pathlib import Path
from typing import Literal

import pytest
from fastapi.testclient import TestClient

from app.db.oracle_repository import OracleYobiRepository
from app.db.sqlite_repository import SQLiteYobiRepository
from app.dependencies import get_option_localization_service, get_repository
from app.domain.concept_ranking import RANKING_POLICY_SHA256, RANKING_POLICY_VERSION
from app.domain.dialogue import (
    ConversationEventInput,
    ConversationEventType,
    RecommendationCandidate,
    RecommendationResult,
    RecommendationSnapshot,
)
from app.domain.models import ProfileCreate
from app.domain.preference_catalog import PREFERENCE_CATALOG_VERSION
from app.domain.structured_recommendation import (
    RecommendationCriteriaCommit,
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationRequestInput,
    RecommendationRequestStatus,
)
from app.knowledge.preference_support import support_manifest_sha256
from app.main import _preference_catalog_etag, app
from app.rag.embeddings import deterministic_embedding


class RecordingEmbeddingProvider:
    model = "yobi-semantic-hash-v1"
    dimension = 1536
    version = "2026-08-06"

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    def embed(
        self,
        texts: list[str],
        mode: Literal["SEARCH_DOCUMENT", "SEARCH_QUERY"],
    ) -> list[list[float]]:
        self.calls.append((list(texts), mode))
        prefix = "document: " if mode == "SEARCH_DOCUMENT" else "query: "
        return [deterministic_embedding(prefix + text, self.dimension) for text in texts]


def test_synthetic_support_manifest_is_grounded_and_upgrade_backfills(
    repository: SQLiteYobiRepository,
) -> None:
    family = repository.get_active_recommendation_release_family()
    assert family is not None
    with repository._connection() as connection:
        rows = connection.execute(
            """
            SELECT support.*,document.source_type,document.review_status document_review,
                   chunk.facet,chunk.metadata_json
            FROM concept_preference_support support
            JOIN knowledge_chunk chunk
              ON chunk.release_id=support.knowledge_release_id
             AND chunk.chunk_id=support.evidence_chunk_id
            JOIN knowledge_document document
              ON document.release_id=chunk.release_id
             AND document.document_id=chunk.document_id
            WHERE support.knowledge_release_id=?
            ORDER BY support.concept_id,support.category_code,support.option_code
            """,
            (family.knowledge_release_id,),
        ).fetchall()
        assert rows
        manifest_rows = [dict(row) for row in rows]
        assert all(row["source_type"] == "SYNTHETIC_WIKI" for row in rows)
        assert all(row["document_review"] == "REVIEWED_DEMO" for row in rows)
        assert all(str(row["facet"]).lower() != "safety" for row in rows)
        assert all(row["provenance_type"] == "SYNTHETIC_WIKI" for row in rows)
        assert all(row["support_status"] == "SUPPORTED" for row in rows)
        assert support_manifest_sha256(manifest_rows) == family.support_manifest_sha256
        connection.execute(
            "DELETE FROM concept_preference_support WHERE knowledge_release_id=?",
            (family.knowledge_release_id,),
        )

    repository.initialize()

    restored = repository.get_active_recommendation_release_family()
    assert restored is not None
    assert restored.ranking_policy_version == RANKING_POLICY_VERSION
    assert restored.ranking_policy_sha256 == RANKING_POLICY_SHA256
    assert restored.support_manifest_sha256 == family.support_manifest_sha256
    with repository._connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM concept_preference_support WHERE knowledge_release_id=?",
            (restored.knowledge_release_id,),
        ).fetchone()[0] == len(rows)


def test_normal_preview_skips_unrequested_capability_scans(
    repository: SQLiteYobiRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile(repository)
    session = repository.create_session(profile.profile_id)
    statements: list[str] = []
    original_connection = repository._connection

    @contextmanager
    def traced_connection():  # type: ignore[no-untyped-def]
        with original_connection() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(repository, "_connection", traced_connection)
    preview = repository.preview_recommendation(
        session.session_id,
        RecommendationCriteriaV2(cuisine_origins=["KOREAN"], max_spice_level=5),
    )

    sql = "\n".join(statements).lower()
    assert preview.eligible_menu_count > 0
    assert "join menu_dietary_attribute relation" not in sql
    assert "from merchant_certification" not in sql
    assert "spice_menus" not in sql


def test_preference_catalog_etag_replays_support_manifest(repository) -> None:  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_repository] = lambda: repository
    client = TestClient(app)
    try:
        first = client.get("/api/v1/recommendation/preferences/catalog?locale=en")
        replay = client.get(
            "/api/v1/recommendation/preferences/catalog?locale=en",
            headers={"If-None-Match": first.headers["etag"]},
        )
        weak_replay = client.get(
            "/api/v1/recommendation/preferences/catalog?locale=en",
            headers={"If-None-Match": f"W/{first.headers['etag']}"},
        )
        japanese = client.get("/api/v1/recommendation/preferences/catalog?locale=ja")
        cross_locale = client.get(
            "/api/v1/recommendation/preferences/catalog?locale=ja",
            headers={"If-None-Match": first.headers["etag"]},
        )
    finally:
        client.close()
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert replay.status_code == 304
    assert weak_replay.status_code == 304
    payload = first.json()
    assert payload["support_manifest_sha256"] != "0" * 64
    assert payload["ranking_policy_version"] == RANKING_POLICY_VERSION
    expected_groups = {
        "cuisine_origins": "core",
        "main_ingredients": "core",
        "food_forms": "core",
        "flavors": "additional",
        "textures": "additional",
        "cooking_methods": "additional",
        "temperatures": "additional",
        "price_bands": "exact",
    }
    assert {category["code"]: category["group"] for category in payload["categories"]} == {
        code: group
        for code, group in expected_groups.items()
        if any(category["code"] == code for category in payload["categories"])
    }
    assert all(
        isinstance(option[field], int) and option[field] >= 0
        for category in payload["categories"]
        for option in category["options"]
        for field in (
            "eligible_menu_count",
            "eligible_merchant_count",
            "reviewed_document_count",
        )
    )
    assert set(payload["capabilities"]) == {
        "halal_certified_only",
        "vegan",
        "max_spice_level",
    }
    assert all(
        isinstance(capability["enabled"], bool)
        and (
            capability["disabled_reason"] is None
            if capability["enabled"]
            else bool(capability["disabled_reason"])
        )
        for capability in payload["capabilities"].values()
    )
    assert replay.status_code == 304
    assert japanese.status_code == 200
    assert japanese.headers["etag"] != first.headers["etag"]
    assert cross_locale.status_code == 200
    assert first.headers["cache-control"] == "private, max-age=300"
    assert "vary" not in first.headers


def test_preference_catalog_etag_changes_with_visible_payload_content() -> None:
    base = {
        "locale": "en",
        "catalog_version": "same-version",
        "country_spice_profiles": [
            {"country_code": "US", "spice_scale_anchors": [{"familiar_dish": "Old"}]}
        ],
    }
    changed = {
        **base,
        "country_spice_profiles": [
            {"country_code": "US", "spice_scale_anchors": [{"familiar_dish": "New"}]}
        ],
    }

    assert _preference_catalog_etag(base) != _preference_catalog_etag(changed)


def test_retry_excludes_seen_menus_and_returns_empty_when_exhausted(
    repository: SQLiteYobiRepository,
) -> None:
    profile = _profile(repository)
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(cuisine_origins=["KOREAN"], max_spice_level=5)
    release_family_id, eligibility_as_of = _active_pin(repository)
    first = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.INITIAL,
        3,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=2,
    )
    assert len(first) == 3
    state = repository.get_session(session.session_id).meal_need_state  # type: ignore[union-attr]
    state.shown_menu_ids = [item.menu_id for item in first]
    with repository._connection() as connection:
        connection.execute(
            "UPDATE chat_session SET meal_need_state_json=? WHERE session_id=?",
            (state.model_dump_json(), session.session_id),
        )

    retry = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.RETRY,
        3,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=2,
    )

    assert retry
    assert {item.menu_id for item in retry}.isdisjoint(state.shown_menu_ids)
    with repository._connection() as connection:
        all_menu_ids = [
            str(row["menu_id"])
            for row in connection.execute(
                "SELECT menu_id FROM menu WHERE availability='AVAILABLE' ORDER BY menu_id"
            ).fetchall()
        ]
        state.shown_menu_ids = all_menu_ids
        connection.execute(
            "UPDATE chat_session SET meal_need_state_json=? WHERE session_id=?",
            (state.model_dump_json(), session.session_id),
        )
    exhausted = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.RETRY,
        3,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=2,
    )
    assert exhausted == []


def test_rankings_and_featured_collections_honor_criteria_and_snapshot_selection(
    repository: SQLiteYobiRepository,
) -> None:
    criteria = RecommendationCriteriaV2(
        price_bands=["UNDER_10000"],
        max_spice_level=5,
    )
    for collection_name in ("ranking", "featured"):
        profile = _profile(repository)
        session = repository.create_session(profile.profile_id)
        committed = _commit(repository, session.session_id, criteria)
        if collection_name == "ranking":
            rankings = {
                sort: repository.list_food_rankings(session.session_id, sort, 20)
                for sort in ("review_count", "order_count", "korean_popularity")
            }
            first = rankings["review_count"]
            replay = repository.list_food_rankings(session.session_id, "review_count", 20)
            menus = [item.menu for item in first.items]
            assert [item.menu.menu_id for item in first.items] == [
                item.menu.menu_id for item in replay.items
            ]
            assert [item.metric_value for item in first.items] == [
                item.metric_value for item in replay.items
            ]
            assert all(1 <= len(collection.items) <= 20 for collection in rankings.values())
            assert all(
                item.metric_value > 0
                for collection in rankings.values()
                for item in collection.items
            )
            assert len({collection.items[0].menu.menu_id for collection in rankings.values()}) == 3
            snapshot_id = first.snapshot_id
            assert "demo" in first.demo_basis.lower()
        else:
            featured = repository.list_kpop_demon_hunters_feature(session.session_id)
            menus = [item.menu for item in featured.items]
            snapshot_id = featured.snapshot_id
            assert all(item.dish_name for item in featured.items)
        assert menus
        assert all(menu.price < 10_000 for menu in menus)

        selected = repository.apply_conversation_event(
            session.session_id,
            ConversationEventInput(
                event_type=ConversationEventType.SELECT_MENU,
                snapshot_id=snapshot_id,
                menu_id=menus[0].menu_id,
                expected_state_version=committed.state_version,
                idempotency_key=f"select-{collection_name}-snapshot-0001",
            ),
        )
        assert selected.selected_menu_id == menus[0].menu_id


def test_sqlite_initialize_adds_server_rank_columns_before_policy_index(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-structured-rank.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE structured_recommendation_request (
              session_id TEXT NOT NULL,
              request_id TEXT NOT NULL,
              request_hash TEXT NOT NULL,
              criteria_version INTEGER NOT NULL,
              mode TEXT NOT NULL,
              status TEXT NOT NULL,
              state_version INTEGER NOT NULL,
              recommendation_release_family_id TEXT NOT NULL,
              eligibility_as_of TEXT NOT NULL,
              snapshot_id TEXT,
              evidence_pool_json TEXT NOT NULL DEFAULT '[]',
              result_json TEXT,
              dispatch_count INTEGER NOT NULL DEFAULT 0,
              failure_code TEXT,
              created_at TEXT NOT NULL,
              dispatched_at TEXT,
              completed_at TEXT,
              PRIMARY KEY(session_id, request_id)
            )
            """
        )

    repository = SQLiteYobiRepository(database_path)
    repository.initialize()

    with repository._connection() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(structured_recommendation_request)"
            ).fetchall()
        }
        indexes = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA index_list(structured_recommendation_request)"
            ).fetchall()
        }
    assert {
        "final_candidates_json",
        "ranking_trace_json",
        "ranking_policy_version",
        "support_manifest_sha256",
        "finalized_at",
    }.issubset(columns)
    assert "idx_rec_request_policy" in indexes


def _profile(repository: SQLiteYobiRepository, **overrides: object):
    values = {
        "consent_demo_data": True,
        "preferred_language": "English",
        **overrides,
    }
    return repository.create_profile(ProfileCreate.model_validate(values))


def _commit(
    repository: SQLiteYobiRepository,
    session_id: str,
    criteria: RecommendationCriteriaV2,
    *,
    request_id: str = "criteria-request-0001",
    expected_state_version: int = 0,
):
    return repository.save_recommendation_criteria(
        session_id,
        RecommendationCriteriaCommit(
            criteria=criteria,
            catalog_version=PREFERENCE_CATALOG_VERSION,
            expected_state_version=expected_state_version,
            request_id=request_id,
        ),
    )


def _active_pin(repository: SQLiteYobiRepository) -> tuple[str, datetime]:
    family = repository.get_active_recommendation_release_family()
    assert family is not None
    return family.release_family_id, datetime.now(timezone.utc)


def test_criteria_and_request_ledger_state_and_idempotency(
    repository: SQLiteYobiRepository,
) -> None:
    profile = _profile(repository)
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        price_bands=["UNDER_10000"],
        max_spice_level=5,
    )

    committed = _commit(repository, session.session_id, criteria)
    assert committed.criteria_version == 1
    assert committed.state_version == 1
    assert repository.get_session(session.session_id).state_version == 1  # type: ignore[union-attr]
    assert _commit(repository, session.session_id, criteria) == committed
    assert repository.get_session(session.session_id).state_version == 1  # type: ignore[union-attr]

    request_input = RecommendationRequestInput(
        request_id="recommendation-request-0001",
        expected_state_version=1,
        criteria_version=1,
    )
    reserved = repository.reserve_recommendation_request(
        session.session_id,
        request_input,
        "request-hash-0001",
    )
    assert reserved.state_version == 1
    assert repository.get_session(session.session_id).state_version == 1  # type: ignore[union-attr]
    duplicate = repository.reserve_recommendation_request(
        session.session_id,
        request_input,
        "request-hash-0001",
    )
    assert duplicate.duplicate is True
    assert duplicate.request_id == reserved.request_id

    with repository._connection() as connection:
        connection.execute(
            """
            INSERT INTO recommendation_release_family(
              release_family_id,knowledge_release_id,catalog_release_id,
              preference_catalog_version,spice_reference_version,
              certification_release_id,embedding_model,embedding_version,status,activated_at
            )
            SELECT 'family-after-reservation',knowledge_release_id,catalog_release_id,
                   preference_catalog_version,spice_reference_version,
                   'certification-release-after-reservation',embedding_model,
                   embedding_version,'ACTIVE',?
            FROM recommendation_release_family WHERE release_family_id=?
            """,
            (datetime.now(timezone.utc).isoformat(), reserved.release_family_id),
        )
        connection.execute(
            """
            UPDATE recommendation_runtime_state
            SET active_release_family_id='family-after-reservation',updated_at=?
            WHERE state_key='ACTIVE'
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
    replay_after_release_change = repository.reserve_recommendation_request(
        session.session_id,
        request_input,
        "request-hash-0001",
    )
    assert replay_after_release_change.duplicate is True
    assert replay_after_release_change.release_family_id == reserved.release_family_id
    assert replay_after_release_change.eligibility_as_of == reserved.eligibility_as_of
    pinned_pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        request_input.mode,
        3,
        release_family_id=reserved.release_family_id,
        eligibility_as_of=reserved.eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert pinned_pool
    assert all(
        item.recommendation_release_family_id == reserved.release_family_id for item in pinned_pool
    )
    repository.mark_recommendation_dispatched(
        session.session_id,
        request_input.request_id,
        pinned_pool,
    )
    completed = repository.complete_recommendation_request(
        session.session_id,
        request_input.request_id,
        RecommendationRequestStatus.SEARCH_FALLBACK,
        result_json={
            "status": "SEARCH_FALLBACK",
            "criteria_summary": "Deterministic fallback",
            "recommendations": [],
            "unmatched_category_codes": [],
        },
        failure_code="GROUNDING_REJECTED",
        grounding_rejection_code="CATEGORY_EVIDENCE_NOT_OWNED",
        grounding_rejection_stage="EVIDENCE_GROUNDING",
        grounding_rejection_detail="matched_criteria.0.evidence_ids:value_error",
    )
    assert completed.ranking_trace_json["grounding_rejection_code"] == (
        "CATEGORY_EVIDENCE_NOT_OWNED"
    )
    assert completed.ranking_trace_json["grounding_rejection_stage"] == ("EVIDENCE_GROUNDING")
    assert completed.ranking_trace_json["grounding_rejection_detail"] == (
        "matched_criteria.0.evidence_ids:value_error"
    )

    with pytest.raises(ValueError, match="PREFERENCE_CATALOG_CHANGED"):
        repository.save_recommendation_criteria(
            session.session_id,
            RecommendationCriteriaCommit(
                criteria=criteria,
                catalog_version="stale-catalog-version",
                expected_state_version=1,
                request_id="criteria-request-0002",
            ),
        )


def test_oracle_completion_persists_the_same_grounding_diagnostic_fields() -> None:
    source = getsource(OracleYobiRepository.complete_recommendation_request)

    assert '"grounding_rejection_code": grounding_rejection_code' in source
    assert '"grounding_rejection_stage": grounding_rejection_stage' in source
    assert '"grounding_rejection_detail": grounding_rejection_detail' in source


def test_legacy_request_rows_receive_additive_release_pin() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE recommendation_runtime_state(
          state_key TEXT PRIMARY KEY,
          active_release_family_id TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE structured_recommendation_request(
          session_id TEXT NOT NULL,
          request_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY(session_id,request_id)
        );
        INSERT INTO recommendation_runtime_state
          VALUES ('ACTIVE','family-migration-pin','now');
        INSERT INTO structured_recommendation_request
          VALUES ('session-old','request-old','2026-08-12T00:00:00+00:00');
        """
    )

    SQLiteYobiRepository._upgrade_structured_request_pin(connection)

    row = connection.execute("SELECT * FROM structured_recommendation_request").fetchone()
    assert row is not None
    assert row["recommendation_release_family_id"] == "family-migration-pin"
    assert row["eligibility_as_of"] == "2026-08-12T00:00:00+00:00"
    SQLiteYobiRepository._upgrade_structured_request_pin(connection)
    assert (
        connection.execute("SELECT COUNT(*) FROM structured_recommendation_request").fetchone()[0]
        == 1
    )
    connection.close()


def test_preference_catalog_exposes_only_supported_reviewed_options(
    repository: SQLiteYobiRepository,
) -> None:
    catalog = repository.get_preference_catalog("ko")
    family = repository.get_active_recommendation_release_family()
    assert family is not None
    assert catalog["knowledge_release_id"] == family.knowledge_release_id
    exposed = {
        option["code"] for category in catalog["categories"] for option in category["options"]
    }
    assert {"SOUTHEAST_ASIAN", "MEXICAN", "WESTERN", "OVER_30000"}.isdisjoint(exposed)
    assert {"KOREAN", "CHINESE", "UNDER_10000"} <= exposed

    with repository._connection() as connection:
        metrics = repository._preference_support_metrics(connection)
    for code in exposed:
        menu_count, merchant_count, wiki_document_count = metrics[code]
        assert menu_count >= 3
        assert merchant_count >= 2
        assert wiki_document_count >= 1


def test_evidence_pool_is_sql_only_public_wiki_and_v2_filters(
    repository: SQLiteYobiRepository,
) -> None:
    recording_provider = RecordingEmbeddingProvider()
    repository.embedding_provider = recording_provider
    profile = _profile(
        repository,
        religion_selection="Islam",
        dietary_rules=["shellfish_allergy", "vegan"],
        allergy_severity="severe",
    )
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        flavors=["SPICY"],
        price_bands=["UNDER_10000"],
        max_spice_level=5,
    )
    release_family_id, eligibility_as_of = _active_pin(repository)
    pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.INITIAL,
        8,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=2,
    )

    assert pool
    assert recording_provider.calls == []
    assert all(len(item.wiki_passages) <= 2 for item in pool)
    assert all(item.menu.price < 10_000 for item in pool)
    assert all(item.spice_reference_country_code is None for item in pool)
    assert all(item.spice_reference_dish_en is None for item in pool)

    family = repository.get_active_recommendation_release_family()
    assert family is not None
    synthetic_release_id = "country-context-test-v1"
    generated_at = datetime.now(timezone.utc).isoformat()
    with repository._connection() as connection:
        connection.execute(
            """
            INSERT INTO synthetic_enrichment_release(
              release_id,catalog_release_id,knowledge_release_id,seed_value,
              generator_version,manifest_sha256,status,created_at,activated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                synthetic_release_id,
                family.catalog_release_id,
                family.knowledge_release_id,
                "country-context-seed",
                "country-context-test",
                "a" * 64,
                "ACTIVE",
                generated_at,
                generated_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO synthetic_country_profile(
              release_id,country_code,spice_baseline,affinity_score,affinity_json
            ) VALUES (?,?,?,?,?)
            """,
            (synthetic_release_id, "KR", 3, 0.5, "{}"),
        )
        connection.execute(
            """
            INSERT INTO synthetic_country_spice_example(
              release_id,country_code,language_code,representative_dish,
              spice_baseline,source_type,seed_hash,generated_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                synthetic_release_id,
                "KR",
                "en",
                "Shin Ramyun",
                3,
                "SYNTHETIC_DEMO",
                "b" * 64,
                generated_at,
            ),
        )
        connection.executemany(
            """
            INSERT INTO synthetic_menu_profile(
              release_id,menu_id,spice_level,halal_fit,vegan_fit,
              source_type,generator_version,seed_hash
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    synthetic_release_id,
                    item.menu.menu_id,
                    3,
                    1,
                    1,
                    "SYNTHETIC_DEMO",
                    "country-context-test",
                    "c" * 64,
                )
                for item in pool
            ],
        )
        connection.execute(
            """
            UPDATE recommendation_release_family
            SET synthetic_enrichment_release_id=?
            WHERE release_family_id=?
            """,
            (synthetic_release_id, family.release_family_id),
        )

    enriched_pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.INITIAL,
        8,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=2,
    )

    assert enriched_pool
    assert all(item.spice_reference_country_code == "KR" for item in enriched_pool)
    assert all(item.spice_reference_dish_en == "Shin Ramyun" for item in enriched_pool)
    assert all(
        {evidence.category_code for evidence in item.criterion_evidence}
        == {"cuisine_origins", "flavors"}
        for item in pool
    )

    passage_ids = {passage.evidence_id for item in pool for passage in item.wiki_passages}
    with repository._connection() as connection:
        rows = connection.execute(
            f"""
            SELECT chunk_id,facet,metadata_json FROM knowledge_chunk
            WHERE chunk_id IN ({",".join("?" for _ in passage_ids)})
            """,
            tuple(passage_ids),
        ).fetchall()
    assert {str(row["chunk_id"]) for row in rows} == passage_ids
    assert all(
        (
            __import__("json").loads(str(row["metadata_json"])).get("recommendation_visibility")
            == "PUBLIC_RAG"
        )
        or (
            "recommendation_visibility" not in __import__("json").loads(str(row["metadata_json"]))
            and str(row["facet"]).lower() != "safety"
        )
        for row in rows
    )

    vegan_pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        RecommendationCriteriaV2(
            dietary_filters={"vegan": True},
            max_spice_level=5,
        ),
        RecommendationMode.INITIAL,
        24,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    # The deterministic demo seed has only PRESENT (not VERIFIED) vegan data.
    # A forced vegan constraint must therefore fail closed instead of upgrading
    # unreviewed source data into a recommendation claim.
    assert vegan_pool == []
    vegan_preview = repository.preview_recommendation(
        session.session_id,
        RecommendationCriteriaV2(
            dietary_filters={"vegan": True},
            max_spice_level=5,
        ),
    )
    assert vegan_preview.zero_reason_codes == ["VEGAN_EVIDENCE_UNAVAILABLE"]

    halal_pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        RecommendationCriteriaV2(
            dietary_filters={"halal_certified_only": True},
            max_spice_level=5,
        ),
        RecommendationMode.INITIAL,
        8,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert halal_pool and all(item.halal_certified is True for item in halal_pool)


def test_live_projection_keeps_current_price_but_removes_unavailable_menu(
    repository: SQLiteYobiRepository,
) -> None:
    profile = _profile(repository)
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(
        cuisine_origins=["KOREAN"],
        price_bands=["UNDER_10000"],
        max_spice_level=5,
    )
    release_family_id, eligibility_as_of = _active_pin(repository)
    pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        RecommendationMode.INITIAL,
        8,
        release_family_id=release_family_id,
        eligibility_as_of=eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert len(pool) >= 2
    repriced, unavailable = pool[:2]
    with repository._connection() as connection:
        connection.execute("UPDATE menu SET price=40000 WHERE menu_id=?", (repriced.menu_id,))
        connection.execute(
            "UPDATE menu SET availability='UNAVAILABLE' WHERE menu_id=?",
            (unavailable.menu_id,),
        )

    states = repository.get_live_recommendation_menu_states(
        session.session_id,
        criteria,
        release_family_id,
        [repriced.menu_id, unavailable.menu_id],
        at=datetime.now(timezone.utc),
    )

    assert states[repriced.menu_id].menu.price == 40_000
    assert unavailable.menu_id not in states


def test_v3_synthetic_halal_candidates_survive_live_revalidation(
    repository: SQLiteYobiRepository,
) -> None:
    profile = _profile(repository)
    session = repository.create_session(profile.profile_id)
    family = repository.get_active_recommendation_release_family()
    assert family is not None
    release_id = "synthetic-live-halal-regression-v1"
    generated_at = datetime.now(timezone.utc).isoformat()
    with repository._connection() as connection:
        menu_rows = connection.execute(
            """
            SELECT DISTINCT menu.menu_id
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            JOIN menu_concept_map mapping
              ON mapping.release_id=family.knowledge_release_id
             AND mapping.mapping_status='MAPPED' AND mapping.confidence_band='high'
            JOIN menu ON menu.menu_id=mapping.menu_id
            WHERE state.state_key='ACTIVE' AND menu.availability='AVAILABLE'
            ORDER BY menu.menu_id LIMIT 2
            """
        ).fetchall()
        assert len(menu_rows) == 2
        halal_menu_id, non_halal_menu_id = (str(row["menu_id"]) for row in menu_rows)
        connection.execute(
            """
            INSERT INTO synthetic_enrichment_release(
              release_id,catalog_release_id,knowledge_release_id,seed_value,
              generator_version,manifest_sha256,status,created_at,activated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                release_id,
                family.catalog_release_id,
                family.knowledge_release_id,
                "regression-seed",
                "regression-generator",
                "a" * 64,
                "ACTIVE",
                generated_at,
                generated_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO synthetic_country_profile(
              release_id,country_code,spice_baseline,affinity_score,affinity_json
            ) VALUES (?,?,?,?,?)
            """,
            (release_id, "US", 3, 0.5, "{}"),
        )
        connection.executemany(
            """
            INSERT INTO synthetic_menu_profile(
              release_id,menu_id,spice_level,halal_fit,vegan_fit,
              source_type,generator_version,seed_hash
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                (
                    release_id,
                    halal_menu_id,
                    3,
                    1,
                    0,
                    "SYNTHETIC_DEMO",
                    "regression-generator",
                    "b" * 64,
                ),
                (
                    release_id,
                    non_halal_menu_id,
                    3,
                    0,
                    0,
                    "SYNTHETIC_DEMO",
                    "regression-generator",
                    "c" * 64,
                ),
            ],
        )
        connection.execute(
            """
            UPDATE recommendation_release_family
            SET synthetic_enrichment_release_id=?
            WHERE release_family_id=?
            """,
            (release_id, family.release_family_id),
        )
    criteria = RecommendationCriteriaV2.model_validate(
        {
            "schema_version": "3",
            "price_range_krw": {"min": 0, "max": 100_000},
            "spice_preference": "SIMILAR",
            "spice_reference_country": "US",
            "dietary_filters": {"halal_certified_only": True},
        }
    )
    eligibility_as_of = datetime.now(timezone.utc)
    states = repository.get_live_recommendation_menu_states(
        session.session_id,
        criteria,
        family.release_family_id,
        [halal_menu_id, non_halal_menu_id],
        at=eligibility_as_of,
    )

    assert set(states) == {halal_menu_id}
    assert states[halal_menu_id].halal_certified is True
    assert {state.halal_scope_label for state in states.values()} == {
        "Synthetic halal-friendly profile"
    }
    _commit(repository, session.session_id, criteria)
    rankings = repository.list_food_rankings(session.session_id, "review_count", 20)
    assert [item.menu.menu_id for item in rankings.items] == [halal_menu_id]


def test_snapshot_completion_revalidates_filters_increments_once_and_hides_audit(
    repository: SQLiteYobiRepository,
) -> None:
    profile = _profile(
        repository,
        religion_selection="Islam",
        dietary_rules=["shellfish_allergy"],
        allergy_severity="severe",
    )
    session = repository.create_session(profile.profile_id)
    criteria = RecommendationCriteriaV2(
        main_ingredients=["PORK"],
        max_spice_level=5,
    )
    committed = _commit(repository, session.session_id, criteria)
    request = RecommendationRequestInput(
        request_id="recommendation-request-0002",
        expected_state_version=committed.state_version,
        criteria_version=committed.criteria_version,
    )
    reserved = repository.reserve_recommendation_request(
        session.session_id,
        request,
        "request-hash-0002",
    )
    pool = repository.build_recommendation_evidence_pool(
        session.session_id,
        profile,
        criteria,
        request.mode,
        24,
        release_family_id=reserved.release_family_id,
        eligibility_as_of=reserved.eligibility_as_of,
        raw_hits_per_value=20,
        passages_per_menu=4,
    )
    assert pool
    dispatched = repository.mark_recommendation_dispatched(
        session.session_id,
        request.request_id,
        pool,
    )
    assert dispatched.dispatch_count == 0
    dispatched = repository.mark_recommendation_provider_called(
        session.session_id,
        request.request_id,
    )
    assert dispatched.dispatch_count == 1
    selected = pool[0]
    unavailable = pool[1]
    with repository._connection() as connection:
        connection.execute(
            "UPDATE menu SET availability='UNAVAILABLE' WHERE menu_id=?",
            (unavailable.menu_id,),
        )
        connection.execute(
            "UPDATE menu SET price=price+321 WHERE menu_id=?",
            (selected.menu_id,),
        )
        current_price = int(
            connection.execute(
                "SELECT price FROM menu WHERE menu_id=?", (selected.menu_id,)
            ).fetchone()[0]
        )

    candidates = [
        RecommendationCandidate(
            menu_id=item.menu_id,
            merchant_id=item.menu.merchant_id,
            rank=rank,
            score=item.retrieval_score,
        )
        for rank, item in enumerate((unavailable, selected), start=1)
    ]
    need_state = repository.get_session(session.session_id).meal_need_state  # type: ignore[union-attr]
    need_state.shown_menu_ids = [item.menu_id for item in (unavailable, selected)]
    snapshot = RecommendationSnapshot(
        snapshot_id="snapshot-structured-0001",
        session_id=session.session_id,
        assistant_message_id="untrusted-shared-message-id",
        state_version=dispatched.state_version + 1,
        meal_need_state=need_state,
        result=RecommendationResult(
            snapshot_id="snapshot-structured-0001",
            candidates=candidates,
            query_summary="Pork dishes",
        ),
        cards=[
            {
                "type": "structured_recommendation",
                "data": {"menu": item.menu.model_dump(mode="json")},
            }
            for item in (unavailable, selected)
        ],
        created_at=datetime.now(timezone.utc),
    )
    result_json = {
        "status": "RECOMMENDED",
        "criteria_summary": "Pork dishes",
        "recommendations": [
            {
                "rank": rank,
                "menu_id": item.menu_id,
                "menu": item.menu.model_dump(mode="json"),
            }
            for rank, item in enumerate((unavailable, selected), start=1)
        ],
        "unmatched_category_codes": [],
    }
    completed = repository.complete_recommendation_request(
        session.session_id,
        request.request_id,
        RecommendationRequestStatus.COMPLETED,
        result_json=result_json,
        snapshot=snapshot,
    )

    assert completed.state_version == committed.state_version + 1
    assert completed.result_json is not None
    assert [item["menu_id"] for item in completed.result_json["recommendations"]] == [
        selected.menu_id
    ]
    assert completed.result_json["recommendations"][0]["menu"]["price"] == current_price
    saved = repository.get_recommendation_snapshot(
        session.session_id,
        completed.snapshot_id,
    )
    assert saved is not None
    assert [item.menu_id for item in saved.result.candidates] == [selected.menu_id]
    assert saved.result.candidates[0].rank == 1
    assert saved.cards[0]["data"]["menu"]["price"] == current_price
    assert unavailable.menu_id not in saved.meal_need_state.shown_menu_ids
    assert repository.list_messages(session.session_id) == []
    with repository._connection() as connection:
        audit = connection.execute(
            """
            SELECT message_id FROM chat_message
            WHERE session_id=? AND message_type='structured_recommendation_audit'
            """,
            (session.session_id,),
        ).fetchone()
    assert audit is not None
    assert str(audit["message_id"]) != snapshot.assistant_message_id

    duplicate = repository.complete_recommendation_request(
        session.session_id,
        request.request_id,
        RecommendationRequestStatus.COMPLETED,
        result_json=result_json,
        snapshot=snapshot,
    )
    assert duplicate.duplicate is True
    assert duplicate.state_version == completed.state_version

    event = repository.apply_conversation_event(
        session.session_id,
        ConversationEventInput(
            event_type=ConversationEventType.SELECT_MENU,
            snapshot_id=saved.snapshot_id,
            menu_id=selected.menu_id,
            expected_state_version=completed.state_version,
            idempotency_key="select-v2-menu-0001",
        ),
    )
    assert event.selected_menu_id == selected.menu_id
    assert event.state_version == completed.state_version + 1


def test_options_api_returns_v2_halal_and_vegan_state_contract(
    repository: SQLiteYobiRepository,
) -> None:
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        with TestClient(app) as client:
            certified_response = client.get("/api/v1/menus/menu_001_01/options")
            uncertified_response = client.get("/api/v1/menus/menu_059_01/options")
    finally:
        app.dependency_overrides.clear()

    assert certified_response.status_code == 200
    certified_items = {
        item["option_item_id"]: item
        for group in certified_response.json()
        for item in group["items"]
    }
    assert certified_items
    for item in certified_items.values():
        assert {
            "halal_certification_preserved",
            "vegan_status",
            "vegan_warning",
        } <= item.keys()
        assert item["halal_certification_preserved"] is True
        assert item["vegan_status"] in {
            "LIKELY_FIT",
            "POSSIBLE_WITH_CHECKS",
            "CONFLICT",
            "UNKNOWN",
            None,
        }

    cheese_add = certified_items["oi_001_01_cheese_add"]
    fishcake_keep = certified_items["oi_001_01_fishcake_keep"]
    assert cheese_add["vegan_status"] == "CONFLICT"
    assert fishcake_keep["vegan_status"] == "CONFLICT"
    assert "adds a confirmed animal-derived ingredient" in cheese_add["vegan_warning"]

    # Removing one ingredient keeps this menu's base conflict; it must not be
    # upgraded to a vegan-safe claim from the option effect alone.
    assert certified_items["oi_001_01_cheese_none"]["vegan_status"] == "CONFLICT"
    assert certified_items["oi_001_01_fishcake_remove"]["vegan_status"] == "CONFLICT"

    assert uncertified_response.status_code == 200
    uncertified_items = [
        item for group in uncertified_response.json() for item in group["items"]
    ]
    assert uncertified_items
    assert all(item["halal_certification_preserved"] is None for item in uncertified_items)
    assert all(item["halal_certification_preserved"] is not False for item in uncertified_items)


def test_options_api_precomputed_mode_bypasses_runtime_model_localization(
    repository: SQLiteYobiRepository,
) -> None:
    class PrecomputedLocalization:
        calls: list[tuple[str, str | None, bool]] = []

        def get_options(
            self,
            menu_id: str,
            session_id: str | None,
            *,
            precomputed_only: bool = False,
        ) -> list[object]:
            self.calls.append((menu_id, session_id, precomputed_only))
            assert precomputed_only is True
            return []

    service = PrecomputedLocalization()

    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_option_localization_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/menus/menu_001_01/options?precomputed_only=true"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []
    assert service.calls == [("menu_001_01", None, True)]
