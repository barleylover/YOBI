from pathlib import Path

import pytest

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import ProfileCreate


@pytest.fixture
def repository(tmp_path: Path) -> SQLiteYobiRepository:
    repo = SQLiteYobiRepository(tmp_path / "yobi-test.db")
    repo.initialize()
    return repo


@pytest.fixture
def profile_data() -> ProfileCreate:
    return ProfileCreate(
        consent_demo_data=True,
        dietary_rules=["shellfish_allergy"],
        allergy_severity="severe",
        spice_tolerance=1,
    )

