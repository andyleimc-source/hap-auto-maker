"""
tests/unit/test_workflow_planner.py

workflow_planner / constraints 的单元测试。
不需要网络，不需要 AI。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workflow"))


class TestGetNodeConstraintsAllowed:
    """get_node_constraints() 必须在每个节点信息里包含 allowed 字段。"""

    def test_allowed_field_present_in_all_types(self):
        from planning.constraints import get_node_constraints
        c = get_node_constraints()
        for nt, spec in c["types"].items():
            assert "allowed" in spec, f"节点 {nt!r} 缺少 allowed 字段"
            assert isinstance(spec["allowed"], bool), f"节点 {nt!r} allowed 必须是 bool"

    def test_allowed_types_list_correct(self):
        from planning.constraints import get_node_constraints
        c = get_node_constraints()
        allowed = {nt for nt, s in c["types"].items() if s["allowed"]}
        expected = {"delete_record", "get_record", "notify", "branch", "branch_condition", "ai_text"}
        assert allowed == expected


class TestBuildNodeTypePromptSection:
    """prompt 生成函数只列出 allowed=True 的节点，禁用节点不出现在文本里。"""

    def test_allowed_nodes_in_prompt(self):
        from planning.constraints import build_node_type_prompt_section
        prompt = build_node_type_prompt_section()
        for name in ["notify", "branch", "ai_text", "delete_record", "get_record"]:
            assert name in prompt, f"allowed 节点 {name!r} 不在 prompt 里"

    def test_disallowed_nodes_not_in_prompt(self):
        from planning.constraints import build_node_type_prompt_section
        prompt = build_node_type_prompt_section()
        for name in ["sms", "email", "loop", "subprocess", "calc", "code_block", "approval"]:
            assert name not in prompt, f"禁用节点 {name!r} 出现在 prompt 里"


class TestValidateStructurePlanFiltering:
    """validate_structure_plan 应过滤禁用节点，空 action_nodes 的工作流被移除。"""

    def _make_plan(self, nodes: list) -> dict:
        return {
            "worksheets": [
                {
                    "worksheet_id": "aaa111bbb222ccc333ddd444",
                    "worksheet_name": "测试表",
                    "custom_actions": [
                        {
                            "name": "动作1",
                            "confirm_msg": "确认?",
                            "sure_name": "确认",
                            "cancel_name": "取消",
                            "action_nodes": nodes,
                        }
                    ],
                    "worksheet_events": [],
                    "date_triggers": [],
                }
            ],
            "time_triggers": [],
        }

    def test_disallowed_node_is_removed(self):
        from planning.workflow_planner import validate_structure_plan
        plan = self._make_plan([
            {"name": "通知", "type": "notify", "target_worksheet_id": "aaa111bbb222ccc333ddd444"},
            {"name": "短信", "type": "sms", "target_worksheet_id": "aaa111bbb222ccc333ddd444"},
        ])
        result = validate_structure_plan(plan, {})
        nodes = result["worksheets"][0]["custom_actions"][0]["action_nodes"]
        types = [n["type"] for n in nodes]
        assert "sms" not in types
        assert "notify" in types

    def test_all_disallowed_removes_workflow(self):
        from planning.workflow_planner import validate_structure_plan
        plan = self._make_plan([
            {"name": "循环", "type": "loop", "target_worksheet_id": "aaa111bbb222ccc333ddd444"},
        ])
        result = validate_structure_plan(plan, {})
        assert result["worksheets"][0]["custom_actions"] == []

    def test_allowed_nodes_pass_through(self):
        from planning.workflow_planner import validate_structure_plan
        plan = self._make_plan([
            {"name": "通知", "type": "notify", "target_worksheet_id": "aaa111bbb222ccc333ddd444"},
            {"name": "分支", "type": "branch", "target_worksheet_id": "aaa111bbb222ccc333ddd444"},
        ])
        result = validate_structure_plan(plan, {})
        nodes = result["worksheets"][0]["custom_actions"][0]["action_nodes"]
        assert len(nodes) == 2

    def test_time_trigger_disallowed_node_removed(self):
        from planning.workflow_planner import validate_structure_plan
        plan = {
            "worksheets": [],
            "time_triggers": [
                {
                    "name": "定时",
                    "action_nodes": [
                        {"name": "循环", "type": "loop"},
                        {"name": "通知", "type": "notify"},
                    ],
                }
            ],
        }
        result = validate_structure_plan(plan, {})
        nodes = result["time_triggers"][0]["action_nodes"]
        assert len(nodes) == 1
        assert nodes[0]["type"] == "notify"

    def test_time_trigger_all_disallowed_removed(self):
        from planning.workflow_planner import validate_structure_plan
        plan = {
            "worksheets": [],
            "time_triggers": [
                {
                    "name": "定时",
                    "action_nodes": [
                        {"name": "循环", "type": "loop"},
                    ],
                }
            ],
        }
        result = validate_structure_plan(plan, {})
        assert result["time_triggers"] == []
