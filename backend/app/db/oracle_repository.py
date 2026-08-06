from __future__ import annotations

import hashlib
import json
from array import array
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import oracledb

from app.core.config import Settings
from app.db.oracle_pool import OraclePool
from app.db.seed_data import CATALOG_VERSION
from app.domain.models import (
    AddressCandidate,
    CartItemInput,
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
    Session,
)
from app.rag.providers import choose_embedding_provider


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _value(value: Any) -> Any:
    return value.read() if hasattr(value, "read") else value


def _json(value: Any) -> Any:
    raw = _value(value)
    return json.loads(raw) if isinstance(raw, str) else raw


def _row(cursor: oracledb.Cursor) -> dict[str, Any] | None:
    values = cursor.fetchone()
    if values is None:
        return None
    if cursor.description is None:
        raise RuntimeError("ORACLE_QUERY_HAS_NO_RESULT_DESCRIPTION")
    columns = [column[0].lower() for column in cursor.description]
    return {column: _value(value) for column, value in zip(columns, values)}


def _rows(cursor: oracledb.Cursor) -> list[dict[str, Any]]:
    if cursor.description is None:
        raise RuntimeError("ORACLE_QUERY_HAS_NO_RESULT_DESCRIPTION")
    columns = [column[0].lower() for column in cursor.description]
    return [
        {column: _value(value) for column, value in zip(columns, values)}
        for values in cursor.fetchall()
    ]


