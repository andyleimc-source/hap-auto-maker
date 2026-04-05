"""运算节点 (typeId=9): 数值运算(100), 从工作表汇总(107)。

关键发现:
  - 数值运算实测可创建+saveNode+publish
  - 汇总节点需要 appId 指向目标工作表
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "calc": {
        "typeId": 9, "actionId": "100",
        "name": "数值运算",
        "verified": True,
        "allowed": False,
        "doc": "需要 formulaMap + formulaValue + fieldValue。",
    },
    "aggregate": {
        "typeId": 9, "actionId": "107", "appType": 1,
        "name": "从工作表汇总", "needs_worksheet": True,
        "verified": False,
        "allowed": False,
        "doc": "需要 appId 指向目标工作表。formulaValue + fieldValue。",
    },
}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict:
    spec = NODES[node_type]
    body = base_body(spec, process_id, node_id, name)

    if node_type == "calc":
        body["formulaMap"] = extra.get("formulaMap", {})
        body["formulaValue"] = extra.get("formulaValue", "")
        body["fieldValue"] = extra.get("fieldValue", "")
    elif node_type == "aggregate":
        if worksheet_id:
            body["appId"] = worksheet_id
        body["formulaValue"] = extra.get("formulaValue", "")
        body["fieldValue"] = extra.get("fieldValue", "")

    return body
