import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))


def test_normalize_view_plan_fast_filters_minimal_payload():
    from pipeline_tableview_filters_v2 import normalize_view_plan

    field_map = {
        "f_status": {"id": "f_status", "name": "状态", "type": 9, "isDropdown": True},
        "f_type": {"id": "f_type", "name": "类型", "type": 11, "isDropdown": True},
    }
    fields = list(field_map.values())
    views_by_id = {"v1": {"viewId": "v1", "viewType": "0"}}

    item = {
        "viewId": "v1",
        "needFastFilters": True,
        "fastFilters": [
            {"controlId": "f_status", "filterType": 2, "advancedSetting": {"allowitem": "2", "showtype": "2"}},
            {"controlId": "f_status", "filterType": 1},
            {"controlId": "f_type", "advancedSetting": {"allowitem": "1"}},
            {"controlId": "not_exists"},
        ],
    }

    normalized = normalize_view_plan(item, field_map, fields, views_by_id)
    assert normalized is not None
    assert normalized["needFastFilters"] is True
    assert normalized["fastFilters"] == [{"controlId": "f_status"}, {"controlId": "f_type"}]


def test_save_view_fast_filters_omit_empty_advanced_setting():
    import pipeline_tableview_filters_v2 as mod

    captured = {}

    def fake_save(app_id, worksheet_id, view_id, payload, auth_config_path, dry_run):
        captured["payload"] = payload
        return {"state": 1}

    mod._save_view_request = fake_save
    mod.save_view_fast_filters(
        app_id="app1",
        worksheet_id="ws1",
        view_id="view1",
        plan={"fastFilters": [{"controlId": "f_status"}], "fastAdvancedSetting": {}, "fastEditAdKeys": []},
        auth_config_path=Path("config/credentials/auth_config.py"),
        dry_run=True,
    )

    payload = captured["payload"]
    assert payload["editAttrs"] == ["fastFilters"]
    assert "advancedSetting" not in payload
    assert "editAdKeys" not in payload


def test_save_view_fast_filters_keep_advanced_setting_when_explicit():
    import pipeline_tableview_filters_v2 as mod

    captured = {}

    def fake_save(app_id, worksheet_id, view_id, payload, auth_config_path, dry_run):
        captured["payload"] = payload
        return {"state": 1}

    mod._save_view_request = fake_save
    mod.save_view_fast_filters(
        app_id="app1",
        worksheet_id="ws1",
        view_id="view1",
        plan={
            "fastFilters": [{"controlId": "f_status"}],
            "fastAdvancedSetting": {"enablebtn": "1"},
            "fastEditAdKeys": ["enablebtn"],
        },
        auth_config_path=Path("config/credentials/auth_config.py"),
        dry_run=True,
    )

    payload = captured["payload"]
    assert payload["editAttrs"] == ["fastFilters", "advancedSetting"]
    assert payload["advancedSetting"] == {"enablebtn": "1"}
    assert payload["editAdKeys"] == ["enablebtn"]
