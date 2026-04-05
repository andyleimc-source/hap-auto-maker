"""开发者节点: JSON解析(21), 代码块(14), API请求(8)。

关键发现:
  - 代码块(14)和API请求(8)初始状态不需要 saveNode，返回 None
  - JSON解析需要 jsonContent + controls
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "json_parse": {
        "typeId": 21, "actionId": "510", "appType": 18,
        "name": "JSON 解析",
        "verified": False,
        "allowed": False,
        "doc": "需要 jsonContent(JSON 字符串) + controls(输出字段定义)。",
    },
    "code_block": {
        "typeId": 14, "actionId": "102",
        "name": "代码块",
        "verified": False,
        "allowed": False,
        "doc": "saveNode 跳过（初始状态无需配置）。",
    },
    "api_request": {
        "typeId": 8, "appType": 7,
        "name": "发送自定义请求",
        "verified": False,
        "allowed": False,
        "doc": "saveNode 跳过（初始状态无需配置）。",
    },
}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict | None:
    spec = NODES[node_type]
    type_id = spec["typeId"]

    if type_id in (8, 14):
        return None

    body = base_body(spec, process_id, node_id, name)
    if type_id == 21:
        body["jsonContent"] = extra.get("jsonContent", "")
        body["controls"] = extra.get("controls", [])

    return body
