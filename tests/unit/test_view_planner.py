"""
tests/unit/test_view_planner.py

validate_structure_plan 和 validate_view_plan 的单元测试。
不需要网络，不需要真实 API。
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from planning.view_planner import validate_structure_plan, validate_view_plan


# ── 测试数据辅助 ──────────────────────────────────────────────────────────────

def _make_ws_by_id(ws_id="ws1", fields=None):
    return {
        ws_id: {
            "worksheetId": ws_id,
            "name": "测试表",
            "fields": fields or [
                {"id": "f1", "type": 2, "name": "标题"},
                {"id": "f2", "type": 9, "name": "状态"},
                {"id": "f3", "type": 15, "name": "日期"},
                {"id": "f4", "type": 26, "name": "负责人"},
            ],
        }
    }


def _make_plan(ws_id="ws1", views=None):
    return {
        "worksheets": [
            {
                "worksheetId": ws_id,
                "views": views or [{"viewType": 0, "name": "表格视图", "sortFields": []}],
            }
        ]
    }


# ── validate_structure_plan ───────────────────────────────────────────────────

class TestValidateStructurePlan:
    def test_valid_plan_passes(self):
        plan = _make_plan()
        result = validate_structure_plan(plan, _make_ws_by_id())
        assert "worksheets" in result

    def test_missing_worksheets_raises(self):
        with pytest.raises(ValueError, match="缺少 worksheets"):
            validate_structure_plan({}, {})

    def test_empty_worksheets_raises(self):
        with pytest.raises(ValueError, match="缺少 worksheets"):
            validate_structure_plan({"worksheets": []}, {})

    def test_invalid_view_type_string_raises(self):
        plan = _make_plan(views=[{"viewType": "invalid", "name": "x"}])
        with pytest.raises(ValueError, match="viewType"):
            validate_structure_plan(plan, _make_ws_by_id())

    def test_view_type_as_string_int_accepted(self):
        # "0" 应被接受（可转为 int）
        plan = _make_plan(views=[{"viewType": "0", "name": "表格"}])
        result = validate_structure_plan(plan, _make_ws_by_id())
        assert result is not None

    def test_view_type_coerced_to_int(self):
        plan = _make_plan(views=[{"viewType": "0", "name": "表格"}])
        validate_structure_plan(plan, _make_ws_by_id())
        assert plan["worksheets"][0]["views"][0]["viewType"] == 0

    def test_views_not_list_raises(self):
        plan = {"worksheets": [{"worksheetId": "ws1", "views": "not_a_list"}]}
        with pytest.raises(ValueError):
            validate_structure_plan(plan, _make_ws_by_id())

    def test_unknown_view_type_raises(self):
        plan = _make_plan(views=[{"viewType": 999, "name": "未知"}])
        with pytest.raises(ValueError, match="viewType"):
            validate_structure_plan(plan, _make_ws_by_id())


# ── validate_view_plan ────────────────────────────────────────────────────────

class TestValidateViewPlan:
    def test_valid_table_view_passes(self):
        plan = _make_plan(views=[{"viewType": 0, "name": "表格", "sortFields": []}])
        result = validate_view_plan(plan, _make_ws_by_id())
        assert result is not None

    def test_missing_worksheets_raises(self):
        with pytest.raises(ValueError, match="缺少 worksheets"):
            validate_view_plan({}, {})

    def test_unknown_worksheet_id_skipped(self):
        # worksheets_by_id 里没有 unknown_ws，应跳过校验而不是报错
        plan = _make_plan(ws_id="unknown_ws")
        result = validate_view_plan(plan, {})
        assert result is not None

    def test_display_controls_pruned_if_field_missing(self):
        # displayControls 中引用了不存在的字段，应被移除
        ws_by_id = _make_ws_by_id(fields=[{"id": "f1", "type": 2, "name": "标题"}])
        plan = _make_plan(views=[{
            "viewType": 0,
            "name": "表格",
            "displayControls": ["f1", "f_nonexistent"],
        }])
        result = validate_view_plan(plan, ws_by_id)
        dc = result["worksheets"][0]["views"][0]["displayControls"]
        assert "f1" in dc
        assert "f_nonexistent" not in dc

    def test_view_control_cleared_if_field_missing(self):
        ws_by_id = _make_ws_by_id(fields=[{"id": "f1", "type": 2, "name": "标题"}])
        plan = _make_plan(views=[{
            "viewType": 1,
            "name": "看板",
            "viewControl": "f_nonexistent",
        }])
        result = validate_view_plan(plan, ws_by_id)
        vc = result["worksheets"][0]["views"][0]["viewControl"]
        assert vc == ""

    def test_view_control_kept_if_field_exists(self):
        ws_by_id = _make_ws_by_id(fields=[
            {"id": "f1", "type": 2, "name": "标题"},
            {"id": "f2", "type": 9, "name": "状态"},
        ])
        plan = _make_plan(views=[{
            "viewType": 1,
            "name": "看板",
            "viewControl": "f2",
        }])
        result = validate_view_plan(plan, ws_by_id)
        vc = result["worksheets"][0]["views"][0]["viewControl"]
        assert vc == "f2"

    def test_invalid_view_type_raises(self):
        plan = _make_plan(views=[{"viewType": 999, "name": "未知"}])
        with pytest.raises(ValueError, match="viewType"):
            validate_view_plan(plan, _make_ws_by_id())
