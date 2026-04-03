"""流程控制节点: 分支(1), 条件(2), 循环(29), 中止(30), 子流程(16)。

关键发现:
  - 分支(1)和中止(30)不需要 isException
  - 分支条件(2)的 operateCondition 为空=所有数据通过
  - 循环(29)会自动创建子流程
  - 子流程(16)的 saveNode 被跳过（初始状态无需配置）
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "branch": {
        "typeId": 1,
        "name": "分支",
        "verified": False,
        "doc": "gatewayType: 1=互斥, 2=并行。需配置 operateCondition 才能 publish。",
    },
    "branch_condition": {
        "typeId": 2,
        "name": "分支条件",
        "verified": False,
        "doc": "operateCondition 为条件规则列表，空数组=所有数据通过。",
    },
    "loop": {
        "typeId": 29, "actionId": "210", "appType": 45,
        "name": "满足条件时循环", "needs_relation": True,
        "verified": False,
        "doc": "自动创建子流程。actionId: 210=条件循环, 211=遍历列表, 212=遍历查询。",
    },
    "abort": {
        "typeId": 30, "actionId": "2",
        "name": "中止流程",
        "verified": False,
        "doc": "无需 isException。",
    },
    "subprocess": {
        "typeId": 16,
        "name": "子流程",
        "verified": False,
        "doc": "saveNode 跳过（初始状态无需配置）。",
    },
}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict | None:
    spec = NODES[node_type]
    type_id = spec["typeId"]

    # 子流程、API请求、代码块初始状态不需要 saveNode
    if type_id in (8, 14, 16):
        return None

    body = base_body(spec, process_id, node_id, name)

    if type_id == 1:
        body["gatewayType"] = extra.get("gatewayType", 1)
        body["flowIds"] = []
        body.pop("isException", None)
    elif type_id == 2:
        body["operateCondition"] = extra.get("operateCondition", [])
        body["flowIds"] = []
    elif type_id == 29:
        body["flowIds"] = []
        body["subProcessId"] = ""
        body["subProcessName"] = "循环"
    elif type_id == 30:
        body.pop("isException", None)

    return body
