"""饼图(3), 环形图(4)。

showPercent 建议设为 True。xaxes 为分类维度。
"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    3: {"name": "饼图", "verified": True, "doc": "showPercent=True。xaxes 为分类维度。"},
    4: {"name": "环形图", "verified": False, "doc": "同饼图，中心留空。showPercent=True。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)
    body["displaySetup"]["showPercent"] = True
    return body
