from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from app.db.schema_sqlite import SCHEMA_SQL
from app.knowledge.authoring import EMBEDDING_DIMENSION, CompiledKnowledgeRelease, compile_directory
from app.knowledge.catalog_seed import CATEGORY_CONCEPT_MAP, build_knowledge_catalog_seed
from app.knowledge.sqlite_store import load_sqlite_release, search_sqlite_chunks

ROOT = Path(__file__).parents[2]
GOLDEN_ROOT = ROOT / "knowledge" / "dishes"
HIERARCHY_CONCEPT_IDS = {
    "dish_korean_cuisine",
    "dish_korean_chinese_cuisine",
    "dish_kalguksu",
    "dish_tuna_gimbap",
    "dish_cheese_gimbap",
    "dish_tray_jjajang",
    "dish_seasoned_fried_chicken",
    "dish_pork_gukbap",
    "dish_vegetable_bibimbap",
}


def _compile_golden():
    return compile_directory(
        GOLDEN_ROOT,
        release_id="knowledge-demo-2026.08.09-v1",
        catalog_version="demo-authoring-golden-v1",
    )


def _knowledge_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA_SQL)
    catalog = build_knowledge_catalog_seed([])
    connection.executemany(
        "INSERT INTO ingredient(ingredient_id,name_ko,name_en,ingredient_group) VALUES (?,?,?,?)",
        [tuple(row.values()) for row in catalog.ingredients],
    )
    connection.executemany(
        "INSERT INTO allergen(allergen_id,code,name_en,name_ko) VALUES (?,?,?,?)",
        [tuple(row.values()) for row in catalog.allergens],
    )
    connection.commit()
    return connection


def test_golden_wiki_compiles_to_stable_release_manifest() -> None:
    first = _compile_golden()
    second = _compile_golden()

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.expected_counts == {
        "concepts": 29,
        "relations": 27,
        "closure": 66,
        "claims": 411,
        "documents": 29,
        "chunks": 261,
    }
    assert {row["concept_id"] for row in first.concepts} == (
        set(CATEGORY_CONCEPT_MAP.values()) | HIERARCHY_CONCEPT_IDS
    )
    rose_ancestors = {
        (row["ancestor_concept_id"], row["depth"], row["inherit_claims"])
        for row in first.closure
        if row["descendant_concept_id"] == "dish_rose_tteokbokki"
    }
    assert rose_ancestors == {
        ("dish_rose_tteokbokki", 0, 1),
        ("dish_tteokbokki", 1, 1),
        ("dish_korean_cuisine", 2, 0),
    }
    relations = {
        (
            row["source_concept_id"],
            row["target_concept_id"],
            row["relation_type"],
            row["inherit_claims"],
        )
        for row in first.relations
    }
    assert {
        ("dish_korean_chinese_cuisine", "dish_korean_cuisine", "IS_A", 0),
        ("dish_kalguksu", "dish_korean_cuisine", "IS_A", 0),
        ("dish_chicken_kalguksu", "dish_kalguksu", "VARIANT_OF", 1),
        ("dish_tuna_gimbap", "dish_gimbap", "VARIANT_OF", 1),
        ("dish_cheese_gimbap", "dish_gimbap", "VARIANT_OF", 1),
        ("dish_tray_jjajang", "dish_jjajangmyeon", "VARIANT_OF", 1),
        (
            "dish_seasoned_fried_chicken",
            "dish_korean_fried_chicken",
            "VARIANT_OF",
            1,
        ),
        ("dish_pork_gukbap", "dish_gukbap", "VARIANT_OF", 1),
        ("dish_vegetable_bibimbap", "dish_bibimbap", "VARIANT_OF", 1),
    } <= relations
    assert all(len(row["embedding_vector_json"]) > EMBEDDING_DIMENSION for row in first.chunks)


def test_golden_authoring_load_and_search_round_trip() -> None:
    compiled = _compile_golden()
    connection = _knowledge_connection()
    try:
        load_sqlite_release(connection, compiled)
        load_sqlite_release(connection, compiled)

        release = connection.execute(
            "SELECT status,manifest_sha256 FROM knowledge_release WHERE release_id=?",
            (compiled.release_id,),
        ).fetchone()
        assert release == ("READY", compiled.manifest_sha256)
        assert (
            connection.execute("SELECT COUNT(*) FROM knowledge_chunk").fetchone()[0]
            == compiled.expected_counts["chunks"]
        )

        results = search_sqlite_chunks(
            connection, "creamy dairy rose sauce with chewy rice cakes", limit=5
        )
        assert results
        assert any(item.concept_id == "dish_rose_tteokbokki" for item in results[:3])
        assert all(item.score <= 1.0 for item in results)
    finally:
        connection.close()


