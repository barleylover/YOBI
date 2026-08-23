from __future__ import annotations

import base64
import hashlib
import hmac
import json
import shutil
import subprocess
import time
from io import BytesIO
from typing import Any, Protocol

from PIL import Image, ImageOps

from app.core.config import Settings
from app.db.repository import YobiRepository
from app.domain.models import AddressCandidate


class AddressOcrAdapter(Protocol):
    def extract_text(self, image_bytes: bytes) -> str: ...

    def parse_booking_fields(self, text: str) -> str: ...

    def resolve_place_candidates(
        self,
        repository: YobiRepository,
        parsed_text: str,
        file_hash: str,
    ) -> list[AddressCandidate]: ...


class FixtureAddressOcrAdapter:
    """Deterministic fallback; resolution is grounded by the seeded fixture hash."""

    def extract_text(self, image_bytes: bytes) -> str:
        return ""

    def parse_booking_fields(self, text: str) -> str:
        return " ".join(text.split())[:4_000]

    def resolve_place_candidates(
        self,
        repository: YobiRepository,
        parsed_text: str,
        file_hash: str,
    ) -> list[AddressCandidate]:
        return repository.resolve_address(parsed_text, file_hash)


class TesseractAddressOcrAdapter(FixtureAddressOcrAdapter):
    """CPU-only OCR adapter. Image metadata is stripped before the subprocess call."""

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        executable = shutil.which("tesseract")
        if executable is None:
            raise RuntimeError("ADDRESS_OCR_PROVIDER_UNAVAILABLE")
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def extract_text(self, image_bytes: bytes) -> str:
        with Image.open(BytesIO(image_bytes)) as source:
            sanitized = ImageOps.exif_transpose(source).convert("RGB")
            buffer = BytesIO()
            sanitized.save(buffer, format="PNG", optimize=True)
        try:
            completed = subprocess.run(
                [self.executable, "stdin", "stdout", "-l", "eng+kor", "--psm", "6"],
                input=buffer.getvalue(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("ADDRESS_OCR_TIMEOUT") from exc
        if completed.returncode != 0:
            raise RuntimeError("ADDRESS_OCR_FAILED")
        return completed.stdout.decode("utf-8", errors="replace")[:4_000]


def choose_address_ocr(settings: Settings) -> AddressOcrAdapter:
    if settings.address_ocr_provider == "tesseract":
        try:
            return TesseractAddressOcrAdapter()
        except RuntimeError:
            if not settings.demo_fallback_enabled:
                raise
    return FixtureAddressOcrAdapter()


class AddressCandidateTokenCodec:
    """Short-lived signed candidate references; no user-supplied catalog fields are trusted."""

    def __init__(self, settings: Settings) -> None:
        secret = settings.demo_control_token.get_secret_value()
        if not secret:
            if settings.app_env == "production":
                raise RuntimeError("ADDRESS_CANDIDATE_SIGNING_KEY_MISSING")
            secret = f"yobi-development-only:{settings.app_base_url}"
        self._key = hashlib.sha256(secret.encode()).digest()

    def encode(
        self,
        session_id: str,
        candidate: AddressCandidate,
        source_image_hash: str | None,
    ) -> str:
        payload = {
            "session_id": session_id,
            "place_id": candidate.place_id,
            "source": candidate.source,
            "confidence": candidate.confidence,
            "source_image_hash": source_image_hash,
            "expires_at": int(time.time()) + 15 * 60,
        }
        body = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ).rstrip(b"=")
        signature = hmac.new(self._key, body, hashlib.sha256).digest()
        encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
        return f"{body.decode()}.{encoded_signature.decode()}"

    def decode(self, token: str, session_id: str) -> dict[str, Any]:
        if len(token) > 2_000 or token.count(".") != 1:
            raise ValueError("ADDRESS_CANDIDATE_TOKEN_INVALID")
        body_text, signature_text = token.split(".", 1)
        body = body_text.encode()
        expected = hmac.new(self._key, body, hashlib.sha256).digest()
        try:
            actual = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
            payload = json.loads(
                base64.urlsafe_b64decode(body_text + "=" * (-len(body_text) % 4))
            )
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("ADDRESS_CANDIDATE_TOKEN_INVALID") from exc
        if not hmac.compare_digest(actual, expected):
            raise ValueError("ADDRESS_CANDIDATE_TOKEN_INVALID")
        if payload.get("session_id") != session_id or int(payload.get("expires_at", 0)) < time.time():
            raise ValueError("ADDRESS_CANDIDATE_TOKEN_INVALID")
        return payload
