from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db.sqlite_repository import SQLiteYobiRepository
from app.domain.models import ProfileCreate
from app.genai.admission import SharedModelAdmissionController


@pytest.fixture(autouse=True)
def reset_shared_model_admission_between_tests() -> Iterator[None]:
    """Keep process-wide model cooldowns from leaking across isolated tests."""

    SharedModelAdmissionController.reset_for_tests()
    yield
    SharedModelAdmissionController.reset_for_tests()


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
