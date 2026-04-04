"""饼图/环形图(3)。

饼图和环形图共用 reportType=3，通过 showChartType 区分。
showPercent 建议设为 True。xaxes 为分类维度。
"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    3: {"name": "饼图/环形图", "verified": True, "doc": "饼图/环形图。showChartType 区分饼/环。showPercent=True。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)
    body["displaySetup"]["showPercent"] = True
    return body
