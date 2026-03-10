#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选择应用并调用 Gemini 生成该应用的推荐角色清单。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from google import genai
from google.genai import types

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import (
    DEFAULT_BASE_URL,
    OUTPUT_ROOT,
    append_log,
    choose_app,
    discover_authorized_apps,
    ensure_dir,
    extract_json_object,
    fetch_app_worksheets,
    load_gemini_api_key,
    make_log_path,
    make_output_path,
    now_iso,
    write_json,
)

ROLE_PLAN_DIR = OUTPUT_ROOT / "role_plans"
ROLE_PLAN_LATEST = ROLE_PLAN_DIR / "role_plan_latest.json"
DEFAULT_MODEL = "gemini-2.5-flash"


def bool_or_default(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
    return default


def normalize_permission_way(value: Any) -> int:
    try:
        n = int(value)
    except Exception:
        return 20
    if n in {0, 20, 30, 60, 80}:
        return n
    return 20


def normalize_roles(raw: Dict[str, Any]) -> List[dict]:
    source = raw.get("recommendedRoles", raw.get("roles", []))
    if not isinstance(source, list):
        raise ValueError("Gemini 返回缺少 recommendedRoles 数组")

    normalized: List[dict] = []
    for idx, item in enumerate(source, start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        permissions = item.get("permissions", {})
        if not isinstance(permissions, dict):
            permissions = {}
        normalized.append(
            {
                "name": name,
                "description": str(item.get("description", "")).strip(),
                "reason": str(item.get("reason", "")).strip(),
                "permissionWay": normalize_permission_way(item.get("permissionWay", 20)),
                "roleType": 0,
                "hideAppForMembers": bool_or_default(item.get("hideAppForMembers"), False),
                "permissions": {
                    "generalAdd": bool_or_default(permissions.get("generalAdd"), True),
                    "generalShare": bool_or_default(permissions.get("generalShare"), False),
                    "generalImport": bool_or_default(permissions.get("generalImport"), False),
                    "generalExport": bool_or_default(permissions.get("generalExport"), False),
                    "generalDiscussion": bool_or_default(permissions.get("generalDiscussion"), True),
                    "generalLogging": bool_or_default(permissions.get("generalLogging"), True),
                    "generalSystemPrinting": bool_or_default(permissions.get("generalSystemPrinting"), False),
                    "recordShare": bool_or_default(permissions.get("recordShare"), False),
                    "payment": bool_or_default(permissions.get("payment"), False),
                },
            }
        )
    if not normalized:
        raise ValueError("Gemini 返回的角色列表为空")
    return normalized


def build_prompt(app_name: str, worksheet_names: List[str]) -> str:
    ws_lines = "\n".join(f"- {x}" for x in worksheet_names) if worksheet_names else "- （该应用下暂无工作表）"
    return f"""
你是企业应用权限架构师。请基于下面应用信息，为应用推荐角色列表。

应用名称：{app_name}
工作表列表：
{ws_lines}

请输出严格 JSON，不要 markdown，不要注释，结构如下：
{{
  "summary": "一句话概述",
  "recommendedRoles": [
    {{
      "name": "角色名称",
      "description": "角色职责说明",
      "reason": "推荐原因",
      "permissionWay": 20,
      "hideAppForMembers": false,
      "permissions": {{
        "generalAdd": true,
        "generalShare": false,
        "generalImport": false,
        "generalExport": false,
        "generalDiscussion": true,
        "generalLogging": true,
        "generalSystemPrinting": false,
        "recordShare": false,
        "payment": false
      }}
    }}
  ],
  "notes": ["注意事项1", "注意事项2"]
}}

约束：
1) recommendedRoles 必须是 3-8 个角色。
2) role name 必须唯一，不要出现“角色1/角色2”这类占位名。
3) permissionWay 仅允许 0/20/30/60/80。
4) 输出必须是合法 JSON 对象。
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="选择应用并生成推荐角色 JSON")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default="", help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    parser.add_argument("--max-retries", type=int, default=3, help="Gemini 重试次数")
    args = parser.parse_args()

    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id, app_index=args.app_index)
    log_path = make_log_path("role_plan", app["appId"])
    append_log(
        log_path,
        "start",
        appId=app["appId"],
        appName=app["appName"],
        model=args.model,
    )

    app_meta, worksheets = fetch_app_worksheets(
        base_url=args.base_url,
        app_key=app["appKey"],
        sign=app["sign"],
    )
    worksheet_names = [str(x.get("worksheetName", "")).strip() for x in worksheets if str(x.get("worksheetName", "")).strip()]
    worksheet_names = sorted(set(worksheet_names))
    append_log(log_path, "app_loaded", worksheetCount=len(worksheet_names))

    config_path = Path(args.config).expanduser().resolve() if args.config else None
    api_key = load_gemini_api_key(config_path) if config_path else load_gemini_api_key()
    client = genai.Client(api_key=api_key)
    prompt = build_prompt(str(app_meta.get("name", "")).strip() or app["appName"], worksheet_names)

    raw: Dict[str, Any] = {}
    last_error = ""
    for i in range(1, max(1, args.max_retries) + 1):
        append_log(log_path, "gemini_request", attempt=i)
        try:
            resp = client.models.generate_content(
                model=args.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            raw = extract_json_object(resp.text or "")
            roles = normalize_roles(raw)
            break
        except Exception as exc:
            last_error = str(exc)
            append_log(log_path, "gemini_retry_failed", attempt=i, error=last_error)
            if i >= max(1, args.max_retries):
                raise RuntimeError(f"Gemini 生成失败: {last_error}") from exc
    else:
        raise RuntimeError(f"Gemini 生成失败: {last_error}")

    roles = normalize_roles(raw)
    notes = raw.get("notes", [])
    if not isinstance(notes, list):
        notes = []

    result = {
        "schemaVersion": "role_plan_v1",
        "generatedAt": now_iso(),
        "model": args.model,
        "app": {
            "appId": app["appId"],
            "appName": str(app_meta.get("name", "")).strip() or app["appName"],
        },
        "worksheetNames": worksheet_names,
        "summary": str(raw.get("summary", "")).strip(),
        "recommendedRoles": roles,
        "notes": [str(x).strip() for x in notes if str(x).strip()],
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        ensure_dir(ROLE_PLAN_DIR)
        output_path = make_output_path(ROLE_PLAN_DIR, "role_plan", app["appId"])

    write_json(output_path, result)
    write_json(ROLE_PLAN_LATEST.resolve(), result)
    append_log(log_path, "finished", output=str(output_path), roleCount=len(roles))

    print("推荐角色生成完成")
    print(f"- 应用: {result['app']['appName']} ({result['app']['appId']})")
    print(f"- 工作表数量: {len(worksheet_names)}")
    print(f"- 推荐角色数量: {len(roles)}")
    print(f"- 结果文件: {output_path}")
    print(f"- 日志文件: {log_path}")
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {log_path}")


if __name__ == "__main__":
    main()
