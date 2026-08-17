from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "yobi_recommendation_query_plan",
    SCRIPTS / "recommendation_query_plan.py",
)
assert SPEC and SPEC.loader
query_plan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = query_plan
SPEC.loader.exec_module(query_plan)


def test_oracle_index_inventory_queries_every_required_v2_index() -> None:
    source = inspect.getsource(query_plan._oracle_plan)

    for index_name in query_plan.EXPECTED_INDEXES:
        assert f"'{index_name}'" in source


def test_oracle_plan_accepts_feature_and_membership_index_access() -> None:
    object_names = {
        "CONCEPT_PREFERENCE_SUPPORT",
        "IDX_MENU_PREF_FEATURE_LOOKUP",
        "IDX_MENU_CONCEPT_MEMBERSHIP_LOOKUP",
        "MENU",
        "MERCHANT",
    }

    assert query_plan._oracle_required_tables_planned(object_names)


def test_oracle_plan_rejects_missing_feature_and_membership_access() -> None:
    object_names = {
        "CONCEPT_PREFERENCE_SUPPORT",
        "MENU",
        "MERCHANT",
    }

    assert not query_plan._oracle_required_tables_planned(object_names)


def test_oracle_plan_still_requires_every_other_table_explicitly() -> None:
    object_names = {
        "CONCEPT_PREFERENCE_SUPPORT",
        "IDX_MENU_PREF_FEATURE_LOOKUP",
        "IDX_MENU_CONCEPT_MEMBERSHIP_LOOKUP",
        "MERCHANT",
    }

    assert not query_plan._oracle_required_tables_planned(object_names)
