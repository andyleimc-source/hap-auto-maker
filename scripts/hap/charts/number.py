"""数值图(10), 进度图(12)。xaxes.controlId 设为 null。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    10: {
        "name": "数值图",
        "verified": True,
        "doc": "xaxes.controlId=null, cid='null-1'。只需 yaxisList。适合 KPI 展示。",
    },
    12: {
        "name": "进度图",
        "verified": False,
        "doc": "单值进度条。同数值图，xaxes.controlId=null。",
    },
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)
    # 数值图不需要 xaxes 维度
    body["xaxes"]["controlId"] = None
    body["xaxes"]["cid"] = "null-1"
    body["xaxes"]["c_Id"] = "null-1"
    body["xaxes"]["controlName"] = ""
    body["xaxes"]["cname"] = ""
    return body
