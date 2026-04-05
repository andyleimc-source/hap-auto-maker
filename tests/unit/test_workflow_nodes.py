"""
tests/unit/test_workflow_nodes.py

workflow/nodes/ 各节点 build() 函数的单元测试。
验证节点参数构造的正确性，不需要网络。
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workflow"))

from nodes._base import base_body
from nodes import notify, flow_control, record_ops


# ---------------------------------------------------------------------------
# _base.base_body
# ---------------------------------------------------------------------------


class TestBaseBody:
    def test_required_fields_present(self):
        spec = {"typeId": 27}
        body = base_body(spec, "proc-1", "node-1", "测试节点")
        assert body["processId"] == "proc-1"
        assert body["flowNodeType"] == 27
        assert body["nodeId"] == "node-1"
        assert body["name"] == "测试节点"
        assert body["isException"] is True

    def test_action_id_included_when_in_spec(self):
        spec = {"typeId": 11, "actionId": "202", "appType": 3}
        body = base_body(spec, "p", "n", "邮件")
        assert body["actionId"] == "202"
        assert body["appType"] == 3

    def test_action_id_absent_when_not_in_spec(self):
        spec = {"typeId": 27}
        body = base_body(spec, "p", "n", "通知")
        assert "actionId" not in body


# ---------------------------------------------------------------------------
# notify.build
# ---------------------------------------------------------------------------


class TestNotifyBuild:
    def _build(self, node_type, extra=None):
        return notify.build(node_type, "proc-1", "node-1", "ws-1", "通知", extra or {})

    def test_notify_uses_send_content(self):
        body = self._build("notify", {"content": "你好"})
        assert body["sendContent"] == "你好"
        assert "content" not in body

    def test_push_uses_send_content(self):
        body = self._build("push", {"content": "推送消息"})
        assert body["sendContent"] == "推送消息"
        assert "content" not in body

    def test_sms_uses_content(self):
        body = self._build("sms", {"content": "短信内容"})
        assert body["content"] == "短信内容"
        assert "sendContent" not in body

    def test_email_uses_content_and_title(self):
        body = self._build("email", {"content": "正文", "title": "主题"})
        assert body["content"] == "正文"
        assert body["title"] == "主题"
        assert "sendContent" not in body

    def test_accounts_set_from_extra(self):
        accounts = [{"type": 6, "roleId": "uaid"}]
        body = self._build("notify", {"accounts": accounts})
        assert body["accounts"] == accounts

    def test_accounts_defaults_to_empty_list(self):
        body = self._build("notify", {})
        assert body["accounts"] == []

    def test_notify_flow_node_type_is_27(self):
        body = self._build("notify")
        assert body["flowNodeType"] == 27

    def test_email_flow_node_type_is_11(self):
        body = self._build("email")
        assert body["flowNodeType"] == 11


# ---------------------------------------------------------------------------
# flow_control.build
# ---------------------------------------------------------------------------


class TestFlowControlBuild:
    def _build(self, node_type, extra=None):
        return flow_control.build(
            node_type, "proc-1", "node-1", "ws-1", "节点", extra or {}
        )

    def test_subprocess_returns_none(self):
        result = self._build("subprocess")
        assert result is None

    def test_branch_no_is_exception(self):
        body = self._build("branch")
        assert "isException" not in body

    def test_branch_has_gateway_type(self):
        body = self._build("branch", {"gatewayType": 2})
        assert body["gatewayType"] == 2

    def test_branch_gateway_type_defaults_to_1(self):
        body = self._build("branch", {})
        assert body["gatewayType"] == 1

    def test_branch_condition_has_operate_condition(self):
        cond = [{"fieldId": "f1", "operate": 2, "value": "foo"}]
        body = self._build("branch_condition", {"operateCondition": cond})
        assert body["operateCondition"] == cond

    def test_branch_condition_defaults_empty(self):
        body = self._build("branch_condition", {})
        assert body["operateCondition"] == []

    def test_abort_no_is_exception(self):
        body = self._build("abort")
        assert "isException" not in body

    def test_loop_has_sub_process_fields(self):
        body = self._build("loop")
        assert "subProcessId" in body
        assert "subProcessName" in body
        assert body["flowNodeType"] == 29

    def test_branch_flow_ids_initialized(self):
        body = self._build("branch")
        assert body["flowIds"] == []


# ---------------------------------------------------------------------------
# record_ops.build
# ---------------------------------------------------------------------------


class TestRecordOpsBuild:
    def _build(self, node_type, extra=None):
        return record_ops.build(
            node_type, "proc-1", "node-1", "ws-1", "操作", extra or {}
        )

    def test_delete_record_returns_body(self):
        # typeId=6，build() 直接返回 body（delete_record 现已实现）
        result = self._build("delete_record")
        assert result is not None
        assert result["flowNodeType"] == 6
        assert result["actionId"] == "3"

    def test_get_record_returns_body(self):
        result = self._build("get_record")
        assert result is not None
        assert result["flowNodeType"] == 6
        assert result["actionId"] == "4"

    def test_get_records_returns_body(self):
        body = self._build("get_records")
        assert body is not None
        assert body["flowNodeType"] == 13

    def test_get_records_has_pagination_defaults(self):
        body = self._build("get_records")
        assert body["filters"] == []
        assert body["sorts"] == []
        assert body["number"] == 50

    def test_get_records_worksheet_id_in_body(self):
        result = record_ops.build("get_records", "p", "n", "ws-abc", "查询", {})
        assert result["appId"] == "ws-abc"


# ---------------------------------------------------------------------------
# allowed 字段存在性
# ---------------------------------------------------------------------------

from nodes import record_ops, notify, timer, approval, human, flow_control, compute, developer, ai as ai_nodes


class TestAllowedFieldPresent:
    """每个节点定义必须包含 allowed 字段（True 或 False）。"""

    def _check_module(self, module):
        for node_type, spec in module.NODES.items():
            assert "allowed" in spec, (
                f"{module.__name__}.NODES[{node_type!r}] 缺少 'allowed' 字段"
            )
            assert isinstance(spec["allowed"], bool), (
                f"{module.__name__}.NODES[{node_type!r}]['allowed'] 必须是 bool"
            )

    def test_record_ops_nodes_have_allowed(self):
        self._check_module(record_ops)

    def test_notify_nodes_have_allowed(self):
        self._check_module(notify)

    def test_timer_nodes_have_allowed(self):
        self._check_module(timer)

    def test_approval_nodes_have_allowed(self):
        self._check_module(approval)

    def test_human_nodes_have_allowed(self):
        self._check_module(human)

    def test_flow_control_nodes_have_allowed(self):
        self._check_module(flow_control)

    def test_compute_nodes_have_allowed(self):
        self._check_module(compute)

    def test_developer_nodes_have_allowed(self):
        self._check_module(developer)

    def test_ai_nodes_have_allowed(self):
        self._check_module(ai_nodes)


class TestAllowedValues:
    """验证 allowed=True 的节点集合符合预期。"""

    def test_allowed_node_set(self):
        from nodes import NODE_REGISTRY
        allowed = {nt for nt, s in NODE_REGISTRY.items() if s.get("allowed")}
        expected = {"delete_record", "get_record", "notify", "branch", "branch_condition", "ai_text"}
        assert allowed == expected, f"allowed 节点集合不符: got={allowed}, want={expected}"
