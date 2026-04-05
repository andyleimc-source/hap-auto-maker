"""双轴图(7), 对称条形图(11)。需要 rightY 结构和 yreportType。"""

from __future__ import annotations
from ._base import base_body, build_yaxis

CHARTS = {
    7: {
        "name": "双轴图",
        "verified": True,
        "doc": "reportType=7。有 rightY 结构 + yreportType。左轴 yaxisList，右轴 rightY.yaxisList。",
    },
    11: {
        "name": "对称条形图",
        "verified": True,
        "doc": "reportType=11。结构类似双轴图，有 rightY + yreportType。",
    },
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)
    yreport_type = chart.get("yreportType")
    if yreport_type is None:
        yreport_type = 1  # 默认左轴为柱图
    body["yreportType"] = yreport_type

    # rightY 结构：AI 有时误把 rightY 直接生成成 yaxisList 列表，做兼容处理
    right_y = chart.get("rightY", {})
    if isinstance(right_y, list):
        right_y = {"yaxisList": right_y}
    body["rightY"] = {
        "reportType": int(right_y.get("reportType", 2)),
        "display": right_y.get("display", {
            "isPerPile": False, "isPile": False, "isAccumulate": False,
            "accumulatePerPile": None,
            "ydisplay": {"showDial": True, "showTitle": False, "title": "",
                         "minValue": None, "maxValue": None, "lineStyle": 1, "showNumber": None},
        }),
        "splitId": right_y.get("splitId", ""),
        "split": right_y.get("split", {}),
        "summary": right_y.get("summary", {
            "controlId": "", "type": 1, "name": "总计", "number": True,
            "percent": False, "sum": 0, "contrastSum": 0, "contrastMapSum": 0, "rename": "",
        }),
        "yaxisList": [build_yaxis(y) for y in right_y.get("yaxisList", [])],
    }
    return body
