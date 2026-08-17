from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from app.knowledge.authoring import (
    LEGACY_FACET_ORDER,
    compile_directory,
    compile_documents,
    parse_document,
)
from app.knowledge.prose_migration import migrate_legacy_document

ROOT = Path(__file__).parents[2]
WIKI_ROOT = ROOT / "knowledge" / "dishes"


def test_all_102_wiki_documents_use_prose_first_minimal_contract() -> None:
    documents = [parse_document(path) for path in sorted(WIKI_ROOT.rglob("*.md"))]

    assert len(documents) == 102
    assert {document.content_contract for document in documents} == {"PROSE_PARAGRAPHS_V2"}
    assert sum(len(document.paragraphs) for document in documents) == 918
    assert sum(len(document.front_matter.essential_facts) for document in documents) == 345
    assert all(len(document.facets) == 9 for document in documents)  # temporary seed projection
    assert all(
        not {
            "ingredients",
            "allergens",
            "dietary",
            "preparation",
        }
        & document.front_matter_payload.keys()
        for document in documents
    )
    assert all(
        fact.fact_type in {"INGREDIENT", "PREPARATION"}
        for document in documents
        for fact in document.front_matter.essential_facts
    )


def test_prose_compiler_emits_paragraph_and_essential_fact_chunks_only() -> None:
    compiled = compile_directory(
        WIKI_ROOT,
        release_id="knowledge-prose-first-contract-v2",
        catalog_version="test-prose-first-v2",
    )
    chunk_kinds = Counter(json.loads(row["metadata_json"])["chunk_kind"] for row in compiled.chunks)
    visibility = Counter(
        json.loads(row["metadata_json"])["recommendation_visibility"] for row in compiled.chunks
    )

    assert compiled.expected_counts == {
        "concepts": 102,
        "relations": 99,
        "closure": 279,
        "claims": 345,
        "documents": 102,
        "chunks": 1263,
    }
    assert chunk_kinds == {"PARAGRAPH": 918, "ESSENTIAL_FACT": 345}
    assert visibility == {"PUBLIC_RAG": 1161, "INTERNAL_ONLY": 102}
    assert {row["claim_type"] for row in compiled.claims} == {"INGREDIENT", "PREPARATION"}
    assert {row["facet"] for row in compiled.chunks} == {"paragraph", "essential_fact"}
    assert all(
        not {"allergens", "dietary"} & json.loads(document_row["front_matter_json"]).keys()
        for document_row in compiled.documents
    )
    assert all(
        json.loads(row["metadata_json"])["source_ref"]
        and json.loads(row["metadata_json"])["review_status"] == "REVIEWED_DEMO"
        for row in compiled.chunks
    )
    public_chunks = [
        row
        for row in compiled.chunks
        if json.loads(row["metadata_json"])["recommendation_visibility"] == "PUBLIC_RAG"
    ]
    assert all(
        "allerg" not in row["content"].casefold()
        and "cross-contact" not in row["content"].casefold()
        for row in public_chunks
    )


def test_legacy_nine_facet_source_still_parses_and_compiles(tmp_path: Path) -> None:
    current = parse_document(WIKI_ROOT / "korean" / "cuisine" / "korean-cuisine.md")
    payload = dict(current.front_matter_payload)
    payload.pop("essential_facts", None)
    payload["version"] = "legacy-test-v1"
    payload.update({"ingredients": [], "allergens": [], "dietary": [], "preparation": []})
    body = "\n\n".join(
        [f"# {current.front_matter.name_en}"]
        + [f"## {facet.title()}\n{current.facets[facet]}" for facet in LEGACY_FACET_ORDER]
    )
    path = tmp_path / "legacy.md"
    path.write_text(
        "---\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n---\n" + body + "\n",
        encoding="utf-8",
    )

    legacy = parse_document(path)
    compiled = compile_documents(
        [legacy], release_id="legacy-reader-contract-v1", catalog_version="legacy-test"
    )

    assert legacy.content_contract == "LEGACY_NINE_FACETS_V1"
    assert tuple(legacy.facets) == LEGACY_FACET_ORDER
    assert compiled.expected_counts["chunks"] == 9
    assert compiled.expected_counts["claims"] == 9
    assert {json.loads(row["metadata_json"])["chunk_kind"] for row in compiled.chunks} == {
        "LEGACY_FACET"
    }


def test_migration_preserves_paragraph_hash_and_is_idempotent(tmp_path: Path) -> None:
    current = parse_document(WIKI_ROOT / "korean" / "cuisine" / "korean-cuisine.md")
    payload = dict(current.front_matter_payload)
    projected = current.front_matter
    payload.pop("essential_facts", None)
    payload["version"] = "legacy-test-v1"
    payload.update(
        {
            "ingredients": [item.model_dump(mode="json") for item in projected.ingredients],
            "allergens": [],
            "dietary": [],
            "preparation": [item.model_dump(mode="json") for item in projected.preparation],
        }
    )
    body = "\n\n".join(
        [f"# {current.front_matter.name_en}"]
        + [f"## {facet.title()}\n{current.facets[facet]}" for facet in LEGACY_FACET_ORDER]
    )
    path = tmp_path / "legacy.md"
    path.write_text(
        "---\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n---\n" + body + "\n",
        encoding="utf-8",
    )

    migrated = migrate_legacy_document(path, write=True)
    repeated = migrate_legacy_document(path, write=True)

    assert migrated.changed is True
    assert migrated.paragraph_count == 9
    assert migrated.original_paragraph_sha256 == migrated.migrated_paragraph_sha256
    assert repeated.changed is False
    assert parse_document(path).content_contract == "PROSE_PARAGRAPHS_V2"
