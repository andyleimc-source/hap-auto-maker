#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_worksheet.py — 为已有应用增量添加新工作表（含字段规划）。

流程：
  1. 加载应用上下文
  2. AI 规划新工作表的字段结构（基于现有表结构 + 业务描述）
  3. 调用 create_worksheets_from_plan 创建工作表和字段

用法（CLI）：
    python3 add_worksheet.py \\
        --app-id <appId> \\
        --name "请假申请表" \\
        --description "员工提交请假申请，记录假期类型、时长和审批状态"

用法（Python）：
    from incremental.add_worksheet import add_worksheet
    result = add_worksheet(
        app_id="xxx",
        name="请假申请表",
        description="员工请假审批流程",
    )
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_HAP = BASE_DIR / "scripts" / "hap"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
INCREMENTAL_OUTPUT_DIR = OUTPUT_ROOT / "incremental"

for p in [str(SCRIPTS_HAP)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from incremental.app_context import load_app_context
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json
from planning.worksheet_planner import build_enhanced_prompt, validate_worksheet_plan
from create_worksheets_from_plan import (
    build_field_payload,
    parse_select_options_from_field,
    to_required,
    build_relationship_rules,
    normalize_relation_plan,
    create_worksheet as _create_worksheet_api,
    CREATE_WS_ENDPOINT,
)

import requests


# ── AI 调用 ────────────────────────────────────────────────────────────────────

def _call_ai(prompt: str, ai_config: dict) -> str:
    client = get_ai_client(ai_config)
    gen_cfg = create_generation_config(ai_config, response_mime_type="application/json")
    resp = client.models.generate_content(
        model=ai_config["model"],
        contents=prompt,
        config=gen_cfg,
    )
    return resp.text if hasattr(resp, "text") else str(resp)


# ── 字段规划 ───────────────────────────────────────────────────────────────────

def plan_new_worksheet_fields(
    new_ws_name: str,
    description: str,
    existing_worksheets: list[dict],
    ai_config: dict,
) -> dict:
    """
    AI 规划新工作表的字段结构。

    Args:
        new_ws_name: 新工作表名称
        description: 业务描述
        existing_worksheets: 已有工作表信息（提供上下文以推荐关联字段）
    Returns:
        worksheet plan dict（含 worksheets + relationships + creation_order）
    """
    # 构建现有工作表上下文摘要
    existing_summary_lines = []
    ws_names = []
    for ws in existing_worksheets:
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        ws_names.append(ws_name)
        field_names = [
            f.get("controlName") or f.get("name", "")
            for f in fields[:8]
        ]
        existing_summary_lines.append(f"  - {ws_name}: {', '.join(field_names)}")

    existing_summary = "\n".join(existing_summary_lines) if existing_summary_lines else "（无已有工作表）"

    business_context = f"""需要新增一个「{new_ws_name}」工作表。

业务描述：{description}

应用中已有的工作表（供参考关联关系）：
{existing_summary}

请为新工作表「{new_ws_name}」设计字段结构。
注意：
1. 如果新工作表与某个已有表有业务关联，可以添加关联字段
2. 关联字段使用 type="Relation"，并设置 relation_target 为目标工作表名称
3. 必须包含标题字段（type="Text"）
4. 根据业务描述选择合适的字段类型
"""

    prompt = build_enhanced_prompt(
        app_name=new_ws_name,
        business_context=business_context,
        extra_requirements=f"只规划一个工作表「{new_ws_name}」，不要生成多余的工作表。",
        min_worksheets=1,
    )

    print(f"  [AI 规划] 规划「{new_ws_name}」字段...")
    raw = _call_ai(prompt, ai_config)
    plan = parse_ai_json(raw)

    # 校验并过滤到只保留新工作表
    errors = validate_worksheet_plan(plan, min_worksheets=1)
    if errors:
        raise ValueError(f"工作表规划校验失败: {'; '.join(errors)}")

    # 只保留目标工作表（以防 AI 多输出了几个）
    worksheets = plan.get("worksheets", [])
    target_ws = next(
        (ws for ws in worksheets if ws.get("name", "").strip() == new_ws_name.strip()),
        worksheets[0] if worksheets else None
    )
    if not target_ws:
        raise ValueError(f"AI 未规划工作表「{new_ws_name}」")

    # 过滤 relationships — 只保留与目标表相关的
    rels = [
        r for r in plan.get("relationships", [])
        if r.get("from") == new_ws_name or r.get("to") == new_ws_name
    ]

    return {
        "worksheets": [target_ws],
        "relationships": rels,
        "creation_order": [new_ws_name],
    }


# ── 创建工作表 ────────────────────────────────────────────────────────────────

def _build_headers(app_key: str, sign: str) -> dict:
    return {
        "Content-Type": "application/json",
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
    }


def create_worksheet_from_plan(
    plan: dict,
    app_key: str,
    sign: str,
    existing_worksheet_ids: dict[str, str],
) -> dict:
    """
    调用 V3 API 创建工作表。

    Args:
        plan: 包含单个工作表的 plan dict
        app_key: 应用 Key
        sign: 应用签名
        existing_worksheet_ids: {worksheetName -> worksheetId} 用于填写 Relation 字段的目标 ID
    Returns:
        {"worksheetId": "...", "worksheetName": "...", "fields_created": N}
    """
    V3_BASE = "https://api.mingdao.com"
    base_url = V3_BASE
    headers = _build_headers(app_key, sign)

    ws_data = plan["worksheets"][0]
    ws_name = ws_data["name"]
    fields_raw = ws_data.get("fields", [])

    # 分离普通字段和关联字段
    normal_fields = []
    relation_fields = []
    title_set = False

    for fld in fields_raw:
        ftype = str(fld.get("type", "Text")).strip()
        if ftype == "Relation":
            relation_fields.append(fld)
            continue
        payload = build_field_payload(fld, is_first_text_title=not title_set)
        if payload.get("isTitle") == 1:
            title_set = True
        normal_fields.append(payload)

    if not normal_fields:
        normal_fields = [{"name": "名称", "type": "Text", "required": True, "isTitle": 1}]

    # Phase 1: 创建工作表（无关联字段）
    create_url = f"{V3_BASE}{CREATE_WS_ENDPOINT}"
    payload = {"name": ws_name, "fields": normal_fields}
    resp = requests.post(create_url, headers=headers, json=payload, timeout=30)
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"创建工作表「{ws_name}」失败: {body}")

    new_ws_id = body["data"]["worksheetId"]
    print(f"  ✓ 创建工作表「{ws_name}」 → {new_ws_id}")

    # Phase 2: 回填关联字段
    added_relations = 0
    if relation_fields:
        # 更新 existing_worksheet_ids 加入新表自身
        all_ws_ids = {**existing_worksheet_ids, ws_name: new_ws_id}
        edit_url = f"{V3_BASE}/v3/app/worksheets/{new_ws_id}"

        for fld in relation_fields:
            target_name = str(fld.get("relation_target", "")).strip()
            target_id = all_ws_ids.get(target_name)
            if not target_id:
                print(f"  ⚠ 跳过关联字段「{fld.get('name')}」: 目标表「{target_name}」ID 未知")
                continue

            relation_payload = {
                "name": str(fld.get("name", "关联")).strip(),
                "type": "Relation",
                "required": to_required(fld.get("required", False)),
                "relation_target_id": target_id,
            }
            try:
                edit_resp = requests.patch(edit_url, headers=headers, json={
                    "fields": [relation_payload]
                }, timeout=30)
                edit_body = edit_resp.json()
                if edit_body.get("success"):
                    added_relations += 1
                    print(f"  ✓ 添加关联字段「{relation_payload['name']}」→「{target_name}」")
                else:
                    print(f"  ⚠ 关联字段「{relation_payload['name']}」失败: {edit_body.get('error_msg')}")
            except Exception as e:
                print(f"  ⚠ 关联字段「{relation_payload['name']}」异常: {e}")

    return {
        "worksheetId": new_ws_id,
        "worksheetName": ws_name,
        "fields_created": len(normal_fields) + added_relations,
    }


