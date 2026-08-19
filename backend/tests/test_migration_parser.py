from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("yobi_migrate", ROOT / "scripts" / "migrate.py")
assert SPEC and SPEC.loader
migrate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrate)


def test_split_statements_preserves_plsql_terminator() -> None:
    sql = (
        "SELECT 1 FROM dual;\n-- +YOBI STATEMENT\n"
        "-- leading migration rationale\nBEGIN\n  NULL;\nEND;"
    )

    statements = migrate.split_statements(sql)

    assert statements[0] == "SELECT 1 FROM dual"
    assert statements[1].endswith("END;")


def test_wiki_eligibility_migration_preserves_every_plsql_terminator() -> None:
    path = ROOT / "database" / "migrations" / "014_wiki_eligibility_indexes.sql"
    statements = migrate.split_statements(path.read_text(encoding="utf-8"))

    assert len(statements) == 7
    assert all(
        statement.endswith("END;")
        for statement in statements
        if "BEGIN" in statement and "EXECUTE IMMEDIATE" in statement
    )


def test_three_level_spice_migration_is_append_only_and_parseable() -> None:
    path = ROOT / "database" / "migrations" / "004_three_level_spice.sql"
    statements = migrate.split_statements(path.read_text(encoding="utf-8"))

    assert len(statements) == 8
    assert any(
        statement.startswith("BEGIN") and statement.endswith("END;") for statement in statements
    )
    assert any("chk_menu_spice_3" in statement for statement in statements)


def test_release_discovers_conversation_and_knowledge_migrations() -> None:
    migrations = migrate.discover_migrations()
    names = [migration.path.name for migration in migrations]

    assert names == sorted(names)
    assert "005_conversation_state.sql" in names
    assert "006_knowledge_graph.sql" in names
    assert "007_service_area_and_mutation_idempotency.sql" in names
    assert "008_checkout_cart_version.sql" in names
    assert "009_cart_confirmation_fingerprint.sql" in names
    assert "010_structured_hybrid_rag_recommendation.sql" in names
    assert "011_external_catalog_import.sql" in names
    assert "012_concept_preference_support_and_server_ranking.sql" in names
    assert "013_menu_preference_features_and_hybrid_rank.sql" in names
    assert "014_wiki_eligibility_indexes.sql" in names


def test_conversation_migration_is_append_only_and_partial_rerun_safe() -> None:
    path = ROOT / "database" / "migrations" / "005_conversation_state.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP TABLE" not in source.upper()
    assert len(statements) == 7
    assert all(
        statement.startswith("BEGIN") and statement.endswith("END;") for statement in statements
    )
    assert all(
        "SQLCODE != -1430" in statement or "SQLCODE != -955" in statement
        for statement in statements
    )


def test_knowledge_graph_migration_uses_collision_free_oracle_quoting() -> None:
    path = ROOT / "database" / "migrations" / "006_knowledge_graph.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP TABLE" not in source.upper()
    quoted_statements = [statement for statement in statements if "EXECUTE IMMEDIATE q'" in statement]

    assert len(statements) == 15
    assert len(quoted_statements) == 12
    assert "q'[" not in source
    assert all(
        statement.startswith("BEGIN") and statement.endswith("END;")
        for statement in statements
    )
    assert all(statement.count("q'^") == 1 for statement in quoted_statements)
    assert all(statement.count("^'") == 1 for statement in quoted_statements)
    assert all("SQLCODE != -955" in statement for statement in statements)


def test_ledger_drift_is_rejected_before_pending_migrations() -> None:
    migrations = migrate.discover_migrations()
    first = migrations[0]
    drifted = first._replace(checksum="0" * 64)
    ledger = {first.version: (first.path.name, first.checksum)}

    with pytest.raises(RuntimeError, match="MIGRATION_CHECKSUM_MISMATCH"):
        migrate.validate_migration_ledger([drifted, *migrations[1:]], ledger)


def test_service_area_migration_is_append_only_and_partial_rerun_safe() -> None:
    path = ROOT / "database" / "migrations" / "007_service_area_and_mutation_idempotency.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP TABLE" not in source.upper()
    assert len(statements) == 6
    assert all(
        statement.startswith("BEGIN") and statement.endswith("END;") for statement in statements
    )
    assert all(
        "SQLCODE != -1430" in statement or "SQLCODE != -955" in statement
        for statement in statements
    )


