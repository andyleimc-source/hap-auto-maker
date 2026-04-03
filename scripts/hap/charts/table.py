"""透视表(13)。需要 xaxes + yaxisList。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    13: {
        "name": "透视表",
        "verified": False,
        "doc": "数据透视表。需要 xaxes + yaxisList。mergeCell=True, showRowList=True。",
    },
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)
    body["displaySetup"]["mergeCell"] = True
    body["displaySetup"]["showRowList"] = True
    return body
