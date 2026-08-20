from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.build_synthetic_enrichment_release import (
    _apply_sqlite,
    _load_sqlite_inputs,
)

from app.db.sqlite_repository import SQLiteYobiRepository
from app.demo_enrichment import (
    COUNTRY_CODES,
    EnrichmentMenu,
    EnrichmentOption,
    build_enrichment_rows,
    manifest_sha256,
    validate_enrichment_rows,
)


def _menus() -> list[EnrichmentMenu]:
    return [
        EnrichmentMenu("m-pork", "매운 제육 덮밥", ("PORK", "SPICY")),
        EnrichmentMenu("m-veg-1", "산채 비빔밥", ("VEGETABLE", "RICE")),
        EnrichmentMenu("m-veg-2", "두부 샐러드", ("TOFU", "VEGETABLE")),
        EnrichmentMenu("m-veg-3", "버섯 국수", ("MUSHROOM", "NOODLES")),
        EnrichmentMenu("m-veg-4", "채소 김밥", ("VEGETABLE", "RICE")),
        EnrichmentMenu("m-veg-5", "콩국수", ("BEAN", "NOODLES")),
        EnrichmentMenu("m-veg-6", "감자전", ("POTATO", "CRISPY")),
        EnrichmentMenu("m-veg-7", "야채죽", ("VEGETABLE", "SOUP")),
        EnrichmentMenu("m-veg-8", "메밀면", ("NOODLES", "COLD")),
        EnrichmentMenu("m-veg-9", "과일 빙수", ("FRUIT", "FROZEN")),
        EnrichmentMenu("m-veg-10", "단호박죽", ("PUMPKIN", "SOUP")),
        EnrichmentMenu("m-veg-11", "구운 채소", ("VEGETABLE", "GRILLED")),
        EnrichmentMenu("m-veg-12", "토마토 국수", ("TOMATO", "NOODLES")),
        EnrichmentMenu("m-veg-13", "옥수수 샐러드", ("CORN", "VEGETABLE")),
        EnrichmentMenu("m-veg-14", "고구마 맛탕", ("SWEET_POTATO", "SWEET")),
        EnrichmentMenu("m-veg-15", "녹두전", ("BEAN", "CRISPY")),
    ]


def test_enrichment_is_reproducible_and_exact() -> None:
    options = [EnrichmentOption("o-cheese", "m-veg-1", "치즈 추가")]
    first = build_enrichment_rows(
        release_id="release-1", seed="stable-seed", menus=_menus(), options=options
    )
    second = build_enrichment_rows(
        release_id="release-1", seed="stable-seed", menus=reversed(_menus()), options=options
    )

    validate_enrichment_rows(first, eligible_menu_count=len(_menus()))
    assert manifest_sha256(first) == manifest_sha256(second)
    assert len(first["countries"]) == len(COUNTRY_CODES) == 36
    assert len(first["country_examples"]) == 108
    assert len(first["preferences"]) == len(_menus()) * 36
    assert len(first["reviews"]) == len(_menus()) * 6
    assert len(first["localizations"]) == len(_menus())


def test_enrichment_guards_obvious_pork_and_animal_options() -> None:
    rows = build_enrichment_rows(
        release_id="release-1",
        seed="stable-seed",
        menus=_menus(),
        options=[EnrichmentOption("o-cheese", "m-veg-1", "치즈 추가")],
    )
    pork = next(row for row in rows["menus"] if row["menu_id"] == "m-pork")
    assert pork["halal_fit"] == 0
    assert pork["vegan_fit"] == 0
    assert rows["options"][0]["vegan_conflict"] == 1


