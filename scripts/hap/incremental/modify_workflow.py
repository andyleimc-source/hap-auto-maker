#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modify_workflow.py — 增/改/删工作流节点，复用 30 种 node registry。

流程：
  1. 获取当前工作流结构（节点列表）
  2. 加载工作表字段上下文
  3. 用 AI + node registry 规划修改方案（增/改/删节点）
  4. 执行修改：
     - 新增节点：flowNode/add + flowNode/saveNode
     - 修改节点：flowNode/saveNode（已有 nodeId）
     - 删除节点：flowNode/delete（或 flowNode/abandon）
  5. 可选发布工作流

用法（CLI）：
    python3 modify_workflow.py \\
        --workflow-id <processId> \\
        --app-id <appId> \\
        --description "在审批通过节点后增加一个邮件通知节点"

    python3 modify_workflow.py \\
        --workflow-id <processId> \\
        --app-id <appId> \\
        --description "修改第一个更新记录节点，增加设置截止日期字段"

    python3 modify_workflow.py \\
        --workflow-id <processId> \\
        --app-id <appId> \\
        --description "删除最后一个延时节点"

用法（Python）：
    from incremental.modify_workflow import modify_workflow
    result = modify_workflow(
        workflow_id="xxx",
        app_id="yyy",
        description="增加一个站内通知节点",
    )
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_HAP = BASE_DIR / "scripts" / "hap"
WORKFLOW_SCRIPTS = BASE_DIR / "workflow" / "scripts"
WORKFLOW_NODES = BASE_DIR / "workflow" / "nodes"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
INCREMENTAL_OUTPUT_DIR = OUTPUT_ROOT / "incremental"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

