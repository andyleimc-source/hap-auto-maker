"""通用 saveNode body 构建工具。"""

from __future__ import annotations


def base_body(spec: dict, process_id: str, node_id: str, name: str) -> dict:
    """构建所有节点共用的 base body。"""
    body = {
        "processId": process_id,
        "flowNodeType": spec["typeId"],
        "name": name,
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
        "nodeId": node_id,
    }
    if "actionId" in spec:
        body["actionId"] = spec["actionId"]
    if "appType" in spec:
        body["appType"] = spec["appType"]
    return body
