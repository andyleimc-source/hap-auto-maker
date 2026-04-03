"""散点图(9)。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    9: {"name": "散点图", "verified": False, "doc": "二维数据分布。xaxes + yaxisList 均为数值型。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    return base_body(chart, app_id, report_type)
