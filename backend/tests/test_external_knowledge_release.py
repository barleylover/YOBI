from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from app.db.schema_sqlite import SCHEMA_SQL

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_external_knowledge", ROOT / "scripts" / "build_external_knowledge_release.py"
)
assert SPEC and SPEC.loader
external_knowledge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(external_knowledge)

MAPPING_PROVENANCE = external_knowledge.MAPPING_PROVENANCE
RANKING_POLICY = external_knowledge.RANKING_POLICY
RANKING_POLICY_VERSION = external_knowledge.RANKING_POLICY_VERSION
SUPPORT_METHOD_VERSION = external_knowledge.SUPPORT_METHOD_VERSION
build_support_rows = external_knowledge.build_support_rows
classify_menus = external_knowledge.classify_menus
compile_external_release = external_knowledge.compile_external_release
sha256_payload = external_knowledge.sha256_payload
support_manifest_sha256 = external_knowledge.support_manifest_sha256


def _external_release_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(SCHEMA_SQL)
    timestamp = "2026-08-16T00:00:00+00:00"
    zero_hash = "0" * 64
    connection.execute(
        """
        INSERT INTO catalog_import_batch(
          catalog_import_id,catalog_release_id,data_origin,source_platform,
          source_zip_sha256,source_xlsx_sha256,source_summary_sha256,
          package_sha256,selection_manifest_sha256,selection_algorithm_version,
          collection_location,source_collected_at,selected_merchant_count,
          expected_counts_json,actual_counts_json,diagnostics_json,status,
          started_at,completed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "external-import-test",
            "external-catalog-test-v1",
            "YOGIYO_PUBLIC_WEB",
            "YOGIYO",
            zero_hash,
            zero_hash,
            zero_hash,
            zero_hash,
            zero_hash,
            "test-selection-v1",
            "SEOUL",
            timestamp,
            3,
            "{}",
            "{}",
            "{}",
            "ACTIVE",
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        "INSERT INTO service_area VALUES (?,?,?,?,?)",
        ("area-test", "Seoul", "Jung-gu", "Test area", 1),
    )
    for index in range(3):
        merchant_id = f"merchant-{index}"
        menu_id = f"menu-{index}"
        connection.execute(
            """
            INSERT INTO merchant(
              merchant_id,service_area,service_area_id,name_ko,delivery_fee,
              eta_min,eta_max,min_order_amount,is_synthetic,catalog_import_id,
              data_origin,source_platform
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                merchant_id,
                "Myeongdong",
                "area-test",
                f"식당 {index}",
                0,
                20,
                40,
                10_000,
                0,
                "external-import-test",
                "YOGIYO_PUBLIC_WEB",
                "YOGIYO",
            ),
        )
        connection.execute(
            """
            INSERT INTO menu(
              menu_id,merchant_id,category,name_ko,price,dietary_tags_json,
              allergen_tags_json,semantic_text,availability,is_synthetic,
              updated_at,catalog_import_id,data_origin,source_platform,
              spice_status,dietary_data_status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                menu_id,
                merchant_id,
                "분식",
                "떡볶이",
                12_000,
                "[]",
                "[]",
                "떡볶이",
                "AVAILABLE",
                0,
                timestamp,
                "external-import-test",
                "YOGIYO_PUBLIC_WEB",
                "YOGIYO",
                "UNKNOWN",
                "UNKNOWN",
            ),
        )
        connection.execute(
            """
            INSERT INTO menu_source_detail(
              menu_id,catalog_import_id,liquor,is_adult,verified_adult,soldout,
              thumbnail_json,badges_json,price_json,point_promotions_json,
              operational_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                menu_id,
                "external-import-test",
                0,
                0,
                0,
                0,
                "{}",
                "[]",
                "{}",
                "[]",
                "{}",
            ),
        )
    connection.execute(
        """
        INSERT INTO knowledge_release VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "old-knowledge",
            "old-catalog",
            zero_hash,
            "deterministic-hash",
            1536,
            "v1",
            "READY",
            "{}",
            "{}",
            1,
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        "INSERT INTO knowledge_runtime_state VALUES ('ACTIVE',?,?)",
        ("old-knowledge", timestamp),
    )
    connection.execute(
        """
        INSERT INTO recommendation_release_family(
          release_family_id,knowledge_release_id,catalog_release_id,
          preference_catalog_version,spice_reference_version,
          certification_release_id,embedding_model,embedding_version,
          support_manifest_sha256,ranking_policy_version,ranking_policy_sha256,
          status,activated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "old-family",
            "old-knowledge",
            "old-catalog",
            "old-preference",
            "old-spice",
            "old-certification",
            "deterministic-hash",
            "v1",
            zero_hash,
            "legacy-llm-rank-v2",
            zero_hash,
            "ACTIVE",
            timestamp,
        ),
    )
    connection.execute(
        "INSERT INTO recommendation_runtime_state VALUES ('ACTIVE',?,?)",
        ("old-family", timestamp),
    )
    connection.commit()
    return connection


