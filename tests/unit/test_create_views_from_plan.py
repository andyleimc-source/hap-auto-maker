"""
tests/unit/test_create_views_from_plan.py

create_views_from_plan.normalize_advanced_setting 的回归测试。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from executors.create_views_from_plan import (
    auto_complete_post_updates,
    build_update_payload,
    normalize_advanced_setting,
)


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


def test_gantt_auto_complete_returns_two_updates():
    view = {
        "viewType": 5,
        "begindate": "f_date1",
        "enddate": "f_date2",
    }
    updates = auto_complete_post_updates(view, ws_fields=[])
    assert len(updates) == 2
    assert updates[0]["editAdKeys"] == ["begindate", "enddate"]
    assert updates[0]["advancedSetting"]["begindate"] == "f_date1"
    assert updates[1]["advancedSetting"]["enddate"] == "f_date2"


def test_build_update_payload_exposes_gantt_dates_to_top_level():
    payload = build_update_payload(
        app_id="app1",
        worksheet_id="ws1",
        view_id="view1",
        update={
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["begindate", "enddate"],
            "advancedSetting": {"begindate": "f_date1", "enddate": "f_date2"},
        },
    )
    assert payload["advancedSetting"]["begindate"] == "f_date1"
    assert payload["advancedSetting"]["enddate"] == "f_date2"
    assert payload["begindate"] == "f_date1"
    assert payload["enddate"] == "f_date2"


def test_gantt_auto_complete_first_update_keeps_display_controls_when_present():
    view = {
        "viewType": 5,
        "begindate": "f_date1",
        "enddate": "f_date2",
        "displayControls": ["f_title", "f_owner", ""],
    }
    updates = auto_complete_post_updates(view, ws_fields=[])
    assert len(updates) == 2
    assert updates[0]["editAttrs"] == ["advancedSetting", "displayControls"]
    assert updates[0]["displayControls"] == ["f_title", "f_owner"]
