from types import SimpleNamespace

from app.genai.response_limits import expanded_output_limit, output_limit_reached


def test_output_limit_reached_accepts_object_and_mapping_signals() -> None:
    assert output_limit_reached(
        SimpleNamespace(
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        )
    )
    assert output_limit_reached(
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
        }
    )


def test_output_limit_reached_does_not_infer_truncation_from_bad_text() -> None:
    assert not output_limit_reached(SimpleNamespace(output_text='{"items":'))
    assert not output_limit_reached(
        SimpleNamespace(
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="content_filter"),
        )
    )


def test_expanded_output_limit_doubles_once_with_provider_cap() -> None:
    assert expanded_output_limit(2_048, 16_384) == 4_096
    assert expanded_output_limit(4_096, 16_384) == 8_192
    assert expanded_output_limit(4_096, 6_000) == 6_000
