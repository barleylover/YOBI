from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable

SYNONYMS: dict[str, tuple[str, ...]] = {
    "red rice cake": ("tteokbokki", "rice cake", "gochujang", "chewy"),
    "comforting": ("comfort", "warm", "savory", "broth"),
    "chicken noodle soup": ("chicken", "broth", "noodle", "kalguksu", "mild"),
    "creamy pasta": ("cream", "creamy", "rose", "mild"),
    "rain": ("warm", "broth", "soup", "comfort"),
    "vegan": ("plant", "vegetable", "no meat", "no egg", "no dairy"),
    "not spicy": ("mild", "spice 0", "spice 1"),
    "shellfish": ("shrimp", "prawn", "crab", "seafood"),
}


def _tokens(text: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9가-힣]+", " ", text.lower()).strip()
    expanded = normalized
    for phrase, additions in SYNONYMS.items():
        if phrase in normalized:
            expanded += " " + " ".join(additions)
    words = expanded.split()
    ngrams = [f"{words[i]}_{words[i + 1]}" for i in range(len(words) - 1)]
    return words + ngrams


def deterministic_embedding(text: str, dimension: int = 1536) -> list[float]:
    """Produce a deterministic semantic hashing vector for offline demo fallback.

    It is not presented as an OCI embedding. It preserves meaningful token overlap and
    synonym expansion so local semantic retrieval remains real rather than random.
    """

    vector = [0.0] * dimension
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        weight = 1.0 + min(len(token), 20) / 20.0
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    return sum(a * b for a, b in zip(left, right))