def test_sqlite_release_id_collision_does_not_replace_active_release() -> None:
    compiled = _compile_golden()
    collision = compiled.model_copy(update={"manifest_sha256": "0" * 64})
    connection = _knowledge_connection()
    try:
        load_sqlite_release(connection, compiled)
        with pytest.raises(RuntimeError, match="KNOWLEDGE_RELEASE_ID_COLLISION"):
            load_sqlite_release(connection, collision)

        active = connection.execute(
            "SELECT active_release_id FROM knowledge_runtime_state WHERE state_key='ACTIVE'"
        ).fetchone()
        stored = connection.execute(
            "SELECT manifest_sha256,status FROM knowledge_release WHERE release_id=?",
            (compiled.release_id,),
        ).fetchone()
        assert active == (compiled.release_id,)
        assert stored == (compiled.manifest_sha256, "READY")
    finally:
        connection.close()


def test_sqlite_failed_new_release_keeps_previous_active_release() -> None:
    compiled = _compile_golden()
    incomplete = CompiledKnowledgeRelease(
        release_id="knowledge-demo-deadbeefdeadbeefdeadbeef",
        catalog_version="test-incomplete-v1",
        manifest_sha256="f" * 64,
        expected_counts={
            "concepts": 1,
            "relations": 0,
            "closure": 0,
            "claims": 0,
            "documents": 0,
            "chunks": 0,
        },
        concepts=[],
        relations=[],
        closure=[],
        claims=[],
        documents=[],
        chunks=[],
    )
    connection = _knowledge_connection()
    try:
        load_sqlite_release(connection, compiled)
        with pytest.raises(RuntimeError, match="KNOWLEDGE_RELEASE_COUNT_MISMATCH"):
            load_sqlite_release(connection, incomplete)

        active = connection.execute(
            "SELECT active_release_id FROM knowledge_runtime_state WHERE state_key='ACTIVE'"
        ).fetchone()
        failed = connection.execute(
            "SELECT status FROM knowledge_release WHERE release_id=?",
            (incomplete.release_id,),
        ).fetchone()
        assert active == (compiled.release_id,)
        assert failed is None
    finally:
        connection.close()


def test_dangling_parent_is_rejected(tmp_path: Path) -> None:
    source = GOLDEN_ROOT / "korean" / "tteokbokki" / "rose-tteokbokki.md"
    (tmp_path / "rose.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="DANGLING_PARENT"):
        compile_directory(tmp_path, release_id="test-dangling-v1", catalog_version="test")


def test_cycle_and_duplicate_concepts_are_rejected(tmp_path: Path) -> None:
    family_text = (GOLDEN_ROOT / "korean" / "tteokbokki" / "tteokbokki.md").read_text(
        encoding="utf-8"
    )
    variant_text = (GOLDEN_ROOT / "korean" / "tteokbokki" / "rose-tteokbokki.md").read_text(
        encoding="utf-8"
    )
    family_with_parent = family_text.replace(
        '"concept_id": "dish_korean_cuisine"',
        '"concept_id": "dish_rose_tteokbokki"',
        1,
    )
    cycle_root = tmp_path / "cycle"
    cycle_root.mkdir()
    (cycle_root / "family.md").write_text(family_with_parent, encoding="utf-8")
    (cycle_root / "variant.md").write_text(variant_text, encoding="utf-8")
    with pytest.raises(ValueError, match="CONCEPT_CYCLE"):
        compile_directory(cycle_root, release_id="test-cycle-v1", catalog_version="test")

    duplicate_root = tmp_path / "duplicate"
    duplicate_root.mkdir()
    (duplicate_root / "one.md").write_text(family_text, encoding="utf-8")
    (duplicate_root / "two.md").write_text(family_text, encoding="utf-8")
    with pytest.raises(ValueError, match="DUPLICATE_CONCEPT_ID"):
        compile_directory(duplicate_root, release_id="test-duplicate-v1", catalog_version="test")


def test_wiki_core_claim_cannot_be_downgraded_to_possible(tmp_path: Path) -> None:
    source = GOLDEN_ROOT / "korean" / "tteokbokki" / "tteokbokki.md"
    invalid = source.read_text(encoding="utf-8").replace(
        '"status": "PRESUMED_PRESENT"', '"status": "POSSIBLE"', 1
    )
    (tmp_path / "invalid.md").write_text(invalid, encoding="utf-8")

    with pytest.raises(ValueError, match="DEFINING and CORE"):
        compile_directory(tmp_path, release_id="test-invalid-core-v1", catalog_version="test")


def test_oracle_knowledge_migration_is_append_only_parseable_and_rerun_safe() -> None:
    spec = importlib.util.spec_from_file_location(
        "yobi_migrate_knowledge", ROOT / "scripts/migrate.py"
    )
    assert spec and spec.loader
    migrate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = migrate
    spec.loader.exec_module(migrate)
    path = ROOT / "database" / "migrations" / "006_knowledge_graph.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert len(statements) == 15
    assert "DROP TABLE" not in source.upper()
    assert all(
        statement.startswith("BEGIN") and statement.endswith("END;") for statement in statements
    )
    assert all("SQLCODE != -955" in statement for statement in statements)
