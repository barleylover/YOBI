from __future__ import annotations

from types import SimpleNamespace

from app.genai.usage import response_usage_metrics


def test_usage_metrics_support_mapping_and_keep_basic_contract_small() -> None:
    response = SimpleNamespace(
        usage={
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "input_tokens_details": {"cached_tokens": 3},
        }
    )

    assert response_usage_metrics(response) == {
        "input_tokens": 11,
        "output_tokens": 7,
    }


def test_detailed_usage_metrics_support_attributes_and_reject_invalid_counts() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=11,
            output_tokens=True,
            total_tokens=18,
            input_tokens_details=SimpleNamespace(cached_tokens=3),
            output_tokens_details=SimpleNamespace(reasoning_tokens=5),
        )
    )

    assert response_usage_metrics(response, include_details=True) == {
        "input_tokens": 11,
        "total_tokens": 18,
        "cached_input_tokens": 3,
        "reasoning_tokens": 5,
    }


def test_usage_metrics_ignore_missing_usage() -> None:
    assert response_usage_metrics(SimpleNamespace()) == {}
