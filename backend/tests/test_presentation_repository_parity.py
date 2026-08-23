from __future__ import annotations

import inspect

import pytest

from app.db.oracle_repository import OracleYobiRepository
from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.presentation_localization import persistable_menu_localization_fields


@pytest.mark.parametrize(
    ("title", "description", "expected_title", "expected_description"),
    [
        (
            "Spicy rice cakes",
            "Coca-Cola 355ml, two sets.",
            "Spicy rice cakes",
            "Coca-Cola 355ml, two sets.",
        ),
        ("Spicy rice cakes", "", "Spicy rice cakes", None),
        ("Spicy rice cakes", "One Coca-Cola 355ml set.", "Spicy rice cakes", None),
        ("Spicy rice cakes", "Two 355ml sets.", "Spicy rice cakes", None),
        ("Korean menu", "Coca-Cola 355ml, two sets.", None, "Coca-Cola 355ml, two sets."),
    ],
)
def test_field_level_persistence_decision_is_independent(
    title: str,
    description: str,
    expected_title: str | None,
    expected_description: str | None,
) -> None:
    assert persistable_menu_localization_fields(
        source_description="Coca-Cola 355ml 2세트",
        language_code="en",
        localized_title=title,
        localized_source_description=description,
    ) == (expected_title, expected_description)


def test_sqlite_and_oracle_use_the_same_persistence_gate() -> None:
    for repository_type in (SQLiteYobiRepository, OracleYobiRepository):
        source = inspect.getsource(repository_type.save_menu_runtime_localizations)
        assert "persistable_menu_localization_fields" in source
        assert "if title_value" in source
        assert "if description_value" in source
