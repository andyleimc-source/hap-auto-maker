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

    def test_no_relation_returns_3(self):
        from planners.mock_data_inline import compute_new_record_count
        assert compute_new_record_count("ws_a", [], []) == 3

    def test_1n_detail_end_sub_type_1_returns_6(self):
        """明细端（单选 Relation，subType=1）→ 6 条"""
        from planners.mock_data_inline import compute_new_record_count
        edges = [self._make_edge("ws_detail", "ws_master", sub_type=1)]
        pairs = [self._make_pair("ws_master", "ws_detail", "1-N", edges=edges)]
        assert compute_new_record_count("ws_detail", pairs, edges) == 6

    def test_1n_master_end_sub_type_2_returns_3(self):
        """主表端（聚合 Relation，subType=2）→ 3 条"""
        from planners.mock_data_inline import compute_new_record_count
        edges = [self._make_edge("ws_master", "ws_detail", sub_type=2)]
        pairs = [self._make_pair("ws_master", "ws_detail", "1-N", edges=edges)]
        assert compute_new_record_count("ws_master", pairs, edges) == 3

    def test_1_1_relation_returns_3(self):
        """1:1 关系 → 3 条"""
        from planners.mock_data_inline import compute_new_record_count
        pairs = [self._make_pair("ws_a", "ws_b", "1-1")]
        assert compute_new_record_count("ws_a", pairs, []) == 3

    def test_no_matching_pair_returns_3(self):
        """有 pair 但 ws_id 不在其中 → 3 条"""
        from planners.mock_data_inline import compute_new_record_count
        pairs = [self._make_pair("ws_x", "ws_y", "1-N")]
        assert compute_new_record_count("ws_z", pairs, []) == 3
