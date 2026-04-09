"""tests/unit/test_view_configurator.py — 视图配置生成校验"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))

FIELDS = [
    {"id": "f_title", "name": "标题", "type": 2},
    {"id": "f_status", "name": "订单状态", "type": 11, "options": [
        {"key": "o1", "value": "待付款"}, {"key": "o2", "value": "已付款"},
    ]},
    {"id": "f_date1", "name": "下单日期", "type": 15},
    {"id": "f_date2", "name": "发货日期", "type": 16},
    {"id": "f_member", "name": "负责人", "type": 26},
]

FIELD_IDS = {f["id"] for f in FIELDS}


class TestValidateConfig:
    def test_valid_kanban_config(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 1,
            "name": "状态看板",
            "viewControl": "f_status",
            "advancedSetting": {"enablerules": "1"},
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is not None
        assert result["viewControl"] == "f_status"

    def test_invalid_field_id_discards_view(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 1,
            "name": "看板",
            "viewControl": "nonexistent_field",
            "advancedSetting": {},
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is None

    def test_unknown_advanced_setting_key_removed(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 4,
            "name": "日历",
            "advancedSetting": {
                "enablerules": "1",
                "bogus_key": "should_be_removed",
            },
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is not None
        assert "bogus_key" not in result.get("advancedSetting", {})

    def test_gantt_config_valid(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 5,
            "name": "甘特图",
            "advancedSetting": {},
            "postCreateUpdates": [{
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["begindate", "enddate"],
                "advancedSetting": {"begindate": "f_date1", "enddate": "f_date2"},
            }],
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is not None

    def test_post_create_updates_invalid_field_drops_entry(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 5,
            "name": "甘特图",
            "advancedSetting": {},
            "postCreateUpdates": [{
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["begindate", "enddate"],
                "advancedSetting": {"begindate": "bad_id", "enddate": "f_date2"},
            }],
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is not None
        pcu = result.get("postCreateUpdates", [])
        for entry in pcu:
            ads = entry.get("advancedSetting", {})
            for v in ads.values():
                if isinstance(v, str) and v and not v.startswith("["):
                    assert v in FIELD_IDS or v == ""

    def test_resource_post_create_keeps_non_field_advanced_setting_values(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 7,
            "name": "资源视图",
            "viewControl": "f_member",
            "advancedSetting": {},
            "postCreateUpdates": [
                {
                    "editAttrs": ["viewControl", "advancedSetting"],
                    "viewControl": "f_member",
                    "editAdKeys": ["navfilters", "navshow"],
                    "advancedSetting": {"navshow": "0", "navfilters": "[]"},
                },
                {
                    "editAttrs": ["advancedSetting"],
                    "editAdKeys": ["begindate", "enddate"],
                    "advancedSetting": {"begindate": "f_date1", "enddate": "f_date2"},
                },
            ],
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is not None
        pcu = result.get("postCreateUpdates", [])
        assert len(pcu) == 2
        assert pcu[0]["advancedSetting"]["navshow"] == "0"
        assert pcu[0]["advancedSetting"]["navfilters"] == "[]"
        assert pcu[0]["viewControl"] == "f_member"
