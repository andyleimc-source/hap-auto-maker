"""
tests/unit/test_workflow_planner.py

validate_structure_plan 和 validate_node_config 的单元测试。
不需要网络。
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from planning.workflow_planner import validate_structure_plan, validate_node_config


def _make_ws_by_id(ws_id="ws1", fields=None):
    return {
        ws_id: {
            "worksheetId": ws_id,
            "name": "任务表",
            "fields": fields or [
                {"id": "f1", "type": 2, "name": "标题"},
                {"id": "f2", "type": 9, "name": "状态"},
                {"id": "f3", "type": 26, "name": "负责人"},
            ],
        }
    }


def _make_structure_plan(ws_id="ws1", worksheet_events=None, custom_actions=None):
    """注意: action_nodes 里 type 字段必须是 'type'，不是 'node_type'。"""
    return {
        "worksheets": [
            {
                "worksheet_id": ws_id,
                "worksheet_events": worksheet_events or [
                    {
                        "name": "新增通知",
                        "trigger_type": "add",
                        "action_nodes": [{"type": "notify", "name": "通知", "sendContent": "有新记录"}],
                    }
                ],
                "custom_actions": custom_actions or [],
            }
        ],
        "time_triggers": [],
    }


class TestWorkflowValidateStructurePlan:
    def test_valid_plan_passes(self):
        plan = _make_structure_plan()
        result = validate_structure_plan(plan, _make_ws_by_id())
        assert "worksheets" in result

    def test_non_list_worksheets_raises(self):
        with pytest.raises(ValueError):
            validate_structure_plan({"worksheets": "not_a_list"}, {})

    def test_missing_worksheet_id_raises(self):
        plan = {"worksheets": [{"worksheet_events": []}]}
        with pytest.raises(ValueError, match="worksheet_id"):
            validate_structure_plan(plan, _make_ws_by_id())

    def test_disallowed_node_type_filtered(self):
        """不在 allowed 列表中的 type 应被过滤出 action_nodes。"""
        plan = _make_structure_plan(worksheet_events=[{
            "name": "工作流",
            "trigger_type": "add",
            "action_nodes": [
                {"type": "notify", "name": "通知", "sendContent": "通知内容"},
                {"type": "sms", "name": "短信"},   # sms 不在 allowed 中
            ],
        }])
        result = validate_structure_plan(plan, _make_ws_by_id())
        events = result["worksheets"][0]["worksheet_events"]
        if events:
            node_types = [n.get("type") for n in events[0]["action_nodes"]]
            assert "sms" not in node_types

    def test_workflow_with_all_disallowed_nodes_removed(self):
        """所有节点都不在 allowed 的工作流应从规划中移除。"""
        plan = _make_structure_plan(worksheet_events=[{
            "name": "全禁工作流",
            "trigger_type": "add",
            "action_nodes": [{"type": "sms", "name": "短信"}],
        }])
        result = validate_structure_plan(plan, _make_ws_by_id())
        events = result["worksheets"][0]["worksheet_events"]
        assert len(events) == 0

    def test_empty_time_triggers_handled(self):
        plan = _make_structure_plan()
        result = validate_structure_plan(plan, _make_ws_by_id())
        assert result.get("time_triggers") == []

    def test_returns_same_object(self):
        plan = _make_structure_plan()
        result = validate_structure_plan(plan, _make_ws_by_id())
        assert result is plan


class TestValidateNodeConfig:
    def _plan(self, nodes, ws_id="ws1"):
        return {
            "worksheets": [{
                "worksheet_id": ws_id,
                "worksheet_events": [{"name": "测试", "trigger_type": "add", "action_nodes": nodes}],
                "custom_actions": [],
            }],
            "time_triggers": [],
        }

    def test_missing_worksheets_raises(self):
        with pytest.raises(ValueError, match="缺少 worksheets"):
            validate_node_config({}, {})

    def test_missing_worksheet_id_raises(self):
        plan = {"worksheets": [{"worksheet_events": []}]}
        with pytest.raises(ValueError, match="worksheet_id"):
            validate_node_config(plan, {})

    def test_notify_with_send_content_passes(self):
        plan = self._plan([{"type": "notify", "name": "通知", "sendContent": "你有新任务", "accounts": []}])
        assert validate_node_config(plan, _make_ws_by_id()) is not None

    def test_notify_missing_send_content_raises(self):
        plan = self._plan([{"type": "notify", "name": "通知", "sendContent": ""}])
        with pytest.raises(ValueError, match="sendContent"):
            validate_node_config(plan, _make_ws_by_id())

    def test_add_record_with_valid_fields_passes(self):
        plan = self._plan([{
            "type": "add_record",
            "target_worksheet_id": "ws1",
            "fields": [
                {"fieldId": "f1", "fieldValue": "测试"},
                {"fieldId": "f2", "fieldValue": "进行中"},
            ],
        }])
        assert validate_node_config(plan, _make_ws_by_id()) is not None

    def test_add_record_too_few_fields_raises(self):
        plan = self._plan([{
            "type": "add_record",
            "target_worksheet_id": "ws1",
            "fields": [{"fieldId": "f1", "fieldValue": "值"}],
        }])
        with pytest.raises(ValueError):
            validate_node_config(plan, _make_ws_by_id())

    def test_add_record_invalid_field_id_raises(self):
        plan = self._plan([{
            "type": "add_record",
            "target_worksheet_id": "ws1",
            "fields": [
                {"fieldId": "f_bad1", "fieldValue": "值"},
                {"fieldId": "f_bad2", "fieldValue": "值"},
            ],
        }])
        with pytest.raises(ValueError, match="fieldId"):
            validate_node_config(plan, _make_ws_by_id())

    def test_time_trigger_with_trigger_reference_raises(self):
        plan = {
            "worksheets": [{"worksheet_id": "ws1", "worksheet_events": [], "custom_actions": []}],
            "time_triggers": [{
                "name": "定时",
                "action_nodes": [{
                    "type": "update_record",
                    "fields": [{"fieldId": "f1", "fieldValue": "{{trigger.record_id}}"}],
                }],
            }],
        }
        with pytest.raises(ValueError, match="触发引用"):
            validate_node_config(plan, _make_ws_by_id())