def test_checkout_cart_version_migration_is_append_only_and_partial_rerun_safe() -> None:
    path = ROOT / "database" / "migrations" / "008_checkout_cart_version.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP TABLE" not in source.upper()
    assert len(statements) == 3
    assert all(
        statement.startswith("BEGIN") and statement.endswith("END;") for statement in statements
    )
    assert all(
        "SQLCODE != -1430" in statement or "SQLCODE != -955" in statement
        for statement in statements
    )


def test_cart_confirmation_fingerprint_migration_is_append_only_and_rerun_safe() -> None:
    path = ROOT / "database" / "migrations" / "009_cart_confirmation_fingerprint.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP TABLE" not in source.upper()
    assert len(statements) == 1
    assert statements[0].startswith("BEGIN") and statements[0].endswith("END;")
    assert "SQLCODE != -1430" in statements[0]


def test_structured_hybrid_rag_migration_is_append_only_and_rerun_safe() -> None:
    path = ROOT / "database" / "migrations" / "010_structured_hybrid_rag_recommendation.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP TABLE" not in source.upper()
    # Snapshot audit columns are deliberately added one at a time so a partially
    # applied migration can be rerun without silently leaving columns missing.
    assert len(statements) == 24
    assert all(
        statement.startswith("BEGIN") and statement.endswith("END;") for statement in statements
    )
    assert "structured_recommendation_request" in source
    assert "recommendation_release_family" in source
    assert "merchant_certification" in source
    assert "request_mode VARCHAR2(16)" in source
    assert "\n      mode VARCHAR2(16)" not in source
    assert "generation_call_count BETWEEN 0 AND 1" in source
    assert all(
        "SQLCODE != -955" in statement
        or "SQLCODE != -1430" in statement
        or "SQLCODE != -2264" in statement
        for statement in statements[1:]
    )


def test_external_catalog_migration_is_additive_and_rerun_safe() -> None:
    path = ROOT / "database" / "migrations" / "011_external_catalog_import.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP TABLE" not in source.upper()
    assert len(statements) == 39
    assert all(
        statement.startswith("BEGIN") and statement.endswith("END;")
        for statement in statements
    )
    assert "catalog_import_batch" in source
    assert "catalog_source_payload" in source
    assert "REQUIRED_SINGLE_SELECT_ZERO_LIMIT" not in source
    assert "idx_option_item_group" in source


def test_menu_feature_hybrid_rank_migration_is_additive_and_rerun_safe() -> None:
    path = (
        ROOT
        / "database"
        / "migrations"
        / "013_menu_preference_features_and_hybrid_rank.sql"
    )
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP TABLE" not in source.upper()
    assert len(statements) == 10
    assert all(
        statement.startswith("BEGIN") and statement.endswith("END;")
        for statement in statements
    )
    assert "menu_preference_feature" in source
    assert "menu_preference_feature_evidence" in source
    assert "menu_concept_membership" in source
    assert source.count("feature_manifest_sha256") >= 3
    assert all(
        "SQLCODE != -955" in statement or "SQLCODE != -1430" in statement
        for statement in statements
    )


def test_wiki_eligibility_index_migration_is_additive_and_rerun_safe() -> None:
    path = ROOT / "database" / "migrations" / "014_wiki_eligibility_indexes.sql"
    source = path.read_text(encoding="utf-8")
    statements = migrate.split_statements(source)

    assert "DROP " not in source.upper()
    assert len(statements) == 7
    assert "CREATE TABLE menu_wiki_eligibility" in source
    assert "CREATE TABLE menu_semantic_embedding" in source
    assert "LEFT JOIN menu_wiki_eligibility existing" in source
    assert "idx_dish_closure_ancestor" in source
    assert "idx_menu_concept_membership_concept" in source
    assert "idx_menu_wiki_eligibility_menu" in source
    assert all(
        "SQLCODE != -955" in statement
        for index, statement in enumerate(statements)
        if index != 2
    )


def test_discovery_rejects_a_missing_migration_version(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").write_text("SELECT 1 FROM dual;", encoding="utf-8")
    (tmp_path / "003_gap.sql").write_text("SELECT 3 FROM dual;", encoding="utf-8")

    with pytest.raises(RuntimeError, match="NON_SEQUENTIAL_MIGRATION_SET"):
        migrate.discover_migrations(tmp_path)
