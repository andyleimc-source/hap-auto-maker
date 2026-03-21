#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据推荐角色 JSON，为应用创建角色。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, List, Optional

import requests

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
    load_json,
    make_log_path,
    make_output_path,
    now_iso,
    resolve_json_input,
    write_json,
)

ROLE_PLAN_DIR = OUTPUT_ROOT / "role_plans"
ROLE_CREATE_RESULT_DIR = OUTPUT_ROOT / "role_create_results"
ROLE_CREATE_RESULT_LATEST = ROLE_CREATE_RESULT_DIR / "role_create_result_latest.json"

GET_ROLES_ENDPOINT = "/v1/open/app/getRoles"
CREATE_ROLE_ENDPOINT = "/v1/open/app/createRole"


def request_open_app_json(method: str, url: str, params: dict, payload: Optional[dict] = None) -> dict:
    resp = requests.request(
        method=method,
        url=url,
        params=params,
        json=payload,
        timeout=30,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        },
    )
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"接口返回非 JSON: status={resp.status_code}, body={resp.text[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"接口返回格式错误: {data}")
    if not data.get("success"):
        raise RuntimeError(f"接口调用失败: {data}")
    return data


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


def make_create_role_payload(role: dict) -> dict:
    permissions = role.get("permissions", {})
    if not isinstance(permissions, dict):
        permissions = {}
    return {
        "name": str(role.get("name", "")).strip(),
        "description": str(role.get("description", "")).strip(),
        "permissionWay": int(role.get("permissionWay", 20) or 20),
        "roleType": 0,
        "hideAppForMembers": bool_or_default(role.get("hideAppForMembers"), False),
        "generalAdd": {"enable": bool_or_default(permissions.get("generalAdd"), True)},
        "gneralShare": {"enable": bool_or_default(permissions.get("generalShare"), False)},
        "generalImport": {"enable": bool_or_default(permissions.get("generalImport"), False)},
        "generalExport": {"enable": bool_or_default(permissions.get("generalExport"), False)},
        "generalDiscussion": {"enable": bool_or_default(permissions.get("generalDiscussion"), True)},
        "generalLogging": {"enable": bool_or_default(permissions.get("generalLogging"), True)},
        "generalSystemPrinting": {"enable": bool_or_default(permissions.get("generalSystemPrinting"), False)},
        "recordShare": {"enable": bool_or_default(permissions.get("recordShare"), False)},
        "payment": {"enable": bool_or_default(permissions.get("payment"), False)},
    }


def build_open_app_params(app: dict) -> dict:
    params = {
        "appKey": str(app.get("appKey", "")).strip(),
        "sign": str(app.get("sign", "")).strip(),
        "appId": str(app.get("appId", "")).strip(),
    }
    project_id = str(app.get("projectId", "")).strip()
    if project_id:
        params["projectId"] = project_id
    return params


def fetch_existing_roles(base_url: str, params: dict) -> List[dict]:
    url = base_url.rstrip("/") + GET_ROLES_ENDPOINT
    data = request_open_app_json("GET", url, params=params, payload=None)
    rows = data.get("data", [])
    if not isinstance(rows, list):
        return []
    return [x for x in rows if isinstance(x, dict)]


def find_role_by_name(existing: List[dict], role_name: str) -> Optional[dict]:
    target = role_name.strip()
    for row in existing:
        name = str(row.get("name", "")).strip()
        if name and name == target:
            return row
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="根据推荐角色 JSON 创建角色")
    parser.add_argument("--plan-json", default="", help="推荐角色 JSON 文件路径或文件名（默认取最新）")
    parser.add_argument("--app-id", default="", help="可选，指定 appId（默认使用 plan 里的 appId）")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="角色已存在时跳过（默认启用）")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false", help="角色已存在时不跳过，继续尝试创建")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    plan_path = resolve_json_input(
        args.plan_json,
        search_dirs=[ROLE_PLAN_DIR],
        default_pattern="role_plan_*.json",
    )
    plan = load_json(plan_path)
    plan_app_id = str(plan.get("app", {}).get("appId", "")).strip()
    target_app_id = args.app_id.strip() or plan_app_id

    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=target_app_id, app_index=args.app_index)
    log_path = make_log_path("role_create", app["appId"])
    append_log(
        log_path,
        "start",
        appId=app["appId"],
        appName=app["appName"],
        planJson=str(plan_path),
        skipExisting=bool(args.skip_existing),
    )

    roles = plan.get("recommendedRoles", [])
    if not isinstance(roles, list) or not roles:
        raise ValueError(f"推荐角色为空: {plan_path}")

    params = build_open_app_params(app)
    existing_roles = fetch_existing_roles(args.base_url, params)
    append_log(log_path, "existing_roles_loaded", count=len(existing_roles))

    created: List[dict] = []
    skipped: List[dict] = []
    failed: List[dict] = []

    for idx, role in enumerate(roles, start=1):
        if not isinstance(role, dict):
            continue
        role_name = str(role.get("name", "")).strip()
        if not role_name:
            failed.append({"index": idx, "name": "", "error": "角色名称为空"})
            continue
        exists = find_role_by_name(existing_roles, role_name)
        if exists and args.skip_existing:
            role_id = str(exists.get("roleId", "") or exists.get("id", "")).strip()
            skipped.append({"index": idx, "name": role_name, "reason": "已存在", "roleId": role_id})
            append_log(log_path, "role_skipped", index=idx, name=role_name, roleId=role_id)
            continue

        payload = make_create_role_payload(role)
        payload.update(params)
        url = args.base_url.rstrip("/") + CREATE_ROLE_ENDPOINT
        append_log(log_path, "role_create_start", index=idx, name=role_name, payload=payload)
        try:
            data = request_open_app_json("POST", url, params=params, payload=payload)
            role_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
            role_id = str(role_data.get("roleId", "") or role_data.get("id", "")).strip()
            created.append({"index": idx, "name": role_name, "roleId": role_id, "response": role_data})
            append_log(log_path, "role_create_success", index=idx, name=role_name, roleId=role_id)
            existing_roles.append({"name": role_name, "roleId": role_id})
        except Exception as exc:
            failed.append({"index": idx, "name": role_name, "error": str(exc)})
            append_log(log_path, "role_create_failed", index=idx, name=role_name, error=str(exc))

    result = {
        "schemaVersion": "role_create_result_v1",
        "createdAt": now_iso(),
        "app": {
            "appId": app["appId"],
            "appName": app["appName"],
        },
        "planJson": str(plan_path),
        "summary": {
            "total": len([x for x in roles if isinstance(x, dict)]),
            "createdCount": len(created),
            "skippedCount": len(skipped),
            "failedCount": len(failed),
        },
        "created": created,
        "skipped": skipped,
        "failed": failed,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        ensure_dir(ROLE_CREATE_RESULT_DIR)
        output_path = make_output_path(ROLE_CREATE_RESULT_DIR, "role_create_result", app["appId"])

    write_json(output_path, result)
    write_json(ROLE_CREATE_RESULT_LATEST.resolve(), result)
    append_log(log_path, "finished", output=str(output_path), summary=result["summary"])

    print("角色创建执行完成")
    print(f"- 应用: {app['appName']} ({app['appId']})")
    print(f"- 总数: {result['summary']['total']}")
    print(f"- 已创建: {result['summary']['createdCount']}")
    print(f"- 已跳过: {result['summary']['skippedCount']}")
    print(f"- 失败: {result['summary']['failedCount']}")
    print(f"- 结果文件: {output_path}")
    print(f"- 日志文件: {log_path}")
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {log_path}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
