from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.domain.preference_catalog import PREFERENCE_CATEGORIES, preference_query_aliases

SUPPORT_METHOD_VERSION = "yobi-reviewed-wiki-support-v1"
SUPPORT_PROVENANCE = "SYNTHETIC_WIKI"
REVIEWED_CUISINE_ORIGIN_CODES = frozenset(
    {
        "KOREAN",
        "CHINESE",
        "JAPANESE",
        "ITALIAN",
        "AMERICAN",
        "SOUTHEAST_ASIAN",
        "MEXICAN",
    }
)
SUPPORT_MANIFEST_FIELDS = (
    "knowledge_release_id",
    "concept_id",
    "category_code",
    "option_code",
    "support_status",
    "support_strength",
    "evidence_chunk_id",
    "provenance_type",
    "source_ref",
    "review_status",
    "support_method_version",
    "is_synthetic",
)


def preference_alias_matches(text: str, aliases: tuple[str, ...]) -> bool:
    """Conservative word matching shared by SQLite and Oracle demo seed paths."""

    ignored = {
        "and",
        "cuisine",
        "dish",
        "flavor",
        "food",
        "method",
        "or",
        "served",
        "temperature",
        "the",
        "to",
        "with",
        "won",
    }
    for alias in aliases:
        words = [
            word
            for word in re.sub(r"[^a-z0-9가-힣]+", " ", alias.lower()).split()
            if word not in ignored
            and (len(word) >= 3 or any("가" <= character <= "힣" for character in word))
        ]
        if not words:
            continue
        required_matches = 1 if len(words) == 1 else 2
        if sum(word in text for word in words) >= required_matches:
            return True
    return False


def build_synthetic_support_rows(
    *,
    knowledge_release_id: str,
    reviewed_chunks: Sequence[Mapping[str, Any]],
    updated_at: Any,
) -> list[dict[str, Any]]:
    """Derive support only from caller-validated reviewed synthetic Wiki chunks.

    The caller owns the database-specific query and must supply only PUBLIC_RAG
    chunks (or legacy non-safety chunks with no visibility marker) from reviewed
    ``SYNTHETIC_WIKI`` documents. Each returned edge cites the single chunk that
    matched it; menu names, merchant copy and reviews are never inputs.
    """

    chunks_by_concept: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for chunk in sorted(
        reviewed_chunks,
        key=lambda row: (
            str(row["concept_id"]),
            int(row.get("depth", 0)),
            str(row["chunk_id"]),
        ),
    ):
        chunks_by_concept[str(chunk["concept_id"])].append(chunk)

    rows: list[dict[str, Any]] = []
    for concept_id, chunks in sorted(chunks_by_concept.items()):
        for category in PREFERENCE_CATEGORIES:
            if category.code == "price_bands":
                continue
            for option in category.options:
                if (
                    category.code == "cuisine_origins"
                    and option.code not in REVIEWED_CUISINE_ORIGIN_CODES
                ):
                    continue
                evidence = next(
                    (
                        chunk
                        for chunk in chunks
                        if preference_alias_matches(
                            str(chunk["content"]).lower(),
                            preference_query_aliases(option.code, "en"),
                        )
                    ),
                    None,
                )
                if evidence is None:
                    continue
                rows.append(
                    {
                        "knowledge_release_id": knowledge_release_id,
                        "concept_id": concept_id,
                        "category_code": category.code,
                        "option_code": option.code,
                        "support_status": "SUPPORTED",
                        "support_strength": 1.0,
                        "evidence_chunk_id": str(evidence["chunk_id"]),
                        "provenance_type": SUPPORT_PROVENANCE,
                        "source_ref": (
                            f"knowledge:{evidence['document_id']}:{evidence['chunk_id']}"
                        ),
                        "review_status": "REVIEWED_DEMO",
                        "support_method_version": SUPPORT_METHOD_VERSION,
                        "is_synthetic": 1,
                        "updated_at": updated_at,
                    }
                )
    return sorted(
        rows,
        key=lambda row: (
            str(row["concept_id"]),
            str(row["category_code"]),
            str(row["option_code"]),
        ),
    )


def support_manifest_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {field: row[field] for field in SUPPORT_MANIFEST_FIELDS}
        for row in sorted(
            rows,
            key=lambda row: (
                str(row["concept_id"]),
                str(row["category_code"]),
                str(row["option_code"]),
            ),
        )
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
