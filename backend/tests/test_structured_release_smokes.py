from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.sqlite_repository import SQLiteYobiRepository
from app.dependencies import (
    get_demo_control,
    get_repository,
    get_structured_recommendation_service,
)
from app.genai.recommendation_generator import (
    GeneratedMenuRecommendation,
    MatchedCriterion,
    RecommendationGenerationStatus,
    RecommendationGenerationV2,
)
from app.main import app
from app.services.demo_control import DemoControl
from app.services.structured_recommendation import StructuredRecommendationService

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fallback_smoke = _load_script("structured_fallback_smoke")
normal_smoke = _load_script("structured_recommendation_smoke")
run_structured_fallback = fallback_smoke.run
_required_option_selections = normal_smoke._required_option_selections


class _GroundedFakeGenerator:
    def generate(
        self,
        *,
        criteria: dict[str, Any],
        evidence_pool: list[dict[str, Any]],
        before_provider_call: Any | None = None,
        **_: Any,
    ) -> RecommendationGenerationV2:
        if before_provider_call is not None:
            before_provider_call()
        recommendations: list[GeneratedMenuRecommendation] = []
        for rank, item in enumerate(evidence_pool[:3], start=1):
            matched: list[MatchedCriterion] = []
            criterion_evidence = item.get("criterion_evidence", {})
            for category_code, selected_values in criteria.items():
                if not isinstance(selected_values, list) or not selected_values:
                    continue
                category_evidence = criterion_evidence.get(category_code, {})
                evidence_ids = [
                    str(evidence_id)
                    for value_code in selected_values
                    for evidence_id in category_evidence.get(value_code, {}).get(
                        "evidence_ids", []
                    )
                ]
                if evidence_ids:
                    matched.append(
                        MatchedCriterion(
                            category_code=category_code,
                            selected_value_codes=list(selected_values),
                            evidence_ids=evidence_ids,
                        )
                    )
            wiki_ids = [
                str(passage["evidence_id"])
                for passage in item.get("wiki_passages", [])[:1]
            ]
            recommendations.append(
                GeneratedMenuRecommendation(
                    rank=rank,
                    menu_id=str(item["menu_id"]),
                    title=f"Grounded choice {rank}",
                    selection_reason="The selected preference has reviewed support.",
                    description="This general food description is backed by the cited passage.",
                    matched_criteria=matched,
                    wiki_evidence_ids=wiki_ids,
                    caution_codes=[],
                )
            )
        return RecommendationGenerationV2(
            status=RecommendationGenerationStatus.RECOMMENDED,
            criteria_summary="One explicit supported preference",
            recommendations=recommendations,
            unmatched_category_codes=[],
        )


class _LocalApiClient:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.client = TestClient(app)

    def __enter__(self) -> _LocalApiClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.client.close()

    def get(self, path: str, **kwargs: Any) -> Any:
        if path == "/demo-booking.png":
            return httpx.Response(
                200,
                content=(ROOT / "frontend" / "public" / "demo-booking.png").read_bytes(),
            )
        return self.client.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.client.post(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.client.put(path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.client.patch(path, **kwargs)


def test_required_option_selection_is_dynamic_and_enforces_availability() -> None:
    selections = _required_option_selections(
        [
            {
                "option_group_id": "required-group",
                "required": True,
                "min_select": 1,
                "max_select": 2,
                "items": [
                    {"option_item_id": "sold-out", "available": False},
                    {"option_item_id": "available", "available": True},
                ],
            },
            {
                "option_group_id": "optional-group",
                "required": False,
                "min_select": 0,
                "max_select": 1,
                "items": [{"option_item_id": "optional", "available": True}],
            },
        ]
    )

    assert selections == [("required-group", ["available"])]

    assert _required_option_selections(
        [
            {
                "option_group_id": "optional-group",
                "required": False,
                "min_select": 0,
                "max_select": 1,
                "items": [{"option_item_id": "optional", "available": True}],
            }
        ]
    ) == [("optional-group", ["optional"])]

    with pytest.raises(RuntimeError, match="STRUCTURED_SMOKE_REQUIRED_OPTION_UNAVAILABLE"):
        _required_option_selections(
            [
                {
                    "option_group_id": "required-group",
                    "required": True,
                    "min_select": 1,
                    "max_select": 1,
                    "items": [{"option_item_id": "sold-out", "available": False}],
                }
            ]
        )


def test_structured_fallback_uses_frozen_server_order_and_cleans_profile(
    repository: SQLiteYobiRepository,
) -> None:
    settings = Settings(
        _env_file=None,
        demo_db_backend="sqlite",
        sqlite_path=repository.path,
    )

    result = run_structured_fallback(repository, settings)

    assert result["status"] == "PASS"
    assert result["gate"] == "structured-provider-fallback"
    assert result["repository_backend"] == "sqlite"
    assert result["exercised_category_code"]
    assert result["exercised_option_code"]
    assert result["result_count"] == 3
    assert result["server_order_preserved"] is True
    assert result["deterministic_explanation"] is True
    assert result["generation_dispatch_count"] == 0
    assert result["failure_mode_scope"] == "isolated-process-control"
    assert result["profile_cascade_cleanup"] is True
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM chat_session").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM structured_recommendation_request"
            ).fetchone()[0]
            == 0
        )


def test_normal_structured_smoke_completes_dynamic_mock_order_and_cleanup(
    repository: SQLiteYobiRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_db_backend="sqlite",
        sqlite_path=repository.path,
        address_ocr_provider="fixture",
    )
    control = DemoControl()
    service = StructuredRecommendationService(
        repository,
        settings,
        control,
        generator=_GroundedFakeGenerator(),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_demo_control] = lambda: control
    app.dependency_overrides[get_structured_recommendation_service] = lambda: service
    monkeypatch.setattr(normal_smoke, "get_repository", lambda: repository)
    monkeypatch.setattr(normal_smoke.httpx, "Client", _LocalApiClient)
    try:
        normal_smoke.run("http://testserver")
    finally:
        app.dependency_overrides.clear()

    output = capsys.readouterr().out
    assert '"gate": "structured-normal-order"' in output
    assert '"mock_checkout_status": "SUCCEEDED"' in output
    assert '"order_status": "CONFIRMED"' in output
    assert '"profile_cascade_cleanup": true' in output
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM chat_session").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM cart").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM mock_checkout").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM mock_order").fetchone()[0] == 0
