from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("yobi_seed_demo", ROOT / "scripts" / "seed_demo.py")
assert SPEC and SPEC.loader
seed_demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed_demo)


def valid_result() -> dict[str, object]:
    return {
        "counts": dict(seed_demo.EXPECTED_COUNTS),
        "null_menu_vectors": 0,
        "null_review_vectors": 0,
        "null_knowledge_vectors": 0,
        "canonical_ready": True,
        "required_groups_without_items": 0,
    }


def test_seed_integrity_accepts_exact_catalog() -> None:
    seed_demo.validate(valid_result())


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("null_menu_vectors", 1, "SEED_MENU_VECTOR_INTEGRITY_FAILED"),
        ("null_review_vectors", 1, "SEED_REVIEW_VECTOR_INTEGRITY_FAILED"),
        ("null_knowledge_vectors", 1, "SEED_KNOWLEDGE_VECTOR_INTEGRITY_FAILED"),
        ("canonical_ready", False, "SEED_CANONICAL_INTEGRITY_FAILED"),
        ("required_groups_without_items", 1, "SEED_REQUIRED_OPTIONS_INTEGRITY_FAILED"),
    ],
)
def test_seed_integrity_rejects_invalid_catalog(field: str, value: object, code: str) -> None:
    result = valid_result()
    result[field] = value
    with pytest.raises(RuntimeError, match=code):
        seed_demo.validate(result)
