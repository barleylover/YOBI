from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_base_url: str = "http://127.0.0.1:5173"
    demo_mode: bool = True
    demo_fallback_enabled: bool = True
    demo_db_backend: Literal["sqlite", "oracle"] = "sqlite"
    sqlite_path: Path = Path("backend/data/yobi_demo.db")

    oci_genai_base_url: str = (
        "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/"
        "20231130/actions/v1"
    )
    oci_genai_api_key: SecretStr = SecretStr("")
    oci_genai_model: str = "xai.grok-4.3"
    oci_genai_fallback_model: str = "openai.gpt-oss-120b"
    oci_embed_model: str = "cohere.embed-v4.0"
    oci_embed_dimension: int = 1536
    oci_compartment_id: SecretStr = SecretStr("")

    adb_dsn: SecretStr = SecretStr("")
    db_username: str = "YOBI_APP"
    db_password: SecretStr = SecretStr("")

    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 0
    tool_call_max_steps: int = 6
    max_upload_mb: int = 8
    address_ocr_provider: Literal["fixture", "tesseract", "rapidocr"] = "tesseract"
    log_level: str = "INFO"
    demo_control_token: SecretStr = SecretStr("")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173"])

    @field_validator("oci_genai_base_url")
    @classmethod
    def require_verified_genai_path(cls, value: str) -> str:
        if not value.rstrip("/").endswith("/20231130/actions/v1"):
            raise ValueError("OCI GenAI base URL must use the verified /20231130/actions/v1 path")
        return value.rstrip("/")

    @field_validator("db_username")
    @classmethod
    def reject_admin_runtime(cls, value: str) -> str:
        if value.upper() == "ADMIN":
            raise ValueError("ADMIN is not allowed as the YOBI runtime database user")
        return value

    @field_validator("oci_embed_dimension")
    @classmethod
    def require_supported_embedding_dimension(cls, value: int) -> int:
        if value != 1536:
            raise ValueError("YOBI migrations and seed data are fixed to 1536 dimensions")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
