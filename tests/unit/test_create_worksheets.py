"""
tests/unit/test_create_worksheets.py

build_field_payload 和 split_fields 的单元测试。
不需要网络。
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from executors.create_worksheets_from_plan import build_field_payload, split_fields


class TestBuildFieldPayload:
    def test_text_title_field_has_is_title(self):
        field = {"name": "标题", "type": "Text"}
        payload = build_field_payload(field, is_first_text_title=True)
        assert payload["name"] == "标题"
        assert payload["type"] == "Text"
        assert payload.get("isTitle") == 1

    def test_non_title_text_field_no_is_title(self):
        field = {"name": "备注", "type": "Text"}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload.get("isTitle") != 1

    def test_single_select_has_options(self):
        field = {
            "name": "状态",
            "type": "SingleSelect",
            "option_values": ["待处理", "进行中", "已完成"],
        }
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["type"] == "SingleSelect"
        assert len(payload.get("options", [])) == 3

    def test_number_field_has_dot(self):
        field = {"name": "数量", "type": "Number"}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["type"] == "Number"
        assert "dot" in payload

    def test_number_dot_custom(self):
        field = {"name": "金额", "type": "Number", "dot": 0}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["dot"] == 0

    def test_date_field_type_preserved(self):
        field = {"name": "创建日期", "type": "Date"}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["type"] == "Date"

    def test_collaborator_subtype_zero(self):
        field = {"name": "负责人", "type": "Collaborator"}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["type"] == "Collaborator"
        assert payload.get("subType") == 0

    def test_collaborator_not_required(self):
        field = {"name": "负责人", "type": "Collaborator", "required": True}
        payload = build_field_payload(field, is_first_text_title=False)
        # Collaborator 强制不必填
        assert payload["required"] is False or payload["required"] == 0


class TestSplitFields:
    def test_basic_fields_in_normal(self):
        fields = [
            {"name": "标题", "type": "Text"},
            {"name": "状态", "type": "SingleSelect"},
        ]
        normal, relation, deferred = split_fields(fields)
        assert len(normal) == 2
        assert relation == []

    def test_relation_fields_separated(self):
        fields = [
            {"name": "标题", "type": "Text"},
            {"name": "关联项目", "type": "Relation", "relate_worksheet": "ws2"},
        ]
        normal, relation, deferred = split_fields(fields)
        assert len(relation) == 1
        assert relation[0]["name"] == "关联项目"

    def test_deferred_type_separated(self):
        # AutoNumber 不在白名单，应 deferred
        fields = [
            {"name": "标题", "type": "Text"},
            {"name": "编号", "type": "AutoNumber"},
        ]
        normal, relation, deferred = split_fields(fields)
        assert len(deferred) == 1

    def test_returns_three_lists(self):
        result = split_fields([])
        assert len(result) == 3
        assert all(isinstance(r, list) for r in result)

    def test_empty_fields_adds_default_title(self):
        """空字段列表时自动补标题字段。"""
        normal, relation, deferred = split_fields([])
        assert len(normal) == 1
        assert normal[0].get("isTitle") == 1

    def test_first_text_field_becomes_title(self):
        fields = [{"name": "任务名", "type": "Text"}]
        normal, relation, deferred = split_fields(fields)
        assert normal[0].get("isTitle") == 1
