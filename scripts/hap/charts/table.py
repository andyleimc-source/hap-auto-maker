"""透视表/雷达图(8)。使用 pivotTable 结构。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    8: {
        "name": "透视表/雷达图",
        "verified": True,
        "doc": "reportType=8。透视表和雷达图共用，都用 pivotTable 结构(columns/lines/columnSummary/lineSummary)。xaxes 为空对象。",
    },
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)
    body["displaySetup"]["mergeCell"] = True
    body["displaySetup"]["showRowList"] = True
    body["xaxes"] = {}
    body["style"] = chart.get("style", {"paginationVisible": True})

    # pivotTable 结构
    pivot = chart.get("pivotTable")
    if pivot:
        body["pivotTable"] = pivot
    else:
        body["pivotTable"] = {
            "showColumnCount": 0, "showColumnTotal": True,
            "showLineCount": 0, "showLineTotal": True,
            "columns": [], "columnSummary": {},
            "lines": [], "lineSummary": {},
        }
    return body
