#!/usr/bin/env python3
from __future__ import annotations

import sys
import time
from pathlib import Path

from openai import APIError, APIStatusError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings
from app.genai.client import OciGenAIClient
from app.genai.rate_limit import call_with_rate_limit_retry


def main() -> None:
    settings = Settings()
    client = OciGenAIClient(settings).build()

    def notice(delay: float, attempt: int, maximum: int) -> None:
        print(
            f"OCI fallback-model rate limit; retrying in {delay:.1f}s "
            f"({attempt}/{maximum}).",
            file=sys.stderr,
            flush=True,
        )

    response = call_with_rate_limit_retry(
        client.responses.create,
        model=settings.oci_genai_fallback_model,
        input="Reply with exactly this text and nothing else: YOBI_FALLBACK_MODEL_OK",
        max_retries=2,
        sleep=time.sleep,
        on_retry=notice,
    )
    if response.output_text.strip() != "YOBI_FALLBACK_MODEL_OK":
        raise SystemExit("Fallback-model smoke did not match the expected sentinel")
    print("PASS: OCI GPT-OSS fallback model response")


def safe_main() -> None:
    try:
        main()
    except APIError as exc:
        status_code = exc.status_code if isinstance(exc, APIStatusError) else None
        code = "RATE_LIMIT" if status_code == 429 else f"HTTP_{status_code or 'ERROR'}"
        raise SystemExit(f"Fallback-model smoke failed safely: {code}") from None
    except RuntimeError as exc:
        code = str(exc) if str(exc).startswith("GENAI_") else "GENAI_RUNTIME_ERROR"
        raise SystemExit(f"Fallback-model smoke failed safely: {code}") from None


if __name__ == "__main__":
    safe_main()
