from __future__ import annotations

from collections import Counter

from evaluation.recommendation_v2_suite import build_query_suite


def test_recommendation_v2_suite_has_frozen_distribution_and_split() -> None:
    suite = build_query_suite()

    assert len(suite) == 200
    assert Counter(item.cohort for item in suite) == {
        "single_option": 100,
        "cross_category": 60,
        "negative": 20,
        "bilingual_equivalence": 20,
    }
    assert Counter(item.split for item in suite) == {"TUNE": 140, "HOLDOUT": 60}
    equivalence = [item for item in suite if item.cohort == "bilingual_equivalence"]
    assert len({item.pair_id for item in equivalence}) == 10
    for pair_id in {item.pair_id for item in equivalence}:
        pair = [item for item in equivalence if item.pair_id == pair_id]
        assert {item.locale for item in pair} == {"English", "한국어"}
        assert pair[0].criteria == pair[1].criteria


def test_every_active_preference_option_has_two_single_option_queries() -> None:
    suite = build_query_suite()
    hits: Counter[tuple[str, str]] = Counter()
    for item in suite:
        if item.cohort != "single_option":
            continue
        for category_code, values in item.criteria.items():
            if isinstance(values, list):
                hits.update((category_code, value) for value in values)

    assert len(hits) == 50
    assert set(hits.values()) == {2}
