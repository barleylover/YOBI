from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
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

FALLBACK_RECOMMENDATION_QUERY_ALIASES = (
    "food",
    "menu",
    "dish",
    "ingredient",
    "preparation",
    "taste",
    "texture",
)


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


def lexical_token_similarity(query: str, document: str) -> float:
    """Return a bounded lexical overlap signal for hybrid Wiki retrieval."""

    query_tokens = set(_tokens(query))
    document_tokens = set(_tokens(document))
    if not query_tokens or not document_tokens:
        return 0.0
    return len(query_tokens & document_tokens) / len(query_tokens)


@dataclass(frozen=True)
class HybridChunkCandidate:
    """One unique Wiki chunk with its query-specific vector signal."""

    chunk_id: str
    content: str
    facet: str
    aliases: tuple[str, ...]
    vector_similarity: float


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    normalized_text = _normalized_retrieval_text(text)
    normalized_phrase = _normalized_retrieval_text(phrase)
    if not normalized_phrase:
        return False
    if any("가" <= character <= "힣" for character in normalized_phrase):
        return normalized_phrase.replace(" ", "") in normalized_text.replace(" ", "")
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(normalized_phrase)}(?![a-z0-9])",
            normalized_text,
        )
    )


def exact_essential_similarity(
    query_aliases: Iterable[str],
    document_text: str,
    facet: str,
    concept_aliases: Iterable[str] = (),
) -> float:
    """Return the exact-name/alias and essential-fact retrieval signal.

    Preference aliases are the stable catalog vocabulary. A direct occurrence in
    either the reviewed prose or the mapped concept names is strong evidence. An
    essential fact with lexical overlap remains useful even when the wording is not
    an exact phrase (for example, ``beef`` versus ``main ingredient: beef``).
    """

    aliases = tuple(alias for alias in query_aliases if alias.strip())
    query_text = " ".join(aliases)
    searchable_aliases = tuple(alias for alias in concept_aliases if alias.strip())
    exact_match = any(
        _contains_normalized_phrase(document_text, alias)
        or any(
            _contains_normalized_phrase(concept_alias, alias)
            or _contains_normalized_phrase(alias, concept_alias)
            for concept_alias in searchable_aliases
        )
        for alias in aliases
    )
    essential_overlap = (
        facet.casefold() == "essential_fact"
        and lexical_token_similarity(query_text, document_text) > 0.0
    )
    if exact_match and essential_overlap:
        return 1.0
    if exact_match:
        return 0.9
    if essential_overlap:
        return 0.7
    return 0.0


def _positive_ranking(
    candidates: tuple[HybridChunkCandidate, ...],
    scores: dict[str, float],
) -> tuple[str, ...]:
    return tuple(
        candidate.chunk_id
        for candidate in sorted(
            candidates,
            key=lambda item: (-scores[item.chunk_id], item.chunk_id),
        )
        if scores[candidate.chunk_id] > 0.0
    )


def rank_hybrid_chunks_rrf(
    query_aliases: Iterable[str],
    candidates: Iterable[HybridChunkCandidate],
    *,
    limit: int,
    rank_constant: int = 60,
) -> list[tuple[HybridChunkCandidate, float]]:
    """Fuse vector, lexical, and exact/essential rankings with reciprocal rank.

    Candidates must represent unique chunks. The returned score is normalized to
    ``[0, 1]`` against the best possible rank across all three signals; callers can
    safely compare menu/category aggregates without depending on raw score scales.
    """

    if limit < 1:
        return []
    if rank_constant < 1:
        raise ValueError("RRF_RANK_CONSTANT_MUST_BE_POSITIVE")
    aliases = tuple(dict.fromkeys(alias.strip() for alias in query_aliases if alias.strip()))
    query_text = " ".join(aliases)
    unique_candidates: dict[str, HybridChunkCandidate] = {}
    for candidate in candidates:
        unique_candidates.setdefault(candidate.chunk_id, candidate)
    values = tuple(unique_candidates.values())
    if not values:
        return []

    vector_scores = {
        item.chunk_id: max(0.0, min(1.0, item.vector_similarity)) for item in values
    }
    lexical_scores = {
        item.chunk_id: lexical_token_similarity(query_text, item.content) for item in values
    }
    essential_scores = {
        item.chunk_id: exact_essential_similarity(
            aliases,
            item.content,
            item.facet,
            item.aliases,
        )
        for item in values
    }
    rankings = (
        _positive_ranking(values, vector_scores),
        _positive_ranking(values, lexical_scores),
        _positive_ranking(values, essential_scores),
    )
    fused: dict[str, float] = {item.chunk_id: 0.0 for item in values}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            fused[chunk_id] += 1.0 / (rank_constant + rank)
    best_possible = 3.0 / (rank_constant + 1)
    ranked = sorted(
        values,
        key=lambda item: (-fused[item.chunk_id], item.chunk_id),
    )
    return [
        (item, max(0.0, min(1.0, fused[item.chunk_id] / best_possible)))
        for item in ranked[:limit]
        if fused[item.chunk_id] > 0.0
    ]


