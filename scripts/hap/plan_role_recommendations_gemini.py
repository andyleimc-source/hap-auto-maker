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

from ai_utils import create_generation_config, get_ai_client, load_ai_config
from script_locator import resolve_script

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


def choose_app_by_name(apps: List[dict], app_name: str) -> dict:
    target = app_name.strip()
    if not target:
        raise ValueError("应用名称不能为空")
    matched = [app for app in apps if str(app.get("appName", "")).strip() == target]
    if not matched:
        raise ValueError(f"未找到应用名称={target}")
    if len(matched) > 1:
        app_ids = ", ".join(str(app.get("appId", "")).strip() for app in matched)
        raise ValueError(f"应用名称重复，请改用 --app-id 指定。appName={target}, appIds={app_ids}")
    return matched[0]


def resolve_app(apps: List[dict], app_id: str = "", app_name: str = "", app_index: int = 0) -> dict:
    if app_id.strip():
        return choose_app(apps, app_id=app_id.strip(), app_index=0)
    if app_name.strip():
        return choose_app_by_name(apps, app_name.strip())
    return choose_app(apps, app_id="", app_index=app_index)


def normalize_worksheet_name_inputs(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in values:
        for piece in str(raw or "").split(","):
            name = piece.strip()
            if not name or name in seen:
                continue
            out.append(name)
            seen.add(name)
    return out


def select_worksheet_names(worksheet_names: List[str], requested_names: List[str]) -> List[str]:
    if not requested_names:
        return worksheet_names
    available = {name: name for name in worksheet_names}
    missing = [name for name in requested_names if name not in available]
    if missing:
        raise ValueError(f"以下工作表不存在于应用中: {missing}")
    return [available[name] for name in requested_names]


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
    parser.add_argument("--app-name", default="", help="可选，按应用名称精确匹配")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument(
        "--worksheet-name",
        action="append",
        default=[],
        help="可选，指定参与角色规划的工作表名称。可重复传入，也可单次传逗号分隔值。",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--config", default="", help="AI 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    parser.add_argument("--inventory-output", default="", help="可选，写出工作表清单 JSON")
    parser.add_argument("--prompt-output", default="", help="可选，写出发送给 AI 的 prompt 文本")
    parser.add_argument("--raw-output", default="", help="可选，写出 AI 原始响应文本")
    parser.add_argument("--max-retries", type=int, default=3, help="AI 重试次数")
    args = parser.parse_args()

    # 结构化 JSON 输出，使用极速档
    config_path = Path(args.config).expanduser().resolve() if args.config else None
    ai_config = load_ai_config(config_path, tier="fast")
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]

    apps = discover_authorized_apps(base_url=args.base_url)
    app = resolve_app(apps, app_id=args.app_id, app_name=args.app_name, app_index=args.app_index)
    log_path = make_log_path("role_plan", app["appId"])
    requested_worksheet_names = normalize_worksheet_name_inputs(args.worksheet_name)
    append_log(
        log_path,
        "start",
        appId=app["appId"],
        appName=app["appName"],
        model=model_name,
        worksheetNames=requested_worksheet_names,
    )

    app_meta, worksheets = fetch_app_worksheets(
        base_url=args.base_url,
        app_key=app["appKey"],
        sign=app["sign"],
    )
    worksheet_names = [str(x.get("worksheetName", "")).strip() for x in worksheets if str(x.get("worksheetName", "")).strip()]
    worksheet_names = sorted(set(worksheet_names))
    selected_worksheet_names = select_worksheet_names(worksheet_names, requested_worksheet_names)
    append_log(
        log_path,
        "app_loaded",
        worksheetCount=len(worksheet_names),
        selectedWorksheetCount=len(selected_worksheet_names),
    )

    if args.inventory_output:
        inventory_output = Path(args.inventory_output).expanduser().resolve()
        write_json(
            inventory_output,
            {
                "schemaVersion": "role_plan_inventory_v1",
                "generatedAt": now_iso(),
                "app": {
                    "appId": app["appId"],
                    "appName": str(app_meta.get("name", "")).strip() or app["appName"],
                },
                "allWorksheetNames": worksheet_names,
                "selectedWorksheetNames": selected_worksheet_names,
                "selectionMode": "manual" if requested_worksheet_names else "all",
            },
        )

    ai_config = load_ai_config(config_path, tier="fast")
    client = get_ai_client(ai_config)
    prompt = build_prompt(str(app_meta.get("name", "")).strip() or app["appName"], selected_worksheet_names)
    if args.prompt_output:
        prompt_output = Path(args.prompt_output).expanduser().resolve()
        prompt_output.parent.mkdir(parents=True, exist_ok=True)
        prompt_output.write_text(prompt, encoding="utf-8")

    raw: Dict[str, Any] = {}
    raw_response_text = ""
    last_error = ""
    for i in range(1, max(1, args.max_retries) + 1):
        append_log(log_path, "ai_request", attempt=i)
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=create_generation_config(
                    ai_config,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            raw_response_text = resp.text or ""
            raw = extract_json_object(raw_response_text)
            roles = normalize_roles(raw)
            break
        except Exception as exc:
            last_error = str(exc)
            append_log(log_path, "ai_retry_failed", attempt=i, error=last_error)
            if i >= max(1, args.max_retries):
                raise RuntimeError(f"AI 生成失败: {last_error}") from exc
    else:
        raise RuntimeError(f"AI 生成失败: {last_error}")

    roles = normalize_roles(raw)
    if args.raw_output:
        raw_output = Path(args.raw_output).expanduser().resolve()
        raw_output.parent.mkdir(parents=True, exist_ok=True)
        raw_output.write_text(raw_response_text, encoding="utf-8")
    notes = raw.get("notes", [])
    if not isinstance(notes, list):
        notes = []

    result = {
        "schemaVersion": "role_plan_v1",
        "generatedAt": now_iso(),
        "model": model_name,
        "app": {
            "appId": app["appId"],
            "appName": str(app_meta.get("name", "")).strip() or app["appName"],
        },
        "worksheetNames": selected_worksheet_names,
        "allWorksheetNames": worksheet_names,
        "selectionMode": "manual" if requested_worksheet_names else "all",
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
    print(f"- 工作表数量: {len(selected_worksheet_names)} / 全部 {len(worksheet_names)}")
    print(f"- 推荐角色数量: {len(roles)}")
    print(f"- 结果文件: {output_path}")
    print(f"- 日志文件: {log_path}")
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {log_path}")


if __name__ == "__main__":
    main()
