from __future__ import annotations

from openai import OpenAI

from app.core.config import Settings


class OciGenAIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: OpenAI | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.oci_genai_api_key.get_secret_value())

    def build(self) -> OpenAI:
        if not self.configured:
            raise RuntimeError("OCI_GENAI_NOT_CONFIGURED")
        if self._client is None:
            self._client = OpenAI(
                base_url=self.settings.oci_genai_base_url,
                api_key=self.settings.oci_genai_api_key.get_secret_value(),
                timeout=self.settings.llm_timeout_seconds,
                # AgentLoop owns the single bounded retry/backoff policy. Keeping the
                # SDK retry disabled prevents multiplicative attempts and latency.
                max_retries=0,
            )
        return self._client
