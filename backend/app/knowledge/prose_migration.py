from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.knowledge.authoring import LEGACY_FACET_ORDER, parse_document

PROSE_WIKI_VERSION = "demo-wiki-2026.08.12-v2"
PROSE_WIKI_UPDATED_AT = "2026-08-12"

_SECTION_LAYOUT = (
    (
        "Character and experience",
        ("overview", "taste", "texture", "temperature", "satiety"),
    ),
    ("Context and comparisons", ("culture", "analogy")),
    ("Ingredients and variations", ("ingredients", "safety")),
)


@dataclass(frozen=True)
class ProseMigrationResult:
    path: Path
    original_paragraph_sha256: str
    migrated_paragraph_sha256: str
    paragraph_count: int
    essential_fact_count: int
    changed: bool


def _sha256_lines(values: list[str]) -> str:
    canonical = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _minimal_front_matter(payload: dict[str, Any]) -> dict[str, Any]:
    essential_facts: list[dict[str, Any]] = []
    for ingredient in payload.get("ingredients", []):
        if ingredient.get("role") not in {"DEFINING", "CORE"}:
            continue
        essential_facts.append(
            {
                "fact_type": "INGREDIENT",
                "ingredient_id": ingredient["ingredient_id"],
                "name_ko": ingredient["name_ko"],
                "name_en": ingredient["name_en"],
                "role": ingredient["role"],
                "status": "PRESUMED_PRESENT",
                "source_ref": ingredient["source_ref"],
            }
        )
    for preparation in payload.get("preparation", []):
        if preparation.get("status", "PRESUMED_PRESENT") != "PRESUMED_PRESENT":
            continue
        essential_facts.append(
            {
                "fact_type": "PREPARATION",
                "method": preparation["method"],
                "value_text": preparation["value_text"],
                "status": "PRESUMED_PRESENT",
                "source_ref": preparation["source_ref"],
            }
        )

    preserved_keys = (
        "concept_id",
        "concept_type",
        "name_ko",
        "name_en",
        "aliases",
        "language",
        "parents",
        "source_type",
        "source_refs",
        "license_state",
        "review_status",
        "is_synthetic",
    )
    result = {key: payload[key] for key in preserved_keys}
    result["version"] = PROSE_WIKI_VERSION
    result["essential_facts"] = essential_facts
    result["updated_at"] = PROSE_WIKI_UPDATED_AT
    return result


def _prose_body(title: str, facets: dict[str, str]) -> str:
    lines = [f"# {title}", ""]
    for heading, keys in _SECTION_LAYOUT:
        lines.extend((f"## {heading}", ""))
        for key in keys:
            lines.extend((facets[key].strip(), ""))
    return "\n".join(lines).rstrip()


def migrate_legacy_document(path: Path, *, write: bool = False) -> ProseMigrationResult:
    """Convert one nine-facet source while proving that no authored paragraph was lost."""

    before = parse_document(path)
    if before.content_contract != "LEGACY_NINE_FACETS_V1":
        paragraphs = [paragraph.content for paragraph in before.paragraphs]
        digest = _sha256_lines(paragraphs)
        return ProseMigrationResult(
            path=path,
            original_paragraph_sha256=digest,
            migrated_paragraph_sha256=digest,
            paragraph_count=len(paragraphs),
            essential_fact_count=len(before.front_matter.essential_facts),
            changed=False,
        )

    original_paragraphs = [before.facets[key] for key in LEGACY_FACET_ORDER]
    payload = _minimal_front_matter(before.front_matter_payload)
    body = _prose_body(before.front_matter.name_en, before.facets)
    migrated = "---\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n---\n" + body + "\n"

    # Parse the candidate before touching the source and check paragraph hash,
    # schema contraction and legacy-seed projection as one atomic gate.
    candidate_path = path.with_name(f".{path.name}.prose-migration-candidate")
    candidate_path.write_text(migrated, encoding="utf-8")
    try:
        after = parse_document(candidate_path)
    finally:
        candidate_path.unlink(missing_ok=True)
    migrated_paragraphs = [paragraph.content for paragraph in after.paragraphs]
    original_hash = _sha256_lines(original_paragraphs)
    migrated_hash = _sha256_lines(migrated_paragraphs)
    if migrated_hash != original_hash:
        raise ValueError(f"PROSE_MIGRATION_PARAGRAPH_DRIFT:{path}")
    if after.content_contract != "PROSE_PARAGRAPHS_V2":
        raise ValueError(f"PROSE_MIGRATION_CONTRACT_MISMATCH:{path}")
    if tuple(after.facets) != LEGACY_FACET_ORDER:
        raise ValueError(f"PROSE_MIGRATION_SEED_PROJECTION_MISMATCH:{path}")
    if any(key in payload for key in ("ingredients", "allergens", "dietary", "preparation")):
        raise ValueError(f"PROSE_MIGRATION_LEGACY_FRONT_MATTER_RETAINED:{path}")

    if write:
        path.write_text(migrated, encoding="utf-8")
    return ProseMigrationResult(
        path=path,
        original_paragraph_sha256=original_hash,
        migrated_paragraph_sha256=migrated_hash,
        paragraph_count=len(migrated_paragraphs),
        essential_fact_count=len(after.front_matter.essential_facts),
        changed=True,
    )


def migrate_directory(root: Path, *, write: bool = False) -> list[ProseMigrationResult]:
    paths = sorted(root.rglob("*.md"))
    if not paths:
        raise ValueError(f"NO_KNOWLEDGE_DOCUMENTS:{root}")
    results = [migrate_legacy_document(path, write=write) for path in paths]
    if len(results) != 102:
        raise ValueError(f"UNEXPECTED_DEMO_WIKI_DOCUMENT_COUNT:{len(results)}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert the demo Wiki to prose-first v2")
    parser.add_argument("root", type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    results = migrate_directory(args.root, write=args.write)
    print(
        json.dumps(
            {
                "documents": len(results),
                "changed": sum(item.changed for item in results),
                "paragraphs": sum(item.paragraph_count for item in results),
                "essential_facts": sum(item.essential_fact_count for item in results),
                "write": args.write,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
