"""基础图表: 柱图(1), 折线图(2)。

柱图 showChartType=1 竖向 / 2 横向。
折线图 showChartType=1 折线 / 2 面积(区域)。
"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    1: {"name": "柱图", "verified": True, "doc": "柱图。showChartType=1竖向/2横向(即条形图)。"},
    2: {"name": "折线图", "verified": True, "doc": "折线图。showChartType=1折线/2面积(区域图)。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    return base_body(chart, app_id, report_type)
