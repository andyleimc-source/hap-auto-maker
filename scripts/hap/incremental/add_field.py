#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_field.py — 为已有工作表增量添加字段。

流程：
  1. 加载工作表现有字段结构
  2. AI 推荐新字段的类型和配置
  3. 调用 SaveWorksheetControls API 添加字段

用法（CLI）：
    python3 add_field.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --name "审批人" \\
        --type Member \\
        --description "负责审批该申请的成员"

    # 让 AI 推荐字段类型
    python3 add_field.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --name "审批状态" \\
        --description "记录审批进度：待审批/审批中/已通过/已拒绝"

用法（Python）：
    from incremental.add_field import add_field
    result = add_field(
        app_id="xxx",
        worksheet_id="yyy",
        field_name="审批人",
        field_description="负责审批的成员",
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

from incremental.app_context import load_app_context, fetch_worksheet_detail
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json
from worksheets.field_types import FIELD_REGISTRY, ALLOWED_FIELD_TYPES, PLANNABLE_TYPES

V3_BASE = "https://api.mingdao.com"
WEB_API_BASE = "https://www.mingdao.com/api/Worksheet"


# ── 字段类型推荐 ───────────────────────────────────────────────────────────────

FIELD_TYPE_DESCRIPTIONS = {
    name: f"{spec['name']} (type={spec['controlType']}) — {spec['doc'][:80]}"
    for name, spec in FIELD_REGISTRY.items()
    if name in PLANNABLE_TYPES
}


def _build_ai_recommend_prompt(
    ws_name: str,
    existing_fields: list[dict],
    field_name: str,
    field_description: str,
) -> str:
    # 现有字段摘要
    existing_summary = []
    for f in existing_fields[:15]:
        fname = f.get("controlName") or f.get("name", "")
        ftype = f.get("type") or f.get("controlType", 0)
        existing_summary.append(f"  - {fname} (type={ftype})")

    types_str = "\n".join(f"  - {k}: {v}" for k, v in list(FIELD_TYPE_DESCRIPTIONS.items())[:20])

    return f"""你是字段配置专家，为工作表「{ws_name}」推荐新字段的类型和配置。

## 工作表现有字段
{"".join(existing_summary) or "（暂无字段）"}

## 需要添加的字段
- 字段名：{field_name}
- 业务描述：{field_description or "无"}

## 可用字段类型（部分）
{types_str}

## 任务
根据字段名和业务描述，推荐最合适的字段类型，并给出完整配置。

## 输出 JSON（严格格式）
{{
  "type": "字段类型名（如 Text/SingleSelect/Member/Number 等）",
  "controlType": 字段类型数字,
  "required": false,
  "option_values": ["选项1", "选项2"],  // 单选/多选/下拉时必填
  "reason": "推荐理由"
}}

规则：
1. type 必须是可用字段类型之一
2. 单选(SingleSelect)/多选(MultiSelect)/下拉(Dropdown) 必须给出 3-6 个 option_values
3. 其他类型 option_values 为空数组
4. required 根据业务语义判断（如"审批状态"通常 required=false，"姓名"通常 required=true）"""


def recommend_field_type(
    ws_name: str,
    existing_fields: list[dict],
    field_name: str,
    field_description: str,
    ai_config: dict,
) -> dict:
    """用 AI 推荐字段类型。Returns: {"type": "...", "controlType": N, "required": bool, "option_values": [...]}"""
    prompt = _build_ai_recommend_prompt(ws_name, existing_fields, field_name, field_description)
    client = get_ai_client(ai_config)
    gen_cfg = create_generation_config(ai_config, response_mime_type="application/json")
    resp = client.models.generate_content(model=ai_config["model"], contents=prompt, config=gen_cfg)
    raw = resp.text if hasattr(resp, "text") else str(resp)
    rec = parse_ai_json(raw)

    # 验证类型
    ftype = str(rec.get("type", "Text")).strip()
    if ftype not in ALLOWED_FIELD_TYPES:
        ftype = "Text"

    return {
        "type": ftype,
        "controlType": FIELD_REGISTRY.get(ftype, {}).get("controlType", 2),
        "required": bool(rec.get("required", False)),
        "option_values": rec.get("option_values", []),
        "reason": rec.get("reason", ""),
    }


# ── 字段创建 ──────────────────────────────────────────────────────────────────

def _get_worksheet_controls(app_key: str, sign: str, worksheet_id: str) -> tuple[list, int]:
    """通过 GetWorksheetControls 获取字段列表 + version（乐观锁）。"""
    url = f"{WEB_API_BASE}/GetWorksheetControls"
    payload = {
        "worksheetId": worksheet_id,
        "appKey": app_key,
        "sign": sign,
    }
    resp = requests.post(url, json=payload, timeout=30)
    body = resp.json()
    if body.get("error_code") != 1:
        raise RuntimeError(f"GetWorksheetControls 失败: {body.get('error_msg')}")
    data = body.get("data", {}).get("data", {})
    controls = data.get("controls", [])
    version = data.get("version", 0)
    return controls, version


def _build_option_list(option_values: list[str]) -> list[dict]:
    """将选项值列表转换为 API 格式。"""
    import uuid
    return [
        {"key": str(uuid.uuid4()).replace("-", "")[:24], "value": v, "index": i + 1}
        for i, v in enumerate(option_values)
        if v.strip()
    ]


def _build_new_field_control(
    field_name: str,
    field_type: str,
    required: bool,
    option_values: list[str],
    hint: str = "",
) -> dict:
    """构造新字段的 control 对象（controlId 为空 = 新增）。"""
    spec = FIELD_REGISTRY.get(field_type, {})
    control_type = spec.get("controlType", 2)

    control = {
        "controlId": "",          # 新增时为空
        "controlName": field_name,
        "type": control_type,
        "required": 1 if required else 0,
        "attribute": 0,
        "advancedSetting": {"sorttype": "zh"},
    }

    if hint:
        control["hint"] = hint

    # 选项类字段
    if field_type in ("SingleSelect", "MultiSelect", "Dropdown") and option_values:
        control["options"] = _build_option_list(option_values)

    # 成员类字段
    if field_type in ("Member", "Collaborator"):
        control["enumDefault"] = 0  # 0=单选成员

    # 多选成员
    if field_type == "MemberMultiple":
        control["enumDefault"] = 1

    # 数值/金额
    if field_type in ("Number", "Money"):
        control["dot"] = 2

    return control


def save_field(
    app_key: str,
    sign: str,
    worksheet_id: str,
    field_name: str,
    field_type: str,
    required: bool = False,
    option_values: list[str] = None,
    hint: str = "",
) -> dict:
    """
    向工作表添加新字段（SaveWorksheetControls）。

    Returns:
        {"controlId": "...", "controlName": "...", "type": N}
    """
    # 获取当前字段列表 + version
    controls, version = _get_worksheet_controls(app_key, sign, worksheet_id)

    # 构造新字段
    new_control = _build_new_field_control(
        field_name=field_name,
        field_type=field_type,
        required=required,
        option_values=option_values or [],
        hint=hint,
    )

    # 追加到末尾
    controls.append(new_control)

    # 调用 SaveWorksheetControls
    url = f"{WEB_API_BASE}/SaveWorksheetControls"
    payload = {
        "version": version,
        "sourceId": worksheet_id,
        "controls": controls,
        "appKey": app_key,
        "sign": sign,
    }
    resp = requests.post(url, json=payload, timeout=30)
    body = resp.json()
    if body.get("error_code") != 1:
        raise RuntimeError(f"SaveWorksheetControls 失败: {body.get('error_msg')} (code={body.get('error_code')})")

    # 从响应中找新增字段的 controlId
    new_controls = body.get("data", {}).get("data", {}).get("controls", [])
    spec = FIELD_REGISTRY.get(field_type, {})
    control_type_int = spec.get("controlType", 2)

    created = next(
        (c for c in reversed(new_controls)
         if c.get("controlName") == field_name and c.get("type") == control_type_int),
        None
    )
    if created:
        return {
            "controlId": created.get("controlId", ""),
            "controlName": field_name,
            "type": control_type_int,
            "typeName": spec.get("name", field_type),
        }
    return {"controlName": field_name, "type": control_type_int, "status": "created_unconfirmed"}


# ── 公共接口 ───────────────────────────────────────────────────────────────────

def add_field(
    app_id: str,
    worksheet_id: str,
    field_name: str,
    field_type: str = "",
    field_description: str = "",
    required: bool = False,
    option_values: Optional[list] = None,
    app_auth_json: str = "",
    ai_config: Optional[dict] = None,
    auto_recommend: bool = True,
) -> dict:
    """
    为工作表增量添加字段。

    Args:
        field_type: 字段类型名（如 Text/SingleSelect/Member），为空时 AI 自动推荐
        auto_recommend: True 时即使指定了 field_type，也可以用 AI 推荐选项值
    Returns:
        {"field": {...}, "recommended": {...}}
    """
    if ai_config is None:
        ai_config = load_ai_config(tier="fast")

    print(f"\n[add_field] 加载上下文 app_id={app_id}...")
    ctx = load_app_context(app_id=app_id, app_auth_json=app_auth_json, with_field_details=False)

    # 获取目标工作表字段
    ws = next((w for w in ctx["worksheets"] if w["worksheetId"] == worksheet_id), None)
    if not ws:
        available = [f"{w['worksheetName']}({w['worksheetId']})" for w in ctx["worksheets"]]
        raise ValueError(f"找不到工作表 {worksheet_id}，可用: {', '.join(available)}")

    ws_name = ws["worksheetName"]
    existing_fields, _ = _get_worksheet_controls(ctx["app_key"], ctx["sign"], worksheet_id)

    # AI 推荐或使用指定类型
    recommended = {}
    if not field_type or (auto_recommend and not option_values and field_description):
        print(f"  [AI 推荐] 为字段「{field_name}」推荐类型...")
        recommended = recommend_field_type(
            ws_name=ws_name,
            existing_fields=existing_fields,
            field_name=field_name,
            field_description=field_description,
            ai_config=ai_config,
        )
        if not field_type:
            field_type = recommended["type"]
            required = recommended.get("required", required)
        if not option_values:
            option_values = recommended.get("option_values", [])
        print(f"  推荐类型: {field_type}，理由: {recommended.get('reason', '')}")

    if not field_type:
        field_type = "Text"

    # 创建字段
    print(f"  创建字段「{field_name}」(type={field_type}, required={required})...")
    result = save_field(
        app_key=ctx["app_key"],
        sign=ctx["sign"],
        worksheet_id=worksheet_id,
        field_name=field_name,
        field_type=field_type,
        required=required,
        option_values=option_values or [],
        hint=field_description,
    )
    print(f"  ✓ 字段创建成功: {result}")

    return {"field": result, "recommended": recommended}


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="增量添加字段到工作表")
    parser.add_argument("--app-id", default="", help="应用 ID")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON 文件路径")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--name", required=True, help="字段名称")
    parser.add_argument("--type", default="", help="字段类型（如 Text/SingleSelect/Member，不传则 AI 推荐）")
    parser.add_argument("--description", default="", help="字段业务描述")
    parser.add_argument("--required", action="store_true", help="是否必填")
    parser.add_argument("--options", default="", help="选项值（逗号分隔，如 '待审批,审批中,已通过'）")
    args = parser.parse_args()

    if not args.app_id and not args.app_auth_json:
        parser.error("请传 --app-id 或 --app-auth-json")

    option_values = [o.strip() for o in args.options.split(",") if o.strip()] if args.options else None

    result = add_field(
        app_id=args.app_id,
        worksheet_id=args.worksheet_id,
        field_name=args.name,
        field_type=args.type,
        field_description=args.description,
        required=args.required,
        option_values=option_values,
        app_auth_json=args.app_auth_json,
    )

    print("\n[add_field] 完成")
    print(json.dumps(result["field"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
