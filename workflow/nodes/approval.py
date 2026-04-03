"""审批节点 (typeId=26)。

关键发现:
  - 可创建 + 配置 accounts，但 publish 校验需要 processNode 子流程完整配置
  - 当前 publish 验证状态: 创建成功但 publish 报 warn 103
  - accounts 用触发者: type=6, roleId="uaid"
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "approval": {
        "typeId": 26, "appType": 10,
        "name": "未命名审批流程",
        "verified": False,  # 创建成功但 publish 报 103
        "doc": "可创建和配置 accounts，但 publish 需要 processNode 子流程。待研究。",
    },
}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict:
    spec = NODES[node_type]
    body = base_body(spec, process_id, node_id, name)
    body["accounts"] = extra.get("accounts", [])
    body["formProperties"] = extra.get("formProperties", [])
    body["flowIds"] = []
    return body
