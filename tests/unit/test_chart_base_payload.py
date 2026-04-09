"""
tests/unit/test_chart_base_payload.py

验证图表通用 payload 构建层的关键兜底规则。
"""

import sys
from pathlib import Path

# 让 import 能找到 scripts/hap
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))

from charts._base import base_body


def _chart_with_two_yaxis(report_type: int) -> dict:
    return {
        "name": "状态与时间双轴",
        "desc": "测试",
        "worksheetId": "ws_1",
        "xaxes": {
            "controlId": "status_id",
            "controlType": 11,
            "controlName": "状态",
        },
        "yaxisList": [
            {"controlId": "record_count", "controlType": 10000000, "controlName": "记录数量"},
            {"controlId": "wfftime", "controlType": 16, "controlName": "剩余时间"},
        ],
    }


def test_single_axis_chart_trims_extra_yaxis():
    body = base_body(_chart_with_two_yaxis(report_type=1), app_id="app_1", report_type=1)
    assert body["reportType"] == 1
    assert len(body["yaxisList"]) == 1
    assert body["yaxisList"][0]["controlId"] == "record_count"


def test_dual_axis_chart_keeps_multiple_left_yaxis():
    body = base_body(_chart_with_two_yaxis(report_type=7), app_id="app_1", report_type=7)
    assert body["reportType"] == 7
    assert len(body["yaxisList"]) == 2
