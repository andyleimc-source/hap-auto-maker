"""散点图(12)。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    12: {"name": "散点图", "verified": True, "doc": "reportType=12。二维数据分布。yaxisList 至少 2-3 个指标。支持 split 分组。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    return base_body(chart, app_id, report_type)
