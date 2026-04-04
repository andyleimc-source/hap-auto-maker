"""通知类节点: 站内通知(27), 短信(10), 邮件(11), 界面推送(17)。

关键发现:
  - 站内通知(27)和界面推送(17)的内容字段是 sendContent，不是 content
  - 短信(10)和邮件(11)用 content
  - accounts 必填，常用触发者: type=6, roleId="uaid"
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "notify": {
        "typeId": 27,
        "name": "发送站内通知",
        "verified": True,
        "doc": "用 sendContent（非 content）。accounts 必填。",
    },
    "sms": {
        "typeId": 10,
        "name": "发送短信",
        "verified": False,
        "doc": "用 content。需要短信签名配置。",
    },
    "email": {
        "typeId": 11, "actionId": "202", "appType": 3,
        "name": "发送邮件",
        "verified": False,
        "doc": "用 content + title。需要邮件服务配置。",
    },
    "push": {
        "typeId": 17,
        "name": "界面推送",
        "verified": False,
        "doc": "用 sendContent（非 content）。accounts 必填。",
    },
}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict:
    spec = NODES[node_type]
    body = base_body(spec, process_id, node_id, name)
    body["accounts"] = extra.get("accounts", [])

    if node_type in ("notify", "push"):
        # 优先用 sendContent，兼容旧的 content 字段名
        body["sendContent"] = extra.get("sendContent") or extra.get("content", "")
    elif node_type == "email":
        body["title"] = extra.get("title", "")
        body["content"] = extra.get("sendContent") or extra.get("content", "")
    else:  # sms
        body["content"] = extra.get("sendContent") or extra.get("content", "")

    return body
