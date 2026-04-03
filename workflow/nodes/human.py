"""人工参与节点: 填写(3), 抄送(5)。

关键发现:
  - 抄送(5)内容字段用 sendContent（同通知节点），实测已验证
  - 填写(3)需要 formProperties 定义可填字段
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "fill": {
        "typeId": 3,
        "name": "填写",
        "verified": False,
        "doc": "需要 formProperties 定义哪些字段可填写。accounts 指定填写人。",
    },
    "copy": {
        "typeId": 5,
        "name": "抄送",
        "verified": True,
        "doc": "用 sendContent。accounts 必填。实测可 publish。",
    },
}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict:
    spec = NODES[node_type]
    body = base_body(spec, process_id, node_id, name)
    body["accounts"] = extra.get("accounts", [])
    body["flowIds"] = []

    if node_type == "fill":
        body["formProperties"] = extra.get("formProperties", [])
    elif node_type == "copy":
        body["sendContent"] = extra.get("content", "")

    return body
