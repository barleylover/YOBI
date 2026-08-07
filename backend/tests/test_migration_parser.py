from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("yobi_migrate", ROOT / "scripts" / "migrate.py")
assert SPEC and SPEC.loader
migrate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrate)


def test_split_statements_preserves_plsql_terminator() -> None:
    sql = "SELECT 1 FROM dual;\n-- +YOBI STATEMENT\nBEGIN\n  NULL;\nEND;"

    statements = migrate.split_statements(sql)

    assert statements[0] == "SELECT 1 FROM dual"
    assert statements[1].endswith("END;")


def test_three_level_spice_migration_is_append_only_and_parseable() -> None:
    path = ROOT / "database" / "migrations" / "004_three_level_spice.sql"
    statements = migrate.split_statements(path.read_text(encoding="utf-8"))

    assert len(statements) == 8
    assert any(statement.startswith("BEGIN") and statement.endswith("END;") for statement in statements)
    assert any("chk_menu_spice_3" in statement for statement in statements)
