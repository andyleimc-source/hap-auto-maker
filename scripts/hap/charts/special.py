"""特殊图表: 词云图(14), 排行图(15), 地图(16), 关系图(17)。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    14: {"name": "词云图", "verified": False, "doc": "文本分析。xaxes 为文本字段。"},
    15: {"name": "排行图", "verified": False, "doc": "横向排名条形图。"},
    16: {"name": "地图", "verified": False, "doc": "需要地理字段（省/市）。"},
    17: {"name": "关系图", "verified": False, "doc": "层级关系可视化。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    return base_body(chart, app_id, report_type)
