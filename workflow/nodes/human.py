"""人工参与节点: 填写(3), 抄送(5)。

关键发现（2026-04-04 抓包确认）:
  - 抄送(5)新版配置方式：formProperties（字段可见性）+ viewId + showTitle
  - 抄送(5)需要 selectNodeId（指向数据来源节点）
  - 填写(3)需要 formProperties 定义可填字段 + selectNodeId
  - formProperties 每个元素: {id, type, name, property: 1=可查看, showCard: 0, sectionId: ""}
"""

from __future__ import annotations
from ._base import base_body


NODES = {
    "fill": {
        "typeId": 3,
        "name": "填写",
        "verified": False,
        "doc": "需要 formProperties + accounts + selectNodeId。",
    },
    "copy": {
        "typeId": 5,
        "name": "抄送",
        "verified": True,
        "doc": "新版用 formProperties+viewId+showTitle；旧版用 sendContent。需要 selectNodeId。",
    },
}


def build_form_properties(controls: list[dict]) -> list[dict]:
    """从工作表字段列表构建 formProperties（新版通知/抄送的字段可见性配置）。"""
    props = []
    for c in controls:
        cid = c.get("controlId", "")
        ctype = c.get("type", 0)
        cname = c.get("controlName", "")
        if not cid or cid.startswith("wf"):
            continue
        props.append({
            "id": cid,
            "type": ctype,
            "name": cname,
            "property": 1,  # 1=可查看
            "showCard": 0,
            "sectionId": "",
            "workflow": False,
            "detailTable": False,
        })
    return props


def build(node_type: str, process_id: str, node_id: str,
          worksheet_id: str, name: str, extra: dict) -> dict:
    spec = NODES[node_type]
    body = base_body(spec, process_id, node_id, name)
    body["accounts"] = extra.get("accounts", [])
    body["flowIds"] = []

    if node_type == "fill":
        body["formProperties"] = extra.get("formProperties", [])
    elif node_type == "copy":
        body["sendContent"] = extra.get("sendContent") or extra.get("content", "")
        # 新版配置
        if extra.get("formProperties"):
            body["formProperties"] = extra["formProperties"]
        if extra.get("viewId"):
            body["viewId"] = extra["viewId"]
            body["showTitle"] = extra.get("showTitle", True)

    return body
