"""数值图(10), 仪表盘(14), 进度图(15)。xaxes.controlId 为空。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    10: {
        "name": "数值图",
        "verified": True,
        "doc": "reportType=10。KPI 数字展示。xaxes 可有维度分组，也可为空。",
    },
    14: {
        "name": "仪表盘",
        "verified": True,
        "doc": "reportType=14。仪表盘。config.min/max 设置范围，showChartType=3。xaxes 为空。",
    },
    15: {
        "name": "进度图",
        "verified": True,
        "doc": "reportType=15。进度条/环形/水波图。config.targetList 设置目标值。xaxes 为空。",
    },
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)

    if report_type in (14, 15):
        # 仪表盘和进度图不需要 xaxes 维度
        body["xaxes"]["controlId"] = ""
        body["xaxes"]["cid"] = ""
        body["xaxes"]["c_Id"] = ""
        body["xaxes"]["controlName"] = ""
        body["xaxes"]["cname"] = ""
        body["xaxes"]["controlType"] = 0

    if report_type == 10:
        # 数值图可以有 xaxes 也可以没有
        x_cid = body["xaxes"].get("controlId", "")
        if not x_cid:
            body["xaxes"]["controlId"] = ""
            body["xaxes"]["cid"] = ""
            body["xaxes"]["c_Id"] = ""

    if report_type == 14:
        # 仪表盘特殊：showChartType=3, config.min/max
        body["displaySetup"]["showChartType"] = 3
        body["config"] = chart.get("config", {"targetList": [], "min": None, "max": None})

    if report_type == 15:
        # 进度图特殊：config.targetList
        body["config"] = chart.get("config", {"min": None, "max": None, "targetList": []})

    return body
