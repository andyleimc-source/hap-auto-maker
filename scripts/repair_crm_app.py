#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
针对 CRM 客户管理系统 (f11f2128-c4de-46cb-a2be-fe1c62ed1481) 的定向修复脚本。

修复内容：
  问题 1: 重命名"未命名分组"→"数据分析"  [已完成]
  问题 3: 甘特图视图补发二次保存          [已完成]
  问题 4: 层级视图补发二次保存            [已完成]
  问题 6+7: 修复 3 个工作流 → publish
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))
sys.path.insert(0, str(BASE_DIR / "workflow" / "scripts"))

import auth_retry
from workflow_io import Session

APP_ID = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"
REFERER = f"https://www.mingdao.com/app/{APP_ID}"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"


def web_post(endpoint: str, payload: dict) -> dict:
    url = f"https://www.mingdao.com/api/{endpoint}"
    resp = auth_retry.hap_web_post(url, AUTH_CONFIG_PATH, referer=REFERER, json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        text = resp.text.strip().lower()
        if text in ("true", "1"):
            return {"data": True, "state": 1}
        return {"raw_text": resp.text, "status_code": resp.status_code}


def get_ws_fields(ws_id: str) -> list[dict]:
    """获取工作表字段列表。"""
    resp = web_post("Worksheet/GetWorksheetInfo", {"worksheetId": ws_id, "getTemplate": True})
    return resp.get("data", {}).get("template", {}).get("controls", [])


# ─── 工作流修复 ──────────────────────────────────────────────────────────────

def fix_error_node(session: Session, process_id: str, node_id: str, proc_name: str) -> bool:
    """修复单个错误节点，返回是否修复成功。"""
    # 获取节点详情
    detail = session.get(
        f"https://api.mingdao.com/workflow/flowNode/getNodeDetail?processId={process_id}&nodeId={node_id}"
    )
    nd = detail.get("data", {})
    action_id = nd.get("actionId", "")
    node_name = nd.get("name", "")
    target_ws = nd.get("appId", "")
    select_node = nd.get("selectNodeId", "")
    existing_fields = nd.get("fields", [])
    type_id = nd.get("flowNodeType")

    print(f"      节点「{node_name}」action={action_id} target={target_ws[:16] if target_ws else '(无)'} fields={len(existing_fields)}")

    # Case 1: update_record (action=2) 无字段 → 填一个文本字段
    if action_id == "2" and not existing_fields:
        if not target_ws:
            print(f"      ⚠ 无 target worksheet，跳过")
            return False
        controls = get_ws_fields(target_ws)
        text_field = next((c for c in controls if c.get("type") == 2 and not c.get("isSystem")), None)
        if not text_field:
            print(f"      ⚠ 未找到文本字段，跳过")
            return False
        fid = text_field["controlId"]
        print(f"      → 补充 update_record 字段: {text_field['controlName']} ({fid})")
        fields = [{
            "fieldId": fid, "type": 2, "enumDefault": 0,
            "fieldValue": "已同步", "fieldValueId": "", "fieldValueType": "",
            "nodeId": "", "nodeAppId": "",
        }]
        save_body = {
            "processId": process_id, "nodeId": node_id,
            "flowNodeType": 6, "actionId": "2",
            "name": node_name, "selectNodeId": select_node,
            "selectNodeName": "工作表事件触发",
            "appId": target_ws, "appType": 1,
            "fields": fields, "filters": [], "isException": True,
        }
        resp = session.post("https://api.mingdao.com/workflow/flowNode/saveNode", save_body)
        print(f"      saveNode → status={resp.get('status')}")
        return resp.get("status") == 1

    # Case 2: add_record (action=1) 有字段但关联字段值为空 → 移除关联字段
    if action_id == "1" and existing_fields:
        # 移除 type=29 (关联) 中 notEmptyActionField=True 且 fieldValue 为空的字段
        fixed_fields = []
        removed = 0
        for f in existing_fields:
            if f.get("type") == 29 and f.get("notEmptyActionField") and not f.get("fieldValue"):
                removed += 1
                continue
            fixed_fields.append(f)
        if removed:
            print(f"      → 移除 {removed} 个空关联字段")
            save_body = {
                "processId": process_id, "nodeId": node_id,
                "flowNodeType": 6, "actionId": "1",
                "name": node_name, "selectNodeId": select_node,
                "selectNodeName": "工作表事件触发",
                "appId": target_ws, "appType": 1,
                "fields": fixed_fields, "filters": [], "isException": True,
            }
            resp = session.post("https://api.mingdao.com/workflow/flowNode/saveNode", save_body)
            print(f"      saveNode → status={resp.get('status')}")
            return resp.get("status") == 1

    # Case 3: delete_record (action=3) → 通常缺 filter，不好自动修复
    if action_id == "3":
        print(f"      → delete_record 节点，尝试直接 publish")
        return True  # 让 publish 去判断

    # Case 4: 通知/抄送节点缺 content
    if action_id in ("", None) and not nd.get("content"):
        # 可能是通知节点
        print(f"      → 尝试补充 content")
        save_body = {
            "processId": process_id, "nodeId": node_id,
            "flowNodeType": type_id or 27,
            "name": node_name,
            "content": f"工作流「{proc_name}」已触发，请及时查看。",
            "accounts": nd.get("accounts") or [],
        }
        resp = session.post("https://api.mingdao.com/workflow/flowNode/saveNode", save_body)
        print(f"      saveNode → status={resp.get('status')}")
        return resp.get("status") == 1

    print(f"      → 无法自动修复此节点类型")
    return False


def fix_workflows() -> list[dict]:
    """修复 3 个工作流并 publish。"""
    account_id, authorization, cookie = auth_retry.load_web_auth(AUTH_CONFIG_PATH)
    session = Session(cookie, account_id, authorization)

    resp = session.get(f"https://api.mingdao.com/workflow/v1/process/listAll?relationId={APP_ID}")
    flat = []
    for group in resp.get("data", []):
        for item in group.get("processList") or []:
            flat.append(item)

    print(f"共 {len(flat)} 个工作流")
    closed = [p for p in flat if not p.get("enabled")]
    print(f"关闭的: {len(closed)} 个")

    # 优先选 warn=200（update_record 空字段，最容易修），跳过 warn=103/99
    results = []
    fixed_count = 0
    target = 3

    for proc in closed:
        if fixed_count >= target:
            break

        pid = proc["id"]
        pname = proc["name"]

        # 尝试 publish 看看哪些 error
        pub = session.get(f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={pid}")
        pd = pub.get("data", {})
        if pd.get("isPublish"):
            print(f"\n  「{pname}」→ 已经可以发布 ✓")
            results.append({"name": pname, "ok": True, "action": "already_publishable"})
            fixed_count += 1
            continue

        errors = pd.get("errorNodeIds", [])
        warnings = pd.get("processWarnings", [])
        warn_types = [w.get("warningType") for w in warnings]

        # 只处理 warn=200 的（update_record 空字段），跳过 103/99
        if 200 not in warn_types:
            continue

        print(f"\n  ── 「{pname}」warn={warn_types} errors={len(errors)} ──")

        # 修复所有错误节点
        all_fixed = True
        for enid in errors:
            ok = fix_error_node(session, pid, enid, pname)
            if not ok:
                all_fixed = False

        # 尝试 publish
        time.sleep(0.5)
        pub2 = session.get(f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={pid}")
        pd2 = pub2.get("data", {})
        is_pub = pd2.get("isPublish", False)
        remaining_errors = pd2.get("errorNodeIds", [])

        if is_pub:
            print(f"    ✓ Publish 成功!")
            results.append({"name": pname, "ok": True})
            fixed_count += 1
        else:
            # 再试一次
            time.sleep(1)
            pub3 = session.get(f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={pid}")
            pd3 = pub3.get("data", {})
            is_pub = pd3.get("isPublish", False)
            if is_pub:
                print(f"    ✓ Publish 成功（重试后）!")
                results.append({"name": pname, "ok": True})
                fixed_count += 1
            else:
                print(f"    ✗ Publish 失败: remaining errors={pd3.get('errorNodeIds')}")
                results.append({"name": pname, "ok": False, "errors": pd3.get("errorNodeIds")})
                fixed_count += 1  # 还是计数，避免无限循环

    return results


def main():
    print("=" * 60)
    print("CRM 应用修复脚本 — 工作流修复")
    print(f"应用: {APP_ID}")
    print("=" * 60)

    # 之前已经修复了：问题 1（分组重命名）、问题 3+4（甘特图/层级视图）
    # 这次只修复工作流

    print("\n修复问题 6+7: 工作流节点配置 + publish")
    print("─" * 40)
    wf_results = fix_workflows()
    ok_count = sum(1 for r in wf_results if r.get("ok"))
    print(f"\n工作流修复: {ok_count}/{len(wf_results)} publish 成功")

    print(f"\n验证链接: {REFERER}")
    print(f"工作流管理: {REFERER}/workflow")


if __name__ == "__main__":
    main()
