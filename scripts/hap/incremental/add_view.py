#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_view.py — 为已有工作表增量添加视图。

流程：
  1. 加载工作表字段结构
  2. AI 规划视图类型和配置（或直接使用指定类型）
  3. 调用 SaveWorksheetView API 创建视图

用法（CLI）：
    python3 add_view.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --name "按状态看板" \\
        --view-type 1 \\
        --view-control <单选字段ID>

    # AI 自动规划
    python3 add_view.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --description "按审批状态分组的看板视图"

用法（Python）：
    from incremental.add_view import add_view
    result = add_view(
        app_id="xxx",
        worksheet_id="yyy",
        view_name="按状态看板",
        view_type=1,
        description="按审批状态分组",
    )
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import requests

BASE_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_HAP = BASE_DIR / "scripts" / "hap"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"

for p in [str(SCRIPTS_HAP)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import auth_retry
from incremental.app_context import load_app_context, fetch_worksheet_detail
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json
from planning.view_planner import (
    build_structure_prompt,
    validate_structure_plan,
    suggest_views,
)
from planning.constraints import classify_fields
from views.view_types import VIEW_REGISTRY
from create_views_from_plan import (
    build_create_payload,
    build_update_payload,
    normalize_advanced_setting,
)

V3_BASE = "https://api.mingdao.com"
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"


# ── AI 规划 ────────────────────────────────────────────────────────────────────

def _build_single_view_prompt(
    ws_name: str,
    ws_id: str,
    fields: list[dict],
    description: str,
) -> str:
    """为单个工作表规划单个视图。"""
    classified = classify_fields(fields)
    suggestions = suggest_views(classified, ws_id)

    field_lines = []
    for cat, label in [("select", "单选/下拉"), ("date", "日期"),
                       ("text", "文本"), ("number", "数值"), ("user", "成员")]:
        cat_fields = classified.get(cat, [])
        if cat_fields:
            fids = ", ".join(f"{f['id']}({f['name']})" for f in cat_fields[:5])
            field_lines.append(f"  [{label}] {fids}")

    suggestion_lines = []
    for sg in suggestions:
        suggestion_lines.append(f"  - viewType={sg['viewType']} {sg['name']}")

    view_types_str = "\n".join(
        f"  {vt}: {spec['name']} — {spec['doc'][:60]}"
        for vt, spec in sorted(VIEW_REGISTRY.items())
    )

    return f"""为工作表「{ws_name}」规划一个视图。

## 工作表字段
{chr(10).join(field_lines) or "（暂无字段）"}

## 可用视图类型
{view_types_str}

## 推荐视图
{chr(10).join(suggestion_lines) or "（无推荐）"}

## 用户需求
{description or "根据字段特点推荐最合适的视图"}

## 输出 JSON
{{
  "name": "视图名称",
  "viewType": "1",
  "viewControl": "看板时填单选字段ID，其他填空字符串",
  "displayControls": ["字段ID1", "字段ID2"],
  "advancedSetting": {{}},
  "reason": "推荐理由"
}}

规则：
1. viewType 0=表格, 1=看板, 2=层级, 3=画廊, 4=日历, 5=甘特图
2. 看板(1) 必须设 viewControl 为单选字段 ID
3. displayControls 选最重要的 5-8 个字段
4. 所有字段 ID 必须来自上方字段列表"""


def recommend_view(
    ws_name: str,
    ws_id: str,
    fields: list[dict],
    description: str,
    ai_config: dict,
) -> dict:
    """AI 推荐视图配置。"""
    prompt = _build_single_view_prompt(ws_name, ws_id, fields, description)
    client = get_ai_client(ai_config)
    gen_cfg = create_generation_config(ai_config, response_mime_type="application/json")
    resp = client.models.generate_content(model=ai_config["model"], contents=prompt, config=gen_cfg)
    raw = resp.text if hasattr(resp, "text") else str(resp)
    rec = parse_ai_json(raw)

    # 验证 viewType
    vt = str(rec.get("viewType", "0")).strip()
    if vt not in {str(k) for k in VIEW_REGISTRY}:
        vt = "0"
    rec["viewType"] = vt

    # 过滤 displayControls（只保留存在的字段 ID）
    field_ids = {f["id"] for f in fields if f.get("id")}
    dc = rec.get("displayControls", [])
    if isinstance(dc, list):
        rec["displayControls"] = [x for x in dc if str(x).strip() in field_ids]

    return rec


# ── 视图创建 ──────────────────────────────────────────────────────────────────

def _normalize_fields(fields: list[dict]) -> list[dict]:
    """归一化字段 id/name/type。"""
    result = []
    for f in fields:
        nf = dict(f)
        if not nf.get("id"):
            nf["id"] = nf.get("controlId", "")
        if not nf.get("name"):
            nf["name"] = nf.get("controlName", "")
        if not nf.get("type") and nf.get("type") != 0:
            nf["type"] = nf.get("controlType", nf.get("type", 2))
        # options
        if "options" not in nf:
            opts = f.get("options", [])
            if opts:
                nf["options"] = opts
        result.append(nf)
    return result


def create_single_view(
    app_id: str,
    worksheet_id: str,
    view_config: dict,
    auth_config_path: Path,
) -> dict:
    """
    调用 SaveWorksheetView 创建视图，并执行 postCreateUpdates（如设置看板字段等）。

    Returns:
        {"viewId": "...", "viewName": "...", "viewType": N}
    """
    payload = build_create_payload(app_id, worksheet_id, view_config)

    referer = f"https://www.mingdao.com/app/{app_id}/{worksheet_id}"
    resp = auth_retry.hap_web_post(
        SAVE_VIEW_URL, auth_config_path, referer=referer, json=payload, timeout=30
    )
    body = resp.json()
    if body.get("state") != 1:
        raise RuntimeError(f"SaveWorksheetView 失败: {body.get('msg')} (state={body.get('state')})")

    view_id = str(body.get("data", {}).get("viewId", "") or body.get("viewId", "")).strip()
    view_name = str(view_config.get("name", "")).strip()
    view_type_int = int(str(view_config.get("viewType", "0")).strip() or "0")

    print(f"  ✓ 创建视图「{view_name}」(viewType={view_type_int}) → {view_id}")

    # postCreateUpdates（如设置日历字段、甘特图起止日期等）
    for update in view_config.get("postCreateUpdates", []) or []:
        if not isinstance(update, dict) or not view_id:
            continue
        upd_payload = build_update_payload(app_id, worksheet_id, view_id, update)
        if upd_payload.get("_skip_reason"):
            continue
        upd_resp = auth_retry.hap_web_post(
            SAVE_VIEW_URL, auth_config_path,
            referer=f"{referer}/{view_id}", json=upd_payload, timeout=30
        )
        upd_body = upd_resp.json()
        if upd_body.get("state") != 1:
            print(f"  ⚠ postCreateUpdate 失败: {upd_body.get('msg')}")

    return {"viewId": view_id, "viewName": view_name, "viewType": view_type_int}


# ── 公共接口 ───────────────────────────────────────────────────────────────────

def add_view(
    app_id: str,
    worksheet_id: str,
    view_name: str = "",
    view_type: Optional[int] = None,
    view_control: str = "",
    description: str = "",
    display_controls: Optional[list] = None,
    app_auth_json: str = "",
    ai_config: Optional[dict] = None,
    auth_config_path: Optional[Path] = None,
    execute: bool = True,
) -> dict:
    """
    为工作表增量添加视图。

    Args:
        view_type: 0=表格 1=看板 2=层级 3=画廊 4=日历 5=甘特图（None 时 AI 推荐）
        view_control: 看板时必填（单选字段 ID）
        description: 业务描述，指导 AI 推荐
    Returns:
        {"view": {...}, "recommended": {...}}
    """
    if ai_config is None:
        ai_config = load_ai_config(tier="fast")
    if auth_config_path is None:
        auth_config_path = AUTH_CONFIG_PATH

    print(f"\n[add_view] 加载上下文 app_id={app_id}...")
    ctx = load_app_context(app_id=app_id, app_auth_json=app_auth_json, with_field_details=True)

    ws = next((w for w in ctx["worksheets"] if w["worksheetId"] == worksheet_id), None)
    if not ws:
        available = [f"{w['worksheetName']}({w['worksheetId']})" for w in ctx["worksheets"]]
        raise ValueError(f"找不到工作表 {worksheet_id}，可用: {', '.join(available)}")

    ws_name = ws["worksheetName"]
    fields = _normalize_fields(ws.get("fields", []))

    # AI 推荐或使用指定配置
    recommended = {}
    if view_type is None or not view_name:
        print(f"  [AI 推荐] 为工作表「{ws_name}」推荐视图...")
        recommended = recommend_view(ws_name, worksheet_id, fields, description, ai_config)
        if view_type is None:
            view_type = int(recommended.get("viewType", "0"))
        if not view_name:
            view_name = recommended.get("name", f"视图_{view_type}")
        if not view_control:
            view_control = recommended.get("viewControl", "")
        if display_controls is None:
            display_controls = recommended.get("displayControls", [])
        print(f"  推荐: viewType={view_type} 名称={view_name}")

    view_config = {
        "name": view_name or f"视图_{view_type}",
        "viewType": str(view_type),
        "viewControl": view_control or "",
        "displayControls": display_controls or [],
        "advancedSetting": recommended.get("advancedSetting", {}),
        "postCreateUpdates": recommended.get("postCreateUpdates", []),
    }

    result = {}
    if execute:
        result = create_single_view(app_id, worksheet_id, view_config, auth_config_path)
    else:
        result = {"status": "plan_only", "view_config": view_config}

    return {"view": result, "recommended": recommended}


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="增量添加视图到工作表")
    parser.add_argument("--app-id", default="", help="应用 ID")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON 文件路径")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--name", default="", help="视图名称（不传则 AI 推荐）")
    parser.add_argument("--view-type", type=int, default=None,
                        help="视图类型: 0=表格 1=看板 2=层级 3=画廊 4=日历 5=甘特图")
    parser.add_argument("--view-control", default="", help="看板视图的单选字段 ID")
    parser.add_argument("--description", default="", help="视图描述，指导 AI 推荐")
    parser.add_argument("--no-execute", action="store_true", help="只生成配置，不实际创建")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    args = parser.parse_args()

    if not args.app_id and not args.app_auth_json:
        parser.error("请传 --app-id 或 --app-auth-json")

    result = add_view(
        app_id=args.app_id,
        worksheet_id=args.worksheet_id,
        view_name=args.name,
        view_type=args.view_type,
        view_control=args.view_control,
        description=args.description,
        app_auth_json=args.app_auth_json,
        auth_config_path=Path(args.auth_config),
        execute=not args.no_execute,
    )

    print("\n[add_view] 完成")
    print(json.dumps(result["view"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
