from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.schema_sqlite import SCHEMA_SQL
from app.db.seed_data import CATALOG_VERSION, build_seed
from app.domain.address import normalize_address_text
from app.domain.dialogue import (
    ConstraintStrictness,
    ConversationEventInput,
    ConversationEventResult,
    ConversationEventType,
    DialogueAct,
    MealNeedState,
    RecommendationSnapshot,
)
from app.domain.dietary import apply_profile_constraints, known_allergen_conflicts
from app.domain.knowledge import (
    GroundedMenuKnowledge,
    GroundedPassage,
    KnowledgeSourceKind,
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
    MenuSummary,
    MerchantComparison,
    OptionGroup,
    OptionItem,
    Order,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    Session,
)
from app.domain.recommendation import rerank_menu_candidates
from app.knowledge.catalog_seed import (
    KNOWLEDGE_CATALOG_VERSION,
    KNOWLEDGE_RELEASE_ID,
    build_knowledge_catalog_seed,
)
from app.knowledge.resolver import (
    allergen_constraint_conflicts,
    category_constraint_conflicts,
    ingredient_constraint_conflicts,
    merchant_cross_contact_conflicts,
    resolve_allergen_claims,
    resolve_ingredient_claims,
    resolve_merchant_ingredient_claims,
    severe_allergy_conflicts,
)
from app.knowledge.sqlite_store import load_sqlite_release
from app.rag.embeddings import cosine_similarity, deterministic_embedding
from app.rag.providers import DeterministicEmbeddingProvider