def apply_soft_profile_retrieval_signal(
    primary_score: float,
    soft_profile_score: float | None,
    *,
    soft_weight: float = 0.1,
) -> float:
    """Use profile affinity only as a bounded tie-break after explicit intent."""

    primary = max(0.0, min(1.0, primary_score))
    if soft_profile_score is None:
        return primary
    if not 0.0 <= soft_weight <= 1.0:
        raise ValueError("SOFT_PROFILE_WEIGHT_OUT_OF_RANGE")
    soft = max(0.0, min(1.0, soft_profile_score))
    return (1.0 - soft_weight) * primary + soft_weight * soft


def hybrid_knowledge_chunk_score(
    query: str,
    vector_similarity: float,
    facet: str,
    aliases: Iterable[str] = (),
    document_text: str = "",
) -> float:
    """Combine vector, requested-facet, and exact dish-alias evidence.

    The returned value remains in ``[0, 1]`` and is shared by SQLite and Oracle.
    Facet and alias signals only route already active Wiki chunks; they never add
    ungrounded content or bypass the active-release contract.
    """

    vector_score = max(0.0, min(1.0, vector_similarity))
    lexical_score = lexical_token_similarity(query, document_text)
    routed = routed_knowledge_facets(query)
    alias_match = query_contains_knowledge_alias(query, aliases)
    if routed:
        try:
            facet_rank = routed.index(facet.lower())
        except ValueError:
            facet_signal = 0.0
        else:
            facet_signal = max(0.8, 1.0 - 0.08 * facet_rank)
        score = (
            0.45 * vector_score
            + 0.20 * lexical_score
            + 0.20 * facet_signal
            + 0.15 * float(alias_match)
        )
    elif alias_match:
        score = 0.60 * vector_score + 0.20 * lexical_score + 0.20
    else:
        score = 0.70 * vector_score + 0.30 * lexical_score
    return max(0.0, min(1.0, score))


@lru_cache(maxsize=32_768)
def deterministic_sparse_embedding(
    text: str,
    dimension: int = 1536,
) -> tuple[tuple[int, float], ...]:
    """Return the sparse form of the deterministic offline embedding.

    Menu retrieval evaluates the same 15k-document mirror repeatedly. Caching
    only non-zero coordinates keeps that channel bounded without retaining
    thousands of 1536-element Python lists.
    """

    values: dict[int, float] = {}
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        weight = 1.0 + min(len(token), 20) / 20.0
        values[index] = values.get(index, 0.0) + sign * weight
    norm = math.sqrt(sum(value * value for value in values.values()))
    if norm == 0:
        return ()
    return tuple(sorted((index, value / norm) for index, value in values.items()))


def sparse_cosine_similarity(
    left: Iterable[tuple[int, float]],
    right: Iterable[tuple[int, float]],
) -> float:
    left_values = dict(left)
    right_values = dict(right)
    if len(left_values) > len(right_values):
        left_values, right_values = right_values, left_values
    return sum(value * right_values.get(index, 0.0) for index, value in left_values.items())


def deterministic_embedding(text: str, dimension: int = 1536) -> list[float]:
    """Produce a deterministic semantic hashing vector for offline demo fallback.

    It is not presented as an OCI embedding. It preserves meaningful token overlap and
    synonym expansion so local semantic retrieval remains real rather than random.
    """

    vector = [0.0] * dimension
    for index, value in deterministic_sparse_embedding(text, dimension):
        vector[index] = value
    return vector


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    return sum(a * b for a, b in zip(left, right))
