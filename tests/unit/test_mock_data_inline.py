"""
tests/unit/test_mock_data_inline.py

mock_data_inline 模块的单元测试。不需要网络。
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))


class TestComputeNewRecordCount:
    """compute_new_record_count(ws_id, relation_pairs, relation_edges) -> int"""

    def _make_pair(self, a_id, b_id, pair_type, edges=None):
        return {
            "worksheetAId": a_id,
            "worksheetBId": b_id,
            "pairType": pair_type,
            "edges": edges or [],
        }

    def _make_edge(self, source_id, target_id, sub_type):
        return {
            "sourceWorksheetId": source_id,
            "targetWorksheetId": target_id,
            "subType": sub_type,
        }

    def test_no_relation_returns_5(self):
        from planners.mock_data_inline import compute_new_record_count
        assert compute_new_record_count("ws_a", [], []) == 5

    def test_1n_detail_end_sub_type_1_returns_10(self):
        """明细端（单选 Relation，subType=1）→ 6 条"""
        from planners.mock_data_inline import compute_new_record_count
        edges = [self._make_edge("ws_detail", "ws_master", sub_type=1)]
        pairs = [self._make_pair("ws_master", "ws_detail", "1-N", edges=edges)]
        assert compute_new_record_count("ws_detail", pairs, edges) == 10

    def test_1n_master_end_sub_type_2_returns_5(self):
        """主表端（聚合 Relation，subType=2）→ 3 条"""
        from planners.mock_data_inline import compute_new_record_count
        edges = [self._make_edge("ws_master", "ws_detail", sub_type=2)]
        pairs = [self._make_pair("ws_master", "ws_detail", "1-N", edges=edges)]
        assert compute_new_record_count("ws_master", pairs, edges) == 5

    def test_1_1_relation_returns_5(self):
        """1:1 关系 → 5 条"""
        from planners.mock_data_inline import compute_new_record_count
        pairs = [self._make_pair("ws_a", "ws_b", "1-1")]
        assert compute_new_record_count("ws_a", pairs, []) == 5

    def test_no_matching_pair_returns_5(self):
        """有 pair 但 ws_id 不在其中 → 5 条"""
        from planners.mock_data_inline import compute_new_record_count
        pairs = [self._make_pair("ws_x", "ws_y", "1-N")]
        assert compute_new_record_count("ws_z", pairs, []) == 5


class TestApplyRelationPhase:
    """apply_relation_phase 的 round-robin 分配逻辑测试（dry_run=True，不发网络请求）"""

    def _make_schema(self, ws_id, ws_name, relation_fields):
        """relation_fields: [{"fieldId": ..., "type": "Relation", "dataSource": target_ws_id, "subType": 1}]"""
        return {
            "worksheetId": ws_id,
            "worksheetName": ws_name,
            "fields": relation_fields,
            "writableFields": [],
            "skippedFields": [],
        }

    def test_dry_run_returns_summary(self):
        """dry_run=True 时不发请求，返回 summary 结构"""
        from planners.mock_data_inline import apply_relation_phase

        # 订单（主表，3条）→ 订单明细（明细端，6条）
        edges = [
            {"sourceWorksheetId": "ws_detail", "targetWorksheetId": "ws_master", "subType": 1},
        ]
        pairs = [
            {
                "worksheetAId": "ws_master",
                "worksheetBId": "ws_detail",
                "pairType": "1-N",
                "edges": edges,
            }
        ]
        ws_schemas = [
            self._make_schema("ws_master", "订单", []),
            self._make_schema(
                "ws_detail",
                "订单明细",
                [{"fieldId": "rel_f1", "name": "订单", "type": "Relation",
                  "dataSource": "ws_master", "subType": 1}],
            ),
        ]
        all_row_ids = {
            "ws_master": ["r1", "r2", "r3", "r4", "r5"],
            "ws_detail": ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8", "d9", "d10"],
        }
        result = apply_relation_phase(
            app_id="app1",
            app_key="key",
            sign="sign",
            base_url="https://api.mingdao.com",
            relation_pairs=pairs,
            relation_edges=edges,
            all_row_ids=all_row_ids,
            worksheet_schemas=ws_schemas,
            dry_run=True,
        )
        # dry_run 时 ws_detail 应被处理，ws_master 跳过
        assert "ws_detail" in result
        assert result["ws_detail"]["planned"] == 10
        assert "ws_master" not in result  # 主表跳过

    def test_round_robin_assignment(self):
        """验证 round-robin 分配：6条明细 → 3条主表，循环分配"""
        from planners.mock_data_inline import _build_relation_assignments
        source_ids = ["d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8", "d9", "d10"]
        target_ids = ["r1", "r2", "r3", "r4", "r5"]
        assignments = _build_relation_assignments(source_ids, target_ids)
        assert assignments == [
            ("d1", "r1"), ("d2", "r2"), ("d3", "r3"), ("d4", "r4"), ("d5", "r5"),
            ("d6", "r1"), ("d7", "r2"), ("d8", "r3"), ("d9", "r4"), ("d10", "r5"),
        ]
