"""基础图表: 柱状图(1), 折线图(2), 条形图(7), 区域图(11)。

标准 xaxes + yaxisList 结构，无特殊配置。
"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    1: {"name": "柱状图", "verified": True, "doc": "默认图表类型。xaxes 为分类维度。"},
    2: {"name": "折线图", "verified": True, "doc": "适合趋势分析。xaxes 通常为日期字段(particleSizeType=1月/4日)。"},
    7: {"name": "条形图", "verified": False, "doc": "横向柱状图。"},
    11: {"name": "区域图", "verified": False, "doc": "带面积填充的折线图。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    return base_body(chart, app_id, report_type)
