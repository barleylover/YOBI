from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypeVar

from app.domain.preference_catalog import preference_query_aliases

T = TypeVar("T")

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
_CATEGORY_FACET_HINTS: dict[str, frozenset[str]] = {
    "cuisine_origins": frozenset({"context", "character"}),
    "flavors": frozenset({"character", "flavor", "taste"}),
    "main_ingredients": frozenset({"ingredients", "character"}),
    "food_forms": frozenset({"character", "context"}),
    "temperatures": frozenset({"temperature", "character"}),
    "textures": frozenset({"texture", "character"}),
    "cooking_methods": frozenset({"preparation", "character"}),
}


def normalized_tokens(value: object) -> frozenset[str]:
    """Return Unicode-aware tokens; substring matches such as heat/wheat are impossible."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return frozenset(_TOKEN_PATTERN.findall(normalized))


def _alias_token_sets(value_code: str) -> tuple[frozenset[str], ...]:
    aliases = preference_query_aliases(value_code, "English")
    return tuple(tokens for alias in aliases if (tokens := normalized_tokens(alias)))


def _matches_alias(tokens: frozenset[str], aliases: Sequence[frozenset[str]]) -> bool:
    return any(alias <= tokens for alias in aliases)


def _row_value(row: Any, key: str, default: object = None) -> Any:
    """Read both dictionaries and sqlite3.Row without assuming ``.get``."""

    try:
        value = row[key]
    except (IndexError, KeyError, TypeError):
        return default
    return default if value is None else value


def rank_wiki_passages(
    rows: Iterable[T],
    *,
    selected_groups: Mapping[str, Sequence[str]],
    preferred_evidence_ids: Iterable[str] = (),
    limit: int,
) -> list[T]:
    """Rank reviewed Wiki passages for the exact structured preference request.

    A concept-support evidence chunk is preferred first. Remaining passages are
    ordered by how many selected preference values they explicitly mention,
    category/facet fit, concept distance, and stable source order. This is a
    deterministic lexical reranker so SQLite and Oracle remain behaviorally
    identical even while their vector indexes use different storage formats.
    """

    if limit < 1:
        return []
    preferred = frozenset(str(value) for value in preferred_evidence_ids)
    selected_aliases = {
        category: tuple((value_code, _alias_token_sets(value_code)) for value_code in value_codes)
        for category, value_codes in selected_groups.items()
    }

    scored: list[tuple[tuple[object, ...], T]] = []
    for row in rows:
        content_tokens = normalized_tokens(_row_value(row, "content"))
        matched_values = 0
        matched_categories = 0
        facet = str(_row_value(row, "facet", "")).casefold()
        facet_matches = 0
        for category, values in selected_aliases.items():
            category_matched = any(
                _matches_alias(content_tokens, aliases) for _value_code, aliases in values
            )
            matched_values += sum(
                _matches_alias(content_tokens, aliases) for _value_code, aliases in values
            )
            matched_categories += int(category_matched)
            facet_matches += int(
                category_matched and facet in _CATEGORY_FACET_HINTS.get(category, frozenset())
            )
        chunk_id = str(_row_value(row, "chunk_id", ""))
        score = (
            -int(chunk_id in preferred),
            -matched_categories,
            -matched_values,
            -facet_matches,
            int(_row_value(row, "depth", 0)),
            int(_row_value(row, "chunk_index", 0)),
            chunk_id,
        )
        scored.append((score, row))

    selected: list[T] = []
    seen_content: set[frozenset[str]] = set()
    for _score, row in sorted(scored, key=lambda item: item[0]):
        content_signature = normalized_tokens(_row_value(row, "content"))
        if content_signature in seen_content:
            continue
        seen_content.add(content_signature)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected
