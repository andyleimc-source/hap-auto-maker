import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))


def _worksheets_fixture():
    return {
        "ws1": {
            "worksheetId": "ws1",
            "worksheetName": "销售订单",
            "fields": [
                {"id": "f_date", "name": "订单日期", "controlType": 16},
                {"id": "f_type", "name": "互动类型", "controlType": 9},
                {"id": "f_num", "name": "订单金额", "controlType": 6},
            ],
        }
    }


def test_validate_plan_force_ctime_filter_range():
    from planners.plan_charts_gemini import validate_plan

    raw = {
        "charts": [
            {
                "name": "销售订单月趋势",
                "reportType": 2,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_date", "controlType": 16},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
                "filter": {
                    "filterRangeId": "f_date",
                    "filterRangeName": "订单日期",
                    "rangeType": 18,
                    "rangeValue": 365,
                    "today": True,
                },
            },
            {
                "name": "兜底数量图",
                "reportType": 10,
                "worksheetId": "ws1",
                "xaxes": {"controlId": ""},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
            {
                "name": "类型占比",
                "reportType": 3,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_type", "controlType": 9},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
        ]
    }

    validated = validate_plan(raw, _worksheets_fixture())
    chart = validated[0]
    assert chart["filter"]["filterRangeId"] == "ctime"
    assert chart["filter"]["filterRangeName"] == "创建时间"
    # 保留原有范围策略
    assert chart["filter"]["rangeType"] == 18
    assert chart["filter"]["rangeValue"] == 365
    assert chart["filter"]["today"] is True


def test_validate_plan_report_type_11_missing_righty_is_auto_filled():
    from planners.plan_charts_gemini import validate_plan

    raw = {
        "charts": [
            {
                "name": "互动类型对比",
                "reportType": 11,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_type", "controlType": 9},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
            {
                "name": "兜底数量图",
                "reportType": 10,
                "worksheetId": "ws1",
                "xaxes": {"controlId": ""},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
            {
                "name": "类型占比",
                "reportType": 3,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_type", "controlType": 9},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
        ]
    }

    validated = validate_plan(raw, _worksheets_fixture())
    chart = validated[0]
    assert chart["reportType"] == 11
    assert isinstance(chart.get("rightY"), dict)
    assert chart["rightY"]["yaxisList"][0]["controlId"] == "record_count"
    assert chart.get("yreportType") == 1


def test_validate_plan_report_type_11_invalid_righty_field_fallback_to_record_count():
    from planners.plan_charts_gemini import validate_plan

    raw = {
        "charts": [
            {
                "name": "互动类型对比",
                "reportType": 11,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_type", "controlType": 9},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
                "rightY": {
                    "reportType": 2,
                    "yaxisList": [{"controlId": "not_exists_field", "controlType": 6}],
                },
            },
            {
                "name": "兜底数量图",
                "reportType": 10,
                "worksheetId": "ws1",
                "xaxes": {"controlId": ""},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
            {
                "name": "类型占比",
                "reportType": 3,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_type", "controlType": 9},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
        ]
    }

    validated = validate_plan(raw, _worksheets_fixture())
    chart = validated[0]
    assert chart["rightY"]["yaxisList"][0]["controlId"] == "record_count"
    assert chart["rightY"]["yaxisList"][0]["controlType"] == 10000000


def test_validate_plan_non_11_chart_does_not_get_righty_injected():
    from planners.plan_charts_gemini import validate_plan

    raw = {
        "charts": [
            {
                "name": "客户类型分布",
                "reportType": 3,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_type", "controlType": 9},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
            {
                "name": "销售趋势",
                "reportType": 2,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_date", "controlType": 16},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
            {
                "name": "排行",
                "reportType": 16,
                "worksheetId": "ws1",
                "xaxes": {"controlId": "f_type", "controlType": 9},
                "yaxisList": [{"controlId": "record_count", "controlType": 10000000}],
            },
        ]
    }

    validated = validate_plan(raw, _worksheets_fixture())
    assert "rightY" not in validated[0]

