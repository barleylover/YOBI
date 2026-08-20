from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from app.domain.structured_recommendation import RecommendationCriteriaV2

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "yobi_recommendation_quality_smoke",
    ROOT / "scripts" / "recommendation_quality_smoke.py",
)
assert SPEC and SPEC.loader
quality = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = quality
SPEC.loader.exec_module(quality)
Scenario = quality.Scenario


def _criteria(*, price_only: bool = False) -> RecommendationCriteriaV2:
    return RecommendationCriteriaV2.model_validate(
        {
            "schema_version": "2",
            "cuisine_origins": [] if price_only else ["KOREAN"],
            "flavors": [],
            "main_ingredients": [],
            "food_forms": [],
            "temperatures": [],
            "price_bands": ["UNDER_10000"] if price_only else [],
            "textures": [],
            "cooking_methods": [],
            "dietary_filters": {
                "halal_certified_only": False,
                "vegan": False,
            },
            "max_spice_level": 5,
            "spice_reference_country": "KR",
        }
    )


def _batch(*, korean: bool = False, price: int = 9_000) -> dict[str, Any]:
    recommendations = []
    for rank in range(1, 4):
        recommendations.append(
            {
                "rank": rank,
                "menu": {
                    "menu_id": f"menu-{rank}",
                    "merchant_id": f"merchant-{rank}",
                    "price": price,
                },
                "title": "추천 메뉴" if korean else "Recommended menu",
                # Selection is ID/evidence-only. User-facing selection reasons
                # were removed from the current recommendation contract.
                "selection_reason": "",
                "description": (
                    "인용된 일반 음식 설명을 바탕으로 안내합니다."
                    if korean
                    else "The cited general food passage describes this dish."
                ),
                "matched_criteria": [
                    {
                        "category_code": "cuisine_origins",
                        "selected_value_codes": ["KOREAN"],
                        "evidence_ids": [f"criterion-{rank}"],
                    }
                ],
                "wiki_passages": [
                    {
                        "evidence_id": f"wiki-{rank}",
                        "content": "Reviewed general food reference.",
                    }
                ],
            }
        )
    return {
        "status": "RECOMMENDED",
        "failure_code": None,
        "snapshot_id": "snapshot-1",
        "criteria_summary": "한식 취향" if korean else "Korean preference",
        "recommendations": recommendations,
        "unmatched_category_codes": [],
    }


def test_quality_batch_accepts_grounded_diverse_three() -> None:
    errors, evidence = quality._validate_batch(
        _batch(),
        Scenario("single", _criteria()),
        language="English",
    )

    assert errors == []
    assert evidence["result_count"] == 3
    assert evidence["merchant_count"] == 3
    assert evidence["evidence_count"] == 3
    assert evidence["matched_group_count_min"] == 1
    assert evidence["selected_cuisine_codes"] == ["KOREAN"]


def test_quality_gate_covers_exactly_five_expanded_cuisines() -> None:
    assert quality.QUALITY_SAMPLE_COUNT == 5
    assert quality.EXPANSION_CUISINE_CODES == (
        "JAPANESE",
        "ITALIAN",
        "AMERICAN",
        "SOUTHEAST_ASIAN",
        "MEXICAN",
    )
    assert set(quality.QUALITY_CASE_LANGUAGES) == set(
        quality.EXPANSION_CUISINE_CODES
    )


def test_quality_batch_checks_korean_copy_and_price_band() -> None:
    batch = _batch(korean=False, price=15_000)
    for item in batch["recommendations"]:
        item["matched_criteria"] = []
        item["wiki_passages"] = []
    errors, _ = quality._validate_batch(
        batch,
        Scenario("price", _criteria(price_only=True)),
        language="한국어",
    )

    assert "KOREAN_GENERATED_COPY_MISSING" in errors
    assert "PRICE_CRITERIA_MISMATCH" in errors
    assert "WIKI_EVIDENCE_MISSING" in errors


def test_quality_batch_rejects_duplicate_identity_and_missing_criterion_evidence() -> None:
    batch = _batch()
    batch["recommendations"][1]["menu"]["menu_id"] = "menu-1"
    batch["recommendations"][1]["menu"]["merchant_id"] = "merchant-1"
    batch["recommendations"][0]["matched_criteria"] = []

    errors, _ = quality._validate_batch(
        batch,
        Scenario("single", _criteria()),
        language="English",
    )

    assert "DUPLICATE_MENU" in errors
    assert "DUPLICATE_MERCHANT" in errors
    assert "SELECTED_CRITERION_EVIDENCE_MISSING" in errors
