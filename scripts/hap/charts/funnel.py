"""漏斗图(5)。showPercent=True。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    5: {"name": "漏斗图", "verified": True, "doc": "showPercent=True。适合转化漏斗分析。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)
    body["displaySetup"]["showPercent"] = True
    return body
