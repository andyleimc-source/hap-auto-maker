#!/usr/bin/env python3
"""
执行工作流规划 JSON，批量创建工作流（execute_workflow_plan.py）

读取 output/pipeline_workflows_latest.json（由 pipeline_workflows.py 生成），
批量创建工作流，每个工作流包含触发节点 + 2-3 个有字段映射的动作节点：
  - 自定义动作 × 3  （仅约一半工作表；触发：按钮；动作节点：来自规划）
  - 工作表事件触发 × 2（每个工作表；触发：数据变化；动作节点：来自规划）
  - 全局时间触发 × 2  （整个应用共 2 个；动作节点：来自规划）

字段值中的 {{trigger.FIELD_ID}} 会在执行时自动替换为 $startNodeId-FIELD_ID$。

用法：
  cd /Users/andy/Desktop/hap_auto/workflow

  python3 scripts/execute_workflow_plan.py
  python3 scripts/execute_workflow_plan.py --skip-existing
  python3 scripts/execute_workflow_plan.py --plan-file output/my_plan.json
  python3 scripts/execute_workflow_plan.py --only-worksheet 69aead6f952cd046bb57e3f2
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from workflow_io import Session, persist


_WORKSHEET_ID_RE = re.compile(r"^[0-9a-f]{24}$")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    default_auth_config = project_root / "config" / "credentials" / "auth_config.py"
    scripts_dir = Path(__file__).parent
    default_plan = scripts_dir.parent / "output" / "pipeline_workflows_latest.json"

    parser = argparse.ArgumentParser(
        description="执行 pipeline_workflows_latest.json，批量创建工作流（含动作节点和字段映射）。"
    )
    parser.add_argument("--plan-file", default=str(default_plan), help="工作流规划 JSON 文件路径。")
    parser.add_argument("--cookie", default="", help="Cookie header 值。")
    parser.add_argument("--auth-config", default=str(default_auth_config), help="auth_config.py 路径。")
    parser.add_argument("--origin", default="https://www.mingdao.com", help="请求 Origin header。")
    parser.add_argument("--no-publish", action="store_true", help="跳过发布步骤，工作流保持关闭状态（默认自动发布）。")
    parser.add_argument("--publish", action="store_true", help="（兼容旧参数）等同于默认行为，保留向后兼容。")
    parser.add_argument("--publish-custom-actions", action="store_true", help="（兼容旧参数）自定义动作创建后立即发布，推荐改用默认行为。")
    parser.add_argument("--only-worksheet", default="", help="只执行指定工作表 ID（调试用）。")
    parser.add_argument("--skip-existing", action="store_true", help="跳过已存在同名工作流（防重复）。")
    return parser.parse_args()


# ── 认证解析 ───────────────────────────────────────────────────────────────────

def load_auth_from_auth_config(path: Path) -> tuple[str, str, str]:
    if not path.exists():
        return "", "", ""
    spec = importlib.util.spec_from_file_location("auth_config_runtime", str(path))
    if spec is None or spec.loader is None:
        return "", "", ""
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return (
        str(getattr(module, "ACCOUNT_ID", "")).strip(),
        str(getattr(module, "AUTHORIZATION", "")).strip(),
        str(getattr(module, "COOKIE", "")).strip(),
    )


def resolve_auth(cli_cookie: str, auth_config_path: Path) -> tuple[str, str, str, str]:
    account_id    = os.environ.get("MINGDAO_ACCOUNT_ID", "").strip()
    authorization = os.environ.get("MINGDAO_AUTHORIZATION", "").strip()

    if cli_cookie.strip():
        return account_id, authorization, cli_cookie.strip(), "cli"
    env_cookie = os.environ.get("MINGDAO_COOKIE", "").strip()
    if env_cookie:
        return account_id, authorization, env_cookie, "env"

    cfg_account_id, cfg_authorization, cfg_cookie = load_auth_from_auth_config(auth_config_path)
    if cfg_cookie:
        return cfg_account_id, cfg_authorization, cfg_cookie, f"auth_config:{auth_config_path}"
    return "", "", "", "none"


# ── 去重 ───────────────────────────────────────────────────────────────────────

def fetch_existing_names(session: Session, app_id: str) -> set[str]:
    try:
        resp  = session.get(f"https://api.mingdao.com/workflow/v1/process/listAll?relationId={app_id}")
        names: set[str] = set()
        for group in resp.get("data") or []:
            for item in group.get("processList") or []:
                name = item.get("name", "")
                if name:
                    names.add(name)
        print(f"[skip-existing] 已有工作流 {len(names)} 个", file=sys.stderr)
        return names
    except Exception as exc:
        print(f"[skip-existing] 拉取失败，不跳过：{exc}", file=sys.stderr)
        return set()


# ── 发布工作流 ────────────────────────────────────────────────────────────────

def publish_process(session: Session, process_id: str) -> bool:
    """调用 process/publish 将工作流设为开启状态，返回是否成功。"""
    try:
        resp = session.get(
            f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={process_id}",
        )
        data = resp.get("data") or {}
        is_publish = data.get("isPublish")
        error_nodes = data.get("errorNodeIds") or []
        warnings = data.get("processWarnings") or []
        if is_publish:
            print(f"    process/publish → ✓ 已开启", file=sys.stderr)
            return True
        else:
            print(f"    process/publish → ✗ 未开启  errorNodes={error_nodes}  warnings={warnings}", file=sys.stderr)
            # 如果有错误节点，尝试第二次发布（某些场景下首次调用仅做校验）
            if error_nodes:
                print(f"    process/publish → 重试发布...", file=sys.stderr)
                resp2 = session.get(
                    f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={process_id}",
                )
                data2 = resp2.get("data") or {}
                if data2.get("isPublish"):
                    print(f"    process/publish → ✓ 重试成功，已开启", file=sys.stderr)
                    return True
                print(f"    process/publish → ✗ 重试仍失败  errorNodes={data2.get('errorNodeIds')}", file=sys.stderr)
            return False
    except Exception as exc:
        print(f"    process/publish → 异常：{exc}", file=sys.stderr)
        return False


# ── 动作节点：字段值处理 & 创建 ───────────────────────────────────────────────

def _resolve_field_value(raw_value: str, start_node_id: str) -> str:
    """
    将 {{trigger.FIELD_ID}} 替换为 $startNodeId-FIELD_ID$，支持多个占位符。
    时间触发类工作流的字段值不应包含占位符，但也不会报错——只是替换后无意义。
    """
    if not isinstance(raw_value, str):
        return str(raw_value) if raw_value is not None else ""
    return re.sub(
        r"\{\{trigger\.([^}]+)\}\}",
        lambda m: f"${start_node_id}-{m.group(1)}$",
        raw_value,
    )


def _build_fields(raw_fields: list, start_node_id: str) -> list:
    """处理字段数组：替换动态引用，补全 nodeAppId。"""
    result = []
    for f in raw_fields:
        field = {
            "fieldId":     f.get("fieldId", ""),
            "type":        f.get("type", 2),
            "enumDefault": f.get("enumDefault", 0),
            "fieldValue":  _resolve_field_value(str(f.get("fieldValue", "") or ""), start_node_id),
            "nodeAppId":   f.get("nodeAppId", ""),
        }
        if field["fieldId"]:
            result.append(field)
    return result


def _sanitize_action_fields(raw_fields: list, action_index: int) -> tuple[list[dict], list[str]]:
    sanitized: list[dict] = []
    warnings: list[str] = []

    for field_index, field in enumerate(raw_fields or [], 1):
        if not isinstance(field, dict):
            warnings.append(f"动作{action_index} 字段{field_index} 不是对象，已跳过")
            continue

        field_id = str(field.get("fieldId", "")).strip()
        raw_type = field.get("type")
        try:
            field_type = int(raw_type)
        except (TypeError, ValueError):
            warnings.append(f"动作{action_index} 字段{field_index} type 非法({raw_type!r})，已跳过")
            continue

        if not field_id:
            warnings.append(f"动作{action_index} 字段{field_index} fieldId 为空，已跳过")
            continue

        sanitized.append(
            {
                **field,
                "fieldId": field_id,
                "type": field_type,
            }
        )

    return sanitized, warnings


def _sanitize_action_nodes(action_nodes: list, trigger_worksheet_id: str) -> tuple[list[dict], list[str]]:
    """
    兜底清洗 AI 产出的动作节点，避免明显非法的计划直接打到 HAP：
    - target_worksheet_id 必须是合法工作表 ID
    - add_record / update_record 至少要有 1 个字段映射
    """
    sanitized: list[dict] = []
    warnings: list[str] = []

    for index, node in enumerate(action_nodes or [], 1):
        if not isinstance(node, dict):
            warnings.append(f"动作{index} 不是对象，已跳过")
            continue

        node_type = str(node.get("type", "update_record")).strip() or "update_record"
        if node_type not in {"add_record", "update_record"}:
            warnings.append(f"动作{index} 类型非法({node_type})，已跳过")
            continue

        target_ws = str(node.get("target_worksheet_id", "")).strip()
        if not target_ws and node_type == "update_record":
            target_ws = trigger_worksheet_id
        if not _WORKSHEET_ID_RE.fullmatch(target_ws):
            warnings.append(f"动作{index} 目标工作表ID非法({target_ws or '空'})，已跳过")
            continue

        raw_fields = node.get("fields")
        if not isinstance(raw_fields, list) or not raw_fields:
            warnings.append(f"动作{index} 未提供字段映射，已跳过")
            continue

        sanitized_fields, field_warnings = _sanitize_action_fields(raw_fields, index)
        warnings.extend(field_warnings)
        if not sanitized_fields:
            warnings.append(f"动作{index} 清洗后无有效字段映射，已跳过")
            continue
        if node_type == "add_record" and len(sanitized_fields) < 2:
            warnings.append(f"动作{index} add_record 字段映射过少({len(sanitized_fields)})，已跳过")
            continue

        sanitized.append(
            {
                **node,
                "type": node_type,
                "target_worksheet_id": target_ws,
                "fields": sanitized_fields,
            }
        )

    return sanitized, warnings


def add_action_nodes(
    session:       Session,
    process_id:    str,
    start_node_id: str,
    worksheet_id:  str,
    action_nodes:  list,
) -> list[dict]:
    """
    按顺序创建 action_nodes 列表中每个节点，链式串联（前一个节点的 ID 作为下一个的 prveId）。

    - prveId：上一个节点 ID（控制 UI 中的连接关系）
    - selectNodeId：始终为 start_node_id（记录上下文来源于触发节点）
    - fieldValue 中的 {{trigger.xxx}} 在此处替换为 $startNodeId-xxx$

    若 action_nodes 为空，自动添加一个默认空节点（防止工作流无动作）。
    """
    if not action_nodes:
        # 兜底：至少保证一个空节点
        action_nodes = [{"name": "更新记录", "type": "update_record", "target_worksheet_id": worksheet_id, "fields": []}]

    results: list[dict]  = []
    prev_node_id: str    = start_node_id

    for i, node_plan in enumerate(action_nodes, 1):
        node_type = node_plan.get("type", "update_record")
        action_id = "1" if node_type == "add_record" else "2"
        name      = node_plan.get("name", f"动作节点{i}")
        target_ws = node_plan.get("target_worksheet_id", "") or worksheet_id
        fields    = _build_fields(node_plan.get("fields", []), start_node_id)

        print(
            f"      [动作{i}] {name}  type={node_type}  fields={len(fields)}  target={target_ws[:16]}",
            file=sys.stderr,
        )

        # Step A: 添加节点骨架
        add_resp = session.post(
            "https://api.mingdao.com/workflow/flowNode/add",
            {
                "processId": process_id,
                "actionId":  action_id,
                "appType":   1,
                "name":      name,
                "prveId":    prev_node_id,
                "typeId":    6,
            },
        )
        print(f"        flowNode/add → status={add_resp.get('status')}", file=sys.stderr)

        if add_resp.get("status") != 1:
            results.append({"ok": False, "step": "flowNode/add", "name": name, "raw": add_resp})
            continue

        added = add_resp.get("data", {}).get("addFlowNodes", [])
        if not added:
            results.append({"ok": False, "step": "addFlowNodes empty", "name": name})
            continue

        node_id = added[0]["id"]

        # Step B: 保存节点配置（含字段映射）
        save_resp = session.post(
            "https://api.mingdao.com/workflow/flowNode/saveNode",
            {
                "processId":    process_id,
                "nodeId":       node_id,
                "flowNodeType": 6,
                "actionId":     action_id,
                "name":         name,
                # update_record: selectNodeId = 触发节点（提供记录上下文）
                # add_record:    selectNodeId = ""
                "selectNodeId": start_node_id if action_id == "2" else "",
                "appId":        target_ws,
                "appType":      1,
                "fields":       fields,
                "filters":      [],
            },
        )
        ok = save_resp.get("status") == 1
        print(
            f"        flowNode/saveNode → status={save_resp.get('status')} msg={save_resp.get('msg')!r}",
            file=sys.stderr,
        )

        results.append({
            "ok":          ok,
            "node_id":     node_id,
            "type":        node_type,
            "name":        name,
            "fields_count": len(fields),
        })
        if ok:
            prev_node_id = node_id  # 下一个节点接在本节点之后

    return results


# ── 创建自定义动作工作流 ───────────────────────────────────────────────────────

def create_custom_action(
    session:      Session,
    worksheet_id: str,
    app_id:       str,
    action_plan:  dict,
    publish:      bool = False,
) -> dict:
    name        = action_plan.get("name", "未命名按钮")
    confirm_msg = action_plan.get("confirm_msg", "你确认执行此操作吗？")
    sure_name   = action_plan.get("sure_name", "确认")
    cancel_name = action_plan.get("cancel_name", "取消")
    action_nodes_plan, action_warnings = _sanitize_action_nodes(
        action_plan.get("action_nodes", []), worksheet_id
    )
    for warning in action_warnings:
        print(f"    [plan-skip] {warning}", file=sys.stderr)
    if not action_nodes_plan:
        return {
            "ok": True,
            "skipped": True,
            "trigger_type": "custom_action",
            "name": name,
            "reason": "no_valid_action_nodes",
            "warnings": action_warnings,
        }

    btn_payload = {
        "btnId": "",
        "name": name,
        "worksheetId": worksheet_id,
        "filters": [],
        "confirmMsg": confirm_msg,
        "sureName": sure_name,
        "cancelName": cancel_name,
        "workflowId": "",
        "desc": "",
        "appId": app_id,
        "isAllView": 1,
        "color": "transparent",
        "icon": "",
        "writeControls": [],
        "addRelationControlId": "",
        "relationControl": "",
        "writeType": "",
        "writeObject": "",
        "clickType": 1,
        "showType": 1,
        "advancedSetting": {"remarkrequired": "1", "remarkname": "操作原因", "tiptext": "操作完成"},
        "workflowType": 1,
    }

    # Step 1: 创建按钮（后端自动创建工作流）
    btn_resp = session.post("https://www.mingdao.com/api/Worksheet/SaveWorksheetBtn", btn_payload)
    print(f"    SaveWorksheetBtn → state={btn_resp.get('state')}", file=sys.stderr)
    if btn_resp.get("state") != 1:
        return {"ok": False, "step": "SaveWorksheetBtn(create)", "raw": btn_resp}

    btn_id = str(btn_resp.get("data", "")).strip()
    if not btn_id:
        return {"ok": False, "step": "btnId empty", "raw": btn_resp}

    # Step 2: 获取 processId + startEventId
    trigger_resp = session.get(
        f"https://api.mingdao.com/workflow/process/getProcessByTriggerId"
        f"?appId={worksheet_id}&triggerId={btn_id}",
    )
    print(f"    getProcessByTriggerId → status={trigger_resp.get('status')}", file=sys.stderr)
    if trigger_resp.get("status") != 1:
        return {"ok": False, "step": "getProcessByTriggerId", "raw": trigger_resp}

    processes = trigger_resp.get("data") or []
    if not processes:
        return {"ok": False, "step": "no process found", "raw": trigger_resp}

    process        = processes[0]
    process_id     = str(process.get("id", "")).strip()
    start_event_id = str(process.get("startEventId", "")).strip()
    if not process_id:
        return {"ok": False, "step": "processId empty", "raw": trigger_resp}

    # Step 3: 回填 workflowId
    btn_payload_update = dict(btn_payload)
    btn_payload_update["btnId"]      = btn_id
    btn_payload_update["workflowId"] = process_id
    session.post("https://www.mingdao.com/api/Worksheet/SaveWorksheetBtn", btn_payload_update)

    # Step 4: 创建动作节点（含字段映射）
    action_results = []
    if start_event_id:
        print(f"    [action nodes] 创建 {len(action_nodes_plan) or 1} 个...", file=sys.stderr)
        action_results = add_action_nodes(session, process_id, start_event_id, worksheet_id, action_nodes_plan)

    # Step 5: 发布（动作节点创建完后再发布）
    published = False
    if publish:
        published = publish_process(session, process_id)

    return {
        "ok":            True,
        "trigger_type":  "custom_action",
        "name":          name,
        "btn_id":        btn_id,
        "process_id":    process_id,
        "start_event_id": start_event_id,
        "publish_status": 1 if published else 0,
        "action_nodes":  action_results,
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{process_id}",
    }


# ── 创建工作表事件触发工作流 ───────────────────────────────────────────────────

def create_worksheet_event(
    session:           Session,
    relation_id:       str,
    worksheet_id:      str,
    event_plan:        dict,
    publish:           bool = False,
) -> dict:
    name             = event_plan.get("name", "工作表事件触发")
    trigger_id       = str(event_plan.get("trigger_id", "2"))
    action_nodes_plan, action_warnings = _sanitize_action_nodes(
        event_plan.get("action_nodes", []), worksheet_id
    )
    for warning in action_warnings:
        print(f"    [plan-skip] {warning}", file=sys.stderr)
    if not action_nodes_plan:
        return {
            "ok": True,
            "skipped": True,
            "trigger_type": "worksheet_event",
            "name": name,
            "reason": "no_valid_action_nodes",
            "warnings": action_warnings,
        }

    # Step 1: 创建工作流
    add_resp = session.post(
        "https://api.mingdao.com/workflow/process/add",
        {"companyId": "", "relationId": relation_id, "relationType": 2,
         "startEventAppType": 1, "name": name, "explain": ""},
    )
    print(f"    process/add → status={add_resp.get('status')}", file=sys.stderr)
    if add_resp.get("status") != 1:
        return {"ok": False, "step": "process/add", "raw": add_resp}

    data       = add_resp.get("data") or {}
    process_id = str(data.get("id", "")).strip()
    company_id = str(data.get("companyId", "")).strip()
    if not (process_id and company_id):
        return {"ok": False, "step": "process_id/company_id empty", "raw": add_resp}

    # Step 2: 注册到 AppManagement
    session.post(
        "https://www.mingdao.com/api/AppManagement/AddWorkflow",
        {"projectId": company_id, "name": name},
        extra_headers={"Referer": f"https://www.mingdao.com/workflowedit/{process_id}"},
    )

    # Step 3: 获取 startNodeId
    pub_resp = session.get(
        f"https://api.mingdao.com/workflow/process/getProcessPublish?processId={process_id}",
    )
    start_node_id = ""
    if pub_resp.get("status") == 1:
        start_node_id = str((pub_resp.get("data") or {}).get("startNodeId", "")).strip()
    print(f"    getProcessPublish → startNodeId={start_node_id!r}", file=sys.stderr)

    action_results = []
    if start_node_id:
        # Step 4: 配置触发节点（绑定工作表）
        session.post(
            "https://api.mingdao.com/workflow/flowNode/saveNode",
            {
                "appId": worksheet_id, "appType": 1, "assignFieldIds": [],
                "processId": process_id, "nodeId": start_node_id,
                "flowNodeType": 0, "operateCondition": [],
                "triggerId": trigger_id, "name": "工作表事件触发", "controls": [],
            },
        )

        # Step 5: 创建动作节点（含字段映射）
        print(f"    [action nodes] 创建 {len(action_nodes_plan) or 1} 个...", file=sys.stderr)
        action_results = add_action_nodes(session, process_id, start_node_id, worksheet_id, action_nodes_plan)

    # Step 6: 发布
    published = False
    if publish and process_id:
        published = publish_process(session, process_id)

    return {
        "ok": True, "trigger_type": "worksheet_event",
        "name": name, "process_id": process_id, "trigger_id": trigger_id,
        "start_node_configured": bool(start_node_id),
        "action_nodes": action_results, "publish_status": 1 if published else 0,
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{process_id}",
    }


# ── 创建时间触发工作流（一次性 & 循环，共用逻辑）─────────────────────────────

def _create_time_based(
    session:          Session,
    relation_id:      str,
    worksheet_id:     str,
    trigger_plan:     dict,
    trigger_type_str: str,
    publish:          bool = False,
) -> dict:
    name             = trigger_plan.get("name", "定时触发")
    execute_time     = trigger_plan.get("execute_time", "")
    execute_end_time = trigger_plan.get("execute_end_time", "")
    repeat_type      = str(trigger_plan.get("repeat_type", "1"))
    interval         = int(trigger_plan.get("interval", 1))
    frequency        = int(trigger_plan.get("frequency", 7))
    week_days        = trigger_plan.get("week_days") or []
    action_nodes_plan, action_warnings = _sanitize_action_nodes(
        trigger_plan.get("action_nodes", []), worksheet_id
    )
    for warning in action_warnings:
        print(f"    [plan-skip] {warning}", file=sys.stderr)
    if not action_nodes_plan:
        return {
            "ok": True,
            "skipped": True,
            "trigger_type": trigger_type_str,
            "name": name,
            "reason": "no_valid_action_nodes",
            "warnings": action_warnings,
        }

    # Step 1: 创建工作流
    add_resp = session.post(
        "https://api.mingdao.com/workflow/process/add",
        {"companyId": "", "relationId": relation_id, "relationType": 2,
         "startEventAppType": 5, "name": name, "explain": ""},
    )
    print(f"    process/add → status={add_resp.get('status')}", file=sys.stderr)
    if add_resp.get("status") != 1:
        return {"ok": False, "step": "process/add", "raw": add_resp}

    data       = add_resp.get("data") or {}
    process_id = str(data.get("id", "")).strip()
    company_id = str(data.get("companyId", "")).strip()
    if not (process_id and company_id):
        return {"ok": False, "step": "process_id/company_id empty", "raw": add_resp}

    # Step 2: 注册到 AppManagement
    session.post(
        "https://www.mingdao.com/api/AppManagement/AddWorkflow",
        {"projectId": company_id, "name": name},
        extra_headers={"Referer": f"https://www.mingdao.com/workflowedit/{process_id}"},
    )

    # Step 3: 获取 startNodeId
    pub_resp = session.get(
        f"https://api.mingdao.com/workflow/process/getProcessPublish?processId={process_id}",
    )
    start_node_id = ""
    if pub_resp.get("status") == 1:
        start_node_id = str((pub_resp.get("data") or {}).get("startNodeId", "")).strip()
    print(f"    getProcessPublish → startNodeId={start_node_id!r}", file=sys.stderr)

    action_results = []
    if start_node_id:
        # Step 4: 配置定时触发节点
        session.post(
            "https://api.mingdao.com/workflow/flowNode/saveNode",
            {
                "appType": 5, "assignFieldIds": [], "processId": process_id,
                "nodeId": start_node_id, "flowNodeType": 0, "name": "定时触发",
                "executeTime": execute_time, "executeEndTime": execute_end_time,
                "repeatType": repeat_type, "interval": interval,
                "frequency": frequency, "weekDays": week_days,
                "controls": [], "returns": [],
            },
        )

        # Step 5: 创建动作节点（时间触发：字段值不应含 trigger 引用，但不报错）
        print(f"    [action nodes] 创建 {len(action_nodes_plan) or 1} 个...", file=sys.stderr)
        action_results = add_action_nodes(session, process_id, start_node_id, worksheet_id, action_nodes_plan)

    # Step 6: 发布
    published = False
    if publish and process_id:
        published = publish_process(session, process_id)

    return {
        "ok": True, "trigger_type": trigger_type_str,
        "name": name, "process_id": process_id,
        "execute_time": execute_time, "repeat_type": repeat_type,
        "timer_configured": bool(start_node_id),
        "action_nodes": action_results, "publish_status": 1 if published else 0,
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{process_id}",
    }


# ── 执行单个工作表的工作流（自定义动作 0 或 3 个 + 事件触发 2 个）────────────

def execute_worksheet_plan(
    session:               Session,
    app_id:                str,
    ws_plan:               dict,
    publish:               bool = False,
    publish_custom_actions: bool = False,
    existing_names:        set | None = None,
) -> dict:
    worksheet_id   = ws_plan.get("worksheet_id", "")
    worksheet_name = ws_plan.get("worksheet_name", worksheet_id)
    results: list[dict] = []

    def _skip(name: str) -> bool:
        if existing_names and name in existing_names:
            print(f"    ⏭  跳过（已存在）：{name}", file=sys.stderr)
            return True
        return False

    # ── 自定义动作（仅被选中工作表有，每个 3 个）────────────────────────────
    ca_plans = (ws_plan.get("custom_actions") or [])[:3]
    for i, action_plan in enumerate(ca_plans, 1):
        name = action_plan.get("name", f"自定义动作{i}")
        print(f"\n  [自定义动作 {i}/{len(ca_plans)}]「{name}」", file=sys.stderr)
        if _skip(name):
            results.append({"ok": True, "skipped": True, "name": name, "seq": i}); continue
        try:
            r = create_custom_action(session, worksheet_id, app_id, action_plan, publish or publish_custom_actions)
        except Exception as exc:
            r = {"ok": False, "step": "exception", "error": str(exc)}
            print(f"    ❌ 异常：{exc}", file=sys.stderr)
        r["seq"] = i
        results.append(r)
        print(f"    {'✓' if r.get('ok') else '✗'}  process_id={r.get('process_id')}", file=sys.stderr)

    # ── 2 个工作表事件触发 ────────────────────────────────────────────────────
    ev_plans = (ws_plan.get("worksheet_events") or [])[:2]
    for j, event_plan in enumerate(ev_plans, 1):
        ev_name  = event_plan.get("name", f"工作表事件触发{j}")
        print(f"\n  [事件触发 {j}/{len(ev_plans)}]「{ev_name}」", file=sys.stderr)
        if _skip(ev_name):
            results.append({"ok": True, "skipped": True, "name": ev_name, "seq": len(ca_plans) + j}); continue
        try:
            r = create_worksheet_event(session, app_id, worksheet_id, event_plan, publish)
        except Exception as exc:
            r = {"ok": False, "step": "exception", "error": str(exc)}
            print(f"    ❌ 异常：{exc}", file=sys.stderr)
        r["seq"] = len(ca_plans) + j
        results.append(r)
        print(f"    {'✓' if r.get('ok') else '✗'}  process_id={r.get('process_id')}", file=sys.stderr)

    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "worksheet_id": worksheet_id, "worksheet_name": worksheet_name,
        "total": len(results), "ok": ok_count, "failed": len(results) - ok_count,
        "workflows": results,
    }


# ── 执行全局时间触发工作流（整个应用共 2 个）─────────────────────────────────

def execute_time_triggers(
    session:        Session,
    app_id:         str,
    time_triggers:  list,
    fallback_ws_id: str,
    publish:        bool = False,
    existing_names: set | None = None,
) -> list[dict]:
    """执行规划中全局的 time_triggers（最多 2 个）。"""
    results: list[dict] = []
    tt_list = time_triggers[:2]
    for i, tt_plan in enumerate(tt_list, 1):
        name = tt_plan.get("name", f"定时触发{i}")
        print(f"\n  [时间触发 {i}/{len(tt_list)}]「{name}」", file=sys.stderr)
        if existing_names and name in existing_names:
            print(f"    ⏭  跳过（已存在）：{name}", file=sys.stderr)
            results.append({"ok": True, "skipped": True, "name": name}); continue
        try:
            r = _create_time_based(session, app_id, fallback_ws_id, tt_plan, "time_trigger", False)
        except Exception as exc:
            r = {"ok": False, "step": "exception", "error": str(exc)}
            print(f"    ❌ 异常：{exc}", file=sys.stderr)
        results.append(r)
        print(f"    {'✓' if r.get('ok') else '✗'}  process_id={r.get('process_id')}", file=sys.stderr)
    return results


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    started_at  = time.time()
    args        = parse_args()
    script_name = Path(__file__).stem
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    log_args    = {k: v for k, v in vars(args).items() if k != "cookie"}

    # 默认发布；只有传 --no-publish 才跳过
    do_publish = not args.no_publish

    # 1. 读取规划文件
    plan_path = Path(args.plan_file).expanduser().resolve()
    print(f"\n[step 1/3] 读取规划文件：{plan_path}", file=sys.stderr)
    if not plan_path.exists():
        msg = (
            f"规划文件不存在：{plan_path}\n"
            "  请先运行：python3 scripts/pipeline_workflows.py --relation-id <appId>"
        )
        print(f"Error: {msg}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=msg, started_at=started_at)
        return 2

    plan          = json.loads(plan_path.read_text(encoding="utf-8"))
    app_id        = plan.get("app_id", "")
    app_name      = plan.get("app_name", "未知应用")
    worksheets    = plan.get("worksheets", [])
    time_triggers = plan.get("time_triggers", [])

    if not app_id:
        persist(script_name, None, args=log_args, error="missing app_id in plan", started_at=started_at)
        return 2

    if args.only_worksheet:
        worksheets    = [ws for ws in worksheets if ws.get("worksheet_id") == args.only_worksheet]
        time_triggers = []  # 指定单表时不执行全局时间触发
        if not worksheets:
            print(f"Error: 未找到工作表 ID：{args.only_worksheet}", file=sys.stderr)
            return 2

    total_estimated = sum(
        len(ws.get("custom_actions") or []) + len(ws.get("worksheet_events") or [])
        for ws in worksheets
    ) + len(time_triggers)
    print(
        f"[step 1/3] ✓ 应用：{app_name}，{len(worksheets)} 个工作表"
        f"，全局时间触发 {len(time_triggers)} 个，预计共 {total_estimated} 个工作流",
        file=sys.stderr,
    )

    # 2. 解析认证
    account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
    if not cookie:
        msg = (
            "缺少 Cookie。\n"
            "  方式1：--cookie '...'\n"
            "  方式2：export MINGDAO_COOKIE='...'\n"
            "  方式3：在 config/credentials/auth_config.py 中设置 COOKIE 变量"
        )
        print(f"Error: {msg}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=msg, started_at=started_at)
        return 2

    print(f"[step 2/3] Cookie 来源：{cookie_source}", file=sys.stderr)
    session = Session(cookie, account_id, authorization, args.origin)

    # 3. 可选：拉取已有工作流名称
    existing_names: set | None = None
    if args.skip_existing:
        print("[step 2/3] 拉取已有工作流（--skip-existing）...", file=sys.stderr)
        existing_names = fetch_existing_names(session, app_id)

    # 4. 批量创建（按工作表）
    print(f"\n[step 3/3] 开始批量创建...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    all_results: list[dict] = []
    total_ok = total_failed = 0

    for idx, ws_plan in enumerate(worksheets, 1):
        ws_name = ws_plan.get("worksheet_name", ws_plan.get("worksheet_id", "?"))
        ws_id   = ws_plan.get("worksheet_id", "")
        print(f"\n【{idx}/{len(worksheets)}】工作表：{ws_name}（{ws_id}）", file=sys.stderr)
        try:
            ws_result = execute_worksheet_plan(
                session                = session,
                app_id                 = app_id,
                ws_plan                = ws_plan,
                publish                = do_publish,
                publish_custom_actions = args.publish_custom_actions,
                existing_names         = existing_names,
            )
        except Exception as exc:
            print(f"  ❌ 工作表执行异常：{exc}", file=sys.stderr)
            ws_result = {
                "worksheet_id": ws_id, "worksheet_name": ws_name,
                "total": 0, "ok": 0, "failed": 0,
                "error": str(exc), "workflows": [],
            }

        all_results.append(ws_result)
        total_ok     += ws_result.get("ok", 0)
        total_failed += ws_result.get("failed", 0)
        icon = "✅" if ws_result.get("failed", 0) == 0 else "⚠️ "
        print(f"  {icon} {ws_result.get('ok')}/{ws_result.get('total')} 成功", file=sys.stderr)

    # 5. 全局时间触发（3 个，跨工作表）
    tt_results: list[dict] = []
    if time_triggers:
        fallback_ws_id = worksheets[0].get("worksheet_id", "") if worksheets else ""
        print(f"\n{'=' * 60}", file=sys.stderr)
        print(f"【全局时间触发】共 {len(time_triggers)} 个", file=sys.stderr)
        tt_results = execute_time_triggers(
            session        = session,
            app_id         = app_id,
            time_triggers  = time_triggers,
            fallback_ws_id = fallback_ws_id,
            publish        = do_publish,
            existing_names = existing_names,
        )
        tt_ok     = sum(1 for r in tt_results if r.get("ok"))
        tt_failed = len(tt_results) - tt_ok
        total_ok     += tt_ok
        total_failed += tt_failed
        icon = "✅" if tt_failed == 0 else "⚠️ "
        print(f"  {icon} 时间触发 {tt_ok}/{len(tt_results)} 成功", file=sys.stderr)

    # 6. 汇总输出
    import datetime as _dt
    output = {
        "app_id": app_id, "app_name": app_name,
        "plan_file": str(plan_path),
        "executed_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "total_workflows": total_ok + total_failed,
        "ok": total_ok, "failed": total_failed,
        "worksheet_count": len(all_results),
        "publish": do_publish,
        "publish_custom_actions": args.publish_custom_actions,
        "skip_existing": args.skip_existing,
        "worksheets": all_results,
        "time_triggers": tt_results,
    }

    persist(script_name, output, args=log_args, started_at=started_at, session=session)

    print("\n" + "=" * 60, file=sys.stderr)
    icon = "✅" if total_failed == 0 else "⚠️ "
    print(f"{icon} 执行完成！应用：{app_name}", file=sys.stderr)
    print(f"   工作流成功：{total_ok} / {total_ok + total_failed}", file=sys.stderr)
    if total_failed:
        print(f"   ⚠️  失败数：{total_failed}（详见 logs/ 目录）", file=sys.stderr)
    print(f"   结果文件：output/execute_workflow_plan_latest.json", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
