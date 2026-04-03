"""双轴图(8)。需要 yreportType 指定第二轴图表类型。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    8: {
        "name": "双轴图",
        "verified": False,
        "doc": "需要 yreportType（第二轴类型: 1=柱状, 2=折线）。yaxisList 至少 2 项。",
    },
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)
    yreport_type = chart.get("yreportType")
    if yreport_type is None:
        yreport_type = 2  # 默认第二轴为折线图
    body["yreportType"] = yreport_type
    return body
