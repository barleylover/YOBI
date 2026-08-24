from __future__ import annotations

from pathlib import Path

from app.db.sqlite_repository import (
    EXPECTED_RUNTIME_COUNTS,
    SQLiteYobiRepository,
)
from app.domain.models import (
    CartItemInput,
    CheckoutCreate,
    DeliveryPreferenceInput,
    ProfileCreate,
)

RUNTIME_TABLES = (
    "user_profile",
    "chat_session",
    "address_ref",
    "cart",
    "cart_item",
    "delivery_preference",
    "mock_checkout",
    "mock_order",
)


def test_option_readiness_distinguishes_release_and_runtime_localizations(
    tmp_path: Path,
) -> None:
    repository = SQLiteYobiRepository(tmp_path / "readiness.db")
    repository.initialize()

    counts = repository.status()["knowledge_supplemental_counts"]

    assert counts["localized_option_groups"] == counts[
        "release_localized_option_groups"
    ]
    assert counts["localized_option_items"] == counts[
        "release_localized_option_items"
    ]
    assert counts["runtime_localized_option_groups"] >= 0
    assert counts["runtime_localized_option_items"] >= 0


def _runtime_snapshot(repository: SQLiteYobiRepository) -> dict[str, list[tuple[object, ...]]]:
    with repository._connection() as connection:
        return {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in RUNTIME_TABLES
        }


def _create_completed_order(repository: SQLiteYobiRepository) -> None:
    profile = repository.create_profile(ProfileCreate(consent_demo_data=True, spice_tolerance=3))
    session = repository.create_session(profile.profile_id)
    repository.add_cart_item(
        session.session_id,
        CartItemInput(
            menu_id="menu_001_01",
            option_item_ids=[
                "oi_001_01_spice_mild",
                "oi_001_01_size_regular",
                "oi_001_01_cheese_add",
                "oi_001_01_fishcake_remove",
            ],
        ),
    )
    address = repository.resolve_address("YOBI Myeongdong Hotel")[0]
    address_ref_id = repository.save_address(session.session_id, address)
    repository.update_delivery(
        session.session_id,
        DeliveryPreferenceInput(address_ref_id=address_ref_id),
    )
    repository.confirm_cart(session.session_id)
    checkout = repository.create_checkout(
        session.session_id,
        CheckoutCreate(
            idempotency_key="seed-upgrade-preservation",
            payment_method="international_card",
        ),
    )
    paid = repository.update_checkout(checkout.checkout_id, "SUCCEEDED")
    assert paid.order_id is not None


def test_upsert_removes_only_stale_catalog_rows_and_preserves_runtime_state(
    tmp_path: Path,
) -> None:
    repository = SQLiteYobiRepository(tmp_path / "upgrade.db")
    repository.initialize()
    _create_completed_order(repository)

    with repository._connection() as connection:
        connection.execute(
            """
            INSERT INTO menu_category VALUES (
              'category_legacy_seed','이전 시드','Legacy seed','obsolete','[]',1,3
            )
            """
        )
        connection.execute(
            "INSERT INTO ingredient VALUES "
            "('ingredient_legacy_seed','이전 재료','Legacy ingredient','legacy')"
        )
        connection.execute(
            "INSERT INTO menu_ingredient VALUES "
            "('menu_001_01','ingredient_legacy_seed','PRESENT','legacy-seed',0)"
        )
        connection.execute(
            "INSERT INTO allergen VALUES "
            "('allergen_legacy_seed','legacy_seed','Legacy allergen','이전 알레르겐')"
        )
        connection.execute(
            "INSERT INTO menu_allergen VALUES "
            "('menu_001_01','allergen_legacy_seed','POSSIBLE',NULL,'UNKNOWN')"
        )
        connection.execute(
            "INSERT INTO dietary_attribute VALUES "
            "('diet_legacy_seed','legacy_seed','Legacy dietary marker')"
        )
        connection.execute(
            "INSERT INTO menu_dietary_attribute VALUES "
            "('menu_001_01','diet_legacy_seed','POSSIBLE',NULL)"
        )
        connection.execute(
            "INSERT INTO option_dietary_conflict VALUES "
            "('oi_001_01_spice_mild','legacy_seed','POSSIBLE',NULL)"
        )

    runtime_before = _runtime_snapshot(repository)
    repository.initialize()

    assert _runtime_snapshot(repository) == runtime_before
    status = repository.status()
    assert status["counts"] == EXPECTED_RUNTIME_COUNTS
    assert status["knowledge_ready"] is True
    readiness_checks = status["readiness_checks"]
    assert isinstance(readiness_checks, dict)
    assert all(readiness_checks.values())
    with repository._connection() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for table, id_column, stale_id in (
            ("menu_category", "category_id", "category_legacy_seed"),
            ("ingredient", "ingredient_id", "ingredient_legacy_seed"),
            ("allergen", "allergen_id", "allergen_legacy_seed"),
            ("dietary_attribute", "attribute_id", "diet_legacy_seed"),
        ):
            assert (
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {id_column}=?", (stale_id,)
                ).fetchone()[0]
                == 0
            )