# ── 公共接口 ───────────────────────────────────────────────────────────────────

def add_worksheet(
    app_id: str,
    name: str,
    description: str = "",
    app_auth_json: str = "",
    ai_config: Optional[dict] = None,
    execute: bool = True,
) -> dict:
    """
    为已有应用增量添加新工作表。

    Args:
        app_id: 应用 ID
        name: 新工作表名称
        description: 业务描述
        app_auth_json: 授权文件路径
        ai_config: AI 配置
        execute: 是否真实创建
    Returns:
        {"plan": {...}, "result": {...}}
    """
    if ai_config is None:
        ai_config = load_ai_config()

    print(f"\n[add_worksheet] 加载应用上下文 app_id={app_id}...")
    ctx = load_app_context(app_id=app_id, app_auth_json=app_auth_json)

    # 规划字段
    plan = plan_new_worksheet_fields(
        new_ws_name=name,
        description=description,
        existing_worksheets=ctx["worksheets"],
        ai_config=ai_config,
    )

    # 保存规划
    INCREMENTAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    plan_file = INCREMENTAL_OUTPUT_DIR / f"worksheet_plan_{app_id}_{ts}.json"
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  规划已保存: {plan_file}")

    ws_plan = plan["worksheets"][0]
    fields = ws_plan.get("fields", [])
    print(f"  规划字段数: {len(fields)}")
    for f in fields:
        print(f"    - {f.get('name')} ({f.get('type')})")

    result = {}
    if execute:
        existing_ws_ids = {
            ws["worksheetName"]: ws["worksheetId"]
            for ws in ctx["worksheets"]
        }
        result = create_worksheet_from_plan(
            plan=plan,
            app_key=ctx["app_key"],
            sign=ctx["sign"],
            existing_worksheet_ids=existing_ws_ids,
        )
    else:
        result = {"status": "plan_only", "plan_file": str(plan_file)}

    return {"plan": plan, "result": result}


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="增量添加工作表到已有应用")
    parser.add_argument("--app-id", default="", help="应用 ID")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON 文件路径")
    parser.add_argument("--name", required=True, help="新工作表名称")
    parser.add_argument("--description", default="", help="业务描述")
    parser.add_argument("--no-execute", action="store_true", help="只生成规划，不实际创建")
    args = parser.parse_args()

    if not args.app_id and not args.app_auth_json:
        parser.error("请传 --app-id 或 --app-auth-json")

    result = add_worksheet(
        app_id=args.app_id,
        name=args.name,
        description=args.description,
        app_auth_json=args.app_auth_json,
        execute=not args.no_execute,
    )

    print("\n[add_worksheet] 完成")
    print(json.dumps(result["result"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
