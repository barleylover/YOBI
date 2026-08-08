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
        "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com/20231130/actions/v1"
    )
    oci_genai_region: str = "us-chicago-1"
    oci_genai_api_key: SecretStr = SecretStr("")
    oci_genai_model: str = "xai.grok-4.3"
    oci_genai_fallback_model: str = "openai.gpt-oss-120b"
    genai_provider: Literal["oci"] = "oci"
    oci_genai_serving_mode: Literal["on_demand", "dedicated"] = "on_demand"
    oci_genai_endpoint_id: str = ""
    oci_genai_fallback_endpoint_id: str = ""
    oci_genai_structured_output_enabled: bool = False
    oci_genai_streaming_enabled: bool = False
    genai_prompt_profile: Literal["yobi-grounded-v1"] = "yobi-grounded-v1"
    oci_embed_model: str = "cohere.embed-v4.0"
    oci_embed_dimension: int = 1536
    oci_compartment_id: SecretStr = SecretStr("")

    adb_dsn: SecretStr = SecretStr("")
    db_username: str = "YOBI_APP"
    db_password: SecretStr = SecretStr("")

    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    llm_retry_base_seconds: float = Field(default=0.25, ge=0.0, le=5.0)
    llm_retry_max_seconds: float = Field(default=2.0, ge=0.0, le=10.0)
    llm_max_concurrent_requests: int = Field(default=4, ge=1, le=32)
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
