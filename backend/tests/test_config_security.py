import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_only_verified_oci_genai_path_is_allowed() -> None:
    with pytest.raises(ValidationError):
        Settings(oci_genai_base_url="https://example.invalid/openai/v1")


def test_admin_runtime_user_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(db_username="ADMIN")


def test_project_parameter_is_not_part_of_runtime_settings() -> None:
    fields = Settings.model_fields
    assert "project" not in fields
    assert "oci_genai_project" not in fields


def test_uppercase_systemd_environment_names_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_DB_BACKEND", "oracle")
    monkeypatch.setenv("DB_USERNAME", "YOBI_APP")
    settings = Settings(_env_file=None)
    assert settings.demo_db_backend == "oracle"
    assert settings.db_username == "YOBI_APP"
