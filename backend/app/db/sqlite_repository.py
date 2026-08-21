from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Literal, cast
from uuid import uuid4

from app.country_spice_examples import effective_language, representative_dish
from app.db.browse_rankings import food_ranking_sql
from app.db.concept_query import (
    build_candidate_recall_channel_query,
    build_concept_candidate_query,
    build_concept_preview_count_query,
    build_semantic_candidate_query,
)
from app.db.demo_address import demo_address_status
from app.db.message_ordering import order_conversation_messages
from app.db.schema_sqlite import SCHEMA_SQL
from app.db.seed_data import CATALOG_VERSION, build_seed
from app.domain.address import normalize_address_text
from app.domain.concept_ranking import (
    RANKING_POLICY_SHA256,
    RANKING_POLICY_VERSION,
    ConceptRankCandidate,
    bayesian_review_prior,
    candidate_channel_fusion_trace,
    merge_candidate_channels,
    rank_concept_candidates,
)
from app.domain.dialogue import (
    ConstraintStrictness,
    ConversationEventInput,
    ConversationEventResult,
    ConversationEventType,
    DialogueAct,
    MealNeedState,
    RecommendationCandidate,
    RecommendationResult,
    RecommendationSnapshot,
)
from app.domain.dietary import apply_profile_constraints, known_allergen_conflicts
from app.domain.knowledge import (
    ClaimStatus,
    GroundedMenuKnowledge,
    GroundedPassage,
    IngredientRole,
    KnowledgeSourceKind,
    SourceScope,
)
from app.domain.models import (
    AddressCandidate,
    AssistantTurn,
    CartItemInput,
    CartItemUpdate,
    CartLine,
    CartPreview,
    ChatState,
    Checkout,
    CheckoutCreate,
    DeliveryPreferenceInput,
    Evidence,
    EvidenceStatus,
    MenuPresentationCacheEntry,
    MenuSummary,
    MerchantComparison,
    MerchantMenuPresentation,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
    OptionGroup,
    OptionItem,
    Order,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    RestaurantNoteTranslation,
    Session,
)
from app.domain.preference_catalog import (
    PREFERENCE_CATALOG_VERSION,
    PREFERENCE_CATEGORIES,
    localized_preference_catalog,
    localized_spice_references,
    normalize_preference_locale,
    preference_option_is_exposable,
    preference_query_aliases,
)
from app.domain.recommendation import (
    operational_menu_signal,
    rerank_menu_candidates,
    wiki_operational_retrieval_score,
)
from app.domain.recommendation_copy import deterministic_presentation_copy
from app.domain.structured_recommendation import (
    CriterionEvidence,
    EvidencePoolItem,
    EvidenceReference,
    FeaturedMenuCollection,
    FeaturedMenuEntry,
    FoodRankingCollection,
    FoodRankingEntry,
    FoodRankingSort,
    LiveRecommendationMenuState,
    RecommendationCriteriaCommit,
    RecommendationCriteriaRecord,
    RecommendationCriteriaV2,
    RecommendationMode,
    RecommendationPreviewV2,
    RecommendationReleaseFamily,
    RecommendationRequestInput,
    RecommendationRequestRecord,
    RecommendationRequestStatus,
)
from app.knowledge.catalog_seed import (
    KNOWLEDGE_CATALOG_VERSION,
    KNOWLEDGE_RELEASE_ID,
    build_knowledge_catalog_seed,
)
from app.knowledge.menu_features import MEMBERSHIP_EXTRACTOR_VERSION
from app.knowledge.menu_features import (
    feature_manifest_sha256 as menu_feature_manifest_sha256,
)
from app.knowledge.passage_ranking import rank_component_wiki_passages
from app.knowledge.preference_support import (
    REVIEWED_CUISINE_ORIGIN_CODES,
    SUPPORT_MANIFEST_FIELDS,
    build_synthetic_support_rows,
    preference_alias_matches,
    support_manifest_sha256,
)
from app.knowledge.resolver import (
    VEGAN_INGREDIENTS,
    allergen_constraint_conflicts,
    category_constraint_conflicts,
    confirmed_allergen_absence_signals,
    ingredient_constraint_conflicts,
    merchant_cross_contact_conflicts,
    resolve_allergen_claims,
    resolve_dietary_claims,
    resolve_ingredient_claims,
    resolve_merchant_ingredient_claims,
    resolve_preparation_claims,
    severe_allergy_conflicts,
)
from app.knowledge.sqlite_store import load_sqlite_release
from app.rag.embeddings import (
    FALLBACK_RECOMMENDATION_QUERY_ALIASES,
    HybridChunkCandidate,
    apply_soft_profile_retrieval_signal,
    cosine_similarity,
    deterministic_embedding,
    deterministic_sparse_embedding,
    hybrid_knowledge_chunk_score,
    rank_hybrid_chunks_rrf,
    sparse_cosine_similarity,
)
from app.rag.providers import DeterministicEmbeddingProvider

# The demo corpus is intentionally bounded at 600 menus. Keep every hard-filtered
# candidate until the structured-preference reranker has applied its 25% share;
# truncating at 40 here can create false empty results for party budgets and drop the
# best sensory match before the final 60/25/15 score exists.
RECOMMENDATION_CANDIDATE_CAP = 600
RECOMMENDATION_PASSAGE_LIMIT = 3
EXPECTED_MAPPED_MENUS = 600
EXPECTED_ORIGIN_DECLARATIONS = 13
EXPECTED_MERCHANT_INGREDIENTS = 120
EXPECTED_OPTION_EFFECTS = 4
EXPECTED_RUNTIME_COUNTS = {
    "service_area": 3,
    "menu_category": 100,
    "merchant": 60,
    "menu": 600,
    "menu_knowledge": 600,
    "menu_option_group": 1202,
    "menu_option_item": 2405,
    "review_snippet": 2400,
    "evidence": 1200,
    "address_place": 20,
    "ingredient": 48,
    "menu_ingredient": 565,
    "allergen": 8,
    "menu_allergen": 48,
    "dietary_attribute": 15,
    "menu_dietary_attribute": 1217,
    "option_dietary_conflict": 1,
}
EXTERNAL_CATALOG_COUNT_TABLES = (
    "catalog_source_payload",
    "menu",
    "menu_option_group",
    "menu_option_item",
    "menu_source_detail",
    "menu_source_section",
    "menu_source_section_item",
    "merchant",
    "merchant_source_detail",
    "option_group_source_detail",
    "source_option",
)
UPGRADE_RETAINED_RUNTIME_COUNT_KEYS = frozenset(
    {"allergen", "dietary_attribute", "ingredient", "menu_allergen"}
)


def _runtime_counts_compatible(counts: dict[str, int]) -> bool:
    return set(counts) == set(EXPECTED_RUNTIME_COUNTS) and all(
        actual >= expected if key in UPGRADE_RETAINED_RUNTIME_COUNT_KEYS else actual == expected
        for key, expected in EXPECTED_RUNTIME_COUNTS.items()
        for actual in (counts[key],)
    )


SPICE_REFERENCE_VERSION = f"{PREFERENCE_CATALOG_VERSION}-spice"
CERTIFICATION_RELEASE_ID = "synthetic-halal-certifications-v1"
RECOMMENDATION_RELEASE_FAMILY_PREFIX = "structured-rag-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _catalog_text(value: object, fallback: object = "") -> str:
    return str(value) if value not in (None, "") else str(fallback or "")


def _optional_int(value: object) -> int | None:
    return None if value is None else int(cast(Any, value))


def _cart_fingerprint(cart_id: str, cart_version: int, total: int) -> str:
    return hashlib.sha256(f"{cart_id}:{cart_version}:{total}".encode()).hexdigest()


class SQLiteYobiRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.embedding_provider = DeterministicEmbeddingProvider()
        self._recommendation_retrieval_metrics: dict[str, dict[str, Any]] = {}

    def get_recommendation_retrieval_metrics(self, session_id: str) -> dict[str, Any]:
        return dict(self._recommendation_retrieval_metrics.get(session_id, {}))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(SCHEMA_SQL)
            self._upgrade_spice_constraints(connection)
            # Recreate indexes dropped by a legacy table rebuild and pick up any
            # additive v2 tables on an existing SQLite database.
            connection.executescript(SCHEMA_SQL)
            merchant_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(merchant)").fetchall()
            }
            if "service_area_id" not in merchant_columns:
                connection.execute("ALTER TABLE merchant ADD COLUMN service_area_id TEXT")
            for column, definition in (
                ("catalog_import_id", "TEXT"),
                ("data_origin", "TEXT"),
                ("source_platform", "TEXT"),
                ("source_merchant_id", "TEXT"),
                ("source_collected_at", "TEXT"),
            ):
                if column not in merchant_columns:
                    connection.execute(f"ALTER TABLE merchant ADD COLUMN {column} {definition}")
            menu_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(menu)").fetchall()
            }
            if "category_id" not in menu_columns:
                connection.execute("ALTER TABLE menu ADD COLUMN category_id TEXT")
            for column, definition in (
                ("catalog_import_id", "TEXT"),
                ("data_origin", "TEXT"),
                ("source_platform", "TEXT"),
                ("source_menu_id", "TEXT"),
                ("source_section_id", "TEXT"),
                ("name_en_status", "TEXT"),
                ("cultural_description_status", "TEXT"),
                ("serves_status", "TEXT"),
                ("spice_status", "TEXT"),
                ("dietary_data_status", "TEXT"),
            ):
                if column not in menu_columns:
                    connection.execute(f"ALTER TABLE menu ADD COLUMN {column} {definition}")
            group_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(menu_option_group)").fetchall()
            }
            for column, definition in (
                ("catalog_import_id", "TEXT"),
                ("source_option_group_id", "TEXT"),
                ("normalization_code", "TEXT"),
            ):
                if column not in group_columns:
                    connection.execute(
                        f"ALTER TABLE menu_option_group ADD COLUMN {column} {definition}"
                    )
            item_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(menu_option_item)").fetchall()
            }
            for column, definition in (
                ("catalog_import_id", "TEXT"),
                ("source_option_item_key", "TEXT"),
            ):
                if column not in item_columns:
                    connection.execute(
                        f"ALTER TABLE menu_option_item ADD COLUMN {column} {definition}"
                    )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_merchant_catalog_import "
                "ON merchant(catalog_import_id,data_origin)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_menu_catalog_import "
                "ON menu(catalog_import_id,merchant_id,availability)"
            )
            address_place_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(address_place)").fetchall()
            }
            if "service_area_id" not in address_place_columns:
                connection.execute("ALTER TABLE address_place ADD COLUMN service_area_id TEXT")
            address_ref_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(address_ref)").fetchall()
            }
            if "service_area_id" not in address_ref_columns:
                connection.execute("ALTER TABLE address_ref ADD COLUMN service_area_id TEXT")
            cart_item_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(cart_item)").fetchall()
            }
            if "agent_request_key" not in cart_item_columns:
                connection.execute("ALTER TABLE cart_item ADD COLUMN agent_request_key TEXT")
            if "note_translation_id" not in cart_item_columns:
                connection.execute("ALTER TABLE cart_item ADD COLUMN note_translation_id TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_cart_agent_request "
                "ON cart_item(agent_request_key)"
            )
            checkout_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(mock_checkout)").fetchall()
            }
            for column, definition in (
                ("cart_version", "INTEGER"),
                ("cart_fingerprint", "TEXT"),
            ):
                if column not in checkout_columns:
                    connection.execute(
                        f"ALTER TABLE mock_checkout ADD COLUMN {column} {definition}"
                    )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_checkout_cart_version "
                "ON mock_checkout(cart_id,cart_version)"
            )
            cart_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(cart)").fetchall()
            }
            if "confirmed_fingerprint" not in cart_columns:
                connection.execute("ALTER TABLE cart ADD COLUMN confirmed_fingerprint TEXT")
            session_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(chat_session)").fetchall()
            }
            for column, definition in (
                ("meal_need_state_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("dialogue_act", "TEXT NOT NULL DEFAULT 'COLLECT_NEEDS'"),
                ("state_version", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if column not in session_columns:
                    connection.execute(f"ALTER TABLE chat_session ADD COLUMN {column} {definition}")
            profile_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(user_profile)").fetchall()
            }
            if "country_code" not in profile_columns:
                connection.execute("ALTER TABLE user_profile ADD COLUMN country_code TEXT")
            presentation_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(menu_presentation_cache)"
                ).fetchall()
            }
            for column, definition in (
                ("localized_subtitle", "TEXT"),
                ("prompt_version", "TEXT"),
                ("content_schema_version", "TEXT"),
                ("evidence_map_json", "TEXT"),
                ("personalization_applied", "INTEGER"),
                ("updated_at", "TEXT"),
            ):
                if column not in presentation_columns:
                    connection.execute(
                        f"ALTER TABLE menu_presentation_cache ADD COLUMN {column} {definition}"
                    )
            provider_attempt_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(recommendation_provider_attempt)"
                ).fetchall()
            }
            if "attempt_role" not in provider_attempt_columns:
                connection.execute(
                    "ALTER TABLE recommendation_provider_attempt "
                    "ADD COLUMN attempt_role TEXT NOT NULL DEFAULT 'SELECTION'"
                )
            snapshot_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(recommendation_snapshot)"
                ).fetchall()
            }
            for column, definition in (
                ("structured_request_id", "TEXT"),
                ("criteria_version", "INTEGER"),
                ("criteria_json", "TEXT"),
                ("criteria_hash", "TEXT"),
                ("recommendation_release_family_id", "TEXT"),
                ("evidence_pool_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("generation_status", "TEXT"),
                ("generation_call_count", "INTEGER NOT NULL DEFAULT 0"),
                ("grounding_validation_json", "TEXT"),
                ("ranking_trace_json", "TEXT"),
                ("ranking_policy_version", "TEXT"),
                ("support_manifest_sha256", "TEXT"),
                ("feature_manifest_sha256", "TEXT"),
            ):
                if column not in snapshot_columns:
                    connection.execute(
                        f"ALTER TABLE recommendation_snapshot ADD COLUMN {column} {definition}"
                    )
            self._upgrade_structured_server_rank(connection)
            self._ensure_wiki_eligibility(connection)
            external_catalog = connection.execute(
                """
                SELECT catalog_import_id FROM catalog_import_batch
                WHERE status='ACTIVE' AND data_origin='YOGIYO_PUBLIC_WEB'
                ORDER BY completed_at DESC LIMIT 1
                """
            ).fetchone()
            if external_catalog is not None:
                return
            existing = connection.execute("SELECT COUNT(*) FROM merchant").fetchone()[0]
            seed = build_seed()
            if existing:
                self._backfill_normalized_catalog(connection, seed)
                self._prune_stale_catalog_dimensions(connection, seed)
                self._load_knowledge_catalog(connection, seed)
                self._ensure_structured_recommendation_data(connection)
                self._ensure_wiki_eligibility(connection)
                self._upgrade_structured_request_pin(connection)
                return
            self._insert_rows(connection, "service_area", seed["service_areas"])
            self._insert_rows(connection, "menu_category", seed["menu_categories"])
            self._insert_rows(connection, "merchant", seed["merchants"])
            self._insert_rows(connection, "menu", seed["menus"])
            self._insert_rows(connection, "menu_knowledge", seed["knowledge"])
            self._insert_rows(connection, "evidence", seed["evidence"])
            self._insert_rows(connection, "review_snippet", seed["reviews"])
            self._insert_rows(connection, "menu_option_group", seed["option_groups"])
            self._insert_rows(connection, "menu_option_item", seed["option_items"])
            self._insert_rows(connection, "ingredient", seed["ingredients"])
            self._insert_rows(connection, "menu_ingredient", seed["menu_ingredients"])
            self._insert_rows(connection, "allergen", seed["allergens"])
            self._insert_rows(connection, "menu_allergen", seed["menu_allergens"])
            self._insert_rows(connection, "dietary_attribute", seed["dietary_attributes"])
            self._insert_rows(connection, "menu_dietary_attribute", seed["menu_dietary_attributes"])
            self._insert_rows(
                connection, "option_dietary_conflict", seed["option_dietary_conflicts"]
            )
            self._insert_rows(connection, "address_place", seed["hotels"])
            self._load_knowledge_catalog(connection, seed)
            self._ensure_structured_recommendation_data(connection)
            self._ensure_wiki_eligibility(connection)
            self._upgrade_structured_request_pin(connection)

    @staticmethod
    def _ensure_wiki_eligibility(connection: sqlite3.Connection) -> None:
        """Compile immutable reviewed-Wiki menu eligibility once per release."""

        release_rows = connection.execute(
            """
            SELECT DISTINCT membership.knowledge_release_id
            FROM menu_concept_membership membership
            WHERE NOT EXISTS (
              SELECT 1 FROM menu_wiki_eligibility eligibility
              WHERE eligibility.knowledge_release_id=membership.knowledge_release_id
            )
            ORDER BY membership.knowledge_release_id
            """
        ).fetchall()
        for row in release_rows:
            release_id = str(row[0])
            connection.execute(
                """
                INSERT OR IGNORE INTO menu_wiki_eligibility (
                  knowledge_release_id,menu_id,reviewed_chunk_count,compiled_at
                )
                SELECT reviewed.release_id,membership.menu_id,
                       COUNT(DISTINCT reviewed.chunk_id),datetime('now')
                FROM (
                  SELECT chunk.release_id,chunk.chunk_id,
                         closure.descendant_concept_id
                  FROM knowledge_chunk chunk
                  JOIN knowledge_document document
                    ON document.release_id=chunk.release_id
                   AND document.document_id=chunk.document_id
                  JOIN dish_concept_closure closure
                    ON closure.release_id=chunk.release_id
                   AND closure.ancestor_concept_id=chunk.concept_id
                   AND closure.inherit_claims=1
                  WHERE chunk.release_id=?
                    AND document.source_type='SYNTHETIC_WIKI'
                    AND document.review_status='REVIEWED_DEMO'
                    AND lower(chunk.facet)<>'safety'
                    AND (
                      json_extract(
                        chunk.metadata_json,'$.recommendation_visibility'
                      )='PUBLIC_RAG'
                      OR json_extract(
                        chunk.metadata_json,'$.recommendation_visibility'
                      ) IS NULL
                    )
                ) reviewed
                JOIN menu_concept_membership membership
                  ON membership.knowledge_release_id=reviewed.release_id
                 AND membership.concept_id=reviewed.descendant_concept_id
                GROUP BY reviewed.release_id,membership.menu_id
                """,
                (release_id,),
            )

    @staticmethod
    def _upgrade_spice_constraints(connection: sqlite3.Connection) -> None:
        """Rebuild only legacy 1..3 tables so reviewed v2 values up to 5 can be stored."""

        rebuilds = {
            "menu": ("spice_level BETWEEN 1 AND 3", "spice_level BETWEEN 1 AND 5"),
        }
        schemas = {
            table: connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            for table in rebuilds
        }
        if not any(row and rebuilds[table][0] in str(row[0]) for table, row in schemas.items()):
            return

        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA legacy_alter_table = ON")
        try:
            for table, (old_check, new_check) in rebuilds.items():
                schema_row = schemas[table]
                if schema_row is None or old_check not in str(schema_row[0]):
                    continue
                old_table = f"{table}_legacy_spice_3"
                create_sql = str(schema_row[0]).replace(old_check, new_check)
                connection.execute(f"ALTER TABLE {table} RENAME TO {old_table}")
                connection.execute(create_sql)
                columns = [
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({old_table})").fetchall()
                ]
                column_list = ",".join(columns)
                connection.execute(
                    f"INSERT INTO {table} ({column_list}) SELECT {column_list} FROM {old_table}"
                )
                connection.execute(f"DROP TABLE {old_table}")
            connection.commit()
        finally:
            connection.execute("PRAGMA legacy_alter_table = OFF")
            connection.execute("PRAGMA foreign_keys = ON")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError("SQLITE_SPICE_UPGRADE_FOREIGN_KEY_VIOLATION")

    @staticmethod
    def _upgrade_structured_server_rank(connection: sqlite3.Connection) -> None:
        zero_hash = "0" * 64
        family_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(recommendation_release_family)"
            ).fetchall()
        }
        for column, definition in (
            ("support_manifest_sha256", f"TEXT NOT NULL DEFAULT '{zero_hash}'"),
            ("feature_manifest_sha256", f"TEXT NOT NULL DEFAULT '{zero_hash}'"),
            ("ranking_policy_version", "TEXT NOT NULL DEFAULT 'legacy-llm-rank-v2'"),
            ("ranking_policy_sha256", f"TEXT NOT NULL DEFAULT '{zero_hash}'"),
            ("synthetic_enrichment_release_id", "TEXT"),
        ):
            if column not in family_columns:
                connection.execute(
                    f"ALTER TABLE recommendation_release_family ADD COLUMN {column} {definition}"
                )

        request_columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(structured_recommendation_request)"
            ).fetchall()
        }
        for column, definition in (
            ("final_candidates_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("ranking_trace_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("ranking_policy_version", "TEXT NOT NULL DEFAULT 'legacy-llm-rank-v2'"),
            ("support_manifest_sha256", f"TEXT NOT NULL DEFAULT '{zero_hash}'"),
            ("feature_manifest_sha256", f"TEXT NOT NULL DEFAULT '{zero_hash}'"),
            ("finalized_at", "TEXT"),
            ("client_cancelled_at", "TEXT"),
        ):
            if column not in request_columns:
                connection.execute(
                    f"ALTER TABLE structured_recommendation_request ADD COLUMN {column} {definition}"
                )
        for statement in (
            "CREATE INDEX IF NOT EXISTS idx_concept_pref_lookup ON "
            "concept_preference_support(knowledge_release_id,category_code,option_code,"
            "support_status,concept_id)",
            "CREATE INDEX IF NOT EXISTS idx_concept_pref_concept ON "
            "concept_preference_support(knowledge_release_id,concept_id,support_status)",
            "CREATE INDEX IF NOT EXISTS idx_menu_concept_high ON "
            "menu_concept_map(release_id,mapping_status,confidence_band,concept_id,menu_id)",
            "CREATE INDEX IF NOT EXISTS idx_menu_recommend_filter ON "
            "menu(availability,price,merchant_id,menu_id)",
            "CREATE INDEX IF NOT EXISTS idx_menu_source_restrict ON "
            "menu_source_detail(liquor,is_adult,verified_adult,soldout,menu_id)",
            "CREATE INDEX IF NOT EXISTS idx_rec_request_policy ON "
            "structured_recommendation_request(session_id,ranking_policy_version,status,created_at)",
            "CREATE INDEX IF NOT EXISTS idx_rec_request_cancelled ON "
            "structured_recommendation_request(session_id,client_cancelled_at,created_at)",
        ):
            connection.execute(statement)

    @staticmethod
    def _upgrade_structured_request_pin(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(structured_recommendation_request)"
            ).fetchall()
        }
        for column, definition in (
            ("recommendation_release_family_id", "TEXT"),
            ("eligibility_as_of", "TEXT"),
        ):
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE structured_recommendation_request "
                    f"ADD COLUMN {column} {definition}"
                )
        active = connection.execute(
            """
            SELECT active_release_family_id FROM recommendation_runtime_state
            WHERE state_key='ACTIVE'
            """
        ).fetchone()
        if active is None:
            return
        connection.execute(
            """
            UPDATE structured_recommendation_request
            SET recommendation_release_family_id=COALESCE(
                  recommendation_release_family_id,?
                ),
                eligibility_as_of=COALESCE(eligibility_as_of,created_at)
            WHERE recommendation_release_family_id IS NULL OR eligibility_as_of IS NULL
            """,
            (str(active["active_release_family_id"]),),
        )

    @classmethod
    def _ensure_structured_recommendation_data(cls, connection: sqlite3.Connection) -> None:
        active = connection.execute(
            """
            SELECT release.release_id,release.embedding_model,release.embedding_version
            FROM knowledge_runtime_state state
            JOIN knowledge_release release ON release.release_id=state.active_release_id
            WHERE state.state_key='ACTIVE' AND release.status='READY'
            """
        ).fetchone()
        if active is None:
            return
        knowledge_release_id = str(active["release_id"])
        now = _now()
        support_manifest_sha256 = cls._ensure_synthetic_concept_support(
            connection,
            knowledge_release_id=knowledge_release_id,
            updated_at=now,
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO menu_concept_membership(
              knowledge_release_id,menu_id,concept_id,membership_role,confidence,
              provenance_type,source_ref,review_status,extractor_version,
              is_synthetic,updated_at
            )
            SELECT release_id,menu_id,concept_id,'PRIMARY',1.0,source_type,source_ref,
                   review_status,?,is_synthetic,updated_at
            FROM menu_concept_map
            WHERE release_id=? AND mapping_status='MAPPED' AND concept_id IS NOT NULL
            """,
            (MEMBERSHIP_EXTRACTOR_VERSION, knowledge_release_id),
        )
        membership_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT knowledge_release_id,menu_id,concept_id,membership_role,confidence,
                       provenance_type,source_ref,review_status,extractor_version,is_synthetic
                FROM menu_concept_membership
                WHERE knowledge_release_id=? ORDER BY menu_id,concept_id
                """,
                (knowledge_release_id,),
            ).fetchall()
        ]
        # Preference exposure now reads the same materialized Wiki eligibility
        # used by retrieval. Compile it immediately after memberships exist;
        # waiting until initialize() returns would incorrectly hide every chip
        # during a fresh database bootstrap.
        cls._ensure_wiki_eligibility(connection)
        feature_manifest_sha256 = menu_feature_manifest_sha256([], [], membership_rows)
        family_identity = {
            "knowledge_release_id": knowledge_release_id,
            "catalog_release_id": CATALOG_VERSION,
            "preference_catalog_version": PREFERENCE_CATALOG_VERSION,
            "spice_reference_version": SPICE_REFERENCE_VERSION,
            "certification_release_id": CERTIFICATION_RELEASE_ID,
            "embedding_model": str(active["embedding_model"]),
            "embedding_version": str(active["embedding_version"]),
            "support_manifest_sha256": support_manifest_sha256,
            "feature_manifest_sha256": feature_manifest_sha256,
            "ranking_policy_version": RANKING_POLICY_VERSION,
            "ranking_policy_sha256": RANKING_POLICY_SHA256,
        }
        family_seed = (
            f"{RECOMMENDATION_RELEASE_FAMILY_PREFIX}:"
            f"{hashlib.sha256(json.dumps(family_identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:24]}"
        )
        active_enriched_family = connection.execute(
            """
            SELECT family.release_family_id
            FROM recommendation_runtime_state state
            JOIN recommendation_release_family family
              ON family.release_family_id=state.active_release_family_id
            JOIN synthetic_enrichment_release enrichment
              ON enrichment.release_id=family.synthetic_enrichment_release_id
            WHERE state.state_key='ACTIVE'
              AND enrichment.status='ACTIVE'
              AND family.knowledge_release_id=?
              AND family.catalog_release_id=?
              AND family.preference_catalog_version=?
              AND family.spice_reference_version=?
              AND family.certification_release_id=?
              AND family.embedding_model=?
              AND family.embedding_version=?
              AND family.support_manifest_sha256=?
              AND family.feature_manifest_sha256=?
              AND family.ranking_policy_version=?
              AND family.ranking_policy_sha256=?
            """,
            (
                knowledge_release_id,
                CATALOG_VERSION,
                PREFERENCE_CATALOG_VERSION,
                SPICE_REFERENCE_VERSION,
                CERTIFICATION_RELEASE_ID,
                str(active["embedding_model"]),
                str(active["embedding_version"]),
                support_manifest_sha256,
                feature_manifest_sha256,
                RANKING_POLICY_VERSION,
                RANKING_POLICY_SHA256,
            ),
        ).fetchone()
        active_family_id = (
            str(active_enriched_family["release_family_id"])
            if active_enriched_family is not None
            else family_seed
        )
        connection.execute(
            """
            UPDATE recommendation_release_family SET status='READY'
            WHERE status='ACTIVE' AND release_family_id<>?
            """,
            (active_family_id,),
        )
        connection.execute(
            """
            INSERT INTO recommendation_release_family(
              release_family_id,knowledge_release_id,catalog_release_id,
              preference_catalog_version,spice_reference_version,
              certification_release_id,embedding_model,embedding_version,
              support_manifest_sha256,feature_manifest_sha256,
              ranking_policy_version,ranking_policy_sha256,
              status,activated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(release_family_id) DO UPDATE SET
              status=excluded.status,activated_at=excluded.activated_at
            """,
            (
                family_seed,
                knowledge_release_id,
                CATALOG_VERSION,
                PREFERENCE_CATALOG_VERSION,
                SPICE_REFERENCE_VERSION,
                CERTIFICATION_RELEASE_ID,
                str(active["embedding_model"]),
                str(active["embedding_version"]),
                support_manifest_sha256,
                feature_manifest_sha256,
                RANKING_POLICY_VERSION,
                RANKING_POLICY_SHA256,
                "ACTIVE" if active_family_id == family_seed else "READY",
                now,
            ),
        )
        connection.execute(
            "UPDATE recommendation_release_family SET status='ACTIVE' WHERE release_family_id=?",
            (active_family_id,),
        )
        connection.execute(
            """
            INSERT INTO recommendation_runtime_state(state_key,active_release_family_id,updated_at)
            VALUES ('ACTIVE',?,?)
            ON CONFLICT(state_key) DO UPDATE SET
              active_release_family_id=excluded.active_release_family_id,
              updated_at=excluded.updated_at
            """,
            (active_family_id, now),
        )

        supported_preference_codes = cls._supported_preference_codes(connection)
        preference_rows: list[tuple[Any, ...]] = []
        for category in PREFERENCE_CATEGORIES:
            for display_order, option in enumerate(category.options):
                preference_rows.append(
                    (
                        PREFERENCE_CATALOG_VERSION,
                        category.code,
                        option.code,
                        option.labels["ko"],
                        option.labels["en"],
                        json.dumps(option.query_aliases, ensure_ascii=False),
                        display_order,
                        int(option.code in supported_preference_codes),
                    )
                )
        connection.executemany(
            """
            INSERT INTO recommendation_preference_option(
              catalog_version,category_code,option_code,label_ko,label_en,
              query_aliases_json,display_order,active
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(catalog_version,category_code,option_code) DO UPDATE SET
              label_ko=excluded.label_ko,label_en=excluded.label_en,
              query_aliases_json=excluded.query_aliases_json,
              display_order=excluded.display_order,active=excluded.active
            """,
            preference_rows,
        )
        ko_spice = {str(item["country"]): item for item in localized_spice_references("ko")}
        en_spice = {str(item["country"]): item for item in localized_spice_references("en")}
        spice_rows: list[tuple[Any, ...]] = []
        for country in ("KR", "US"):
            ko_levels = {
                int(str(item["level"])): item
                for item in cast(list[dict[str, object]], ko_spice[country]["levels"])
            }
            en_levels = {
                int(str(item["level"])): item
                for item in cast(list[dict[str, object]], en_spice[country]["levels"])
            }
            for level in range(1, 6):
                spice_rows.append(
                    (
                        SPICE_REFERENCE_VERSION,
                        country,
                        level,
                        str(ko_levels[level]["label"]),
                        str(en_levels[level]["label"]),
                        str(ko_levels[level]["example"]),
                        str(en_levels[level]["example"]),
                    )
                )
        connection.executemany(
            """
            INSERT INTO spice_reference(
              reference_version,country_code,spice_level,label_ko,label_en,example_ko,example_en
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(reference_version,country_code,spice_level) DO UPDATE SET
              label_ko=excluded.label_ko,label_en=excluded.label_en,
              example_ko=excluded.example_ko,example_en=excluded.example_en
            """,
            spice_rows,
        )

        merchant_ids = [
            str(row["merchant_id"])
            for row in connection.execute(
                "SELECT merchant_id FROM merchant ORDER BY merchant_id LIMIT 18"
            ).fetchall()
        ]
        connection.executemany(
            """
            INSERT INTO merchant_certification(
              certification_id,certification_release_id,merchant_id,certification_type,status,
              issuer,certificate_number,valid_from,valid_to,scope_type,scope_ref,
              source_type,source_ref,last_verified_at,is_synthetic
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(certification_id) DO UPDATE SET
              status=excluded.status,valid_from=excluded.valid_from,valid_to=excluded.valid_to,
              last_verified_at=excluded.last_verified_at
            """,
            [
                (
                    f"cert_demo_halal_{merchant_id}",
                    CERTIFICATION_RELEASE_ID,
                    merchant_id,
                    "HALAL",
                    "ACTIVE",
                    "YOBI demo certification fixture",
                    f"DEMO-{merchant_id.upper()}",
                    "2026-01-01T00:00:00+00:00",
                    "2099-12-31T23:59:59+00:00",
                    "MERCHANT",
                    None,
                    "DEMO_SEED",
                    f"synthetic-assumption:{merchant_id}",
                    now,
                    1,
                )
                for merchant_id in merchant_ids
            ],
        )

    @classmethod
    def _ensure_synthetic_concept_support(
        cls,
        connection: sqlite3.Connection,
        *,
        knowledge_release_id: str,
        updated_at: str,
    ) -> str:
        release = connection.execute(
            "SELECT is_synthetic FROM knowledge_release WHERE release_id=?",
            (knowledge_release_id,),
        ).fetchone()
        if release is None or not bool(release["is_synthetic"]):
            raise RuntimeError("SYNTHETIC_SUPPORT_RELEASE_REQUIRED")
        chunks = connection.execute(
            """
            SELECT mapping.concept_id,closure.depth,chunk.chunk_id,
                   chunk.document_id,chunk.content
            FROM menu_concept_map mapping
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
             AND closure.inherit_claims=1
            JOIN knowledge_chunk chunk
              ON chunk.release_id=closure.release_id
             AND chunk.concept_id=closure.ancestor_concept_id
            JOIN knowledge_document document
              ON document.release_id=chunk.release_id
             AND document.document_id=chunk.document_id
            WHERE mapping.release_id=?
              AND mapping.mapping_status='MAPPED'
              AND mapping.confidence_band='high'
              AND document.source_type='SYNTHETIC_WIKI'
              AND document.review_status='REVIEWED_DEMO'
              AND lower(chunk.facet)<>'safety'
              AND (
                json_extract(chunk.metadata_json,'$.recommendation_visibility')='PUBLIC_RAG'
                OR json_extract(chunk.metadata_json,'$.recommendation_visibility') IS NULL
              )
            GROUP BY mapping.concept_id,closure.depth,chunk.chunk_id,
                     chunk.document_id,chunk.content
            ORDER BY mapping.concept_id,closure.depth,chunk.chunk_id
            """,
            (knowledge_release_id,),
        ).fetchall()
        support_rows = build_synthetic_support_rows(
            knowledge_release_id=knowledge_release_id,
            reviewed_chunks=[dict(chunk) for chunk in chunks],
            updated_at=updated_at,
        )
        manifest_sha256 = support_manifest_sha256(support_rows)
        if not support_rows:
            raise RuntimeError("SYNTHETIC_CONCEPT_SUPPORT_EMPTY")
        connection.executemany(
            """
            INSERT INTO concept_preference_support(
              knowledge_release_id,concept_id,category_code,option_code,
              support_status,support_strength,evidence_chunk_id,provenance_type,
              source_ref,review_status,support_method_version,is_synthetic,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(knowledge_release_id,concept_id,category_code,option_code)
            DO UPDATE SET
              support_status=excluded.support_status,
              support_strength=excluded.support_strength,
              evidence_chunk_id=excluded.evidence_chunk_id,
              provenance_type=excluded.provenance_type,
              source_ref=excluded.source_ref,
              review_status=excluded.review_status,
              support_method_version=excluded.support_method_version,
              is_synthetic=excluded.is_synthetic,
              updated_at=excluded.updated_at
            """,
            [
                tuple(row[column] for column in (*SUPPORT_MANIFEST_FIELDS, "updated_at"))
                for row in support_rows
            ],
        )
        return manifest_sha256

    @staticmethod
    def _preference_alias_matches(text: str, aliases: tuple[str, ...]) -> bool:
        return preference_alias_matches(text, aliases)

    @classmethod
    def _preference_support_metrics(
        cls,
        connection: sqlite3.Connection,
    ) -> dict[str, tuple[int, int, int]]:
        # Exposure must follow the same reviewed support graph used by ranking.
        # The former implementation repeatedly scanned concatenated menu/Wiki
        # prose against every alias (roughly 230k Python matches per startup),
        # which was both slower and less grounded than the compiled evidence.
        support_rows = connection.execute(
            """
            SELECT support.option_code,
                   COUNT(DISTINCT menu.menu_id) AS menu_count,
                   COUNT(DISTINCT menu.merchant_id) AS merchant_count,
                   COUNT(DISTINCT chunk.document_id) AS document_count
            FROM concept_preference_support support
            JOIN menu_concept_membership membership
              ON membership.knowledge_release_id=support.knowledge_release_id
             AND membership.concept_id=support.concept_id
            JOIN menu ON menu.menu_id=membership.menu_id
            JOIN menu_wiki_eligibility eligibility
              ON eligibility.knowledge_release_id=support.knowledge_release_id
             AND eligibility.menu_id=menu.menu_id
            JOIN knowledge_chunk chunk
              ON chunk.release_id=support.knowledge_release_id
             AND chunk.chunk_id=support.evidence_chunk_id
            JOIN knowledge_runtime_state state
              ON state.state_key='ACTIVE'
             AND state.active_release_id=support.knowledge_release_id
            WHERE menu.availability='AVAILABLE'
              AND support.support_status='SUPPORTED'
              AND support.evidence_chunk_id IS NOT NULL
            GROUP BY support.option_code
            """
        ).fetchall()
        metrics = {
            str(row["option_code"]): (
                int(row["menu_count"]),
                int(row["merchant_count"]),
                int(row["document_count"]),
            )
            for row in support_rows
        }
        price_rows = connection.execute(
            """
            SELECT CASE
                     WHEN menu.price<10000 THEN 'UNDER_10000'
                     WHEN menu.price<20000 THEN 'FROM_10000_TO_19999'
                     WHEN menu.price<30000 THEN 'FROM_20000_TO_29999'
                     ELSE 'OVER_30000'
                   END AS option_code,
                   COUNT(DISTINCT menu.menu_id) AS menu_count,
                   COUNT(DISTINCT menu.merchant_id) AS merchant_count,
                   COUNT(DISTINCT chunk.document_id) AS document_count
            FROM menu_wiki_eligibility eligibility
            JOIN knowledge_runtime_state state
              ON state.state_key='ACTIVE'
             AND state.active_release_id=eligibility.knowledge_release_id
            JOIN menu ON menu.menu_id=eligibility.menu_id
            JOIN menu_concept_membership membership
              ON membership.knowledge_release_id=eligibility.knowledge_release_id
             AND membership.menu_id=menu.menu_id
            JOIN dish_concept_closure closure
              ON closure.release_id=membership.knowledge_release_id
             AND closure.descendant_concept_id=membership.concept_id
             AND closure.inherit_claims=1
            JOIN knowledge_chunk chunk
              ON chunk.release_id=closure.release_id
             AND chunk.concept_id=closure.ancestor_concept_id
            WHERE menu.availability='AVAILABLE'
            GROUP BY CASE
                       WHEN menu.price<10000 THEN 'UNDER_10000'
                       WHEN menu.price<20000 THEN 'FROM_10000_TO_19999'
                       WHEN menu.price<30000 THEN 'FROM_20000_TO_29999'
                       ELSE 'OVER_30000'
                     END
            """
        ).fetchall()
        metrics.update(
            {
                str(row["option_code"]): (
                    int(row["menu_count"]),
                    int(row["merchant_count"]),
                    int(row["document_count"]),
                )
                for row in price_rows
            }
        )
        return metrics

    @classmethod
    def _supported_preference_codes(cls, connection: sqlite3.Connection) -> frozenset[str]:
        metrics = cls._preference_support_metrics(connection)
        supported = {
            option.code
            for category in PREFERENCE_CATEGORIES
            for option in category.options
            if preference_option_is_exposable(
                option.code,
                menu_count=metrics.get(option.code, (0, 0, 0))[0],
                merchant_count=metrics.get(option.code, (0, 0, 0))[1],
                document_count=metrics.get(option.code, (0, 0, 0))[2],
            )
            and (category.code != "cuisine_origins" or option.code in REVIEWED_CUISINE_ORIGIN_CODES)
        }
        return frozenset(supported)

    @classmethod
    def _load_knowledge_catalog(
        cls,
        connection: sqlite3.Connection,
        seed: dict[str, list[dict[str, Any]]],
    ) -> None:
        catalog = build_knowledge_catalog_seed(seed["menus"])
        load_sqlite_release(connection, catalog.compiled_release)
        for table, seed_key, keys in (
            ("menu_concept_map", "menu_concept_maps", ("release_id", "menu_id")),
            (
                "merchant_origin_declaration",
                "merchant_origin_declarations",
                ("release_id", "declaration_id"),
            ),
            (
                "merchant_ingredient",
                "merchant_ingredients",
                ("release_id", "merchant_id", "ingredient_id", "declaration_id"),
            ),
            (
                "option_ingredient_effect",
                "option_ingredient_effects",
                ("release_id", "option_item_id", "ingredient_id", "effect"),
            ),
        ):
            cls._upsert_rows(connection, table, seed[seed_key], keys)

    @classmethod
    def _backfill_normalized_catalog(
        cls, connection: sqlite3.Connection, seed: dict[str, list[dict[str, Any]]]
    ) -> None:
        cls._delete_stale_menu_relation_rows(
            connection,
            table="menu_ingredient",
            value_column="ingredient_id",
            menu_ids=[str(row["menu_id"]) for row in seed["menus"]],
            rows=seed["menu_ingredients"],
        )
        cls._delete_stale_menu_relation_rows(
            connection,
            table="menu_allergen",
            value_column="allergen_id",
            menu_ids=[str(row["menu_id"]) for row in seed["menus"]],
            rows=seed["menu_allergens"],
        )
        cls._delete_stale_menu_relation_rows(
            connection,
            table="menu_dietary_attribute",
            value_column="attribute_id",
            menu_ids=[str(row["menu_id"]) for row in seed["menus"]],
            rows=seed["menu_dietary_attributes"],
        )
        cls._delete_stale_option_conflicts(
            connection,
            menu_ids=[str(row["menu_id"]) for row in seed["menus"]],
            rows=seed["option_dietary_conflicts"],
        )
        for table, seed_key, keys in (
            ("service_area", "service_areas", ("service_area_id",)),
            ("menu_category", "menu_categories", ("category_id",)),
            ("merchant", "merchants", ("merchant_id",)),
            ("menu", "menus", ("menu_id",)),
            ("menu_knowledge", "knowledge", ("knowledge_id",)),
            ("evidence", "evidence", ("evidence_id",)),
            ("review_snippet", "reviews", ("snippet_id",)),
            ("menu_option_group", "option_groups", ("option_group_id",)),
            ("menu_option_item", "option_items", ("option_item_id",)),
            ("ingredient", "ingredients", ("ingredient_id",)),
            ("menu_ingredient", "menu_ingredients", ("menu_id", "ingredient_id")),
            ("allergen", "allergens", ("allergen_id",)),
            ("menu_allergen", "menu_allergens", ("menu_id", "allergen_id")),
            ("dietary_attribute", "dietary_attributes", ("attribute_id",)),
            (
                "menu_dietary_attribute",
                "menu_dietary_attributes",
                ("menu_id", "attribute_id"),
            ),
            (
                "option_dietary_conflict",
                "option_dietary_conflicts",
                ("option_item_id", "rule_code"),
            ),
            ("address_place", "hotels", ("place_id",)),
        ):
            cls._upsert_rows(connection, table, seed[seed_key], keys)

    @staticmethod
    def _delete_stale_menu_relation_rows(
        connection: sqlite3.Connection,
        *,
        table: str,
        value_column: str,
        menu_ids: list[str],
        rows: list[dict[str, Any]],
    ) -> None:
        """Delete relation keys retired from deterministic seed menus, not whole tables."""

        allowed_by_menu: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            allowed_by_menu[str(row["menu_id"])].append(str(row[value_column]))
        grouped: dict[int, list[tuple[str, ...]]] = defaultdict(list)
        for menu_id in menu_ids:
            allowed = tuple(sorted(set(allowed_by_menu[menu_id])))
            grouped[len(allowed)].append((menu_id, *allowed))
        for allowed_count, parameters in grouped.items():
            absent_clause = (
                f" AND {value_column} NOT IN ({','.join('?' for _ in range(allowed_count))})"
                if allowed_count
                else ""
            )
            connection.executemany(
                f"DELETE FROM {table} WHERE menu_id=?{absent_clause}",
                parameters,
            )

    @staticmethod
    def _delete_stale_option_conflicts(
        connection: sqlite3.Connection,
        *,
        menu_ids: list[str],
        rows: list[dict[str, Any]],
    ) -> None:
        allowed = sorted({(str(row["option_item_id"]), str(row["rule_code"])) for row in rows})
        allowed_clause = (
            " AND NOT ("
            + " OR ".join(
                "(option_dietary_conflict.option_item_id=? AND option_dietary_conflict.rule_code=?)"
                for _ in allowed
            )
            + ")"
            if allowed
            else ""
        )
        parameters = [
            (menu_id, *(value for pair in allowed for value in pair)) for menu_id in menu_ids
        ]
        connection.executemany(
            """
            DELETE FROM option_dietary_conflict
            WHERE EXISTS (
              SELECT 1
              FROM menu_option_item item
              JOIN menu_option_group option_group
                ON option_group.option_group_id=item.option_group_id
              WHERE item.option_item_id=option_dietary_conflict.option_item_id
                AND option_group.menu_id=?
            )
            """
            + allowed_clause,
            parameters,
        )

    @classmethod
    def _prune_stale_catalog_dimensions(
        cls,
        connection: sqlite3.Connection,
        seed: dict[str, list[dict[str, Any]]],
    ) -> None:
        """Prune retired dimensions only when no runtime or historical release still needs them."""

        for table, id_column, seed_key, references in (
            (
                "menu_category",
                "category_id",
                "menu_categories",
                ("SELECT 1 FROM menu WHERE menu.category_id=menu_category.category_id",),
            ),
            (
                "ingredient",
                "ingredient_id",
                "ingredients",
                (
                    "SELECT 1 FROM menu_ingredient fact "
                    "WHERE fact.ingredient_id=ingredient.ingredient_id",
                    "SELECT 1 FROM concept_claim claim "
                    "WHERE claim.ingredient_id=ingredient.ingredient_id",
                    "SELECT 1 FROM merchant_ingredient fact "
                    "WHERE fact.ingredient_id=ingredient.ingredient_id",
                    "SELECT 1 FROM option_ingredient_effect effect "
                    "WHERE effect.ingredient_id=ingredient.ingredient_id",
                ),
            ),
            (
                "allergen",
                "allergen_id",
                "allergens",
                (
                    "SELECT 1 FROM menu_allergen fact WHERE fact.allergen_id=allergen.allergen_id",
                    "SELECT 1 FROM concept_claim claim "
                    "WHERE claim.allergen_id=allergen.allergen_id",
                ),
            ),
            (
                "dietary_attribute",
                "attribute_id",
                "dietary_attributes",
                (
                    "SELECT 1 FROM menu_dietary_attribute fact "
                    "WHERE fact.attribute_id=dietary_attribute.attribute_id",
                    "SELECT 1 FROM concept_claim claim "
                    "WHERE claim.attribute_id=dietary_attribute.attribute_id",
                ),
            ),
        ):
            allowed_ids = [str(row[id_column]) for row in seed[seed_key]]
            placeholders = ",".join("?" for _ in allowed_ids)
            reference_guards = "".join(f" AND NOT EXISTS ({reference})" for reference in references)
            connection.execute(
                f"DELETE FROM {table} WHERE {id_column} NOT IN ({placeholders}){reference_guards}",
                allowed_ids,
            )

    @staticmethod
    def _upsert_rows(
        connection: sqlite3.Connection,
        table: str,
        rows: list[dict[str, Any]],
        keys: tuple[str, ...],
    ) -> None:
        if not rows:
            return
        columns = list(rows[0])
        updates = [column for column in columns if column not in keys]
        placeholders = ",".join("?" for _ in columns)
        update_sql = ",".join(f"{column}=excluded.{column}" for column in updates)
        sql = (
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({','.join(keys)}) DO UPDATE SET {update_sql}"
        )
        connection.executemany(sql, [[row[column] for column in columns] for row in rows])

    @staticmethod
    def _insert_rows(
        connection: sqlite3.Connection,
        table: str,
        rows: list[dict[str, Any]],
        *,
        replace: bool = False,
    ) -> None:
        if not rows:
            return
        columns = list(rows[0])
        placeholders = ",".join("?" for _ in columns)
        operation = "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{operation} INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
        connection.executemany(sql, [[row[column] for column in columns] for row in rows])

    def create_profile(self, data: ProfileCreate) -> Profile:
        if not data.consent_demo_data:
            raise ValueError("Data processing consent is required to start a session")
        profile_id = _id("profile")
        created_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO user_profile (
                  profile_id, preferred_language, nationality, country_code, age_band, gender,
                  religion_selection, dietary_rules_json, allergy_severity,
                  spice_tolerance, favorite_foods_json, consent_demo_data,
                  remember_profile, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    data.preferred_language,
                    data.nationality,
                    data.country_code,
                    data.age_band,
                    data.gender,
                    data.religion_selection,
                    json.dumps(data.dietary_rules),
                    data.allergy_severity,
                    data.spice_tolerance,
                    json.dumps(data.favorite_foods),
                    int(data.consent_demo_data),
                    int(data.remember_profile),
                    created_at,
                ),
            )
        return Profile(
            profile_id=profile_id,
            created_at=datetime.fromisoformat(created_at),
            **data.model_dump(),
        )

    def get_profile(self, profile_id: str) -> Profile | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM user_profile WHERE profile_id = ?", (profile_id,)
            ).fetchone()
        return self._profile_from_row(row) if row else None

    def update_profile(self, profile_id: str, data: ProfileUpdate) -> Profile | None:
        existing = self.get_profile(profile_id)
        if existing is None:
            return None
        merged = ProfileCreate.model_validate(
            {
                **existing.model_dump(
                    exclude={"profile_id", "created_at"},
                ),
                **data.model_dump(exclude_unset=True),
            }
        )
        if not merged.consent_demo_data:
            raise ValueError("Data processing consent is required to keep a profile")
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE user_profile SET preferred_language=?, nationality=?, country_code=?, age_band=?, gender=?,
                  religion_selection=?, dietary_rules_json=?, allergy_severity=?,
                  spice_tolerance=?, favorite_foods_json=?, consent_demo_data=?,
                  remember_profile=? WHERE profile_id=?
                """,
                (
                    merged.preferred_language,
                    merged.nationality,
                    merged.country_code,
                    merged.age_band,
                    merged.gender,
                    merged.religion_selection,
                    json.dumps(merged.dietary_rules),
                    merged.allergy_severity,
                    merged.spice_tolerance,
                    json.dumps(merged.favorite_foods),
                    int(merged.consent_demo_data),
                    int(merged.remember_profile),
                    profile_id,
                ),
            )
        return self.get_profile(profile_id)

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> Profile:
        return Profile(
            profile_id=row["profile_id"],
            preferred_language=row["preferred_language"],
            nationality=row["nationality"],
            country_code=row["country_code"],
            age_band=row["age_band"],
            gender=row["gender"],
            religion_selection=row["religion_selection"],
            dietary_rules=json.loads(row["dietary_rules_json"]),
            allergy_severity=row["allergy_severity"],
            spice_tolerance=row["spice_tolerance"],
            favorite_foods=json.loads(row["favorite_foods_json"]),
            consent_demo_data=bool(row["consent_demo_data"]),
            remember_profile=bool(row["remember_profile"]),
            created_at=row["created_at"],
        )

    def delete_profile(self, profile_id: str) -> bool:
        with self._connection() as connection:
            session_rows = connection.execute(
                "SELECT session_id FROM chat_session WHERE profile_id = ?", (profile_id,)
            ).fetchall()
            for row in session_rows:
                self._reset_session_in_connection(
                    connection, row["session_id"], delete_session=True
                )
            cursor = connection.execute(
                "DELETE FROM user_profile WHERE profile_id = ?", (profile_id,)
            )
            return cursor.rowcount > 0

    def create_session(self, profile_id: str) -> Session:
        if not self.get_profile(profile_id):
            raise KeyError("PROFILE_NOT_FOUND")
        session_id = _id("session")
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO chat_session (
                  session_id, profile_id, state, state_stack_json,
                  required_slots_json, created_at, updated_at
                ) VALUES (?, ?, ?, '[]', ?, ?, ?)
                """,
                (
                    session_id,
                    profile_id,
                    ChatState.DISCOVERY.value,
                    json.dumps(["order.menu_id", "delivery.address_confirmed"]),
                    now,
                    now,
                ),
            )
        return Session(
            session_id=session_id,
            profile_id=profile_id,
            state=ChatState.DISCOVERY,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )

    def get_session(self, session_id: str) -> Session | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM chat_session WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return Session(
            session_id=row["session_id"],
            profile_id=row["profile_id"],
            state=ChatState(row["state"]),
            selected_menu_id=row["selected_menu_id"],
            selected_merchant_id=row["selected_merchant_id"],
            dialogue_act=DialogueAct(row["dialogue_act"]),
            meal_need_state=MealNeedState.model_validate(
                json.loads(row["meal_need_state_json"] or "{}")
            ),
            state_version=int(row["state_version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_type: str,
        message_id: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
    ) -> str:
        message_id = message_id or _id("msg")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO chat_message (
                  message_id, session_id, role, content, message_type,
                  safe_metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    session_id,
                    role,
                    content,
                    message_type,
                    json.dumps(safe_metadata or {}, ensure_ascii=False),
                    _now(),
                ),
            )
        return message_id

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT message_id, role, content, message_type, safe_metadata_json, created_at
                FROM chat_message
                WHERE session_id = ?
                  AND message_type <> 'structured_recommendation_audit'
                ORDER BY created_at, message_id
                """,
                (session_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            message = dict(row)
            message["safe_metadata"] = json.loads(message.pop("safe_metadata_json") or "{}")
            messages.append(message)
        return order_conversation_messages(messages)

    def update_dialogue_state(
        self,
        session_id: str,
        dialogue_act: DialogueAct,
        meal_need_state: MealNeedState,
        state: str,
        expected_state_version: int,
    ) -> Session:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_session
                SET state=?, dialogue_act=?, meal_need_state_json=?,
                    state_version=state_version+1, updated_at=?
                WHERE session_id=? AND state_version=?
                """,
                (
                    state,
                    dialogue_act.value,
                    meal_need_state.model_dump_json(),
                    _now(),
                    session_id,
                    expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
        updated = self.get_session(session_id)
        if updated is None:
            raise KeyError("SESSION_NOT_FOUND")
        return updated

    def commit_chat_turn(
        self,
        session_id: str,
        expected_state_version: int,
        user_message_id: str,
        user_text: str,
        user_created_at: datetime,
        assistant_turn: AssistantTurn,
        meal_need_state: MealNeedState,
        dialogue_act: DialogueAct,
        snapshot: RecommendationSnapshot | None = None,
        request_id: str | None = None,
        intent: str | None = None,
    ) -> Session:
        next_version = expected_state_version + 1
        persisted_turn = assistant_turn.model_copy(
            update={"state_version": next_version, "dialogue_act": dialogue_act}
        )
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE chat_session
                SET state=?, dialogue_act=?, meal_need_state_json=?,
                    selected_menu_id=?,
                    selected_merchant_id=(SELECT merchant_id FROM menu WHERE menu_id=?),
                    state_version=?, updated_at=?
                WHERE session_id=? AND state_version=?
                """,
                (
                    persisted_turn.state.value,
                    dialogue_act.value,
                    meal_need_state.model_dump_json(),
                    meal_need_state.selected_menu_id,
                    meal_need_state.selected_menu_id,
                    next_version,
                    _now(),
                    session_id,
                    expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            user_metadata = (
                {
                    "client_request_id": request_id,
                    "intent": intent,
                }
                if request_id
                else {}
            )
            connection.execute(
                """
                INSERT INTO chat_message(
                  message_id, session_id, role, content, message_type,
                  safe_metadata_json, created_at
                ) VALUES (?, ?, 'user', ?, 'text', ?, ?)
                """,
                (
                    user_message_id,
                    session_id,
                    user_text,
                    json.dumps(user_metadata, ensure_ascii=False),
                    user_created_at.isoformat(),
                ),
            )
            assistant_metadata = persisted_turn.model_dump(mode="json")
            if request_id:
                assistant_metadata["client_request_id"] = request_id
            connection.execute(
                """
                INSERT INTO chat_message(
                  message_id, session_id, role, content, message_type,
                  safe_metadata_json, created_at
                ) VALUES (?, ?, 'assistant', ?, 'assistant_turn', ?, ?)
                """,
                (
                    persisted_turn.message_id,
                    session_id,
                    persisted_turn.text,
                    json.dumps(assistant_metadata, ensure_ascii=False),
                    persisted_turn.created_at.isoformat(),
                ),
            )
            if snapshot is not None:
                persisted_snapshot = snapshot.model_copy(
                    update={
                        "state_version": next_version,
                        "meal_need_state": meal_need_state,
                        "cards": [card.model_dump(mode="json") for card in persisted_turn.cards],
                    }
                )
                connection.execute(
                    """
                    INSERT INTO recommendation_snapshot(
                      snapshot_id, session_id, assistant_message_id, state_version,
                      meal_need_state_json, result_json, cards_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        persisted_snapshot.snapshot_id,
                        session_id,
                        persisted_snapshot.assistant_message_id,
                        next_version,
                        meal_need_state.model_dump_json(),
                        persisted_snapshot.result.model_dump_json(),
                        json.dumps(persisted_snapshot.cards, ensure_ascii=False),
                        persisted_snapshot.created_at.isoformat(),
                    ),
                )
        updated = self.get_session(session_id)
        if updated is None:
            raise KeyError("SESSION_NOT_FOUND")
        return updated

    def save_recommendation_snapshot(self, snapshot: RecommendationSnapshot) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO recommendation_snapshot(
                  snapshot_id, session_id, assistant_message_id, state_version,
                  meal_need_state_json, result_json, cards_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.session_id,
                    snapshot.assistant_message_id,
                    snapshot.state_version,
                    snapshot.meal_need_state.model_dump_json(),
                    snapshot.result.model_dump_json(),
                    json.dumps(snapshot.cards, ensure_ascii=False),
                    snapshot.created_at.isoformat(),
                ),
            )

    def get_recommendation_snapshot(
        self, session_id: str, snapshot_id: str | None = None
    ) -> RecommendationSnapshot | None:
        with self._connection() as connection:
            if snapshot_id:
                row = connection.execute(
                    "SELECT * FROM recommendation_snapshot WHERE session_id=? AND snapshot_id=?",
                    (session_id, snapshot_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM recommendation_snapshot WHERE session_id=?
                    ORDER BY created_at DESC, snapshot_id DESC LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
        if row is None:
            return None
        return RecommendationSnapshot.model_validate(
            {
                "snapshot_id": row["snapshot_id"],
                "session_id": row["session_id"],
                "assistant_message_id": row["assistant_message_id"],
                "state_version": row["state_version"],
                "meal_need_state": json.loads(row["meal_need_state_json"]),
                "result": json.loads(row["result_json"]),
                "cards": json.loads(row["cards_json"]),
                "created_at": row["created_at"],
            }
        )

    @staticmethod
    def _criteria_record_from_row(row: sqlite3.Row) -> RecommendationCriteriaRecord:
        return RecommendationCriteriaRecord(
            session_id=str(row["session_id"]),
            criteria=RecommendationCriteriaV2.model_validate_json(str(row["criteria_json"])),
            criteria_version=int(row["criteria_version"]),
            state_version=int(row["state_version"]),
            criteria_hash=str(row["criteria_hash"]),
            request_id=str(row["request_id"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    @staticmethod
    def _request_record_from_row(
        row: sqlite3.Row,
        *,
        duplicate: bool = False,
    ) -> RecommendationRequestRecord:
        columns = set(row.keys())
        return RecommendationRequestRecord(
            request_id=str(row["request_id"]),
            session_id=str(row["session_id"]),
            request_hash=str(row["request_hash"]),
            criteria_version=int(row["criteria_version"]),
            mode=RecommendationMode(str(row["mode"])),
            status=RecommendationRequestStatus(str(row["status"])),
            state_version=int(row["state_version"]),
            release_family_id=str(row["recommendation_release_family_id"]),
            eligibility_as_of=datetime.fromisoformat(str(row["eligibility_as_of"])),
            snapshot_id=str(row["snapshot_id"]) if row["snapshot_id"] else None,
            evidence_pool_json=json.loads(str(row["evidence_pool_json"] or "[]")),
            result_json=(
                json.loads(str(row["result_json"])) if row["result_json"] is not None else None
            ),
            final_candidates_json=(
                json.loads(str(row["final_candidates_json"] or "[]"))
                if "final_candidates_json" in columns
                else []
            ),
            ranking_trace_json=(
                json.loads(str(row["ranking_trace_json"] or "{}"))
                if "ranking_trace_json" in columns
                else {}
            ),
            ranking_policy_version=(
                str(row["ranking_policy_version"])
                if "ranking_policy_version" in columns and row["ranking_policy_version"]
                else "legacy-llm-rank-v2"
            ),
            support_manifest_sha256=(
                str(row["support_manifest_sha256"])
                if "support_manifest_sha256" in columns and row["support_manifest_sha256"]
                else "0" * 64
            ),
            feature_manifest_sha256=(
                str(row["feature_manifest_sha256"])
                if "feature_manifest_sha256" in columns and row["feature_manifest_sha256"]
                else "0" * 64
            ),
            finalized_at=(
                datetime.fromisoformat(str(row["finalized_at"]))
                if "finalized_at" in columns and row["finalized_at"]
                else None
            ),
            dispatch_count=int(row["dispatch_count"]),
            failure_code=str(row["failure_code"]) if row["failure_code"] else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
            dispatched_at=(
                datetime.fromisoformat(str(row["dispatched_at"])) if row["dispatched_at"] else None
            ),
            completed_at=(
                datetime.fromisoformat(str(row["completed_at"])) if row["completed_at"] else None
            ),
            client_cancelled_at=(
                datetime.fromisoformat(str(row["client_cancelled_at"]))
                if "client_cancelled_at" in columns and row["client_cancelled_at"]
                else None
            ),
            duplicate=duplicate,
        )

    def save_recommendation_criteria(
        self,
        session_id: str,
        commit: RecommendationCriteriaCommit,
    ) -> RecommendationCriteriaRecord:
        canonical = json.dumps(
            {
                "catalog_version": commit.catalog_version,
                "criteria": commit.criteria.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        criteria_hash = hashlib.sha256(canonical.encode()).hexdigest()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM session_recommendation_criteria
                WHERE session_id=? AND request_id=?
                """,
                (session_id, commit.request_id),
            ).fetchone()
            if existing is not None:
                if str(existing["criteria_hash"]) != criteria_hash:
                    raise ValueError("CRITERIA_REQUEST_ID_REUSED")
                return self._criteria_record_from_row(existing)

            active = connection.execute(
                """
                SELECT family.preference_catalog_version
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                """
            ).fetchone()
            if active is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
            if str(active["preference_catalog_version"]) != commit.catalog_version:
                raise ValueError("PREFERENCE_CATALOG_CHANGED")
            selected_codes = {
                value
                for category in (
                    "cuisine_origins",
                    "flavors",
                    "main_ingredients",
                    "food_forms",
                    "temperatures",
                    "price_bands",
                    "textures",
                    "cooking_methods",
                )
                for value in getattr(commit.criteria, category)
            }
            available_codes = {
                str(row["option_code"])
                for row in connection.execute(
                    """
                    SELECT option_code FROM recommendation_preference_option
                    WHERE catalog_version=? AND active=1
                    """,
                    (commit.catalog_version,),
                ).fetchall()
            }
            unknown_codes = sorted(selected_codes - available_codes)
            if unknown_codes:
                raise ValueError(f"UNSUPPORTED_PREFERENCE_CODE:{unknown_codes[0]}")

            session = connection.execute(
                "SELECT state_version FROM chat_session WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise KeyError("SESSION_NOT_FOUND")
            current_state_version = int(session["state_version"])
            if current_state_version != commit.expected_state_version:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            version_row = connection.execute(
                """
                SELECT COALESCE(MAX(criteria_version),0)+1 AS next_version
                FROM session_recommendation_criteria WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()
            criteria_version = int(version_row["next_version"])
            next_state_version = current_state_version + 1
            updated = connection.execute(
                """
                UPDATE chat_session SET state_version=?,updated_at=?
                WHERE session_id=? AND state_version=?
                """,
                (next_state_version, _now(), session_id, current_state_version),
            )
            if updated.rowcount != 1:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            created_at = _now()
            connection.execute(
                """
                INSERT INTO session_recommendation_criteria(
                  session_id,criteria_version,criteria_json,criteria_hash,
                  request_id,state_version,created_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    criteria_version,
                    commit.criteria.model_dump_json(),
                    criteria_hash,
                    commit.request_id,
                    next_state_version,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM session_recommendation_criteria
                WHERE session_id=? AND criteria_version=?
                """,
                (session_id, criteria_version),
            ).fetchone()
            if row is None:
                raise RuntimeError("RECOMMENDATION_CRITERIA_WRITE_FAILED")
            return self._criteria_record_from_row(row)

    def get_recommendation_criteria(
        self,
        session_id: str,
        version: int | None = None,
    ) -> RecommendationCriteriaRecord | None:
        with self._connection() as connection:
            if version is None:
                row = connection.execute(
                    """
                    SELECT * FROM session_recommendation_criteria
                    WHERE session_id=? ORDER BY criteria_version DESC LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM session_recommendation_criteria
                    WHERE session_id=? AND criteria_version=?
                    """,
                    (session_id, version),
                ).fetchone()
        return self._criteria_record_from_row(row) if row else None

    def reserve_recommendation_request(
        self,
        session_id: str,
        data: RecommendationRequestInput,
        request_hash: str,
    ) -> RecommendationRequestRecord:
        if not request_hash or len(request_hash) > 160:
            raise ValueError("INVALID_RECOMMENDATION_REQUEST_HASH")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, data.request_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["request_hash"]) != request_hash
                    or int(existing["criteria_version"]) != data.criteria_version
                    or str(existing["mode"]) != data.mode.value
                ):
                    raise ValueError("RECOMMENDATION_REQUEST_ID_REUSED")
                return self._request_record_from_row(existing, duplicate=True)

            session = connection.execute(
                "SELECT state_version FROM chat_session WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise KeyError("SESSION_NOT_FOUND")
            current_state_version = int(session["state_version"])
            if current_state_version != data.expected_state_version:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            criteria = connection.execute(
                """
                SELECT 1 FROM session_recommendation_criteria
                WHERE session_id=? AND criteria_version=?
                """,
                (session_id, data.criteria_version),
            ).fetchone()
            if criteria is None:
                raise ValueError("RECOMMENDATION_CRITERIA_VERSION_NOT_FOUND")
            created_at = _now()
            pinned_family = connection.execute(
                """
                SELECT family.release_family_id,family.ranking_policy_version,
                       family.support_manifest_sha256,family.feature_manifest_sha256
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                JOIN knowledge_release release
                  ON release.release_id=family.knowledge_release_id
                WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                  AND release.status='READY'
                """
            ).fetchone()
            if pinned_family is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
            eligibility_as_of = created_at
            connection.execute(
                """
                INSERT INTO structured_recommendation_request(
                  session_id,request_id,request_hash,criteria_version,mode,status,state_version,
                  recommendation_release_family_id,eligibility_as_of,snapshot_id,
                  evidence_pool_json,result_json,final_candidates_json,ranking_trace_json,
                  ranking_policy_version,support_manifest_sha256,
                  feature_manifest_sha256,finalized_at,
                  dispatch_count,failure_code,
                  created_at,dispatched_at,completed_at
                ) VALUES (?,?,?,?,?,'CREATED',?,?,?,NULL,'[]',NULL,'[]','{}',?,?,?,NULL,0,NULL,?,NULL,NULL)
                """,
                (
                    session_id,
                    data.request_id,
                    request_hash,
                    data.criteria_version,
                    data.mode.value,
                    current_state_version,
                    str(pinned_family["release_family_id"]),
                    eligibility_as_of,
                    str(pinned_family["ranking_policy_version"]),
                    str(pinned_family["support_manifest_sha256"]),
                    str(pinned_family["feature_manifest_sha256"]),
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, data.request_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("RECOMMENDATION_REQUEST_RESERVATION_FAILED")
            return self._request_record_from_row(row)

    def mark_recommendation_dispatched(
        self,
        session_id: str,
        request_id: str,
        evidence_pool: list[EvidencePoolItem],
    ) -> RecommendationRequestRecord:
        if not evidence_pool:
            raise ValueError("EVIDENCE_POOL_EMPTY")
        serialized = json.dumps(
            [item.model_dump(mode="json") for item in evidence_pool],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        serialized_final = "[]"
        serialized_trace = json.dumps(
            {
                "ranking_policy_version": (
                    evidence_pool[0].ranking_trace.get("ranking_policy_version")
                    or RANKING_POLICY_VERSION
                ),
                "shortlist_count": len(evidence_pool),
                "selection_status": "PENDING",
                "candidates": [item.ranking_trace for item in evidence_pool],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, request_id),
            ).fetchone()
            if row is None:
                raise KeyError("RECOMMENDATION_REQUEST_NOT_FOUND")
            if str(row["status"]) != RecommendationRequestStatus.CREATED.value:
                if str(row["evidence_pool_json"]) != serialized:
                    raise ValueError("RECOMMENDATION_DISPATCH_PAYLOAD_CHANGED")
                return self._request_record_from_row(row, duplicate=True)
            dispatched_at = _now()
            updated = connection.execute(
                """
                UPDATE structured_recommendation_request
                SET status='DISPATCHED',evidence_pool_json=?,final_candidates_json=?,
                    ranking_trace_json=?,dispatched_at=?
                WHERE session_id=? AND request_id=? AND status='CREATED' AND dispatch_count=0
                """,
                (
                    serialized,
                    serialized_final,
                    serialized_trace,
                    dispatched_at,
                    session_id,
                    request_id,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("RECOMMENDATION_DISPATCH_CONFLICT")
            current = connection.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, request_id),
            ).fetchone()
            if current is None:
                raise RuntimeError("RECOMMENDATION_DISPATCH_WRITE_FAILED")
            return self._request_record_from_row(current)

    def mark_recommendation_provider_called(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationRequestRecord:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE structured_recommendation_request
                SET dispatch_count=1
                WHERE session_id=? AND request_id=?
                  AND status='DISPATCHED' AND dispatch_count=0
                """,
                (session_id, request_id),
            )
            if updated.rowcount != 1:
                raise RuntimeError("RECOMMENDATION_PROVIDER_CALL_CONFLICT")
            row = connection.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, request_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("RECOMMENDATION_PROVIDER_CALL_WRITE_FAILED")
            return self._request_record_from_row(row)

    def record_recommendation_provider_attempt(
        self,
        session_id: str,
        request_id: str,
        *,
        attempt_no: int,
        provider: str,
        model_id: str,
        status: str,
        error_code: str | None,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        attempt_role: str = "SELECTION",
    ) -> None:
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO recommendation_provider_attempt(
                  session_id,request_id,attempt_no,provider,model_id,status,error_code,
                  latency_ms,input_tokens,output_tokens,attempt_role,created_at,completed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(session_id,request_id,attempt_no) DO UPDATE SET
                  status=excluded.status,error_code=excluded.error_code,
                  latency_ms=excluded.latency_ms,input_tokens=excluded.input_tokens,
                  output_tokens=excluded.output_tokens,attempt_role=excluded.attempt_role,
                  completed_at=excluded.completed_at
                """,
                (
                    session_id,
                    request_id,
                    attempt_no,
                    provider,
                    model_id,
                    status,
                    error_code,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    attempt_role,
                    now,
                    now,
                ),
            )

    def record_restaurant_note_translation_attempt(
        self,
        session_id: str,
        request_hash: str,
        *,
        attempt_no: int,
        provider: str,
        model_id: str,
        status: str,
        error_code: str | None,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        now = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO restaurant_note_translation_attempt(
                  session_id,request_hash,attempt_no,provider,model_id,status,error_code,
                  latency_ms,input_tokens,output_tokens,created_at,completed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(session_id,request_hash,attempt_no) DO UPDATE SET
                  provider=excluded.provider,model_id=excluded.model_id,
                  status=excluded.status,error_code=excluded.error_code,
                  latency_ms=excluded.latency_ms,input_tokens=excluded.input_tokens,
                  output_tokens=excluded.output_tokens,completed_at=excluded.completed_at
                """,
                (
                    session_id,
                    request_hash,
                    attempt_no,
                    provider,
                    model_id,
                    status,
                    error_code,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    now,
                    now,
                ),
            )

    def cancel_recommendation_request(self, session_id: str, request_id: str) -> bool:
        with self._connection() as connection:
            updated = connection.execute(
                """
                UPDATE structured_recommendation_request
                SET client_cancelled_at=COALESCE(client_cancelled_at,?)
                WHERE session_id=? AND request_id=?
                """,
                (_now(), session_id, request_id),
            )
            return updated.rowcount == 1

    @staticmethod
    def _restaurant_note_translation_from_row(
        row: sqlite3.Row,
    ) -> RestaurantNoteTranslation:
        return RestaurantNoteTranslation(
            translation_id=str(row["translation_id"]),
            source_text=str(row["source_text"]),
            source_language=str(row["source_language"]),
            korean_text=str(row["korean_text"]) if row["korean_text"] else None,
            back_translation=(str(row["back_translation"]) if row["back_translation"] else None),
            model_id=str(row["model_id"]),
            status=cast(Any, str(row["status"])),
            error_code=str(row["error_code"]) if row["error_code"] else None,
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def get_restaurant_note_translation_by_hash(
        self, session_id: str, request_hash: str
    ) -> RestaurantNoteTranslation | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM restaurant_note_translation
                WHERE session_id=? AND request_hash=? AND status='SUCCEEDED'
                ORDER BY created_at DESC LIMIT 1
                """,
                (session_id, request_hash),
            ).fetchone()
        return self._restaurant_note_translation_from_row(row) if row else None

    def save_restaurant_note_translation(
        self,
        session_id: str,
        *,
        translation_id: str,
        source_language: str,
        source_text: str,
        korean_text: str | None,
        back_translation: str | None,
        provider: str,
        model_id: str,
        status: str,
        error_code: str | None,
        request_hash: str,
    ) -> RestaurantNoteTranslation:
        created_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO restaurant_note_translation(
                  translation_id,session_id,source_language,source_text,korean_text,
                  back_translation,provider,model_id,status,error_code,request_hash,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    translation_id,
                    session_id,
                    source_language,
                    source_text,
                    korean_text,
                    back_translation,
                    provider,
                    model_id,
                    status,
                    error_code,
                    request_hash,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM restaurant_note_translation WHERE translation_id=?",
                (translation_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("RESTAURANT_NOTE_TRANSLATION_WRITE_FAILED")
        return self._restaurant_note_translation_from_row(row)

    def complete_recommendation_request(
        self,
        session_id: str,
        request_id: str,
        status: RecommendationRequestStatus,
        *,
        result_json: dict[str, Any] | None = None,
        snapshot: RecommendationSnapshot | None = None,
        failure_code: str | None = None,
        provider_metrics: dict[str, int] | None = None,
        grounding_rejection_code: str | None = None,
        grounding_rejection_stage: str | None = None,
        grounding_rejection_detail: str | None = None,
    ) -> RecommendationRequestRecord:
        terminal_statuses = {
            RecommendationRequestStatus.COMPLETED,
            RecommendationRequestStatus.NO_RESULTS,
            RecommendationRequestStatus.NO_MATCH,
            RecommendationRequestStatus.SEARCH_FALLBACK,
            RecommendationRequestStatus.FAILED,
            RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH,
        }
        if status not in terminal_statuses:
            raise ValueError("RECOMMENDATION_STATUS_NOT_TERMINAL")
        if snapshot is not None and snapshot.session_id != session_id:
            raise ValueError("RECOMMENDATION_SNAPSHOT_SESSION_MISMATCH")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, request_id),
            ).fetchone()
            if row is None:
                raise KeyError("RECOMMENDATION_REQUEST_NOT_FOUND")
            current_status = RecommendationRequestStatus(str(row["status"]))
            if current_status in terminal_statuses:
                canonicalized_snapshot_replay = snapshot is not None and (
                    str(row["snapshot_id"] or "") == snapshot.snapshot_id
                    or str(row["failure_code"] or "") == "LIVE_ELIGIBILITY_EMPTY"
                )
                if canonicalized_snapshot_replay:
                    return self._request_record_from_row(row, duplicate=True)
                serialized_result = (
                    json.dumps(
                        result_json,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if result_json is not None
                    else None
                )
                same_payload = (
                    current_status is status
                    and (row["result_json"] or None) == serialized_result
                    and (row["failure_code"] or None) == failure_code
                    and (row["snapshot_id"] or None) == (snapshot.snapshot_id if snapshot else None)
                )
                if not same_payload:
                    raise ValueError("RECOMMENDATION_COMPLETION_PAYLOAD_CHANGED")
                return self._request_record_from_row(row, duplicate=True)
            requires_dispatch = {
                RecommendationRequestStatus.COMPLETED,
                RecommendationRequestStatus.NO_MATCH,
                RecommendationRequestStatus.SEARCH_FALLBACK,
                RecommendationRequestStatus.UNKNOWN_AFTER_DISPATCH,
            }
            if (
                status in requires_dispatch
                and current_status is not RecommendationRequestStatus.DISPATCHED
            ):
                raise RuntimeError("RECOMMENDATION_NOT_DISPATCHED")
            persisted_state_version = int(row["state_version"])
            if snapshot is not None:
                criteria_row = connection.execute(
                    """
                    SELECT * FROM session_recommendation_criteria
                    WHERE session_id=? AND criteria_version=?
                    """,
                    (session_id, int(row["criteria_version"])),
                ).fetchone()
                family_row = connection.execute(
                    """
                    SELECT family.release_family_id
                    FROM recommendation_release_family family
                    WHERE family.release_family_id=?
                    """,
                    (str(row["recommendation_release_family_id"]),),
                ).fetchone()
                if criteria_row is None or family_row is None:
                    raise RuntimeError("RECOMMENDATION_SNAPSHOT_CONTEXT_MISSING")
                criteria = RecommendationCriteriaV2.model_validate_json(
                    str(criteria_row["criteria_json"])
                )
                requested_menu_ids = [candidate.menu_id for candidate in snapshot.result.candidates]
                evidence_pool_menu_ids = {
                    str(item.get("menu", {}).get("menu_id") or item.get("menu_id") or "")
                    for item in json.loads(str(row["evidence_pool_json"] or "[]"))
                    if isinstance(item, dict)
                }
                if not set(requested_menu_ids) <= evidence_pool_menu_ids:
                    raise ValueError("SNAPSHOT_MENU_OUTSIDE_EVIDENCE_POOL")
                eligible_rows, live_certifications, live_vegan = (
                    self._structured_objective_candidates(
                        connection,
                        session_id,
                        criteria,
                        release_family_id=str(row["recommendation_release_family_id"]),
                        eligibility_as_of=datetime.now(timezone.utc),
                        menu_ids=requested_menu_ids,
                        enforce_price_bands=False,
                    )
                )
                eligible_by_id = {str(menu["menu_id"]): menu for menu in eligible_rows}
                retained_candidates = [
                    candidate.model_copy(update={"rank": rank})
                    for rank, candidate in enumerate(
                        (
                            candidate
                            for candidate in snapshot.result.candidates
                            if candidate.menu_id in eligible_by_id
                            and str(eligible_by_id[candidate.menu_id]["merchant_id"])
                            == candidate.merchant_id
                        ),
                        start=1,
                    )
                ]
                if not retained_candidates:
                    snapshot = None
                    status = RecommendationRequestStatus.NO_RESULTS
                    failure_code = failure_code or "LIVE_ELIGIBILITY_EMPTY"
                    if result_json is not None:
                        result_json = {**result_json, "status": "NO_MATCH", "recommendations": []}
                else:
                    retained_ids = {candidate.menu_id for candidate in retained_candidates}
                    retained_claim_ids = list(
                        dict.fromkeys(
                            claim_id
                            for candidate in retained_candidates
                            for claim_id in candidate.claim_ids
                        )
                    )
                    retained_passage_ids = list(
                        dict.fromkeys(
                            passage_id
                            for candidate in retained_candidates
                            for passage_id in candidate.passage_ids
                        )
                    )
                    retained_result = snapshot.result.model_copy(
                        update={
                            "candidates": retained_candidates,
                            "grounded_claim_ids": retained_claim_ids,
                            "grounded_passage_ids": retained_passage_ids,
                        }
                    )
                    retained_state = snapshot.meal_need_state.model_copy(deep=True)
                    retained_state.shown_menu_ids = [
                        menu_id
                        for menu_id in retained_state.shown_menu_ids
                        if menu_id not in requested_menu_ids or menu_id in retained_ids
                    ]
                    refreshed_menus: dict[str, dict[str, Any]] = {}
                    retained_recommendations: list[dict[str, Any]] = []
                    if result_json is not None:
                        for item in list(result_json.get("recommendations", [])):
                            if not isinstance(item, dict):
                                continue
                            menu_id = str(
                                item.get("menu_id")
                                or cast(dict[str, Any], item.get("menu") or {}).get("menu_id")
                                or ""
                            )
                            if menu_id not in retained_ids:
                                continue
                            menu_payload = self._live_structured_menu_payload(
                                eligible_by_id[menu_id],
                                cast(dict[str, Any], item.get("menu") or {}),
                            )
                            refreshed_menus[menu_id] = menu_payload
                            certification = live_certifications.get(menu_id)
                            vegan_status, vegan_warning, _ = live_vegan.get(
                                menu_id, ("UNKNOWN", None, [])
                            )
                            retained_recommendations.append(
                                {
                                    **item,
                                    "menu_id": menu_id,
                                    "menu": menu_payload,
                                    "halal_certified": bool(certification),
                                    "halal_scope_label": (
                                        certification[1] if certification else None
                                    ),
                                    "vegan_status": vegan_status,
                                    "vegan_warning": vegan_warning,
                                }
                            )
                        retained_recommendations = [
                            {**item, "rank": rank}
                            for rank, item in enumerate(retained_recommendations, start=1)
                        ]
                        result_json = {
                            **result_json,
                            "recommendations": retained_recommendations,
                        }
                    retained_cards = [
                        {
                            "type": "structured_recommendation",
                            "data": {
                                "menu": refreshed_menus.get(candidate.menu_id)
                                or self._live_structured_menu_payload(
                                    eligible_by_id[candidate.menu_id],
                                    self._menu_from_cards(snapshot.cards, candidate.menu_id),
                                )
                            },
                        }
                        for candidate in retained_candidates
                    ]
                    snapshot = snapshot.model_copy(
                        update={
                            "result": retained_result,
                            "cards": retained_cards,
                            "meal_need_state": retained_state,
                        }
                    )

                    session = connection.execute(
                        "SELECT state_version FROM chat_session WHERE session_id=?",
                        (session_id,),
                    ).fetchone()
                    if session is None or int(session["state_version"]) != int(
                        row["state_version"]
                    ):
                        raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
                    persisted_state_version = int(row["state_version"]) + 1
                    updated_session = connection.execute(
                        """
                        UPDATE chat_session
                        SET meal_need_state_json=?,state_version=?,updated_at=?
                        WHERE session_id=? AND state_version=?
                        """,
                        (
                            snapshot.meal_need_state.model_dump_json(),
                            persisted_state_version,
                            _now(),
                            session_id,
                            int(row["state_version"]),
                        ),
                    )
                    if updated_session.rowcount != 1:
                        raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
                    snapshot = snapshot.model_copy(
                        update={
                            "assistant_message_id": (
                                "msg_a_v2_"
                                + hashlib.sha256(f"{session_id}:{request_id}".encode()).hexdigest()[
                                    :40
                                ]
                            ),
                            "state_version": persisted_state_version,
                        }
                    )

            serialized_result = (
                json.dumps(result_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if result_json is not None
                else None
            )
            final_candidates = []
            if result_json is not None:
                for rank, item in enumerate(result_json.get("recommendations", []), start=1):
                    if not isinstance(item, dict):
                        continue
                    menu = cast(dict[str, Any], item.get("menu") or {})
                    final_candidates.append(
                        {
                            "rank": rank,
                            "menu_id": str(item.get("menu_id") or menu.get("menu_id") or ""),
                            "merchant_id": str(menu.get("merchant_id") or ""),
                        }
                    )
            serialized_final = json.dumps(
                final_candidates,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            ranking_trace = json.loads(str(row["ranking_trace_json"] or "{}"))
            ranking_trace.update(
                {
                    "selection_status": (
                        "GROK_SELECTED"
                        if status is RecommendationRequestStatus.COMPLETED
                        else "DETERMINISTIC_FALLBACK"
                        if status is RecommendationRequestStatus.SEARCH_FALLBACK
                        else status.value
                    ),
                    "fallback_reason": failure_code,
                    "grounding_rejection_code": grounding_rejection_code,
                    "grounding_rejection_stage": grounding_rejection_stage,
                    "grounding_rejection_detail": grounding_rejection_detail,
                    "final_candidates": final_candidates,
                    "provider_metrics": dict(provider_metrics or {}),
                }
            )
            serialized_ranking_trace = json.dumps(
                ranking_trace,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if snapshot is not None:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO chat_message(
                      message_id,session_id,role,content,message_type,safe_metadata_json,created_at
                    ) VALUES (?,?,'assistant','Structured recommendation snapshot.',
                              'structured_recommendation_audit',?,?)
                    """,
                    (
                        snapshot.assistant_message_id,
                        session_id,
                        json.dumps(
                            {
                                "request_id": request_id,
                                "state_version": persisted_state_version,
                                "non_user_visible": True,
                            },
                            separators=(",", ":"),
                        ),
                        snapshot.created_at.isoformat(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO recommendation_snapshot(
                      snapshot_id,session_id,assistant_message_id,state_version,
                      meal_need_state_json,result_json,cards_json,structured_request_id,
                      criteria_version,criteria_json,criteria_hash,
                      recommendation_release_family_id,evidence_pool_json,
                      generation_status,generation_call_count,grounding_validation_json,
                      ranking_trace_json,ranking_policy_version,support_manifest_sha256,
                      feature_manifest_sha256,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        snapshot.snapshot_id,
                        snapshot.session_id,
                        snapshot.assistant_message_id,
                        persisted_state_version,
                        snapshot.meal_need_state.model_dump_json(),
                        snapshot.result.model_dump_json(),
                        json.dumps(snapshot.cards, ensure_ascii=False),
                        request_id,
                        int(row["criteria_version"]),
                        str(criteria_row["criteria_json"]),
                        str(criteria_row["criteria_hash"]),
                        str(family_row["release_family_id"]),
                        str(row["evidence_pool_json"]),
                        status.value,
                        int(row["dispatch_count"]),
                        json.dumps({"validated": True}, separators=(",", ":")),
                        serialized_ranking_trace,
                        str(row["ranking_policy_version"]),
                        str(row["support_manifest_sha256"]),
                        str(row["feature_manifest_sha256"]),
                        snapshot.created_at.isoformat(),
                    ),
                )
            completed_at = _now()
            updated = connection.execute(
                """
                UPDATE structured_recommendation_request
                SET status=?,result_json=?,snapshot_id=?,failure_code=?,completed_at=?,
                    state_version=?,final_candidates_json=?,ranking_trace_json=?,finalized_at=?
                WHERE session_id=? AND request_id=? AND status=?
                """,
                (
                    status.value,
                    serialized_result,
                    snapshot.snapshot_id if snapshot else None,
                    failure_code,
                    completed_at,
                    persisted_state_version,
                    serialized_final,
                    serialized_ranking_trace,
                    completed_at,
                    session_id,
                    request_id,
                    current_status.value,
                ),
            )
            if updated.rowcount != 1:
                raise RuntimeError("RECOMMENDATION_COMPLETION_CONFLICT")
            current = connection.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, request_id),
            ).fetchone()
            if current is None:
                raise RuntimeError("RECOMMENDATION_COMPLETION_WRITE_FAILED")
            return self._request_record_from_row(current)

    def get_recommendation_request(
        self,
        session_id: str,
        request_id: str,
    ) -> RecommendationRequestRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, request_id),
            ).fetchone()
        return self._request_record_from_row(row) if row else None

    def get_recommendation_comparison(
        self,
        session_id: str,
        recommendation_request_id: str,
        comparison_request_id: str,
    ) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT result_json FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, recommendation_request_id),
            ).fetchone()
        if row is None or not row["result_json"]:
            return None
        result = json.loads(str(row["result_json"]))
        cache = result.get("comparison_cache", {})
        cached = cache.get("canonical") if isinstance(cache, dict) else None
        if not isinstance(cached, dict) and isinstance(cache, dict):
            cached = next(
                (value for _key, value in sorted(cache.items()) if isinstance(value, dict)),
                None,
            )
        return dict(cached) if isinstance(cached, dict) else None

    def save_recommendation_comparison(
        self,
        session_id: str,
        recommendation_request_id: str,
        comparison_request_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT result_json,status FROM structured_recommendation_request
                WHERE session_id=? AND request_id=?
                """,
                (session_id, recommendation_request_id),
            ).fetchone()
            if row is None:
                raise KeyError("RECOMMENDATION_REQUEST_NOT_FOUND")
            if str(row["status"]) not in {"COMPLETED", "SEARCH_FALLBACK"}:
                raise ValueError("RECOMMENDATION_COMPARISON_NOT_AVAILABLE")
            result = json.loads(str(row["result_json"] or "{}"))
            cache = result.setdefault("comparison_cache", {})
            if not isinstance(cache, dict):
                raise ValueError("RECOMMENDATION_COMPARISON_CACHE_INVALID")
            existing = cache.get("canonical")
            if not isinstance(existing, dict):
                existing = next(
                    (value for _key, value in sorted(cache.items()) if isinstance(value, dict)),
                    None,
                )
            if isinstance(existing, dict):
                return dict(existing), True
            cache["canonical"] = payload
            connection.execute(
                """
                UPDATE structured_recommendation_request SET result_json=?
                WHERE session_id=? AND request_id=?
                """,
                (
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    session_id,
                    recommendation_request_id,
                ),
            )
        return dict(payload), False

    def get_latest_recommendation_request(
        self,
        session_id: str,
        *,
        active_only: bool = False,
    ) -> RecommendationRequestRecord | None:
        active_clause = (
            "AND status IN ('CREATED','DISPATCHED') AND client_cancelled_at IS NULL"
            if active_only
            else ""
        )
        with self._connection() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM structured_recommendation_request
                WHERE session_id=? {active_clause}
                ORDER BY created_at DESC,request_id DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return self._request_record_from_row(row) if row else None

    @staticmethod
    def _price_matches_v2(price: int, selected_bands: list[str]) -> bool:
        if not selected_bands:
            return True
        return any(
            (
                code == "UNDER_10000"
                and price < 10_000
                or code == "FROM_10000_TO_19999"
                and 10_000 <= price < 20_000
                or code == "FROM_20000_TO_29999"
                and 20_000 <= price < 30_000
                or code == "OVER_30000"
                and price >= 30_000
            )
            for code in selected_bands
        )

    @staticmethod
    def _valid_halal_certifications_in_connection(
        connection: sqlite3.Connection,
        *,
        release_family_id: str,
        instant: str,
    ) -> dict[str, tuple[str, str]]:
        rows = connection.execute(
            """
            SELECT certification.certification_id,certification.scope_type,
                   certification.scope_ref,certification.merchant_id
            FROM recommendation_release_family family
            JOIN merchant_certification certification
              ON certification.certification_release_id=family.certification_release_id
            WHERE family.release_family_id=?
              AND certification.certification_type='HALAL'
              AND certification.status='ACTIVE'
              AND certification.valid_from<=?
              AND (certification.valid_to IS NULL OR certification.valid_to>?)
            ORDER BY certification.certification_id
            """,
            (release_family_id, instant, instant),
        ).fetchall()
        result: dict[str, tuple[str, str]] = {}
        merchant_certifications: dict[str, tuple[str, str]] = {}
        for row in rows:
            certification_id = str(row["certification_id"])
            if str(row["scope_type"]) == "MERCHANT":
                merchant_certifications[str(row["merchant_id"])] = (
                    certification_id,
                    "Merchant-level halal certification scope",
                )
                continue
            menu_id = str(row["scope_ref"] or "")
            if not menu_id:
                continue
            owner = connection.execute(
                "SELECT merchant_id FROM menu WHERE menu_id=?",
                (menu_id,),
            ).fetchone()
            if owner is not None and str(owner["merchant_id"]) == str(row["merchant_id"]):
                result[menu_id] = (
                    certification_id,
                    "Menu-level halal certification scope",
                )
        if merchant_certifications:
            placeholders = ",".join("?" for _ in merchant_certifications)
            for row in connection.execute(
                f"""
                SELECT menu_id,merchant_id FROM menu
                WHERE merchant_id IN ({placeholders})
                """,
                tuple(merchant_certifications),
            ).fetchall():
                menu_id = str(row["menu_id"])
                result.setdefault(menu_id, merchant_certifications[str(row["merchant_id"])])
        return result

    @staticmethod
    def _v2_vegan_classifications(
        connection: sqlite3.Connection,
        menu_ids: list[str],
        *,
        knowledge_release_id: str,
    ) -> dict[str, tuple[str, str | None, list[EvidenceReference]]]:
        unique_ids = list(dict.fromkeys(menu_ids))
        resolved = SQLiteYobiRepository._bulk_resolved_knowledge_claims(
            connection,
            unique_ids,
            release_id=knowledge_release_id,
        )
        dietary_signals: dict[str, list[tuple[str, str, str | None]]] = defaultdict(list)
        if unique_ids:
            placeholders = ",".join("?" for _ in unique_ids)
            for row in connection.execute(
                f"""
                SELECT relation.menu_id,attribute.code,relation.status,relation.evidence_id
                FROM menu_dietary_attribute relation
                JOIN dietary_attribute attribute
                  ON attribute.attribute_id=relation.attribute_id
                WHERE relation.menu_id IN ({placeholders})
                  AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                """,
                unique_ids,
            ).fetchall():
                dietary_signals[str(row["menu_id"])].append(
                    (
                        str(row["code"]).lower(),
                        str(row["status"]).upper(),
                        str(row["evidence_id"]) if row["evidence_id"] else None,
                    )
                )

        classifications: dict[str, tuple[str, str | None, list[EvidenceReference]]] = {}
        present = {ClaimStatus.CONFIRMED_PRESENT, ClaimStatus.PRESUMED_PRESENT}
        uncertain = {ClaimStatus.POSSIBLE, ClaimStatus.CONFLICTING}
        for menu_id in unique_ids:
            ingredient_claims = resolved.get(menu_id, ([], [], []))[0]
            vegan_claims = [
                claim for claim in ingredient_claims if claim.ingredient_id in VEGAN_INGREDIENTS
            ]
            confirmed_conflicts = [
                claim
                for claim in vegan_claims
                if claim.status in present
                and (
                    claim.source_scope is SourceScope.MENU
                    or claim.role in {IngredientRole.DEFINING, IngredientRole.CORE}
                )
            ]
            possible_conflicts = [
                claim
                for claim in vegan_claims
                if claim.status in uncertain
                or (claim.status in present and claim not in confirmed_conflicts)
            ]
            claim_references = [
                EvidenceReference(
                    evidence_id=str(claim.source_id),
                    evidence_type="ESSENTIAL_FACT",
                    content=(
                        f"{claim.name_en} is recorded as {claim.status.value.lower()} "
                        f"({claim.role.value.lower()})."
                    ),
                )
                for claim in [*confirmed_conflicts, *possible_conflicts]
            ]
            positive_signals = [
                signal
                for signal in dietary_signals.get(menu_id, [])
                if signal[1] in {"PRESENT", "VERIFIED", "CONFIRMED_PRESENT"}
            ]
            claim_references.extend(
                EvidenceReference(
                    evidence_id=evidence_id or f"fact_{menu_id}_{code}",
                    evidence_type="MENU_FACT",
                    content=f"Catalog signal: {code.replace('_', ' ')} ({status.lower()}).",
                )
                for code, status, evidence_id in positive_signals
            )
            if confirmed_conflicts:
                classifications[menu_id] = (
                    "CONFLICT",
                    "Confirmed animal-derived defining, core, or menu-level ingredients conflict with vegan selection.",
                    claim_references,
                )
            elif possible_conflicts:
                classifications[menu_id] = (
                    "POSSIBLE_WITH_CHECKS",
                    "Vegan suitability needs confirmation because optional or uncertain animal-derived ingredients may be used.",
                    claim_references,
                )
            elif positive_signals:
                classifications[menu_id] = (
                    "LIKELY_FIT",
                    "A vegan-compatible catalog signal exists; confirm the selected options before ordering.",
                    claim_references,
                )
            else:
                classifications[menu_id] = (
                    "UNKNOWN",
                    "Vegan suitability is not confirmed; check the ingredients and selected options before ordering.",
                    claim_references,
                )
        return classifications

    @classmethod
    def _structured_objective_candidates(
        cls,
        connection: sqlite3.Connection,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        *,
        release_family_id: str,
        eligibility_as_of: datetime,
        menu_ids: list[str] | None = None,
        exclude_history: bool = False,
        enforce_price_bands: bool = True,
    ) -> tuple[
        list[sqlite3.Row],
        dict[str, tuple[str, str]],
        dict[str, tuple[str, str | None, list[EvidenceReference]]],
    ]:
        family = connection.execute(
            """
            SELECT knowledge_release_id,synthetic_enrichment_release_id
            FROM recommendation_release_family
            WHERE release_family_id=?
            """,
            (release_family_id,),
        ).fetchone()
        if family is None:
            raise RuntimeError("RECOMMENDATION_RELEASE_NOT_FOUND")
        parameters: list[Any] = []
        spice_clause = ""
        if criteria.schema_version == "2":
            spice_clause = "AND (menu.spice_level IS NULL OR menu.spice_level<=?)"
            parameters.append(criteria.max_spice_level)
        menu_clause = ""
        if menu_ids is not None:
            unique_ids = list(dict.fromkeys(menu_ids))
            if not unique_ids:
                return [], {}, {}
            menu_clause = f"AND menu.menu_id IN ({','.join('?' for _ in unique_ids)})"
            parameters.extend(unique_ids)
        rows = connection.execute(
            f"""
            SELECT menu.menu_id,menu.merchant_id,menu.name_en,menu.name_ko,
                   menu.category,menu.description,menu.cultural_description,menu.price,
                   menu.spice_level,menu.serves_min,menu.serves_max,menu.is_synthetic,
                   COALESCE(merchant.name_en,merchant.name_ko) AS merchant_name,
                   merchant.delivery_fee,merchant.eta_min,merchant.eta_max,
                   merchant.service_area_id,
                   COALESCE(merchant.min_order_amount,0) AS minimum_order_amount
            FROM menu
            JOIN merchant ON merchant.merchant_id=menu.merchant_id
            WHERE menu.availability='AVAILABLE'
              {spice_clause}
              {menu_clause}
            """,
            parameters,
        ).fetchall()

        session_row = connection.execute(
            "SELECT meal_need_state_json FROM chat_session WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            raise KeyError("SESSION_NOT_FOUND")
        need_state = MealNeedState.model_validate_json(
            str(session_row["meal_need_state_json"] or "{}")
        )
        confirmed_area = connection.execute(
            """
            SELECT address.service_area_id
            FROM cart
            JOIN address_ref address ON address.address_ref_id=cart.address_ref_id
            JOIN service_area area ON area.service_area_id=address.service_area_id
            WHERE cart.session_id=? AND address.confirmed=1 AND area.active=1
            """,
            (session_id,),
        ).fetchone()
        service_area_id = (
            str(confirmed_area["service_area_id"])
            if confirmed_area is not None and confirmed_area["service_area_id"]
            else need_state.service_area_id
        )
        excluded_menu_ids = (
            {
                *need_state.shown_menu_ids,
                *need_state.rejected_menu_ids,
                *([need_state.selected_menu_id] if need_state.selected_menu_id else []),
            }
            if exclude_history
            else set()
        )
        rows = [
            row
            for row in rows
            if str(row["menu_id"]) not in excluded_menu_ids
            and (not service_area_id or str(row["service_area_id"] or "") == service_area_id)
            and (
                not enforce_price_bands
                or (
                    criteria.schema_version == "3"
                    and criteria.price_range_krw is not None
                    and criteria.price_range_krw.min
                    <= int(row["price"])
                    <= criteria.price_range_krw.max
                )
                or (
                    criteria.schema_version == "2"
                    and cls._price_matches_v2(int(row["price"]), criteria.price_bands)
                )
            )
        ]
        if criteria.schema_version == "3":
            synthetic_release_id = str(family["synthetic_enrichment_release_id"] or "")
            if not synthetic_release_id or not rows:
                return [], {}, {}
            baseline = connection.execute(
                """
                SELECT spice_baseline FROM synthetic_country_profile
                WHERE release_id=? AND country_code=?
                """,
                (synthetic_release_id, criteria.spice_reference_country),
            ).fetchone()
            if baseline is None:
                return [], {}, {}
            spice_baseline = int(baseline["spice_baseline"])
            menu_ids_for_profile = [str(row["menu_id"]) for row in rows]
            placeholders = ",".join("?" for _ in menu_ids_for_profile)
            profiles = connection.execute(
                f"""
                SELECT menu_id,spice_level,halal_fit,vegan_fit
                FROM synthetic_menu_profile
                WHERE release_id=? AND menu_id IN ({placeholders})
                """,
                (synthetic_release_id, *menu_ids_for_profile),
            ).fetchall()
            profile_by_menu = {str(profile["menu_id"]): profile for profile in profiles}

            def v3_menu_matches(row: sqlite3.Row) -> bool:
                profile = profile_by_menu.get(str(row["menu_id"]))
                if profile is None:
                    return False
                spice_level = int(profile["spice_level"])
                spice_matches = (
                    spice_level < spice_baseline
                    if criteria.spice_preference == "LESS"
                    else spice_level > spice_baseline
                    if criteria.spice_preference == "MORE"
                    else spice_level == spice_baseline
                )
                return bool(
                    spice_matches
                    and (not criteria.dietary_filters.halal_certified_only or profile["halal_fit"])
                    and (not criteria.dietary_filters.vegan or profile["vegan_fit"])
                )

            filtered_rows: list[sqlite3.Row] = [row for row in rows if v3_menu_matches(row)]
            certifications = {
                menu_id: (synthetic_release_id, "Synthetic halal-friendly profile")
                for menu_id, profile in profile_by_menu.items()
                if profile["halal_fit"]
            }
            synthetic_vegan: dict[str, tuple[str, str | None, list[EvidenceReference]]] = {
                menu_id: (
                    "LIKELY_FIT" if profile["vegan_fit"] else "UNKNOWN",
                    (
                        "The menu profile marks this menu vegan-friendly; "
                        "confirm options before ordering."
                        if profile["vegan_fit"]
                        else "Vegan suitability is not confirmed; check ingredients and options."
                    ),
                    [],
                )
                for menu_id, profile in profile_by_menu.items()
            }
            return filtered_rows, certifications, synthetic_vegan

        halal_certifications = cls._valid_halal_certifications_in_connection(
            connection,
            release_family_id=release_family_id,
            instant=eligibility_as_of.isoformat(),
        )
        if criteria.dietary_filters.halal_certified_only:
            rows = [row for row in rows if str(row["menu_id"]) in halal_certifications]

        vegan = cls._v2_vegan_classifications(
            connection,
            [str(row["menu_id"]) for row in rows],
            knowledge_release_id=str(family["knowledge_release_id"]),
        )
        if criteria.dietary_filters.vegan:
            rows = [
                row
                for row in rows
                if vegan.get(str(row["menu_id"]), ("UNKNOWN", None, []))[0]
                in {"LIKELY_FIT", "POSSIBLE_WITH_CHECKS"}
            ]
        return rows, halal_certifications, vegan

    def get_live_recommendation_menu_states(
        self,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        release_family_id: str,
        menu_ids: list[str],
        *,
        at: datetime,
    ) -> dict[str, LiveRecommendationMenuState]:
        with self._connection() as connection:
            rows, certifications, vegan = self._structured_objective_candidates(
                connection,
                session_id,
                criteria,
                release_family_id=release_family_id,
                eligibility_as_of=at,
                menu_ids=menu_ids,
                enforce_price_bands=False,
            )
        result: dict[str, LiveRecommendationMenuState] = {}
        for row in rows:
            menu_id = str(row["menu_id"])
            certification = certifications.get(menu_id)
            vegan_status, vegan_warning, _ = vegan.get(menu_id, ("UNKNOWN", None, []))
            result[menu_id] = LiveRecommendationMenuState(
                menu=self._menu_summary(
                    row,
                    [],
                    [],
                    EvidenceStatus.UNKNOWN,
                    0.0,
                ),
                halal_certified=bool(certification),
                halal_scope_label=certification[1] if certification else None,
                vegan_status=cast(Any, vegan_status),
                vegan_warning=vegan_warning,
            )
        return result

    @staticmethod
    def _public_rag_chunks(
        connection: sqlite3.Connection,
        release_id: str,
        menu_ids: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
        placeholders = ",".join("?" for _ in unique_ids)
        rows = connection.execute(
            f"""
            SELECT mapping.menu_id,mapping.concept_id AS mapped_concept_id,
                   chunk.chunk_id,chunk.document_id,chunk.concept_id,chunk.facet,
                   chunk.content,chunk.embedding_vector_json,
                   concept.canonical_name_ko,concept.canonical_name_en,concept.aliases_json
            FROM menu_concept_map mapping
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
             AND closure.inherit_claims=1
            JOIN knowledge_chunk chunk
              ON chunk.release_id=closure.release_id
             AND chunk.concept_id=closure.ancestor_concept_id
            JOIN knowledge_document document
              ON document.release_id=chunk.release_id
             AND document.document_id=chunk.document_id
            JOIN dish_concept concept
              ON concept.release_id=chunk.release_id
             AND concept.concept_id=chunk.concept_id
            WHERE mapping.release_id=? AND mapping.mapping_status='MAPPED'
              AND mapping.menu_id IN ({placeholders})
              AND chunk.embedding_vector_json IS NOT NULL
              AND document.review_status IN ('REVIEWED_DEMO','VERIFIED')
              AND (
                json_extract(chunk.metadata_json,'$.recommendation_visibility')='PUBLIC_RAG'
                OR (
                  json_extract(chunk.metadata_json,'$.recommendation_visibility') IS NULL
                  AND lower(chunk.facet)<>'safety'
                )
              )
            ORDER BY mapping.menu_id,closure.depth,chunk.chunk_id
            """,
            (release_id, *unique_ids),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (str(row["menu_id"]), str(row["chunk_id"]))
            if key in seen:
                continue
            seen.add(key)
            grouped[key[0]].append(dict(row))
        return grouped

    def build_recommendation_evidence_pool(
        self,
        session_id: str,
        profile: Profile,
        criteria: RecommendationCriteriaV2,
        mode: RecommendationMode,
        limit: int,
        *,
        release_family_id: str,
        eligibility_as_of: datetime,
        raw_hits_per_value: int,
        passages_per_menu: int,
    ) -> list[EvidencePoolItem]:
        if limit < 1 or raw_hits_per_value < 1 or passages_per_menu < 1:
            return []
        with self._connection() as connection:
            family = connection.execute(
                """
                SELECT family.*,release.embedding_dimension
                FROM recommendation_release_family family
                JOIN knowledge_release release
                  ON release.release_id=family.knowledge_release_id
                WHERE family.release_family_id=? AND release.status='READY'
                """,
                (release_family_id,),
            ).fetchone()
            if family is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
            if str(family["ranking_policy_version"]) == RANKING_POLICY_VERSION:
                concept_pool = self._build_concept_ranked_pool(
                    connection,
                    session_id=session_id,
                    criteria=criteria,
                    profile=profile,
                    mode=mode,
                    limit=limit,
                    family=family,
                    eligibility_as_of=eligibility_as_of,
                    passages_per_menu=passages_per_menu,
                )
                metrics = self._recommendation_retrieval_metrics.get(session_id)
                if metrics is not None:
                    metrics["query_count"] = int(metrics.get("query_count", 0)) + 1
                return concept_pool
            candidate_rows, certifications, vegan = self._structured_objective_candidates(
                connection,
                session_id,
                criteria,
                release_family_id=release_family_id,
                eligibility_as_of=eligibility_as_of,
                exclude_history=mode is RecommendationMode.SIMILAR,
            )
            candidate_rows = candidate_rows[:RECOMMENDATION_CANDIDATE_CAP]
            chunks_by_menu = self._public_rag_chunks(
                connection,
                str(family["knowledge_release_id"]),
                [str(row["menu_id"]) for row in candidate_rows],
            )
            subjective_groups = criteria.subjective_groups()
            query_aliases_by_code: dict[str, tuple[str, ...]] = {}
            for selected in subjective_groups.values():
                for value_code in selected:
                    query_aliases_by_code[value_code] = preference_query_aliases(
                        value_code,
                        profile.preferred_language,
                    )
            if not subjective_groups:
                query_aliases_by_code["__fallback__"] = FALLBACK_RECOMMENDATION_QUERY_ALIASES
            query_values = [
                (code, " ".join(aliases)) for code, aliases in query_aliases_by_code.items()
            ]
            query_vectors = self.embedding_provider.embed(
                [query for _, query in query_values],
                "SEARCH_QUERY",
            )
            if len(query_vectors) != len(query_values):
                raise RuntimeError("PREFERENCE_QUERY_EMBEDDING_COUNT_MISMATCH")
            query_vector_by_code = {
                value_code: vector for (value_code, _), vector in zip(query_values, query_vectors)
            }

            chunk_rows_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for chunks in chunks_by_menu.values():
                for chunk in chunks:
                    chunk_rows_by_id[str(chunk["chunk_id"])].append(chunk)
            ranked_by_code_menu: dict[
                str,
                dict[str, list[tuple[float, dict[str, Any]]]],
            ] = {}
            for value_code, query_aliases in query_aliases_by_code.items():
                query_vector = query_vector_by_code[value_code]
                unique_candidates: list[HybridChunkCandidate] = []
                for chunk_id, associated_rows in chunk_rows_by_id.items():
                    chunk = associated_rows[0]
                    vector = json.loads(str(chunk["embedding_vector_json"]))
                    aliases = (
                        str(chunk["canonical_name_ko"] or ""),
                        str(chunk["canonical_name_en"] or ""),
                        *tuple(
                            str(alias) for alias in json.loads(str(chunk["aliases_json"] or "[]"))
                        ),
                    )
                    unique_candidates.append(
                        HybridChunkCandidate(
                            chunk_id=chunk_id,
                            content=str(chunk["content"]),
                            facet=str(chunk["facet"]),
                            aliases=aliases,
                            vector_similarity=cosine_similarity(query_vector, vector),
                        )
                    )
                ranked_chunks = rank_hybrid_chunks_rrf(
                    query_aliases,
                    unique_candidates,
                    limit=raw_hits_per_value,
                )
                by_menu: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
                for candidate, score in ranked_chunks:
                    for chunk in chunk_rows_by_id[candidate.chunk_id]:
                        by_menu[str(chunk["menu_id"])].append((score, chunk))
                for values in by_menu.values():
                    values.sort(key=lambda item: (-item[0], str(item[1]["chunk_id"])))
                ranked_by_code_menu[value_code] = by_menu

            pool: list[EvidencePoolItem] = []
            for row in candidate_rows:
                menu_id = str(row["menu_id"])
                chunks = chunks_by_menu.get(menu_id, [])
                if not chunks:
                    continue
                criterion_evidence: list[CriterionEvidence] = []
                passage_scores: dict[str, tuple[float, EvidenceReference]] = {}
                category_scores: list[float] = []
                mapped_concept_id: str | None = None
                for category_code, selected_codes in subjective_groups.items():
                    selected_scores: list[float] = []
                    for value_code in selected_codes:
                        ranked = ranked_by_code_menu.get(value_code, {}).get(menu_id, [])
                        if not ranked:
                            continue
                        best_score, best_chunk = ranked[0]
                        mapped_concept_id = str(best_chunk["mapped_concept_id"])
                        reference = EvidenceReference(
                            evidence_id=str(best_chunk["chunk_id"]),
                            evidence_type=(
                                "ESSENTIAL_FACT"
                                if str(best_chunk["facet"]).casefold() == "essential_fact"
                                else "WIKI_PASSAGE"
                            ),
                            content=str(best_chunk["content"]),
                            score=round(max(0.0, min(1.0, best_score)), 6),
                        )
                        criterion_evidence.append(
                            CriterionEvidence(
                                category_code=cast(Any, category_code),
                                selected_value_code=value_code,
                                evidence=[reference],
                            )
                        )
                        selected_scores.append(best_score)
                        current = passage_scores.get(reference.evidence_id)
                        if current is None or best_score > current[0]:
                            passage_scores[reference.evidence_id] = (best_score, reference)
                    if selected_scores:
                        category_scores.append(max(selected_scores))

                if subjective_groups and len(category_scores) != len(subjective_groups):
                    continue
                fallback_score: float | None = None
                if not subjective_groups:
                    for score, chunk in ranked_by_code_menu.get("__fallback__", {}).get(
                        menu_id,
                        [],
                    ):
                        fallback_score = max(fallback_score or 0.0, score)
                        mapped_concept_id = str(chunk["mapped_concept_id"])
                        reference = EvidenceReference(
                            evidence_id=str(chunk["chunk_id"]),
                            evidence_type=(
                                "ESSENTIAL_FACT"
                                if str(chunk["facet"]).casefold() == "essential_fact"
                                else "WIKI_PASSAGE"
                            ),
                            content=str(chunk["content"]),
                            score=round(max(0.0, min(1.0, score)), 6),
                        )
                        passage_scores[reference.evidence_id] = (score, reference)
                if not passage_scores:
                    continue
                wiki_passages = [
                    item[1]
                    for item in sorted(
                        passage_scores.values(),
                        key=lambda item: (-item[0], item[1].evidence_id),
                    )[:passages_per_menu]
                ]
                certification = certifications.get(menu_id)
                vegan_status, vegan_warning, vegan_facts = vegan.get(
                    menu_id,
                    ("UNKNOWN", None, []),
                )
                menu_facts = [
                    EvidenceReference(
                        evidence_id=f"fact_{menu_id}_price",
                        evidence_type="MENU_FACT",
                        content=f"Current base price: KRW {int(row['price']):,}.",
                    ),
                    *vegan_facts,
                ]
                menu_facts.append(
                    EvidenceReference(
                        evidence_id=f"fact_{menu_id}_spice",
                        evidence_type="MENU_FACT",
                        content=(
                            f"Reviewed spice level: {int(row['spice_level'])} of 5."
                            if row["spice_level"] is not None
                            else "The source did not provide a reviewed spice level."
                        ),
                    )
                )
                if certification:
                    menu_facts.append(
                        EvidenceReference(
                            evidence_id=certification[0],
                            evidence_type="CERTIFICATION",
                            content=certification[1],
                        )
                    )
                primary_score = (
                    sum(category_scores) / len(category_scores)
                    if category_scores
                    else fallback_score or 0.5
                )
                soft_ranked = ranked_by_code_menu.get("__profile_soft__", {}).get(
                    menu_id,
                    [],
                )
                retrieval_score = apply_soft_profile_retrieval_signal(
                    primary_score,
                    soft_ranked[0][0] if soft_ranked else None,
                )
                risks = [vegan_warning] if criteria.dietary_filters.vegan and vegan_warning else []
                reasons = [
                    f"Matches selected {category.replace('_', ' ')}"
                    for category in subjective_groups
                ] or ["Matches the selected objective filters"]
                menu = self._menu_summary(
                    row,
                    reasons,
                    risks,
                    EvidenceStatus.VERIFIED if certification else EvidenceStatus.UNKNOWN,
                    retrieval_score,
                ).model_copy(
                    update={
                        "dietary_summary": (
                            "A valid halal certification scope is recorded for this menu."
                            if certification
                            else "No halal certification is recorded for this menu."
                        ),
                        "risk_hints": risks,
                        "evidence_ids": [fact.evidence_id for fact in menu_facts],
                        "grounded_claim_ids": [fact.evidence_id for fact in menu_facts],
                        "grounded_passage_ids": [item.evidence_id for item in wiki_passages],
                    }
                )
                pool.append(
                    EvidencePoolItem(
                        menu=menu,
                        knowledge_concept_id=mapped_concept_id,
                        criterion_evidence=criterion_evidence,
                        wiki_passages=wiki_passages,
                        menu_facts=menu_facts,
                        halal_certified=bool(certification),
                        halal_scope_label=certification[1] if certification else None,
                        vegan_status=cast(Any, vegan_status),
                        vegan_warning=vegan_warning,
                        retrieval_score=round(max(0.0, min(1.0, retrieval_score)), 6),
                        knowledge_release_id=str(family["knowledge_release_id"]),
                        catalog_release_id=str(family["catalog_release_id"]),
                        recommendation_release_family_id=str(family["release_family_id"]),
                    )
                )
        return sorted(
            pool,
            key=lambda item: (-item.retrieval_score, item.menu.price, item.menu.menu_id),
        )[:limit]

    @staticmethod
    def _structured_session_filters(
        connection: sqlite3.Connection,
        session_id: str,
        *,
        exclude_history: bool,
    ) -> tuple[str | None, set[str]]:
        session_row = connection.execute(
            "SELECT meal_need_state_json FROM chat_session WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            raise KeyError("SESSION_NOT_FOUND")
        need_state = MealNeedState.model_validate_json(
            str(session_row["meal_need_state_json"] or "{}")
        )
        confirmed_area = connection.execute(
            """
            SELECT address.service_area_id
            FROM cart
            JOIN address_ref address ON address.address_ref_id=cart.address_ref_id
            JOIN service_area area ON area.service_area_id=address.service_area_id
            WHERE cart.session_id=? AND address.confirmed=1 AND area.active=1
            """,
            (session_id,),
        ).fetchone()
        service_area_id = (
            str(confirmed_area["service_area_id"])
            if confirmed_area is not None and confirmed_area["service_area_id"]
            else need_state.service_area_id
        )
        excluded = set()
        if exclude_history:
            excluded.update(need_state.shown_menu_ids)
            excluded.update(need_state.rejected_menu_ids)
            if need_state.selected_menu_id:
                excluded.add(need_state.selected_menu_id)
        return service_area_id, excluded

    @staticmethod
    def _concept_support_rows(
        connection: sqlite3.Connection,
        *,
        release_id: str,
        menu_ids: list[str],
        criteria: RecommendationCriteriaV2,
    ) -> list[sqlite3.Row]:
        if not menu_ids or not criteria.subjective_groups():
            return []
        selected = [
            (category, option)
            for category, options in criteria.subjective_groups().items()
            for option in options
        ]
        selected_predicates = " OR ".join(
            "(support.category_code=? AND support.option_code=?)" for _ in selected
        )
        placeholders = ",".join("?" for _ in menu_ids)
        parameters: list[Any] = [release_id, *menu_ids]
        for category, option in selected:
            parameters.extend((category, option))
        return connection.execute(
            f"""
            SELECT feature.menu_id,feature.category_code,feature.option_code,
                   feature.support_strength,evidence.evidence_id,
                   feature.review_status,evidence.excerpt AS content,
                   evidence.source_type AS facet,feature.evidence_scope
            FROM menu_preference_feature feature
            JOIN menu_preference_feature_evidence evidence
              ON evidence.knowledge_release_id=feature.knowledge_release_id
             AND evidence.feature_id=feature.feature_id
             AND evidence.evidence_role='SUPPORT'
            WHERE feature.knowledge_release_id=?
              AND feature.support_status='SUPPORTED'
              AND feature.evidence_scope='MENU_DIRECT'
              AND feature.menu_id IN ({placeholders})
              AND ({selected_predicates.replace("support.", "feature.")})
            UNION ALL
            SELECT membership.menu_id,support.category_code,support.option_code,
                   support.support_strength*0.65 AS support_strength,
                   support.evidence_chunk_id AS evidence_id,
                   support.review_status,chunk.content,chunk.facet,
                   'CONCEPT_GENERAL' AS evidence_scope
            FROM menu_concept_membership membership
            JOIN concept_preference_support support
              ON support.knowledge_release_id=membership.knowledge_release_id
             AND support.concept_id=membership.concept_id
             AND support.support_status='SUPPORTED'
            JOIN knowledge_chunk chunk
              ON chunk.release_id=support.knowledge_release_id
             AND chunk.chunk_id=support.evidence_chunk_id
            WHERE membership.knowledge_release_id=?
              AND membership.menu_id IN ({placeholders})
              AND ({selected_predicates})
              AND NOT EXISTS (
                SELECT 1 FROM menu_preference_feature contradiction
                WHERE contradiction.knowledge_release_id=membership.knowledge_release_id
                  AND contradiction.menu_id=membership.menu_id
                  AND contradiction.category_code=support.category_code
                  AND contradiction.option_code=support.option_code
                  AND contradiction.support_status='CONTRADICTED'
                  AND contradiction.evidence_scope='MENU_DIRECT'
              )
            ORDER BY menu_id,category_code,support_strength DESC,option_code,evidence_id
            """,
            [*parameters, *parameters],
        ).fetchall()

    @staticmethod
    def _final_concept_wiki_rows(
        connection: sqlite3.Connection,
        *,
        release_id: str,
        menu_ids: list[str],
        criteria: RecommendationCriteriaV2,
        preferred_evidence_ids_by_menu: dict[str, set[str]],
        passages_per_menu: int,
    ) -> dict[str, list[sqlite3.Row]]:
        if not menu_ids:
            return {}
        placeholders = ",".join("?" for _ in menu_ids)
        rows = connection.execute(
            f"""
            SELECT membership.menu_id,chunk.chunk_id,chunk.content,chunk.facet,
                   closure.depth,chunk.chunk_index,
                   membership.concept_id AS member_concept_id,
                   membership.membership_role,
                   member_concept.canonical_name_ko AS component_name_ko,
                   member_concept.canonical_name_en AS component_name_en
              FROM menu_concept_membership membership
              JOIN dish_concept member_concept
                ON member_concept.release_id=membership.knowledge_release_id
               AND member_concept.concept_id=membership.concept_id
              JOIN dish_concept_closure closure
                ON closure.release_id=membership.knowledge_release_id
               AND closure.descendant_concept_id=membership.concept_id
               AND closure.inherit_claims=1
              JOIN knowledge_chunk chunk
                ON chunk.release_id=closure.release_id
               AND chunk.concept_id=closure.ancestor_concept_id
              JOIN knowledge_document document
                ON document.release_id=chunk.release_id
               AND document.document_id=chunk.document_id
              WHERE membership.knowledge_release_id=?
                AND membership.menu_id IN ({placeholders})
                AND document.source_type='SYNTHETIC_WIKI'
                AND document.review_status='REVIEWED_DEMO'
                AND lower(chunk.facet)<>'safety'
                AND (
                  json_extract(chunk.metadata_json,'$.recommendation_visibility')='PUBLIC_RAG'
                  OR json_extract(chunk.metadata_json,'$.recommendation_visibility') IS NULL
                )
            ORDER BY membership.menu_id,closure.depth,chunk.chunk_index,chunk.chunk_id
            """,
            (release_id, *menu_ids),
        ).fetchall()
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            grouped[str(row["menu_id"])].append(row)
        return {
            menu_id: rank_component_wiki_passages(
                rows,
                selected_groups=criteria.subjective_groups(),
                preferred_evidence_ids=preferred_evidence_ids_by_menu.get(menu_id, set()),
                limit=passages_per_menu,
            )
            for menu_id, rows in grouped.items()
        }

    @staticmethod
    def _menu_component_rows(
        connection: sqlite3.Connection,
        *,
        release_id: str,
        menu_ids: list[str],
    ) -> dict[str, list[dict[str, str]]]:
        if not menu_ids:
            return {}
        placeholders = ",".join("?" for _ in menu_ids)
        rows = connection.execute(
            f"""
            SELECT membership.menu_id,membership.concept_id,
                   concept.canonical_name_ko,concept.canonical_name_en
            FROM menu_concept_membership membership
            JOIN dish_concept concept
              ON concept.release_id=membership.knowledge_release_id
             AND concept.concept_id=membership.concept_id
            WHERE membership.knowledge_release_id=?
              AND membership.membership_role='COMPONENT'
              AND membership.menu_id IN ({placeholders})
            ORDER BY membership.menu_id,membership.concept_id
            """,
            (release_id, *menu_ids),
        ).fetchall()
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[str(row["menu_id"])].append(
                {
                    "component_id": str(row["concept_id"]),
                    "name_ko": str(row["canonical_name_ko"]),
                    "name_en": str(row["canonical_name_en"]),
                }
            )
        return grouped

    def _build_concept_ranked_pool(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        profile: Profile,
        mode: RecommendationMode,
        limit: int,
        family: sqlite3.Row,
        eligibility_as_of: datetime,
        passages_per_menu: int,
    ) -> list[EvidencePoolItem]:
        pipeline_started = monotonic()
        query_count = 0
        session_filter_started = monotonic()
        service_area_id, excluded = self._structured_session_filters(
            connection,
            session_id,
            exclude_history=mode in {RecommendationMode.SIMILAR, RecommendationMode.RETRY},
        )
        query_count += 2
        session_filter_ms = int((monotonic() - session_filter_started) * 1000)
        channel_limit = max(3, limit)
        query_text = (
            " ".join(
                alias
                for selected_codes in criteria.subjective_groups().values()
                for code in selected_codes
                # Structured preference codes are language-neutral.  Use one
                # canonical bilingual alias pack so an otherwise identical Korean
                # and English request has the same semantic retrieval channel.
                for alias in preference_query_aliases(code, "English")
            )
            or "meal menu"
        )
        semantic_channel_active = bool(
            str(family["embedding_model"]) == self.embedding_provider.model
            and str(family["embedding_version"]) == self.embedding_provider.version
        )
        semantic_channel_status = "ACTIVE" if semantic_channel_active else "DISABLED_MODEL_MISMATCH"
        query_sparse_vector = (
            deterministic_sparse_embedding(f"query: {query_text}")
            if semantic_channel_active
            else ()
        )
        objective_started = monotonic()
        if criteria.subjective_groups():
            feature_query = build_candidate_recall_channel_query(
                dialect="sqlite",
                criteria=criteria,
                knowledge_release_id=str(family["knowledge_release_id"]),
                certification_release_id=str(family["certification_release_id"]),
                synthetic_enrichment_release_id=(
                    str(family["synthetic_enrichment_release_id"])
                    if family["synthetic_enrichment_release_id"]
                    else None
                ),
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of.isoformat(),
                candidate_limit=channel_limit,
                support_channel="MENU_FEATURE",
            )
            feature_rows = connection.execute(
                feature_query.sql, feature_query.parameters
            ).fetchall()
            concept_query = build_candidate_recall_channel_query(
                dialect="sqlite",
                criteria=criteria,
                knowledge_release_id=str(family["knowledge_release_id"]),
                certification_release_id=str(family["certification_release_id"]),
                synthetic_enrichment_release_id=(
                    str(family["synthetic_enrichment_release_id"])
                    if family["synthetic_enrichment_release_id"]
                    else None
                ),
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of.isoformat(),
                candidate_limit=channel_limit,
                support_channel="CONCEPT_SUPPORT",
            )
            concept_rows = connection.execute(
                concept_query.sql, concept_query.parameters
            ).fetchall()
            query_count += 2
        else:
            # With no selected preference value there is no feature channel to
            # recall. Keep one reviewed-concept objective population.
            feature_rows = []
            concept_query = build_candidate_recall_channel_query(
                dialect="sqlite",
                criteria=criteria,
                knowledge_release_id=str(family["knowledge_release_id"]),
                certification_release_id=str(family["certification_release_id"]),
                synthetic_enrichment_release_id=(
                    str(family["synthetic_enrichment_release_id"])
                    if family["synthetic_enrichment_release_id"]
                    else None
                ),
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of.isoformat(),
                candidate_limit=channel_limit,
                support_channel="CONCEPT_SUPPORT",
            )
            concept_rows = connection.execute(
                concept_query.sql, concept_query.parameters
            ).fetchall()
            query_count += 1
        if semantic_channel_active:
            semantic_query = build_semantic_candidate_query(
                dialect="sqlite",
                criteria=criteria,
                knowledge_release_id=str(family["knowledge_release_id"]),
                certification_release_id=str(family["certification_release_id"]),
                synthetic_enrichment_release_id=(
                    str(family["synthetic_enrichment_release_id"])
                    if family["synthetic_enrichment_release_id"]
                    else None
                ),
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of.isoformat(),
                candidate_limit=channel_limit,
            )
            semantic_rows = connection.execute(
                semantic_query.sql,
                semantic_query.parameters,
            ).fetchall()
            semantic_ranked = sorted(
                (
                    (
                        max(
                            0.0,
                            min(
                                1.0,
                                sparse_cosine_similarity(
                                    query_sparse_vector,
                                    deterministic_sparse_embedding(
                                        f"document: {str(row['semantic_text'] or '')}"
                                    ),
                                ),
                            ),
                        ),
                        row,
                    )
                    for row in semantic_rows
                ),
                key=lambda item: (
                    -item[0],
                    str(item[1]["merchant_id"]),
                    str(item[1]["menu_id"]),
                ),
            )[:channel_limit]
        else:
            semantic_ranked = []
        feature_channel_ids = [str(row["menu_id"]) for row in feature_rows]
        concept_channel_ids = [str(row["menu_id"]) for row in concept_rows]
        semantic_channel_ids = [str(row["menu_id"]) for _score, row in semantic_ranked]
        named_channels = {
            "MENU_FEATURE": feature_channel_ids,
            "CONCEPT_SUPPORT": concept_channel_ids,
            "SEMANTIC": semantic_channel_ids,
        }
        channel_fusion_by_menu = candidate_channel_fusion_trace(named_channels)
        raw_channel_union_count = len(
            set(feature_channel_ids) | set(concept_channel_ids) | set(semantic_channel_ids)
        )
        channel_union_ids = merge_candidate_channels(
            list(named_channels.values()),
            limit=channel_limit,
        )
        candidate_rows: list[sqlite3.Row] = []
        if channel_union_ids:
            grounded_query = build_concept_candidate_query(
                dialect="sqlite",
                criteria=criteria,
                knowledge_release_id=str(family["knowledge_release_id"]),
                certification_release_id=str(family["certification_release_id"]),
                synthetic_enrichment_release_id=(
                    str(family["synthetic_enrichment_release_id"])
                    if family["synthetic_enrichment_release_id"]
                    else None
                ),
                service_area_id=service_area_id,
                excluded_menu_ids=excluded,
                eligibility_as_of=eligibility_as_of.isoformat(),
                candidate_limit=None,
                included_menu_ids=channel_union_ids,
            )
            candidate_rows = connection.execute(
                grounded_query.sql,
                grounded_query.parameters,
            ).fetchall()
        query_count += int(semantic_channel_active) + int(bool(channel_union_ids))
        objective_sql_ms = int((monotonic() - objective_started) * 1000)
        if not candidate_rows:
            self._recommendation_retrieval_metrics[session_id] = {
                "session_filter_ms": session_filter_ms,
                "objective_sql_ms": objective_sql_ms,
                "support_lookup_ms": 0,
                "scoring_rerank_ms": 0,
                "evidence_ms": 0,
                "query_count": query_count,
                "selected_category_count": len(criteria.subjective_groups()),
                "explicit_channel_count": len(set(feature_channel_ids) | set(concept_channel_ids)),
                "menu_feature_channel_count": len(feature_channel_ids),
                "concept_support_channel_count": len(concept_channel_ids),
                "semantic_channel_count": len(semantic_channel_ids),
                "semantic_channel_status": semantic_channel_status,
                "raw_channel_union_count": raw_channel_union_count,
                "channel_union_count": len(channel_union_ids),
                "fetched_candidate_count": 0,
                "candidate_merchant_count": 0,
                "candidate_concept_count": 0,
                "support_row_count": 0,
                "wiki_row_count": 0,
                "pipeline_ms": int((monotonic() - pipeline_started) * 1000),
            }
            return []
        candidate_by_id = {str(row["menu_id"]): row for row in candidate_rows}
        support_started = monotonic()
        support_rows = self._concept_support_rows(
            connection,
            release_id=str(family["knowledge_release_id"]),
            menu_ids=list(candidate_by_id),
            criteria=criteria,
        )
        if criteria.subjective_groups():
            query_count += 1
        support_lookup_ms = int((monotonic() - support_started) * 1000)
        supports_by_menu: dict[str, dict[str, tuple[float, sqlite3.Row]]] = defaultdict(dict)
        for support in support_rows:
            menu_id = str(support["menu_id"])
            category = str(support["category_code"])
            current = supports_by_menu[menu_id].get(category)
            strength = float(support["support_strength"])
            if current is None or strength > current[0]:
                supports_by_menu[menu_id][category] = (strength, support)
        signal_rows = connection.execute(
            f"""
            SELECT menu.menu_id,menu.semantic_text,
                   COALESCE(menu_source.review_count,merchant_source.review_count,0)
                     AS review_count,
                   merchant_source.review_average
            FROM menu
            LEFT JOIN menu_source_detail menu_source ON menu_source.menu_id=menu.menu_id
            LEFT JOIN merchant_source_detail merchant_source
              ON merchant_source.merchant_id=menu.merchant_id
            WHERE menu.menu_id IN ({",".join("?" for _ in candidate_by_id)})
            ORDER BY menu.menu_id
            """,
            tuple(sorted(candidate_by_id)),
        ).fetchall()
        # SQLite is the offline/test mirror and has no native VECTOR column. Use
        # the deterministic on-read strategy advertised by readiness so a request
        # never sends every candidate menu back to the external embedding API.
        # Production Oracle embeds only the query and compares it with the
        # already-persisted Cohere menu vectors through VECTOR_DISTANCE.
        ordered_signal_rows = list(signal_rows)
        signals_by_menu: dict[str, tuple[float, float]] = {}
        for row in ordered_signal_rows:
            signals_by_menu[str(row["menu_id"])] = (
                (
                    max(
                        0.0,
                        min(
                            1.0,
                            sparse_cosine_similarity(
                                query_sparse_vector,
                                deterministic_sparse_embedding(
                                    f"document: {str(row['semantic_text'] or '')}"
                                ),
                            ),
                        ),
                    )
                    if semantic_channel_active
                    else 0.0
                ),
                bayesian_review_prior(
                    int(row["review_count"] or 0),
                    float(row["review_average"]) if row["review_average"] is not None else None,
                ),
            )
        rank_inputs = []
        for row in candidate_rows:
            menu_id = str(row["menu_id"])
            category_supports = {
                category: strength
                for category, (strength, _support) in supports_by_menu.get(menu_id, {}).items()
            }
            if not category_supports:
                category_supports = {"__objective__": 1.0}
            semantic_score, review_prior = signals_by_menu.get(menu_id, (0.0, 0.5))
            rank_inputs.append(
                ConceptRankCandidate(
                    menu_id=menu_id,
                    merchant_id=str(row["merchant_id"]),
                    concept_id=str(row["concept_id"]),
                    category_supports=category_supports,
                    reviewed_evidence_count=int(row["reviewed_evidence_count"]),
                    semantic_score=semantic_score,
                    direct_evidence_ratio=float(row["direct_evidence_ratio"]),
                    review_prior=review_prior,
                )
            )
        scoring_started = monotonic()
        decisions = rank_concept_candidates(
            rank_inputs,
            has_soft_profile=False,
            limit=limit,
        )
        scoring_rerank_ms = int((monotonic() - scoring_started) * 1000)
        evidence_started = monotonic()
        wiki_by_menu = self._final_concept_wiki_rows(
            connection,
            release_id=str(family["knowledge_release_id"]),
            menu_ids=[decision.menu_id for decision in decisions],
            criteria=criteria,
            preferred_evidence_ids_by_menu={
                menu_id: {
                    str(support["evidence_id"])
                    for _category, (_strength, support) in supports.items()
                    if str(support["evidence_scope"]) == "CONCEPT_GENERAL"
                }
                for menu_id, supports in supports_by_menu.items()
            },
            passages_per_menu=passages_per_menu,
        )
        components_by_menu = self._menu_component_rows(
            connection,
            release_id=str(family["knowledge_release_id"]),
            menu_ids=[decision.menu_id for decision in decisions],
        )
        if decisions:
            query_count += 2
        synthetic_by_menu: dict[str, sqlite3.Row] = {}
        synthetic_reviews_by_menu: dict[str, list[dict[str, Any]]] = defaultdict(list)
        synthetic_release_id = (
            str(family["synthetic_enrichment_release_id"])
            if family["synthetic_enrichment_release_id"]
            else None
        )
        country_code = profile.country_code or "ZZ"
        spice_reference_country = criteria.spice_reference_country
        requested_locale = normalize_preference_locale(profile.preferred_language)
        presentation_locale = requested_locale if requested_locale in {"ko", "ja"} else "en"
        if decisions and synthetic_release_id:
            selected_ids = [decision.menu_id for decision in decisions]
            placeholders = ",".join("?" for _ in selected_ids)
            synthetic_rows = connection.execute(
                f"""
                SELECT profile.menu_id,profile.spice_level,profile.halal_fit,
                       profile.vegan_fit,localization.display_name,
                       localization.source_hash AS menu_localization_source_hash,
                       description_localization.description_text
                         AS localized_source_description,
                       description_localization.source_hash
                         AS source_description_source_hash,
                       preference.preference_percent,preference.sample_size,
                       country.spice_baseline
                FROM synthetic_menu_profile profile
                JOIN synthetic_country_profile country
                  ON country.release_id=profile.release_id
                 AND country.country_code=?
                LEFT JOIN menu_localization localization
                  ON localization.release_id=profile.release_id
                 AND localization.menu_id=profile.menu_id
                 AND localization.language_code=?
                 AND localization.validation_status='VALID'
                LEFT JOIN menu_source_description_localization description_localization
                  ON description_localization.release_id=profile.release_id
                 AND description_localization.menu_id=profile.menu_id
                 AND description_localization.language_code=?
                 AND description_localization.validation_status='VALID'
                LEFT JOIN synthetic_menu_country_preference preference
                  ON preference.release_id=profile.release_id
                 AND preference.menu_id=profile.menu_id
                 AND preference.country_code=?
                WHERE profile.release_id=?
                  AND profile.menu_id IN ({placeholders})
                """,
                (
                    spice_reference_country,
                    presentation_locale,
                    presentation_locale,
                    country_code,
                    synthetic_release_id,
                    *selected_ids,
                ),
            ).fetchall()
            synthetic_by_menu = {str(item["menu_id"]): item for item in synthetic_rows}
            review_rows = connection.execute(
                f"""
                SELECT review_id,menu_id,topic,rating,review_text,display_order
                FROM synthetic_review_snippet
                WHERE release_id=? AND menu_id IN ({placeholders})
                ORDER BY menu_id,display_order,review_id
                """,
                (synthetic_release_id, *selected_ids),
            ).fetchall()
            for review in review_rows:
                synthetic_reviews_by_menu[str(review["menu_id"])].append(
                    {
                        "review_id": str(review["review_id"]),
                        "topic": str(review["topic"]),
                        "rating": int(review["rating"]),
                        "review_text": str(review["review_text"]),
                    }
                )
            query_count += 2
        pool: list[EvidencePoolItem] = []
        for decision in decisions:
            row = candidate_by_id[decision.menu_id]
            synthetic = synthetic_by_menu.get(decision.menu_id)
            wiki_passages = [
                EvidenceReference(
                    evidence_id=str(chunk["chunk_id"]),
                    evidence_type="WIKI_PASSAGE",
                    content=str(chunk["content"]),
                    component_id=str(chunk["member_concept_id"]),
                    component_name_ko=str(chunk["component_name_ko"]),
                    component_name_en=str(chunk["component_name_en"]),
                    membership_role=cast(
                        Literal["PRIMARY", "COMPONENT", "SECONDARY"],
                        str(chunk["membership_role"]),
                    ),
                )
                for chunk in wiki_by_menu.get(decision.menu_id, [])
            ]
            if not wiki_passages and not criteria.subjective_groups():
                continue
            criterion_evidence = []
            direct_feature_facts: list[EvidenceReference] = []
            for category, (_strength, support) in sorted(
                supports_by_menu.get(decision.menu_id, {}).items()
            ):
                reference = EvidenceReference(
                    evidence_id=str(support["evidence_id"]),
                    evidence_type=(
                        "MENU_FACT"
                        if str(support["evidence_scope"]) == "MENU_DIRECT"
                        else "WIKI_PASSAGE"
                    ),
                    content=str(support["content"]),
                    score=round(float(support["support_strength"]), 6),
                )
                criterion_evidence.append(
                    CriterionEvidence(
                        category_code=cast(Any, category),
                        selected_value_code=str(support["option_code"]),
                        evidence=[reference],
                    )
                )
                if reference.evidence_type == "MENU_FACT":
                    direct_feature_facts.append(reference)
            facts = [
                EvidenceReference(
                    evidence_id=f"fact_{decision.menu_id}_price",
                    evidence_type="MENU_FACT",
                    content=f"Current base price: KRW {int(row['price']):,}.",
                ),
                EvidenceReference(
                    evidence_id=f"fact_{decision.menu_id}_spice",
                    evidence_type="MENU_FACT",
                    content=(
                        f"Internal spice level: {int(synthetic['spice_level'])} of 5."
                        if synthetic is not None
                        else f"Reviewed spice level: {int(row['spice_level'])} of 5."
                        if row["spice_level"] is not None
                        else "The source did not provide a reviewed spice level."
                    ),
                ),
                *direct_feature_facts,
            ]
            channel_fusion = channel_fusion_by_menu.get(
                decision.menu_id,
                {"channel_ranks": {}, "rrf_contributions": {}, "rrf_score": 0.0},
            )
            retrieval_channels = [
                channel for channel in named_channels if channel in channel_fusion["channel_ranks"]
            ]
            trace = {
                **decision.trace_payload(),
                "qualified_candidate_count": len(candidate_rows),
                "support_manifest_sha256": str(family["support_manifest_sha256"]),
                "feature_manifest_sha256": str(family["feature_manifest_sha256"]),
                "semantic_channel_status": semantic_channel_status,
                "retrieval_channels": retrieval_channels,
                "channel_fusion": channel_fusion,
                "channel_candidate_counts": {
                    "menu_feature": len(feature_channel_ids),
                    "concept_support": len(concept_channel_ids),
                    "semantic": len(semantic_channel_ids),
                    "raw_union": raw_channel_union_count,
                    "bounded_union_before_grounding": len(channel_union_ids),
                },
            }
            menu = self._menu_summary(
                row,
                [
                    f"Matches selected {item.category_code.replace('_', ' ')}"
                    for item in criterion_evidence
                ]
                or ["Matches the selected objective filters"],
                [],
                EvidenceStatus.UNKNOWN,
                decision.score,
            ).model_copy(
                update={
                    "evidence_ids": [fact.evidence_id for fact in facts],
                    "grounded_claim_ids": [fact.evidence_id for fact in facts],
                    "grounded_passage_ids": [passage.evidence_id for passage in wiki_passages],
                }
            )
            pool.append(
                EvidencePoolItem(
                    menu=menu,
                    knowledge_concept_id=decision.concept_id,
                    criterion_evidence=criterion_evidence,
                    wiki_passages=wiki_passages,
                    menu_facts=facts,
                    halal_certified=(
                        bool(synthetic["halal_fit"])
                        if synthetic is not None
                        else True
                        if criteria.dietary_filters.halal_certified_only
                        else None
                    ),
                    vegan_status=(
                        "LIKELY_FIT"
                        if synthetic is not None and bool(synthetic["vegan_fit"])
                        else "UNKNOWN"
                    ),
                    localized_title=(
                        str(synthetic["display_name"])
                        if synthetic is not None and synthetic["display_name"]
                        else menu.name_ko
                        if presentation_locale == "ko"
                        else menu.name_en
                    ),
                    localized_source_description=(
                        str(synthetic["localized_source_description"])
                        if synthetic is not None and synthetic["localized_source_description"]
                        else menu.description
                    ),
                    menu_localization_source_hash=(
                        str(synthetic["menu_localization_source_hash"])
                        if synthetic is not None and synthetic["menu_localization_source_hash"]
                        else None
                    ),
                    source_description_source_hash=(
                        str(synthetic["source_description_source_hash"])
                        if synthetic is not None and synthetic["source_description_source_hash"]
                        else None
                    ),
                    synthetic_spice_level=(
                        int(synthetic["spice_level"]) if synthetic is not None else None
                    ),
                    country_spice_baseline=(
                        int(synthetic["spice_baseline"]) if synthetic is not None else None
                    ),
                    country_preference=(
                        {
                            "country_code": country_code,
                            "preference_percent": int(synthetic["preference_percent"]),
                            "sample_size": int(synthetic["sample_size"]),
                        }
                        if synthetic is not None and synthetic["preference_percent"] is not None
                        else None
                    ),
                    synthetic_reviews=synthetic_reviews_by_menu.get(decision.menu_id, []),
                    menu_components=components_by_menu.get(decision.menu_id, []),
                    retrieval_score=decision.score,
                    server_rank=decision.rank,
                    explicit_score=decision.explicit_score,
                    semantic_score=decision.semantic_score,
                    min_category_support=decision.min_category_support,
                    reviewed_evidence_count=decision.reviewed_evidence_count,
                    ranking_trace=trace,
                    knowledge_release_id=str(family["knowledge_release_id"]),
                    catalog_release_id=str(family["catalog_release_id"]),
                    recommendation_release_family_id=str(family["release_family_id"]),
                    synthetic_enrichment_release_id=synthetic_release_id,
                )
            )
        evidence_ms = int((monotonic() - evidence_started) * 1000)
        self._recommendation_retrieval_metrics[session_id] = {
            "session_filter_ms": session_filter_ms,
            "objective_sql_ms": objective_sql_ms,
            "support_lookup_ms": support_lookup_ms,
            "scoring_rerank_ms": scoring_rerank_ms,
            "evidence_ms": evidence_ms,
            "query_count": query_count,
            "selected_category_count": len(criteria.subjective_groups()),
            "explicit_channel_count": len(set(feature_channel_ids) | set(concept_channel_ids)),
            "menu_feature_channel_count": len(feature_channel_ids),
            "concept_support_channel_count": len(concept_channel_ids),
            "semantic_channel_count": len(semantic_channel_ids),
            "semantic_channel_status": semantic_channel_status,
            "raw_channel_union_count": raw_channel_union_count,
            "channel_union_count": len(channel_union_ids),
            "fetched_candidate_count": len(candidate_rows),
            "candidate_merchant_count": len({str(row["merchant_id"]) for row in candidate_rows}),
            "candidate_concept_count": len({str(row["concept_id"]) for row in candidate_rows}),
            "support_row_count": len(support_rows),
            "wiki_row_count": sum(len(rows) for rows in wiki_by_menu.values()),
            "pipeline_ms": int((monotonic() - pipeline_started) * 1000),
        }
        return pool

    def preview_recommendation(
        self,
        session_id: str,
        criteria: RecommendationCriteriaV2,
        *,
        release_family_id: str | None = None,
        exclude_history: bool = False,
    ) -> RecommendationPreviewV2:
        started = monotonic()
        with self._connection() as connection:
            if release_family_id is None:
                family = connection.execute(
                    """
                    SELECT family.* FROM recommendation_runtime_state state
                    JOIN recommendation_release_family family
                      ON family.release_family_id=state.active_release_family_id
                    WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                    """
                ).fetchone()
            else:
                family = connection.execute(
                    "SELECT * FROM recommendation_release_family WHERE release_family_id=?",
                    (release_family_id,),
                ).fetchone()
            if family is None:
                raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
            unsupported_reasons: list[str] = []
            release_id = str(family["knowledge_release_id"])
            synthetic_release_id = (
                str(family["synthetic_enrichment_release_id"])
                if family["synthetic_enrichment_release_id"]
                else None
            )
            if criteria.schema_version == "3" and synthetic_release_id is None:
                unsupported_reasons.append("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            if criteria.schema_version == "2" and criteria.dietary_filters.halal_certified_only:
                halal_menus = len(
                    self._valid_halal_certifications_in_connection(
                        connection,
                        release_family_id=str(family["release_family_id"]),
                        instant=_now(),
                    )
                )
                if halal_menus < 3:
                    unsupported_reasons.append("HALAL_CERTIFICATION_UNAVAILABLE")
            if criteria.schema_version == "2" and criteria.dietary_filters.vegan:
                vegan_capability = connection.execute(
                    """
                    SELECT COUNT(DISTINCT menu.menu_id) vegan_menus,
                           COUNT(DISTINCT menu.merchant_id) vegan_merchants
                    FROM menu_concept_map mapping
                    JOIN menu ON menu.menu_id=mapping.menu_id
                      AND menu.availability='AVAILABLE'
                    JOIN menu_dietary_attribute relation
                      ON relation.menu_id=menu.menu_id
                     AND upper(relation.status)='VERIFIED'
                    JOIN dietary_attribute attribute
                      ON attribute.attribute_id=relation.attribute_id
                     AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                    WHERE mapping.release_id=? AND mapping.mapping_status='MAPPED'
                      AND mapping.confidence_band='high'
                    """,
                    (release_id,),
                ).fetchone()
                if not (
                    vegan_capability
                    and int(vegan_capability["vegan_menus"] or 0) >= 3
                    and int(vegan_capability["vegan_merchants"] or 0) >= 2
                ):
                    unsupported_reasons.append("VEGAN_EVIDENCE_UNAVAILABLE")
            if criteria.schema_version == "2" and criteria.max_spice_level < 5:
                spice_capability = connection.execute(
                    """
                    SELECT COUNT(DISTINCT menu.menu_id) spice_menus,
                           COUNT(DISTINCT menu.merchant_id) spice_merchants
                    FROM menu_concept_map mapping
                    JOIN menu ON menu.menu_id=mapping.menu_id
                      AND menu.availability='AVAILABLE'
                    WHERE mapping.release_id=? AND mapping.mapping_status='MAPPED'
                      AND mapping.confidence_band='high'
                      AND menu.spice_status IN ('REVIEWED','VERIFIED')
                      AND menu.spice_level IS NOT NULL
                    """,
                    (release_id,),
                ).fetchone()
                if not (
                    spice_capability
                    and int(spice_capability["spice_menus"] or 0) >= 3
                    and int(spice_capability["spice_merchants"] or 0) >= 2
                ):
                    unsupported_reasons.append("SPICE_LEVEL_UNAVAILABLE")
            service_area_id, excluded = self._structured_session_filters(
                connection, session_id, exclude_history=exclude_history
            )
            if unsupported_reasons:
                menu_count = 0
                merchant_count = 0
                reasons = unsupported_reasons
            else:
                preview_query = build_concept_preview_count_query(
                    dialect="sqlite",
                    criteria=criteria,
                    knowledge_release_id=str(family["knowledge_release_id"]),
                    certification_release_id=str(family["certification_release_id"]),
                    synthetic_enrichment_release_id=synthetic_release_id,
                    service_area_id=service_area_id,
                    excluded_menu_ids=excluded,
                    eligibility_as_of=_now(),
                )
                counts = connection.execute(preview_query.sql, preview_query.parameters).fetchone()
                menu_count = int(counts["eligible_menu_count"] if counts else 0)
                merchant_count = int(counts["eligible_merchant_count"] if counts else 0)
                reasons = ["NO_SUPPORTED_CONCEPT_COMBINATION"] if menu_count == 0 else []
        return RecommendationPreviewV2(
            eligible_menu_count=menu_count,
            eligible_merchant_count=merchant_count,
            zero_reason_codes=reasons,
            release_id=str(family["release_family_id"]),
            support_manifest_sha256=str(family["support_manifest_sha256"]),
            ranking_policy_version=str(family["ranking_policy_version"]),
            timing_ms=max(0, int((monotonic() - started) * 1000)),
        )

    def get_active_recommendation_release_family(
        self,
    ) -> RecommendationReleaseFamily | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT family.* FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                """
            ).fetchone()
        if row is None:
            return None
        return RecommendationReleaseFamily(
            release_family_id=str(row["release_family_id"]),
            knowledge_release_id=str(row["knowledge_release_id"]),
            catalog_release_id=str(row["catalog_release_id"]),
            preference_catalog_version=str(row["preference_catalog_version"]),
            spice_reference_version=str(row["spice_reference_version"]),
            certification_release_id=str(row["certification_release_id"]),
            embedding_model=str(row["embedding_model"]),
            embedding_version=str(row["embedding_version"]),
            support_manifest_sha256=str(row["support_manifest_sha256"]),
            feature_manifest_sha256=str(row["feature_manifest_sha256"]),
            ranking_policy_version=str(row["ranking_policy_version"]),
            ranking_policy_sha256=str(row["ranking_policy_sha256"]),
            synthetic_enrichment_release_id=(
                str(row["synthetic_enrichment_release_id"])
                if row["synthetic_enrichment_release_id"]
                else None
            ),
            status=cast(Any, str(row["status"])),
            activated_at=(
                datetime.fromisoformat(str(row["activated_at"])) if row["activated_at"] else None
            ),
        )

    def list_valid_halal_certified_menu_ids(
        self,
        *,
        at: datetime | None = None,
    ) -> set[str]:
        instant = (at or datetime.now(timezone.utc)).isoformat()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT certification.scope_type,certification.scope_ref,certification.merchant_id
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                JOIN merchant_certification certification
                  ON certification.certification_release_id=family.certification_release_id
                WHERE state.state_key='ACTIVE'
                  AND certification.certification_type='HALAL'
                  AND certification.status='ACTIVE'
                  AND certification.valid_from<=?
                  AND (certification.valid_to IS NULL OR certification.valid_to>?)
                """,
                (instant, instant),
            ).fetchall()
            merchant_ids = [
                str(row["merchant_id"]) for row in rows if row["scope_type"] == "MERCHANT"
            ]
            menu_ids = {
                str(row["scope_ref"])
                for row in rows
                if row["scope_type"] == "MENU" and row["scope_ref"]
            }
            if merchant_ids:
                placeholders = ",".join("?" for _ in merchant_ids)
                menu_ids.update(
                    str(row["menu_id"])
                    for row in connection.execute(
                        f"""
                        SELECT menu_id FROM menu
                        WHERE merchant_id IN ({placeholders}) AND availability='AVAILABLE'
                        """,
                        merchant_ids,
                    ).fetchall()
                )
        return menu_ids

    def get_preference_catalog(self, locale: str) -> dict[str, Any]:
        family = self.get_active_recommendation_release_family()
        if family is None:
            raise RuntimeError("RECOMMENDATION_RELEASE_NOT_READY")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT option_code FROM recommendation_preference_option
                WHERE catalog_version=? AND active=1
                ORDER BY category_code,display_order,option_code
                """,
                (family.preference_catalog_version,),
            ).fetchall()
            metrics_rows = connection.execute(
                """
                SELECT support.option_code,
                       COUNT(DISTINCT mapping.menu_id) AS menu_count,
                       COUNT(DISTINCT menu.merchant_id) AS merchant_count,
                       COUNT(DISTINCT document.document_id) AS document_count
                FROM concept_preference_support support
                JOIN menu_concept_map mapping
                  ON mapping.release_id=support.knowledge_release_id
                 AND mapping.concept_id=support.concept_id
                 AND mapping.mapping_status='MAPPED'
                 AND mapping.confidence_band='high'
                JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
                JOIN knowledge_chunk chunk
                  ON chunk.release_id=support.knowledge_release_id
                 AND chunk.chunk_id=support.evidence_chunk_id
                JOIN knowledge_document document
                  ON document.release_id=chunk.release_id
                 AND document.document_id=chunk.document_id
                WHERE support.knowledge_release_id=? AND support.support_status='SUPPORTED'
                  AND support.review_status IN ('REVIEWED_DEMO','VERIFIED')
                  AND document.review_status IN ('REVIEWED_DEMO','VERIFIED')
                  AND menu.price>0 AND COALESCE(source_detail.liquor,0)=0
                  AND COALESCE(source_detail.is_adult,0)=0
                  AND COALESCE(source_detail.verified_adult,0)=0
                  AND COALESCE(source_detail.soldout,0)=0
                GROUP BY support.option_code
                """,
                (family.knowledge_release_id,),
            ).fetchall()
            metrics = {
                str(row["option_code"]): (
                    int(row["menu_count"]),
                    int(row["merchant_count"]),
                    int(row["document_count"]),
                )
                for row in metrics_rows
            }
            price_metric_rows = connection.execute(
                """
                SELECT CASE
                         WHEN menu.price<10000 THEN 'UNDER_10000'
                         WHEN menu.price<20000 THEN 'FROM_10000_TO_19999'
                         WHEN menu.price<30000 THEN 'FROM_20000_TO_29999'
                         ELSE 'OVER_30000'
                       END option_code,
                       COUNT(DISTINCT menu.menu_id) menu_count,
                       COUNT(DISTINCT menu.merchant_id) merchant_count,
                       COUNT(DISTINCT document.document_id) document_count
                FROM menu_concept_map mapping
                JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
                JOIN knowledge_document document
                  ON document.release_id=mapping.release_id
                 AND document.concept_id=mapping.concept_id
                 AND document.review_status IN ('REVIEWED_DEMO','VERIFIED')
                WHERE mapping.release_id=? AND mapping.mapping_status='MAPPED'
                  AND mapping.confidence_band='high' AND menu.price>0
                  AND COALESCE(source_detail.liquor,0)=0
                  AND COALESCE(source_detail.is_adult,0)=0
                  AND COALESCE(source_detail.verified_adult,0)=0
                  AND COALESCE(source_detail.soldout,0)=0
                GROUP BY CASE
                           WHEN menu.price<10000 THEN 'UNDER_10000'
                           WHEN menu.price<20000 THEN 'FROM_10000_TO_19999'
                           WHEN menu.price<30000 THEN 'FROM_20000_TO_29999'
                           ELSE 'OVER_30000'
                         END
                """,
                (family.knowledge_release_id,),
            ).fetchall()
            metrics.update(
                {
                    str(row["option_code"]): (
                        int(row["menu_count"]),
                        int(row["merchant_count"]),
                        int(row["document_count"]),
                    )
                    for row in price_metric_rows
                }
            )
            capability_rows = connection.execute(
                """
                SELECT
                  COUNT(DISTINCT CASE WHEN menu.spice_status IN ('REVIEWED','VERIFIED')
                    AND menu.spice_level IS NOT NULL THEN menu.menu_id END) spice_menus,
                  COUNT(DISTINCT CASE WHEN menu.spice_status IN ('REVIEWED','VERIFIED')
                    AND menu.spice_level IS NOT NULL THEN menu.merchant_id END) spice_merchants,
                  COUNT(DISTINCT CASE WHEN EXISTS (
                    SELECT 1 FROM menu_dietary_attribute relation
                    JOIN dietary_attribute attribute
                      ON attribute.attribute_id=relation.attribute_id
                    WHERE relation.menu_id=menu.menu_id
                      AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                      AND upper(relation.status)='VERIFIED'
                  ) THEN menu.menu_id END) vegan_menus,
                  COUNT(DISTINCT CASE WHEN EXISTS (
                    SELECT 1 FROM menu_dietary_attribute relation
                    JOIN dietary_attribute attribute
                      ON attribute.attribute_id=relation.attribute_id
                    WHERE relation.menu_id=menu.menu_id
                      AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                      AND upper(relation.status)='VERIFIED'
                  ) THEN menu.merchant_id END) vegan_merchants
                FROM menu_concept_map mapping
                JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                WHERE mapping.release_id=? AND mapping.mapping_status='MAPPED'
                  AND mapping.confidence_band='high'
                """,
                (family.knowledge_release_id,),
            ).fetchone()
            _halal_menus = len(
                self._valid_halal_certifications_in_connection(
                    connection,
                    release_family_id=family.release_family_id,
                    instant=_now(),
                )
            )
            synthetic_price_bounds = None
            synthetic_country_rows: list[sqlite3.Row] = []
            synthetic_capability = None
            if family.synthetic_enrichment_release_id:
                synthetic_price_bounds = connection.execute(
                    """
                    SELECT MIN(menu.price) min_price,MAX(menu.price) max_price
                    FROM synthetic_menu_profile profile
                    JOIN menu ON menu.menu_id=profile.menu_id
                    WHERE profile.release_id=? AND menu.availability='AVAILABLE'
                    """,
                    (family.synthetic_enrichment_release_id,),
                ).fetchone()
                synthetic_country_rows = connection.execute(
                    """
                    SELECT profile.country_code,profile.spice_baseline,
                           example.representative_dish
                    FROM synthetic_country_profile profile
                    LEFT JOIN synthetic_country_spice_example example
                      ON example.release_id=profile.release_id
                     AND example.country_code=profile.country_code
                     AND example.language_code=?
                    WHERE profile.release_id=? ORDER BY profile.country_code
                    """,
                    (effective_language(locale), family.synthetic_enrichment_release_id),
                ).fetchall()
                synthetic_capability = connection.execute(
                    """
                    SELECT SUM(halal_fit) halal_menus,SUM(vegan_fit) vegan_menus,
                           COUNT(*) menu_count
                    FROM synthetic_menu_profile WHERE release_id=?
                    """,
                    (family.synthetic_enrichment_release_id,),
                ).fetchone()
        active_codes = frozenset(str(row["option_code"]) for row in rows)
        exposed_codes = (
            frozenset(
                code
                for code in active_codes
                if preference_option_is_exposable(
                    code,
                    menu_count=metrics.get(code, (0, 0, 0))[0],
                    merchant_count=metrics.get(code, (0, 0, 0))[1],
                    document_count=metrics.get(code, (0, 0, 0))[2],
                )
            )
            if family.ranking_policy_version == RANKING_POLICY_VERSION
            else active_codes
        )
        payload = localized_preference_catalog(locale, exposed_codes=exposed_codes)
        group_by_category = {
            "cuisine_origins": "core",
            "main_ingredients": "core",
            "food_forms": "core",
            "flavors": "additional",
            "textures": "additional",
            "cooking_methods": "additional",
            "temperatures": "additional",
            "price_bands": "exact",
        }
        for category in cast(list[dict[str, Any]], payload["categories"]):
            category["group"] = group_by_category[str(category["code"])]
            for option in cast(list[dict[str, Any]], category["options"]):
                menu_count, merchant_count, document_count = metrics.get(
                    str(option["code"]), (0, 0, 0)
                )
                option.update(
                    {
                        "eligible_menu_count": menu_count,
                        "eligible_merchant_count": merchant_count,
                        "reviewed_document_count": document_count,
                    }
                )
        _spice_enabled = bool(
            capability_rows
            and int(capability_rows["spice_menus"] or 0) >= 3
            and int(capability_rows["spice_merchants"] or 0) >= 2
        )
        _vegan_enabled = bool(
            capability_rows
            and int(capability_rows["vegan_menus"] or 0) >= 3
            and int(capability_rows["vegan_merchants"] or 0) >= 2
        )
        payload["capabilities"] = {
            "halal_certified_only": {
                "enabled": bool(
                    synthetic_capability and int(synthetic_capability["halal_menus"] or 0) >= 3
                ),
                "disabled_reason": None
                if synthetic_capability and int(synthetic_capability["halal_menus"] or 0) >= 3
                else "Enrichment data is not ready.",
            },
            "vegan": {
                "enabled": bool(
                    synthetic_capability and int(synthetic_capability["vegan_menus"] or 0) >= 3
                ),
                "disabled_reason": None
                if synthetic_capability and int(synthetic_capability["vegan_menus"] or 0) >= 3
                else "Enrichment data is not ready.",
            },
            "max_spice_level": {
                "enabled": bool(synthetic_country_rows),
                "disabled_reason": None
                if synthetic_country_rows
                else "Enrichment data is not ready.",
            },
        }
        if synthetic_price_bounds and synthetic_price_bounds["min_price"] is not None:
            minimum = int(synthetic_price_bounds["min_price"])
            maximum = int(synthetic_price_bounds["max_price"])
            payload["price_range_krw"] = {
                "min": (minimum // 1000) * 1000,
                "max": ((maximum + 999) // 1000) * 1000,
                "step": 1000,
            }
        payload["country_spice_profiles"] = [
            {
                "country_code": str(row["country_code"]),
                "spice_baseline": int(row["spice_baseline"]),
                "representative_dish": str(
                    row["representative_dish"]
                    or representative_dish(str(row["country_code"]), locale)
                ),
            }
            for row in synthetic_country_rows
        ]
        payload["schema_version"] = "3"
        payload["synthetic_enrichment_release_id"] = family.synthetic_enrichment_release_id
        payload["spice_reference_version"] = family.spice_reference_version
        payload["knowledge_release_id"] = family.knowledge_release_id
        payload["support_manifest_sha256"] = family.support_manifest_sha256
        payload["feature_manifest_sha256"] = family.feature_manifest_sha256
        payload["ranking_policy_version"] = family.ranking_policy_version
        return dict(payload)

    def _save_browse_snapshot(
        self,
        session_id: str,
        menus: list[MenuSummary],
        *,
        query_summary: str,
    ) -> str:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError("SESSION_NOT_FOUND")
        snapshot_id = _id("snapshot_browse")
        assistant_message_id = _id("msg_a_browse")
        need_state = session.meal_need_state.model_copy(deep=True)
        need_state.shown_menu_ids = list(
            dict.fromkeys([*need_state.shown_menu_ids, *(menu.menu_id for menu in menus)])
        )
        result = RecommendationResult(
            snapshot_id=snapshot_id,
            candidates=[
                RecommendationCandidate(
                    menu_id=menu.menu_id,
                    merchant_id=menu.merchant_id,
                    rank=index,
                    score=round(max(0.0, 1.0 - (index - 1) * 0.01), 6),
                    match_reasons=list(menu.match_reasons),
                    risk_hints=list(menu.risk_hints),
                    evidence_ids=list(menu.evidence_ids),
                    claim_ids=list(menu.grounded_claim_ids),
                    passage_ids=list(menu.grounded_passage_ids),
                )
                for index, menu in enumerate(menus, start=1)
            ],
            query_summary=query_summary,
            grounded_claim_ids=list(
                dict.fromkeys(claim for menu in menus for claim in menu.grounded_claim_ids)
            ),
            grounded_passage_ids=list(
                dict.fromkeys(passage for menu in menus for passage in menu.grounded_passage_ids)
            ),
            synthetic_data=all(menu.is_synthetic for menu in menus),
        )
        cards = [
            {"type": "browse_menu", "data": {"menu": menu.model_dump(mode="json")}}
            for menu in menus
        ]
        created_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO chat_message(
                  message_id,session_id,role,content,message_type,safe_metadata_json,created_at
                ) VALUES (?,?,'assistant','Browse collection authorization snapshot.',
                          'browse_snapshot_audit',?,?)
                """,
                (
                    assistant_message_id,
                    session_id,
                    json.dumps({"non_user_visible": True}, separators=(",", ":")),
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO recommendation_snapshot(
                  snapshot_id,session_id,assistant_message_id,state_version,
                  meal_need_state_json,result_json,cards_json,generation_status,created_at
                ) VALUES (?,?,?,?,?,?,?,'BROWSE',?)
                """,
                (
                    snapshot_id,
                    session_id,
                    assistant_message_id,
                    session.state_version,
                    need_state.model_dump_json(),
                    result.model_dump_json(),
                    json.dumps(cards, ensure_ascii=False),
                    created_at,
                ),
            )
        return snapshot_id

    @staticmethod
    def _browse_exact_filter_sql(
        connection: sqlite3.Connection,
        session_id: str,
    ) -> tuple[str, dict[str, Any]]:
        row = connection.execute(
            """
            SELECT criteria_json FROM session_recommendation_criteria
            WHERE session_id=? ORDER BY criteria_version DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return "", {}
        criteria = RecommendationCriteriaV2.model_validate_json(str(row["criteria_json"]))
        conditions: list[str] = []
        parameters: dict[str, Any] = {}
        if criteria.schema_version == "3":
            price_range = criteria.price_range_krw
            if price_range is None:
                return " AND 1=0", {}
            parameters.update(
                {
                    "browse_price_min_krw": price_range.min,
                    "browse_price_max_krw": price_range.max,
                    "browse_spice_reference_country": criteria.spice_reference_country,
                    "browse_spice_preference": criteria.spice_preference,
                }
            )
            conditions.append("menu.price BETWEEN :browse_price_min_krw AND :browse_price_max_krw")
            synthetic_dietary_conditions = ""
            if criteria.dietary_filters.halal_certified_only:
                synthetic_dietary_conditions += " AND synthetic_menu.halal_fit=1"
            if criteria.dietary_filters.vegan:
                synthetic_dietary_conditions += " AND synthetic_menu.vegan_fit=1"
            conditions.append(
                f"""EXISTS (
                  SELECT 1 FROM synthetic_menu_profile synthetic_menu
                  JOIN synthetic_country_profile synthetic_country
                    ON synthetic_country.release_id=synthetic_menu.release_id
                   AND synthetic_country.country_code=:browse_spice_reference_country
                  WHERE synthetic_menu.release_id=family.synthetic_enrichment_release_id
                    AND synthetic_menu.menu_id=menu.menu_id
                    AND (
                      (:browse_spice_preference='LESS'
                       AND synthetic_menu.spice_level<synthetic_country.spice_baseline)
                      OR (:browse_spice_preference='SIMILAR'
                          AND synthetic_menu.spice_level=synthetic_country.spice_baseline)
                      OR (:browse_spice_preference='MORE'
                          AND synthetic_menu.spice_level>synthetic_country.spice_baseline)
                    )
                    {synthetic_dietary_conditions}
                )"""
            )
            return " AND " + " AND ".join(conditions), parameters

        price_conditions = [
            {
                "UNDER_10000": "menu.price<10000",
                "FROM_10000_TO_19999": "menu.price BETWEEN 10000 AND 19999",
                "FROM_20000_TO_29999": "menu.price BETWEEN 20000 AND 29999",
                "OVER_30000": "menu.price>=30000",
            }[band]
            for band in criteria.price_bands
        ]
        if price_conditions:
            conditions.append("(" + " OR ".join(price_conditions) + ")")
        if criteria.max_spice_level < 5:
            parameters["browse_max_spice_level"] = criteria.max_spice_level
            conditions.extend(
                [
                    "menu.spice_status IN ('REVIEWED','VERIFIED')",
                    "menu.spice_level<=:browse_max_spice_level",
                ]
            )
        if criteria.dietary_filters.halal_certified_only:
            parameters["browse_eligibility_as_of"] = _now()
            conditions.append(
                """EXISTS (
                  SELECT 1 FROM merchant_certification certification
                  WHERE certification.certification_release_id=family.certification_release_id
                    AND certification.merchant_id=menu.merchant_id
                    AND certification.certification_type='HALAL'
                    AND certification.status='ACTIVE'
                    AND certification.valid_from<=:browse_eligibility_as_of
                    AND (certification.valid_to IS NULL
                         OR certification.valid_to>=:browse_eligibility_as_of)
                    AND (certification.scope_type='MERCHANT'
                         OR (certification.scope_type='MENU'
                             AND certification.scope_ref=menu.menu_id))
                )"""
            )
        if criteria.dietary_filters.vegan:
            conditions.append(
                """EXISTS (
                  SELECT 1 FROM menu_dietary_attribute relation
                  JOIN dietary_attribute attribute
                    ON attribute.attribute_id=relation.attribute_id
                  WHERE relation.menu_id=menu.menu_id
                    AND lower(attribute.code) IN ('vegan_option','vegan_possible')
                    AND upper(relation.status)='VERIFIED'
                )"""
            )
        return (" AND " + " AND ".join(conditions) if conditions else ""), parameters

    def list_food_rankings(
        self,
        session_id: str,
        sort: FoodRankingSort,
        limit: int,
    ) -> FoodRankingCollection:
        bounded_limit = max(1, min(20, limit))
        order_expression = {
            "review_count": "ranking_review_count",
            "order_count": "ranking_order_count",
            "korean_popularity": "ranking_korean_popularity",
        }[sort]
        ranking_sql = food_ranking_sql(
            "sqlite",
            menu_id="menu.menu_id",
            is_synthetic="menu.is_synthetic",
            menu_review_count="source.review_count",
            merchant_review_count="merchant_source.review_count",
        )
        with self._connection() as connection:
            service_area_id, _excluded = self._structured_session_filters(
                connection, session_id, exclude_history=False
            )
            exact_clause, parameters = self._browse_exact_filter_sql(connection, session_id)
            area_clause = ""
            if service_area_id:
                area_clause = "AND merchant.service_area_id=:browse_service_area_id"
                parameters["browse_service_area_id"] = service_area_id
            rows = connection.execute(
                f"""
                SELECT menu.menu_id,menu.merchant_id,
                       COALESCE(merchant.name_en,merchant.name_ko) merchant_name,
                       menu.name_en,menu.name_ko,menu.category,menu.description,
                       menu.cultural_description,menu.price,
                       COALESCE(merchant.min_order_amount,0) minimum_order_amount,
                       COALESCE(merchant.delivery_fee,0) delivery_fee,
                       COALESCE(merchant.eta_min,0) eta_min,
                       COALESCE(merchant.eta_max,0) eta_max,
                       menu.spice_level,menu.serves_min,menu.serves_max,menu.is_synthetic,
                       COALESCE(source.review_count,0) source_menu_review_count,
                       COALESCE(merchant_source.review_count,0) source_merchant_review_count,
                       {ranking_sql.review_count} ranking_review_count,
                       {ranking_sql.order_count} ranking_order_count,
                       {ranking_sql.korean_popularity} ranking_korean_popularity,
                       {ranking_sql.basis} ranking_metric_basis,
                       mapping.concept_id,
                       (SELECT chunk.content FROM knowledge_chunk chunk
                        JOIN knowledge_document document
                          ON document.release_id=chunk.release_id
                         AND document.document_id=chunk.document_id
                        WHERE chunk.release_id=mapping.release_id
                          AND chunk.concept_id=mapping.concept_id
                          AND document.source_type='SYNTHETIC_WIKI'
                          AND document.review_status='REVIEWED_DEMO'
                          AND lower(chunk.facet)<>'safety'
                          AND (
                            json_extract(chunk.metadata_json,
                                         '$.recommendation_visibility')='PUBLIC_RAG'
                            OR json_extract(chunk.metadata_json,
                                            '$.recommendation_visibility') IS NULL
                          )
                        ORDER BY chunk.chunk_id LIMIT 1) concept_description
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                 AND family.status='ACTIVE'
                JOIN menu_concept_map mapping
                  ON mapping.release_id=family.knowledge_release_id
                 AND mapping.mapping_status='MAPPED' AND mapping.confidence_band='high'
                JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                JOIN merchant ON merchant.merchant_id=menu.merchant_id
                LEFT JOIN menu_source_detail source ON source.menu_id=menu.menu_id
                LEFT JOIN merchant_source_detail merchant_source
                  ON merchant_source.merchant_id=menu.merchant_id
                WHERE state.state_key='ACTIVE' AND menu.price>0
                  AND COALESCE(source.liquor,0)=0 AND COALESCE(source.is_adult,0)=0
                  AND COALESCE(source.verified_adult,0)=0 AND COALESCE(source.soldout,0)=0
                  {area_clause}
                  {exact_clause}
                ORDER BY {order_expression} DESC,menu.merchant_id,menu.menu_id
                LIMIT 500
                """,
                parameters,
            ).fetchall()
            session_row = connection.execute(
                """
                SELECT session.meal_need_state_json,profile.dietary_rules_json,
                       profile.religion_selection,profile.allergy_severity
                FROM chat_session session JOIN user_profile profile
                  ON profile.profile_id=session.profile_id
                WHERE session.session_id=?
                """,
                (session_id,),
            ).fetchone()
            if session_row is None:
                raise KeyError("SESSION_NOT_FOUND")
            need_state = apply_profile_constraints(
                MealNeedState.model_validate_json(str(session_row["meal_need_state_json"] or "{}")),
                list(json.loads(str(session_row["dietary_rules_json"] or "[]"))),
                str(session_row["religion_selection"]),
            )
            eligible_rows = [
                row
                for row in rows
                if not self._menu_hard_constraint_conflicts(
                    connection,
                    str(row["menu_id"]),
                    need_state,
                    str(session_row["allergy_severity"]),
                )[0]
            ][:bounded_limit]
        items: list[FoodRankingEntry] = []
        menus: list[MenuSummary] = []
        for position, row in enumerate(eligible_rows, start=1):
            metric_value = {
                "review_count": int(row["ranking_review_count"] or 0),
                "order_count": int(row["ranking_order_count"] or 0),
                "korean_popularity": int(row["ranking_korean_popularity"] or 0),
            }[sort]
            if str(row["ranking_metric_basis"]) == "DETERMINISTIC_SYNTHETIC_FALLBACK":
                metric_label = {
                    "review_count": "Deterministic demo review score",
                    "order_count": "Deterministic demo order score",
                    "korean_popularity": "Deterministic demo Korean-popularity score",
                }[sort]
            else:
                metric_label = {
                    "review_count": "Source menu review count",
                    "order_count": "Deterministic demo order proxy",
                    "korean_popularity": "Deterministic demo Korean-popularity proxy",
                }[sort]
            menu = self._menu_summary(
                row,
                ["Available mapped menu in the current demo delivery area"],
                ["Ranking is a demo view, not a live platform-wide ranking"],
                EvidenceStatus.UNKNOWN,
                1.0,
            )
            if row["concept_description"]:
                menu = menu.model_copy(
                    update={
                        "cultural_description": (
                            "General food reference: " + str(row["concept_description"])
                        )
                    }
                )
            menus.append(menu)
            items.append(
                FoodRankingEntry(
                    position=position,
                    metric_label=metric_label,
                    metric_value=metric_value,
                    menu=menu,
                )
            )
        snapshot_id = self._save_browse_snapshot(
            session_id, menus, query_summary=f"Deterministic demo food ranking: {sort}"
        )
        return FoodRankingCollection(
            snapshot_id=snapshot_id,
            demo_basis=(
                "YOBI demo only. Provided source counts take priority. Synthetic menus with "
                "no source counts use stable menu-ID-derived demo scores so sort controls "
                "remain demonstrable. No value is a live Yogiyo-wide statistic."
            ),
            sort=sort,
            items=items,
        )

    def list_kpop_demon_hunters_feature(
        self,
        session_id: str,
    ) -> FeaturedMenuCollection:
        feature_names = (
            "Gimbap",
            "Korean wheat noodles",
            "Tteokbokki",
            "Gukbap",
            "Hotteok",
            "Seolleongtang",
            "Eomuk",
        )
        with self._connection() as connection:
            service_area_id, _excluded = self._structured_session_filters(
                connection, session_id, exclude_history=False
            )
            feature_keys = [f"browse_feature_{index}" for index in range(len(feature_names))]
            placeholders = ",".join(":" + key for key in feature_keys)
            exact_clause, parameters = self._browse_exact_filter_sql(connection, session_id)
            parameters.update(dict(zip(feature_keys, feature_names)))
            area_clause = ""
            if service_area_id:
                area_clause = "AND merchant.service_area_id=:browse_service_area_id"
                parameters["browse_service_area_id"] = service_area_id
            candidate_rows = connection.execute(
                f"""
                SELECT * FROM (
                  SELECT menu.menu_id,menu.merchant_id,
                         COALESCE(merchant.name_en,merchant.name_ko) merchant_name,
                         menu.name_en,menu.name_ko,menu.category,menu.description,
                         menu.cultural_description,menu.price,
                         COALESCE(merchant.min_order_amount,0) minimum_order_amount,
                         COALESCE(merchant.delivery_fee,0) delivery_fee,
                         COALESCE(merchant.eta_min,0) eta_min,
                         COALESCE(merchant.eta_max,0) eta_max,
                         menu.spice_level,menu.serves_min,menu.serves_max,menu.is_synthetic,
                         concept.canonical_name_en dish_name,
                         (SELECT chunk.content FROM knowledge_chunk chunk
                          JOIN knowledge_document document
                            ON document.release_id=chunk.release_id
                           AND document.document_id=chunk.document_id
                          WHERE chunk.release_id=mapping.release_id
                            AND chunk.concept_id=mapping.concept_id
                            AND document.source_type='SYNTHETIC_WIKI'
                            AND document.review_status='REVIEWED_DEMO'
                            AND lower(chunk.facet)<>'safety'
                            AND (
                              json_extract(chunk.metadata_json,
                                           '$.recommendation_visibility')='PUBLIC_RAG'
                              OR json_extract(chunk.metadata_json,
                                              '$.recommendation_visibility') IS NULL
                            )
                          ORDER BY chunk.chunk_id LIMIT 1) concept_description,
                         ROW_NUMBER() OVER (
                           PARTITION BY concept.canonical_name_en
                           ORDER BY COALESCE(source.review_count,0) DESC,
                                    menu.merchant_id,menu.menu_id
                         ) concept_rank
                  FROM recommendation_runtime_state state
                  JOIN recommendation_release_family family
                    ON family.release_family_id=state.active_release_family_id
                   AND family.status='ACTIVE'
                  JOIN menu_concept_map mapping
                    ON mapping.release_id=family.knowledge_release_id
                   AND mapping.mapping_status='MAPPED' AND mapping.confidence_band='high'
                  JOIN dish_concept concept
                    ON concept.release_id=mapping.release_id
                   AND concept.concept_id=mapping.concept_id
                  JOIN menu ON menu.menu_id=mapping.menu_id AND menu.availability='AVAILABLE'
                  JOIN merchant ON merchant.merchant_id=menu.merchant_id
                  LEFT JOIN menu_source_detail source ON source.menu_id=menu.menu_id
                  WHERE state.state_key='ACTIVE' AND menu.price>0
                    AND concept.canonical_name_en IN ({placeholders})
                    AND COALESCE(source.liquor,0)=0 AND COALESCE(source.is_adult,0)=0
                    AND COALESCE(source.verified_adult,0)=0 AND COALESCE(source.soldout,0)=0
                    {area_clause}
                    {exact_clause}
                ) WHERE concept_rank<=20
                ORDER BY CASE dish_name
                  WHEN 'Gimbap' THEN 1 WHEN 'Korean wheat noodles' THEN 2
                  WHEN 'Tteokbokki' THEN 3 WHEN 'Gukbap' THEN 4 WHEN 'Hotteok' THEN 5
                  WHEN 'Seolleongtang' THEN 6 WHEN 'Eomuk' THEN 7 ELSE 8 END,concept_rank
                """,
                parameters,
            ).fetchall()
            session_row = connection.execute(
                """
                SELECT session.meal_need_state_json,profile.dietary_rules_json,
                       profile.religion_selection,profile.allergy_severity
                FROM chat_session session JOIN user_profile profile
                  ON profile.profile_id=session.profile_id
                WHERE session.session_id=?
                """,
                (session_id,),
            ).fetchone()
            if session_row is None:
                raise KeyError("SESSION_NOT_FOUND")
            need_state = apply_profile_constraints(
                MealNeedState.model_validate_json(str(session_row["meal_need_state_json"] or "{}")),
                list(json.loads(str(session_row["dietary_rules_json"] or "[]"))),
                str(session_row["religion_selection"]),
            )
            rows: list[sqlite3.Row] = []
            seen_dishes: set[str] = set()
            for row in candidate_rows:
                dish_name = str(row["dish_name"])
                if dish_name in seen_dishes:
                    continue
                if self._menu_hard_constraint_conflicts(
                    connection,
                    str(row["menu_id"]),
                    need_state,
                    str(session_row["allergy_severity"]),
                )[0]:
                    continue
                seen_dishes.add(dish_name)
                rows.append(row)
        menus = [
            self._menu_summary(
                row,
                ["Mapped to a food in the K-pop Demon Hunters demo feature"],
                ["General food knowledge does not verify this restaurant's recipe"],
                EvidenceStatus.UNKNOWN,
                1.0,
            ).model_copy(
                update={
                    "cultural_description": (
                        "General food reference: " + str(row["concept_description"])
                        if row["concept_description"]
                        else ""
                    )
                }
            )
            for row in rows
        ]
        snapshot_id = self._save_browse_snapshot(
            session_id, menus, query_summary="K-pop Demon Hunters mapped food feature"
        )
        return FeaturedMenuCollection(
            snapshot_id=snapshot_id,
            items=[
                FeaturedMenuEntry(
                    dish_name=str(row["dish_name"]),
                    description=(
                        str(row["concept_description"])
                        if row["concept_description"]
                        else "No reviewed general food description is available."
                    ),
                    menu=menu,
                )
                for row, menu in zip(rows, menus)
            ],
        )

    @staticmethod
    def _menu_from_cards(cards: list[dict[str, Any]], menu_id: str) -> dict[str, Any] | None:
        def visit(value: Any) -> dict[str, Any] | None:
            if isinstance(value, dict):
                if value.get("menu_id") == menu_id:
                    return {str(key): item for key, item in value.items()}
                for item in value.values():
                    match = visit(item)
                    if match is not None:
                        return match
            elif isinstance(value, list):
                for item in value:
                    match = visit(item)
                    if match is not None:
                        return match
            return None

        return visit(cards)

    @staticmethod
    def _live_structured_menu_payload(
        row: sqlite3.Row,
        existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Overlay server-owned catalog fields without changing model prose."""
        return {
            **(existing or {}),
            "menu_id": str(row["menu_id"]),
            "merchant_id": str(row["merchant_id"]),
            "merchant_name": _catalog_text(row["merchant_name"]),
            "name_en": _catalog_text(row["name_en"], row["name_ko"]),
            "name_ko": str(row["name_ko"]),
            "category": str(row["category"]),
            "description": _catalog_text(row["description"]),
            "cultural_description": _catalog_text(row["cultural_description"]),
            "price": int(row["price"]),
            "delivery_fee": int(row["delivery_fee"]),
            "eta_min": int(row["eta_min"]),
            "eta_max": int(row["eta_max"]),
            "spice_level": _optional_int(row["spice_level"]),
            "serves_min": _optional_int(row["serves_min"]),
            "serves_max": _optional_int(row["serves_max"]),
        }

    def apply_conversation_event(
        self, session_id: str, event: ConversationEventInput
    ) -> ConversationEventResult:
        with self._connection() as connection:
            # Serialise the idempotency lookup and state transition. A concurrent
            # replay then observes the committed ledger row instead of surfacing a
            # uniqueness or optimistic-version error.
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                """
                SELECT payload_json,result_json FROM conversation_event
                WHERE session_id=? AND idempotency_key=?
                """,
                (session_id, event.idempotency_key),
            ).fetchone()
            if duplicate:
                if json.loads(duplicate["payload_json"]) != event.model_dump(mode="json"):
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                previous = ConversationEventResult.model_validate_json(duplicate["result_json"])
                return previous.model_copy(update={"duplicate": True})

            session_row = connection.execute(
                "SELECT * FROM chat_session WHERE session_id=?", (session_id,)
            ).fetchone()
            if session_row is None:
                raise KeyError("SESSION_NOT_FOUND")
            version = int(session_row["state_version"])
            if event.expected_state_version is not None and event.expected_state_version != version:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            need_state = MealNeedState.model_validate_json(
                session_row["meal_need_state_json"] or "{}"
            )
            profile_row = connection.execute(
                """
                SELECT p.dietary_rules_json,p.allergy_severity,p.religion_selection
                FROM user_profile p WHERE p.profile_id=?
                """,
                (session_row["profile_id"],),
            ).fetchone()
            if profile_row is None:
                raise KeyError("PROFILE_NOT_FOUND")
            current_area = connection.execute(
                """
                SELECT ref.service_area_id
                FROM cart JOIN address_ref ref ON ref.address_ref_id=cart.address_ref_id
                JOIN service_area area ON area.service_area_id=ref.service_area_id
                WHERE cart.session_id=? AND ref.confirmed=1 AND area.active=1
                """,
                (session_id,),
            ).fetchone()
            if current_area and current_area["service_area_id"]:
                need_state.service_area_id = str(current_area["service_area_id"])
            snapshot: RecommendationSnapshot | None = None
            structured_criteria: RecommendationCriteriaV2 | None = None
            structured_request_pin: tuple[str, datetime] | None = None
            if event.snapshot_id:
                snapshot_row = connection.execute(
                    "SELECT * FROM recommendation_snapshot WHERE session_id=? AND snapshot_id=?",
                    (session_id, event.snapshot_id),
                ).fetchone()
                if snapshot_row is None:
                    raise ValueError("RECOMMENDATION_SNAPSHOT_NOT_FOUND")
                if snapshot_row["structured_request_id"] and snapshot_row["criteria_json"]:
                    structured_criteria = RecommendationCriteriaV2.model_validate_json(
                        str(snapshot_row["criteria_json"])
                    )
                    request_pin = connection.execute(
                        """
                        SELECT recommendation_release_family_id,eligibility_as_of
                        FROM structured_recommendation_request
                        WHERE session_id=? AND request_id=?
                        """,
                        (session_id, str(snapshot_row["structured_request_id"])),
                    ).fetchone()
                    if request_pin is None:
                        raise ValueError("STRUCTURED_RECOMMENDATION_REQUEST_NOT_FOUND")
                    structured_request_pin = (
                        str(request_pin["recommendation_release_family_id"]),
                        datetime.fromisoformat(str(request_pin["eligibility_as_of"])),
                    )
                snapshot = RecommendationSnapshot.model_validate(
                    {
                        "snapshot_id": snapshot_row["snapshot_id"],
                        "session_id": snapshot_row["session_id"],
                        "assistant_message_id": snapshot_row["assistant_message_id"],
                        "state_version": snapshot_row["state_version"],
                        "meal_need_state": json.loads(snapshot_row["meal_need_state_json"]),
                        "result": json.loads(snapshot_row["result_json"]),
                        "cards": json.loads(snapshot_row["cards_json"]),
                        "created_at": snapshot_row["created_at"],
                    }
                )
            if structured_criteria is None:
                need_state = apply_profile_constraints(
                    need_state,
                    list(json.loads(profile_row["dietary_rules_json"])),
                    str(profile_row["religion_selection"]),
                )

            candidate_by_id = {
                candidate.menu_id: candidate
                for candidate in (snapshot.result.candidates if snapshot else [])
            }
            selected_menu_id = session_row["selected_menu_id"]
            selected_merchant_id = session_row["selected_merchant_id"]
            selected_menu: dict[str, Any] | None = None
            chat_state = session_row["state"]
            dialogue_act = DialogueAct(session_row["dialogue_act"])

            if event.event_type == ConversationEventType.SELECT_MENU:
                if event.menu_id not in candidate_by_id:
                    raise ValueError("MENU_NOT_IN_RECOMMENDATION_SNAPSHOT")
                candidate = candidate_by_id[event.menu_id]
                if structured_criteria is not None and structured_request_pin is not None:
                    eligible_rows, _, _ = self._structured_objective_candidates(
                        connection,
                        session_id,
                        structured_criteria,
                        release_family_id=structured_request_pin[0],
                        eligibility_as_of=datetime.now(timezone.utc),
                        menu_ids=[candidate.menu_id],
                        enforce_price_bands=False,
                    )
                    live_menu = eligible_rows[0] if eligible_rows else None
                    conflicts: list[str] = [] if live_menu is not None else ["v2:ineligible"]
                else:
                    conflicts, _ = self._menu_hard_constraint_conflicts(
                        connection,
                        candidate.menu_id,
                        need_state,
                        str(profile_row["allergy_severity"]),
                    )
                    live_menu = connection.execute(
                        "SELECT merchant_id FROM menu WHERE menu_id=?",
                        (candidate.menu_id,),
                    ).fetchone()
                if (
                    conflicts
                    or live_menu is None
                    or live_menu["merchant_id"] != candidate.merchant_id
                ):
                    raise ValueError("MENU_NO_LONGER_ELIGIBLE")
                selected_menu_id = candidate.menu_id
                selected_merchant_id = candidate.merchant_id
                need_state.selected_menu_id = candidate.menu_id
                # Option group IDs belong to one menu. Never carry selections or risk
                # acknowledgements across a menu change/reselection.
                need_state.option_selections = {}
                need_state.option_risk_acknowledged = []
                selected_menu = (
                    self._menu_from_cards(snapshot.cards, candidate.menu_id) if snapshot else None
                )
                dialogue_act = DialogueAct.SELECT
                chat_state = ChatState.MENU_SELECTION.value
            elif event.event_type == ConversationEventType.REJECT_MENU:
                if event.menu_id not in candidate_by_id:
                    raise ValueError("MENU_NOT_IN_RECOMMENDATION_SNAPSHOT")
                if event.menu_id not in need_state.rejected_menu_ids:
                    need_state.rejected_menu_ids.append(event.menu_id)
                if selected_menu_id == event.menu_id:
                    selected_menu_id = None
                    selected_merchant_id = None
                    need_state.selected_menu_id = None
                    need_state.option_selections = {}
                    need_state.option_risk_acknowledged = []
                dialogue_act = DialogueAct.REJECT
                chat_state = ChatState.DISCOVERY.value
            elif event.event_type == ConversationEventType.COMPARE_MENUS:
                if any(menu_id not in candidate_by_id for menu_id in set(event.menu_ids)):
                    raise ValueError("MENU_NOT_IN_RECOMMENDATION_SNAPSHOT")
                need_state.compared_menu_ids = list(dict.fromkeys(event.menu_ids))
                dialogue_act = DialogueAct.COMPARE
                chat_state = ChatState.MERCHANT_COMPARISON.value
            elif event.event_type == ConversationEventType.UPDATE_OPTIONS:
                if event.menu_id != selected_menu_id:
                    raise ValueError("OPTIONS_REQUIRE_SELECTED_MENU")
                group = connection.execute(
                    """
                    SELECT option_group_id,min_select,max_select FROM menu_option_group
                    WHERE option_group_id=? AND menu_id=?
                    """,
                    (event.option_group_id, event.menu_id),
                ).fetchone()
                if group is None:
                    raise ValueError("OPTION_GROUP_NOT_FOUND")
                selected_option_ids = list(dict.fromkeys(event.option_item_ids))
                if (
                    not int(group["min_select"])
                    <= len(selected_option_ids)
                    <= int(group["max_select"])
                ):
                    raise ValueError("OPTION_SELECTION_CARDINALITY_INVALID")
                if selected_option_ids:
                    placeholders = ",".join("?" for _ in selected_option_ids)
                    count = connection.execute(
                        f"""
                        SELECT COUNT(*) FROM menu_option_item
                        WHERE option_group_id=? AND option_item_id IN ({placeholders})
                          AND availability='AVAILABLE'
                        """,
                        [event.option_group_id, *selected_option_ids],
                    ).fetchone()[0]
                    if count != len(selected_option_ids):
                        raise ValueError("OPTION_ITEM_NOT_AVAILABLE")
                need_state.option_selections[event.option_group_id or ""] = selected_option_ids
                if event.risk_acknowledged and event.option_group_id:
                    if event.option_group_id not in need_state.option_risk_acknowledged:
                        need_state.option_risk_acknowledged.append(event.option_group_id)
                dialogue_act = DialogueAct.ORDER_ACTION
                chat_state = ChatState.MENU_OPTIONS.value

            next_version = version + 1
            cursor = connection.execute(
                """
                UPDATE chat_session SET state=?, selected_menu_id=?, selected_merchant_id=?,
                  dialogue_act=?, meal_need_state_json=?, state_version=?, updated_at=?
                WHERE session_id=? AND state_version=?
                """,
                (
                    chat_state,
                    selected_menu_id,
                    selected_merchant_id,
                    dialogue_act.value,
                    need_state.model_dump_json(),
                    next_version,
                    _now(),
                    session_id,
                    version,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            result = ConversationEventResult(
                event_id=_id("event"),
                event_type=event.event_type,
                state_version=next_version,
                state=need_state,
                selected_menu_id=selected_menu_id,
                selected_merchant_id=selected_merchant_id,
                selected_menu=selected_menu,
            )
            connection.execute(
                """
                INSERT INTO conversation_event(
                  event_id, session_id, snapshot_id, event_type, payload_json, result_json,
                  idempotency_key, resulting_state_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.event_id,
                    session_id,
                    event.snapshot_id,
                    event.event_type.value,
                    event.model_dump_json(),
                    result.model_dump_json(),
                    event.idempotency_key,
                    next_version,
                    _now(),
                ),
            )
        return result

    def set_session_selection(
        self, session_id: str, state: str, menu_id: str | None, merchant_id: str | None
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE chat_session
                SET state = ?, selected_menu_id = ?, selected_merchant_id = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (state, menu_id, merchant_id, _now(), session_id),
            )

    def search_menus(
        self,
        query: str,
        profile: Profile,
        budget_krw: int | None,
        max_spiciness: int | None,
        excluded_ingredients: list[str],
        limit: int = 4,
        constraint_strictness: ConstraintStrictness = ConstraintStrictness.STRICT,
    ) -> list[MenuSummary]:
        budget = budget_krw or 30000
        spice = max_spiciness if max_spiciness is not None else profile.spice_tolerance
        safety_state = apply_profile_constraints(
            MealNeedState(
                budget_krw=budget,
                max_spiciness=spice,
                excluded_ingredients=excluded_ingredients,
            ),
            profile.dietary_rules,
            profile.religion_selection,
        )
        safety_state.strictness = constraint_strictness
        query_vector = deterministic_embedding(f"query: {query}")
        vegan_required = "vegan" in profile.dietary_rules
        severe_allergies = profile.allergy_severity == "severe"
        excluded = {item.lower() for item in excluded_ingredients}
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*, COALESCE(r.name_en,r.name_ko) AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max
                FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                WHERE m.availability = 'AVAILABLE' AND m.price <= ?
                  AND (m.spice_level IS NULL OR m.spice_level <= ?)
                """,
                (budget, max(spice, 1)),
            ).fetchall()
            prelim: list[
                tuple[
                    float,
                    sqlite3.Row,
                    list[str],
                    list[str],
                    EvidenceStatus,
                    set[str],
                    set[str],
                ]
            ] = []
            for row in rows:
                dietary_tags = set(json.loads(row["dietary_tags_json"]))
                allergen_tags = set(json.loads(row["allergen_tags_json"]))
                if severe_allergies and known_allergen_conflicts(
                    allergen_tags, set(profile.dietary_rules)
                ):
                    continue
                if "pork" in excluded and "pork" in allergen_tags:
                    continue
                if vegan_required and "vegan_option" not in dietary_tags:
                    continue
                menu_similarity = max(
                    0.0,
                    cosine_similarity(
                        query_vector,
                        deterministic_embedding(f"document: {row['semantic_text']}"),
                    ),
                )
                operational_signal = operational_menu_signal(
                    menu_similarity,
                    price=int(row["price"]),
                    budget=budget,
                    delivery_fee=int(row["delivery_fee"]),
                    eta_max=int(row["eta_max"]),
                )
                spice_level = _optional_int(row["spice_level"])
                reasons = (
                    [f"Matches your spice tolerance (level {spice_level} of 5)"]
                    if spice_level is not None
                    else ["Spice level was not provided by the source"]
                )
                risks: list[str] = (
                    ["Confirm spice level with the merchant"] if spice_level is None else []
                )
                status = EvidenceStatus.UNKNOWN
                if "shellfish_sauce_absent" in dietary_tags:
                    status = EvidenceStatus.VERIFIED
                    reasons.append("Demo sauce specification has shellfish marked absent")
                    risks.append("Cross-contamination is not verified")
                elif allergen_tags:
                    risks.append("Some dietary details are not verified")
                prelim.append(
                    (
                        operational_signal,
                        row,
                        reasons,
                        risks,
                        status,
                        dietary_tags,
                        allergen_tags,
                    )
                )

            # Do not pre-truncate by menu text: every hard-filtered demo menu gets one
            # batched active-Wiki score before the candidate cap is applied.
            candidate_ids = [str(item[1]["menu_id"]) for item in prelim]
            grounded = self._bulk_resolved_knowledge_claims(connection, candidate_ids)
            knowledge = self._bulk_knowledge_passages(
                connection,
                candidate_ids,
                query_vector,
                query=query,
            )
            evidence_by_menu: dict[str, list[str]] = defaultdict(list)
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                for evidence_row in connection.execute(
                    f"""
                    SELECT subject_id,evidence_id FROM evidence
                    WHERE subject_id IN ({placeholders}) ORDER BY subject_id,evidence_id
                    """,
                    candidate_ids,
                ).fetchall():
                    evidence_by_menu[str(evidence_row["subject_id"])].append(
                        str(evidence_row["evidence_id"])
                    )

        scored: list[MenuSummary] = []
        for (
            operational_signal,
            row,
            reasons,
            risks,
            status,
            _dietary_tags,
            _allergen_tags,
        ) in prelim:
            menu_id = str(row["menu_id"])
            ingredient_claims, allergen_claims, merchant_claims = grounded.get(
                menu_id, ([], [], [])
            )
            conflicts = ingredient_constraint_conflicts(ingredient_claims, safety_state)
            conflicts.extend(allergen_constraint_conflicts(allergen_claims, safety_state))
            if profile.allergy_severity == "severe":
                conflicts.extend(
                    severe_allergy_conflicts(
                        ingredient_claims,
                        allergen_claims,
                        safety_state.dietary_rules,
                    )
                )
            conflicts.extend(
                merchant_cross_contact_conflicts(
                    merchant_claims,
                    safety_state,
                    allergy_severity=profile.allergy_severity,
                )
            )
            if conflicts:
                continue
            absent_allergies, cross_contact_unknown = confirmed_allergen_absence_signals(
                allergen_claims,
                safety_state.dietary_rules,
            )
            for allergy in absent_allergies:
                reasons.append(
                    f"Synthetic menu specification marks {allergy.replace('_', ' ')} absent"
                )
            if absent_allergies:
                status = EvidenceStatus.VERIFIED
            if cross_contact_unknown and "Cross-contamination is not verified" not in risks:
                risks.append("Cross-contamination is not verified")
            knowledge_score, passage_ids = knowledge.get(menu_id, (0.0, []))
            combined_score = wiki_operational_retrieval_score(
                knowledge_score,
                operational_signal,
            )
            claim_ids = list(
                dict.fromkeys(
                    [claim.source_id for claim in ingredient_claims]
                    + [claim.source_id for claim in allergen_claims]
                    + [claim.source_id for claim in merchant_claims]
                )
            )
            scored.append(
                self._menu_summary(row, reasons, risks, status, combined_score).model_copy(
                    update={
                        "evidence_ids": evidence_by_menu.get(menu_id, []),
                        "grounded_claim_ids": claim_ids,
                        "grounded_passage_ids": passage_ids,
                    }
                )
            )
        scored.sort(key=lambda item: (item.semantic_score, -item.price), reverse=True)
        return scored[: min(limit, RECOMMENDATION_CANDIDATE_CAP)]

    def recommend_menus(
        self,
        query: str,
        profile: Profile,
        meal_need_state: MealNeedState,
        limit: int = 4,
    ) -> list[MenuSummary]:
        meal_need_state = apply_profile_constraints(
            meal_need_state, profile.dietary_rules, profile.religion_selection
        )
        effective_profile = profile.model_copy(
            update={
                "dietary_rules": list(
                    dict.fromkeys([*profile.dietary_rules, *meal_need_state.dietary_rules])
                )
            }
        )
        expanded_query = " ".join(
            part
            for part in (
                query,
                *meal_need_state.temperature_preferences,
                *meal_need_state.texture_preferences,
                *meal_need_state.flavor_preferences,
                *meal_need_state.preferred_categories,
            )
            if part
        )
        candidates = self.search_menus(
            expanded_query,
            effective_profile,
            meal_need_state.budget_krw,
            meal_need_state.max_spiciness,
            meal_need_state.excluded_ingredients,
            limit=RECOMMENDATION_CANDIDATE_CAP,
            constraint_strictness=meal_need_state.strictness,
        )
        with self._connection() as connection:
            merchant_areas = {
                row["merchant_id"]: row["service_area_id"]
                for row in connection.execute(
                    "SELECT merchant_id, service_area_id FROM merchant"
                ).fetchall()
            }
        return rerank_menu_candidates(candidates, meal_need_state, merchant_areas, limit)

    @staticmethod
    def _menu_summary(
        row: sqlite3.Row,
        reasons: list[str],
        risks: list[str],
        status: EvidenceStatus,
        score: float,
    ) -> MenuSummary:
        return MenuSummary(
            menu_id=row["menu_id"],
            merchant_id=row["merchant_id"],
            merchant_name=_catalog_text(row["merchant_name"]),
            name_en=_catalog_text(row["name_en"], row["name_ko"]),
            name_ko=row["name_ko"],
            category=row["category"],
            description=_catalog_text(row["description"]),
            cultural_description=_catalog_text(row["cultural_description"]),
            price=row["price"],
            minimum_order_amount=int(
                row["minimum_order_amount"]
                if "minimum_order_amount" in row.keys()
                else row["min_order_amount"]
                if "min_order_amount" in row.keys()
                else 0
            ),
            delivery_fee=row["delivery_fee"],
            eta_min=row["eta_min"],
            eta_max=row["eta_max"],
            spice_level=_optional_int(row["spice_level"]),
            serves_min=_optional_int(row["serves_min"]),
            serves_max=_optional_int(row["serves_max"]),
            dietary_summary=(
                "Synthetic evidence; see evidence details before ordering."
                if bool(row["is_synthetic"])
                else "Dietary details were not provided by the source; confirm with the merchant."
            ),
            evidence_status=status,
            match_reasons=reasons,
            risk_hints=risks,
            semantic_score=round(max(0.0, min(1.0, score)), 4),
            is_synthetic=bool(row["is_synthetic"]),
        )

    def get_menu(self, menu_id: str, profile: Profile) -> MenuSummary | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT m.*, COALESCE(r.name_en,r.name_ko) AS merchant_name,
                       r.min_order_amount AS minimum_order_amount,
                       r.delivery_fee, r.eta_min, r.eta_max
                FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                WHERE m.menu_id = ?
                """,
                (menu_id,),
            ).fetchone()
        if not row:
            return None
        allergens = set(json.loads(row["allergen_tags_json"]))
        status = (
            EvidenceStatus.RISK_SIGNAL if "shellfish_risk" in allergens else EvidenceStatus.UNKNOWN
        )
        tags = set(json.loads(row["dietary_tags_json"]))
        if "shellfish_sauce_absent" in tags:
            status = EvidenceStatus.VERIFIED
        external_source = not bool(row["is_synthetic"])
        menu = self._menu_summary(
            row,
            [
                "Selected menu from the provided Yogiyo source catalog"
                if external_source
                else "Selected menu from the synthetic catalog"
            ],
            [
                "Ingredients, dietary suitability, and cross-contamination were not provided"
                if external_source
                else "Cross-contamination is not verified"
            ],
            status,
            1.0,
        )
        knowledge = self.get_grounded_menu_knowledge(menu_id)
        return menu.model_copy(
            update={
                "evidence_ids": [item.evidence_id for item in self.get_evidence(menu_id)],
                "grounded_claim_ids": knowledge.claim_ids,
                "grounded_passage_ids": [item.chunk_id for item in knowledge.passages],
            }
        )

    def get_category_knowledge_source(self, category: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT menu_id FROM menu
                WHERE lower(category)=lower(?)
                ORDER BY CASE WHEN availability='AVAILABLE' THEN 0 ELSE 1 END, menu_id
                LIMIT 1
                """,
                (category,),
            ).fetchone()
        return str(row["menu_id"]) if row else None

    def list_merchant_menus(
        self,
        merchant_id: str,
        profile: Profile,
        excluded_menu_ids: list[str],
        limit: int = 12,
        meal_need_state: MealNeedState | None = None,
    ) -> list[MenuSummary]:
        safety_state = apply_profile_constraints(
            meal_need_state.model_copy(deep=True)
            if meal_need_state is not None
            else MealNeedState(max_spiciness=profile.spice_tolerance),
            profile.dietary_rules,
            profile.religion_selection,
        )
        if safety_state.max_spiciness is None:
            safety_state.max_spiciness = profile.spice_tolerance
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*, COALESCE(r.name_en,r.name_ko) AS merchant_name,
                       r.min_order_amount AS minimum_order_amount,
                       r.delivery_fee, r.eta_min, r.eta_max,
                       r.service_area_id AS merchant_service_area_id
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE m.merchant_id=? AND m.availability='AVAILABLE'
                  AND (m.spice_level IS NULL OR m.spice_level<=?)
                ORDER BY m.price, m.menu_id
                """,
                (merchant_id, safety_state.max_spiciness),
            ).fetchall()
            hard_conflicts = {
                str(row["menu_id"]): self._menu_hard_constraint_conflicts(
                    connection,
                    str(row["menu_id"]),
                    safety_state,
                    profile.allergy_severity,
                )[0]
                for row in rows
            }
        excluded = set(excluded_menu_ids)
        rules = set(profile.dietary_rules)
        candidates: list[MenuSummary] = []
        merchant_areas: dict[str, str] = {}
        for index, row in enumerate(rows):
            if row["menu_id"] in excluded:
                continue
            if hard_conflicts.get(str(row["menu_id"])):
                continue
            tags = set(json.loads(row["dietary_tags_json"]))
            allergens = set(json.loads(row["allergen_tags_json"]))
            if profile.allergy_severity == "severe" and known_allergen_conflicts(allergens, rules):
                continue
            if "vegan" in rules and "vegan_option" not in tags:
                continue
            status = EvidenceStatus.UNKNOWN
            if "shellfish_risk" in allergens:
                status = EvidenceStatus.RISK_SIGNAL
            elif "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
            menu = self._menu_summary(
                row,
                ["More from the restaurant already selected"],
                ["Cross-contamination is not verified"],
                status,
                max(0.1, 0.6 - index * 0.001),
            )
            merchant_areas[menu.merchant_id] = str(row["merchant_service_area_id"])
            candidates.append(
                menu.model_copy(
                    update={
                        "evidence_ids": [
                            item.evidence_id for item in self.get_evidence(menu.menu_id)
                        ]
                    }
                )
            )
        return rerank_menu_candidates(candidates, safety_state, merchant_areas, limit)

    def list_merchant_menu_presentations(
        self,
        session_id: str,
        merchant_id: str,
        request: MerchantMenuPresentationRequest,
    ) -> MerchantMenuPresentationPage:
        with self._connection() as connection:
            context = connection.execute(
                """
                SELECT profile.preferred_language,profile.country_code,
                       family.knowledge_release_id,family.synthetic_enrichment_release_id
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE session.session_id=?
                """,
                (session_id,),
            ).fetchone()
            if context is None:
                raise KeyError("SESSION_NOT_FOUND")
            release_id = str(context["synthetic_enrichment_release_id"] or "")
            if not release_id:
                raise RuntimeError("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            requested_locale = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested_locale if requested_locale in {"ko", "ja"} else "en"
            country_code = str(context["country_code"] or "ZZ")
            parameters: list[Any] = [
                release_id,
                language_code,
                release_id,
                language_code,
                release_id,
                country_code,
                str(context["knowledge_release_id"]),
                merchant_id,
                request.cursor or "",
            ]
            exclude_sql = ""
            if request.exclude_menu_ids:
                exclude_sql = (
                    f" AND menu.menu_id NOT IN ({','.join('?' for _ in request.exclude_menu_ids)})"
                )
                parameters.extend(request.exclude_menu_ids)
            parameters.append(request.limit + 1)
            rows = connection.execute(
                f"""
                SELECT menu.*,COALESCE(merchant.name_en,merchant.name_ko) merchant_name,
                       merchant.min_order_amount AS minimum_order_amount,
                       merchant.delivery_fee,merchant.eta_min,merchant.eta_max,
                       localization.display_name,
                       localization.source_hash AS menu_localization_source_hash,
                       description_localization.description_text
                         AS localized_source_description,
                       description_localization.source_hash
                         AS source_description_source_hash,
                       preference.preference_percent,preference.sample_size
                FROM menu_wiki_eligibility eligibility
                JOIN menu ON menu.menu_id=eligibility.menu_id
                JOIN merchant ON merchant.merchant_id=menu.merchant_id
                LEFT JOIN menu_localization localization
                  ON localization.release_id=? AND localization.menu_id=menu.menu_id
                 AND localization.language_code=? AND localization.validation_status='VALID'
                LEFT JOIN menu_source_description_localization description_localization
                  ON description_localization.release_id=?
                 AND description_localization.menu_id=menu.menu_id
                 AND description_localization.language_code=?
                 AND description_localization.validation_status='VALID'
                LEFT JOIN synthetic_menu_country_preference preference
                  ON preference.release_id=? AND preference.menu_id=menu.menu_id
                 AND preference.country_code=?
                WHERE eligibility.knowledge_release_id=?
                  AND menu.merchant_id=? AND menu.availability='AVAILABLE'
                  AND menu.menu_id>? {exclude_sql}
                ORDER BY menu.menu_id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
            has_more = len(rows) > request.limit
            visible_rows = rows[: request.limit]
            components_by_menu = self._menu_component_rows(
                connection,
                release_id=str(context["knowledge_release_id"]),
                menu_ids=[str(row["menu_id"]) for row in visible_rows],
            )
            items: list[MerchantMenuPresentation] = []
            for row in visible_rows:
                menu_id = str(row["menu_id"])
                passage_rows = connection.execute(
                    """
                    SELECT chunk.chunk_id,chunk.content,
                           membership.concept_id AS member_concept_id,
                           membership.membership_role,
                           member_concept.canonical_name_ko AS component_name_ko,
                           member_concept.canonical_name_en AS component_name_en,
                           chunk.facet,closure.depth,chunk.chunk_index
                    FROM menu_concept_membership membership
                    JOIN dish_concept member_concept
                      ON member_concept.release_id=membership.knowledge_release_id
                     AND member_concept.concept_id=membership.concept_id
                    JOIN dish_concept_closure closure
                      ON closure.release_id=membership.knowledge_release_id
                     AND closure.descendant_concept_id=membership.concept_id
                     AND closure.inherit_claims=1
                    JOIN knowledge_chunk chunk
                      ON chunk.release_id=closure.release_id
                     AND chunk.concept_id=closure.ancestor_concept_id
                    JOIN knowledge_document document
                      ON document.release_id=chunk.release_id
                     AND document.document_id=chunk.document_id
                    WHERE membership.knowledge_release_id=? AND membership.menu_id=?
                      AND document.source_type='SYNTHETIC_WIKI'
                      AND document.review_status='REVIEWED_DEMO'
                      AND lower(chunk.facet)<>'safety'
                    ORDER BY closure.depth,chunk.chunk_index,chunk.chunk_id
                    """,
                    (str(context["knowledge_release_id"]), menu_id),
                ).fetchall()
                passage_rows = rank_component_wiki_passages(
                    passage_rows, selected_groups={}, limit=2
                )
                reviews = connection.execute(
                    """
                    SELECT review_id,topic,rating,review_text FROM synthetic_review_snippet
                    WHERE release_id=? AND menu_id=? ORDER BY display_order LIMIT 3
                    """,
                    (release_id, menu_id),
                ).fetchall()
                title = str(
                    row["display_name"]
                    or (row["name_ko"] if language_code == "ko" else row["name_en"])
                    or row["name_ko"]
                )
                passage_texts = [str(passage["content"]) for passage in passage_rows]
                presentation_copy = deterministic_presentation_copy(
                    language_code,
                    localized_title=title,
                    wiki_passages=passage_texts,
                    reviews=[
                        {"topic": review["topic"], "rating": review["rating"]} for review in reviews
                    ],
                )
                short = presentation_copy.short_explanation
                long = presentation_copy.long_explanation
                review_summary = presentation_copy.review_summary
                evidence_ids = [str(passage["chunk_id"]) for passage in passage_rows]
                review_ids = [str(review["review_id"]) for review in reviews]
                source_description = str(
                    row["localized_source_description"] or row["description"] or ""
                )
                menu = self._menu_summary(
                    row,
                    ["More from this restaurant"],
                    [],
                    EvidenceStatus.UNKNOWN,
                    0.5,
                )
                items.append(
                    MerchantMenuPresentation(
                        menu=menu,
                        localized_title=title,
                        localized_subtitle=title,
                        yobi_short_explanation=short,
                        yobi_long_explanation=long,
                        source_description=source_description,
                        review_summary=review_summary,
                        country_preference={
                            "country_code": country_code,
                            "preference_percent": int(row["preference_percent"] or 54),
                            "sample_size": int(row["sample_size"] or 120),
                        },
                        evidence_ids=evidence_ids,
                        review_ids=review_ids,
                        generation_model="DETERMINISTIC_GROUNDED_FALLBACK",
                        release_id=release_id,
                        language_code=cast(Any, language_code),
                        evidence_map={
                            "wiki_passages": [
                                {
                                    "evidence_id": str(passage["chunk_id"]),
                                    "evidence_type": "WIKI_PASSAGE",
                                    "content": str(passage["content"]),
                                    "component_id": str(passage["member_concept_id"]),
                                    "component_name_ko": str(passage["component_name_ko"]),
                                    "component_name_en": str(passage["component_name_en"]),
                                    "membership_role": str(passage["membership_role"]),
                                }
                                for passage in passage_rows
                            ],
                            "menu_facts": [],
                            "synthetic_reviews": [dict(review) for review in reviews],
                            "menu_components": components_by_menu.get(menu_id, []),
                            "source_identity": {
                                "menu_localization_source_hash": row[
                                    "menu_localization_source_hash"
                                ],
                                "source_description_source_hash": row[
                                    "source_description_source_hash"
                                ],
                                "knowledge_release_id": str(context["knowledge_release_id"]),
                            },
                        },
                    )
                )
        return MerchantMenuPresentationPage(
            items=items,
            next_cursor=(str(visible_rows[-1]["menu_id"]) if has_more and visible_rows else None),
        )

    def save_menu_presentation_cache(
        self, session_id: str, presentation: MerchantMenuPresentation
    ) -> None:
        with self._connection() as connection:
            context = connection.execute(
                """
                SELECT profile.preferred_language,profile.country_code,
                       family.synthetic_enrichment_release_id
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE session.session_id=?
                """,
                (session_id,),
            ).fetchone()
            if context is None or not context["synthetic_enrichment_release_id"]:
                raise RuntimeError("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            release_id = str(context["synthetic_enrichment_release_id"])
            requested_locale = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested_locale if requested_locale in {"ko", "ja"} else "en"
            country_code = str(context["country_code"] or "ZZ")
            source_hash = hashlib.sha256(
                json.dumps(
                    {
                        "localized_title": presentation.localized_title,
                        "source_description": presentation.source_description,
                        "evidence_ids": presentation.evidence_ids,
                        "review_ids": presentation.review_ids,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            cache_key = hashlib.sha256(
                f"{release_id}|{presentation.menu.menu_id}|{language_code}|{country_code}".encode()
            ).hexdigest()
            connection.execute(
                """
                INSERT OR IGNORE INTO menu_presentation_cache(
                  cache_key,release_id,menu_id,language_code,country_code,localized_title,
                  short_explanation,long_explanation,review_summary,evidence_ids_json,
                  review_ids_json,model_id,source_hash,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    cache_key,
                    release_id,
                    presentation.menu.menu_id,
                    language_code,
                    country_code,
                    presentation.localized_title,
                    presentation.yobi_short_explanation,
                    presentation.yobi_long_explanation,
                    presentation.review_summary,
                    json.dumps(presentation.evidence_ids),
                    json.dumps(presentation.review_ids),
                    presentation.generation_model,
                    source_hash,
                    _now(),
                ),
            )

    @staticmethod
    def _menu_presentation_cache_entry_from_row(
        row: sqlite3.Row,
    ) -> MenuPresentationCacheEntry:
        created_at = datetime.fromisoformat(str(row["created_at"]))
        updated_at = datetime.fromisoformat(str(row["updated_at"] or row["created_at"]))
        return MenuPresentationCacheEntry(
            cache_key=str(row["cache_key"]),
            release_id=str(row["release_id"]),
            menu_id=str(row["menu_id"]),
            language_code=cast(Any, str(row["language_code"])),
            country_code=str(row["country_code"]),
            localized_title=str(row["localized_title"]),
            localized_subtitle=str(row["localized_subtitle"] or row["localized_title"]),
            short_explanation=str(row["short_explanation"]),
            long_explanation=str(row["long_explanation"]),
            review_summary=str(row["review_summary"]),
            evidence_ids=list(json.loads(str(row["evidence_ids_json"] or "[]"))),
            review_ids=list(json.loads(str(row["review_ids_json"] or "[]"))),
            evidence_map=dict(json.loads(str(row["evidence_map_json"] or "{}"))),
            model_id=str(row["model_id"]),
            prompt_version=str(row["prompt_version"] or "legacy"),
            content_schema_version=str(row["content_schema_version"] or "1"),
            source_hash=str(row["source_hash"]),
            personalization_applied=bool(row["personalization_applied"] or 0),
            created_at=created_at,
            updated_at=updated_at,
        )

    def get_menu_presentation_cache(self, cache_key: str) -> MenuPresentationCacheEntry | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM menu_presentation_cache WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
        return self._menu_presentation_cache_entry_from_row(row) if row else None

    def save_menu_presentation_cache_entry(self, entry: MenuPresentationCacheEntry) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO menu_presentation_cache(
                  cache_key,release_id,menu_id,language_code,country_code,localized_title,
                  short_explanation,long_explanation,review_summary,evidence_ids_json,
                  review_ids_json,model_id,source_hash,created_at,localized_subtitle,
                  prompt_version,content_schema_version,evidence_map_json,
                  personalization_applied,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    entry.cache_key,
                    entry.release_id,
                    entry.menu_id,
                    entry.language_code,
                    entry.country_code,
                    entry.localized_title,
                    entry.short_explanation,
                    entry.long_explanation,
                    entry.review_summary,
                    json.dumps(entry.evidence_ids, ensure_ascii=False),
                    json.dumps(entry.review_ids, ensure_ascii=False),
                    entry.model_id,
                    entry.source_hash,
                    entry.created_at.isoformat(),
                    entry.localized_subtitle,
                    entry.prompt_version,
                    entry.content_schema_version,
                    json.dumps(entry.evidence_map, ensure_ascii=False, sort_keys=True),
                    int(entry.personalization_applied),
                    entry.updated_at.isoformat(),
                ),
            )

    def acquire_menu_presentation_lease(
        self,
        cache_key: str,
        owner_token: str,
        *,
        expires_at: datetime,
    ) -> bool:
        now = datetime.now(timezone.utc)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM menu_presentation_generation_lease WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO menu_presentation_generation_lease(
                      cache_key,owner_token,status,expires_at,retry_after,attempt_count,
                      error_code,created_at,updated_at
                    ) VALUES (?,?, 'GENERATING',?,NULL,1,NULL,?,?)
                    """,
                    (
                        cache_key,
                        owner_token,
                        expires_at.isoformat(),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                return True
            current_expiry = datetime.fromisoformat(str(row["expires_at"]))
            retry_after = (
                datetime.fromisoformat(str(row["retry_after"])) if row["retry_after"] else None
            )
            claimable = (
                str(row["owner_token"]) == owner_token
                or current_expiry <= now
                or (str(row["status"]) == "FAILED" and (retry_after is None or retry_after <= now))
            )
            if not claimable:
                return False
            connection.execute(
                """
                UPDATE menu_presentation_generation_lease
                SET owner_token=?,status='GENERATING',expires_at=?,retry_after=NULL,
                    attempt_count=attempt_count+1,error_code=NULL,updated_at=?
                WHERE cache_key=?
                """,
                (owner_token, expires_at.isoformat(), now.isoformat(), cache_key),
            )
            return True

    def finish_menu_presentation_lease(
        self,
        cache_key: str,
        owner_token: str,
        *,
        error_code: str | None = None,
    ) -> None:
        with self._connection() as connection:
            if error_code is None:
                connection.execute(
                    "DELETE FROM menu_presentation_generation_lease "
                    "WHERE cache_key=? AND owner_token=?",
                    (cache_key, owner_token),
                )
                return
            now = datetime.now(timezone.utc)
            connection.execute(
                """
                UPDATE menu_presentation_generation_lease
                SET status='FAILED',error_code=?,retry_after=?,updated_at=?
                WHERE cache_key=? AND owner_token=?
                """,
                (
                    error_code[:160],
                    (now + timedelta(seconds=1)).isoformat(),
                    now.isoformat(),
                    cache_key,
                    owner_token,
                ),
            )

    def get_evidence(self, menu_id: str) -> list[Evidence]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM evidence WHERE subject_id = ? ORDER BY evidence_id",
                (menu_id,),
            ).fetchall()
        return [Evidence(**dict(row)) for row in rows]

    @staticmethod
    def _resolved_knowledge_claims(
        connection: sqlite3.Connection,
        menu_id: str,
        option_item_ids: list[str] | None = None,
    ) -> tuple[str | None, str | None, list[Any], list[Any]]:
        active = connection.execute(
            """
            SELECT state.active_release_id, mapping.concept_id
            FROM knowledge_runtime_state state
            JOIN knowledge_release release ON release.release_id=state.active_release_id
            LEFT JOIN menu_concept_map mapping
              ON mapping.release_id=state.active_release_id AND mapping.menu_id=?
              AND mapping.mapping_status='MAPPED'
            WHERE state.state_key='ACTIVE' AND release.status='READY'
            """,
            (menu_id,),
        ).fetchone()
        if active is None:
            return None, None, [], []
        release_id = str(active["active_release_id"])
        concept_id = str(active["concept_id"]) if active["concept_id"] else None
        wiki_ingredient_rows: list[dict[str, Any]] = []
        wiki_allergen_rows: list[dict[str, Any]] = []
        if concept_id:
            wiki_ingredient_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT claim.*, ingredient.name_en, ingredient.name_ko, closure.depth,
                           claim.release_id AS source_version
                    FROM dish_concept_closure closure
                    JOIN concept_claim claim
                      ON claim.release_id=closure.release_id
                     AND claim.concept_id=closure.ancestor_concept_id
                    JOIN ingredient ON ingredient.ingredient_id=claim.ingredient_id
                    WHERE closure.release_id=? AND closure.descendant_concept_id=?
                      AND closure.inherit_claims=1 AND claim.claim_type='INGREDIENT'
                      AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
                    """,
                    (release_id, concept_id),
                ).fetchall()
            ]
            wiki_allergen_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT claim.*, allergen.code, closure.depth,
                           claim.release_id AS source_version
                    FROM dish_concept_closure closure
                    JOIN concept_claim claim
                      ON claim.release_id=closure.release_id
                     AND claim.concept_id=closure.ancestor_concept_id
                    JOIN allergen ON allergen.allergen_id=claim.allergen_id
                    WHERE closure.release_id=? AND closure.descendant_concept_id=?
                      AND closure.inherit_claims=1 AND claim.claim_type='ALLERGEN'
                      AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
                    """,
                    (release_id, concept_id),
                ).fetchall()
            ]
        menu_ingredient_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT fact.*, ingredient.name_en, ingredient.name_ko,
                       fact.source_id AS source_version
                FROM menu_ingredient fact
                JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
                WHERE fact.menu_id=?
                """,
                (menu_id,),
            ).fetchall()
        ]
        menu_allergen_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT fact.*, allergen.code, fact.evidence_id AS source_id,
                       'catalog' AS source_version
                FROM menu_allergen fact
                JOIN allergen ON allergen.allergen_id=fact.allergen_id
                WHERE fact.menu_id=?
                """,
                (menu_id,),
            ).fetchall()
        ]
        option_rows: list[dict[str, Any]] = []
        selected_options = list(dict.fromkeys(option_item_ids or []))
        if selected_options:
            placeholders = ",".join("?" for _ in selected_options)
            option_rows = [
                dict(row)
                for row in connection.execute(
                    f"""
                    SELECT effect.*, ingredient.name_en, ingredient.name_ko,
                           effect.option_item_id AS source_id,
                           effect.release_id AS source_version
                    FROM option_ingredient_effect effect
                    JOIN ingredient ON ingredient.ingredient_id=effect.ingredient_id
                    WHERE effect.release_id=? AND effect.option_item_id IN ({placeholders})
                    """,
                    (release_id, *selected_options),
                ).fetchall()
            ]
        return (
            release_id,
            concept_id,
            resolve_ingredient_claims(
                wiki_ingredient_rows,
                menu_ingredient_rows,
                option_rows,
            ),
            resolve_allergen_claims(wiki_allergen_rows, menu_allergen_rows),
        )

    @staticmethod
    def _bulk_resolved_knowledge_claims(
        connection: sqlite3.Connection,
        menu_ids: list[str],
        *,
        release_id: str | None = None,
    ) -> dict[str, tuple[list[Any], list[Any], list[Any]]]:
        """Resolve active Wiki/menu/merchant claims in a fixed number of queries."""

        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
        if release_id is None:
            active = connection.execute(
                """
                SELECT release.release_id
                FROM knowledge_runtime_state state
                JOIN knowledge_release release ON release.release_id=state.active_release_id
                WHERE state.state_key='ACTIVE' AND release.status='READY'
                """
            ).fetchone()
            if active is None:
                return {menu_id: ([], [], []) for menu_id in unique_ids}
            release_id = str(active["release_id"])
        else:
            ready = connection.execute(
                """
                SELECT 1 FROM knowledge_release
                WHERE release_id=? AND status='READY'
                """,
                (release_id,),
            ).fetchone()
            if ready is None:
                raise RuntimeError("PINNED_KNOWLEDGE_RELEASE_NOT_READY")
        placeholders = ",".join("?" for _ in unique_ids)
        params = (release_id, *unique_ids)

        wiki_ingredients = connection.execute(
            f"""
            SELECT mapping.menu_id,claim.*,ingredient.name_en,ingredient.name_ko,closure.depth,
                   claim.release_id AS source_version
            FROM menu_concept_map mapping
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
            JOIN concept_claim claim
              ON claim.release_id=closure.release_id
             AND claim.concept_id=closure.ancestor_concept_id
            JOIN ingredient ON ingredient.ingredient_id=claim.ingredient_id
            WHERE mapping.release_id=? AND mapping.mapping_status='MAPPED'
              AND mapping.menu_id IN ({placeholders})
              AND closure.inherit_claims=1 AND claim.claim_type='INGREDIENT'
              AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
            """,
            params,
        ).fetchall()
        wiki_allergens = connection.execute(
            f"""
            SELECT mapping.menu_id,claim.*,allergen.code,closure.depth,
                   claim.release_id AS source_version
            FROM menu_concept_map mapping
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
            JOIN concept_claim claim
              ON claim.release_id=closure.release_id
             AND claim.concept_id=closure.ancestor_concept_id
            JOIN allergen ON allergen.allergen_id=claim.allergen_id
            WHERE mapping.release_id=? AND mapping.mapping_status='MAPPED'
              AND mapping.menu_id IN ({placeholders})
              AND closure.inherit_claims=1 AND claim.claim_type='ALLERGEN'
              AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
            """,
            params,
        ).fetchall()
        menu_ingredients = connection.execute(
            f"""
            SELECT fact.menu_id,fact.*,ingredient.name_en,ingredient.name_ko,
                   fact.source_id AS source_version
            FROM menu_ingredient fact
            JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
            WHERE fact.menu_id IN ({placeholders})
            """,
            unique_ids,
        ).fetchall()
        menu_allergens = connection.execute(
            f"""
            SELECT fact.menu_id,fact.*,allergen.code,fact.evidence_id AS source_id,
                   'catalog' AS source_version
            FROM menu_allergen fact
            JOIN allergen ON allergen.allergen_id=fact.allergen_id
            WHERE fact.menu_id IN ({placeholders})
            """,
            unique_ids,
        ).fetchall()
        merchant_ingredients = connection.execute(
            f"""
            SELECT menu.menu_id,fact.*,ingredient.name_en,ingredient.name_ko,
                   declaration.source_version
            FROM menu
            JOIN merchant_ingredient fact ON fact.merchant_id=menu.merchant_id
            JOIN merchant_origin_declaration declaration
              ON declaration.release_id=fact.release_id
             AND declaration.declaration_id=fact.declaration_id
            JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
            WHERE fact.release_id=? AND menu.menu_id IN ({placeholders})
            """,
            params,
        ).fetchall()

        grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
            menu_id: defaultdict(list) for menu_id in unique_ids
        }
        for key, rows in (
            ("wiki_ingredients", wiki_ingredients),
            ("wiki_allergens", wiki_allergens),
            ("menu_ingredients", menu_ingredients),
            ("menu_allergens", menu_allergens),
            ("merchant_ingredients", merchant_ingredients),
        ):
            for source in rows:
                row = dict(source)
                menu_id = str(row.pop("menu_id"))
                if key == "merchant_ingredients":
                    row["source_id"] = f"{row['declaration_id']}:{row['ingredient_id']}"
                grouped[menu_id][key].append(row)

        return {
            menu_id: (
                resolve_ingredient_claims(
                    parts["wiki_ingredients"],
                    parts["menu_ingredients"],
                ),
                resolve_allergen_claims(
                    parts["wiki_allergens"],
                    parts["menu_allergens"],
                ),
                resolve_merchant_ingredient_claims(parts["merchant_ingredients"]),
            )
            for menu_id, parts in grouped.items()
        }

    @staticmethod
    def _bulk_knowledge_passages(
        connection: sqlite3.Connection,
        menu_ids: list[str],
        query_vector: list[float],
        *,
        query: str = "",
    ) -> dict[str, tuple[float, list[str]]]:
        """Return the strongest active knowledge-chunk signal for each candidate menu."""

        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
        placeholders = ",".join("?" for _ in unique_ids)
        rows = connection.execute(
            f"""
            SELECT mapping.menu_id,chunk.chunk_id,chunk.facet,chunk.content,
                   chunk.embedding_vector_json,
                   concept.canonical_name_ko,concept.canonical_name_en,concept.aliases_json
            FROM knowledge_runtime_state state
            JOIN knowledge_release release ON release.release_id=state.active_release_id
            JOIN menu_concept_map mapping
              ON mapping.release_id=release.release_id AND mapping.mapping_status='MAPPED'
            JOIN dish_concept_closure closure
              ON closure.release_id=mapping.release_id
             AND closure.descendant_concept_id=mapping.concept_id
             AND closure.inherit_claims=1
            JOIN knowledge_chunk chunk
              ON chunk.release_id=closure.release_id
             AND chunk.concept_id=closure.ancestor_concept_id
            JOIN dish_concept concept
              ON concept.release_id=chunk.release_id
             AND concept.concept_id=chunk.concept_id
            WHERE state.state_key='ACTIVE' AND release.status='READY'
              AND mapping.menu_id IN ({placeholders})
              AND chunk.embedding_vector_json IS NOT NULL
              AND chunk.embedding_model=release.embedding_model
              AND chunk.embedding_dimension=release.embedding_dimension
              AND chunk.embedding_version=release.embedding_version
            """,
            unique_ids,
        ).fetchall()
        grouped: dict[str, list[tuple[float, str]]] = defaultdict(list)
        for row in rows:
            aliases = [
                str(row["canonical_name_ko"]),
                str(row["canonical_name_en"]),
                *[str(alias) for alias in json.loads(str(row["aliases_json"]))],
            ]
            vector_similarity = cosine_similarity(
                query_vector,
                json.loads(str(row["embedding_vector_json"])),
            )
            grouped[str(row["menu_id"])].append(
                (
                    hybrid_knowledge_chunk_score(
                        query,
                        vector_similarity,
                        str(row["facet"]),
                        aliases,
                        str(row["content"]),
                    ),
                    str(row["chunk_id"]),
                )
            )
        result: dict[str, tuple[float, list[str]]] = {}
        for menu_id, values in grouped.items():
            ranked = sorted(values, key=lambda item: (-item[0], item[1]))
            result[menu_id] = (
                max(0.0, min(1.0, ranked[0][0])),
                [chunk_id for _, chunk_id in ranked[:RECOMMENDATION_PASSAGE_LIMIT]],
            )
        return result

    @staticmethod
    def _menu_hard_constraint_conflicts(
        connection: sqlite3.Connection,
        menu_id: str,
        state: MealNeedState,
        allergy_severity: str,
        option_item_ids: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Evaluate one menu against current server state and grounded facts."""

        menu = connection.execute(
            """
            SELECT m.*, merchant.service_area_id
            FROM menu m JOIN merchant ON merchant.merchant_id=m.merchant_id
            WHERE m.menu_id=?
            """,
            (menu_id,),
        ).fetchone()
        if menu is None or menu["availability"] != "AVAILABLE":
            return ["menu:unavailable"], []
        conflicts: list[str] = []
        if state.budget_krw is not None and int(menu["price"]) > state.budget_krw:
            conflicts.append("menu:over_budget")
        if (
            state.max_spiciness is not None
            and menu["spice_level"] is not None
            and int(menu["spice_level"]) > state.max_spiciness
        ):
            conflicts.append("menu:too_spicy")
        if menu_id in state.rejected_menu_ids:
            conflicts.append("menu:rejected")
        if state.service_area_id and menu["service_area_id"] != state.service_area_id:
            conflicts.append("menu:service_area")
        conflicts.extend(category_constraint_conflicts(str(menu["category"]), state))

        _, _, ingredient_claims, allergen_claims = SQLiteYobiRepository._resolved_knowledge_claims(
            connection, menu_id, option_item_ids
        )
        merchant_rows = connection.execute(
            """
            SELECT fact.*,ingredient.name_en,ingredient.name_ko,declaration.source_version
            FROM menu
            JOIN knowledge_runtime_state state ON state.state_key='ACTIVE'
            JOIN merchant_ingredient fact
              ON fact.release_id=state.active_release_id
             AND fact.merchant_id=menu.merchant_id
            JOIN merchant_origin_declaration declaration
              ON declaration.release_id=fact.release_id
             AND declaration.declaration_id=fact.declaration_id
            JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
            WHERE menu.menu_id=?
            """,
            (menu_id,),
        ).fetchall()
        merchant_claims = resolve_merchant_ingredient_claims(
            [
                {
                    **dict(row),
                    "source_id": f"{row['declaration_id']}:{row['ingredient_id']}",
                }
                for row in merchant_rows
            ]
        )
        conflicts.extend(ingredient_constraint_conflicts(ingredient_claims, state))
        conflicts.extend(allergen_constraint_conflicts(allergen_claims, state))
        if allergy_severity == "severe":
            conflicts.extend(
                severe_allergy_conflicts(
                    ingredient_claims,
                    allergen_claims,
                    state.dietary_rules,
                )
            )
        conflicts.extend(
            merchant_cross_contact_conflicts(
                merchant_claims,
                state,
                allergy_severity=allergy_severity,
            )
        )
        claim_ids = list(
            dict.fromkeys(
                [claim.source_id for claim in ingredient_claims]
                + [claim.source_id for claim in allergen_claims]
                + [claim.source_id for claim in merchant_claims]
            )
        )
        return list(dict.fromkeys(conflicts)), claim_ids

    def get_grounded_menu_knowledge(
        self,
        menu_id: str,
        query: str = "",
        option_item_ids: list[str] | None = None,
    ) -> GroundedMenuKnowledge:
        with self._connection() as connection:
            release_id, concept_id, ingredient_claims, allergen_claims = (
                self._resolved_knowledge_claims(connection, menu_id, option_item_ids)
            )
            passages: list[GroundedPassage] = []
            concept_ids: list[str] = []
            available_facets: list[str] = []
            wiki_dietary_rows: list[dict[str, Any]] = []
            wiki_preparation_rows: list[dict[str, Any]] = []
            if release_id and concept_id:
                concept_ids = [
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT ancestor_concept_id FROM dish_concept_closure
                        WHERE release_id=? AND descendant_concept_id=? AND inherit_claims=1
                        """,
                        (release_id, concept_id),
                    ).fetchall()
                ]
                placeholders = ",".join("?" for _ in concept_ids)
                rows = connection.execute(
                    f"""
                    SELECT chunk.chunk_id,chunk.document_id,chunk.concept_id,chunk.facet,
                           chunk.content,chunk.embedding_vector_json,
                           concept.canonical_name_ko,concept.canonical_name_en,
                           concept.aliases_json
                    FROM knowledge_chunk chunk
                    JOIN dish_concept concept
                      ON concept.release_id=chunk.release_id
                     AND concept.concept_id=chunk.concept_id
                    WHERE chunk.release_id=? AND chunk.concept_id IN ({placeholders})
                    """,
                    (release_id, *concept_ids),
                ).fetchall()
                available_facets = sorted({str(row["facet"]) for row in rows})
                wiki_dietary_rows = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT claim.*,da.code,da.display_name,closure.depth,
                               claim.release_id AS source_version
                        FROM dish_concept_closure closure
                        JOIN concept_claim claim
                          ON claim.release_id=closure.release_id
                         AND claim.concept_id=closure.ancestor_concept_id
                        JOIN dietary_attribute da ON da.attribute_id=claim.attribute_id
                        WHERE closure.release_id=? AND closure.descendant_concept_id=?
                          AND closure.inherit_claims=1 AND claim.claim_type='DIETARY'
                          AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
                        """,
                        (release_id, concept_id),
                    ).fetchall()
                ]
                wiki_preparation_rows = [
                    dict(row)
                    for row in connection.execute(
                        """
                        SELECT claim.*,closure.depth,claim.release_id AS source_version
                        FROM dish_concept_closure closure
                        JOIN concept_claim claim
                          ON claim.release_id=closure.release_id
                         AND claim.concept_id=closure.ancestor_concept_id
                        WHERE closure.release_id=? AND closure.descendant_concept_id=?
                          AND closure.inherit_claims=1 AND claim.claim_type='PREPARATION'
                          AND (closure.depth=0 OR claim.inheritance_mode='INHERIT')
                        """,
                        (release_id, concept_id),
                    ).fetchall()
                ]
                menu_name_row = connection.execute(
                    "SELECT name_en,category FROM menu WHERE menu_id=?", (menu_id,)
                ).fetchone()
                search_text = query.strip() or (
                    f"{menu_name_row['name_en']} {menu_name_row['category']} description ingredients safety"
                    if menu_name_row
                    else menu_id
                )
                query_vector = deterministic_embedding(f"query: {search_text}")
                scored = [
                    (
                        hybrid_knowledge_chunk_score(
                            search_text,
                            cosine_similarity(
                                query_vector,
                                json.loads(str(row["embedding_vector_json"])),
                            ),
                            str(row["facet"]),
                            [
                                str(row["canonical_name_ko"]),
                                str(row["canonical_name_en"]),
                                *[str(alias) for alias in json.loads(str(row["aliases_json"]))],
                            ],
                            str(row["content"]),
                        ),
                        row,
                    )
                    for row in rows
                    if row["embedding_vector_json"]
                ]
                scored.sort(key=lambda item: (-item[0], str(item[1]["chunk_id"])))
                for score, row in scored[:5]:
                    passages.append(
                        GroundedPassage(
                            chunk_id=row["chunk_id"],
                            document_id=row["document_id"],
                            concept_id=row["concept_id"],
                            facet=row["facet"],
                            content=row["content"],
                            source_kind=KnowledgeSourceKind.SYNTHETIC_WIKI,
                            source_version=release_id,
                            score=round(score, 4),
                        )
                    )
            else:
                legacy_rows = connection.execute(
                    """
                    SELECT knowledge_id,knowledge_type,content,updated_at
                    FROM menu_knowledge WHERE menu_id=? ORDER BY knowledge_id LIMIT 3
                    """,
                    (menu_id,),
                ).fetchall()
                passages = [
                    GroundedPassage(
                        chunk_id=row["knowledge_id"],
                        document_id=row["knowledge_id"],
                        facet=row["knowledge_type"],
                        content=row["content"],
                        source_kind=KnowledgeSourceKind.LEGACY_MENU_KNOWLEDGE,
                        source_version=row["updated_at"],
                        score=0.0,
                    )
                    for row in legacy_rows
                ]
            menu_dietary_rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT fact.*,da.code,da.display_name,
                           fact.evidence_id AS source_id,'catalog' AS source_version
                    FROM menu_dietary_attribute fact
                    JOIN dietary_attribute da ON da.attribute_id=fact.attribute_id
                    WHERE fact.menu_id=?
                    ORDER BY fact.attribute_id
                    """,
                    (menu_id,),
                ).fetchall()
            ]
            dietary_claims = resolve_dietary_claims(wiki_dietary_rows, menu_dietary_rows)
            preparation_claims = resolve_preparation_claims(wiki_preparation_rows)
            origin_rows = connection.execute(
                """
                SELECT DISTINCT declaration.raw_text
                FROM menu
                JOIN merchant_origin_declaration declaration
                  ON declaration.merchant_id=menu.merchant_id
                JOIN knowledge_runtime_state state
                  ON state.active_release_id=declaration.release_id
                WHERE menu.menu_id=?
                ORDER BY declaration.declaration_id
                """,
                (menu_id,),
            ).fetchall()
            merchant_ingredient_rows = connection.execute(
                """
                SELECT fact.*,ingredient.name_en,ingredient.name_ko,declaration.source_version
                FROM menu
                JOIN knowledge_runtime_state state ON state.state_key='ACTIVE'
                JOIN merchant_ingredient fact
                  ON fact.release_id=state.active_release_id
                 AND fact.merchant_id=menu.merchant_id
                JOIN merchant_origin_declaration declaration
                  ON declaration.release_id=fact.release_id
                 AND declaration.declaration_id=fact.declaration_id
                JOIN ingredient ON ingredient.ingredient_id=fact.ingredient_id
                WHERE menu.menu_id=?
                ORDER BY fact.ingredient_id,fact.declaration_id
                """,
                (menu_id,),
            ).fetchall()
            merchant_claims = resolve_merchant_ingredient_claims(
                [
                    {
                        **dict(row),
                        "source_id": f"{row['declaration_id']}:{row['ingredient_id']}",
                    }
                    for row in merchant_ingredient_rows
                ]
            )
            cross_contact_unknowns = [
                (
                    f"{claim.code}: menu-specific absence is recorded, but cross-contact "
                    "is UNKNOWN; this is not a safety certification."
                )
                for claim in allergen_claims
                if claim.status is ClaimStatus.CONFIRMED_ABSENT
                and claim.cross_contamination_status == "UNKNOWN"
            ]
        return GroundedMenuKnowledge(
            menu_id=menu_id,
            release_id=release_id,
            concept_id=concept_id,
            concept_lineage=concept_ids,
            available_facets=available_facets,
            ingredient_claims=ingredient_claims,
            allergen_claims=allergen_claims,
            dietary_claims=dietary_claims,
            preparation_claims=preparation_claims,
            merchant_ingredient_claims=merchant_claims,
            passages=passages,
            merchant_origin_notes=[str(row[0]) for row in origin_rows],
            unknowns=[
                "Merchant-specific recipe differences are unknown unless a menu fact overrides the Wiki.",
                "Shared-kitchen cross-contact is not confirmed by the synthetic Wiki or origin declaration.",
                *cross_contact_unknowns,
            ],
        )

    def compare_merchants(
        self,
        category: str,
        profile: Profile,
        limit: int = 3,
        meal_need_state: MealNeedState | None = None,
    ) -> list[MerchantComparison]:
        state = apply_profile_constraints(
            meal_need_state.model_copy(deep=True)
            if meal_need_state is not None
            else MealNeedState(max_spiciness=profile.spice_tolerance),
            profile.dietary_rules,
            profile.religion_selection,
        )
        if state.max_spiciness is None:
            state.max_spiciness = profile.spice_tolerance
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*, COALESCE(r.name_en,r.name_ko) AS merchant_name, r.delivery_fee, r.eta_min,
                       r.eta_max, r.flavor_profile, r.packaging_signal,
                       r.service_area_id AS merchant_service_area_id
                FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                WHERE lower(m.category) = lower(?) AND m.availability = 'AVAILABLE'
                ORDER BY m.price, r.eta_min
                """,
                (category,),
            ).fetchall()
            hard_conflicts = {
                str(row["menu_id"]): self._menu_hard_constraint_conflicts(
                    connection,
                    str(row["menu_id"]),
                    state,
                    profile.allergy_severity,
                )[0]
                for row in rows
            }
        summaries: list[MenuSummary] = []
        merchant_areas: dict[str, str] = {}
        rows_by_menu = {str(row["menu_id"]): row for row in rows}
        for index, row in enumerate(rows):
            if hard_conflicts[str(row["menu_id"])]:
                continue
            allergens = set(json.loads(row["allergen_tags_json"]))
            tags = set(json.loads(row["dietary_tags_json"]))
            status = EvidenceStatus.UNKNOWN
            if "shellfish_risk" in allergens:
                status = EvidenceStatus.RISK_SIGNAL
            elif "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
            summary = self._menu_summary(
                row,
                ["Comparable listing for the requested food"],
                ["Cross-contamination is not verified"],
                status,
                max(0.1, 0.6 - index * 0.001),
            )
            summaries.append(summary)
            merchant_areas[summary.merchant_id] = str(row["merchant_service_area_id"])
        ranked = rerank_menu_candidates(summaries, state, merchant_areas, limit)
        comparisons: list[MerchantComparison] = []
        for menu in ranked:
            row = rows_by_menu[menu.menu_id]
            dietary_note = "Ingredient and cross-contamination details are not verified."
            if menu.evidence_status == EvidenceStatus.RISK_SIGNAL:
                dietary_note = "The synthetic menu specification contains a shellfish risk signal."
            elif menu.evidence_status == EvidenceStatus.VERIFIED:
                dietary_note = "Sauce marked seafood-free; cross-contamination remains unknown."
            comparisons.append(
                MerchantComparison(
                    merchant_id=menu.merchant_id,
                    merchant_name=menu.merchant_name,
                    menu_id=menu.menu_id,
                    menu_name=menu.name_en,
                    price=menu.price,
                    delivery_fee=menu.delivery_fee,
                    eta=f"{row['eta_min']}-{row['eta_max']} min",
                    portion=(
                        "Portion information not provided"
                        if menu.serves_max is None
                        else "One-person portion"
                        if menu.serves_max == 1
                        else "Shareable portion"
                    ),
                    flavor=row["flavor_profile"],
                    packaging_signal=row["packaging_signal"],
                    dietary_status=menu.evidence_status,
                    dietary_note=dietary_note,
                    best_for="; ".join(menu.match_reasons),
                    evidence_ids=[
                        evidence.evidence_id for evidence in self.get_evidence(menu.menu_id)
                    ],
                )
            )
        return comparisons

    def get_options(self, menu_id: str, session_id: str | None = None) -> list[OptionGroup]:
        with self._connection() as connection:
            language_code = "en"
            if session_id:
                language_row = connection.execute(
                    """
                    SELECT profile.preferred_language FROM chat_session session
                    JOIN user_profile profile ON profile.profile_id=session.profile_id
                    WHERE session.session_id=?
                    """,
                    (session_id,),
                ).fetchone()
                if language_row:
                    requested = normalize_preference_locale(str(language_row[0]))
                    language_code = requested if requested in {"ko", "ja"} else "en"
            family = connection.execute(
                """
                SELECT family.release_family_id,family.knowledge_release_id,
                       family.certification_release_id,
                       family.synthetic_enrichment_release_id
                FROM recommendation_runtime_state state
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                JOIN knowledge_release release
                  ON release.release_id=family.knowledge_release_id
                WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                  AND release.status='READY'
                """
            ).fetchone()
            base_vegan_status: str | None = None
            base_vegan_warning: str | None = None
            halal_certification_preserved: bool | None = None
            option_effects: dict[str, list[sqlite3.Row]] = defaultdict(list)
            synthetic_option_states: dict[str, tuple[bool, bool]] = {}
            if family is not None:
                base_vegan_status, base_vegan_warning, _ = self._v2_vegan_classifications(
                    connection,
                    [menu_id],
                    knowledge_release_id=str(family["knowledge_release_id"]),
                ).get(menu_id, ("UNKNOWN", None, []))
                valid_certifications = self._valid_halal_certifications_in_connection(
                    connection,
                    release_family_id=str(family["release_family_id"]),
                    instant=_now(),
                )
                if menu_id in valid_certifications:
                    # Options do not change the certification scope in the current
                    # catalog, so either a restaurant- or menu-scoped certificate
                    # remains applicable to the selected menu.
                    halal_certification_preserved = True
                effect_rows = connection.execute(
                    """
                    SELECT effect.option_item_id,effect.ingredient_id,
                           effect.effect,effect.assertion_status
                    FROM option_ingredient_effect effect
                    JOIN menu_option_item item
                      ON item.option_item_id=effect.option_item_id
                    JOIN menu_option_group option_group
                      ON option_group.option_group_id=item.option_group_id
                    WHERE option_group.menu_id=? AND effect.release_id=?
                    """,
                    (menu_id, str(family["knowledge_release_id"])),
                ).fetchall()
                for effect in effect_rows:
                    option_effects[str(effect["option_item_id"])].append(effect)
                if family["synthetic_enrichment_release_id"]:
                    synthetic_release_id = str(family["synthetic_enrichment_release_id"])
                    menu_profile = connection.execute(
                        """
                        SELECT halal_fit,vegan_fit FROM synthetic_menu_profile
                        WHERE release_id=? AND menu_id=?
                        """,
                        (synthetic_release_id, menu_id),
                    ).fetchone()
                    if menu_profile is not None:
                        halal_certification_preserved = bool(menu_profile["halal_fit"])
                        base_vegan_status = (
                            "LIKELY_FIT" if menu_profile["vegan_fit"] else "CONFLICT"
                        )
                        base_vegan_warning = (
                            None
                            if menu_profile["vegan_fit"]
                            else "This menu is not marked as vegan-friendly."
                        )
                    synthetic_option_states = {
                        str(row["option_item_id"]): (
                            bool(row["halal_conflict"]),
                            bool(row["vegan_conflict"]),
                        )
                        for row in connection.execute(
                            """
                            SELECT profile.option_item_id,profile.halal_conflict,
                                   profile.vegan_conflict
                            FROM synthetic_option_profile profile
                            JOIN menu_option_item item
                              ON item.option_item_id=profile.option_item_id
                            JOIN menu_option_group groups
                              ON groups.option_group_id=item.option_group_id
                            WHERE profile.release_id=? AND groups.menu_id=?
                            """,
                            (synthetic_release_id, menu_id),
                        ).fetchall()
                    }

            def v2_option_state(item_id: str) -> tuple[str | None, str | None]:
                synthetic_state = synthetic_option_states.get(item_id)
                if synthetic_state is not None:
                    return (
                        ("CONFLICT", "This option is not marked as vegan-friendly.")
                        if synthetic_state[1]
                        else (base_vegan_status, base_vegan_warning)
                    )
                effects = option_effects.get(item_id, [])
                animal_adds = [
                    effect
                    for effect in effects
                    if str(effect["effect"]).upper() == "ADD"
                    and str(effect["ingredient_id"]) in VEGAN_INGREDIENTS
                ]
                if any(
                    str(effect["assertion_status"]).upper()
                    in {"CONFIRMED_PRESENT", "PRESENT", "VERIFIED"}
                    for effect in animal_adds
                ):
                    return (
                        "CONFLICT",
                        "This option adds a confirmed animal-derived ingredient and does not fit a vegan selection.",
                    )
                if any(
                    str(effect["assertion_status"]).upper() not in {"CONFIRMED_ABSENT", "ABSENT"}
                    for effect in animal_adds
                ):
                    return (
                        "POSSIBLE_WITH_CHECKS",
                        "This option may add an animal-derived ingredient; check before ordering vegan.",
                    )
                # Removing one ingredient never upgrades the whole menu to vegan.
                # Preserve the base-menu classification and its existing caution.
                return base_vegan_status, base_vegan_warning

            groups = connection.execute(
                "SELECT * FROM menu_option_group WHERE menu_id = ? ORDER BY sort_order",
                (menu_id,),
            ).fetchall()
            group_localizations: dict[str, str] = {}
            item_localizations: dict[str, str] = {}
            if family is not None and family["synthetic_enrichment_release_id"]:
                group_localizations = {
                    str(row["option_group_id"]): str(row["display_name"])
                    for row in connection.execute(
                        """
                        SELECT localization.option_group_id,localization.display_name
                        FROM option_group_localization localization
                        JOIN menu_option_group groups
                          ON groups.option_group_id=localization.option_group_id
                        WHERE localization.release_id=?
                          AND localization.language_code=? AND groups.menu_id=?
                        """,
                        (
                            str(family["synthetic_enrichment_release_id"]),
                            language_code,
                            menu_id,
                        ),
                    ).fetchall()
                }
                item_localizations = {
                    str(row["option_item_id"]): str(row["display_name"])
                    for row in connection.execute(
                        """
                        SELECT localization.option_item_id,localization.display_name
                        FROM option_item_localization localization
                        JOIN menu_option_item item
                          ON item.option_item_id=localization.option_item_id
                        JOIN menu_option_group groups
                          ON groups.option_group_id=item.option_group_id
                        WHERE localization.release_id=?
                          AND localization.language_code=? AND groups.menu_id=?
                        """,
                        (
                            str(family["synthetic_enrichment_release_id"]),
                            language_code,
                            menu_id,
                        ),
                    ).fetchall()
                }
            result = []
            for group in groups:
                items = connection.execute(
                    """
                    SELECT i.*, (
                      SELECT GROUP_CONCAT(odc.rule_code, ',')
                      FROM option_dietary_conflict odc
                      WHERE odc.option_item_id=i.option_item_id
                    ) AS conflicting_rules_csv
                    FROM menu_option_item i
                    WHERE i.option_group_id = ? ORDER BY i.sort_order
                    """,
                    (group["option_group_id"],),
                ).fetchall()
                v2_states = {
                    str(item["option_item_id"]): v2_option_state(str(item["option_item_id"]))
                    for item in items
                }
                result.append(
                    OptionGroup(
                        option_group_id=group["option_group_id"],
                        name_en=_catalog_text(group["name_en"], group["name_ko"]),
                        name_ko=group["name_ko"],
                        display_name=group_localizations.get(
                            str(group["option_group_id"]),
                            str(group["name_ko"])
                            if language_code == "ko"
                            else _catalog_text(group["name_en"], group["name_ko"]),
                        ),
                        description=_catalog_text(group["description"]),
                        required=bool(group["required"]),
                        min_select=group["min_select"],
                        max_select=group["max_select"],
                        items=[
                            OptionItem(
                                option_item_id=item["option_item_id"],
                                name_en=_catalog_text(item["name_en"], item["name_ko"]),
                                name_ko=item["name_ko"],
                                display_name=item_localizations.get(
                                    str(item["option_item_id"]),
                                    str(item["name_ko"])
                                    if language_code == "ko"
                                    else _catalog_text(item["name_en"], item["name_ko"]),
                                ),
                                description=_catalog_text(item["description"]),
                                price_delta=item["price_delta"],
                                available=item["availability"] == "AVAILABLE",
                                dietary_conflict=item["dietary_conflict"],
                                conflicting_rules=(
                                    str(item["conflicting_rules_csv"]).split(",")
                                    if item["conflicting_rules_csv"]
                                    else []
                                ),
                                halal_certification_preserved=(
                                    False
                                    if synthetic_option_states.get(
                                        str(item["option_item_id"]), (False, False)
                                    )[0]
                                    else halal_certification_preserved
                                ),
                                vegan_status=cast(
                                    Any,
                                    v2_states[str(item["option_item_id"])][0],
                                ),
                                vegan_warning=v2_states[str(item["option_item_id"])][1],
                            )
                            for item in items
                        ],
                    )
                )
        return result

    def option_localizations_complete(
        self,
        session_id: str,
        menu_id: str,
        group_ids: list[str],
        item_ids: list[str],
        prompt_version: str,
    ) -> bool:
        localized_groups, localized_items = self.load_option_localizations(
            session_id,
            menu_id,
            prompt_version,
        )
        return set(localized_groups) == set(group_ids) and set(localized_items) == set(item_ids)

    def load_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        prompt_version: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        with self._connection() as connection:
            context = connection.execute(
                """
                SELECT profile.preferred_language,family.synthetic_enrichment_release_id
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE session.session_id=?
                """,
                (session_id,),
            ).fetchone()
            if context is None or not context["synthetic_enrichment_release_id"]:
                return {}, {}
            requested = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested if requested in {"ko", "ja"} else "en"
            localized_groups = {
                str(row["option_group_id"]): str(row["display_name"])
                for row in connection.execute(
                    """
                    SELECT localization.option_group_id,localization.display_name
                    FROM runtime_option_group_localization localization
                    JOIN menu_option_group groups
                      ON groups.option_group_id=localization.option_group_id
                    WHERE localization.release_id=? AND localization.language_code=?
                      AND localization.prompt_version=? AND groups.menu_id=?
                    """,
                    (
                        str(context["synthetic_enrichment_release_id"]),
                        language_code,
                        prompt_version,
                        menu_id,
                    ),
                )
            }
            localized_items = {
                str(row["option_item_id"]): str(row["display_name"])
                for row in connection.execute(
                    """
                    SELECT localization.option_item_id,localization.display_name
                    FROM runtime_option_item_localization localization
                    JOIN menu_option_item item
                      ON item.option_item_id=localization.option_item_id
                    JOIN menu_option_group groups
                      ON groups.option_group_id=item.option_group_id
                    WHERE localization.release_id=? AND localization.language_code=?
                      AND localization.prompt_version=? AND groups.menu_id=?
                    """,
                    (
                        str(context["synthetic_enrichment_release_id"]),
                        language_code,
                        prompt_version,
                        menu_id,
                    ),
                )
            }
        return localized_groups, localized_items

    def save_option_localizations(
        self,
        session_id: str,
        menu_id: str,
        group_names: dict[str, str],
        item_names: dict[str, str],
        model_id: str,
        prompt_version: str,
    ) -> None:
        with self._connection() as connection:
            context = connection.execute(
                """
                SELECT profile.preferred_language,family.synthetic_enrichment_release_id
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE session.session_id=?
                """,
                (session_id,),
            ).fetchone()
            if context is None or not context["synthetic_enrichment_release_id"]:
                raise RuntimeError("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            requested = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested if requested in {"ko", "ja"} else "en"
            group_rows = connection.execute(
                """
                SELECT option_group_id,name_en,name_ko FROM menu_option_group
                WHERE menu_id=?
                """,
                (menu_id,),
            ).fetchall()
            item_rows = connection.execute(
                """
                SELECT item.option_item_id,item.option_group_id,item.name_en,item.name_ko
                FROM menu_option_item item
                JOIN menu_option_group groups
                  ON groups.option_group_id=item.option_group_id
                WHERE groups.menu_id=?
                """,
                (menu_id,),
            ).fetchall()
            known_group_ids = {str(row["option_group_id"]) for row in group_rows}
            known_item_ids = {str(row["option_item_id"]) for row in item_rows}
            if not set(group_names).issubset(known_group_ids):
                raise ValueError("OPTION_LOCALIZATION_GROUP_IDS_MISMATCH")
            if not set(item_names).issubset(known_item_ids):
                raise ValueError("OPTION_LOCALIZATION_ITEM_IDS_MISMATCH")
            if any(
                str(row["option_item_id"]) in item_names
                and str(row["option_group_id"]) not in group_names
                for row in item_rows
            ):
                raise ValueError("OPTION_LOCALIZATION_ITEM_GROUP_MISMATCH")
            release_id = str(context["synthetic_enrichment_release_id"])
            generated_at = _now()
            for row in group_rows:
                if str(row["option_group_id"]) not in group_names:
                    continue
                source_hash = hashlib.sha256(
                    json.dumps(
                        [row["name_ko"], row["name_en"], language_code],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO runtime_option_group_localization(
                      release_id,option_group_id,language_code,display_name,
                      model_id,prompt_version,source_hash,generated_at
                    ) VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(release_id,option_group_id,language_code,prompt_version)
                    DO UPDATE SET
                      display_name=excluded.display_name,model_id=excluded.model_id,
                      prompt_version=excluded.prompt_version,
                      source_hash=excluded.source_hash,generated_at=excluded.generated_at
                    """,
                    (
                        release_id,
                        row["option_group_id"],
                        language_code,
                        group_names[str(row["option_group_id"])],
                        model_id,
                        prompt_version,
                        source_hash,
                        generated_at,
                    ),
                )
            for row in item_rows:
                if str(row["option_item_id"]) not in item_names:
                    continue
                source_hash = hashlib.sha256(
                    json.dumps(
                        [row["name_ko"], row["name_en"], language_code],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO runtime_option_item_localization(
                      release_id,option_item_id,language_code,display_name,
                      model_id,prompt_version,source_hash,generated_at
                    ) VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(release_id,option_item_id,language_code,prompt_version)
                    DO UPDATE SET
                      display_name=excluded.display_name,model_id=excluded.model_id,
                      prompt_version=excluded.prompt_version,
                      source_hash=excluded.source_hash,generated_at=excluded.generated_at
                    """,
                    (
                        release_id,
                        row["option_item_id"],
                        language_code,
                        item_names[str(row["option_item_id"])],
                        model_id,
                        prompt_version,
                        source_hash,
                        generated_at,
                    ),
                )

    def save_menu_runtime_localizations(
        self,
        session_id: str,
        menu_id: str,
        localized_title: str,
        localized_source_description: str,
        model_id: str,
        prompt_version: str,
    ) -> None:
        with self._connection() as connection:
            context = connection.execute(
                """
                SELECT profile.preferred_language,
                       family.synthetic_enrichment_release_id,
                       menu.name_ko,menu.description
                FROM chat_session session
                JOIN user_profile profile ON profile.profile_id=session.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                JOIN menu ON menu.menu_id=?
                WHERE session.session_id=?
                """,
                (menu_id, session_id),
            ).fetchone()
            if context is None or not context["synthetic_enrichment_release_id"]:
                raise RuntimeError("SYNTHETIC_ENRICHMENT_UNAVAILABLE")
            requested = normalize_preference_locale(str(context["preferred_language"]))
            language_code = requested if requested in {"ko", "ja"} else "en"
            release_id = str(context["synthetic_enrichment_release_id"])
            generated_at = _now()
            title_source_hash = hashlib.sha256(
                json.dumps(
                    [context["name_ko"], language_code, prompt_version],
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
            connection.execute(
                """
                INSERT INTO menu_localization(
                  release_id,menu_id,language_code,display_name,model_id,prompt_version,
                  wiki_evidence_ids_json,source_hash,validation_status,generated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(release_id,menu_id,language_code) DO UPDATE SET
                  display_name=excluded.display_name,model_id=excluded.model_id,
                  prompt_version=excluded.prompt_version,source_hash=excluded.source_hash,
                  validation_status='VALID',generated_at=excluded.generated_at
                """,
                (
                    release_id,
                    menu_id,
                    language_code,
                    localized_title,
                    model_id,
                    prompt_version,
                    "[]",
                    title_source_hash,
                    "VALID",
                    generated_at,
                ),
            )
            if str(context["description"] or ""):
                description_source_hash = hashlib.sha256(
                    json.dumps(
                        [context["description"], language_code, prompt_version],
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO menu_source_description_localization(
                      release_id,menu_id,language_code,description_text,model_id,
                      prompt_version,source_hash,validation_status,generated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(release_id,menu_id,language_code) DO UPDATE SET
                      description_text=excluded.description_text,model_id=excluded.model_id,
                      prompt_version=excluded.prompt_version,source_hash=excluded.source_hash,
                      validation_status='VALID',generated_at=excluded.generated_at
                    """,
                    (
                        release_id,
                        menu_id,
                        language_code,
                        localized_source_description,
                        model_id,
                        prompt_version,
                        description_source_hash,
                        "VALID",
                        generated_at,
                    ),
                )

    def resolve_address(self, text: str, file_hash: str | None = None) -> list[AddressCandidate]:
        normalized = normalize_address_text(text)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT place.* FROM address_place place
                JOIN service_area area ON area.service_area_id=place.service_area_id
                WHERE area.active=1 ORDER BY place.place_id
                """
            ).fetchall()
        scored = []
        for row in rows:
            aliases = json.loads(row["aliases_json"])
            haystack = " ".join([row["name_en"], row["name_ko"], *aliases]).lower()
            normalized_road = normalize_address_text(str(row["road_address"]))
            score = (
                0.98 if row["place_id"] == "hotel_demo_01" and "myeongdong" in normalized else 0.0
            )
            if normalized_road in normalized:
                score = max(score, 0.95)
            if normalized and any(token in haystack for token in normalized.split()):
                score = max(score, 0.82)
            if file_hash and row["fixture_sha256"] == file_hash:
                score = 1.0
            if score > 0:
                scored.append((score, row))
        if not scored and rows:
            scored = [(0.35, rows[0])]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            AddressCandidate(
                place_id=row["place_id"],
                hotel_name=row["name_en"],
                road_address=row["road_address"],
                postal_code=row["postal_code"],
                city=row["city"],
                service_area_id=row["service_area_id"],
                delivery_hint=row["delivery_hint"],
                confidence=score,
                source="canonical_fixture" if score >= 0.98 else "manual",
                needs_confirmation=True,
            )
            for score, row in scored[:3]
        ]

    def get_address_candidate(self, place_id: str) -> AddressCandidate | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT place.* FROM address_place place
                JOIN service_area area ON area.service_area_id=place.service_area_id
                WHERE place.place_id=? AND area.active=1
                """,
                (place_id,),
            ).fetchone()
        if row is None:
            return None
        return AddressCandidate(
            place_id=row["place_id"],
            hotel_name=row["name_en"],
            road_address=row["road_address"],
            postal_code=row["postal_code"],
            city=row["city"],
            service_area_id=row["service_area_id"],
            delivery_hint=row["delivery_hint"],
            confidence=1.0,
            source="canonical_fixture",
            needs_confirmation=True,
        )

    def save_address(
        self,
        session_id: str,
        candidate: AddressCandidate,
        source_image_hash: str | None = None,
    ) -> str:
        address_ref_id = _id("address")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active_area = connection.execute(
                "SELECT 1 FROM service_area WHERE service_area_id=? AND active=1",
                (candidate.service_area_id,),
            ).fetchone()
            if active_area is None:
                raise ValueError("ADDRESS_OUTSIDE_SERVICE_AREA")
            connection.execute(
                """
                INSERT INTO address_ref (
                  address_ref_id, session_id, source_type, source_image_hash, place_id, hotel_name,
                  road_address, extraction_confidence, service_area_id, confirmed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    address_ref_id,
                    session_id,
                    candidate.source,
                    source_image_hash,
                    candidate.place_id if candidate.place_id != "manual" else None,
                    candidate.hotel_name,
                    candidate.road_address,
                    candidate.confidence,
                    candidate.service_area_id,
                    _now(),
                ),
            )
            cart_id = self._ensure_cart(connection, session_id)
            connection.execute(
                """
                UPDATE cart SET address_ref_id = ?, version = version + 1,
                  confirmed = 0, updated_at = ? WHERE cart_id = ?
                """,
                (address_ref_id, _now(), cart_id),
            )
        return address_ref_id

    def get_session_service_area(self, session_id: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT ref.service_area_id
                FROM cart JOIN address_ref ref ON ref.address_ref_id=cart.address_ref_id
                JOIN service_area area ON area.service_area_id=ref.service_area_id
                WHERE cart.session_id=? AND ref.confirmed=1 AND area.active=1
                """,
                (session_id,),
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    @staticmethod
    def _ensure_cart(connection: sqlite3.Connection, session_id: str) -> str:
        row = connection.execute(
            "SELECT cart_id FROM cart WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row:
            return row["cart_id"]
        cart_id = _id("cart")
        now = _now()
        connection.execute(
            "INSERT INTO cart (cart_id, session_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (cart_id, session_id, now, now),
        )
        return cart_id

    @staticmethod
    def _cart_item_values(
        connection: sqlite3.Connection, item: CartItemInput
    ) -> tuple[sqlite3.Row, list[dict[str, Any]], int]:
        menu = connection.execute(
            "SELECT * FROM menu WHERE menu_id = ? AND availability = 'AVAILABLE'", (item.menu_id,)
        ).fetchone()
        if not menu:
            raise KeyError("MENU_NOT_FOUND")
        options: list[dict[str, Any]] = []
        option_total = 0
        selected_counts: dict[str, int] = {}
        for option_id in item.option_item_ids:
            option = connection.execute(
                """
                SELECT i.*, g.menu_id FROM menu_option_item i
                JOIN menu_option_group g ON g.option_group_id = i.option_group_id
                WHERE i.option_item_id = ? AND i.availability = 'AVAILABLE'
                """,
                (option_id,),
            ).fetchone()
            if not option or option["menu_id"] != item.menu_id:
                raise ValueError("INVALID_MENU_OPTION")
            group_id = str(option["option_group_id"])
            selected_counts[group_id] = selected_counts.get(group_id, 0) + 1
            options.append(
                {
                    "option_item_id": option["option_item_id"],
                    "name_en": _catalog_text(option["name_en"], option["name_ko"]),
                    "name_ko": option["name_ko"],
                    "price_delta": int(option["price_delta"]),
                }
            )
            option_total += int(option["price_delta"])
        groups = connection.execute(
            """
            SELECT option_group_id, min_select, max_select
            FROM menu_option_group WHERE menu_id = ?
            """,
            (item.menu_id,),
        ).fetchall()
        if any(
            selected_counts.get(str(group["option_group_id"]), 0) < int(group["min_select"])
            for group in groups
        ):
            raise ValueError("REQUIRED_MENU_OPTION_MISSING")
        if any(
            selected_counts.get(str(group["option_group_id"]), 0) > int(group["max_select"])
            for group in groups
        ):
            raise ValueError("OPTION_GROUP_MAX_EXCEEDED")
        return menu, options, (int(menu["price"]) + option_total) * item.quantity

    @staticmethod
    def _validated_note_translation(
        connection: sqlite3.Connection,
        session_id: str,
        item: CartItemInput,
    ) -> tuple[str, str | None]:
        if not item.user_note.strip():
            return "", None
        if not item.note_translation_id:
            raise ValueError("RESTAURANT_NOTE_TRANSLATION_REQUIRED")
        row = connection.execute(
            """
            SELECT korean_text,source_text,status
            FROM restaurant_note_translation
            WHERE translation_id=? AND session_id=?
            """,
            (item.note_translation_id, session_id),
        ).fetchone()
        if (
            row is None
            or str(row["status"]) != "SUCCEEDED"
            or str(row["source_text"]) != item.user_note
            or not row["korean_text"]
        ):
            raise ValueError("RESTAURANT_NOTE_TRANSLATION_REQUIRED")
        return str(row["korean_text"]), item.note_translation_id

    def add_cart_item(
        self,
        session_id: str,
        item: CartItemInput,
        agent_request_key: str | None = None,
    ) -> CartPreview:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cart_id = self._ensure_cart(connection, session_id)
            if agent_request_key:
                duplicate = connection.execute(
                    """
                    SELECT menu_id,quantity,option_snapshot_json,user_note
                    FROM cart_item WHERE cart_id=? AND agent_request_key=? LIMIT 1
                    """,
                    (cart_id, agent_request_key),
                ).fetchone()
                if duplicate:
                    stored_option_ids = sorted(
                        str(option["option_item_id"])
                        for option in json.loads(duplicate["option_snapshot_json"])
                    )
                    if (
                        str(duplicate["menu_id"]) != item.menu_id
                        or int(duplicate["quantity"]) != item.quantity
                        or stored_option_ids != sorted(item.option_item_ids)
                        or str(duplicate["user_note"] or "") != item.user_note
                    ):
                        raise ValueError("IDEMPOTENCY_KEY_REUSED")
                    return self.get_cart(session_id)
            menu, options, line_total = self._cart_item_values(connection, item)
            korean_note, note_translation_id = self._validated_note_translation(
                connection, session_id, item
            )
            other_merchant = connection.execute(
                """
                SELECT 1 FROM cart_item WHERE cart_id = ? AND merchant_id <> ? LIMIT 1
                """,
                (cart_id, menu["merchant_id"]),
            ).fetchone()
            if other_merchant:
                raise ValueError("CART_MULTIPLE_MERCHANTS")
            cart_item_id = _id("cartitem")
            connection.execute(
                """
                INSERT INTO cart_item (
                  cart_item_id, cart_id, menu_id, merchant_id, quantity, unit_price,
                  menu_snapshot_json, option_snapshot_json, line_total, user_note,
                  korean_note, note_translation_id, agent_request_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cart_item_id,
                    cart_id,
                    menu["menu_id"],
                    menu["merchant_id"],
                    item.quantity,
                    menu["price"],
                    json.dumps(
                        {
                            "name_en": _catalog_text(menu["name_en"], menu["name_ko"]),
                            "price": menu["price"],
                        }
                    ),
                    json.dumps(options),
                    line_total,
                    item.user_note,
                    korean_note,
                    note_translation_id,
                    agent_request_key,
                    _now(),
                ),
            )
            connection.execute(
                "UPDATE cart SET version = version + 1, confirmed = 0, updated_at = ? WHERE cart_id = ?",
                (_now(), cart_id),
            )
        return self.get_cart(session_id)

    def update_cart_item(
        self, session_id: str, cart_item_id: str, item: CartItemUpdate
    ) -> CartPreview:
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT ci.* FROM cart_item ci JOIN cart c ON c.cart_id=ci.cart_id
                WHERE ci.cart_item_id=? AND c.session_id=?
                """,
                (cart_item_id, session_id),
            ).fetchone()
            if existing is None:
                raise KeyError("CART_ITEM_NOT_FOUND")
            current_options = json.loads(existing["option_snapshot_json"])
            replacement = CartItemInput(
                menu_id=existing["menu_id"],
                quantity=item.quantity if item.quantity is not None else int(existing["quantity"]),
                option_item_ids=(
                    item.option_item_ids
                    if item.option_item_ids is not None
                    else [str(option["option_item_id"]) for option in current_options]
                ),
                user_note=item.user_note if item.user_note is not None else existing["user_note"],
                note_translation_id=(
                    item.note_translation_id
                    if item.note_translation_id is not None
                    else existing["note_translation_id"]
                ),
            )
            menu, options, line_total = self._cart_item_values(connection, replacement)
            korean_note, note_translation_id = self._validated_note_translation(
                connection, session_id, replacement
            )
            connection.execute(
                """
                UPDATE cart_item SET quantity=?,unit_price=?,menu_snapshot_json=?,
                  option_snapshot_json=?,line_total=?,user_note=?,korean_note=?,
                  note_translation_id=?
                WHERE cart_item_id=?
                """,
                (
                    replacement.quantity,
                    int(menu["price"]),
                    json.dumps(
                        {
                            "name_en": _catalog_text(menu["name_en"], menu["name_ko"]),
                            "price": int(menu["price"]),
                        }
                    ),
                    json.dumps(options),
                    line_total,
                    replacement.user_note,
                    korean_note,
                    note_translation_id,
                    cart_item_id,
                ),
            )
            connection.execute(
                """
                UPDATE cart SET version=version+1,confirmed=0,updated_at=? WHERE cart_id=?
                """,
                (_now(), existing["cart_id"]),
            )
        return self.get_cart(session_id)

    def delete_cart_item(self, session_id: str, cart_item_id: str) -> CartPreview:
        with self._connection() as connection:
            existing = connection.execute(
                """
                SELECT ci.cart_id FROM cart_item ci JOIN cart c ON c.cart_id=ci.cart_id
                WHERE ci.cart_item_id=? AND c.session_id=?
                """,
                (cart_item_id, session_id),
            ).fetchone()
            if existing is None:
                raise KeyError("CART_ITEM_NOT_FOUND")
            connection.execute("DELETE FROM cart_item WHERE cart_item_id=?", (cart_item_id,))
            connection.execute(
                """
                UPDATE cart SET version=version+1,confirmed=0,updated_at=? WHERE cart_id=?
                """,
                (_now(), existing["cart_id"]),
            )
        return self.get_cart(session_id)

    @staticmethod
    def _translate_note(note: str) -> str:
        lowered = note.lower()
        translations = []
        if "mild" in lowered or "not spicy" in lowered:
            translations.append("최대한 맵지 않게 부탁드립니다.")
        if "front desk" in lowered:
            translations.append("호텔 프런트에 맡겨 주세요.")
        if "no cutlery" in lowered or "no disposable" in lowered:
            translations.append("일회용 수저와 포크는 필요 없습니다.")
        return " ".join(translations) or "요청사항을 확인해 주세요."

    def get_cart(self, session_id: str) -> CartPreview:
        with self._connection() as connection:
            cart = connection.execute(
                "SELECT * FROM cart WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not cart:
                cart_id = self._ensure_cart(connection, session_id)
                cart = connection.execute(
                    "SELECT * FROM cart WHERE cart_id = ?", (cart_id,)
                ).fetchone()
            rows = connection.execute(
                """
                SELECT ci.*,
                       COALESCE(m.name_en,m.name_ko,m.menu_id) AS menu_name,
                       COALESCE(m.name_ko,m.name_en,m.menu_id) AS menu_name_ko,
                       m.allergen_tags_json
                FROM cart_item ci
                JOIN menu m ON m.menu_id = ci.menu_id WHERE ci.cart_id = ? ORDER BY ci.created_at
                """,
                (cart["cart_id"],),
            ).fetchall()
            merchant_ids = {row["merchant_id"] for row in rows}
            delivery_fee = 0
            if merchant_ids:
                placeholders = ",".join("?" for _ in merchant_ids)
                fee_row = connection.execute(
                    f"SELECT MAX(delivery_fee) AS fee FROM merchant WHERE merchant_id IN ({placeholders})",
                    tuple(merchant_ids),
                ).fetchone()
                delivery_fee = int(fee_row["fee"] or 0)
            has_delivery = connection.execute(
                "SELECT 1 FROM delivery_preference WHERE cart_id = ?", (cart["cart_id"],)
            ).fetchone()
            profile_row = connection.execute(
                """
                SELECT p.dietary_rules_json, p.allergy_severity,
                       p.religion_selection, p.country_code,p.preferred_language,
                       s.meal_need_state_json,
                       family.synthetic_enrichment_release_id AS active_synthetic_enrichment_release_id
                FROM chat_session s JOIN user_profile p ON p.profile_id=s.profile_id
                JOIN recommendation_runtime_state state ON state.state_key='ACTIVE'
                JOIN recommendation_release_family family
                  ON family.release_family_id=state.active_release_family_id
                WHERE s.session_id=?
                """,
                (session_id,),
            ).fetchone()
            structured_criteria_row = connection.execute(
                """
                SELECT criteria.criteria_json,family.release_family_id,
                       family.knowledge_release_id,family.certification_release_id,
                       family.synthetic_enrichment_release_id
                FROM recommendation_snapshot snapshot
                JOIN session_recommendation_criteria criteria
                  ON criteria.session_id=snapshot.session_id
                 AND criteria.criteria_version=snapshot.criteria_version
                JOIN recommendation_release_family family
                  ON family.release_family_id=snapshot.recommendation_release_family_id
                WHERE snapshot.session_id=? AND snapshot.structured_request_id IS NOT NULL
                ORDER BY snapshot.created_at DESC,snapshot.snapshot_id DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            structured_criteria = (
                RecommendationCriteriaV2.model_validate_json(
                    str(structured_criteria_row["criteria_json"])
                )
                if structured_criteria_row is not None
                else None
            )
            minimum_order_amount = 0
            if len(merchant_ids) == 1:
                minimum_row = connection.execute(
                    "SELECT min_order_amount FROM merchant WHERE merchant_id=?",
                    (next(iter(merchant_ids)),),
                ).fetchone()
                minimum_order_amount = int(minimum_row["min_order_amount"]) if minimum_row else 0
            dietary_conflicts: list[str] = []
            blocking_dietary_conflicts: list[str] = []
            service_area_conflict = False
            address_area_row = (
                connection.execute(
                    """
                    SELECT ref.service_area_id FROM address_ref ref
                    JOIN service_area area ON area.service_area_id=ref.service_area_id
                    WHERE ref.address_ref_id=? AND ref.session_id=? AND ref.confirmed=1
                      AND area.active=1
                    """,
                    (cart["address_ref_id"], session_id),
                ).fetchone()
                if cart["address_ref_id"]
                else None
            )
            address_service_area = (
                str(address_area_row["service_area_id"] or "") if address_area_row else ""
            )
            if profile_row and rows and structured_criteria is None:
                dietary_rules = set(json.loads(profile_row["dietary_rules_json"]))
                need_state = apply_profile_constraints(
                    MealNeedState.model_validate_json(profile_row["meal_need_state_json"] or "{}"),
                    list(dietary_rules),
                    str(profile_row["religion_selection"]),
                )
                severe_shellfish = (
                    "shellfish_allergy" in dietary_rules
                    and profile_row["allergy_severity"] == "severe"
                )
                vegan_required = "vegan" in dietary_rules
                for row in rows:
                    if vegan_required:
                        vegan_verified = connection.execute(
                            """
                            SELECT 1 FROM menu_dietary_attribute mda
                            JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                            WHERE mda.menu_id=? AND da.code='vegan_option' AND mda.status='VERIFIED'
                            """,
                            (row["menu_id"],),
                        ).fetchone()
                        if not vegan_verified:
                            dietary_conflicts.append(
                                f"Remove {row['menu_name']} to continue; vegan status is not verified."
                            )
                    if severe_shellfish:
                        for option in json.loads(row["option_snapshot_json"]):
                            conflict = connection.execute(
                                """
                                SELECT 1 FROM option_dietary_conflict
                                WHERE option_item_id=? AND rule_code='shellfish_allergy'
                                """,
                                (option["option_item_id"],),
                            ).fetchone()
                            if conflict:
                                dietary_conflicts.append(f"Remove {option['name_en']} to continue.")
                    selected_ids = [
                        str(option["option_item_id"])
                        for option in json.loads(row["option_snapshot_json"])
                    ]
                    hard_conflicts, _ = self._menu_hard_constraint_conflicts(
                        connection,
                        str(row["menu_id"]),
                        need_state,
                        str(profile_row["allergy_severity"]),
                        selected_ids,
                    )
                    if hard_conflicts:
                        dietary_conflicts.append(
                            f"Remove {row['menu_name']} to continue; it conflicts with current "
                            "meal constraints or grounded safety facts."
                        )
            elif (
                structured_criteria is not None
                and structured_criteria_row is not None
                and structured_criteria.schema_version == "3"
            ):
                synthetic_release_id = str(
                    structured_criteria_row["synthetic_enrichment_release_id"] or ""
                )
                if not synthetic_release_id:
                    blocking_dietary_conflicts.append(
                        "The active menu profile is unavailable. Refresh the recommendation."
                    )
                else:
                    country_code = structured_criteria.spice_reference_country
                    baseline_row = connection.execute(
                        """
                        SELECT spice_baseline FROM synthetic_country_profile
                        WHERE release_id=? AND country_code=?
                        """,
                        (synthetic_release_id, country_code),
                    ).fetchone()
                    spice_baseline = int(baseline_row["spice_baseline"]) if baseline_row else 3
                    price_range = structured_criteria.price_range_krw
                    for row in rows:
                        menu_id = str(row["menu_id"])
                        profile = connection.execute(
                            """
                            SELECT spice_level,halal_fit,vegan_fit
                            FROM synthetic_menu_profile WHERE release_id=? AND menu_id=?
                            """,
                            (synthetic_release_id, menu_id),
                        ).fetchone()
                        current_menu = connection.execute(
                            "SELECT price FROM menu WHERE menu_id=?", (menu_id,)
                        ).fetchone()
                        conflict = profile is None or current_menu is None
                        if price_range and current_menu is not None:
                            price = int(current_menu["price"])
                            conflict = conflict or not (price_range.min <= price <= price_range.max)
                        if profile is not None:
                            spice = int(profile["spice_level"])
                            preference = structured_criteria.spice_preference or "SIMILAR"
                            spice_matches = (
                                spice < spice_baseline
                                if preference == "LESS"
                                else spice > spice_baseline
                                if preference == "MORE"
                                else spice == spice_baseline
                            )
                            conflict = conflict or not spice_matches
                            conflict = conflict or bool(
                                structured_criteria.dietary_filters.halal_certified_only
                                and not profile["halal_fit"]
                            )
                            conflict = conflict or bool(
                                structured_criteria.dietary_filters.vegan
                                and not profile["vegan_fit"]
                            )
                        selected_ids = [
                            str(option["option_item_id"])
                            for option in json.loads(row["option_snapshot_json"])
                        ]
                        if selected_ids:
                            placeholders = ",".join("?" for _ in selected_ids)
                            option_profiles = connection.execute(
                                f"""
                                SELECT halal_conflict,vegan_conflict
                                FROM synthetic_option_profile
                                WHERE release_id=? AND option_item_id IN ({placeholders})
                                """,
                                (synthetic_release_id, *selected_ids),
                            ).fetchall()
                            conflict = conflict or any(
                                structured_criteria.dietary_filters.halal_certified_only
                                and option["halal_conflict"]
                                or structured_criteria.dietary_filters.vegan
                                and option["vegan_conflict"]
                                for option in option_profiles
                            )
                        if conflict:
                            warning = (
                                f"Remove {row['menu_name']} to continue; it no longer matches "
                                "your saved price, spice, or dietary choices."
                            )
                            dietary_conflicts.append(warning)
                            blocking_dietary_conflicts.append(warning)
            elif structured_criteria is not None and structured_criteria_row is not None:
                menu_ids = [str(row["menu_id"]) for row in rows]
                valid_certifications = self._valid_halal_certifications_in_connection(
                    connection,
                    release_family_id=str(structured_criteria_row["release_family_id"]),
                    instant=_now(),
                )
                vegan = self._v2_vegan_classifications(
                    connection,
                    menu_ids,
                    knowledge_release_id=str(structured_criteria_row["knowledge_release_id"]),
                )
                for row in rows:
                    menu_id = str(row["menu_id"])
                    menu_name = str(row["menu_name"])
                    if (
                        structured_criteria.dietary_filters.halal_certified_only
                        and menu_id not in valid_certifications
                    ):
                        warning = f"Remove {menu_name} to continue; its halal certification is no longer valid."
                        dietary_conflicts.append(warning)
                        blocking_dietary_conflicts.append(warning)
                    current_menu = connection.execute(
                        "SELECT price,spice_level FROM menu WHERE menu_id=?",
                        (menu_id,),
                    ).fetchone()
                    if not self._price_matches_v2(
                        int(current_menu["price"]) if current_menu else -1,
                        structured_criteria.price_bands,
                    ):
                        warning = (
                            f"{menu_name}'s current price is outside your selected range; "
                            "review the updated total before checkout."
                        )
                        dietary_conflicts.append(warning)
                    if current_menu is None or (
                        current_menu["spice_level"] is not None
                        and int(current_menu["spice_level"]) > structured_criteria.max_spice_level
                    ):
                        warning = f"Remove {menu_name} to continue; its spice level no longer matches your selection."
                        dietary_conflicts.append(warning)
                        blocking_dietary_conflicts.append(warning)
                    if structured_criteria.dietary_filters.vegan:
                        vegan_status, vegan_warning, _ = vegan.get(menu_id, ("UNKNOWN", None, []))
                        if vegan_status != "LIKELY_FIT":
                            dietary_conflicts.append(
                                vegan_warning
                                or f"Check {menu_name}'s ingredients before ordering it as vegan."
                            )
                        selected_ids = [
                            str(option["option_item_id"])
                            for option in json.loads(row["option_snapshot_json"])
                        ]
                        if selected_ids:
                            placeholders = ",".join("?" for _ in selected_ids)
                            option_effects = connection.execute(
                                f"""
                                SELECT ingredient_id,effect,assertion_status
                                FROM option_ingredient_effect
                                WHERE release_id=?
                                  AND option_item_id IN ({placeholders})
                                """,
                                (
                                    str(structured_criteria_row["knowledge_release_id"]),
                                    *selected_ids,
                                ),
                            ).fetchall()
                            if any(
                                str(effect["effect"]).upper() == "ADD"
                                and str(effect["ingredient_id"]) in VEGAN_INGREDIENTS
                                and str(effect["assertion_status"]).upper()
                                not in {"CONFIRMED_ABSENT", "ABSENT"}
                                for effect in option_effects
                            ):
                                dietary_conflicts.append(
                                    f"A selected option for {menu_name} may add an animal-derived ingredient."
                                )
            for row in rows:
                merchant_area = connection.execute(
                    "SELECT service_area_id FROM merchant WHERE merchant_id=?",
                    (row["merchant_id"],),
                ).fetchone()
                if (
                    not address_service_area
                    or merchant_area is None
                    or merchant_area["service_area_id"] != address_service_area
                ):
                    service_area_conflict = True
            if structured_criteria is None:
                blocking_dietary_conflicts = list(dietary_conflicts)
            cart_menu_localizations: dict[str, str] = {}
            cart_option_localizations: dict[str, str] = {}
            synthetic_release_id = (
                str(structured_criteria_row["synthetic_enrichment_release_id"] or "")
                if structured_criteria_row is not None
                else str(profile_row["active_synthetic_enrichment_release_id"] or "")
                if profile_row is not None
                else ""
            )
            if synthetic_release_id and profile_row is not None:
                requested_locale = normalize_preference_locale(
                    str(profile_row["preferred_language"])
                )
                language_code = requested_locale if requested_locale in {"ko", "ja"} else "en"
                cart_menu_localizations = {
                    str(item["menu_id"]): str(item["display_name"])
                    for item in connection.execute(
                        """
                        SELECT menu_id,display_name FROM menu_localization
                        WHERE release_id=? AND language_code=? AND validation_status='VALID'
                        """,
                        (synthetic_release_id, language_code),
                    ).fetchall()
                }
                cart_option_localizations = {
                    str(item["option_item_id"]): str(item["display_name"])
                    for item in connection.execute(
                        """
                        SELECT option_item_id,display_name FROM option_item_localization
                        WHERE release_id=? AND language_code=?
                        """,
                        (synthetic_release_id, language_code),
                    ).fetchall()
                }
                # The selected-menu flow can improve legacy catalog labels at runtime.
                # Prefer its newest version in every downstream cart surface so the
                # option chooser, cart sheet, and final handoff never disagree.
                cart_option_localizations.update(
                    {
                        str(item["option_item_id"]): str(item["display_name"])
                        for item in connection.execute(
                            """
                            SELECT option_item_id,display_name FROM (
                              SELECT option_item_id,display_name,
                                     ROW_NUMBER() OVER (
                                       PARTITION BY option_item_id
                                       ORDER BY generated_at DESC,prompt_version DESC
                                     ) AS localization_rank
                              FROM runtime_option_item_localization
                              WHERE release_id=? AND language_code=?
                            ) WHERE localization_rank=1
                            """,
                            (synthetic_release_id, language_code),
                        ).fetchall()
                    }
                )
        items = [
            CartLine(
                cart_item_id=row["cart_item_id"],
                menu_id=row["menu_id"],
                merchant_id=row["merchant_id"],
                menu_name=row["menu_name"],
                menu_name_ko=row["menu_name_ko"],
                display_name=cart_menu_localizations.get(str(row["menu_id"])),
                quantity=row["quantity"],
                unit_price=row["unit_price"],
                options=[
                    {
                        **option,
                        "display_name": cart_option_localizations.get(
                            str(option["option_item_id"])
                        ),
                    }
                    for option in json.loads(row["option_snapshot_json"])
                ],
                line_total=row["line_total"],
            )
            for row in rows
        ]
        subtotal = sum(line.line_total for line in items)
        missing = []
        if not items:
            missing.append("menu")
        if not cart["address_ref_id"]:
            missing.append("address")
        if not has_delivery:
            missing.append("delivery_preferences")
        minimum_order_shortfall = max(0, minimum_order_amount - subtotal)
        if minimum_order_shortfall:
            missing.append("minimum_order_amount")
        if blocking_dietary_conflicts:
            missing.append("dietary_conflict")
        if service_area_conflict:
            missing.append("service_area")
        warnings = list(dict.fromkeys(dietary_conflicts))
        if service_area_conflict:
            warnings.append("The confirmed address is outside this merchant's service area.")
        if items and structured_criteria is None:
            warnings.append("Synthetic evidence only; cross-contamination may be unverified.")
        current_fingerprint = _cart_fingerprint(
            str(cart["cart_id"]), int(cart["version"]), subtotal + delivery_fee
        )
        return CartPreview(
            cart_id=cart["cart_id"],
            session_id=session_id,
            version=cart["version"],
            items=items,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            total_price=subtotal + delivery_fee,
            missing_slots=missing,
            dietary_warnings=warnings,
            minimum_order_amount=minimum_order_amount,
            minimum_order_shortfall=minimum_order_shortfall,
            ready_to_checkout=not missing,
            confirmed=(
                bool(cart["confirmed"]) and cart["confirmed_fingerprint"] == current_fingerprint
            ),
        )

    def update_delivery(self, session_id: str, preference: DeliveryPreferenceInput) -> CartPreview:
        with self._connection() as connection:
            cart_id = self._ensure_cart(connection, session_id)
            if preference.address_ref_id:
                address = connection.execute(
                    "SELECT 1 FROM address_ref WHERE address_ref_id = ? AND session_id = ? AND confirmed = 1",
                    (preference.address_ref_id, session_id),
                ).fetchone()
                if not address:
                    raise ValueError("ADDRESS_NOT_CONFIRMED")
                connection.execute(
                    "UPDATE cart SET address_ref_id = ? WHERE cart_id = ?",
                    (preference.address_ref_id, cart_id),
                )
            korean_note = self._translate_note(preference.user_note)
            connection.execute(
                """
                INSERT INTO delivery_preference (
                  cart_id, handoff_method, cutlery, ring_bell, front_desk,
                  user_note, korean_note, back_translation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cart_id) DO UPDATE SET
                  handoff_method=excluded.handoff_method, cutlery=excluded.cutlery,
                  ring_bell=excluded.ring_bell, front_desk=excluded.front_desk,
                  user_note=excluded.user_note, korean_note=excluded.korean_note,
                  back_translation=excluded.back_translation
                """,
                (
                    cart_id,
                    preference.handoff_method,
                    int(preference.cutlery),
                    int(preference.ring_bell),
                    int(preference.front_desk),
                    preference.user_note,
                    korean_note,
                    preference.user_note,
                ),
            )
            connection.execute(
                "UPDATE cart SET version = version + 1, confirmed = 0, updated_at = ? WHERE cart_id = ?",
                (_now(), cart_id),
            )
        return self.get_cart(session_id)

    @staticmethod
    def _revalidate_cart(
        connection: sqlite3.Connection,
        session_id: str,
        *,
        confirm: bool,
    ) -> tuple[str, bool, bool, int, int]:
        """Validate and reprice a cart against current catalog rows while locked."""
        cart = connection.execute(
            """
            SELECT c.*, p.dietary_rules_json, p.allergy_severity,
                   p.religion_selection, p.country_code, s.meal_need_state_json
            FROM cart c
            JOIN chat_session s ON s.session_id = c.session_id
            JOIN user_profile p ON p.profile_id = s.profile_id
            WHERE c.session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if not cart:
            raise ValueError("CART_INCOMPLETE")
        address = connection.execute(
            """
            SELECT ref.service_area_id FROM address_ref ref
            JOIN service_area area ON area.service_area_id=ref.service_area_id
            WHERE ref.address_ref_id = ? AND ref.session_id = ? AND ref.confirmed = 1
              AND area.active=1
            """,
            (cart["address_ref_id"], session_id),
        ).fetchone()
        delivery = connection.execute(
            "SELECT 1 FROM delivery_preference WHERE cart_id = ?", (cart["cart_id"],)
        ).fetchone()
        lines = connection.execute(
            "SELECT * FROM cart_item WHERE cart_id = ? ORDER BY created_at",
            (cart["cart_id"],),
        ).fetchall()
        if not address or not delivery or not lines:
            raise ValueError("CART_INCOMPLETE")

        dietary_rules = set(json.loads(cart["dietary_rules_json"]))
        structured_criteria_row = connection.execute(
            """
            SELECT criteria.criteria_json,family.release_family_id,
                   family.knowledge_release_id,family.certification_release_id,
                   family.synthetic_enrichment_release_id
            FROM recommendation_snapshot snapshot
            JOIN session_recommendation_criteria criteria
              ON criteria.session_id=snapshot.session_id
             AND criteria.criteria_version=snapshot.criteria_version
            JOIN recommendation_release_family family
              ON family.release_family_id=snapshot.recommendation_release_family_id
            WHERE snapshot.session_id=? AND snapshot.structured_request_id IS NOT NULL
            ORDER BY snapshot.created_at DESC,snapshot.snapshot_id DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        structured_criteria = (
            RecommendationCriteriaV2.model_validate_json(
                str(structured_criteria_row["criteria_json"])
            )
            if structured_criteria_row is not None
            else None
        )
        need_state = MealNeedState.model_validate_json(cart["meal_need_state_json"] or "{}")
        if structured_criteria is None:
            need_state = apply_profile_constraints(
                need_state,
                list(dietary_rules),
                str(cart["religion_selection"]),
            )
        address_service_area = str(address["service_area_id"] or "")
        if need_state.service_area_id and need_state.service_area_id != address_service_area:
            raise ValueError("CART_SERVICE_AREA_MISMATCH")
        severe_shellfish = structured_criteria is None and (
            "shellfish_allergy" in dietary_rules and cart["allergy_severity"] == "severe"
        )
        vegan_required = structured_criteria is None and "vegan" in dietary_rules
        valid_structured_halal = (
            SQLiteYobiRepository._valid_halal_certifications_in_connection(
                connection,
                release_family_id=str(structured_criteria_row["release_family_id"]),
                instant=_now(),
            )
            if structured_criteria is not None
            and structured_criteria.schema_version == "2"
            and structured_criteria_row is not None
            else {}
        )
        synthetic_release_id = (
            str(structured_criteria_row["synthetic_enrichment_release_id"] or "")
            if structured_criteria is not None
            and structured_criteria.schema_version == "3"
            and structured_criteria_row is not None
            else ""
        )
        country_spice_baseline = 3
        if structured_criteria is not None and structured_criteria.schema_version == "3":
            if not synthetic_release_id:
                raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
            baseline = connection.execute(
                """
                SELECT spice_baseline FROM synthetic_country_profile
                WHERE release_id=? AND country_code=?
                """,
                (
                    synthetic_release_id,
                    structured_criteria.spice_reference_country,
                ),
            ).fetchone()
            if baseline is None:
                raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
            country_spice_baseline = int(baseline["spice_baseline"])
        merchant_ids: set[str] = set()
        subtotal = 0
        changed = False
        for line in lines:
            menu = connection.execute(
                """
                SELECT m.*, r.delivery_fee, r.min_order_amount,
                       r.service_area_id AS merchant_service_area_id
                FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                WHERE m.menu_id = ? AND m.availability = 'AVAILABLE'
                """,
                (line["menu_id"],),
            ).fetchone()
            if not menu:
                raise ValueError("CART_MENU_UNAVAILABLE")
            if menu["merchant_id"] != line["merchant_id"]:
                raise ValueError("CART_MERCHANT_MISMATCH")
            if not address_service_area or menu["merchant_service_area_id"] != address_service_area:
                raise ValueError("CART_SERVICE_AREA_MISMATCH")
            merchant_ids.add(menu["merchant_id"])
            if structured_criteria is not None and structured_criteria.schema_version == "3":
                synthetic_profile = connection.execute(
                    """
                    SELECT spice_level,halal_fit,vegan_fit
                    FROM synthetic_menu_profile
                    WHERE release_id=? AND menu_id=?
                    """,
                    (synthetic_release_id, menu["menu_id"]),
                ).fetchone()
                if synthetic_profile is None:
                    raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
                price_range = structured_criteria.price_range_krw
                if (
                    price_range is None
                    or not price_range.min <= int(menu["price"]) <= price_range.max
                ):
                    raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
                spice_level = int(synthetic_profile["spice_level"])
                spice_matches = (
                    spice_level < country_spice_baseline
                    if structured_criteria.spice_preference == "LESS"
                    else spice_level > country_spice_baseline
                    if structured_criteria.spice_preference == "MORE"
                    else spice_level == country_spice_baseline
                )
                if not spice_matches:
                    raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
                if (
                    structured_criteria.dietary_filters.halal_certified_only
                    and not synthetic_profile["halal_fit"]
                ) or (
                    structured_criteria.dietary_filters.vegan and not synthetic_profile["vegan_fit"]
                ):
                    raise ValueError("CART_DIETARY_CONFLICT")
            elif structured_criteria is not None:
                if (
                    menu["spice_level"] is not None
                    and int(menu["spice_level"]) > structured_criteria.max_spice_level
                ):
                    raise ValueError("CART_MENU_NO_LONGER_ELIGIBLE")
                if (
                    structured_criteria.dietary_filters.halal_certified_only
                    and str(menu["menu_id"]) not in valid_structured_halal
                ):
                    raise ValueError("CART_DIETARY_CONFLICT")
            if vegan_required:
                vegan_verified = connection.execute(
                    """
                    SELECT 1 FROM menu_dietary_attribute mda
                    JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                    WHERE mda.menu_id=? AND da.code='vegan_option' AND mda.status='VERIFIED'
                    """,
                    (menu["menu_id"],),
                ).fetchone()
                if not vegan_verified:
                    raise ValueError("CART_DIETARY_CONFLICT")

            selected_ids = [
                str(option["option_item_id"]) for option in json.loads(line["option_snapshot_json"])
            ]
            selected_counts: dict[str, int] = {}
            current_options: list[dict[str, Any]] = []
            option_total = 0
            for option_id in selected_ids:
                option = connection.execute(
                    """
                    SELECT i.*, g.menu_id FROM menu_option_item i
                    JOIN menu_option_group g ON g.option_group_id = i.option_group_id
                    WHERE i.option_item_id = ? AND i.availability = 'AVAILABLE'
                    """,
                    (option_id,),
                ).fetchone()
                if not option or option["menu_id"] != menu["menu_id"]:
                    raise ValueError("CART_OPTION_UNAVAILABLE")
                if severe_shellfish:
                    conflict = connection.execute(
                        """
                        SELECT 1 FROM option_dietary_conflict
                        WHERE option_item_id=? AND rule_code='shellfish_allergy'
                        """,
                        (option_id,),
                    ).fetchone()
                    if conflict:
                        raise ValueError("CART_DIETARY_CONFLICT")
                if structured_criteria is not None and structured_criteria.schema_version == "3":
                    synthetic_option = connection.execute(
                        """
                        SELECT halal_conflict,vegan_conflict
                        FROM synthetic_option_profile
                        WHERE release_id=? AND option_item_id=?
                        """,
                        (synthetic_release_id, option_id),
                    ).fetchone()
                    if synthetic_option is not None and (
                        structured_criteria.dietary_filters.halal_certified_only
                        and synthetic_option["halal_conflict"]
                        or structured_criteria.dietary_filters.vegan
                        and synthetic_option["vegan_conflict"]
                    ):
                        raise ValueError("CART_DIETARY_CONFLICT")
                group_id = str(option["option_group_id"])
                selected_counts[group_id] = selected_counts.get(group_id, 0) + 1
                current_options.append(
                    {
                        "option_item_id": option["option_item_id"],
                        "name_en": _catalog_text(option["name_en"], option["name_ko"]),
                        "name_ko": option["name_ko"],
                        "price_delta": int(option["price_delta"]),
                    }
                )
                option_total += int(option["price_delta"])
            groups = connection.execute(
                """
                SELECT option_group_id, min_select, max_select
                FROM menu_option_group WHERE menu_id = ?
                """,
                (menu["menu_id"],),
            ).fetchall()
            if any(
                selected_counts.get(str(group["option_group_id"]), 0) < int(group["min_select"])
                or selected_counts.get(str(group["option_group_id"]), 0) > int(group["max_select"])
                for group in groups
            ):
                raise ValueError("CART_OPTION_SELECTION_INVALID")

            if structured_criteria is None:
                hard_conflicts, _ = SQLiteYobiRepository._menu_hard_constraint_conflicts(
                    connection,
                    str(menu["menu_id"]),
                    need_state,
                    str(cart["allergy_severity"]),
                    selected_ids,
                )
                if hard_conflicts:
                    raise ValueError("CART_DIETARY_CONFLICT")

            unit_price = int(menu["price"])
            line_total = (unit_price + option_total) * int(line["quantity"])
            menu_snapshot = json.dumps(
                {
                    "name_en": _catalog_text(menu["name_en"], menu["name_ko"]),
                    "price": unit_price,
                }
            )
            option_snapshot = json.dumps(current_options)
            line_changed = (
                int(line["unit_price"]) != unit_price
                or int(line["line_total"]) != line_total
                or json.loads(line["menu_snapshot_json"]) != json.loads(menu_snapshot)
                or json.loads(line["option_snapshot_json"]) != current_options
            )
            if line_changed:
                changed = True
                connection.execute(
                    """
                    UPDATE cart_item SET unit_price = ?, menu_snapshot_json = ?,
                      option_snapshot_json = ?, line_total = ? WHERE cart_item_id = ?
                    """,
                    (unit_price, menu_snapshot, option_snapshot, line_total, line["cart_item_id"]),
                )
            subtotal += line_total

        if len(merchant_ids) != 1:
            raise ValueError("CART_MULTIPLE_MERCHANTS")
        merchant = connection.execute(
            "SELECT min_order_amount, delivery_fee FROM merchant WHERE merchant_id = ?",
            (next(iter(merchant_ids)),),
        ).fetchone()
        if merchant is None or subtotal < int(merchant["min_order_amount"]):
            raise ValueError("MINIMUM_ORDER_NOT_MET")

        current_total = subtotal + int(merchant["delivery_fee"])
        was_confirmed = bool(cart["confirmed"])
        current_fingerprint = _cart_fingerprint(
            str(cart["cart_id"]), int(cart["version"]), current_total
        )
        confirmation_stale = was_confirmed and cart["confirmed_fingerprint"] != current_fingerprint
        changed = changed or confirmation_stale
        version_changed = False
        if confirm and (not was_confirmed or changed):
            confirmed_version = int(cart["version"]) + 1
            connection.execute(
                """
                UPDATE cart SET confirmed = 1, version = version + 1,
                  confirmed_fingerprint = ?, updated_at = ?
                WHERE cart_id = ?
                """,
                (
                    _cart_fingerprint(str(cart["cart_id"]), confirmed_version, current_total),
                    _now(),
                    cart["cart_id"],
                ),
            )
            version_changed = True
        elif changed:
            connection.execute(
                """
                UPDATE cart SET confirmed = 0, version = version + 1,
                  confirmed_fingerprint = NULL, updated_at = ?
                WHERE cart_id = ?
                """,
                (_now(), cart["cart_id"]),
            )
            version_changed = True
        return (
            str(cart["cart_id"]),
            changed,
            was_confirmed,
            current_total,
            int(cart["version"]) + int(version_changed),
        )

    def confirm_cart(self, session_id: str) -> CartPreview:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._revalidate_cart(connection, session_id, confirm=True)
        return self.get_cart(session_id)

    def create_checkout(self, session_id: str, data: CheckoutCreate) -> Checkout:
        changed = False
        checkout: Checkout | None = None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cart_id, changed, was_confirmed, current_total, cart_version = self._revalidate_cart(
                connection, session_id, confirm=False
            )
            if not was_confirmed:
                raise ValueError("CART_NOT_CONFIRMED")
            if changed:
                # Commit the refreshed snapshot and confirmation reset before asking
                # the user to review the new total.
                pass
            else:
                fingerprint = _cart_fingerprint(cart_id, cart_version, current_total)
                existing = connection.execute(
                    "SELECT * FROM mock_checkout WHERE idempotency_key = ?",
                    (data.idempotency_key,),
                ).fetchone()
                if existing:
                    if existing["cart_id"] != cart_id or existing["cart_version"] != cart_version:
                        raise ValueError("IDEMPOTENCY_KEY_REUSED")
                    if existing["cart_fingerprint"] != fingerprint:
                        connection.execute(
                            """
                            UPDATE cart SET confirmed=0,version=version+1,updated_at=?
                            WHERE cart_id=? AND confirmed=1
                            """,
                            (_now(), cart_id),
                        )
                        changed = True
                    else:
                        checkout = self._checkout_from_row(existing)
                else:
                    active = connection.execute(
                        """
                        SELECT * FROM mock_checkout
                        WHERE cart_id=? AND cart_version=?
                        ORDER BY created_at,checkout_id LIMIT 1
                        """,
                        (cart_id, cart_version),
                    ).fetchone()
                    if active:
                        if active["cart_fingerprint"] != fingerprint:
                            connection.execute(
                                """
                                UPDATE cart SET confirmed=0,version=version+1,updated_at=?
                                WHERE cart_id=? AND confirmed=1
                                """,
                                (_now(), cart_id),
                            )
                            changed = True
                        else:
                            checkout = self._checkout_from_row(active)
                    else:
                        checkout_id = _id("checkout")
                        payment_url = f"/pay/{checkout_id}"
                        now = _now()
                        connection.execute(
                            """
                            INSERT INTO mock_checkout (
                              checkout_id, cart_id, idempotency_key, payment_method, status,
                              amount, payment_url, cart_version, cart_fingerprint,
                              created_at, updated_at
                            ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                checkout_id,
                                cart_id,
                                data.idempotency_key,
                                data.payment_method,
                                current_total,
                                payment_url,
                                cart_version,
                                fingerprint,
                                now,
                                now,
                            ),
                        )
                        row = connection.execute(
                            "SELECT * FROM mock_checkout WHERE checkout_id = ?", (checkout_id,)
                        ).fetchone()
                        checkout = self._checkout_from_row(row)
        if changed:
            raise ValueError("CART_CHANGED_RECONFIRM_REQUIRED")
        if checkout is None:
            raise RuntimeError("CHECKOUT_CREATION_FAILED")
        return checkout

    def get_checkout(self, checkout_id: str) -> Checkout | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
            if not row:
                return None
            order = connection.execute(
                "SELECT order_id FROM mock_order WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
        return self._checkout_from_row(row, order["order_id"] if order else None)

    @staticmethod
    def _checkout_from_row(row: sqlite3.Row, order_id: str | None = None) -> Checkout:
        return Checkout(
            checkout_id=row["checkout_id"],
            cart_id=row["cart_id"],
            status=row["status"],
            amount=row["amount"],
            payment_method=row["payment_method"],
            payment_url=row["payment_url"],
            order_id=order_id,
        )

    def update_checkout(self, checkout_id: str, status: str) -> Checkout:
        if status not in {"SUCCEEDED", "FAILED", "CANCELED"}:
            raise ValueError("INVALID_PAYMENT_STATUS")
        checkout_stale = False
        order_id = None
        updated: sqlite3.Row | None = None
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
            if not row:
                raise KeyError("CHECKOUT_NOT_FOUND")
            if row["status"] == "SUCCEEDED" and status != "SUCCEEDED":
                raise ValueError("PAYMENT_ALREADY_SUCCEEDED")
            if status == "SUCCEEDED":
                existing_order = connection.execute(
                    "SELECT order_id FROM mock_order WHERE checkout_id = ?", (checkout_id,)
                ).fetchone()
                if row["status"] == "SUCCEEDED" and existing_order:
                    order_id = existing_order["order_id"]
                else:
                    cart_session = connection.execute(
                        "SELECT session_id FROM cart WHERE cart_id = ?",
                        (row["cart_id"],),
                    ).fetchone()
                    if cart_session is None:
                        raise ValueError("CHECKOUT_STALE")
                    try:
                        (
                            current_cart_id,
                            cart_changed,
                            cart_confirmed,
                            current_total,
                            current_version,
                        ) = self._revalidate_cart(
                            connection, str(cart_session["session_id"]), confirm=False
                        )
                    except ValueError as exc:
                        raise ValueError("CHECKOUT_STALE") from exc
                    current_fingerprint = _cart_fingerprint(
                        current_cart_id, current_version, current_total
                    )
                    fingerprint_changed = current_fingerprint != row["cart_fingerprint"]
                    if (
                        current_cart_id != row["cart_id"]
                        or not cart_confirmed
                        or cart_changed
                        or current_version != row["cart_version"]
                        or fingerprint_changed
                    ):
                        if (
                            fingerprint_changed
                            and not cart_changed
                            and cart_confirmed
                            and current_version == row["cart_version"]
                        ):
                            connection.execute(
                                """
                                UPDATE cart SET confirmed=0,version=version+1,updated_at=?
                                WHERE cart_id=? AND confirmed=1
                                """,
                                (_now(), current_cart_id),
                            )
                        checkout_stale = True
                    else:
                        completed_other = connection.execute(
                            """
                            SELECT other.checkout_id FROM mock_checkout other
                            JOIN mock_order placed ON placed.checkout_id=other.checkout_id
                            WHERE other.cart_id=? AND other.checkout_id<>? LIMIT 1
                            """,
                            (row["cart_id"], checkout_id),
                        ).fetchone()
                        if completed_other:
                            raise ValueError("CART_ORDER_ALREADY_COMPLETED")
                        connection.execute(
                            "UPDATE mock_checkout SET status = ?, updated_at = ? WHERE checkout_id = ?",
                            (status, _now(), checkout_id),
                        )
                        if existing_order:
                            order_id = existing_order["order_id"]
                        else:
                            order_id = _id("YOBI-DEMO")
                            cart_rows = connection.execute(
                                "SELECT * FROM cart_item WHERE cart_id = ? ORDER BY created_at",
                                (row["cart_id"],),
                            ).fetchall()
                            snapshot = [dict(item) for item in cart_rows]
                            eta = datetime.now(timezone.utc) + timedelta(minutes=35)
                            connection.execute(
                                """
                                INSERT INTO mock_order (
                                  order_id, checkout_id, cart_snapshot_json, order_status,
                                  estimated_delivery_at, created_at
                                ) VALUES (?, ?, ?, 'CONFIRMED', ?, ?)
                                """,
                                (
                                    order_id,
                                    checkout_id,
                                    json.dumps(snapshot),
                                    eta.isoformat(),
                                    _now(),
                                ),
                            )
            else:
                connection.execute(
                    "UPDATE mock_checkout SET status = ?, updated_at = ? WHERE checkout_id = ?",
                    (status, _now(), checkout_id),
                )
            updated = connection.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
        if checkout_stale:
            raise ValueError("CHECKOUT_STALE")
        if updated is None:
            raise RuntimeError("CHECKOUT_UPDATE_FAILED")
        return self._checkout_from_row(updated, order_id)

    def get_order(self, order_id: str) -> Order | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM mock_order WHERE order_id = ?", (order_id,)
            ).fetchone()
        if not row:
            return None
        return Order(
            order_id=row["order_id"],
            checkout_id=row["checkout_id"],
            order_status=row["order_status"],
            estimated_delivery_at=row["estimated_delivery_at"],
            summary={"items": json.loads(row["cart_snapshot_json"]), "payment": "Demo only"},
        )

    def reset_session(self, session_id: str) -> None:
        with self._connection() as connection:
            self._reset_session_in_connection(connection, session_id, delete_session=False)

    @staticmethod
    def _reset_session_in_connection(
        connection: sqlite3.Connection, session_id: str, delete_session: bool
    ) -> None:
        cart = connection.execute(
            "SELECT cart_id FROM cart WHERE session_id = ?", (session_id,)
        ).fetchone()
        if cart:
            checkouts = connection.execute(
                "SELECT checkout_id FROM mock_checkout WHERE cart_id = ?", (cart["cart_id"],)
            ).fetchall()
            for checkout in checkouts:
                connection.execute(
                    "DELETE FROM mock_order WHERE checkout_id = ?", (checkout["checkout_id"],)
                )

            connection.execute("DELETE FROM mock_checkout WHERE cart_id = ?", (cart["cart_id"],))
            connection.execute("DELETE FROM cart WHERE cart_id = ?", (cart["cart_id"],))
        connection.execute("DELETE FROM address_ref WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM conversation_event WHERE session_id = ?", (session_id,))
        connection.execute(
            "DELETE FROM recommendation_snapshot WHERE session_id = ?", (session_id,)
        )
        connection.execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
        if delete_session:
            connection.execute("DELETE FROM chat_session WHERE session_id = ?", (session_id,))
        else:
            connection.execute(
                """
                UPDATE chat_session SET state = ?, selected_menu_id = NULL,
                  selected_merchant_id = NULL, meal_need_state_json='{}',
                  dialogue_act=?, state_version=state_version+1,
                  state_stack_json='[]', updated_at = ? WHERE session_id = ?
                """,
                (
                    ChatState.DISCOVERY.value,
                    DialogueAct.COLLECT_NEEDS.value,
                    _now(),
                    session_id,
                ),
            )

    def prewarm_explanation(self, menu_id: str) -> bool:
        menu = self.get_menu(
            menu_id,
            Profile(
                profile_id="prewarm",
                consent_demo_data=True,
                created_at=datetime.now(timezone.utc),
            ),
        )
        if menu is None:
            return False
        payload = json.dumps(
            {
                "menu_id": menu.menu_id,
                "cultural_description": menu.cultural_description,
                "description": menu.description,
                "dietary_summary": menu.dietary_summary,
            },
            ensure_ascii=False,
        )
        with self._connection() as connection:
            active_release = connection.execute(
                """
                SELECT active_release_id FROM knowledge_runtime_state
                WHERE state_key='ACTIVE'
                """
            ).fetchone()
            knowledge_version = str(active_release[0]) if active_release else "legacy"
            source_version = f"{CATALOG_VERSION}:{knowledge_version}"
            cache_digest = hashlib.sha256(source_version.encode("utf-8")).hexdigest()[:16]
            cache_key = f"prewarm:{menu_id}:en:{cache_digest}"
            connection.execute(
                """
                DELETE FROM explanation_cache
                WHERE menu_id=? AND language='en' AND profile_signature='prewarm'
                  AND source_version<>?
                """,
                (menu_id, source_version),
            )
            connection.execute(
                """
                INSERT INTO explanation_cache (
                  cache_key, menu_id, language, profile_signature,
                  explanation_json, source_version, created_at
                ) VALUES (?, ?, 'en', 'prewarm', ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  explanation_json=excluded.explanation_json,
                  source_version=excluded.source_version,
                  created_at=excluded.created_at
                """,
                (cache_key, menu_id, payload, source_version, _now()),
            )
        return True

    def status(self) -> dict[str, object]:
        runtime_embedding = DeterministicEmbeddingProvider()
        with self._connection() as connection:
            count_rows = connection.execute(
                " UNION ALL ".join(
                    f"SELECT '{table}' table_name,COUNT(*) row_count FROM {table}"
                    for table in EXPECTED_RUNTIME_COUNTS
                )
            ).fetchall()
            counts = {str(row["table_name"]): int(row["row_count"]) for row in count_rows}
            external = connection.execute(
                """
                SELECT * FROM catalog_import_batch
                WHERE status='ACTIVE' AND data_origin='YOGIYO_PUBLIC_WEB'
                ORDER BY completed_at DESC LIMIT 1
                """
            ).fetchone()
            if external is not None:
                expected_external = {
                    str(key): int(value)
                    for key, value in json.loads(str(external["expected_counts_json"])).items()
                }
                if set(expected_external) != set(EXTERNAL_CATALOG_COUNT_TABLES):
                    expected_external = {}
                actual_external = {
                    table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in EXTERNAL_CATALOG_COUNT_TABLES
                }
                declared_external = {
                    str(key): int(value)
                    for key, value in json.loads(str(external["actual_counts_json"])).items()
                }
                invalid_required_options = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM menu_option_group groups
                        WHERE groups.min_select<0 OR groups.max_select<groups.min_select
                          OR (groups.required=1 AND groups.min_select<1)
                          OR (SELECT COUNT(*) FROM menu_option_item item
                              WHERE item.option_group_id=groups.option_group_id
                                AND item.availability='AVAILABLE') < groups.min_select
                        """
                    ).fetchone()[0]
                )
                missing_semantics = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM menu WHERE TRIM(COALESCE(semantic_text,''))=''"
                    ).fetchone()[0]
                )
                unknown_fields_preserved = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM menu
                        WHERE name_en IS NULL AND serves_min IS NULL AND serves_max IS NULL
                          AND spice_level IS NULL AND name_en_status='NOT_PROVIDED'
                          AND serves_status='NOT_PROVIDED' AND spice_status='NOT_PROVIDED'
                        """
                    ).fetchone()[0]
                )
                source_release = connection.execute(
                    """
                    SELECT release.* FROM knowledge_runtime_state state
                    JOIN knowledge_release release ON release.release_id=state.active_release_id
                    WHERE state.state_key='ACTIVE'
                    """
                ).fetchone()
                active_family_row = connection.execute(
                    """
                        SELECT family.* FROM recommendation_runtime_state state
                        JOIN recommendation_release_family family
                          ON family.release_family_id=state.active_release_family_id
                        WHERE state.state_key='ACTIVE' AND family.status='ACTIVE'
                          AND family.catalog_release_id=?
                        """,
                    (str(external["catalog_release_id"]),),
                ).fetchone()
                release_id = str(source_release["release_id"]) if source_release else ""
                classification_row = connection.execute(
                    """
                    SELECT
                      SUM(CASE WHEN mapping_status='MAPPED' AND confidence_band='high'
                        THEN 1 ELSE 0 END) mapped_high,
                      SUM(CASE WHEN mapping_status='UNMAPPED' THEN 1 ELSE 0 END) unmapped,
                      SUM(CASE WHEN mapping_status='UNMAPPED'
                        AND TRIM(COALESCE(unmapped_reason,''))='' THEN 1 ELSE 0 END) blank_reasons,
                      COUNT(*) classified
                    FROM menu_concept_map WHERE release_id=?
                    """,
                    (release_id,),
                ).fetchone()
                mapped_count = int(classification_row["mapped_high"] or 0)
                unmapped_count = int(classification_row["unmapped"] or 0)
                blank_unmapped_reasons = int(classification_row["blank_reasons"] or 0)
                classified_count = int(classification_row["classified"] or 0)
                reviewed_knowledge = connection.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM knowledge_document
                       WHERE release_id=? AND source_type='SYNTHETIC_WIKI'
                         AND review_status='REVIEWED_DEMO' AND is_synthetic=1) documents,
                      (SELECT COUNT(*) FROM knowledge_chunk
                       WHERE release_id=? AND is_synthetic=1) chunks,
                      (SELECT COUNT(*) FROM concept_preference_support
                       WHERE knowledge_release_id=? AND support_status='SUPPORTED'
                         AND evidence_chunk_id IS NOT NULL
                         AND provenance_type='SYNTHETIC_WIKI'
                         AND review_status='REVIEWED_DEMO') supports,
                      (SELECT COUNT(*) FROM menu_concept_map
                       WHERE release_id=? AND mapping_status='MAPPED'
                         AND (confidence_band<>'high'
                           OR source_type<>'YOBI_DERIVED_DEMO_MAPPING')) invalid_mappings
                    """,
                    (release_id, release_id, release_id, release_id),
                ).fetchone()
                feature_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM menu_preference_feature WHERE knowledge_release_id=?",
                        (release_id,),
                    ).fetchone()[0]
                )
                feature_evidence_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM menu_preference_feature_evidence "
                        "WHERE knowledge_release_id=?",
                        (release_id,),
                    ).fetchone()[0]
                )
                membership_counts = connection.execute(
                    "SELECT COUNT(*),COUNT(DISTINCT menu_id) "
                    "FROM menu_concept_membership WHERE knowledge_release_id=?",
                    (release_id,),
                ).fetchone()
                membership_count = int(membership_counts[0])
                membership_menu_count = int(membership_counts[1])
                wiki_eligible_menu_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM menu_wiki_eligibility WHERE knowledge_release_id=?",
                        (release_id,),
                    ).fetchone()[0]
                )
                option_localization_counts = {
                    "eligible_option_groups": 0,
                    "eligible_option_items": 0,
                    "localized_option_groups": 0,
                    "localized_option_items": 0,
                }
                enrichment_release_id = (
                    str(active_family_row["synthetic_enrichment_release_id"] or "")
                    if active_family_row
                    else ""
                )
                if enrichment_release_id:
                    eligible_options = connection.execute(
                        """
                        SELECT COUNT(DISTINCT groups.option_group_id),
                               COUNT(DISTINCT item.option_item_id)
                        FROM menu_wiki_eligibility eligibility
                        JOIN menu_option_group groups ON groups.menu_id=eligibility.menu_id
                        LEFT JOIN menu_option_item item
                          ON item.option_group_id=groups.option_group_id
                        WHERE eligibility.knowledge_release_id=?
                        """,
                        (release_id,),
                    ).fetchone()
                    localized_options = connection.execute(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM option_group_localization
                           WHERE release_id=? AND language_code IN ('ko','en','ja')),
                          (SELECT COUNT(*) FROM option_item_localization
                           WHERE release_id=? AND language_code IN ('ko','en','ja'))
                        """,
                        (enrichment_release_id, enrichment_release_id),
                    ).fetchone()
                    option_localization_counts = {
                        "eligible_option_groups": int(eligible_options[0] or 0),
                        "eligible_option_items": int(eligible_options[1] or 0),
                        "localized_option_groups": int(localized_options[0] or 0),
                        "localized_option_items": int(localized_options[1] or 0),
                    }
                synthetic_core = int(
                    connection.execute(
                        """
                        SELECT (SELECT COUNT(*) FROM merchant WHERE is_synthetic<>0)
                             + (SELECT COUNT(*) FROM menu WHERE is_synthetic<>0)
                        """
                    ).fetchone()[0]
                )
                source_fact_rows = sum(
                    int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in (
                        "menu_ingredient",
                        "menu_allergen",
                        "menu_dietary_attribute",
                        "merchant_certification",
                    )
                )
                address_status = demo_address_status(connection.cursor())
                source_integrity_checks = {
                    "external_counts_exact": bool(
                        expected_external
                        and expected_external == declared_external == actual_external
                    ),
                    "external_provenance_exact": int(
                        connection.execute(
                            """
                            SELECT COUNT(*) FROM menu
                            WHERE data_origin='YOGIYO_PUBLIC_WEB' AND is_synthetic=0
                            """
                        ).fetchone()[0]
                    )
                    == actual_external["menu"]
                    and synthetic_core == 0,
                    "unknown_fields_preserved_as_null": unknown_fields_preserved
                    == actual_external["menu"],
                    "menu_semantics_complete": missing_semantics == 0,
                    "required_options_valid": invalid_required_options == 0,
                    "source_release_catalog_compatible": bool(
                        source_release
                        and source_release["status"] == "READY"
                        and source_release["catalog_version"] == external["catalog_release_id"]
                    ),
                    "single_demo_address_ready": address_status["ready"] is True,
                    "package_hashes_present": all(
                        len(str(external[column])) == 64
                        for column in (
                            "source_zip_sha256",
                            "source_xlsx_sha256",
                            "source_summary_sha256",
                            "package_sha256",
                            "selection_manifest_sha256",
                        )
                    ),
                }
                recommendation_checks = {
                    "recommendation_family_active": active_family_row is not None,
                    "classification_coverage_complete": classified_count == actual_external["menu"],
                    "high_confidence_mapping_present": mapped_count > 0,
                    "unmapped_reasons_complete": blank_unmapped_reasons == 0,
                    "reviewed_wiki_documents_present": bool(
                        reviewed_knowledge and int(reviewed_knowledge["documents"] or 0) > 0
                    ),
                    "reviewed_wiki_chunks_present": bool(
                        reviewed_knowledge and int(reviewed_knowledge["chunks"] or 0) > 0
                    ),
                    "reviewed_preference_support_present": bool(
                        reviewed_knowledge and int(reviewed_knowledge["supports"] or 0) > 0
                    ),
                    "mapping_provenance_exact": bool(
                        reviewed_knowledge and int(reviewed_knowledge["invalid_mappings"] or 0) == 0
                    ),
                    "source_specific_facts_not_invented": source_fact_rows == 0,
                    "support_manifest_valid": bool(
                        active_family_row
                        and len(str(active_family_row["support_manifest_sha256"] or "")) == 64
                        and str(active_family_row["support_manifest_sha256"]) != "0" * 64
                    ),
                    "menu_preference_features_present": feature_count > 0,
                    "menu_preference_evidence_present": feature_evidence_count > 0,
                    "menu_concept_memberships_present": membership_count > 0,
                    "wiki_eligibility_exactly_covers_membership_menus": (
                        wiki_eligible_menu_count == membership_menu_count
                        and membership_menu_count > 0
                    ),
                    "feature_manifest_valid": bool(
                        active_family_row
                        and len(str(active_family_row["feature_manifest_sha256"] or "")) == 64
                        and str(active_family_row["feature_manifest_sha256"]) != "0" * 64
                    ),
                    "ranking_policy_active": bool(
                        active_family_row
                        and str(active_family_row["ranking_policy_version"])
                        == RANKING_POLICY_VERSION
                        and len(str(active_family_row["ranking_policy_sha256"] or "")) == 64
                        and str(active_family_row["ranking_policy_sha256"]) != "0" * 64
                    ),
                    "semantic_embedding_identity_compatible": bool(
                        source_release
                        and active_family_row
                        and str(source_release["embedding_model"]) == self.embedding_provider.model
                        and int(source_release["embedding_dimension"])
                        == self.embedding_provider.dimension
                        and str(source_release["embedding_version"])
                        == self.embedding_provider.version
                        and str(active_family_row["embedding_model"])
                        == self.embedding_provider.model
                        and str(active_family_row["embedding_version"])
                        == self.embedding_provider.version
                        and missing_semantics == 0
                    ),
                }
                external_checks = {**source_integrity_checks, **recommendation_checks}
                source_release_counts = (
                    json.loads(str(source_release["actual_counts_json"])) if source_release else {}
                )
                return {
                    "backend": "sqlite",
                    "catalog_mode": "EXTERNAL_SOURCE",
                    "data_origin": str(external["data_origin"]),
                    "catalog_import_id": str(external["catalog_import_id"]),
                    "catalog_version": str(external["catalog_release_id"]),
                    "knowledge_catalog_version": (
                        str(source_release["catalog_version"]) if source_release else None
                    ),
                    "counts": counts,
                    "external_counts": actual_external,
                    "demo_address": address_status,
                    "source_integrity_ready": all(source_integrity_checks.values()),
                    "recommendation_ready": all(recommendation_checks.values()),
                    "canonical_ready": all(source_integrity_checks.values()),
                    "last_seed_time": connection.execute(
                        "SELECT MAX(updated_at) FROM menu"
                    ).fetchone()[0],
                    "knowledge_ready": all(recommendation_checks.values()),
                    "vector_ready": recommendation_checks["semantic_embedding_identity_compatible"],
                    "semantic_channel_status": (
                        "READY"
                        if recommendation_checks["semantic_embedding_identity_compatible"]
                        else "DISABLED_MODEL_MISMATCH"
                    ),
                    "menu_vector_strategy": "deterministic_on_read",
                    "readiness_checks": external_checks,
                    "knowledge_expected_counts": source_release_counts,
                    "knowledge_actual_counts": source_release_counts,
                    "knowledge_supplemental_counts": {
                        "mapped_menus": mapped_count,
                        "unmapped_menus": unmapped_count,
                        "source_fact_rows": source_fact_rows,
                        "menu_preference_features": feature_count,
                        "menu_preference_feature_evidence": feature_evidence_count,
                        "menu_concept_memberships": membership_count,
                        "menu_concept_membership_menus": membership_menu_count,
                        "wiki_eligible_menus": wiki_eligible_menu_count,
                        **option_localization_counts,
                    },
                    "feature_count": feature_count,
                    "wiki_eligible_menu_count": wiki_eligible_menu_count,
                    "feature_manifest_sha256": (
                        str(active_family_row["feature_manifest_sha256"])
                        if active_family_row
                        else None
                    ),
                    "ranking_policy_version": (
                        str(active_family_row["ranking_policy_version"])
                        if active_family_row
                        else None
                    ),
                    "knowledge_release_id": (
                        str(source_release["release_id"]) if source_release else None
                    ),
                    "knowledge_embedding_model": (
                        str(source_release["embedding_model"]) if source_release else None
                    ),
                    "knowledge_embedding_dimension": (
                        int(source_release["embedding_dimension"]) if source_release else None
                    ),
                    "knowledge_embedding_version": (
                        str(source_release["embedding_version"]) if source_release else None
                    ),
                    "source_limitations": [
                        "NO_REVIEWED_INGREDIENT_DATA",
                        "NO_FORMAL_CERTIFICATION_DATA",
                        "SPICE_AND_SERVES_NOT_PROVIDED",
                    ],
                }
            canonical = connection.execute(
                "SELECT COUNT(*) FROM menu WHERE menu_id IN ('menu_001_01','menu_002_01','menu_003_01')"
            ).fetchone()[0]
            last_seed_time = connection.execute("SELECT MAX(updated_at) FROM menu").fetchone()[0]
            knowledge = connection.execute(
                """
                SELECT release.release_id,release.catalog_version,release.manifest_sha256,
                       release.status,release.expected_counts_json,release.actual_counts_json,
                       release.embedding_model,
                       release.embedding_dimension,release.embedding_version,
                       (SELECT COUNT(*) FROM menu_concept_map mapping
                        WHERE mapping.release_id=release.release_id
                          AND mapping.mapping_status='MAPPED') mapped_menus,
                       (SELECT COUNT(*) FROM knowledge_chunk chunk
                        WHERE chunk.release_id=release.release_id
                          AND chunk.embedding_vector_json IS NULL) null_vectors
                FROM knowledge_runtime_state state
                JOIN knowledge_release release ON release.release_id=state.active_release_id
                WHERE state.state_key='ACTIVE'
                """
            ).fetchone()
            observed_counts: dict[str, int] = {}
            supplemental_counts = {
                "mapped_menus": 0,
                "origin_declarations": 0,
                "merchant_ingredients": 0,
                "option_effects": 0,
                "chunk_metadata_mismatches": 0,
            }
            expected_counts: dict[str, int] = {}
            declared_actual_counts: dict[str, int] = {}
            if knowledge:
                release_id = str(knowledge["release_id"])
                expected_counts = {
                    str(key): int(value)
                    for key, value in json.loads(str(knowledge["expected_counts_json"])).items()
                }
                declared_actual_counts = {
                    str(key): int(value)
                    for key, value in json.loads(str(knowledge["actual_counts_json"])).items()
                }
                for key, table in (
                    ("concepts", "dish_concept"),
                    ("relations", "dish_relation"),
                    ("closure", "dish_concept_closure"),
                    ("claims", "concept_claim"),
                    ("documents", "knowledge_document"),
                    ("chunks", "knowledge_chunk"),
                ):
                    observed_counts[key] = int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE release_id=?", (release_id,)
                        ).fetchone()[0]
                    )
                supplemental_counts.update(
                    {
                        "mapped_menus": int(knowledge["mapped_menus"]),
                        "origin_declarations": int(
                            connection.execute(
                                "SELECT COUNT(*) FROM merchant_origin_declaration WHERE release_id=?",
                                (release_id,),
                            ).fetchone()[0]
                        ),
                        "merchant_ingredients": int(
                            connection.execute(
                                "SELECT COUNT(*) FROM merchant_ingredient WHERE release_id=?",
                                (release_id,),
                            ).fetchone()[0]
                        ),
                        "option_effects": int(
                            connection.execute(
                                "SELECT COUNT(*) FROM option_ingredient_effect WHERE release_id=?",
                                (release_id,),
                            ).fetchone()[0]
                        ),
                        "chunk_metadata_mismatches": int(
                            connection.execute(
                                """
                                SELECT COUNT(*) FROM knowledge_chunk
                                WHERE release_id=? AND (
                                  embedding_model<>? OR embedding_dimension<>?
                                  OR embedding_version<>?
                                )
                                """,
                                (
                                    release_id,
                                    knowledge["embedding_model"],
                                    int(knowledge["embedding_dimension"]),
                                    knowledge["embedding_version"],
                                ),
                            ).fetchone()[0]
                        ),
                    }
                )
            missing_menu_semantics = int(
                connection.execute(
                    "SELECT COUNT(*) FROM menu WHERE TRIM(COALESCE(semantic_text,''))=''"
                ).fetchone()[0]
            )
            invalid_required_options = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM menu_option_group groups
                    WHERE groups.min_select<0 OR groups.max_select<groups.min_select
                      OR (groups.required=1 AND groups.min_select<1)
                      OR (SELECT COUNT(*) FROM menu_option_item item
                          WHERE item.option_group_id=groups.option_group_id
                            AND item.availability='AVAILABLE') < groups.min_select
                    """
                ).fetchone()[0]
            )
            release_embedding_matches_runtime = bool(
                knowledge
                and knowledge["embedding_model"] == runtime_embedding.model
                and int(knowledge["embedding_dimension"]) == runtime_embedding.dimension
                and knowledge["embedding_version"] == runtime_embedding.version
            )
            readiness_checks = {
                "base_catalog_counts_compatible": _runtime_counts_compatible(counts),
                "canonical_rows_present": int(canonical) == 3,
                "active_release_matches_runtime_corpus": bool(
                    knowledge
                    and knowledge["release_id"] == KNOWLEDGE_RELEASE_ID
                    and knowledge["catalog_version"] == KNOWLEDGE_CATALOG_VERSION
                ),
                "release_manifest_present": bool(
                    knowledge
                    and len(str(knowledge["manifest_sha256"])) == 64
                    and str(knowledge["manifest_sha256"]).strip("0") != ""
                ),
                "release_status_ready": bool(knowledge and knowledge["status"] == "READY"),
                "release_counts_exact": bool(
                    knowledge
                    and expected_counts
                    and expected_counts == declared_actual_counts == observed_counts
                ),
                "menu_mappings_exact": supplemental_counts["mapped_menus"] == EXPECTED_MAPPED_MENUS,
                "origin_declarations_exact": supplemental_counts["origin_declarations"]
                == EXPECTED_ORIGIN_DECLARATIONS,
                "merchant_ingredients_exact": supplemental_counts["merchant_ingredients"]
                == EXPECTED_MERCHANT_INGREDIENTS,
                "option_effects_exact": supplemental_counts["option_effects"]
                == EXPECTED_OPTION_EFFECTS,
                "knowledge_chunk_vectors_complete": bool(
                    knowledge
                    and int(knowledge["null_vectors"]) == 0
                    and supplemental_counts["chunk_metadata_mismatches"] == 0
                ),
                "embedding_runtime_compatible": release_embedding_matches_runtime,
                "menu_semantics_complete": missing_menu_semantics == 0,
                "required_options_valid": invalid_required_options == 0,
            }
            knowledge_ready = all(readiness_checks.values())
        return {
            "backend": "sqlite",
            "catalog_version": CATALOG_VERSION,
            "knowledge_catalog_version": knowledge["catalog_version"] if knowledge else None,
            "counts": counts,
            "canonical_ready": int(canonical) == 3 and _runtime_counts_compatible(counts),
            "last_seed_time": last_seed_time,
            "knowledge_ready": knowledge_ready,
            "vector_ready": release_embedding_matches_runtime and missing_menu_semantics == 0,
            "menu_vector_strategy": "deterministic_on_read",
            "readiness_checks": readiness_checks,
            "knowledge_expected_counts": expected_counts,
            "knowledge_actual_counts": observed_counts,
            "knowledge_supplemental_counts": supplemental_counts,
            "knowledge_release_id": knowledge["release_id"] if knowledge else None,
            "knowledge_embedding_model": knowledge["embedding_model"] if knowledge else None,
            "knowledge_embedding_dimension": (
                int(knowledge["embedding_dimension"]) if knowledge else None
            ),
            "knowledge_embedding_version": knowledge["embedding_version"] if knowledge else None,
        }

    def record_audit(
        self,
        session_id: str | None,
        tool: str,
        input_payload: str,
        evidence_ids: list[str],
        output_status: str,
        latency_ms: int,
        fallback_used: bool,
        safe_error_code: str | None = None,
    ) -> None:
        safe_session = self.safe_input_hash(session_id) if session_id else None
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO audit_log (
                  log_id, session_id, tool, input_hash, evidence_ids_json,
                  output_status, latency_ms, fallback_used, safe_error_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _id("audit"),
                    safe_session,
                    tool[:120],
                    self.safe_input_hash(input_payload),
                    json.dumps(evidence_ids[:50]),
                    output_status[:40],
                    max(0, latency_ms),
                    int(fallback_used),
                    safe_error_code[:120] if safe_error_code else None,
                    _now(),
                ),
            )

    @staticmethod
    def safe_input_hash(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
