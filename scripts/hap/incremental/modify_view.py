#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modify_view.py — 修改已有视图的配置（筛选/排序/分组/显示字段等）。

流程：
  1. 获取工作表的所有视图列表，找到目标视图
  2. 获取工作表字段结构（供 AI 参考）
  3. 用 AI 根据用户描述 + 当前视图配置 生成新的 advancedSetting / displayControls 等
  4. 调用 SaveWorksheetView API 保存修改

用法（CLI）：
    python3 modify_view.py \\
        --worksheet-id <worksheetId> \\
        --view-id <viewId> \\
        --description "增加按状态筛选，只显示进行中的记录"

    python3 modify_view.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --view-id <viewId> \\
        --description "按负责人分组，显示姓名/状态/截止日期字段"

用法（Python）：
    from incremental.modify_view import modify_view
    result = modify_view(
        worksheet_id="yyy",
        view_id="zzz",
        description="只显示本月到期记录，按优先级排序",
    )
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_HAP = BASE_DIR / "scripts" / "hap"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
INCREMENTAL_OUTPUT_DIR = OUTPUT_ROOT / "incremental"

for p in [str(SCRIPTS_HAP)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import auth_retry
from incremental.app_context import load_app_context, fetch_worksheet_detail
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json
from planning.constraints import classify_fields
from create_views_from_plan import normalize_advanced_setting

V3_BASE = "https://api.mingdao.com"
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"


# ── 工具函数 ───────────────────────────────────────────────────────────────────

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
        if "options" not in nf:
            opts = f.get("options", [])
            if opts:
                nf["options"] = opts
        result.append(nf)
    return result


def _find_view_in_worksheet(ws_detail: dict, view_id: str) -> Optional[dict]:
    """从工作表详情中找到指定 viewId 的视图配置。"""
    views = ws_detail.get("views", []) or []
    for v in views:
        if str(v.get("viewId", "")).strip() == view_id:
            return v
    return None


# ── AI 生成新配置 ──────────────────────────────────────────────────────────────

def _build_modify_view_prompt(
    ws_name: str,
    fields: list[dict],
    current_view: dict,
    description: str,
) -> str:
    """构建修改视图配置的 AI Prompt。"""
    classified = classify_fields(fields)

    # 字段摘要
    field_lines = []
    for cat, label in [("select", "单选/下拉"), ("date", "日期"),
                       ("text", "文本"), ("number", "数值"), ("user", "成员"),
                       ("relation", "关联")]:
        cat_fields = classified.get(cat, [])
        if cat_fields:
            for f in cat_fields:
                opts_str = ""
                if f.get("options"):
                    opts_str = "  选项: " + ", ".join(
                        f'key="{o["key"]}" value="{o["value"]}"'
                        for o in f["options"][:6]
                    )
                field_lines.append(
                    f"  [{label}] id={f['id']} type={f['type']} 名称={f['name']}{opts_str}"
                )

    # 当前视图配置摘要
    view_type = str(current_view.get("viewType", "0"))
    view_type_name = {
        "0": "表格", "1": "看板", "2": "层级", "3": "画廊", "4": "日历", "5": "甘特图"
    }.get(view_type, "未知")

    current_adv = current_view.get("advancedSetting") or {}
    current_display = current_view.get("displayControls") or []
    current_filters = current_view.get("filters") or []

    current_view_str = json.dumps({
        "viewType": view_type,
        "viewTypeName": view_type_name,
        "name": current_view.get("name", ""),
        "viewControl": current_view.get("viewControl", ""),
        "displayControls": current_display,
        "filters": current_filters,
        "advancedSetting": current_adv,
    }, ensure_ascii=False, indent=2)

    return f"""你是一名应用配置专家，正在修改工作表「{ws_name}」的已有视图配置。

## 工作表字段
{chr(10).join(field_lines) or "（暂无字段）"}

## 当前视图配置
```json
{current_view_str}
```

## 用户修改需求
{description}

## 任务
根据用户需求，生成更新后的视图配置。只输出需要修改的字段，其他字段保持不变。

## 输出 JSON（严格 JSON，无注释）
{{
  "displayControls": ["字段ID1", "字段ID2"],
  "advancedSetting": {{
    "enablerules": "1",
    "groupView": "",
    "coverstyle": ""
  }},
  "filters": [],
  "sortCid": "",
  "sortType": 0,
  "reason": "修改理由说明"
}}

## 规则
1. displayControls 只保留来自上方字段列表的 ID，选最重要的 5-8 个字段
2. advancedSetting 中的 groupView 若设置分组，格式为 JSON 字符串：
   '{{"viewId":"","groupFilters":[{{"controlId":"<单选字段ID>","values":[],"dataType":<type>,"spliceType":1,"filterType":2,"dateRange":0,"minValue":"","maxValue":"","isGroup":true}}],"navShow":true}}'
3. filters 用于筛选条件，每项格式：
   {{"controlId": "字段ID", "dataType": type, "spliceType": 1, "filterType": 2, "values": ["值"]}}
4. 若某字段无需修改，可省略（不要输出原值，直接省略该 key）
5. sortCid 为排序字段 ID，sortType: 0=升序 1=降序
6. 所有字段 ID 必须来自上方字段列表"""


def plan_view_modification(
    ws_name: str,
    fields: list[dict],
    current_view: dict,
    description: str,
    ai_config: dict,
) -> dict:
    """AI 生成视图修改方案。"""
    prompt = _build_modify_view_prompt(ws_name, fields, current_view, description)
    client = get_ai_client(ai_config)
    gen_cfg = create_generation_config(ai_config, response_mime_type="application/json")
    resp = client.models.generate_content(
        model=ai_config["model"], contents=prompt, config=gen_cfg
    )
    raw = resp.text if hasattr(resp, "text") else str(resp)
    plan = parse_ai_json(raw)

    # 过滤 displayControls（只保留存在的字段 ID）
    field_ids = {f["id"] for f in fields if f.get("id")}
    dc = plan.get("displayControls")
    if isinstance(dc, list):
        plan["displayControls"] = [x for x in dc if str(x).strip() in field_ids]

    # 过滤 filters 中非法字段引用
    filters = plan.get("filters")
    if isinstance(filters, list):
        plan["filters"] = [
            f for f in filters
            if isinstance(f, dict) and str(f.get("controlId", "")).strip() in field_ids
        ]

    # 过滤 sortCid
    sort_cid = str(plan.get("sortCid", "")).strip()
    if sort_cid and sort_cid not in field_ids:
        plan["sortCid"] = ""

    return plan


# ── 视图修改执行 ───────────────────────────────────────────────────────────────

def _build_modify_payload(
    app_id: str,
    worksheet_id: str,
    view_id: str,
    current_view: dict,
    plan: dict,
) -> dict:
    """
    合并当前视图配置与 AI 生成的修改方案，构建 SaveWorksheetView payload。
    只更新 plan 中明确提供的字段，其余字段保持原值。
    """
    view_type = str(current_view.get("viewType", "0"))

    # displayControls：优先用 plan，否则保持原值
    display_controls = plan.get("displayControls")
    if not isinstance(display_controls, list):
        display_controls = current_view.get("displayControls") or []
    display_controls = [str(x).strip() for x in display_controls if str(x).strip()]

    # advancedSetting：合并（plan 中的 key 覆盖当前值）
    current_adv = dict(current_view.get("advancedSetting") or {})
    plan_adv = plan.get("advancedSetting") or {}
    if isinstance(plan_adv, dict):
        current_adv.update(plan_adv)
    merged_adv = normalize_advanced_setting(view_type, current_adv)

    # filters
    filters = plan.get("filters")
    if not isinstance(filters, list):
        filters = current_view.get("filters") or []

    # sortCid / sortType
    sort_cid = str(plan.get("sortCid", current_view.get("sortCid", ""))).strip()
    sort_type = plan.get("sortType", current_view.get("sortType", 0))

    payload = {
        "viewId": view_id,
        "appId": app_id,
        "worksheetId": worksheet_id,
        "viewType": view_type,
        "name": current_view.get("name", ""),
        "displayControls": display_controls,
        "sortType": sort_type,
        "sortCid": sort_cid,
        "coverType": current_view.get("coverType", 0),
        "controls": current_view.get("controls") or [],
        "filters": filters,
        "showControlName": current_view.get("showControlName", True),
        "advancedSetting": merged_adv,
    }

    # 保留 viewControl（看板字段）
    view_control = str(current_view.get("viewControl", "")).strip()
    if view_control:
        payload["viewControl"] = view_control

    # 保留 coverCid（画廊封面字段）
    cover_cid = str(current_view.get("coverCid", "")).strip()
    if cover_cid:
        payload["coverCid"] = cover_cid

    return payload


def execute_modify_view(
    app_id: str,
    worksheet_id: str,
    view_id: str,
    current_view: dict,
    plan: dict,
    auth_config_path: Path,
) -> dict:
    """调用 SaveWorksheetView 保存修改后的视图配置。"""
    payload = _build_modify_payload(app_id, worksheet_id, view_id, current_view, plan)

    referer = f"https://www.mingdao.com/app/{app_id}/{worksheet_id}/{view_id}"
    resp = auth_retry.hap_web_post(
        SAVE_VIEW_URL, auth_config_path, referer=referer, json=payload, timeout=30
    )
    body = resp.json()
    if body.get("state") != 1:
        raise RuntimeError(
            f"SaveWorksheetView 失败: {body.get('msg')} (state={body.get('state')})"
        )

    view_name = current_view.get("name", "")
    print(f"  ✓ 已修改视图「{view_name}」(viewId={view_id})")
    return {"viewId": view_id, "viewName": view_name, "state": 1}


# ── 公共接口 ───────────────────────────────────────────────────────────────────

def modify_view(
    worksheet_id: str,
    view_id: str,
    description: str,
    app_id: str = "",
    app_auth_json: str = "",
    ai_config: Optional[dict] = None,
    auth_config_path: Optional[Path] = None,
    execute: bool = True,
) -> dict:
    """
    修改已有视图的 advancedSetting（筛选/排序/分组/显示字段等）。

    Args:
        worksheet_id:  目标工作表 ID
        view_id:       目标视图 ID
        description:   用户描述（要改什么）
        app_id:        应用 ID（用于加载字段上下文，可选）
        app_auth_json: 授权文件路径
        ai_config:     AI 配置（默认 fast tier）
        auth_config_path: auth_config.py 路径
        execute:       是否真实保存（False 时只生成方案）
    Returns:
        {"result": {...}, "plan": {...}, "current_view": {...}}
    """
    if ai_config is None:
        ai_config = load_ai_config(tier="fast")
    if auth_config_path is None:
        auth_config_path = AUTH_CONFIG_PATH

    print(f"\n[modify_view] 加载上下文 worksheet_id={worksheet_id}...")
    ctx = load_app_context(
        app_id=app_id, app_auth_json=app_auth_json, with_field_details=True
    )

    # 找到目标工作表
    ws = next(
        (w for w in ctx["worksheets"] if w["worksheetId"] == worksheet_id), None
    )
    if not ws:
        available = [f"{w['worksheetName']}({w['worksheetId']})" for w in ctx["worksheets"]]
        raise ValueError(f"找不到工作表 {worksheet_id}，可用: {', '.join(available)}")

    ws_name = ws["worksheetName"]
    fields = _normalize_fields(ws.get("fields", []))

    # 找到目标视图
    current_view = _find_view_in_worksheet(ws, view_id)
    if not current_view:
        views_info = [
            f"{v.get('name', '')}({v.get('viewId', '')})"
            for v in (ws.get("views") or [])
        ]
        raise ValueError(
            f"找不到视图 {view_id}，工作表「{ws_name}」的视图: {', '.join(views_info) or '（无）'}"
        )

    print(f"  当前视图: 「{current_view.get('name', '')}」 viewType={current_view.get('viewType', 0)}")

    # AI 规划修改方案
    print(f"  [AI] 根据描述规划视图修改方案...")
    plan = plan_view_modification(ws_name, fields, current_view, description, ai_config)
    print(f"  [AI] 修改理由: {plan.get('reason', '（无）')}")

    # 保存修改方案到文件
    INCREMENTAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    import time as _time
    ts = int(_time.time())
    resolved_app_id = str(ctx.get("app_id", app_id)).strip()
    plan_file = INCREMENTAL_OUTPUT_DIR / f"modify_view_{worksheet_id}_{view_id}_{ts}.json"
    plan_file.write_text(
        json.dumps({"current_view": current_view, "plan": plan}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  修改方案已保存: {plan_file}")

    result = {}
    if execute:
        print("[modify_view] 执行视图修改...")
        result = execute_modify_view(
            resolved_app_id, worksheet_id, view_id, current_view, plan, auth_config_path
        )
    else:
        result = {"status": "plan_only", "plan_file": str(plan_file)}

    return {"result": result, "plan": plan, "current_view": current_view}


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="修改已有视图的配置（筛选/排序/分组/显示字段等）")
    parser.add_argument("--app-id", default="", help="应用 ID")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON 文件路径")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--view-id", required=True, help="视图 ID")
    parser.add_argument("--description", required=True, help="修改描述，例如：只显示进行中的记录，按状态分组")
    parser.add_argument("--no-execute", action="store_true", help="只生成方案，不实际保存")
    parser.add_argument(
        "--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径"
    )
    args = parser.parse_args()

    if not args.app_id and not args.app_auth_json:
        parser.error("请传 --app-id 或 --app-auth-json")

    result = modify_view(
        worksheet_id=args.worksheet_id,
        view_id=args.view_id,
        description=args.description,
        app_id=args.app_id,
        app_auth_json=args.app_auth_json,
        auth_config_path=Path(args.auth_config),
        execute=not args.no_execute,
    )

    print("\n[modify_view] 完成")
    print(json.dumps(result["result"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
