from __future__ import annotations

import hashlib
import json
import re

from app.option_static_localization import localize_option_name

MODEL_ID = "CODEX_OFFLINE_STATIC_V1"
PROMPT_VERSION = "menu-source-description-static-v1"


def description_source_hash(source_text: str, language_code: str) -> str:
    payload = json.dumps(
        {
            "source_text": source_text,
            "language_code": language_code,
            "prompt_version": PROMPT_VERSION,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def localize_source_description(source_text: str, language_code: str) -> str:
    """Create deterministic offline display copy without a runtime provider call.

    The source catalog frequently contains short noun phrases rather than prose.
    Reusing the curated menu/option glossary gives those phrases a stable
    translation, while deterministic transliteration preserves brands and other
    source-only terms instead of inventing meaning.
    """

    source = re.sub(r"\s+", " ", source_text).strip()
    if not source:
        raise ValueError("MENU_SOURCE_DESCRIPTION_EMPTY")
    if language_code == "ko":
        return source
    if language_code not in {"en", "ja"}:
        raise ValueError("MENU_SOURCE_DESCRIPTION_LANGUAGE_UNSUPPORTED")
    chunks = [
        chunk.strip()
        for chunk in re.split(r"(?<=[.!?。！？])\s+|\s*[|｜]\s*|\s*/\s*", source)
        if chunk.strip()
    ]
    localized = [localize_option_name(chunk[:280], language_code) for chunk in chunks]
    separator = "。" if language_code == "ja" else ". "
    result = separator.join(value.rstrip(".。") for value in localized if value).strip()
    if language_code == "ja" and result and not result.endswith("。"):
        result += "。"
    elif language_code == "en" and result and result[-1] not in ".!?":
        result += "."
    if not result or re.search(r"[가-힣]", result):
        raise ValueError("MENU_SOURCE_DESCRIPTION_OUTPUT_INVALID")
    return result[:4000]