def test_production_size_coverage_counts_are_exact() -> None:
    menus = [
        EnrichmentMenu(f"wiki-menu-{index:05d}", f"위키 메뉴 {index}", ("VEGETABLE",))
        for index in range(4_558)
    ]
    rows = build_enrichment_rows(
        release_id="release-production-size",
        seed="stable-production-seed",
        menus=menus,
    )

    validate_enrichment_rows(rows, eligible_menu_count=4_558)
    assert len(rows["preferences"]) == 164_088
    assert len(rows["reviews"]) == 27_348
    assert len(rows["localizations"]) * 3 == 13_674


def test_sqlite_release_apply_is_resumable_and_preserves_base_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "enrichment.db"
    SQLiteYobiRepository(database_path).initialize()
    catalog_release_id, knowledge_release_id, menus, options = _load_sqlite_inputs(
        database_path
    )
    with sqlite3.connect(database_path) as connection:
        eligible_ids = {
            str(row[0])
            for row in connection.execute(
                "SELECT menu_id FROM menu_wiki_eligibility WHERE knowledge_release_id=?",
                (knowledge_release_id,),
            )
        }
    assert {menu.menu_id for menu in menus} == eligible_ids
    rows = build_enrichment_rows(
        release_id="release-resumable",
        seed="stable-seed",
        menus=menus,
        options=options,
    )
    manifest = manifest_sha256(rows)

    first = _apply_sqlite(
        database_path,
        release_id="release-resumable",
        catalog_release_id=catalog_release_id,
        knowledge_release_id=knowledge_release_id,
        seed="stable-seed",
        rows=rows,
        manifest=manifest,
        activate=False,
    )
    second = _apply_sqlite(
        database_path,
        release_id="release-resumable",
        catalog_release_id=catalog_release_id,
        knowledge_release_id=knowledge_release_id,
        seed="stable-seed",
        rows=rows,
        manifest=manifest,
        activate=False,
    )

    assert first[0] == first[1] == second[0] == second[1]
    with sqlite3.connect(database_path) as connection:
        counts = {
            table: int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE release_id=?",  # noqa: S608
                    ("release-resumable",),
                ).fetchone()[0]
            )
            for table in (
                "synthetic_menu_profile",
                "synthetic_menu_country_preference",
                "synthetic_review_snippet",
            )
        }
    assert counts == {
        "synthetic_menu_profile": len(menus),
        "synthetic_menu_country_preference": len(menus) * 36,
        "synthetic_review_snippet": len(menus) * 6,
    }

    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO menu_localization(
              release_id,menu_id,language_code,display_name,model_id,prompt_version,
              wiki_evidence_ids_json,source_hash,validation_status,generated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    "release-resumable",
                    menu.menu_id,
                    language_code,
                    menu.name_ko,
                    "TEST_FIXTURE",
                    "test-only",
                    "[]",
                    "a" * 64,
                    "VALID",
                    "2026-08-20T00:00:00+00:00",
                )
                for menu in menus
                for language_code in ("en", "ja")
            ],
        )

    _apply_sqlite(
        database_path,
        release_id="release-resumable",
        catalog_release_id=catalog_release_id,
        knowledge_release_id=knowledge_release_id,
        seed="stable-seed",
        rows=rows,
        manifest=manifest,
        activate=True,
    )
    with sqlite3.connect(database_path) as connection:
        active_before_restart = str(
            connection.execute(
                "SELECT active_release_family_id FROM recommendation_runtime_state "
                "WHERE state_key='ACTIVE'"
            ).fetchone()[0]
        )

    SQLiteYobiRepository(database_path).initialize()

    with sqlite3.connect(database_path) as connection:
        active_after_restart = str(
            connection.execute(
                "SELECT active_release_family_id FROM recommendation_runtime_state "
                "WHERE state_key='ACTIVE'"
            ).fetchone()[0]
        )
        active_enrichment = str(
            connection.execute(
                "SELECT synthetic_enrichment_release_id FROM recommendation_release_family "
                "WHERE release_family_id=?",
                (active_after_restart,),
            ).fetchone()[0]
        )

    assert active_after_restart == active_before_restart
    assert active_enrichment == "release-resumable"
