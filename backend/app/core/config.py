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
    structured_recommendation_model: str = "xai.grok-4.3"
    structured_recommendation_max_output_tokens: int = Field(default=2048, ge=64)
    structured_recommendation_max_concurrent_requests: int = Field(
        default=2, ge=1, le=8
    )
    genai_provider: Literal["oci"] = "oci"
    oci_genai_serving_mode: Literal["on_demand", "dedicated"] = "on_demand"
    oci_genai_endpoint_id: str = ""
    oci_genai_fallback_endpoint_id: str = ""
    oci_genai_structured_output_enabled: bool = False
    oci_genai_streaming_enabled: bool = False
    # Explicit provider contract profile. These are the request envelope that the
    # configured OCI model/endpoint is expected to support, not advertised model
    # headline limits. Operators must lower them for a more restrictive endpoint.
    oci_genai_max_input_tokens: int = Field(default=131072, ge=512)
    oci_genai_max_output_tokens: int = Field(default=4096, ge=64)
    oci_genai_max_tools_per_request: int = Field(default=4, ge=1, le=14)
    oci_genai_max_tool_calls_per_response: int = Field(default=4, ge=1, le=14)
    genai_prompt_profile: Literal["yobi-grounded-v1"] = "yobi-grounded-v1"
    oci_embed_model: str = "cohere.embed-v4.0"
    oci_embed_dimension: int = 1536
    embedding_provider: Literal["deterministic", "oci", "auto"] = "deterministic"
    oci_compartment_id: SecretStr = SecretStr("")

    adb_dsn: SecretStr = SecretStr("")
    db_username: str = "YOBI_APP"
    db_password: SecretStr = SecretStr("")

    llm_timeout_seconds: float = Field(default=120.0, gt=0.0, le=300.0)
    llm_max_retries: int = Field(default=0, ge=0, le=3)
    llm_retry_base_seconds: float = Field(default=0.25, ge=0.0, le=5.0)
    llm_retry_max_seconds: float = Field(default=2.0, ge=0.0, le=10.0)
    llm_max_concurrent_requests: int = Field(default=4, ge=1, le=32)
    llm_max_input_tokens: int = Field(default=131072, ge=512)
    llm_max_output_tokens: int = Field(default=4096, ge=64)
    llm_max_tools_per_request: int = Field(default=4, ge=1, le=14)
    llm_max_tool_calls_per_response: int = Field(default=4, ge=1, le=14)
    tool_call_max_steps: int = Field(default=6, ge=1, le=12)
    recommendation_prompt_version: str = "yobi-structured-rag-v2"
    recommendation_raw_hits_per_value: int = Field(default=20, ge=4, le=100)
    recommendation_evidence_pool_limit: int = Field(default=24, ge=6, le=60)
    recommendation_candidate_limit: int = Field(default=100, ge=15, le=100)
    recommendation_llm_shortlist_limit: int = Field(default=15, ge=3, le=15)
    recommendation_llm_passages_per_menu: int = Field(default=2, ge=1, le=4)
    recommendation_llm_selection_enabled: bool = True
    recommendation_passages_per_menu: int = Field(default=4, ge=1, le=8)
    recommendation_result_limit: int = Field(default=3, ge=1, le=5)
    recommendation_request_orphan_seconds: int = Field(default=180, ge=30, le=3600)
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
