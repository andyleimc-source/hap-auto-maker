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
