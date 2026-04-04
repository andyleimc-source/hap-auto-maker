"""记录操作节点 (typeId=6): 新增/更新/删除/获取/校准。

注意: typeId=6 的节点在 execute_workflow_plan.py 的 add_action_nodes() 中
直接构建 saveNode body（不经过 build），这里返回 None 表示跳过。
typeId=13 (查询工作表) 是独立类型。

关键发现:
  - 单选字段(type=9)的 fieldValue 必须是完整 UUID key，截断会被 HAP 静默丢弃
  - 跨表新增的关联字段引用格式 $nodeId-fieldId$ 需配合 sourceControlType
"""

from __future__ import annotations
from ._base import base_body

NODES = {
    "delete_record": {
        "typeId": 6, "actionId": "3", "appType": 1,
        "name": "删除记录", "needs_worksheet": True,
        "verified": False,
        "doc": "需要 filters 指定删除条件。",
    },
    "get_record": {
        "typeId": 6, "actionId": "4", "appType": 1,
        "name": "获取单条数据", "needs_worksheet": True,
        "verified": True,
        "doc": "需要 filters + sorts。实测可 publish。",
    },
    "get_records": {
        "typeId": 13, "actionId": "400",
        "name": "查询工作表", "needs_worksheet": False,
        "verified": False,
        "doc": "typeId=13 而非 6。需要 filters + sorts + number。",
    },
    "calibrate_record": {
        "typeId": 6, "actionId": "6", "appType": 1,
        "name": "校准单条数据", "needs_worksheet": True,
        "verified": False,
        "doc": "需要 fields + errorFields。",
    },
}


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict | None:
    spec = NODES[node_type]
    type_id = spec["typeId"]
    action = spec.get("actionId", "")

    # typeId=6: 记录操作节点
    if type_id == 6:
        body = base_body(spec, process_id, node_id, name)
        if worksheet_id:
            body["appId"] = worksheet_id
        body["fields"] = extra.get("fields", [])
        body["filters"] = extra.get("filters", [])
        if action in ("4", "5", "6"):
            body["sorts"] = extra.get("sorts", [])
        return body

    # typeId=13 (查询工作表)
    body = base_body(spec, process_id, node_id, name)
    if worksheet_id:
        body["appId"] = worksheet_id
    body["filters"] = []
    body["sorts"] = []
    body["number"] = 50
    return body
