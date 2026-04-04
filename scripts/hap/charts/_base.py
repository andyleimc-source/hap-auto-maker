"""统计图通用构建工具 — 从 create_charts_from_plan.py 提取。"""

from __future__ import annotations
from datetime import datetime


def base_display_setup(report_type: int, xaxes: dict) -> dict:
    """通用 displaySetup，根据图表类型自动调整。"""
    x_control_name = str(xaxes.get("controlName", "")).strip()
    setup = {
        "isPerPile": False,
        "isPile": False,
        "isAccumulate": False,
        "accumulatePerPile": None,
        "isToday": False,
        "isLifecycle": False,
        "lifecycleValue": 0,
        "contrastType": 0,
        "fontStyle": 1,
        "showTotal": False,
        "showTitle": True,
        "showLegend": True,
        "legendType": 1,
        "showDimension": True,
        "showNumber": True,
        "showPercent": report_type in {3, 6},
        "showXAxisCount": 0,
        "showChartType": 1,
        "showPileTotal": True,
        "hideOverlapText": False,
        "showRowList": True,
        "showControlIds": [],
        "auxiliaryLines": [],
        "showOptionIds": [],
        "contrast": False,
        "colorRules": [],
        "percent": {"enable": False, "type": 2, "dot": "2", "dotFormat": "1", "roundType": 2},
        "mergeCell": True,
        "previewUrl": None,
        "imageUrl": None,
        "xdisplay": {
            "showDial": True, "showTitle": False, "title": x_control_name,
            "minValue": None, "maxValue": None,
        },
        "xaxisEmpty": False,
        "ydisplay": {
            "showDial": True, "showTitle": False, "title": "记录数量",
            "minValue": None, "maxValue": None, "lineStyle": 1, "showNumber": None,
        },
    }
    if report_type == 10:
        setup["showLegend"] = False
        setup["showDimension"] = False
    if report_type == 13:
        setup["mergeCell"] = True
        setup["showRowList"] = True
    return setup


def build_xaxes(xaxes: dict) -> dict:
    """构建 xaxes payload。"""
    control_id = str(xaxes.get("controlId", "")).strip()
    control_type = int(xaxes.get("controlType", 16) or 16)
    control_name = str(xaxes.get("controlName", "")).strip()
    cid = f"{control_id}-1"
    return {
        "controlId": control_id,
        "sortType": int(xaxes.get("sortType", 0) or 0),
        "particleSizeType": int(xaxes.get("particleSizeType", 0) or 0),
        "rename": str(xaxes.get("rename", "") or ""),
        "emptyType": int(xaxes.get("emptyType", 0) or 0),
        "fields": None, "subTotal": False, "subTotalName": None,
        "showFormat": "4", "displayMode": "text",
        "controlName": control_name, "controlType": control_type,
        "dataSource": "", "options": [], "advancedSetting": {},
        "relationControl": None,
        "cid": cid, "cname": control_name,
        "xaxisEmptyType": int(xaxes.get("xaxisEmptyType", 0) or 0),
        "xaxisEmpty": bool(xaxes.get("xaxisEmpty", False)),
        "c_Id": cid,
    }


def build_yaxis(y: dict) -> dict:
    """构建单个 yaxis payload。"""
    control_id = str(y.get("controlId", "record_count")).strip()
    control_name = str(y.get("controlName", "记录数量")).strip()
    control_type = int(y.get("controlType", 10000000) or 10000000)
    return {
        "controlId": control_id, "controlName": control_name, "controlType": control_type,
        "magnitude": 0, "roundType": 2, "dotFormat": "1", "suffix": "", "ydot": 2,
        "fixType": 0, "showNumber": True, "hide": False,
        "percent": {"enable": False, "type": 2, "dot": "2", "dotFormat": "1", "roundType": 2},
        "normType": 5, "emptyShowType": 0, "dot": 0,
        "rename": str(y.get("rename", "") or ""),
        "advancedSetting": {},
    }


def base_body(chart: dict, app_id: str, report_type: int) -> dict:
    """构建所有图表类型共用的 saveReportConfig body。"""
    name = str(chart.get("name", "")).strip()
    desc = str(chart.get("desc", "") or "").strip()
    xaxes_raw = chart.get("xaxes", {})
    yaxis_list_raw = chart.get("yaxisList", [])

    _DEFAULT_FILTER = {
        "filterRangeId": "ctime", "filterRangeName": "创建时间",
        "rangeType": 18, "rangeValue": 365, "today": True,
    }
    filter_cfg = chart.get("filter") or _DEFAULT_FILTER
    if not isinstance(filter_cfg, dict):
        filter_cfg = _DEFAULT_FILTER
    filter_cfg.setdefault("filterRangeId", "ctime")
    filter_cfg.setdefault("filterRangeName", "创建时间")
    filter_cfg.setdefault("rangeType", 0)
    filter_cfg.setdefault("rangeValue", 0)
    filter_cfg.setdefault("today", False)

    return {
        "splitId": "",
        "split": {},
        "displaySetup": base_display_setup(report_type, xaxes_raw),
        "name": name,
        "desc": desc,
        "reportType": report_type,
        "filter": filter_cfg,
        "createdDate": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account": {"accountId": "", "fullName": None, "avatar": None, "status": None},
        "appId": str(chart.get("worksheetId", "") or app_id).strip() or app_id,
        "appType": 1,
        "sorts": [],
        "summary": {
            "controlId": "", "type": 1, "name": "总计", "number": True,
            "percent": False, "sum": 0, "contrastSum": 0, "contrastMapSum": 0,
            "rename": "",
        },
        "style": {},
        "formulas": [],
        "views": chart.get("views", []),
        "auth": 1,
        "yreportType": None,
        "yaxisList": [build_yaxis(y) for y in yaxis_list_raw],
        "xaxes": build_xaxes(xaxes_raw),
        "sourceType": 1,
        "isPublic": True,
        "id": str(chart.get("id", "") or "").strip(),
        "version": "6.5",
    }
