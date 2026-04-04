"""通用 saveNode body 构建工具。

selectNodeId 规则（2026-04-04 抓包确认）：
  需要 selectNodeId 的节点（操作具体记录）：
    - typeId=6  记录操作 — 但仅限同表操作（appId=触发表），跨表新增时 selectNodeId 应为空
    - typeId=3  填写
    - typeId=5  抄送
    - typeId=26 审批

延时节点(typeId=12, actionId=301) 时间单位：
  - numberFieldValue.fieldValue = 天数（如 "1" = 1天）
  - hourFieldValue.fieldValue = 小时数
  - minuteFieldValue.fieldValue = 分钟数
  - secondFieldValue.fieldValue = 秒数
  各字段独立，不要把天转成分钟（如 1天 应设 numberFieldValue="1"，不是 minuteFieldValue="1440"）
  不需要 selectNodeId 的节点（不引用具体记录）：
    - typeId=27 站内通知
    - typeId=12 延时
    - typeId=9  数值运算/汇总
    - typeId=10/11 短信/邮件
    - typeId=17 界面推送
    - typeId=1/2 分支/条件
    - typeId=29 循环
    - typeId=31/33 AI 节点

触发节点 saveNode 规则：
  - 必须传完整的 controls 数组（工作表所有字段），否则编辑器报"程序错误"
  - controls 每个元素需包含：controlId, controlName, type, options, enumDefault,
    sourceControlType, processVariableType, originalType, workflowRequired 等
"""

from __future__ import annotations

# 需要 selectNodeId 的节点 typeId 集合
NEEDS_SELECT_NODE: set[int] = {6, 3, 5, 26}


def base_body(spec: dict, process_id: str, node_id: str, name: str) -> dict:
    """构建所有节点共用的 base body。"""
    type_id = spec["typeId"]
    body = {
        "processId": process_id,
        "flowNodeType": type_id,
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