def test_historical_release_keeps_dimension_rows_required_by_its_claims(
    tmp_path: Path,
) -> None:
    repository = SQLiteYobiRepository(tmp_path / "history.db")
    repository.initialize()
    with repository._connection() as connection:
        connection.execute(
            "INSERT INTO ingredient VALUES "
            "('ingredient_history_only','과거 재료','History-only ingredient','legacy')"
        )
        connection.execute(
            """
            INSERT INTO knowledge_release (
              release_id,catalog_version,manifest_sha256,embedding_model,
              embedding_dimension,embedding_version,status,expected_counts_json,
              actual_counts_json,is_synthetic,created_at,completed_at
            ) VALUES (
              'knowledge-history-sentinel','legacy-v1',?,'legacy-model',1536,
              'legacy-version','READY','{}','{}',1,'old','old'
            )
            """,
            ("b" * 64,),
        )
        connection.execute(
            """
            INSERT INTO dish_concept (
              release_id,concept_id,concept_type,canonical_name_ko,canonical_name_en,
              aliases_json,source_type,source_ref,review_status,is_synthetic,updated_at
            ) VALUES (
              'knowledge-history-sentinel','dish_history','FAMILY','과거 음식',
              'History dish','[]','SYNTHETIC_WIKI','history','DEMO_REVIEWED',1,'old'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO concept_claim (
              release_id,claim_id,concept_id,claim_type,ingredient_id,allergen_id,
              attribute_id,facet_key,value_text,ingredient_role,assertion_status,
              inheritance_mode,source_ref,review_status,is_synthetic,updated_at
            ) VALUES (
              'knowledge-history-sentinel','claim_history','dish_history','INGREDIENT',
              'ingredient_history_only',NULL,NULL,NULL,'history','CORE','TYPICAL',
              'INHERIT','history','DEMO_REVIEWED',1,'old'
            )
            """
        )
        release_before = tuple(
            connection.execute(
                "SELECT * FROM knowledge_release WHERE release_id='knowledge-history-sentinel'"
            ).fetchone()
        )

    repository.initialize()

    with repository._connection() as connection:
        release_after = tuple(
            connection.execute(
                "SELECT * FROM knowledge_release WHERE release_id='knowledge-history-sentinel'"
            ).fetchone()
        )
        assert release_after == release_before
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM ingredient WHERE ingredient_id='ingredient_history_only'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    status = repository.status()
    assert status["counts"]["ingredient"] == EXPECTED_RUNTIME_COUNTS["ingredient"] + 1
    assert status["canonical_ready"] is True
    assert status["knowledge_ready"] is True
    assert status["readiness_checks"]["base_catalog_counts_compatible"] is True
