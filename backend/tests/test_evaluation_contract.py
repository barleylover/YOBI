from __future__ import annotations

import json

from evaluation.run_evaluation import (
    CATEGORY_GOLDEN_CASES,
    SERVER_RANK_GOLDEN_PATH,
    server_rank_golden_failures,
)


def test_legacy_semantic_hash_categories_are_query_specific() -> None:
    chicken_query_categories = CATEGORY_GOLDEN_CASES[1][1]
    unspecified_protein_categories = CATEGORY_GOLDEN_CASES[2][1]

    assert chicken_query_categories == frozenset({"Chicken kalguksu"})
    assert "Janchi guksu" in unspecified_protein_categories
    assert "Tteokbokki" not in unspecified_protein_categories


def test_server_rank_golden_fixture_is_executed_and_mutation_fails(tmp_path) -> None:
    assert server_rank_golden_failures() == 0

    fixture = json.loads(SERVER_RANK_GOLDEN_PATH.read_text(encoding="utf-8"))
    fixture["golden_cases"][0]["expected_order"] = ["c", "b", "a"]
    mutated_path = tmp_path / "mutated-server-rank-golden.json"
    mutated_path.write_text(json.dumps(fixture), encoding="utf-8")

    assert server_rank_golden_failures(mutated_path) > 0
