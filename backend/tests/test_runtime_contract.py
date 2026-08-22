from __future__ import annotations

from app.db.runtime_contract import EXPECTED_RUNTIME_COUNTS, runtime_counts_compatible


def test_runtime_count_contract_is_shared_and_allows_only_retained_reference_growth() -> None:
    assert runtime_counts_compatible(dict(EXPECTED_RUNTIME_COUNTS)) is True

    retained_growth = dict(EXPECTED_RUNTIME_COUNTS)
    retained_growth["ingredient"] += 1
    assert runtime_counts_compatible(retained_growth) is True

    fixture_drift = dict(EXPECTED_RUNTIME_COUNTS)
    fixture_drift["menu"] += 1
    assert runtime_counts_compatible(fixture_drift) is False

    missing_table = dict(EXPECTED_RUNTIME_COUNTS)
    missing_table.pop("menu")
    assert runtime_counts_compatible(missing_table) is False
