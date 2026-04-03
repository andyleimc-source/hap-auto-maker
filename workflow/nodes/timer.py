"""延时节点 (typeId=12): 延时时长(301), 延时到日期(302), 延时到字段时间(303)。

关键发现:
  - actionId=301(时长): 时间值放在 saveNode body 根级别（numberFieldValue 等），actionId 也在根级别
  - actionId=302/303(到日期/到字段): 必须嵌套在 timerNode 对象内，根级别不设 actionId
  - FieldValue 结构: {"fieldValue": "静态值", "fieldNodeId": "", "fieldControlId": ""}
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "delay_duration": {
        "typeId": 12, "actionId": "301",
        "name": "延时一段时间",
        "verified": True,
        "doc": "天/时/分/秒通过 numberFieldValue/hour/minute/secondFieldValue 设置。值在根级别。",
    },
    "delay_until": {
        "typeId": 12, "actionId": "302",
        "name": "延时到指定日期",
        "verified": True,
        "doc": "timerNode 嵌套结构: {actionId, executeTimeType, number, unit, time}。",
    },
    "delay_field": {
        "typeId": 12, "actionId": "303",
        "name": "延时到字段时间",
        "verified": True,
        "doc": "timerNode 嵌套结构: {actionId, executeTimeType, number, unit, time}。",
    },
}

_EMPTY_FV = {"fieldValue": "", "fieldNodeId": "", "fieldControlId": ""}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict:
    spec = NODES[node_type]
    body = base_body(spec, process_id, node_id, name)
    # actionId 不由 base_body 设置（timer 特殊处理）
    action = spec.get("actionId", "301")
    body["actionId"] = action

    if action == "301":
        body["numberFieldValue"] = extra.get("numberFieldValue", dict(_EMPTY_FV))
        body["hourFieldValue"] = extra.get("hourFieldValue", dict(_EMPTY_FV))
        body["minuteFieldValue"] = extra.get("minuteFieldValue", dict(_EMPTY_FV))
        body["secondFieldValue"] = extra.get("secondFieldValue", dict(_EMPTY_FV))
    else:
        # 302/303: 参数必须嵌套在 timerNode 对象内，根级别不设 actionId
        del body["actionId"]
        body["timerNode"] = {
            "actionId": action,
            "executeTimeType": extra.get("executeTimeType", 0),
            "number": extra.get("number", 0),
            "unit": extra.get("unit", 1),
            "time": extra.get("time", "08:00"),
        }

    return body
