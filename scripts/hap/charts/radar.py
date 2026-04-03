"""雷达图(6)。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    6: {"name": "雷达图", "verified": False, "doc": "多维度对比分析。xaxes 为维度，yaxisList 为度量。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    return base_body(chart, app_id, report_type)