RECOMMENDATION_CANDIDATE_CAP = 40
RECOMMENDATION_PASSAGE_LIMIT = 3
EXPECTED_MAPPED_MENUS = 150
EXPECTED_ORIGIN_DECLARATIONS = 30
EXPECTED_MERCHANT_INGREDIENTS = 266
EXPECTED_OPTION_EFFECTS = 4
EXPECTED_RUNTIME_COUNTS = {
    "service_area": 3,
    "menu_category": 20,
    "merchant": 30,
    "menu": 150,
    "menu_knowledge": 150,
    "menu_option_group": 302,
    "menu_option_item": 605,
    "review_snippet": 600,
    "evidence": 300,
    "address_place": 20,
    "ingredient": 47,
    "menu_ingredient": 7,
    "allergen": 10,
    "menu_allergen": 162,
    "dietary_attribute": 15,
    "menu_dietary_attribute": 317,
    "option_dietary_conflict": 1,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _cart_fingerprint(cart_id: str, cart_version: int, total: int) -> str:
    return hashlib.sha256(f"{cart_id}:{cart_version}:{total}".encode()).hexdigest()


class SQLiteYobiRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

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
            merchant_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(merchant)").fetchall()
            }
            if "service_area_id" not in merchant_columns:
                connection.execute("ALTER TABLE merchant ADD COLUMN service_area_id TEXT")
            menu_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(menu)").fetchall()
            }
            if "category_id" not in menu_columns:
                connection.execute("ALTER TABLE menu ADD COLUMN category_id TEXT")
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
            existing = connection.execute("SELECT COUNT(*) FROM merchant").fetchone()[0]
            seed = build_seed()
            if existing:
                self._backfill_normalized_catalog(connection, seed)
                self._load_knowledge_catalog(connection, seed)
                connection.execute(
                    """
                    UPDATE user_profile SET spice_tolerance = CASE
                      WHEN spice_tolerance <= 1 THEN 1
                      WHEN spice_tolerance <= 3 THEN 2
                      ELSE 3 END
                    """
                )
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
        connection.executemany(
            "DELETE FROM menu_ingredient WHERE menu_id=?",
            [(row["menu_id"],) for row in seed["menus"]],
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
            raise ValueError("Demo data processing consent is required to start a session")
        profile_id = _id("profile")
        created_at = _now()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO user_profile (
                  profile_id, preferred_language, nationality, age_band, gender,
                  religion_selection, dietary_rules_json, allergy_severity,
                  spice_tolerance, favorite_foods_json, consent_demo_data,
                  remember_profile, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    data.preferred_language,
                    data.nationality,
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
            raise ValueError("Demo data processing consent is required to keep a profile")
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE user_profile SET preferred_language=?, nationality=?, age_band=?, gender=?,
                  religion_selection=?, dietary_rules_json=?, allergy_severity=?,
                  spice_tolerance=?, favorite_foods_json=?, consent_demo_data=?,
                  remember_profile=? WHERE profile_id=?
                """,
                (
                    merged.preferred_language,
                    merged.nationality,
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
                FROM chat_message WHERE session_id = ? ORDER BY created_at, message_id
                """,
                (session_id,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            message = dict(row)
            message["safe_metadata"] = json.loads(message.pop("safe_metadata_json") or "{}")
            messages.append(message)
        return messages

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
            user_metadata = {
                "client_request_id": request_id,
                "intent": intent,
            } if request_id else {}
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
            need_state = apply_profile_constraints(
                need_state,
                list(json.loads(profile_row["dietary_rules_json"])),
                str(profile_row["religion_selection"]),
            )
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
            if event.snapshot_id:
                snapshot_row = connection.execute(
                    "SELECT * FROM recommendation_snapshot WHERE session_id=? AND snapshot_id=?",
                    (session_id, event.snapshot_id),
                ).fetchone()
                if snapshot_row is None:
                    raise ValueError("RECOMMENDATION_SNAPSHOT_NOT_FOUND")
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
                if not int(group["min_select"]) <= len(selected_option_ids) <= int(
                    group["max_select"]
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
        lowered = query.lower()
        severe_shellfish = (
            "shellfish_allergy" in profile.dietary_rules and profile.allergy_severity == "severe"
        )
        vegan_required = "vegan" in profile.dietary_rules
        severe_allergies = profile.allergy_severity == "severe"
        excluded = {item.lower() for item in excluded_ingredients}
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max
                FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                WHERE m.availability = 'AVAILABLE' AND m.price <= ? AND m.spice_level <= ?
                """,
                (budget, max(spice, 1)),
            ).fetchall()
            prelim: list[
                tuple[
                    float,
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
                if severe_shellfish and "shellfish_sauce_absent" not in dietary_tags:
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
                boost = 0.0
                if "red rice cake" in lowered and "tteokbokki" in row["category"].lower():
                    boost += 0.45
                if any(term in lowered for term in ("rain", "broth", "noodle", "soup")) and row[
                    "category"
                ] in {"Chicken kalguksu", "Samgyetang", "Sundubu"}:
                    boost += 0.18
                if any(term in lowered for term in ("mild", "not spicy")) and row[
                    "spice_level"
                ] <= 1:
                    boost += 0.16
                if any(term in lowered for term in ("vegan", "plant")) and (
                    "vegan_option" in dietary_tags
                ):
                    boost += 0.4
                reasons = [f"Matches your spice tolerance (level {row['spice_level']} of 3)"]
                if "creamy pasta" in profile.favorite_foods and "rose" in row["category"].lower():
                    boost += 0.2
                    reasons.append("Creamy profile connects with a favourite food you selected")
                risks: list[str] = []
                status = EvidenceStatus.UNKNOWN
                if "shellfish_sauce_absent" in dietary_tags:
                    status = EvidenceStatus.VERIFIED
                    reasons.append("Demo sauce specification has shellfish marked absent")
                    risks.append("Cross-contamination is not verified")
                elif allergen_tags:
                    risks.append("Some dietary details are not verified")
                prelim.append(
                    (
                        menu_similarity,
                        boost,
                        row,
                        reasons,
                        risks,
                        status,
                        dietary_tags,
                        allergen_tags,
                    )
                )

            prelim.sort(
                key=lambda item: (item[0] + item[1], -int(item[2]["price"])), reverse=True
            )
            candidate_limit = min(
                RECOMMENDATION_CANDIDATE_CAP,
                max(16, min(limit, RECOMMENDATION_CANDIDATE_CAP) * 4),
            )
            prelim = prelim[:candidate_limit]
            candidate_ids = [str(item[2]["menu_id"]) for item in prelim]
            grounded = self._bulk_resolved_knowledge_claims(connection, candidate_ids)
            knowledge = self._bulk_knowledge_passages(connection, candidate_ids, query_vector)
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
            menu_similarity,
            boost,
            row,
            reasons,
            risks,
            status,
            dietary_tags,
            allergen_tags,
        ) in prelim:
            menu_id = str(row["menu_id"])
            ingredient_claims, allergen_claims, merchant_claims = grounded.get(
                menu_id, ([], [], [])
            )
            conflicts = ingredient_constraint_conflicts(ingredient_claims, safety_state)
            mastered_shellfish = (
                "shellfish_sauce_absent" in dietary_tags and "shellfish_risk" not in allergen_tags
            )
            ignored_allergies = (
                {"shellfish"}
                if mastered_shellfish
                and "shellfish_allergy"
                in {*safety_state.dietary_rules, *safety_state.profile_dietary_rules}
                else set()
            )
            conflicts.extend(
                allergen_constraint_conflicts(
                    allergen_claims,
                    safety_state,
                    ignored_allergies=ignored_allergies,
                )
            )
            if profile.allergy_severity == "severe":
                conflicts.extend(
                    severe_allergy_conflicts(
                        ingredient_claims,
                        allergen_claims,
                        safety_state.dietary_rules,
                        shellfish_mastered_absence=mastered_shellfish,
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
            knowledge_score, passage_ids = knowledge.get(menu_id, (0.0, []))
            combined_score = 0.75 * menu_similarity + 0.25 * knowledge_score + boost
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
        return scored[:limit]

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
            merchant_name=row["merchant_name"],
            name_en=row["name_en"],
            name_ko=row["name_ko"],
            category=row["category"],
            description=row["description"],
            cultural_description=row["cultural_description"],
            price=row["price"],
            delivery_fee=row["delivery_fee"],
            eta_min=row["eta_min"],
            eta_max=row["eta_max"],
            spice_level=row["spice_level"],
            serves_min=row["serves_min"],
            serves_max=row["serves_max"],
            dietary_summary="Synthetic evidence; see evidence details before ordering.",
            evidence_status=status,
            match_reasons=reasons,
            risk_hints=risks,
            semantic_score=round(max(0.0, min(1.0, score)), 4),
        )

    def get_menu(self, menu_id: str, profile: Profile) -> MenuSummary | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max
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
        menu = self._menu_summary(
            row,
            ["Selected menu from the synthetic catalog"],
            ["Cross-contamination is not verified"],
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
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max,
                       r.service_area_id AS merchant_service_area_id
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE m.merchant_id=? AND m.availability='AVAILABLE' AND m.spice_level<=?
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
            if (
                "shellfish_allergy" in rules
                and profile.allergy_severity == "severe"
                and "shellfish_sauce_absent" not in tags
            ):
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
                    SELECT claim.*, ingredient.name_en, closure.depth,
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
                SELECT fact.*, ingredient.name_en, fact.source_id AS source_version
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
                    SELECT effect.*, ingredient.name_en, effect.option_item_id AS source_id,
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
    ) -> dict[str, tuple[list[Any], list[Any], list[Any]]]:
        """Resolve active Wiki/menu/merchant claims in a fixed number of queries."""

        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
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
        placeholders = ",".join("?" for _ in unique_ids)
        params = (release_id, *unique_ids)

        wiki_ingredients = connection.execute(
            f"""
            SELECT mapping.menu_id,claim.*,ingredient.name_en,closure.depth,
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
            SELECT fact.menu_id,fact.*,ingredient.name_en,fact.source_id AS source_version
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
            SELECT menu.menu_id,fact.*,ingredient.name_en,declaration.source_version
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
    ) -> dict[str, tuple[float, list[str]]]:
        """Return the strongest active knowledge-chunk signal for each candidate menu."""

        unique_ids = list(dict.fromkeys(menu_ids))
        if not unique_ids:
            return {}
        placeholders = ",".join("?" for _ in unique_ids)
        rows = connection.execute(
            f"""
            SELECT mapping.menu_id,chunk.chunk_id,chunk.embedding_vector_json
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
            grouped[str(row["menu_id"])].append(
                (
                    cosine_similarity(
                        query_vector,
                        json.loads(str(row["embedding_vector_json"])),
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
        if state.max_spiciness is not None and int(menu["spice_level"]) > state.max_spiciness:
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
            SELECT fact.*,ingredient.name_en,declaration.source_version
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
        mastered_shellfish = connection.execute(
            """
            SELECT CASE WHEN EXISTS (
              SELECT 1 FROM menu_dietary_attribute mda
              JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
              WHERE mda.menu_id=? AND da.code='shellfish_sauce_absent'
                AND mda.status='VERIFIED'
            ) AND NOT EXISTS (
              SELECT 1 FROM menu_allergen ma
              JOIN allergen a ON a.allergen_id=ma.allergen_id
              WHERE ma.menu_id=? AND a.code='shellfish_risk'
            ) THEN 1 ELSE 0 END
            """,
            (menu_id, menu_id),
        ).fetchone()[0]
        ignored_allergies = (
            {"shellfish"}
            if mastered_shellfish
            and "shellfish_allergy" in {*state.dietary_rules, *state.profile_dietary_rules}
            else set()
        )
        conflicts.extend(
            allergen_constraint_conflicts(
                allergen_claims,
                state,
                ignored_allergies=ignored_allergies,
            )
        )
        if allergy_severity == "severe":
            conflicts.extend(
                severe_allergy_conflicts(
                    ingredient_claims,
                    allergen_claims,
                    state.dietary_rules,
                    shellfish_mastered_absence=bool(mastered_shellfish),
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
                    SELECT chunk_id,document_id,concept_id,facet,content,
                           embedding_vector_json
                    FROM knowledge_chunk
                    WHERE release_id=? AND concept_id IN ({placeholders})
                    """,
                    (release_id, *concept_ids),
                ).fetchall()
                available_facets = sorted({str(row["facet"]) for row in rows})
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
                        cosine_similarity(
                            query_vector,
                            json.loads(str(row["embedding_vector_json"])),
                        ),
                        row,
                    )
                    for row in rows
                    if row["embedding_vector_json"]
                ]
                scored.sort(key=lambda item: (item[0], str(item[1]["chunk_id"])), reverse=True)
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
                SELECT fact.*,ingredient.name_en,declaration.source_version
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
        return GroundedMenuKnowledge(
            menu_id=menu_id,
            release_id=release_id,
            concept_id=concept_id,
            concept_lineage=concept_ids,
            available_facets=available_facets,
            ingredient_claims=ingredient_claims,
            allergen_claims=allergen_claims,
            merchant_ingredient_claims=merchant_claims,
            passages=passages,
            merchant_origin_notes=[str(row[0]) for row in origin_rows],
            unknowns=[
                "Merchant-specific recipe differences are unknown unless a menu fact overrides the Wiki.",
                "Shared-kitchen cross-contact is not confirmed by the synthetic Wiki or origin declaration.",
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
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min,
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
                        "One-person portion" if menu.serves_max == 1 else "Shareable portion"
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

    def get_options(self, menu_id: str) -> list[OptionGroup]:
        with self._connection() as connection:
            groups = connection.execute(
                "SELECT * FROM menu_option_group WHERE menu_id = ? ORDER BY sort_order",
                (menu_id,),
            ).fetchall()
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
                result.append(
                    OptionGroup(
                        option_group_id=group["option_group_id"],
                        name_en=group["name_en"],
                        name_ko=group["name_ko"],
                        description=group["description"],
                        required=bool(group["required"]),
                        min_select=group["min_select"],
                        max_select=group["max_select"],
                        items=[
                            OptionItem(
                                option_item_id=item["option_item_id"],
                                name_en=item["name_en"],
                                name_ko=item["name_ko"],
                                description=item["description"],
                                price_delta=item["price_delta"],
                                available=item["availability"] == "AVAILABLE",
                                dietary_conflict=item["dietary_conflict"],
                                conflicting_rules=(
                                    str(item["conflicting_rules_csv"]).split(",")
                                    if item["conflicting_rules_csv"]
                                    else []
                                ),
                            )
                            for item in items
                        ],
                    )
                )
        return result

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
                    "name_en": option["name_en"],
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
                  korean_note, agent_request_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cart_item_id,
                    cart_id,
                    menu["menu_id"],
                    menu["merchant_id"],
                    item.quantity,
                    menu["price"],
                    json.dumps({"name_en": menu["name_en"], "price": menu["price"]}),
                    json.dumps(options),
                    line_total,
                    item.user_note,
                    self._translate_note(item.user_note),
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
            )
            menu, options, line_total = self._cart_item_values(connection, replacement)
            connection.execute(
                """
                UPDATE cart_item SET quantity=?,unit_price=?,menu_snapshot_json=?,
                  option_snapshot_json=?,line_total=?,user_note=?,korean_note=?
                WHERE cart_item_id=?
                """,
                (
                    replacement.quantity,
                    int(menu["price"]),
                    json.dumps({"name_en": menu["name_en"], "price": int(menu["price"])}),
                    json.dumps(options),
                    line_total,
                    replacement.user_note,
                    self._translate_note(replacement.user_note),
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
                SELECT ci.*, m.name_en AS menu_name, m.name_ko AS menu_name_ko, m.allergen_tags_json FROM cart_item ci
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
                       p.religion_selection, s.meal_need_state_json
                FROM chat_session s JOIN user_profile p ON p.profile_id=s.profile_id
                WHERE s.session_id=?
                """,
                (session_id,),
            ).fetchone()
            minimum_order_amount = 0
            if len(merchant_ids) == 1:
                minimum_row = connection.execute(
                    "SELECT min_order_amount FROM merchant WHERE merchant_id=?",
                    (next(iter(merchant_ids)),),
                ).fetchone()
                minimum_order_amount = int(minimum_row["min_order_amount"]) if minimum_row else 0
            dietary_conflicts: list[str] = []
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
            if profile_row and rows:
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
                    conflicts = (
                        known_allergen_conflicts(
                            set(json.loads(row["allergen_tags_json"])), dietary_rules
                        )
                        if profile_row["allergy_severity"] == "severe"
                        else set()
                    )
                    for conflict in sorted(conflicts - {"shellfish"}):
                        dietary_conflicts.append(
                            f"Remove {row['menu_name']} to continue; it is flagged for {conflict.replace('_', ' ')}."
                        )
                    if severe_shellfish:
                        normalized_safe = connection.execute(
                            """
                            SELECT CASE WHEN EXISTS (
                              SELECT 1 FROM menu_dietary_attribute mda
                              JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                              WHERE mda.menu_id=? AND da.code='shellfish_sauce_absent'
                                AND mda.status='VERIFIED'
                            ) AND NOT EXISTS (
                              SELECT 1 FROM menu_allergen ma
                              JOIN allergen a ON a.allergen_id=ma.allergen_id
                              WHERE ma.menu_id=? AND a.code='shellfish_risk'
                            ) THEN 1 ELSE 0 END
                            """,
                            (row["menu_id"], row["menu_id"]),
                        ).fetchone()[0]
                        if not normalized_safe:
                            dietary_conflicts.append(
                                f"Remove {row['menu_name']} to continue; its shellfish safety is not verified."
                            )
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
        items = [
            CartLine(
                cart_item_id=row["cart_item_id"],
                menu_id=row["menu_id"],
                merchant_id=row["merchant_id"],
                menu_name=row["menu_name"],
                menu_name_ko=row["menu_name_ko"],
                quantity=row["quantity"],
                unit_price=row["unit_price"],
                options=json.loads(row["option_snapshot_json"]),
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
        if dietary_conflicts:
            missing.append("dietary_conflict")
        if service_area_conflict:
            missing.append("service_area")
        warnings = list(dict.fromkeys(dietary_conflicts))
        if service_area_conflict:
            warnings.append("The confirmed address is outside this merchant's service area.")
        if items:
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
                bool(cart["confirmed"])
                and cart["confirmed_fingerprint"] == current_fingerprint
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
                   p.religion_selection, s.meal_need_state_json
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
        need_state = apply_profile_constraints(
            MealNeedState.model_validate_json(cart["meal_need_state_json"] or "{}"),
            list(dietary_rules),
            str(cart["religion_selection"]),
        )
        address_service_area = str(address["service_area_id"] or "")
        if need_state.service_area_id and need_state.service_area_id != address_service_area:
            raise ValueError("CART_SERVICE_AREA_MISMATCH")
        severe_shellfish = (
            "shellfish_allergy" in dietary_rules and cart["allergy_severity"] == "severe"
        )
        vegan_required = "vegan" in dietary_rules
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
            if cart["allergy_severity"] == "severe" and (
                known_allergen_conflicts(set(json.loads(menu["allergen_tags_json"])), dietary_rules)
                - {"shellfish"}
            ):
                raise ValueError("CART_DIETARY_CONFLICT")
            if severe_shellfish:
                normalized_safe = connection.execute(
                    """
                    SELECT CASE WHEN
                      EXISTS (
                        SELECT 1 FROM menu_dietary_attribute mda
                        JOIN dietary_attribute da ON da.attribute_id=mda.attribute_id
                        WHERE mda.menu_id=? AND da.code='shellfish_sauce_absent'
                          AND mda.status='VERIFIED'
                      ) AND NOT EXISTS (
                        SELECT 1 FROM menu_allergen ma
                        JOIN allergen a ON a.allergen_id=ma.allergen_id
                        WHERE ma.menu_id=? AND a.code='shellfish_risk'
                      ) THEN 1 ELSE 0 END
                    """,
                    (menu["menu_id"], menu["menu_id"]),
                ).fetchone()[0]
                if not normalized_safe:
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
                group_id = str(option["option_group_id"])
                selected_counts[group_id] = selected_counts.get(group_id, 0) + 1
                current_options.append(
                    {
                        "option_item_id": option["option_item_id"],
                        "name_en": option["name_en"],
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
            menu_snapshot = json.dumps({"name_en": menu["name_en"], "price": unit_price})
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
        confirmation_stale = (
            was_confirmed and cart["confirmed_fingerprint"] != current_fingerprint
        )
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
                    _cart_fingerprint(
                        str(cart["cart_id"]), confirmed_version, current_total
                    ),
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
                    if (
                        existing["cart_id"] != cart_id
                        or existing["cart_version"] != cart_version
                    ):
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
                "base_catalog_counts_exact": counts == EXPECTED_RUNTIME_COUNTS,
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
                "menu_mappings_exact": supplemental_counts["mapped_menus"]
                == EXPECTED_MAPPED_MENUS,
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
            "canonical_ready": int(canonical) == 3 and counts == EXPECTED_RUNTIME_COUNTS,
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
