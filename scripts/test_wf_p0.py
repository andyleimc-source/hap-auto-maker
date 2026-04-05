#!/usr/bin/env python3
"""
测试脚本：验证 9 种工作流节点的 add + saveNode 接口。

节点列表：
  1. 校准记录      (typeId=6, actionId="6")
  2. 汇总          (typeId=9, actionId="107")
  3. 填写          (typeId=3)
  4. 审批          (typeId=26)
  5. 分支网关      (typeId=1) + 分支条件 (typeId=2)
  6. 循环          (typeId=29, actionId="210")
  7. AI文本        (typeId=31, actionId="531")
  8. AI对象        (typeId=31, actionId="532")
  9. AI Agent      (typeId=33, actionId="533")

测试策略：
  - 每个节点创建独立工作流（工作表事件触发）
  - 调用 flowNode/add 添加节点骨架
  - 调用 flowNode/saveNode 配置节点
  - 记录 pass/fail + 错误信息
"""

from __future__ import annotations

import importlib.util
import json
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

APP_ID = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"       # CRM 应用
PROJECT_ID = "faa2f6b1-f706-4084-9a8d-50616817f890"   # 组织 ID
SECTION_ID = "69ce832640691821042c6e79"               # 基础设置 section

# CRM 应用中的一个已有工作表 ID（供触发器绑定用）
# 使用 AppManagement/AddWorkSheet 创建的工作表
WORKSHEET_ID = ""   # 将在运行时自动获取或创建

