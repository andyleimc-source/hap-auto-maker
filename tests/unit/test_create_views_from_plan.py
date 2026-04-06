"""
tests/unit/test_create_views_from_plan.py

create_views_from_plan.normalize_advanced_setting 的回归测试。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from executors.create_views_from_plan import normalize_advanced_setting


def test_groupsetting_dict_should_be_normalized_to_array_string():
    adv = {"groupsetting": {"controlId": "f_status", "isAsc": True}}
    out = normalize_advanced_setting("0", adv)
    assert isinstance(out.get("groupsetting"), str)
    parsed = json.loads(out["groupsetting"])
    assert isinstance(parsed, list)
    assert parsed and parsed[0]["controlId"] == "f_status"


def test_groupsetting_object_string_should_be_normalized_to_array_string():
    adv = {"groupsetting": '{"controlId":"f_status","isAsc":true}'}
    out = normalize_advanced_setting("0", adv)
    parsed = json.loads(out["groupsetting"])
    assert isinstance(parsed, list)
    assert parsed and parsed[0]["controlId"] == "f_status"
