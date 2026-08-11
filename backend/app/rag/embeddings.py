from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from functools import lru_cache

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

# Deterministic embeddings intentionally remain the offline demo fallback.  These
# bilingual routes keep short Korean questions useful even when their wording has
# little or no token overlap with the English Wiki prose.
KNOWLEDGE_FACET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ingredients": (
        "ingredient",
        "ingredients",
        "contains",
        "made of",
        "what is in",
        "재료",
        "성분",
        "뭐가 들어",
        "무엇이 들어",
        "어떤 게 들어",
        "들어가",
    ),
    "safety": (
        "allergen",
        "allergy",
        "safe to eat",
        "dietary risk",
        "risk",
        "알레르기",
        "알러지",
        "먹어도 돼",
        "먹어도 되",
        "위험",
        "안전",
        "diet",
        "dietary",
        "religion",
        "religious",
        "halal",
        "vegan",
        "vegetarian",
        "식단",
        "식이",
        "종교",
        "할랄",
        "무슬림",
        "비건",
        "채식",
    ),
    "preparation": (
        "preparation",
        "prepared",
        "how is it cooked",
        "how is it made",
        "cooking method",
        "조리",
        "어떻게 만들어",
        "어떻게 만들",
        "만드는 법",
        "조리법",
    ),
    "taste": (
        "taste",
        "flavor",
        "flavour",
        "sweet",
        "savory",
        "spicy",
        "무슨 맛",
        "어떤 맛",
        "맛이",
        "달아",
        "매워",
        "고소",
        "짭짤",
    ),
    "texture": (
        "texture",
        "chewy",
        "crispy",
        "crunchy",
        "soft",
        "식감",
        "쫄깃",
        "바삭",
        "아삭",
        "부드러",
    ),
    "temperature": (
        "temperature",
        "served hot",
        "served cold",
        "warm food",
        "cold food",
        "온도",
        "따뜻",
        "뜨겁",
        "차갑",
        "차가운",
        "시원",
    ),
    "overview": (
        "what is",
        "tell me about",
        "describe",
        "description",
        "뭐야",
        "무슨 음식",
        "어떤 음식",
        "설명해",
        "소개해",
    ),
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


def _normalized_retrieval_text(text: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", " ", text.lower()).strip()


@lru_cache(maxsize=256)
def routed_knowledge_facets(query: str) -> tuple[str, ...]:
    """Return deterministic Wiki facets explicitly requested by a bilingual query."""

    normalized = _normalized_retrieval_text(query)
    compact = normalized.replace(" ", "")
    routed: list[tuple[int, str]] = []
    for facet, keywords in KNOWLEDGE_FACET_KEYWORDS.items():
        positions: list[int] = []
        for keyword in keywords:
            normalized_keyword = _normalized_retrieval_text(keyword)
            position = normalized.find(normalized_keyword)
            if position < 0:
                position = compact.find(normalized_keyword.replace(" ", ""))
            if position >= 0:
                positions.append(position)
        if positions:
            routed.append((min(positions), facet))
    return tuple(facet for _, facet in sorted(routed, key=lambda item: (item[0], item[1])))


def query_contains_knowledge_alias(query: str, aliases: Iterable[str]) -> bool:
    """Match a complete bilingual dish alias inside a natural-language question."""

    normalized_query = _normalized_retrieval_text(query)
    compact_query = normalized_query.replace(" ", "")
    for alias in aliases:
        normalized_alias = _normalized_retrieval_text(alias)
        if len(normalized_alias.replace(" ", "")) < 2:
            continue
        if any("가" <= character <= "힣" for character in normalized_alias):
            if normalized_alias.replace(" ", "") in compact_query:
                return True
            continue
        if re.search(
            rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])",
            normalized_query,
        ):
            return True
    return False


def hybrid_knowledge_chunk_score(
    query: str,
    vector_similarity: float,
    facet: str,
    aliases: Iterable[str] = (),
) -> float:
    """Combine vector, requested-facet, and exact dish-alias evidence.

    The returned value remains in ``[0, 1]`` and is shared by SQLite and Oracle.
    Facet and alias signals only route already active Wiki chunks; they never add
    ungrounded content or bypass the active-release contract.
    """

    vector_score = max(0.0, min(1.0, vector_similarity))
    routed = routed_knowledge_facets(query)
    alias_match = query_contains_knowledge_alias(query, aliases)
    if routed:
        try:
            facet_rank = routed.index(facet.lower())
        except ValueError:
            facet_signal = 0.0
        else:
            facet_signal = max(0.8, 1.0 - 0.08 * facet_rank)
        score = 0.55 * vector_score + 0.25 * facet_signal + 0.20 * float(alias_match)
    elif alias_match:
        score = 0.75 * vector_score + 0.25
    else:
        score = vector_score
    return max(0.0, min(1.0, score))


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