for p in [str(SCRIPTS_HAP), str(WORKFLOW_SCRIPTS), str(WORKFLOW_NODES.parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from incremental.app_context import load_app_context
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json
from planning.constraints import classify_fields, build_node_type_prompt_section

# 工作流节点注册中心
try:
    from nodes import NODE_REGISTRY, NODE_CONFIGS
    _NODE_REGISTRY_AVAILABLE = True
except ImportError:
    NODE_REGISTRY = {}
    NODE_CONFIGS = {}
    _NODE_REGISTRY_AVAILABLE = False

# workflow_io.Session（复用已有 Session 类）
try:
    from workflow_io import Session as _WfSession
    _WF_IO_AVAILABLE = True
except ImportError:
    _WF_IO_AVAILABLE = False
    _WfSession = None


# ── 认证工具 ───────────────────────────────────────────────────────────────────

def _load_auth_from_config(auth_config_path: Path) -> tuple[str, str, str]:
    """从 auth_config.py 加载 ACCOUNT_ID / AUTHORIZATION / COOKIE。"""
    if not auth_config_path.exists():
        return "", "", ""
    spec = importlib.util.spec_from_file_location("auth_config_runtime", str(auth_config_path))
    if spec is None or spec.loader is None:
        return "", "", ""
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return (
        str(getattr(module, "ACCOUNT_ID", "")).strip(),
        str(getattr(module, "AUTHORIZATION", "")).strip(),
        str(getattr(module, "COOKIE", "")).strip(),
    )


def _build_session(auth_config_path: Path) -> "_WfSession":
    """构建 workflow_io.Session。"""
    if not _WF_IO_AVAILABLE:
        raise RuntimeError("workflow_io 模块不可用，请确认 workflow/scripts 在 sys.path 中")
    account_id, authorization, cookie = _load_auth_from_config(auth_config_path)
    env_cookie = os.environ.get("MINGDAO_COOKIE", "").strip()
    env_account_id = os.environ.get("MINGDAO_ACCOUNT_ID", "").strip()
    env_authorization = os.environ.get("MINGDAO_AUTHORIZATION", "").strip()
    return _WfSession(
        cookie=cookie or env_cookie,
        account_id=account_id or env_account_id,
        authorization=authorization or env_authorization,
        origin="https://www.mingdao.com",
    )


# ── 工作流 API ────────────────────────────────────────────────────────────────

API_BASE = "https://api.mingdao.com"
API2_BASE = "https://api2.mingdao.com"


def fetch_workflow_detail(process_id: str, session) -> dict:
    """
    获取工作流发布信息（含 startNodeId 和各节点配置）。

    GET /workflow/process/getProcessPublish?processId={processId}
    响应：status==1，data 含 process、flowNodeList 等
    """
    resp = session.get(f"{API2_BASE}/workflow/process/getProcessPublish?processId={process_id}")
    if resp.get("status") != 1:
        raise RuntimeError(f"getProcessPublish 失败: {json.dumps(resp, ensure_ascii=False)}")
    return resp.get("data") or {}


def fetch_workflow_nodes(process_id: str, session) -> list[dict]:
    """
    获取工作流所有节点。

    GET /workflow/flowNode/get?processId={processId}
    响应：status==1，data 为节点列表
    """
    resp = session.get(f"{API_BASE}/workflow/flowNode/get?processId={process_id}")
    if resp.get("status") != 1:
        raise RuntimeError(f"flowNode/get 失败: {json.dumps(resp, ensure_ascii=False)}")
    data = resp.get("data") or {}
    # data 可能是 dict（含 flowNodeList）或直接是 list
    if isinstance(data, list):
        return data
    return data.get("flowNodeList") or data.get("flowNodes") or []


def add_workflow_node(
    session,
    process_id: str,
    prev_node_id: str,
    node_type: str,
    name: str,
) -> dict:
    """
    添加工作流节点骨架。

    POST /workflow/flowNode/add
    返回：{"status": 1, "data": {"addFlowNodes": [{"id": "...", ...}]}}
    """
    # 从 node registry 获取 typeId、actionId、appType
    node_spec = NODE_REGISTRY.get(node_type) or NODE_CONFIGS.get(node_type) or {}
    type_id = node_spec.get("typeId", 6)
    action_id = node_spec.get("actionId", "")
    app_type = node_spec.get("appType", 0)

    payload: dict = {
        "processId": process_id,
        "typeId": type_id,
        "name": name,
        "prveId": prev_node_id,
    }
    if action_id:
        payload["actionId"] = str(action_id)
    if app_type:
        payload["appType"] = app_type

    resp = session.post(f"{API_BASE}/workflow/flowNode/add", payload)
    if resp.get("status") != 1:
        raise RuntimeError(f"flowNode/add 失败 ({node_type}): {resp.get('msg')} status={resp.get('status')}")

    added = (resp.get("data") or {}).get("addFlowNodes") or []
    if not added:
        raise RuntimeError(f"flowNode/add 返回空 addFlowNodes ({node_type})")
    return added[0]  # {"id": "...", "typeId": ..., "name": "..."}


def save_workflow_node(
    session,
    process_id: str,
    node_id: str,
    node_type: str,
    worksheet_id: str,
    name: str,
    extra: dict,
) -> dict:
    """
    保存工作流节点配置。

    POST /workflow/flowNode/saveNode
    返回：{"status": 1, "data": {...}}
    """
    try:
        # 优先用 node registry 的 build_save_body
        from nodes import build_save_body
        body = build_save_body(node_type, process_id, node_id, worksheet_id, name, extra)
        if body is None:
            return {"status": 1, "skipped": True, "reason": "节点类型不需要 saveNode"}
    except Exception:
        # 降级：手动构建 notify/update_record 等常用节点的 saveNode body
        body = _build_save_body_fallback(
            node_type, process_id, node_id, worksheet_id, name, extra
        )

    resp = session.post(f"{API_BASE}/workflow/flowNode/saveNode", body)
    if resp.get("status") != 1:
        raise RuntimeError(
            f"flowNode/saveNode 失败 ({node_type} nodeId={node_id}): "
            f"{resp.get('msg')} status={resp.get('status')}"
        )
    return resp


def _build_save_body_fallback(
    node_type: str,
    process_id: str,
    node_id: str,
    worksheet_id: str,
    name: str,
    extra: dict,
) -> dict:
    """降级 saveNode body 构建（当 node registry 不可用时）。"""
    base = {
        "processId": process_id,
        "nodeId": node_id,
        "name": name,
    }
    if node_type in ("notify",):
        base.update({
            "flowNodeType": 27,
            "sendContent": extra.get("sendContent", ""),
            "accounts": extra.get("accounts", []),
        })
    elif node_type in ("update_record", "add_record"):
        action_id = "1" if node_type == "add_record" else "2"
        base.update({
            "flowNodeType": 6,
            "actionId": action_id,
            "appId": extra.get("target_worksheet_id", worksheet_id),
            "appType": 1,
            "fields": extra.get("fields", []),
            "filters": extra.get("filters", []),
            "selectNodeId": extra.get("selectNodeId", ""),
        })
    elif node_type == "delay_duration":
        base.update({
            "flowNodeType": 12,
            "actionId": "301",
            "number": extra.get("number", 1),
            "unit": extra.get("unit", 3),
        })
    elif node_type == "copy":
        base.update({
            "flowNodeType": 5,
            "sendContent": extra.get("sendContent", ""),
            "accounts": extra.get("accounts", []),
        })
    else:
        # 通用兜底
        base["flowNodeType"] = extra.get("flowNodeType", 0)
        base.update({k: v for k, v in extra.items() if k not in base})
    return base


def delete_workflow_node(session, process_id: str, node_id: str) -> bool:
    """
    删除工作流节点。

    # TODO: 确认正确的删除节点 API
    #   候选端点：
    #     POST /workflow/flowNode/delete  {"processId": ..., "nodeId": ...}
    #     POST /workflow/flowNode/abandon {"processId": ..., "nodeId": ...}
    #   当前暂用 delete，如 API 返回错误请改为 abandon
    """
    resp = session.post(
        f"{API_BASE}/workflow/flowNode/delete",
        {"processId": process_id, "nodeId": node_id},
    )
    return resp.get("status") == 1


def publish_workflow(process_id: str, session) -> bool:
    """发布工作流（启用）。"""
    url = f"{API_BASE}/workflow/process/publish?isPublish=true&processId={process_id}"
    for attempt in range(1, 4):
        try:
            resp = session.get(url)
            data = resp.get("data") or {}
            if data.get("isPublish"):
                print(f"    process/publish → ✓ 已开启")
                return True
            error_nodes = data.get("errorNodeIds") or []
            warnings = data.get("processWarnings") or []
            print(f"    process/publish → ✗ 未开启  errorNodes={error_nodes}  warnings={warnings}")
            if attempt < 3:
                time.sleep(2)
                continue
            return False
        except Exception as exc:
            if attempt < 3:
                print(f"    process/publish → 异常: {exc}，{2}s 后重试...")
                time.sleep(2)
                continue
            print(f"    process/publish → 异常: {exc}")
            return False
    return False


# ── AI 规划修改方案 ────────────────────────────────────────────────────────────

def _build_modify_workflow_prompt(
    workflow_detail: dict,
    current_nodes: list[dict],
    worksheets_info: list[dict],
    description: str,
) -> str:
    """构建工作流修改规划的 AI Prompt。"""
    node_type_section = build_node_type_prompt_section() if _NODE_REGISTRY_AVAILABLE else (
        "可用节点类型：update_record, add_record, delete_record, notify, copy, "
        "delay_duration, calc, aggregate, approval, ai_text"
    )

    # 当前节点摘要
    node_lines = []
    for i, node in enumerate(current_nodes):
        nid = node.get("id", node.get("nodeId", ""))
        ntype = node.get("typeId", "?")
        nname = node.get("name", "(未命名)")
        prev_id = node.get("prveId", node.get("prevId", ""))
        node_lines.append(
            f"  [{i}] id={nid}  typeId={ntype}  name={nname}  prveId={prev_id}"
        )

    # 工作表字段摘要
    ws_lines = []
    for ws in worksheets_info:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        classified = classify_fields(fields)
        ws_lines.append(f"\n工作表「{ws_name}」(ID: {ws_id})")
        for cat_name, cat_label in [
            ("text", "文本"), ("number", "数值"), ("date", "日期"),
            ("select", "单选/下拉"), ("user", "成员"), ("relation", "关联"),
        ]:
            cat_fields = classified.get(cat_name, [])
            if cat_fields:
                for f in cat_fields[:6]:
                    opts = ""
                    if f.get("options"):
                        opts = "  选项: " + ", ".join(
                            f'key="{o["key"]}" value="{o["value"]}"'
                            for o in f["options"][:5]
                        )
                    ws_lines.append(
                        f"  field_id={f['id']}  type={f['type']}  {f['name']}{opts}"
                    )

    process_name = (workflow_detail.get("process") or {}).get("name", "（未知工作流）")
    start_node_id = workflow_detail.get("startNodeId") or (
        (workflow_detail.get("process") or {}).get("startNodeId", "")
    )

    return f"""你是一名工作流配置专家，正在修改工作流「{process_name}」的节点配置。

{node_type_section}

## 当前工作流节点列表
startNodeId={start_node_id}
{chr(10).join(node_lines) or "（暂无节点）"}

## 工作表字段参考
{"".join(ws_lines) or "（无字段信息）"}

## 用户修改需求
{description}

## 任务
根据用户需求，规划对工作流节点的增/改/删操作。

## 输出 JSON（严格 JSON，无注释）
{{
  "operations": [
    {{
      "op": "add",
      "after_node_id": "在此节点之后插入（填该节点的 id，末尾插入则填最后一个节点 id）",
      "node_type": "notify",
      "name": "节点名称",
      "extra": {{
        "sendContent": "通知内容（notify/copy 必填）",
        "fields": [],
        "target_worksheet_id": "目标工作表 ID（update_record/add_record 必填）"
      }}
    }},
    {{
      "op": "update",
      "node_id": "要修改的节点 id",
      "node_type": "update_record",
      "name": "新名称（可不变）",
      "extra": {{
        "fields": [
          {{"fieldId": "字段ID", "type": 数字, "fieldValue": "值"}}
        ],
        "target_worksheet_id": "目标工作表 ID"
      }}
    }},
    {{
      "op": "delete",
      "node_id": "要删除的节点 id"
    }}
  ],
  "publish": true,
  "reason": "操作理由说明"
}}

## 规则
1. op 只能是 add / update / delete
2. node_type 必须来自上方可用节点类型列表
3. add 操作：after_node_id 必须是上方节点列表中存在的 id
4. update/delete 操作：node_id 必须是上方节点列表中存在的 id（不能修改/删除触发节点 startNodeId）
5. notify/copy 必须有 sendContent
6. update_record/add_record 必须有 fields（至少 1 个）且 target_worksheet_id 必须来自工作表列表
7. 所有字段 ID 必须来自上方字段参考
8. publish: true 表示修改完成后自动发布工作流"""


def _validate_operations(
    operations: list[dict],
    current_nodes: list[dict],
    start_node_id: str,
    worksheets_info: list[dict],
) -> list[dict]:
    """校验并清洗 AI 生成的操作列表。"""
    valid_node_ids = {
        node.get("id", node.get("nodeId", ""))
        for node in current_nodes
    }
    valid_ws_ids = {ws["worksheetId"] for ws in worksheets_info}
    ws_field_ids: dict[str, set] = {}
    for ws in worksheets_info:
        fids = set()
        for f in ws.get("fields", []):
            fid = str(f.get("id", "") or f.get("controlId", "")).strip()
            if fid:
                fids.add(fid)
        ws_field_ids[ws["worksheetId"]] = fids

    cleaned = []
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            print(f"  [校验] 操作[{i}] 不是对象，跳过")
            continue

        op_type = str(op.get("op", "")).strip()
        if op_type not in ("add", "update", "delete"):
            print(f"  [校验] 操作[{i}] op={op_type!r} 无效，跳过")
            continue

        if op_type == "add":
            after_id = str(op.get("after_node_id", "")).strip()
            if after_id and after_id not in valid_node_ids:
                print(f"  [校验] add 操作 after_node_id={after_id!r} 不在节点列表，跳过")
                continue
            node_type = str(op.get("node_type", "")).strip()
            if not node_type:
                print(f"  [校验] add 操作缺少 node_type，跳过")
                continue
            cleaned.append(op)

        elif op_type == "update":
            node_id = str(op.get("node_id", "")).strip()
            if not node_id or node_id not in valid_node_ids:
                print(f"  [校验] update 操作 node_id={node_id!r} 不在节点列表，跳过")
                continue
            if node_id == start_node_id:
                print(f"  [校验] 不允许修改触发节点 (startNodeId={start_node_id})，跳过")
                continue
            cleaned.append(op)

        elif op_type == "delete":
            node_id = str(op.get("node_id", "")).strip()
            if not node_id or node_id not in valid_node_ids:
                print(f"  [校验] delete 操作 node_id={node_id!r} 不在节点列表，跳过")
                continue
            if node_id == start_node_id:
                print(f"  [校验] 不允许删除触发节点 (startNodeId={start_node_id})，跳过")
                continue
            cleaned.append(op)

    return cleaned


# ── 执行修改方案 ───────────────────────────────────────────────────────────────

def execute_modify_operations(
    session,
    process_id: str,
    operations: list[dict],
    current_nodes: list[dict],
    worksheet_id: str,
    start_node_id: str,
    should_publish: bool = True,
) -> dict:
    """
    执行工作流节点增/改/删操作。

    Returns:
        {"added": [...], "updated": [...], "deleted": [...], "failed": [...], "published": bool}
    """
    result = {"added": [], "updated": [], "deleted": [], "failed": [], "published": False}

    # 构建节点 ID -> 节点信息的映射（用于 add 操作确定 prveId）
    node_id_map = {
        node.get("id", node.get("nodeId", "")): node
        for node in current_nodes
    }

    for i, op in enumerate(operations):
        op_type = op.get("op")
        try:
            if op_type == "add":
                after_node_id = str(op.get("after_node_id", "")).strip() or start_node_id
                node_type = str(op.get("node_type", "")).strip()
                name = str(op.get("name", f"新节点{i+1}")).strip()
                extra = op.get("extra") or {}

                print(f"\n  [add] {name} ({node_type}) after={after_node_id[:16]}...")
                added_node = add_workflow_node(
                    session, process_id, after_node_id, node_type, name
                )
                node_id = added_node.get("id", "")
                print(f"    flowNode/add → nodeId={node_id}")

                # saveNode（如有配置）
                if extra or node_type in ("notify", "copy", "update_record", "add_record",
                                          "delay_duration", "calc", "aggregate"):
                    save_resp = save_workflow_node(
                        session, process_id, node_id, node_type,
                        extra.get("target_worksheet_id", worksheet_id),
                        name, extra,
                    )
                    ok = save_resp.get("status") == 1 or save_resp.get("skipped")
                    print(f"    flowNode/saveNode → {'✓' if ok else '✗'}")
                    result["added"].append({
                        "node_id": node_id, "name": name, "node_type": node_type,
                        "save_ok": ok,
                    })
                else:
                    result["added"].append({
                        "node_id": node_id, "name": name, "node_type": node_type,
                        "save_ok": True,
                    })

            elif op_type == "update":
                node_id = str(op.get("node_id", "")).strip()
                node_type = str(op.get("node_type", "")).strip()
                name = str(op.get("name", node_id_map.get(node_id, {}).get("name", ""))).strip()
                extra = op.get("extra") or {}

                print(f"\n  [update] nodeId={node_id[:16]}... name={name}")
                save_resp = save_workflow_node(
                    session, process_id, node_id, node_type,
                    extra.get("target_worksheet_id", worksheet_id),
                    name, extra,
                )
                ok = save_resp.get("status") == 1 or save_resp.get("skipped")
                print(f"    flowNode/saveNode → {'✓' if ok else '✗'}")
                result["updated"].append({
                    "node_id": node_id, "name": name, "node_type": node_type,
                    "save_ok": ok,
                })

            elif op_type == "delete":
                node_id = str(op.get("node_id", "")).strip()
                node_name = node_id_map.get(node_id, {}).get("name", node_id[:16])

                print(f"\n  [delete] nodeId={node_id[:16]}... name={node_name}")
                ok = delete_workflow_node(session, process_id, node_id)
                print(f"    flowNode/delete → {'✓' if ok else '✗'}")
                result["deleted"].append({
                    "node_id": node_id, "name": node_name, "ok": ok,
                })

        except Exception as exc:
            print(f"  ✗ 操作[{i}] {op_type} 失败: {exc}")
            result["failed"].append({"op": op, "error": str(exc)})

    # 发布工作流
    if should_publish and (result["added"] or result["updated"] or result["deleted"]):
        print(f"\n  发布工作流 {process_id[:16]}...")
        published = publish_workflow(process_id, session)
        result["published"] = published

    return result


# ── 公共接口 ───────────────────────────────────────────────────────────────────

def modify_workflow(
    workflow_id: str,
    app_id: str = "",
    description: str = "",
    worksheet_id: str = "",
    app_auth_json: str = "",
    ai_config: Optional[dict] = None,
    auth_config_path: Optional[Path] = None,
    execute: bool = True,
    auto_publish: bool = True,
) -> dict:
    """
    修改已有工作流的节点（增/改/删）。

    Args:
        workflow_id:   工作流 processId
        app_id:        应用 ID（加载工作表字段上下文）
        description:   用户描述（要改什么）
        worksheet_id:  工作流关联的工作表 ID（可选，辅助字段引用验证）
        app_auth_json: 授权文件路径
        ai_config:     AI 配置（默认 fast tier）
        auth_config_path: auth_config.py 路径
        execute:       是否真实执行（False 时只生成方案）
        auto_publish:  修改后是否自动发布
    Returns:
        {"plan": {...}, "result": {...}, "workflow_detail": {...}}
    """
    if ai_config is None:
        ai_config = load_ai_config(tier="fast")
    if auth_config_path is None:
        auth_config_path = AUTH_CONFIG_PATH

    # 构建 session
    session = _build_session(auth_config_path)

    # 获取工作流详情
    print(f"\n[modify_workflow] 获取工作流详情 processId={workflow_id[:16]}...")
    workflow_detail = fetch_workflow_detail(workflow_id, session)
    process_name = (workflow_detail.get("process") or {}).get("name", workflow_id)
    start_node_id = (
        workflow_detail.get("startNodeId")
        or (workflow_detail.get("process") or {}).get("startNodeId", "")
    )
    print(f"  工作流: 「{process_name}」 startNodeId={start_node_id[:16] if start_node_id else '（未知）'}...")

    # 获取当前节点列表
    print(f"[modify_workflow] 获取工作流节点列表...")
    current_nodes = fetch_workflow_nodes(workflow_id, session)
    print(f"  当前节点数: {len(current_nodes)}")
    for node in current_nodes:
        nid = node.get("id", node.get("nodeId", ""))
        nname = node.get("name", "(未命名)")
        ntype = node.get("typeId", "?")
        print(f"    - [{ntype}] {nname}  id={nid[:16] if nid else '?'}...")

    # 加载工作表字段上下文
    worksheets_info: list[dict] = []
    if app_id or app_auth_json:
        print(f"[modify_workflow] 加载应用上下文...")
        try:
            ctx = load_app_context(
                app_id=app_id, app_auth_json=app_auth_json, with_field_details=True
            )
            worksheets_info = ctx.get("worksheets", [])
            # 字段归一化
            for ws in worksheets_info:
                fields = ws.get("fields", [])
                normalized = []
                for f in fields:
                    nf = dict(f)
                    if not nf.get("id"):
                        nf["id"] = nf.get("controlId", "")
                    if not nf.get("name"):
                        nf["name"] = nf.get("controlName", "")
                    normalized.append(nf)
                ws["fields"] = normalized
            print(f"  已加载 {len(worksheets_info)} 个工作表")
        except Exception as exc:
            print(f"  ⚠ 加载应用上下文失败: {exc}（继续，字段引用验证将跳过）")

    # 如果指定了 worksheet_id，优先用它确定操作目标
    target_ws_id = worksheet_id
    if not target_ws_id and worksheets_info:
        target_ws_id = worksheets_info[0]["worksheetId"]

    # AI 规划修改方案
    print(f"[modify_workflow] AI 规划修改方案...")
    prompt = _build_modify_workflow_prompt(
        workflow_detail, current_nodes, worksheets_info, description
    )
    client = get_ai_client(ai_config)
    gen_cfg = create_generation_config(ai_config, response_mime_type="application/json")
    resp = client.models.generate_content(
        model=ai_config["model"], contents=prompt, config=gen_cfg
    )
    raw = resp.text if hasattr(resp, "text") else str(resp)
    plan = parse_ai_json(raw)

    print(f"  AI 修改理由: {plan.get('reason', '（无）')}")

    operations = plan.get("operations") or []
    print(f"  规划操作数: {len(operations)}")
    for op in operations:
        print(f"    - {op.get('op')} {op.get('node_type', '')} {op.get('name', '') or op.get('node_id', '')[:16]}")

    # 校验操作
    validated_ops = _validate_operations(
        operations, current_nodes, start_node_id, worksheets_info
    )
    print(f"  校验通过: {len(validated_ops)} 个操作（过滤了 {len(operations) - len(validated_ops)} 个非法操作）")

    # 保存方案到文件
    INCREMENTAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    plan_file = INCREMENTAL_OUTPUT_DIR / f"modify_workflow_{workflow_id[:16]}_{ts}.json"
    plan_file.write_text(
        json.dumps({
            "workflow_id": workflow_id,
            "process_name": process_name,
            "current_nodes_count": len(current_nodes),
            "plan": plan,
            "validated_ops": validated_ops,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  修改方案已保存: {plan_file}")

    # 执行
    exec_result = {}
    if execute and validated_ops:
        should_publish = auto_publish and bool(plan.get("publish", True))
        print(f"\n[modify_workflow] 执行 {len(validated_ops)} 个操作...")
        exec_result = execute_modify_operations(
            session=session,
            process_id=workflow_id,
            operations=validated_ops,
            current_nodes=current_nodes,
            worksheet_id=target_ws_id,
            start_node_id=start_node_id,
            should_publish=should_publish,
        )
        print(
            f"\n[modify_workflow] 完成: "
            f"新增{len(exec_result['added'])} 修改{len(exec_result['updated'])} "
            f"删除{len(exec_result['deleted'])} 失败{len(exec_result['failed'])}"
        )
    elif not validated_ops:
        exec_result = {"status": "no_valid_ops", "plan_file": str(plan_file)}
        print("[modify_workflow] 无有效操作可执行")
    else:
        exec_result = {"status": "plan_only", "plan_file": str(plan_file)}
        print(f"[modify_workflow] 已生成规划（未执行）: {plan_file}")

    return {
        "plan": plan,
        "validated_ops": validated_ops,
        "result": exec_result,
        "workflow_detail": {
            "process_name": process_name,
            "start_node_id": start_node_id,
            "nodes_count": len(current_nodes),
        },
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="修改已有工作流的节点（增/改/删）")
    parser.add_argument("--workflow-id", required=True, help="工作流 processId")
    parser.add_argument("--app-id", default="", help="应用 ID（加载字段上下文）")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON 文件路径")
    parser.add_argument("--worksheet-id", default="", help="工作流关联的工作表 ID（辅助字段验证）")
    parser.add_argument("--description", required=True,
                        help="修改描述，例如：在审批通过后增加邮件通知节点")
    parser.add_argument("--no-execute", action="store_true", help="只生成方案，不实际执行")
    parser.add_argument("--no-publish", action="store_true", help="执行后不自动发布工作流")
    parser.add_argument(
        "--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径"
    )
    args = parser.parse_args()

    result = modify_workflow(
        workflow_id=args.workflow_id,
        app_id=args.app_id,
        description=args.description,
        worksheet_id=args.worksheet_id,
        app_auth_json=args.app_auth_json,
        auth_config_path=Path(args.auth_config),
        execute=not args.no_execute,
        auto_publish=not args.no_publish,
    )

    print("\n[modify_workflow] 执行结果:")
    print(json.dumps(result["result"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
