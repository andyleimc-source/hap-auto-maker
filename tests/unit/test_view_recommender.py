"""tests/unit/test_view_recommender.py — 硬约束过滤 + 推荐校验"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))


# ── 测试数据 ──────────────────────────────────────────────────────────────────

FIELDS_FULL = [
    {"id": "f_title", "name": "标题", "type": 2},
    {"id": "f_status", "name": "订单状态", "type": 11, "options": [
        {"key": "o1", "value": "待付款"}, {"key": "o2", "value": "已付款"},
        {"key": "o3", "value": "已发货"}, {"key": "o4", "value": "已完成"},
    ]},
    {"id": "f_date1", "name": "下单日期", "type": 15},
    {"id": "f_date2", "name": "发货日期", "type": 16},
    {"id": "f_member", "name": "负责人", "type": 26},
    {"id": "f_photo", "name": "商品图片", "type": 14},
    {"id": "f_loc", "name": "收货定位", "type": 40},
    {"id": "f_doc", "name": "合同文件", "type": 14},
]

FIELDS_MINIMAL = [
    {"id": "f_title", "name": "标题", "type": 2},
    {"id": "f_num", "name": "金额", "type": 6},
]


class TestHardConstraints:
    def test_full_fields_all_types_available(self):
        from planners.view_recommender import get_available_view_types
        available = get_available_view_types(FIELDS_FULL)
        assert 0 in available  # 表格分组：有单选
        assert 1 in available  # 看板：有单选
        assert 3 in available  # 画廊：有图片附件
        assert 4 in available  # 日历：有日期
        assert 5 in available  # 甘特：有2个日期
        assert 7 in available  # 资源：有成员+2日期
        assert 8 in available  # 地图：有定位

    def test_minimal_fields_no_views(self):
        from planners.view_recommender import get_available_view_types
        available = get_available_view_types(FIELDS_MINIMAL)
        assert len(available) == 0

    def test_gallery_excludes_doc_attachment(self):
        from planners.view_recommender import get_available_view_types
        fields = [
            {"id": "f1", "name": "标题", "type": 2},
            {"id": "f2", "name": "合同文件", "type": 14},
        ]
        available = get_available_view_types(fields)
        assert 3 not in available

    def test_gallery_includes_image_attachment(self):
        from planners.view_recommender import get_available_view_types
        fields = [
            {"id": "f1", "name": "标题", "type": 2},
            {"id": "f2", "name": "产品图片", "type": 14},
        ]
        available = get_available_view_types(fields)
        assert 3 in available

    def test_gantt_needs_two_dates(self):
        from planners.view_recommender import get_available_view_types
        fields = [
            {"id": "f1", "name": "标题", "type": 2},
            {"id": "f2", "name": "日期", "type": 15},
        ]
        available = get_available_view_types(fields)
        assert 4 in available
        assert 5 not in available

    def test_resource_needs_member_and_two_dates(self):
        from planners.view_recommender import get_available_view_types
        fields = [
            {"id": "f1", "name": "标题", "type": 2},
            {"id": "f2", "name": "开始", "type": 15},
            {"id": "f3", "name": "结束", "type": 16},
        ]
        available = get_available_view_types(fields)
        assert 7 not in available

    def test_no_detail_view(self):
        from planners.view_recommender import get_available_view_types
        available = get_available_view_types(FIELDS_FULL)
        assert 6 not in available


class TestValidateRecommendation:
    def test_valid_recommendation_passes(self):
        from planners.view_recommender import validate_recommendation
        rec = {
            "views": [
                {"viewType": 1, "name": "状态看板", "reason": "有状态流转"},
                {"viewType": 4, "name": "订单日历", "reason": "按日期浏览"},
            ]
        }
        available = {0, 1, 3, 4, 5, 7, 8}
        result = validate_recommendation(rec, available)
        assert len(result["views"]) == 2

    def test_disallowed_type_dropped(self):
        from planners.view_recommender import validate_recommendation
        rec = {
            "views": [
                {"viewType": 1, "name": "看板", "reason": "..."},
                {"viewType": 8, "name": "地图", "reason": "..."},
            ]
        }
        available = {0, 1, 4}
        result = validate_recommendation(rec, available)
        assert len(result["views"]) == 1
        assert result["views"][0]["viewType"] == 1

    def test_duplicate_type_keeps_first(self):
        from planners.view_recommender import validate_recommendation
        rec = {
            "views": [
                {"viewType": 1, "name": "看板1", "reason": "..."},
                {"viewType": 1, "name": "看板2", "reason": "..."},
            ]
        }
        available = {1}
        result = validate_recommendation(rec, available)
        assert len(result["views"]) == 1
        assert result["views"][0]["name"] == "看板1"

    def test_max_seven_views(self):
        from planners.view_recommender import validate_recommendation
        rec = {
            "views": [{"viewType": i, "name": f"v{i}", "reason": "..."} for i in [0, 1, 3, 4, 5, 7, 8, 0]]
        }
        available = {0, 1, 3, 4, 5, 7, 8}
        result = validate_recommendation(rec, available)
        assert len(result["views"]) <= 7

    def test_empty_views_accepted(self):
        from planners.view_recommender import validate_recommendation
        rec = {"views": []}
        result = validate_recommendation(rec, {0, 1})
        assert result["views"] == []