def _menu(menu_id: str, name: str, category: str, *, price: int = 12_000) -> dict[str, object]:
    return {
        "menu_id": menu_id,
        "merchant_id": f"merchant-{menu_id}",
        "name_ko": name,
        "category": category,
        "price": price,
        "availability": "AVAILABLE",
        "liquor": 0,
        "is_adult": 0,
        "soldout": 0,
    }


def test_external_wiki_compiles_base_and_reviewed_catalog_extensions() -> None:
    compiled = compile_external_release("catalog-test-v1")

    assert compiled.expected_counts["concepts"] == 198
    assert compiled.expected_counts["documents"] == 198
    assert compiled.expected_counts["chunks"] > 1_500
    assert all(row["source_type"] == "SYNTHETIC_WIKI" for row in compiled.documents)
    assert all(row["review_status"] == "REVIEWED_DEMO" for row in compiled.documents)
    assert {row["concept_id"] for row in compiled.concepts} >= {
        "dish_burger",
        "dish_sushi",
        "dish_kimchi_fried_rice",
        "dish_japanese_cuisine",
        "dish_italian_cuisine",
        "dish_american_cuisine",
        "dish_southeast_asian_cuisine",
        "dish_mexican_cuisine",
        "dish_poke",
        "dish_banh_mi",
        "dish_tako_wasabi",
    }


def test_menu_classification_is_total_conservative_and_provenance_explicit() -> None:
    compiled = compile_external_release("catalog-test-v1")
    source = [
        _menu("mapped", "떡볶이", "분식"),
        _menu("new-concept", "햄버거", "버거"),
        _menu("composite", "떡볶이＋김밥 세트", "세트 메뉴"),
        _menu("promotion", "포토 리뷰 이벤트 참여", "이벤트", price=0),
        _menu("unknown", "오늘의 특별식", "메인 메뉴"),
    ]

    rows = classify_menus(source, compiled)
    assert len(rows) == len(source)
    by_id = {row["menu_id"]: row for row in rows}
    assert by_id["mapped"]["concept_id"] == "dish_tteokbokki"
    assert by_id["new-concept"]["concept_id"] == "dish_burger"
    assert by_id["composite"]["unmapped_reason"] == "UNSUPPORTED_COMPOSITE"
    assert by_id["promotion"]["unmapped_reason"] == "NON_FOOD_OR_PROMOTION"
    assert by_id["unknown"]["unmapped_reason"] == "CONCEPT_NOT_AUTHORED"
    assert all(row["source_type"] == MAPPING_PROVENANCE for row in rows)
    assert all(
        row["confidence_band"] == "high"
        for row in rows
        if row["mapping_status"] == "MAPPED"
    )
    assert all(
        row["unmapped_reason"]
        for row in rows
        if row["mapping_status"] == "UNMAPPED"
    )


def test_support_manifest_is_reviewed_grounded_and_deterministic() -> None:
    compiled = compile_external_release("catalog-test-v1")
    first = build_support_rows(compiled)
    second = build_support_rows(compiled)
    supported = {
        (row["concept_id"], row["category_code"], row["option_code"])
        for row in first
    }

    assert first
    assert support_manifest_sha256(first) == support_manifest_sha256(second)
    assert len(support_manifest_sha256(first)) == 64
    assert all(row["support_status"] == "SUPPORTED" for row in first)
    assert all(row["evidence_chunk_id"] for row in first)
    assert all(row["review_status"] == "REVIEWED_DEMO" for row in first)
    assert all(row["support_method_version"] == SUPPORT_METHOD_VERSION for row in first)
    assert ("dish_plain_fried_chicken", "cuisine_origins", "KOREAN") in supported
    assert ("dish_plain_fried_chicken", "main_ingredients", "CHICKEN") in supported
    assert ("dish_plain_fried_chicken", "cooking_methods", "FRIED") in supported
    assert ("dish_tteokbokki", "flavors", "SPICY") in supported
    assert ("dish_sushi", "cuisine_origins", "JAPANESE") in supported
    assert ("dish_pizza", "cuisine_origins", "ITALIAN") in supported
    assert ("dish_burger", "cuisine_origins", "AMERICAN") in supported
    assert ("dish_pho", "cuisine_origins", "SOUTHEAST_ASIAN") in supported
    assert ("dish_taco", "cuisine_origins", "MEXICAN") in supported


def test_ranking_policy_identity_is_versioned_and_sha256_stable() -> None:
    assert RANKING_POLICY["version"] == RANKING_POLICY_VERSION
    assert RANKING_POLICY["eligibility"]["same_category"] == "OR"
    assert RANKING_POLICY["eligibility"]["cross_category"] == "AND"
    assert RANKING_POLICY["eligibility"]["review_required_is_supported"] is False
    assert RANKING_POLICY["diversity"]["relaxation_order"] == ["concept", "merchant"]
    assert len(sha256_payload(RANKING_POLICY)) == 64


