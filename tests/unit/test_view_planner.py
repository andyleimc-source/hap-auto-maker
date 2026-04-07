"""
tests/unit/test_view_planner.py

validate_structure_plan 和 validate_view_plan 的单元测试。
不需要网络，不需要真实 API。
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from planning.view_planner import validate_structure_plan, validate_view_plan, suggest_views
from planning.constraints import classify_fields


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


# ── suggest_views ─────────────────────────────────────────────────────────────

def _fields(*specs):
    """Build a minimal fields list. Each spec: (id, type, name, options=None)."""
    result = []
    for spec in specs:
        fid, ftype, fname = spec[0], spec[1], spec[2]
        f = {"id": fid, "type": ftype, "name": fname}
        if len(spec) > 3:
            f["options"] = spec[3]
        result.append(f)
    return result


class TestSuggestViews:
    # ── 看板收窄：优先级/等级不再触发看板 ────────────────────────────────────

    def test_kanban_not_triggered_by_priority_field(self):
        """「优先级」是分级字段，不应触发看板。"""
        fields = _fields(("f1", 9, "优先级"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "任务列表")
        view_types = [s["viewType"] for s in result]
        assert 1 not in view_types, "优先级字段不应触发看板"

    def test_kanban_not_triggered_by_urgency_field(self):
        """「紧急程度」是分级字段，不应触发看板。"""
        fields = _fields(("f1", 11, "紧急程度"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "问题单")
        view_types = [s["viewType"] for s in result]
        assert 1 not in view_types, "紧急程度字段不应触发看板"

    def test_kanban_not_triggered_by_risk_level_field(self):
        """「风险等级」是分级字段，不应触发看板。"""
        fields = _fields(("f1", 11, "风险等级"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "风险管理")
        view_types = [s["viewType"] for s in result]
        assert 1 not in view_types, "风险等级字段不应触发看板"

    def test_kanban_triggered_by_status_field(self):
        """「状态」字段应触发看板。"""
        fields = _fields(("f1", 9, "状态"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "任务管理")
        view_types = [s["viewType"] for s in result]
        assert 1 in view_types, "状态字段应触发看板"

    def test_kanban_triggered_by_stage_field(self):
        """「阶段」字段应触发看板。"""
        fields = _fields(("f1", 11, "阶段"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "项目管理")
        view_types = [s["viewType"] for s in result]
        assert 1 in view_types, "阶段字段应触发看板"

    def test_kanban_triggered_by_approval_field(self):
        """「审批状态」字段应触发看板。"""
        fields = _fields(("f1", 9, "审批状态"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "合同管理")
        view_types = [s["viewType"] for s in result]
        assert 1 in view_types, "审批状态字段应触发看板"

    # ── 日历：任意日期字段就触发（去掉工作表名限制）────────────────────────

    def test_calendar_triggered_by_any_date_field(self):
        """任何工作表，只要有日期字段，就应触发日历候选。"""
        fields = _fields(("f1", 15, "创建日期"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "员工档案")
        view_types = [s["viewType"] for s in result]
        assert 4 in view_types, "有日期字段就应触发日历候选"

    def test_calendar_uses_date_field_id(self):
        """日历候选应携带正确的 calendarcid 字段 ID。"""
        fields = _fields(("date_f1", 15, "截止日期"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "任务管理")
        cal = next((s for s in result if s["viewType"] == 4), None)
        assert cal is not None
        assert cal.get("calendarcid") == "date_f1"

    def test_no_calendar_without_date_field(self):
        """没有日期字段时不应触发日历。"""
        fields = _fields(("f1", 2, "标题"), ("f2", 9, "状态"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "活动日程")
        view_types = [s["viewType"] for s in result]
        assert 4 not in view_types

    # ── 甘特图：两个日期字段就触发（去掉工作表名限制）─────────────────────

    def test_gantt_triggered_by_two_date_fields_any_ws(self):
        """任何工作表，只要有两个日期字段，就触发甘特候选。"""
        fields = _fields(("f1", 15, "签约日期"), ("f2", 15, "到期日期"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "合同管理")
        view_types = [s["viewType"] for s in result]
        assert 5 in view_types, "两个日期字段应触发甘特候选"

    def test_gantt_not_triggered_by_one_date_field(self):
        """只有一个日期字段时不触发甘特图。"""
        fields = _fields(("f1", 15, "截止日期"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "任务管理")
        view_types = [s["viewType"] for s in result]
        assert 5 not in view_types

    def test_gantt_uses_correct_field_ids(self):
        """甘特候选应携带 begindate 和 enddate 字段 ID。"""
        fields = _fields(("start_f", 15, "开始日期"), ("end_f", 16, "结束日期"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "项目计划")
        gantt = next((s for s in result if s["viewType"] == 5), None)
        assert gantt is not None
        assert gantt.get("begindate") == "start_f"
        assert gantt.get("enddate") == "end_f"

    # ── 资源视图：成员字段 + 两个日期字段 ──────────────────────────────────

    def test_resource_triggered_by_member_and_two_dates(self):
        """成员字段 + 两个日期字段应触发资源视图候选。"""
        fields = _fields(
            ("m1", 26, "负责人"),
            ("d1", 15, "开始日期"),
            ("d2", 15, "结束日期"),
        )
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "任务管理")
        view_types = [s["viewType"] for s in result]
        assert 7 in view_types, "成员+两日期应触发资源视图"

    def test_resource_not_triggered_without_member_field(self):
        """没有成员字段时不触发资源视图。"""
        fields = _fields(("d1", 15, "开始日期"), ("d2", 15, "结束日期"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "任务管理")
        view_types = [s["viewType"] for s in result]
        assert 7 not in view_types

    def test_resource_not_triggered_with_only_one_date(self):
        """只有一个日期字段时不触发资源视图（需要 begindate + enddate）。"""
        fields = _fields(("m1", 26, "负责人"), ("d1", 15, "截止日期"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "任务管理")
        view_types = [s["viewType"] for s in result]
        assert 7 not in view_types

    def test_resource_carries_correct_field_ids(self):
        """资源候选应携带 viewControl（成员字段）和 begindate/enddate。"""
        fields = _fields(
            ("m1", 26, "负责人"),
            ("d1", 15, "开始日期"),
            ("d2", 16, "截止日期"),
        )
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "排班表")
        res = next((s for s in result if s["viewType"] == 7), None)
        assert res is not None
        assert res.get("viewControl") == "m1"
        assert res.get("begindate") == "d1"
        assert res.get("enddate") == "d2"

    # ── 地图视图：type=40 才触发，type=24（地区）不够 ─────────────────────

    def test_map_triggered_by_location_type_40(self):
        """type=40 定位字段应触发地图视图。"""
        fields = _fields(("loc1", 40, "位置"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "门店管理")
        view_types = [s["viewType"] for s in result]
        assert 8 in view_types

    def test_map_not_triggered_by_area_type_24(self):
        """type=24 地区字段（省市区）不应触发地图视图。"""
        fields = _fields(("area1", 24, "所在地区"))
        classified = classify_fields(fields)
        result = suggest_views(classified, "ws1", "门店管理")
        view_types = [s["viewType"] for s in result]
        assert 8 not in view_types