class OracleYobiRepository:
    """Production repository: Oracle owns catalog, state, cart, checkout, and audit data."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pool = OraclePool(settings)
        self.embedding_provider = choose_embedding_provider(settings)

    def initialize(self) -> None:
        self.pool.initialize()
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM schema_migration")
            cursor.fetchone()

    def create_profile(self, data: ProfileCreate) -> Profile:
        if not data.consent_demo_data:
            raise ValueError("Demo data processing consent is required to start a session")
        profile_id = _id("profile")
        created_at = _now()
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO user_profile (
                  profile_id, preferred_language, nationality, age_band, gender,
                  religion_selection, dietary_rules_json, allergy_severity,
                  spice_tolerance, favorite_foods_json, consent_demo_data,
                  remember_profile, created_at
                ) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12,:13)
                """,
                [
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
                ],
            )
        return Profile(profile_id=profile_id, created_at=created_at, **data.model_dump())

    def get_profile(self, profile_id: str) -> Profile | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM user_profile WHERE profile_id = :id", id=profile_id)
            row = _row(cursor)
        return self._profile(row) if row else None

    @staticmethod
    def _profile(row: dict[str, Any]) -> Profile:
        return Profile(
            profile_id=row["profile_id"],
            preferred_language=row["preferred_language"],
            nationality=row["nationality"],
            age_band=row["age_band"],
            gender=row["gender"],
            religion_selection=row["religion_selection"],
            dietary_rules=_json(row["dietary_rules_json"]),
            allergy_severity=row["allergy_severity"],
            spice_tolerance=int(row["spice_tolerance"]),
            favorite_foods=_json(row["favorite_foods_json"]),
            consent_demo_data=bool(row["consent_demo_data"]),
            remember_profile=bool(row["remember_profile"]),
            created_at=row["created_at"],
        )

    def delete_profile(self, profile_id: str) -> bool:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT session_id FROM chat_session WHERE profile_id = :id", id=profile_id)
            for row in cursor.fetchall():
                self._reset(connection, row[0], True)
            cursor.execute("DELETE FROM user_profile WHERE profile_id = :id", id=profile_id)
            return cursor.rowcount > 0

    def create_session(self, profile_id: str) -> Session:
        if not self.get_profile(profile_id):
            raise KeyError("PROFILE_NOT_FOUND")
        session_id = _id("session")
        now = _now()
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO chat_session (
                  session_id, profile_id, state, state_stack_json, required_slots_json,
                  created_at, updated_at
                ) VALUES (:1,:2,:3,'[]',:4,:5,:6)
                """,
                [
                    session_id,
                    profile_id,
                    ChatState.DISCOVERY.value,
                    json.dumps(["order.menu_id", "delivery.address_confirmed"]),
                    now,
                    now,
                ],
            )
        return Session(
            session_id=session_id,
            profile_id=profile_id,
            state=ChatState.DISCOVERY,
            created_at=now,
            updated_at=now,
        )

    def get_session(self, session_id: str) -> Session | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM chat_session WHERE session_id = :id", id=session_id)
            row = _row(cursor)
        if not row:
            return None
        return Session(
            session_id=row["session_id"],
            profile_id=row["profile_id"],
            state=ChatState(row["state"]),
            selected_menu_id=row["selected_menu_id"],
            selected_merchant_id=row["selected_merchant_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_message(self, session_id: str, role: str, content: str, message_type: str) -> str:
        message_id = _id("msg")
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO chat_message(message_id, session_id, role, content, message_type, created_at)
                VALUES (:1,:2,:3,:4,:5,:6)
                """,
                [message_id, session_id, role, content, message_type, _now()],
            )
        return message_id

    def list_messages(self, session_id: str) -> list[dict[str, str]]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT message_id, role, content, message_type, created_at
                FROM chat_message WHERE session_id = :id ORDER BY created_at, message_id
                """,
                id=session_id,
            )
            rows = _rows(cursor)
        return [{key: str(value) for key, value in row.items()} for row in rows]

    def set_session_selection(
        self, session_id: str, state: str, menu_id: str | None, merchant_id: str | None
    ) -> None:
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                UPDATE chat_session SET state=:state, selected_menu_id=:menu_id,
                  selected_merchant_id=:merchant_id, updated_at=:updated_at
                WHERE session_id=:session_id
                """,
                state=state,
                menu_id=menu_id,
                merchant_id=merchant_id,
                updated_at=_now(),
                session_id=session_id,
            )

    def search_menus(
        self,
        query: str,
        profile: Profile,
        budget_krw: int | None,
        max_spiciness: int | None,
        excluded_ingredients: list[str],
        limit: int = 4,
    ) -> list[MenuSummary]:
        budget = budget_krw or 30000
        spice = max_spiciness if max_spiciness is not None else max(profile.spice_tolerance, 1)
        query_vector = array(
            "f", self.embedding_provider.embed([query], "SEARCH_QUERY")[0]
        )
        severe_shellfish = (
            "shellfish_allergy" in profile.dietary_rules and profile.allergy_severity == "severe"
        )
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM (
                  SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max,
                    VECTOR_DISTANCE(m.embedding_vector, :query_vector, COSINE) AS vector_distance
                  FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                  WHERE m.availability = 'AVAILABLE'
                    AND m.price <= :budget
                    AND m.spice_level <= :spice
                    AND m.embedding_vector IS NOT NULL
                    AND (:severe_shellfish = 0 OR (
                      JSON_EXISTS(m.dietary_tags_json, '$?(@ == "shellfish_sauce_absent")')
                      AND NOT JSON_EXISTS(m.allergen_tags_json, '$?(@ == "shellfish_risk")')
                    ))
                    AND (:exclude_pork = 0 OR NOT JSON_EXISTS(m.allergen_tags_json, '$?(@ == "pork")'))
                  ORDER BY vector_distance, m.price
                ) WHERE ROWNUM <= :candidate_limit
                """,
                query_vector=query_vector,
                budget=budget,
                spice=spice,
                severe_shellfish=int(severe_shellfish),
                exclude_pork=int("pork" in {item.lower() for item in excluded_ingredients}),
                candidate_limit=max(limit * 5, 20),
            )
            rows = _rows(cursor)

        lowered = query.lower()
        scored: list[tuple[float, dict[str, Any], list[str], list[str], EvidenceStatus]] = []
        for row in rows:
            tags = set(_json(row["dietary_tags_json"]))
            allergens = set(_json(row["allergen_tags_json"]))
            similarity = max(0.0, 1.0 - float(row["vector_distance"]))
            boost = 0.0
            if "red rice cake" in lowered and "tteokbokki" in row["category"].lower():
                boost += 0.45
            if any(term in lowered for term in ("rain", "broth", "noodle", "soup")) and row[
                "category"
            ] in {"Chicken kalguksu", "Samgyetang", "Sundubu"}:
                boost += 0.18
            if any(term in lowered for term in ("mild", "not spicy")) and row["spice_level"] <= 1:
                boost += 0.16
            if "vegan" in lowered and "vegan_option" in tags:
                boost += 0.4
            reasons = [f"Matches your spice tolerance ({int(row['spice_level'])}/5)"]
            if "creamy pasta" in profile.favorite_foods and "rose" in row["category"].lower():
                boost += 0.2
                reasons.append("Creamy profile connects with a favourite food you selected")
            risks: list[str] = []
            status = EvidenceStatus.UNKNOWN
            if "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
                reasons.append("Demo sauce specification has shellfish marked absent")
                risks.append("Cross-contamination is not verified")
            elif allergens:
                risks.append("Some dietary details are not verified")
            scored.append((similarity + boost, row, reasons, risks, status))
        scored.sort(key=lambda item: (item[0], -int(item[1]["price"])), reverse=True)
        return [
            self._menu_summary(row, reasons, risks, status, score)
            for score, row, reasons, risks, status in scored[:limit]
        ]

    @staticmethod
    def _menu_summary(
        row: dict[str, Any],
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
            price=int(row["price"]),
            delivery_fee=int(row["delivery_fee"]),
            eta_min=int(row["eta_min"]),
            eta_max=int(row["eta_max"]),
            spice_level=int(row["spice_level"]),
            serves_min=int(row["serves_min"]),
            serves_max=int(row["serves_max"]),
            dietary_summary="Synthetic evidence; see evidence details before ordering.",
            evidence_status=status,
            match_reasons=reasons,
            risk_hints=risks,
            semantic_score=round(max(0.0, min(1.0, score)), 4),
        )

    def get_menu(self, menu_id: str, profile: Profile) -> MenuSummary | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max
                FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                WHERE m.menu_id=:id
                """,
                id=menu_id,
            )
            row = _row(cursor)
        if not row:
            return None
        tags = set(_json(row["dietary_tags_json"]))
        allergens = set(_json(row["allergen_tags_json"]))
        status = EvidenceStatus.UNKNOWN
        if "shellfish_risk" in allergens:
            status = EvidenceStatus.RISK_SIGNAL
        elif "shellfish_sauce_absent" in tags:
            status = EvidenceStatus.VERIFIED
        return self._menu_summary(
            row,
            ["Selected menu from the synthetic catalog"],
            ["Cross-contamination is not verified"],
            status,
            1.0,
        )

    def get_evidence(self, menu_id: str) -> list[Evidence]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM evidence WHERE subject_id=:id ORDER BY evidence_id", id=menu_id
            )
            rows = _rows(cursor)
        return [Evidence(**row) for row in rows]

    def compare_merchants(
        self, category: str, profile: Profile, limit: int = 3
    ) -> list[MerchantComparison]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT * FROM (
                  SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min,
                    r.eta_max, r.flavor_profile, r.packaging_signal
                  FROM menu m JOIN merchant r ON r.merchant_id=m.merchant_id
                  WHERE LOWER(m.category)=LOWER(:category) AND m.availability='AVAILABLE'
                  ORDER BY m.price, r.eta_min
                ) WHERE ROWNUM <= :limit
                """,
                category=category,
                limit=limit,
            )
            rows = _rows(cursor)
        result = []
        for index, row in enumerate(rows):
            allergens = set(_json(row["allergen_tags_json"]))
            tags = set(_json(row["dietary_tags_json"]))
            status = EvidenceStatus.UNKNOWN
            note = "Ingredient and cross-contamination details are not verified."
            if "shellfish_risk" in allergens:
                status = EvidenceStatus.RISK_SIGNAL
                note = "Synthetic reviews contain a shellfish risk signal."
            elif "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
                note = "Sauce marked seafood-free; cross-contamination remains unknown."
            result.append(
                MerchantComparison(
                    merchant_id=row["merchant_id"],
                    merchant_name=row["merchant_name"],
                    menu_id=row["menu_id"],
                    menu_name=row["name_en"],
                    price=int(row["price"]),
                    delivery_fee=int(row["delivery_fee"]),
                    eta=f"{int(row['eta_min'])}-{int(row['eta_max'])} min",
                    portion=("One-person portion" if row["serves_max"] == 1 else "Shareable portion"),
                    flavor=row["flavor_profile"],
                    packaging_signal=row["packaging_signal"],
                    dietary_status=status,
                    dietary_note=note,
                    best_for=(
                        "First-time visitors who prefer a milder, creamier dish"
                        if index == 0
                        else "Travellers prioritising value and a larger portion"
                    ),
                )
            )
        return result

    def get_options(self, menu_id: str) -> list[OptionGroup]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM menu_option_group WHERE menu_id=:id ORDER BY sort_order", id=menu_id
            )
            groups = _rows(cursor)
            result = []
            for group in groups:
                cursor.execute(
                    "SELECT * FROM menu_option_item WHERE option_group_id=:id ORDER BY sort_order",
                    id=group["option_group_id"],
                )
                items = _rows(cursor)
                result.append(
                    OptionGroup(
                        option_group_id=group["option_group_id"],
                        name_en=group["name_en"],
                        name_ko=group["name_ko"],
                        description=group["description"],
                        required=bool(group["required"]),
                        min_select=int(group["min_select"]),
                        max_select=int(group["max_select"]),
                        items=[
                            OptionItem(
                                option_item_id=item["option_item_id"],
                                name_en=item["name_en"],
                                name_ko=item["name_ko"],
                                description=item["description"],
                                price_delta=int(item["price_delta"]),
                                available=item["availability"] == "AVAILABLE",
                                dietary_conflict=item["dietary_conflict"],
                            )
                            for item in items
                        ],
                    )
                )
        return result

    def resolve_address(self, text: str, file_hash: str | None = None) -> list[AddressCandidate]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM address_place ORDER BY place_id")
            rows = _rows(cursor)
        normalized = text.lower().strip()
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            aliases = _json(row["aliases_json"])
            haystack = " ".join([row["name_en"], row["name_ko"], *aliases]).lower()
            score = 0.98 if row["place_id"] == "hotel_demo_01" and "myeongdong" in normalized else 0.0
            if normalized and any(token in haystack for token in normalized.split()):
                score = max(score, 0.82)
            if file_hash and row["fixture_sha256"] == file_hash:
                score = 1.0
            if score:
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
                delivery_hint=row["delivery_hint"],
                confidence=score,
                source="canonical_fixture" if score >= 0.98 else "manual",
                needs_confirmation=True,
            )
            for score, row in scored[:3]
        ]

    def save_address(self, session_id: str, candidate: AddressCandidate) -> str:
        address_ref_id = _id("address")
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO address_ref(address_ref_id,session_id,source_type,place_id,hotel_name,
                  road_address,extraction_confidence,confirmed,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,1,:8)
                """,
                [
                    address_ref_id,
                    session_id,
                    candidate.source,
                    candidate.place_id,
                    candidate.hotel_name,
                    candidate.road_address,
                    candidate.confidence,
                    _now(),
                ],
            )
            cart_id = self._ensure_cart(connection, session_id)
            cursor.execute(
                "UPDATE cart SET address_ref_id=:address,version=version+1,updated_at=:now WHERE cart_id=:cart",
                address=address_ref_id,
                now=_now(),
                cart=cart_id,
            )
        return address_ref_id

    @staticmethod
    def _ensure_cart(connection: oracledb.Connection, session_id: str) -> str:
        cursor = connection.cursor()
        cursor.execute("SELECT cart_id FROM cart WHERE session_id=:id", id=session_id)
        row = cursor.fetchone()
        if row:
            return row[0]
        cart_id = _id("cart")
        now = _now()
        cursor.execute(
            "INSERT INTO cart(cart_id,session_id,created_at,updated_at) VALUES (:1,:2,:3,:4)",
            [cart_id, session_id, now, now],
        )
        return cart_id

    def add_cart_item(self, session_id: str, item: CartItemInput) -> CartPreview:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM menu WHERE menu_id=:id AND availability='AVAILABLE'", id=item.menu_id
            )
            menu = _row(cursor)
            if not menu:
                raise KeyError("MENU_NOT_FOUND")
            options = []
            selected_groups: set[str] = set()
            option_total = 0
            for option_id in item.option_item_ids:
                cursor.execute(
                    """
                    SELECT i.*,g.menu_id FROM menu_option_item i
                    JOIN menu_option_group g ON g.option_group_id=i.option_group_id
                    WHERE i.option_item_id=:id AND i.availability='AVAILABLE'
                    """,
                    id=option_id,
                )
                option = _row(cursor)
                if not option or option["menu_id"] != item.menu_id:
                    raise ValueError("INVALID_MENU_OPTION")
                if option["option_group_id"] in selected_groups:
                    raise ValueError("OPTION_GROUP_MAX_EXCEEDED")
                selected_groups.add(option["option_group_id"])
                options.append(
                    {
                        "option_item_id": option["option_item_id"],
                        "name_en": option["name_en"],
                        "name_ko": option["name_ko"],
                        "price_delta": int(option["price_delta"]),
                    }
                )
                option_total += int(option["price_delta"])
            cursor.execute(
                "SELECT option_group_id FROM menu_option_group WHERE menu_id=:id AND required=1",
                id=item.menu_id,
            )
            if any(row[0] not in selected_groups for row in cursor.fetchall()):
                raise ValueError("REQUIRED_MENU_OPTION_MISSING")
            cart_id = self._ensure_cart(connection, session_id)
            line_total = (int(menu["price"]) + option_total) * item.quantity
            cursor.execute(
                """
                INSERT INTO cart_item(cart_item_id,cart_id,menu_id,merchant_id,quantity,unit_price,
                  menu_snapshot_json,option_snapshot_json,line_total,user_note,korean_note,created_at)
                VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10,:11,:12)
                """,
                [
                    _id("cartitem"),
                    cart_id,
                    menu["menu_id"],
                    menu["merchant_id"],
                    item.quantity,
                    int(menu["price"]),
                    json.dumps({"name_en": menu["name_en"], "price": int(menu["price"])}),
                    json.dumps(options),
                    line_total,
                    item.user_note,
                    self._translate_note(item.user_note),
                    _now(),
                ],
            )
            cursor.execute(
                "UPDATE cart SET version=version+1,confirmed=0,updated_at=:now WHERE cart_id=:id",
                now=_now(),
                id=cart_id,
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
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM cart WHERE session_id=:id", id=session_id)
            cart = _row(cursor)
            if not cart:
                cart_id = self._ensure_cart(connection, session_id)
                cursor.execute("SELECT * FROM cart WHERE cart_id=:id", id=cart_id)
                cart = _row(cursor)
            if cart is None:
                raise RuntimeError("CART_CREATION_FAILED")
            cursor.execute(
                """
                SELECT ci.*,m.name_en AS menu_name FROM cart_item ci
                JOIN menu m ON m.menu_id=ci.menu_id WHERE ci.cart_id=:id ORDER BY ci.created_at
                """,
                id=cart["cart_id"],
            )
            rows = _rows(cursor)
            cursor.execute(
                """
                SELECT NVL(MAX(r.delivery_fee),0) FROM cart_item ci
                JOIN merchant r ON r.merchant_id=ci.merchant_id WHERE ci.cart_id=:id
                """,
                id=cart["cart_id"],
            )
            delivery_fee = int(cursor.fetchone()[0])
            cursor.execute("SELECT 1 FROM delivery_preference WHERE cart_id=:id", id=cart["cart_id"])
            has_delivery = cursor.fetchone() is not None
        items = [
            CartLine(
                cart_item_id=row["cart_item_id"],
                menu_id=row["menu_id"],
                merchant_id=row["merchant_id"],
                menu_name=row["menu_name"],
                quantity=int(row["quantity"]),
                unit_price=int(row["unit_price"]),
                options=_json(row["option_snapshot_json"]),
                line_total=int(row["line_total"]),
            )
            for row in rows
        ]
        missing = []
        if not items:
            missing.append("menu")
        if not cart["address_ref_id"]:
            missing.append("address")
        if not has_delivery:
            missing.append("delivery_preferences")
        subtotal = sum(item.line_total for item in items)
        return CartPreview(
            cart_id=cart["cart_id"],
            session_id=session_id,
            version=int(cart["version"]),
            items=items,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            total_price=subtotal + delivery_fee,
            missing_slots=missing,
            dietary_warnings=(
                ["Synthetic evidence only; cross-contamination may be unverified."] if items else []
            ),
            ready_to_checkout=not missing,
            confirmed=bool(cart["confirmed"]),
        )

    def update_delivery(
        self, session_id: str, preference: DeliveryPreferenceInput
    ) -> CartPreview:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cart_id = self._ensure_cart(connection, session_id)
            if preference.address_ref_id:
                cursor.execute(
                    """
                    SELECT 1 FROM address_ref WHERE address_ref_id=:b_address AND session_id=:b_session_id
                      AND confirmed=1
                    """,
                    b_address=preference.address_ref_id,
                    b_session_id=session_id,
                )
                if not cursor.fetchone():
                    raise ValueError("ADDRESS_NOT_CONFIRMED")
                cursor.execute(
                    "UPDATE cart SET address_ref_id=:address WHERE cart_id=:cart",
                    address=preference.address_ref_id,
                    cart=cart_id,
                )
            korean = self._translate_note(preference.user_note)
            cursor.execute(
                """
                MERGE INTO delivery_preference target
                USING (SELECT :b_cart_id AS cart_id FROM dual) source
                ON (target.cart_id=source.cart_id)
                WHEN MATCHED THEN UPDATE SET handoff_method=:b_handoff,cutlery=:b_cutlery,
                  ring_bell=:b_ring_bell,front_desk=:b_front_desk,user_note=:b_user_note,
                  korean_note=:b_korean_note,back_translation=:b_back_translation
                WHEN NOT MATCHED THEN INSERT (cart_id,handoff_method,cutlery,ring_bell,
                  front_desk,user_note,korean_note,back_translation)
                VALUES (:b_cart_id,:b_handoff,:b_cutlery,:b_ring_bell,:b_front_desk,:b_user_note,
                  :b_korean_note,:b_back_translation)
                """,
                b_cart_id=cart_id,
                b_handoff=preference.handoff_method,
                b_cutlery=int(preference.cutlery),
                b_ring_bell=int(preference.ring_bell),
                b_front_desk=int(preference.front_desk),
                b_user_note=preference.user_note,
                b_korean_note=korean,
                b_back_translation=preference.user_note,
            )
            cursor.execute(
                "UPDATE cart SET version=version+1,confirmed=0,updated_at=:now WHERE cart_id=:id",
                now=_now(),
                id=cart_id,
            )
        return self.get_cart(session_id)

    def confirm_cart(self, session_id: str) -> CartPreview:
        preview = self.get_cart(session_id)
        if not preview.ready_to_checkout:
            raise ValueError("CART_INCOMPLETE")
        with self.pool.connection() as connection:
            connection.cursor().execute(
                "UPDATE cart SET confirmed=1,updated_at=:now WHERE cart_id=:id",
                now=_now(),
                id=preview.cart_id,
            )
        return self.get_cart(session_id)

    def create_checkout(self, session_id: str, data: CheckoutCreate) -> Checkout:
        preview = self.get_cart(session_id)
        if not preview.ready_to_checkout or not preview.confirmed:
            raise ValueError("CART_NOT_CONFIRMED")
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM mock_checkout WHERE idempotency_key=:key", key=data.idempotency_key
            )
            existing = _row(cursor)
            if existing:
                if existing["cart_id"] != preview.cart_id:
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                return self._checkout(existing)
            checkout_id = _id("checkout")
            now = _now()
            cursor.execute(
                """
                INSERT INTO mock_checkout(checkout_id,cart_id,idempotency_key,payment_method,status,
                  amount,payment_url,created_at,updated_at)
                VALUES (:1,:2,:3,:4,'PENDING',:5,:6,:7,:8)
                """,
                [
                    checkout_id,
                    preview.cart_id,
                    data.idempotency_key,
                    data.payment_method,
                    preview.total_price,
                    f"/pay/{checkout_id}",
                    now,
                    now,
                ],
            )
            cursor.execute("SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id)
            row = _row(cursor)
        if row is None:
            raise RuntimeError("CHECKOUT_CREATION_FAILED")
        return self._checkout(row)

    @staticmethod
    def _checkout(row: dict[str, Any], order_id: str | None = None) -> Checkout:
        return Checkout(
            checkout_id=row["checkout_id"],
            cart_id=row["cart_id"],
            status=row["status"],
            amount=int(row["amount"]),
            payment_method=row["payment_method"],
            payment_url=row["payment_url"],
            order_id=order_id,
        )

    def get_checkout(self, checkout_id: str) -> Checkout | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id)
            row = _row(cursor)
            if not row:
                return None
            cursor.execute("SELECT order_id FROM mock_order WHERE checkout_id=:id", id=checkout_id)
            order = cursor.fetchone()
        return self._checkout(row, order[0] if order else None)

    def update_checkout(self, checkout_id: str, status: str) -> Checkout:
        if status not in {"SUCCEEDED", "FAILED", "CANCELED"}:
            raise ValueError("INVALID_PAYMENT_STATUS")
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id=:id FOR UPDATE", id=checkout_id
            )
            row = _row(cursor)
            if not row:
                raise KeyError("CHECKOUT_NOT_FOUND")
            if row["status"] == "SUCCEEDED" and status != "SUCCEEDED":
                raise ValueError("PAYMENT_ALREADY_SUCCEEDED")
            cursor.execute(
                "UPDATE mock_checkout SET status=:status,updated_at=:now WHERE checkout_id=:id",
                status=status,
                now=_now(),
                id=checkout_id,
            )
            order_id = None
            if status == "SUCCEEDED":
                cursor.execute("SELECT order_id FROM mock_order WHERE checkout_id=:id", id=checkout_id)
                existing = cursor.fetchone()
                if existing:
                    order_id = existing[0]
                else:
                    order_id = _id("YOBI-DEMO")
                    cursor.execute(
                        "SELECT * FROM cart_item WHERE cart_id=:id ORDER BY created_at",
                        id=row["cart_id"],
                    )
                    snapshot = _rows(cursor)
                    for item in snapshot:
                        item["created_at"] = str(item["created_at"])
                    cursor.execute(
                        """
                        INSERT INTO mock_order(order_id,checkout_id,cart_snapshot_json,order_status,
                          estimated_delivery_at,created_at)
                        VALUES (:1,:2,:3,'CONFIRMED',:4,:5)
                        """,
                        [
                            order_id,
                            checkout_id,
                            json.dumps(snapshot),
                            _now() + timedelta(minutes=35),
                            _now(),
                        ],
                    )
            cursor.execute("SELECT * FROM mock_checkout WHERE checkout_id=:id", id=checkout_id)
            updated = _row(cursor)
        if updated is None:
            raise RuntimeError("CHECKOUT_UPDATE_FAILED")
        return self._checkout(updated, order_id)

    def get_order(self, order_id: str) -> Order | None:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM mock_order WHERE order_id=:id", id=order_id)
            row = _row(cursor)
        if not row:
            return None
        return Order(
            order_id=row["order_id"],
            checkout_id=row["checkout_id"],
            order_status=row["order_status"],
            estimated_delivery_at=row["estimated_delivery_at"],
            summary={"items": _json(row["cart_snapshot_json"]), "payment": "Demo only"},
        )

    def reset_session(self, session_id: str) -> None:
        with self.pool.connection() as connection:
            self._reset(connection, session_id, False)

    def prewarm_explanation(self, menu_id: str) -> bool:
        profile = Profile(
            profile_id="prewarm",
            consent_demo_data=True,
            created_at=datetime.now(timezone.utc),
        )
        menu = self.get_menu(menu_id, profile)
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
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                MERGE INTO explanation_cache target
                USING (SELECT :cache_key AS cache_key FROM dual) source
                ON (target.cache_key = source.cache_key)
                WHEN MATCHED THEN UPDATE SET
                  target.explanation_json=:payload,
                  target.source_version=:source_version,
                  target.created_at=SYSTIMESTAMP
                WHEN NOT MATCHED THEN INSERT (
                  cache_key, menu_id, language, profile_signature,
                  explanation_json, source_version
                ) VALUES (:cache_key, :menu_id, 'en', 'prewarm', :payload, :source_version)
                """,
                cache_key=f"prewarm:{menu_id}:en",
                menu_id=menu_id,
                payload=payload,
                source_version=CATALOG_VERSION,
            )
        return True

    @staticmethod
    def _reset(connection: oracledb.Connection, session_id: str, delete_session: bool) -> None:
        cursor = connection.cursor()
        cursor.execute("SELECT cart_id FROM cart WHERE session_id=:id", id=session_id)
        row = cursor.fetchone()
        if row:
            cart_id = row[0]
            cursor.execute(
                "DELETE FROM mock_order WHERE checkout_id IN (SELECT checkout_id FROM mock_checkout WHERE cart_id=:id)",
                id=cart_id,
            )
            cursor.execute("DELETE FROM mock_checkout WHERE cart_id=:id", id=cart_id)
            cursor.execute("DELETE FROM cart WHERE cart_id=:id", id=cart_id)
        cursor.execute("DELETE FROM address_ref WHERE session_id=:id", id=session_id)
        cursor.execute("DELETE FROM chat_message WHERE session_id=:id", id=session_id)
        if delete_session:
            cursor.execute("DELETE FROM chat_session WHERE session_id=:id", id=session_id)
        else:
            cursor.execute(
                """
                UPDATE chat_session SET state=:state,selected_menu_id=NULL,
                  selected_merchant_id=NULL,updated_at=:now WHERE session_id=:id
                """,
                state=ChatState.DISCOVERY.value,
                now=_now(),
                id=session_id,
            )

    def status(self) -> dict[str, object]:
        with self.pool.connection() as connection:
            cursor = connection.cursor()
            counts = {}
            for table in (
                "merchant",
                "menu",
                "menu_option_item",
                "review_snippet",
                "evidence",
                "address_place",
            ):
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM menu WHERE menu_id IN ('menu_001_01','menu_002_01','menu_003_01')"
            )
            canonical = int(cursor.fetchone()[0]) == 3
            cursor.execute(
                """
                SELECT VECTOR_DISTANCE(embedding_vector, embedding_vector, COSINE)
                FROM menu WHERE embedding_vector IS NOT NULL FETCH FIRST 1 ROW ONLY
                """
            )
            vector_ready = cursor.fetchone() is not None
            cursor.execute("SELECT MAX(updated_at) FROM menu")
            last_seed_time = cursor.fetchone()[0]
        return {
            "backend": "oracle-26ai",
            "catalog_version": CATALOG_VERSION,
            "counts": counts,
            "canonical_ready": canonical,
            "vector_ready": vector_ready,
            "embedding_model": self.embedding_provider.model,
            "last_seed_time": str(last_seed_time) if last_seed_time else None,
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
        with self.pool.connection() as connection:
            connection.cursor().execute(
                """
                INSERT INTO audit_log (
                  log_id,session_id,tool,input_hash,evidence_ids_json,output_status,
                  latency_ms,fallback_used,safe_error_code,created_at
                ) VALUES (:1,:2,:3,:4,:5,:6,:7,:8,:9,:10)
                """,
                [
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
                ],
            )

    @staticmethod
    def safe_input_hash(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
