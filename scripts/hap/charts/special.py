"""特殊图表: 行政区划图(9), 词云图(13), 排行图(16), 地图(17)。"""

from __future__ import annotations
from ._base import base_body

CHARTS = {
    9: {"name": "行政区划图", "verified": True, "doc": "reportType=9。需 country 字段和地区(controlType=24)维度。style.isDrillDownLayer=True。"},
    13: {"name": "词云图", "verified": True, "doc": "reportType=13。文本/单选分析。xaxes 为文本或单选字段。"},
    16: {"name": "排行图", "verified": True, "doc": "reportType=16。横向排名条形图。style.topStyle='crown', sorts=[{record_count:2}]降序。"},
    17: {"name": "地图", "verified": True, "doc": "reportType=17。地理分布地图。需 country 字段和地区(controlType=24)维度。支持 split 分组。"},
}


def build(report_type: int, chart: dict, app_id: str) -> dict:
    body = base_body(chart, app_id, report_type)

    if report_type == 16:
        # 排行图: 皇冠样式 + 降序排列
        body["style"] = {"topStyle": "crown", "valueProgressVisible": True}
        body["sorts"] = [{"record_count": 2}]

    if report_type in (9, 17):
        # 行政区划图和地图: country 配置
        body["country"] = chart.get("country", {
            "filterCode": "", "filterCodeName": "",
            "municipality": False, "particleSizeType": 1,
        })

    if report_type == 9:
        # 行政区划图: 下钻
        body["style"] = {"isDrillDownLayer": True}

    return body