def test_external_mapping_golden_sample_is_exact() -> None:
    fixture = json.loads(
        (ROOT / "backend" / "evaluation" / "fixtures" / "external_mapping_golden.json")
        .read_text(encoding="utf-8")
    )
    compiled = compile_external_release("catalog-golden-v1")
    source = [
        {
            **_menu(str(index), row["name_ko"], row["category"], price=row.get("price", 12_000)),
        }
        for index, row in enumerate(fixture)
    ]
    actual = classify_menus(source, compiled)

    for expected, row in zip(fixture, actual, strict=True):
        assert row["concept_id"] == expected.get("expected_concept_id")
        assert row["unmapped_reason"] == expected.get("expected_unmapped_reason")


def test_stage_keeps_both_pointers_then_activation_switches_together(
    tmp_path: Path,
) -> None:
    connection = _external_release_database(tmp_path / "staged.db")
    try:
        before = external_knowledge.runtime_pointers(connection.cursor(), False)

        staged = external_knowledge.stage_plan(connection, False)

        assert staged["active_pointers_unchanged"] is True
        assert staged["activation_performed"] is False
        assert staged["staging_verification"]["pass"] is True
        assert staged["staging_verification"]["preference_option_count"] == 50
        assert staged["staging_verification"]["spice_reference_count"] == 10
        assert connection.execute(
            "SELECT COUNT(*) FROM recommendation_preference_option WHERE catalog_version=?",
            (external_knowledge.PREFERENCE_CATALOG_VERSION,),
        ).fetchone() == (50,)
        assert external_knowledge.runtime_pointers(connection.cursor(), False) == before
        target_status = connection.execute(
            "SELECT status FROM recommendation_release_family WHERE release_family_id=?",
            (staged["release_family_id"],),
        ).fetchone()
        assert target_status == ("READY",)

        activated = external_knowledge.activate_staged_plan(connection, False)

        assert activated["activation_performed"] is True
        assert activated["verification"]["pass"] is True
        assert external_knowledge.runtime_pointers(connection.cursor(), False) == (
            staged["knowledge_release_id"],
            staged["release_family_id"],
        )
    finally:
        connection.close()


def test_stage_verification_failure_rolls_back_and_preserves_pointers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _external_release_database(tmp_path / "stage-failure.db")
    try:
        before = external_knowledge.runtime_pointers(connection.cursor(), False)
        target = external_knowledge.build_plan(connection.cursor())["release_family_id"]
        monkeypatch.setattr(
            external_knowledge,
            "verify_release_family",
            lambda *_args, **_kwargs: {"pass": False, "checks": {"injected": False}},
        )

        with pytest.raises(
            RuntimeError,
            match="EXTERNAL_KNOWLEDGE_STAGING_VERIFICATION_FAILED",
        ):
            external_knowledge.stage_plan(connection, False)

        assert external_knowledge.runtime_pointers(connection.cursor(), False) == before
        assert connection.execute(
            "SELECT COUNT(*) FROM recommendation_release_family WHERE release_family_id=?",
            (target,),
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_activation_transaction_failure_restores_both_data_pointers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _external_release_database(tmp_path / "activation-failure.db")
    try:
        before = external_knowledge.runtime_pointers(connection.cursor(), False)
        staged = external_knowledge.stage_plan(connection, False)
        real_verify = external_knowledge.verify_release_family
        calls = 0

        def injected_verify(*args: object, **kwargs: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 2:
                return {"pass": False, "checks": {"injected": False}}
            return real_verify(*args, **kwargs)

        monkeypatch.setattr(
            external_knowledge,
            "verify_release_family",
            injected_verify,
        )

        with pytest.raises(
            RuntimeError,
            match="ACTIVATION_TRANSACTION_VERIFICATION_FAILED",
        ):
            external_knowledge.activate_staged_plan(connection, False)

        assert external_knowledge.runtime_pointers(connection.cursor(), False) == before
        assert connection.execute(
            "SELECT status FROM recommendation_release_family WHERE release_family_id=?",
            (staged["release_family_id"],),
        ).fetchone() == ("READY",)
        assert connection.execute(
            "SELECT status FROM recommendation_release_family WHERE release_family_id='old-family'"
        ).fetchone() == ("ACTIVE",)
    finally:
        connection.close()


def test_apply_remains_backward_compatible_stage_plus_activate(tmp_path: Path) -> None:
    connection = _external_release_database(tmp_path / "apply-compatible.db")
    try:
        result = external_knowledge.apply_plan(connection, False)

        assert result["activation_performed"] is True
        assert result["staging"]["active_pointers_unchanged"] is True
        assert result["verification"]["pass"] is True
        assert external_knowledge.runtime_pointers(connection.cursor(), False) == (
            result["knowledge_release_id"],
            result["release_family_id"],
        )
    finally:
        connection.close()
