from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.schema_sqlite import SCHEMA_SQL
from app.db.seed_data import CATALOG_VERSION, build_seed
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
from app.rag.embeddings import cosine_similarity, deterministic_embedding


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


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
            existing = connection.execute("SELECT COUNT(*) FROM merchant").fetchone()[0]
            if existing:
                return
            seed = build_seed()
            self._insert_rows(connection, "merchant", seed["merchants"])
            self._insert_rows(connection, "menu", seed["menus"])
            self._insert_rows(connection, "evidence", seed["evidence"])
            self._insert_rows(connection, "review_snippet", seed["reviews"])
            self._insert_rows(connection, "menu_option_group", seed["option_groups"])
            self._insert_rows(connection, "menu_option_item", seed["option_items"])
            self._insert_rows(connection, "address_place", seed["hotels"])

    @staticmethod
    def _insert_rows(
        connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]
    ) -> None:
        if not rows:
            return
        columns = list(rows[0])
        placeholders = ",".join("?" for _ in columns)
        sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
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
                self._reset_session_in_connection(connection, row["session_id"], delete_session=True)
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
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_message(self, session_id: str, role: str, content: str, message_type: str) -> str:
        message_id = _id("msg")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO chat_message (
                  message_id, session_id, role, content, message_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, message_type, _now()),
            )
        return message_id

    def list_messages(self, session_id: str) -> list[dict[str, str]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT message_id, role, content, message_type, created_at
                FROM chat_message WHERE session_id = ? ORDER BY created_at, message_id
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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
    ) -> list[MenuSummary]:
        budget = budget_krw or 30000
        spice = max_spiciness if max_spiciness is not None else profile.spice_tolerance
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min, r.eta_max
                FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                WHERE m.availability = 'AVAILABLE' AND m.price <= ? AND m.spice_level <= ?
                """,
                (budget, max(spice, 1)),
            ).fetchall()

        query_vector = deterministic_embedding(query)
        scored: list[tuple[float, sqlite3.Row, list[str], list[str], EvidenceStatus]] = []
        severe_shellfish = (
            "shellfish_allergy" in profile.dietary_rules and profile.allergy_severity == "severe"
        )
        excluded = {item.lower() for item in excluded_ingredients}
        for row in rows:
            dietary_tags = set(json.loads(row["dietary_tags_json"]))
            allergen_tags = set(json.loads(row["allergen_tags_json"]))
            if "pork" in excluded and "pork" in allergen_tags:
                continue
            if severe_shellfish and "shellfish_sauce_absent" not in dietary_tags:
                continue
            score = cosine_similarity(query_vector, deterministic_embedding(row["semantic_text"]))
            exact_boost = 0.0
            lowered = query.lower()
            if "red rice cake" in lowered and "tteokbokki" in row["category"].lower():
                exact_boost += 0.45
            if "rain" in lowered and row["category"] in {"Chicken kalguksu", "Samgyetang", "Sundubu"}:
                exact_boost += 0.18
            if any(term in lowered for term in ("broth", "noodle", "soup")) and row[
                "category"
            ] in {"Chicken kalguksu", "Samgyetang", "Sundubu"}:
                exact_boost += 0.18
            if any(term in lowered for term in ("mild", "not spicy")) and row["spice_level"] <= 1:
                exact_boost += 0.16
            if any(term in lowered for term in ("vegan", "plant")) and "vegan_option" in dietary_tags:
                exact_boost += 0.4
            reasons = [f"Matches your spice tolerance ({row['spice_level']}/5)"]
            if "creamy pasta" in profile.favorite_foods and "rose" in row["category"].lower():
                exact_boost += 0.2
                reasons.append("Creamy profile connects with a favourite food you selected")
            if "shellfish_sauce_absent" in dietary_tags:
                reasons.append("Demo sauce specification has shellfish marked absent")
            risks = []
            status = EvidenceStatus.UNKNOWN
            if "shellfish_sauce_absent" in dietary_tags:
                status = EvidenceStatus.VERIFIED
                risks.append("Cross-contamination is not verified")
            elif allergen_tags:
                risks.append("Some dietary details are not verified")
            scored.append((score + exact_boost, row, reasons, risks, status))

        scored.sort(key=lambda item: (item[0], -item[1]["price"]), reverse=True)
        return [
            self._menu_summary(row, reasons, risks, status, score)
            for score, row, reasons, risks, status in scored[:limit]
        ]

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
        status = EvidenceStatus.RISK_SIGNAL if "shellfish_risk" in allergens else EvidenceStatus.UNKNOWN
        tags = set(json.loads(row["dietary_tags_json"]))
        if "shellfish_sauce_absent" in tags:
            status = EvidenceStatus.VERIFIED
        return self._menu_summary(
            row,
            ["Selected menu from the synthetic catalog"],
            ["Cross-contamination is not verified"],
            status,
            1.0,
        )

    def get_evidence(self, menu_id: str) -> list[Evidence]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM evidence WHERE subject_id = ? ORDER BY evidence_id",
                (menu_id,),
            ).fetchall()
        return [Evidence(**dict(row)) for row in rows]

    def compare_merchants(
        self, category: str, profile: Profile, limit: int = 3
    ) -> list[MerchantComparison]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.*, r.name_en AS merchant_name, r.delivery_fee, r.eta_min,
                       r.eta_max, r.flavor_profile, r.packaging_signal
                FROM menu m JOIN merchant r ON r.merchant_id = m.merchant_id
                WHERE lower(m.category) = lower(?) AND m.availability = 'AVAILABLE'
                ORDER BY m.price, r.eta_min LIMIT ?
                """,
                (category, limit),
            ).fetchall()
        comparisons = []
        for index, row in enumerate(rows):
            allergens = set(json.loads(row["allergen_tags_json"]))
            tags = set(json.loads(row["dietary_tags_json"]))
            status = EvidenceStatus.UNKNOWN
            note = "Ingredient and cross-contamination details are not verified."
            if "shellfish_risk" in allergens:
                status = EvidenceStatus.RISK_SIGNAL
                note = "Synthetic reviews contain a shellfish risk signal."
            elif "shellfish_sauce_absent" in tags:
                status = EvidenceStatus.VERIFIED
                note = "Sauce marked seafood-free; cross-contamination remains unknown."
            comparisons.append(
                MerchantComparison(
                    merchant_id=row["merchant_id"],
                    merchant_name=row["merchant_name"],
                    menu_id=row["menu_id"],
                    menu_name=row["name_en"],
                    price=row["price"],
                    delivery_fee=row["delivery_fee"],
                    eta=f"{row['eta_min']}-{row['eta_max']} min",
                    portion="One-person portion" if row["serves_max"] == 1 else "Shareable portion",
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
                    SELECT * FROM menu_option_item
                    WHERE option_group_id = ? ORDER BY sort_order
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
                            )
                            for item in items
                        ],
                    )
                )
        return result

    def resolve_address(self, text: str, file_hash: str | None = None) -> list[AddressCandidate]:
        normalized = text.lower().strip()
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM address_place ORDER BY place_id").fetchall()
        scored = []
        for row in rows:
            aliases = json.loads(row["aliases_json"])
            haystack = " ".join([row["name_en"], row["name_ko"], *aliases]).lower()
            score = 0.98 if row["place_id"] == "hotel_demo_01" and "myeongdong" in normalized else 0.0
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
                delivery_hint=row["delivery_hint"],
                confidence=score,
                source="canonical_fixture" if score >= 0.98 else "manual",
                needs_confirmation=True,
            )
            for score, row in scored[:3]
        ]

    def save_address(self, session_id: str, candidate: AddressCandidate) -> str:
        address_ref_id = _id("address")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO address_ref (
                  address_ref_id, session_id, source_type, place_id, hotel_name,
                  road_address, extraction_confidence, confirmed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    address_ref_id,
                    session_id,
                    candidate.source,
                    candidate.place_id,
                    candidate.hotel_name,
                    candidate.road_address,
                    candidate.confidence,
                    _now(),
                ),
            )
            cart_id = self._ensure_cart(connection, session_id)
            connection.execute(
                "UPDATE cart SET address_ref_id = ?, version = version + 1, updated_at = ? WHERE cart_id = ?",
                (address_ref_id, _now(), cart_id),
            )
        return address_ref_id

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

    def add_cart_item(self, session_id: str, item: CartItemInput) -> CartPreview:
        with self._connection() as connection:
            menu = connection.execute(
                "SELECT * FROM menu WHERE menu_id = ? AND availability = 'AVAILABLE'", (item.menu_id,)
            ).fetchone()
            if not menu:
                raise KeyError("MENU_NOT_FOUND")
            options = []
            option_total = 0
            selected_groups: set[str] = set()
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
                if option["option_group_id"] in selected_groups:
                    raise ValueError("OPTION_GROUP_MAX_EXCEEDED")
                selected_groups.add(option["option_group_id"])
                options.append(
                    {
                        "option_item_id": option["option_item_id"],
                        "name_en": option["name_en"],
                        "name_ko": option["name_ko"],
                        "price_delta": option["price_delta"],
                    }
                )
                option_total += option["price_delta"]
            required_groups = connection.execute(
                """
                SELECT option_group_id FROM menu_option_group
                WHERE menu_id = ? AND required = 1
                """,
                (item.menu_id,),
            ).fetchall()
            missing_required = [
                row["option_group_id"]
                for row in required_groups
                if row["option_group_id"] not in selected_groups
            ]
            if missing_required:
                raise ValueError("REQUIRED_MENU_OPTION_MISSING")
            cart_id = self._ensure_cart(connection, session_id)
            cart_item_id = _id("cartitem")
            line_total = (menu["price"] + option_total) * item.quantity
            connection.execute(
                """
                INSERT INTO cart_item (
                  cart_item_id, cart_id, menu_id, merchant_id, quantity, unit_price,
                  menu_snapshot_json, option_snapshot_json, line_total, user_note,
                  korean_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    _now(),
                ),
            )
            connection.execute(
                "UPDATE cart SET version = version + 1, confirmed = 0, updated_at = ? WHERE cart_id = ?",
                (_now(), cart_id),
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
                cart = connection.execute("SELECT * FROM cart WHERE cart_id = ?", (cart_id,)).fetchone()
            rows = connection.execute(
                """
                SELECT ci.*, m.name_en AS menu_name FROM cart_item ci
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
        items = [
            CartLine(
                cart_item_id=row["cart_item_id"],
                menu_id=row["menu_id"],
                merchant_id=row["merchant_id"],
                menu_name=row["menu_name"],
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
        warnings = []
        if items:
            warnings.append("Synthetic evidence only; cross-contamination may be unverified.")
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
            ready_to_checkout=not missing,
            confirmed=bool(cart["confirmed"]),
        )

    def update_delivery(
        self, session_id: str, preference: DeliveryPreferenceInput
    ) -> CartPreview:
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

    def confirm_cart(self, session_id: str) -> CartPreview:
        preview = self.get_cart(session_id)
        if not preview.ready_to_checkout:
            raise ValueError("CART_INCOMPLETE")
        with self._connection() as connection:
            connection.execute(
                "UPDATE cart SET confirmed = 1, updated_at = ? WHERE cart_id = ?",
                (_now(), preview.cart_id),
            )
        return self.get_cart(session_id)

    def create_checkout(self, session_id: str, data: CheckoutCreate) -> Checkout:
        preview = self.get_cart(session_id)
        if not preview.ready_to_checkout or not preview.confirmed:
            raise ValueError("CART_NOT_CONFIRMED")
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT * FROM mock_checkout WHERE idempotency_key = ?", (data.idempotency_key,)
            ).fetchone()
            if existing:
                if existing["cart_id"] != preview.cart_id:
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                return self._checkout_from_row(existing)
            checkout_id = _id("checkout")
            payment_url = f"/pay/{checkout_id}"
            now = _now()
            connection.execute(
                """
                INSERT INTO mock_checkout (
                  checkout_id, cart_id, idempotency_key, payment_method, status,
                  amount, payment_url, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
                """,
                (
                    checkout_id,
                    preview.cart_id,
                    data.idempotency_key,
                    data.payment_method,
                    preview.total_price,
                    payment_url,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
        return self._checkout_from_row(row)

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
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
            if not row:
                raise KeyError("CHECKOUT_NOT_FOUND")
            if row["status"] == "SUCCEEDED" and status != "SUCCEEDED":
                raise ValueError("PAYMENT_ALREADY_SUCCEEDED")
            connection.execute(
                "UPDATE mock_checkout SET status = ?, updated_at = ? WHERE checkout_id = ?",
                (status, _now(), checkout_id),
            )
            order_id = None
            if status == "SUCCEEDED":
                existing_order = connection.execute(
                    "SELECT order_id FROM mock_order WHERE checkout_id = ?", (checkout_id,)
                ).fetchone()
                if existing_order:
                    order_id = existing_order["order_id"]
                else:
                    order_id = _id("YOBI-DEMO")
                    cart_rows = connection.execute(
                        "SELECT * FROM cart_item WHERE cart_id = ? ORDER BY created_at", (row["cart_id"],)
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
                        (order_id, checkout_id, json.dumps(snapshot), eta.isoformat(), _now()),
                    )
            updated = connection.execute(
                "SELECT * FROM mock_checkout WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
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
        connection.execute("DELETE FROM chat_message WHERE session_id = ?", (session_id,))
        if delete_session:
            connection.execute("DELETE FROM chat_session WHERE session_id = ?", (session_id,))
        else:
            connection.execute(
                """
                UPDATE chat_session SET state = ?, selected_menu_id = NULL,
                  selected_merchant_id = NULL, updated_at = ? WHERE session_id = ?
                """,
                (ChatState.DISCOVERY.value, _now(), session_id),
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
                (f"prewarm:{menu_id}:en", menu_id, payload, CATALOG_VERSION, _now()),
            )
        return True

    def status(self) -> dict[str, object]:
        with self._connection() as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "merchant",
                    "menu",
                    "menu_option_item",
                    "review_snippet",
                    "evidence",
                    "address_place",
                )
            }
            canonical = connection.execute(
                "SELECT COUNT(*) FROM menu WHERE menu_id IN ('menu_001_01','menu_002_01','menu_003_01')"
            ).fetchone()[0]
            last_seed_time = connection.execute(
                "SELECT MAX(updated_at) FROM menu"
            ).fetchone()[0]
        return {
            "backend": "sqlite",
            "catalog_version": CATALOG_VERSION,
            "counts": counts,
            "canonical_ready": canonical == 3,
            "last_seed_time": last_seed_time,
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
