"""AI 节点: AI文本(31/531), AI数据对象(31/532), AI Agent(33/533)。

关键发现:
  - 所有 AI 节点不需要 isException
  - ai_text 需要 appId=""
  - ai_agent 需要 tools 数组
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "ai_text": {
        "typeId": 31, "actionId": "531", "appType": 46,
        "name": "AI 生成文本",
        "verified": False,
        "allowed": True,
        "doc": "需要 appId=''。不需要 isException。",
    },
    "ai_object": {
        "typeId": 31, "actionId": "532", "appType": 46,
        "name": "AI 生成数据对象",
        "verified": False,
        "allowed": False,
        "doc": "最小 body。不需要 isException。",
    },
    "ai_agent": {
        "typeId": 33, "actionId": "533", "appType": 48,
        "name": "AI Agent",
        "verified": False,
        "allowed": False,
        "doc": "需要 appId='' + tools 数组。tools.type: 1=工作表查询, 2=写入, 3=知识库, 4=其他。",
    },
}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict:
    spec = NODES[node_type]
    body = base_body(spec, process_id, node_id, name)
    body.pop("isException", None)

    if node_type == "ai_text":
        body["appId"] = ""
    elif node_type == "ai_agent":
        body["appId"] = ""
        body["tools"] = extra.get("tools", [])

    return body
