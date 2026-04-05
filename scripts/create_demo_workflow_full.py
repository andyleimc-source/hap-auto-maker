#!/usr/bin/env python3
"""
创建"全节点演示工作流"：线性串联 21 种工作流节点，供 UI 目视验证。

节点序列（按任务要求）：
  1.  更新记录      (typeId=6, actionId=2)
  2.  获取单条      (typeId=6, actionId=4)
  3.  数值运算      (typeId=9, actionId=100)
  4.  延时一段时间  (typeId=12, actionId=301)
  5.  站内通知      (typeId=27)
  6.  抄送          (typeId=5)
  7.  校准记录      (typeId=6, actionId=6)
  8.  汇总          (typeId=9, actionId=107)
  9.  填写          (typeId=3)
  10. 审批          (typeId=26)
  11. 循环          (typeId=29, actionId=210)
  12. AI文本        (typeId=31, actionId=531)
  13. AI对象        (typeId=31, actionId=532)
  14. AI Agent      (typeId=33, actionId=533)
  15. 删除记录      (typeId=6, actionId=3)
  16. 获取多条      (typeId=13, actionId=400)
  17. 延时到日期    (typeId=12, actionId=302) — timerNode 嵌套
  18. 发送短信      (typeId=10)
  19. 发送邮件      (typeId=11, actionId=202)
  20. 界面推送      (typeId=17, pushType=2)
  21. 中止流程      (typeId=30, actionId=2)

运行：
    cd /Users/andy/Documents/coding/hap-auto-maker
    python3 scripts/create_demo_workflow_full.py
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
AUTH_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

APP_ID       = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"
PROJECT_ID   = "faa2f6b1-f706-4084-9a8d-50616817f890"
SECTION_ID   = "69ce832640691821042c6e79"
WORKSHEET_ID = "69cf74eef9434db36c6e0816"   # 全字段演示工作表

API_BASE = "https://api.mingdao.com"
WEB_BASE = "https://www.mingdao.com"

WORKFLOW_NAME = "全节点演示工作流"

# ---------------------------------------------------------------------------
# 认证 & HTTP
# ---------------------------------------------------------------------------

def load_auth(path: Path) -> tuple[str, str, str]:
    spec = importlib.util.spec_from_file_location("_auth_cfg", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载认证文件: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return (
        str(getattr(mod, "ACCOUNT_ID", "")).strip(),
        str(getattr(mod, "AUTHORIZATION", "")).strip(),
        str(getattr(mod, "COOKIE", "")).strip(),
    )


def build_headers(account_id: str, authorization: str, cookie: str,
                  referer: str = "") -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "accountid": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "Origin": WEB_BASE,
        "Referer": referer or f"{WEB_BASE}/app/{APP_ID}",
        "X-Requested-With": "XMLHttpRequest",
    }


def api_post(url: str, payload: dict,
             account_id: str, authorization: str, cookie: str,
             referer: str = "") -> dict:
    headers = build_headers(account_id, authorization, cookie, referer)
    resp = requests.post(url, json=payload, headers=headers, timeout=30, proxies={})
    raw = resp.text.strip()
    if not raw and resp.status_code == 200:
        return {"_empty": True, "status": 1}
    try:
        return resp.json()
    except Exception:
        return {"_raw": resp.text[:300], "_status_code": resp.status_code}


def api_get(url: str, account_id: str, authorization: str, cookie: str) -> dict:
    headers = build_headers(account_id, authorization, cookie)
    resp = requests.get(url, headers=headers, timeout=30, proxies={})
    try:
        return resp.json()
    except Exception:
        return {"_raw": resp.text[:300], "_status_code": resp.status_code}


# ---------------------------------------------------------------------------
# 工作流创建 & 辅助
# ---------------------------------------------------------------------------

def create_workflow(name: str, worksheet_id: str,
                    account_id: str, authorization: str, cookie: str) -> tuple[str, str]:
    """
    创建工作流并绑定触发工作表。
    返回 (process_id, start_node_id)。
    """
    # Step 1: process/add
    resp = api_post(
        f"{API_BASE}/workflow/process/add",
        {
            "companyId": "",
            "relationId": APP_ID,
            "relationType": 2,
            "startEventAppType": 1,
            "name": name,
            "explain": "",
        },
        account_id, authorization, cookie,
    )
    if resp.get("status") != 1:
        raise RuntimeError(f"process/add 失败: {resp}")

    data = resp.get("data", {})
    process_id = str(data.get("id", "")).strip()
    if not process_id:
        raise RuntimeError(f"process/add 没有返回 id: {resp}")

    # Step 2: 获取 start_node_id
    pub_resp = api_get(
        f"{API_BASE}/workflow/process/getProcessPublish?processId={process_id}",
        account_id, authorization, cookie,
    )
    start_node_id = ""
    if pub_resp.get("status") == 1:
        pdata = pub_resp.get("data") or {}
        start_node_id = str(pdata.get("startNodeId", "")).strip()

    # Step 3: 绑定触发工作表
    if start_node_id and worksheet_id:
        save_resp = api_post(
            f"{API_BASE}/workflow/flowNode/saveNode",
            {
                "appId": worksheet_id,
                "appType": 1,
                "assignFieldIds": [],
                "processId": process_id,
                "nodeId": start_node_id,
                "flowNodeType": 0,
                "operateCondition": [],
                "triggerId": "2",
                "name": "工作表事件触发",
                "controls": [],
            },
            account_id, authorization, cookie,
        )
        if save_resp.get("status") != 1:
            print(f"  [warn] 绑定触发工作表: {save_resp}")

    return process_id, start_node_id


def add_node(process_id: str, prev_node_id: str,
             name: str, type_id: int,
             action_id: str = "", app_type: int = 0, app_id: str = "",
             account_id: str = "", authorization: str = "", cookie: str = "") -> str:
    """调用 flowNode/add，返回新节点 ID。失败时返回空字符串。"""
    payload: dict = {
        "processId": process_id,
        "prveId": prev_node_id,
        "name": name,
        "typeId": type_id,
    }
    if action_id:
        payload["actionId"] = action_id
    if app_type:
        payload["appType"] = app_type
    if app_id:
        payload["appId"] = app_id

    resp = api_post(
        f"{API_BASE}/workflow/flowNode/add",
        payload,
        account_id, authorization, cookie,
    )
    if resp.get("status") != 1:
        raise RuntimeError(f"flowNode/add 失败: {resp}")

    added_nodes = resp.get("data", {}).get("addFlowNodes", [])
    if not added_nodes:
        raise RuntimeError(f"flowNode/add 无 addFlowNodes: {resp}")
    return added_nodes[0]["id"]


def save_node(body: dict, account_id: str, authorization: str, cookie: str) -> dict:
    return api_post(
        f"{API_BASE}/workflow/flowNode/saveNode",
        body,
        account_id, authorization, cookie,
    )


def is_ok(resp: dict) -> bool:
    return resp.get("status") == 1 or resp.get("_empty") is True


# ---------------------------------------------------------------------------
# 节点定义 — 每个返回 (node_id, ok, error_msg)
# ---------------------------------------------------------------------------

def step_update_record(process_id, prev_id, start_node_id, ws_id, aid, auth, ck):
    """1. 更新记录 (typeId=6, actionId=2)"""
    nid = add_node(process_id, prev_id, "更新记录", 6, "2", 1, ws_id, aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 6,
        "actionId": "2",
        "appType": 1,
        "appId": ws_id,
        "name": "更新记录",
        "selectNodeId": start_node_id,
        "selectNodeName": "工作表事件触发",
        "fields": [],
        "filters": [],
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_get_single(process_id, prev_id, ws_id, aid, auth, ck):
    """2. 获取单条 (typeId=6, actionId=4)"""
    nid = add_node(process_id, prev_id, "获取单条", 6, "4", 1, ws_id, aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 6,
        "actionId": "4",
        "appType": 1,
        "appId": ws_id,
        "name": "获取单条",
        "selectNodeId": "",
        "selectNodeName": "",
        "filters": [],
        "sorts": [],
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_arithmetic(process_id, prev_id, aid, auth, ck):
    """3. 数值运算 (typeId=9, actionId=100)"""
    nid = add_node(process_id, prev_id, "数值运算", 9, "100", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 9,
        "actionId": "100",
        "name": "数值运算",
        "selectNodeId": "",
        "selectNodeName": "",
        "formulaMap": {},
        "formulaValue": "",
        "fieldValue": "",
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_delay_duration(process_id, prev_id, aid, auth, ck):
    """4. 延时一段时间 (typeId=12, actionId=301)"""
    nid = add_node(process_id, prev_id, "延时一段时间", 12, "301", 0, "", aid, auth, ck)
    empty_fv = {"fieldValue": "", "fieldNodeId": "", "fieldControlId": ""}
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 12,
        "actionId": "301",
        "name": "延时一段时间",
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
        "numberFieldValue": dict(empty_fv),
        "hourFieldValue": dict(empty_fv),
        "minuteFieldValue": {"fieldValue": "5", "fieldNodeId": "", "fieldControlId": ""},
        "secondFieldValue": dict(empty_fv),
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_notify(process_id, prev_id, aid, auth, ck):
    """5. 站内通知 (typeId=27)"""
    nid = add_node(process_id, prev_id, "站内通知", 27, "", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 27,
        "name": "站内通知",
        "selectNodeId": "",
        "selectNodeName": "",
        "accounts": [],
        "sendContent": "全节点演示工作流：站内通知测试",
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_cc(process_id, prev_id, aid, auth, ck):
    """6. 抄送 (typeId=5)"""
    nid = add_node(process_id, prev_id, "抄送", 5, "", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 5,
        "name": "抄送",
        "selectNodeId": "",
        "selectNodeName": "",
        "accounts": [],
        "sendContent": "全节点演示工作流：抄送内容",
        "flowIds": [],
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_calibrate(process_id, prev_id, ws_id, aid, auth, ck):
    """7. 校准记录 (typeId=6, actionId=6)"""
    nid = add_node(process_id, prev_id, "校准记录", 6, "6", 1, ws_id, aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 6,
        "actionId": "6",
        "appType": 1,
        "appId": ws_id,
        "name": "校准记录",
        "selectNodeId": "",
        "selectNodeName": "",
        "fields": [],
        "errorFields": [],
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_aggregate(process_id, prev_id, ws_id, aid, auth, ck):
    """8. 汇总 (typeId=9, actionId=107)"""
    nid = add_node(process_id, prev_id, "从工作表汇总", 9, "107", 1, ws_id, aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 9,
        "actionId": "107",
        "appType": 1,
        "appId": ws_id,
        "name": "从工作表汇总",
        "selectNodeId": "",
        "selectNodeName": "",
        "formulaValue": "",
        "fieldValue": "",
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_fill(process_id, prev_id, aid, auth, ck):
    """9. 填写 (typeId=3)"""
    nid = add_node(process_id, prev_id, "填写", 3, "", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 3,
        "name": "填写",
        "selectNodeId": "",
        "selectNodeName": "",
        "flowIds": [],
        "formProperties": [],
        "accounts": [],
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_approval(process_id, prev_id, aid, auth, ck):
    """10. 审批 (typeId=26, appType=10)"""
    nid = add_node(process_id, prev_id, "发起审批", 26, "", 10, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 26,
        "appType": 10,
        "name": "发起审批",
        "selectNodeId": "",
        "selectNodeName": "",
        "flowIds": [],
        "formProperties": [],
        "accounts": [],
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_loop(process_id, prev_id, aid, auth, ck):
    """11. 循环 (typeId=29, actionId=210, appType=45)"""
    nid = add_node(process_id, prev_id, "满足条件时循环", 29, "210", 45, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 29,
        "actionId": "210",
        "appType": 45,
        "name": "满足条件时循环",
        "selectNodeId": "",
        "selectNodeName": "",
        "flowIds": [],
        "subProcessId": "",
        "subProcessName": "循环",
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_ai_text(process_id, prev_id, aid, auth, ck):
    """12. AI文本 (typeId=31, actionId=531, appType=46)"""
    nid = add_node(process_id, prev_id, "AI 生成文本", 31, "531", 46, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 31,
        "actionId": "531",
        "appType": 46,
        "name": "AI 生成文本",
        "selectNodeId": "",
        "selectNodeName": "",
        "appId": "",
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_ai_object(process_id, prev_id, aid, auth, ck):
    """13. AI对象 (typeId=31, actionId=532, appType=46)"""
    nid = add_node(process_id, prev_id, "AI 生成数据对象", 31, "532", 46, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 31,
        "actionId": "532",
        "appType": 46,
        "name": "AI 生成数据对象",
        "selectNodeId": "",
        "selectNodeName": "",
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_ai_agent(process_id, prev_id, aid, auth, ck):
    """14. AI Agent (typeId=33, actionId=533, appType=48)"""
    nid = add_node(process_id, prev_id, "AI Agent", 33, "533", 48, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 33,
        "actionId": "533",
        "appType": 48,
        "name": "AI Agent",
        "selectNodeId": "",
        "selectNodeName": "",
        "appId": "",
        "tools": [],
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_delete_record(process_id, prev_id, start_node_id, ws_id, aid, auth, ck):
    """15. 删除记录 (typeId=6, actionId=3)"""
    nid = add_node(process_id, prev_id, "删除记录", 6, "3", 1, ws_id, aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 6,
        "actionId": "3",
        "appType": 1,
        "appId": ws_id,
        "name": "删除记录",
        "selectNodeId": start_node_id,
        "selectNodeName": "工作表事件触发",
        "filters": [],
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_get_records(process_id, prev_id, ws_id, aid, auth, ck):
    """16. 获取多条 (typeId=13, actionId=400)"""
    nid = add_node(process_id, prev_id, "获取多条", 13, "400", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 13,
        "actionId": "400",
        "name": "获取多条",
        "selectNodeId": "",
        "selectNodeName": "",
        "appId": ws_id,
        "filters": [],
        "sorts": [],
        "number": 50,
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_delay_until(process_id, prev_id, aid, auth, ck):
    """17. 延时到日期 (typeId=12, actionId=302) — timerNode 嵌套结构"""
    nid = add_node(process_id, prev_id, "延时到指定日期", 12, "302", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 12,
        "name": "延时到指定日期",
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
        # 关键：必须用 timerNode 嵌套结构
        "timerNode": {
            "name": "延时到指定日期",
            "desc": "",
            "actionId": "302",
            "executeTimeType": 0,
            "number": 0,
            "unit": 1,
            "time": "08:00",
        },
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_sms(process_id, prev_id, aid, auth, ck):
    """18. 发送短信 (typeId=10)"""
    nid = add_node(process_id, prev_id, "发送短信", 10, "", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 10,
        "name": "发送短信",
        "selectNodeId": "",
        "selectNodeName": "",
        "accounts": [],
        "content": "全节点演示工作流：短信测试内容",
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_email(process_id, prev_id, aid, auth, ck):
    """19. 发送邮件 (typeId=11, actionId=202, appType=3)"""
    nid = add_node(process_id, prev_id, "发送邮件", 11, "202", 3, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 11,
        "actionId": "202",
        "appType": 3,
        "name": "发送邮件",
        "selectNodeId": "",
        "selectNodeName": "",
        "accounts": [],
        "title": "全节点演示工作流：邮件标题",
        "content": "全节点演示工作流：邮件正文内容",
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_push(process_id, prev_id, aid, auth, ck):
    """20. 界面推送 (typeId=17, pushType=2)"""
    nid = add_node(process_id, prev_id, "界面推送", 17, "", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 17,
        "name": "界面推送",
        "selectNodeId": "",
        "selectNodeName": "",
        "accounts": [],
        "sendContent": "全节点演示工作流：界面推送内容",
        "pushType": 2,   # 0/1 会 500；2/3 成功
        "openMode": 0,
        "isException": True,
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


def step_abort(process_id, prev_id, aid, auth, ck):
    """21. 中止流程 (typeId=30, actionId=2) — saveNode 返回 empty body 为成功"""
    nid = add_node(process_id, prev_id, "中止流程", 30, "2", 0, "", aid, auth, ck)
    body = {
        "processId": process_id,
        "nodeId": nid,
        "flowNodeType": 30,
        "actionId": "2",
        "name": "中止流程",
        "selectNodeId": "",
        "selectNodeName": "",
        # 中止节点无 isException
    }
    resp = save_node(body, aid, auth, ck)
    if not is_ok(resp):
        raise RuntimeError(f"saveNode 失败: {resp}")
    return nid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

STEPS = [
    ("更新记录",      "typeId=6, actionId=2",   "step_update_record"),
    ("获取单条",      "typeId=6, actionId=4",   "step_get_single"),
    ("数值运算",      "typeId=9, actionId=100",  "step_arithmetic"),
    ("延时一段时间",  "typeId=12, actionId=301", "step_delay_duration"),
    ("站内通知",      "typeId=27",               "step_notify"),
    ("抄送",          "typeId=5",                "step_cc"),
    ("校准记录",      "typeId=6, actionId=6",   "step_calibrate"),
    ("汇总",          "typeId=9, actionId=107",  "step_aggregate"),
    ("填写",          "typeId=3",                "step_fill"),
    ("审批",          "typeId=26",               "step_approval"),
    ("循环",          "typeId=29, actionId=210", "step_loop"),
    ("AI文本",        "typeId=31, actionId=531", "step_ai_text"),
    ("AI对象",        "typeId=31, actionId=532", "step_ai_object"),
    ("AI Agent",      "typeId=33, actionId=533", "step_ai_agent"),
    ("删除记录",      "typeId=6, actionId=3",   "step_delete_record"),
    ("获取多条",      "typeId=13, actionId=400", "step_get_records"),
    ("延时到日期",    "typeId=12, actionId=302", "step_delay_until"),
    ("发送短信",      "typeId=10",               "step_sms"),
    ("发送邮件",      "typeId=11, actionId=202", "step_email"),
    ("界面推送",      "typeId=17, pushType=2",   "step_push"),
    ("中止流程",      "typeId=30, actionId=2",   "step_abort"),
]


def main():
    print("=" * 70)
    print(f"创建 {WORKFLOW_NAME}")
    print("=" * 70)

    # 加载认证
    print("\n[Auth] 加载认证配置...")
    try:
        aid, auth, ck = load_auth(AUTH_PATH)
        print(f"  account_id={aid[:8]}...  authorization={'*' * 8}")
    except Exception as e:
        print(f"  ✗ 认证加载失败: {e}")
        sys.exit(1)

    # 创建工作流
    print(f"\n[创建工作流] {WORKFLOW_NAME}...")
    try:
        process_id, start_node_id = create_workflow(
            WORKFLOW_NAME, WORKSHEET_ID, aid, auth, ck
        )
        print(f"  ✓ processId = {process_id}")
        print(f"  ✓ startNodeId = {start_node_id}")
    except Exception as e:
        print(f"  ✗ 创建工作流失败: {e}")
        sys.exit(1)

    # 线性添加节点
    print("\n[添加节点序列]")
    prev_id = start_node_id
    results: list[tuple[str, str, str, str, str]] = []

    for i, (name, desc, fn_name) in enumerate(STEPS, 1):
        print(f"\n  [{i:02d}] {name} ({desc})")
        t0 = time.time()
        node_id = ""
        status = "FAIL"
        err_msg = ""
        try:
            # 根据节点类型调用对应函数
            if fn_name == "step_update_record":
                node_id = step_update_record(process_id, prev_id, start_node_id, WORKSHEET_ID, aid, auth, ck)
            elif fn_name == "step_get_single":
                node_id = step_get_single(process_id, prev_id, WORKSHEET_ID, aid, auth, ck)
            elif fn_name == "step_arithmetic":
                node_id = step_arithmetic(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_delay_duration":
                node_id = step_delay_duration(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_notify":
                node_id = step_notify(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_cc":
                node_id = step_cc(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_calibrate":
                node_id = step_calibrate(process_id, prev_id, WORKSHEET_ID, aid, auth, ck)
            elif fn_name == "step_aggregate":
                node_id = step_aggregate(process_id, prev_id, WORKSHEET_ID, aid, auth, ck)
            elif fn_name == "step_fill":
                node_id = step_fill(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_approval":
                node_id = step_approval(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_loop":
                node_id = step_loop(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_ai_text":
                node_id = step_ai_text(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_ai_object":
                node_id = step_ai_object(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_ai_agent":
                node_id = step_ai_agent(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_delete_record":
                node_id = step_delete_record(process_id, prev_id, start_node_id, WORKSHEET_ID, aid, auth, ck)
            elif fn_name == "step_get_records":
                node_id = step_get_records(process_id, prev_id, WORKSHEET_ID, aid, auth, ck)
            elif fn_name == "step_delay_until":
                node_id = step_delay_until(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_sms":
                node_id = step_sms(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_email":
                node_id = step_email(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_push":
                node_id = step_push(process_id, prev_id, aid, auth, ck)
            elif fn_name == "step_abort":
                node_id = step_abort(process_id, prev_id, aid, auth, ck)
            else:
                raise RuntimeError(f"未知函数: {fn_name}")

            status = "PASS"
            prev_id = node_id   # 链接到下一节点
            elapsed = round((time.time() - t0) * 1000)
            print(f"       ✓ PASS  nodeId={node_id}  ({elapsed}ms)")

        except Exception as e:
            elapsed = round((time.time() - t0) * 1000)
            err_msg = str(e)
            print(f"       ✗ FAIL  ({elapsed}ms)  {err_msg}")
            # FAIL 时 prev_id 不更新（保持上一个成功节点，继续尝试后续节点）

        results.append((name, desc, status, node_id, err_msg))
        time.sleep(0.2)

    # ---------------------------------------------------------------------------
    # 汇总输出
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("汇总结果")
    print("=" * 70)
    passed = sum(1 for _, _, s, _, _ in results if s == "PASS")
    failed = sum(1 for _, _, s, _, _ in results if s == "FAIL")

    header = f"{'#':<4} {'节点名':<16} {'描述':<24} {'结果':<6} {'节点ID':<28} {'错误'}"
    print(header)
    print("-" * 95)
    for i, (name, desc, status, node_id, err_msg) in enumerate(results, 1):
        symbol = "PASS" if status == "PASS" else "FAIL"
        err_snippet = err_msg[:30] if err_msg else "-"
        nid_display = node_id[:26] if node_id else "-"
        print(f"{i:<4} {name:<16} {desc:<24} {symbol:<6} {nid_display:<28} {err_snippet}")
    print("-" * 95)
    print(f"共 {len(results)} 个节点   PASS: {passed}   FAIL: {failed}")

    # ---------------------------------------------------------------------------
    # 最终输出
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("工作流信息")
    print("=" * 70)
    print(f"  processId : {process_id}")
    print(f"  编辑链接  : https://www.mingdao.com/workflowedit/{process_id}")
    print("=" * 70)

    if failed > 0:
        print("\n[失败节点详情]")
        for i, (name, desc, status, node_id, err_msg) in enumerate(results, 1):
            if status == "FAIL":
                print(f"  [{i:02d}] {name}: {err_msg}")


if __name__ == "__main__":
    main()
