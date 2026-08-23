from __future__ import annotations

import unicodedata


def normalize_address_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