API_BASE = "https://api.mingdao.com"
WEB_BASE = "https://www.mingdao.com"

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def load_auth(path: Path) -> tuple[str, str, str]:
    spec = importlib.util.spec_from_file_location("_auth_cfg", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载认证文件: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    account_id = str(getattr(mod, "ACCOUNT_ID", "")).strip()
    authorization = str(getattr(mod, "AUTHORIZATION", "")).strip()
    cookie = str(getattr(mod, "COOKIE", "")).strip()
    return account_id, authorization, cookie


def build_headers(account_id: str, authorization: str, cookie: str, referer: str = "") -> dict:
    h = {
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
    return h


def api_post(url: str, payload: dict, account_id: str, authorization: str, cookie: str,
             referer: str = "") -> dict:
    headers = build_headers(account_id, authorization, cookie, referer)
    resp = requests.post(url, json=payload, headers=headers, timeout=30, proxies={})
    try:
        return resp.json()
    except Exception:
        return {"_raw": resp.text[:300], "_status_code": resp.status_code}


def api_get(url: str, account_id: str, authorization: str, cookie: str,
            referer: str = "") -> dict:
    headers = build_headers(account_id, authorization, cookie, referer)
    resp = requests.get(url, headers=headers, timeout=30, proxies={})
    try:
        return resp.json()
    except Exception:
        return {"_raw": resp.text[:300], "_status_code": resp.status_code}


# ---------------------------------------------------------------------------
# 获取可用工作表 ID（应用中已有的工作表）
# ---------------------------------------------------------------------------

def get_worksheet_id(account_id: str, authorization: str, cookie: str) -> str:
    """从 CRM 应用获取第一个可用工作表 ID。"""
    url = f"{WEB_BASE}/api/AppManagement/GetAppInfo"
    data = api_post(url, {"appId": APP_ID}, account_id, authorization, cookie)
    # 尝试从 sectionList 中拿第一个 worksheetId
    section_list = data.get("data", {}).get("sectionList", [])
    for section in section_list:
        for item in section.get("workSheetInfo", []):
            ws_id = item.get("workSheetId", "")
            if ws_id:
                return ws_id
    return ""


# ---------------------------------------------------------------------------
# 创建工作流（工作表事件触发）
# ---------------------------------------------------------------------------

def create_workflow(name: str, worksheet_id: str,
                    account_id: str, authorization: str, cookie: str) -> Optional[str]:
    """
    创建工作流并绑定触发工作表。
    返回 process_id，失败返回 None。
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
        print(f"  [create_workflow] process/add 失败: {resp}")
        return None

    data = resp.get("data", {})
    process_id = str(data.get("id", "")).strip()
    company_id = str(data.get("companyId", "")).strip()
    if not process_id:
        print(f"  [create_workflow] 未拿到 process_id: {resp}")
        return None

    # Step 2: AppManagement/AddWorkflow（注册到应用列表）
    api_post(
        f"{WEB_BASE}/api/AppManagement/AddWorkflow",
        {"projectId": company_id, "name": name},
        account_id, authorization, cookie,
        referer=f"{WEB_BASE}/workflowedit/{process_id}",
    )

    # Step 3: 绑定触发工作表（saveNode on start node）
    if worksheet_id:
        pub_resp = api_get(
            f"{API_BASE}/workflow/process/getProcessPublish?processId={process_id}",
            account_id, authorization, cookie,
        )
        start_node_id = ""
        if pub_resp.get("status") == 1:
            pdata = pub_resp.get("data") or {}
            start_node_id = str(pdata.get("startNodeId", "")).strip()

        if start_node_id:
            api_post(
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

    return process_id


# ---------------------------------------------------------------------------
# 获取流程触发节点 ID
# ---------------------------------------------------------------------------

def get_start_node_id(process_id: str, account_id: str, authorization: str, cookie: str) -> str:
    resp = api_get(
        f"{API_BASE}/workflow/process/getProcessPublish?processId={process_id}",
        account_id, authorization, cookie,
    )
    if resp.get("status") == 1:
        pdata = resp.get("data") or {}
        return str(pdata.get("startNodeId", "")).strip()
    return ""


# ---------------------------------------------------------------------------
# 节点 add 函数
# ---------------------------------------------------------------------------

def add_node(process_id: str, prev_node_id: str, name: str, type_id: int,
             action_id: str = "", app_type: int = 0, app_id: str = "",
             account_id: str = "", authorization: str = "", cookie: str = "") -> Optional[str]:
    """调用 flowNode/add，返回新节点 ID。"""
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


# ---------------------------------------------------------------------------
# saveNode 函数
# ---------------------------------------------------------------------------

def save_node(body: dict, account_id: str, authorization: str, cookie: str) -> dict:
    return api_post(
        f"{API_BASE}/workflow/flowNode/saveNode",
        body,
        account_id, authorization, cookie,
    )


# ---------------------------------------------------------------------------
# 各节点测试
# ---------------------------------------------------------------------------

def make_base_body(process_id: str, node_id: str, flow_node_type: int, name: str,
                   action_id: str = "", app_type: int = 0, is_exception: bool = True) -> dict:
    """
    构建 saveNode 通用 body。
    关键字段名：nodeId（非 id）、flowNodeType（非 typeId）。
    """
    body: dict = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": flow_node_type,
        "name": name,
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": is_exception,
    }
    if action_id:
        body["actionId"] = action_id
    if app_type:
        body["appType"] = app_type
    return body


def test_calibrate_record(account_id, authorization, cookie, worksheet_id):
    """1. 校准记录 (typeId=6, actionId="6")"""
    process_id = create_workflow("测试-校准记录", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    node_id = add_node(process_id, start_node_id, "校准记录", 6, "6", 1, worksheet_id,
                       account_id, authorization, cookie)

    body = make_base_body(process_id, node_id, 6, "校准记录", "6", 1)
    body["appId"] = worksheet_id
    body["fields"] = []
    body["errorFields"] = []
    resp = save_node(body, account_id, authorization, cookie)
    if resp.get("status") != 1:
        raise RuntimeError(f"saveNode 失败: {resp}")
    return {"process_id": process_id, "node_id": node_id}


def test_aggregate(account_id, authorization, cookie, worksheet_id):
    """2. 汇总 (typeId=9, actionId="107")"""
    process_id = create_workflow("测试-汇总", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    node_id = add_node(process_id, start_node_id, "从工作表汇总", 9, "107", 1, worksheet_id,
                       account_id, authorization, cookie)

    body = make_base_body(process_id, node_id, 9, "从工作表汇总", "107", 1)
    body["appId"] = worksheet_id
    body["formulaValue"] = ""
    body["fieldValue"] = ""
    resp = save_node(body, account_id, authorization, cookie)
    if resp.get("status") != 1:
        raise RuntimeError(f"saveNode 失败: {resp}")
    return {"process_id": process_id, "node_id": node_id}


def test_fill(account_id, authorization, cookie, worksheet_id):
    """3. 填写 (typeId=3)"""
    process_id = create_workflow("测试-填写", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    node_id = add_node(process_id, start_node_id, "填写", 3, "", 0, "",
                       account_id, authorization, cookie)

    body = make_base_body(process_id, node_id, 3, "填写")
    body["flowIds"] = []
    body["formProperties"] = []
    body["accounts"] = []
    resp = save_node(body, account_id, authorization, cookie)
    if resp.get("status") != 1:
        raise RuntimeError(f"saveNode 失败: {resp}")
    return {"process_id": process_id, "node_id": node_id}


def test_approval(account_id, authorization, cookie, worksheet_id):
    """4. 审批 (typeId=26, appType=10)"""
    process_id = create_workflow("测试-审批", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    node_id = add_node(process_id, start_node_id, "发起审批", 26, "", 10, "",
                       account_id, authorization, cookie)

    body = make_base_body(process_id, node_id, 26, "发起审批", "", 10)
    body["flowIds"] = []
    body["formProperties"] = []
    body["accounts"] = []
    resp = save_node(body, account_id, authorization, cookie)
    if resp.get("status") != 1:
        raise RuntimeError(f"saveNode 失败: {resp}")
    return {"process_id": process_id, "node_id": node_id}


def test_branch(account_id, authorization, cookie, worksheet_id):
    """5. 分支网关 (typeId=1) + 分支条件 (typeId=2)"""
    process_id = create_workflow("测试-分支网关", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    # 添加分支网关节点：add 会同时返回网关节点 + 自动生成的条件分支节点
    add_payload = {
        "processId": process_id,
        "prveId": start_node_id,
        "name": "分支",
        "typeId": 1,
    }
    add_resp = api_post(
        f"{API_BASE}/workflow/flowNode/add",
        add_payload,
        account_id, authorization, cookie,
    )
    if add_resp.get("status") != 1:
        raise RuntimeError(f"分支网关 flowNode/add 失败: {add_resp}")

    added_nodes = add_resp.get("data", {}).get("addFlowNodes", [])
    # 网关节点是 typeId=1，条件节点是 typeId=2
    gateway_id = ""
    condition_node_ids = []
    for n in added_nodes:
        if n.get("typeId") == 1:
            gateway_id = n["id"]
        elif n.get("typeId") == 2:
            condition_node_ids.append(n["id"])

    if not gateway_id:
        # 若没有区分，第一个节点为网关
        if added_nodes:
            gateway_id = added_nodes[0]["id"]

    if not gateway_id:
        raise RuntimeError(f"未拿到分支网关节点 ID。addFlowNodes={added_nodes}")

    # saveNode 分支网关
    gw_body = make_base_body(process_id, gateway_id, 1, "分支", is_exception=False)
    gw_body.pop("isException", None)
    gw_body["gatewayType"] = 1
    gw_body["flowIds"] = condition_node_ids
    gw_resp = save_node(gw_body, account_id, authorization, cookie)
    if gw_resp.get("status") != 1:
        raise RuntimeError(f"分支网关 saveNode 失败: {gw_resp}")

    # saveNode 第一个条件分支节点
    condition_node_id = condition_node_ids[0] if condition_node_ids else None
    if condition_node_id:
        cond_body = make_base_body(process_id, condition_node_id, 2, "条件1")
        cond_body["flowIds"] = []
        cond_body["operateCondition"] = []
        cond_resp = save_node(cond_body, account_id, authorization, cookie)
        if cond_resp.get("status") != 1:
            raise RuntimeError(f"分支条件 saveNode 失败: {cond_resp}")
    else:
        # 条件节点未在 addFlowNodes 中返回，尝试单独 add 一个
        cond_add_resp = api_post(
            f"{API_BASE}/workflow/flowNode/add",
            {
                "processId": process_id,
                "prveId": gateway_id,
                "name": "条件1",
                "typeId": 2,
            },
            account_id, authorization, cookie,
        )
        if cond_add_resp.get("status") != 1:
            raise RuntimeError(f"分支条件 flowNode/add 失败: {cond_add_resp}")
        cond_nodes = cond_add_resp.get("data", {}).get("addFlowNodes", [])
        condition_node_id = cond_nodes[0]["id"] if cond_nodes else None

        if condition_node_id:
            cond_body = make_base_body(process_id, condition_node_id, 2, "条件1")
            cond_body["flowIds"] = []
            cond_body["operateCondition"] = []
            cond_resp = save_node(cond_body, account_id, authorization, cookie)
            if cond_resp.get("status") != 1:
                raise RuntimeError(f"分支条件 saveNode 失败: {cond_resp}")
        else:
            raise RuntimeError("无法创建分支条件节点")

    return {
        "process_id": process_id,
        "gateway_node_id": gateway_id,
        "condition_node_id": condition_node_id,
        "all_added_nodes": [n["id"] for n in added_nodes],
    }


def test_loop(account_id, authorization, cookie, worksheet_id):
    """6. 循环 (typeId=29, actionId="210", appType=45)"""
    process_id = create_workflow("测试-循环", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    node_id = add_node(process_id, start_node_id, "满足条件时循环", 29, "210", 45, "",
                       account_id, authorization, cookie)

    body = make_base_body(process_id, node_id, 29, "满足条件时循环", "210", 45)
    body["flowIds"] = []
    body["subProcessId"] = ""
    body["subProcessName"] = "循环"
    resp = save_node(body, account_id, authorization, cookie)
    if resp.get("status") != 1:
        raise RuntimeError(f"saveNode 失败: {resp}")
    return {"process_id": process_id, "node_id": node_id}


def test_ai_text(account_id, authorization, cookie, worksheet_id):
    """7. AI文本 (typeId=31, actionId="531", appType=46)"""
    process_id = create_workflow("测试-AI文本", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    node_id = add_node(process_id, start_node_id, "AI 生成文本", 31, "531", 46, "",
                       account_id, authorization, cookie)

    body = make_base_body(process_id, node_id, 31, "AI 生成文本", "531", 46, is_exception=False)
    body.pop("isException", None)
    body["appId"] = ""
    resp = save_node(body, account_id, authorization, cookie)
    if resp.get("status") != 1:
        raise RuntimeError(f"saveNode 失败: {resp}")
    return {"process_id": process_id, "node_id": node_id}


def test_ai_object(account_id, authorization, cookie, worksheet_id):
    """8. AI对象 (typeId=31, actionId="532", appType=46)"""
    process_id = create_workflow("测试-AI对象", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    node_id = add_node(process_id, start_node_id, "AI 生成数据对象", 31, "532", 46, "",
                       account_id, authorization, cookie)

    body = make_base_body(process_id, node_id, 31, "AI 生成数据对象", "532", 46, is_exception=False)
    body.pop("isException", None)
    resp = save_node(body, account_id, authorization, cookie)
    if resp.get("status") != 1:
        raise RuntimeError(f"saveNode 失败: {resp}")
    return {"process_id": process_id, "node_id": node_id}


def test_ai_agent(account_id, authorization, cookie, worksheet_id):
    """9. AI Agent (typeId=33, actionId="533", appType=48)"""
    process_id = create_workflow("测试-AI Agent", worksheet_id, account_id, authorization, cookie)
    if not process_id:
        raise RuntimeError("创建工作流失败")
    start_node_id = get_start_node_id(process_id, account_id, authorization, cookie)

    node_id = add_node(process_id, start_node_id, "AI Agent", 33, "533", 48, "",
                       account_id, authorization, cookie)

    body = make_base_body(process_id, node_id, 33, "AI Agent", "533", 48, is_exception=False)
    body.pop("isException", None)
    body["appId"] = ""
    body["tools"] = []
    resp = save_node(body, account_id, authorization, cookie)
    if resp.get("status") != 1:
        raise RuntimeError(f"saveNode 失败: {resp}")
    return {"process_id": process_id, "node_id": node_id}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TESTS = [
    ("校准记录",  "typeId=6, actionId='6'",   test_calibrate_record),
    ("汇总",      "typeId=9, actionId='107'",  test_aggregate),
    ("填写",      "typeId=3",                  test_fill),
    ("审批",      "typeId=26",                 test_approval),
    ("分支网关+条件", "typeId=1+2",            test_branch),
    ("循环",      "typeId=29, actionId='210'", test_loop),
    ("AI文本",    "typeId=31, actionId='531'", test_ai_text),
    ("AI对象",    "typeId=31, actionId='532'", test_ai_object),
    ("AI Agent",  "typeId=33, actionId='533'", test_ai_agent),
]


def main():
    print("=" * 70)
    print("工作流节点 P0 测试脚本")
    print("=" * 70)

    # 加载认证
    print("\n[Auth] 加载认证配置...")
    try:
        account_id, authorization, cookie = load_auth(AUTH_PATH)
        print(f"  account_id={account_id[:8]}...  authorization={'*' * 8}")
    except Exception as e:
        print(f"  ✗ 认证加载失败: {e}")
        sys.exit(1)

    # 获取工作表 ID
    print("\n[WorksheetID] 获取可用工作表...")
    worksheet_id = get_worksheet_id(account_id, authorization, cookie)
    if not worksheet_id:
        # 尝试通过 GetAppWorksheets 获取
        url = f"{WEB_BASE}/api/AppManagement/GetAppWorksheets"
        resp = api_post(url, {"appId": APP_ID}, account_id, authorization, cookie)
        sheets = resp.get("data", [])
        if sheets:
            worksheet_id = sheets[0].get("workSheetId", "")
    if not worksheet_id:
        print("  ✗ 无法获取工作表 ID，使用空字符串（触发器不绑定工作表）")
    else:
        print(f"  ✓ worksheetId={worksheet_id}")

    # 执行测试
    results = []
    for name, desc, test_fn in TESTS:
        print(f"\n[测试] {name} ({desc})")
        t0 = time.time()
        try:
            detail = test_fn(account_id, authorization, cookie, worksheet_id)
            elapsed = round((time.time() - t0) * 1000)
            print(f"  ✓ PASS  ({elapsed}ms)  {detail}")
            results.append((name, desc, "PASS", "", elapsed, detail))
        except Exception as e:
            elapsed = round((time.time() - t0) * 1000)
            err_msg = str(e)
            print(f"  ✗ FAIL  ({elapsed}ms)  {err_msg}")
            results.append((name, desc, "FAIL", err_msg, elapsed, {}))
        time.sleep(0.3)  # 避免请求过于密集

    # 汇总表
    print("\n" + "=" * 70)
    print("汇总结果")
    print("=" * 70)
    header = f"{'节点名':<18} {'描述':<24} {'结果':<6} {'耗时(ms)':<10} {'错误信息'}"
    print(header)
    print("-" * 70)
    passed = 0
    failed = 0
    for name, desc, status, err_msg, elapsed, _ in results:
        status_icon = "PASS" if status == "PASS" else "FAIL"
        err_display = err_msg[:50] if err_msg else "-"
        print(f"{name:<18} {desc:<24} {status_icon:<6} {elapsed:<10} {err_display}")
        if status == "PASS":
            passed += 1
        else:
            failed += 1

    print("-" * 70)
    print(f"总计: {len(results)} 个节点  PASS: {passed}  FAIL: {failed}")
    print("=" * 70)

    # 详细错误信息（如有）
    if failed > 0:
        print("\n[详细错误信息]")
        for name, desc, status, err_msg, elapsed, _ in results:
            if status == "FAIL":
                print(f"\n  节点: {name} ({desc})")
                print(f"  错误: {err_msg}")


if __name__ == "__main__":
    main()
