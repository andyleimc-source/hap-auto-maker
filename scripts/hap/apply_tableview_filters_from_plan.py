#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行视图筛选配置规划：
- 筛选列表：navGroup + advancedSetting
- 快速筛选：fastFilters + advancedSetting
"""

import argparse
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
PLAN_DIR = OUTPUT_ROOT / "tableview_filter_plans"
RESULT_DIR = OUTPUT_ROOT / "tableview_filter_apply_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"
DELETE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/DeleteWorksheetView"
NAV_SUPPORTED_VIEW_TYPES = {"0", "3"}
FAST_SUPPORTED_VIEW_TYPES = {"0", "1", "3", "4"}


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_plan_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (PLAN_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到规划文件: {value}")
    p = latest_file(PLAN_DIR, "tableview_filter_plan_*.json")
    if not p:
        raise FileNotFoundError(f"未找到规划文件（目录: {PLAN_DIR}）")
    return p.resolve()


def load_auth_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"认证文件不存在: {path}")
    spec = importlib.util.spec_from_file_location("auth_config_runtime", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载认证文件: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    account_id = str(getattr(mod, "ACCOUNT_ID", "")).strip()
    authorization = str(getattr(mod, "AUTHORIZATION", "")).strip()
    cookie = str(getattr(mod, "COOKIE", "")).strip()
    if not account_id or not authorization or not cookie:
        raise ValueError(f"auth_config.py 缺少 ACCOUNT_ID/AUTHORIZATION/COOKIE: {path}")
    return {"accountId": account_id, "authorization": authorization, "cookie": cookie}


def to_adv_str_dict(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    out = {}
    for k, v in value.items():
        if isinstance(v, (dict, list)):
            out[str(k)] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(v, bool):
            out[str(k)] = "1" if v else "0"
        elif v is None:
            out[str(k)] = ""
        else:
            out[str(k)] = str(v)
    return out


def save_view(payload: dict, auth: dict, app_id: str, worksheet_id: str, view_id: str, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "payload": payload}
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "accountid": auth["accountId"],
        "Authorization": auth["authorization"],
        "Cookie": auth["cookie"],
        "Origin": "https://www.mingdao.com",
        "Referer": f"https://www.mingdao.com/app/{app_id}/{worksheet_id}/{view_id}",
        "X-Requested-With": "XMLHttpRequest",
    }
    resp = requests.post(SAVE_VIEW_URL, headers=headers, json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


def delete_view(app_id: str, worksheet_id: str, view_id: str, auth: dict, dry_run: bool) -> dict:
    payload = {"appId": app_id, "worksheetId": worksheet_id, "viewId": view_id}
    if dry_run:
        return {"dry_run": True, "payload": payload}
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "accountid": auth["accountId"],
        "Authorization": auth["authorization"],
        "Cookie": auth["cookie"],
        "Origin": "https://www.mingdao.com",
        "Referer": f"https://www.mingdao.com/app/{app_id}/{worksheet_id}/{view_id}",
        "X-Requested-With": "XMLHttpRequest",
    }
    resp = requests.post(DELETE_VIEW_URL, headers=headers, json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


def main() -> None:
    parser = argparse.ArgumentParser(description="执行视图筛选列表/快速筛选规划")
    parser.add_argument("--plan-json", default="", help="规划 JSON 路径（默认取最新）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="认证配置 auth_config.py 路径")
    parser.add_argument("--app-ids", default="", help="可选，仅执行指定 appId（逗号分隔）")
    parser.add_argument("--worksheet-ids", default="", help="可选，仅执行指定 worksheetId（逗号分隔）")
    parser.add_argument("--view-ids", default="", help="可选，仅执行指定 viewId（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际调用接口")
    parser.add_argument("--output", default="", help="输出结果 JSON 路径")
    args = parser.parse_args()

    plan_path = resolve_plan_json(args.plan_json)
    plan = load_json(plan_path)
    auth = load_auth_config(Path(args.auth_config).expanduser().resolve())

    wanted_app_ids = {x.strip() for x in str(args.app_ids).split(",") if x.strip()}
    wanted_ws_ids = {x.strip() for x in str(args.worksheet_ids).split(",") if x.strip()}
    wanted_view_ids = {x.strip() for x in str(args.view_ids).split(",") if x.strip()}

    apps = plan.get("apps")
    if not isinstance(apps, list) or not apps:
        raise ValueError(f"规划文件缺少 apps 列表: {plan_path}")

    result = {
        "executedAt": datetime.now().isoformat(timespec="seconds"),
        "planJson": str(plan_path),
        "dryRun": bool(args.dry_run),
        "apps": [],
        "summary": {
            "appCount": 0,
            "worksheetCount": 0,
            "viewCount": 0,
            "navAppliedCount": 0,
            "fastAppliedCount": 0,
            "deletedOldViewCount": 0,
            "deleteFailedCount": 0,
            "failedCount": 0,
        },
    }

    for app in apps:
        if not isinstance(app, dict):
            continue
        app_id = str(app.get("appId", "")).strip()
        app_name = str(app.get("appName", "")).strip() or app_id
        if not app_id:
            continue
        if wanted_app_ids and app_id not in wanted_app_ids:
            continue

        ws_list = app.get("worksheets")
        if not isinstance(ws_list, list):
            ws_list = []
        app_result = {"appId": app_id, "appName": app_name, "worksheets": []}

        for ws in ws_list:
            if not isinstance(ws, dict):
                continue
            ws_id = str(ws.get("worksheetId", "")).strip()
            ws_name = str(ws.get("worksheetName", "")).strip() or ws_id
            if not ws_id:
                continue
            if wanted_ws_ids and ws_id not in wanted_ws_ids:
                continue

            view_plans = ws.get("viewPlans")
            if not isinstance(view_plans, list):
                view_plans = []
            ws_result = {"worksheetId": ws_id, "worksheetName": ws_name, "views": []}
            result["summary"]["worksheetCount"] += 1

            for vp in view_plans:
                if not isinstance(vp, dict):
                    continue
                view_id = str(vp.get("viewId", "")).strip()
                view_name = str(vp.get("viewName", "")).strip()
                view_type = str(vp.get("viewType", "")).strip()
                if not view_id:
                    continue
                if wanted_view_ids and view_id not in wanted_view_ids:
                    continue
                result["summary"]["viewCount"] += 1

                view_result = {
                    "viewId": view_id,
                    "viewName": view_name,
                    "viewType": view_type,
                    "navApply": None,
                    "fastApply": None,
                }

                if bool(vp.get("needNavGroup", False)) and view_type in NAV_SUPPORTED_VIEW_TYPES:
                    payload = {
                        "appId": app_id,
                        "worksheetId": ws_id,
                        "viewId": view_id,
                        "editAttrs": ["navGroup", "advancedSetting"],
                        "navGroup": vp.get("navGroup") if isinstance(vp.get("navGroup"), list) else [],
                        "advancedSetting": to_adv_str_dict(vp.get("navAdvancedSetting")),
                        "editAdKeys": vp.get("navEditAdKeys") if isinstance(vp.get("navEditAdKeys"), list) else [],
                    }
                    resp = save_view(payload, auth, app_id, ws_id, view_id, args.dry_run)
                    ok = bool(args.dry_run) or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
                    view_result["navApply"] = {"payload": payload, "response": resp, "success": ok}
                    if ok:
                        result["summary"]["navAppliedCount"] += 1
                    else:
                        result["summary"]["failedCount"] += 1
                else:
                    reason = "needNavGroup=false"
                    if bool(vp.get("needNavGroup", False)) and view_type not in NAV_SUPPORTED_VIEW_TYPES:
                        reason = f"viewType={view_type} 不支持筛选列表"
                    view_result["navApply"] = {"skipped": True, "reason": reason}

                if bool(vp.get("needFastFilters", False)) and view_type in FAST_SUPPORTED_VIEW_TYPES:
                    payload = {
                        "appId": app_id,
                        "worksheetId": ws_id,
                        "viewId": view_id,
                        "editAttrs": ["fastFilters", "advancedSetting"],
                        "fastFilters": vp.get("fastFilters") if isinstance(vp.get("fastFilters"), list) else [],
                        "advancedSetting": to_adv_str_dict(vp.get("fastAdvancedSetting")),
                        "editAdKeys": vp.get("fastEditAdKeys") if isinstance(vp.get("fastEditAdKeys"), list) else [],
                    }
                    resp = save_view(payload, auth, app_id, ws_id, view_id, args.dry_run)
                    ok = bool(args.dry_run) or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
                    view_result["fastApply"] = {"payload": payload, "response": resp, "success": ok}
                    if ok:
                        result["summary"]["fastAppliedCount"] += 1
                    else:
                        result["summary"]["failedCount"] += 1
                else:
                    reason = "needFastFilters=false"
                    if bool(vp.get("needFastFilters", False)) and view_type not in FAST_SUPPORTED_VIEW_TYPES:
                        reason = f"viewType={view_type} 不支持快速筛选"
                    view_result["fastApply"] = {"skipped": True, "reason": reason}

                ws_result["views"].append(view_result)

            app_result["worksheets"].append(ws_result)
        if app_result["worksheets"]:
            result["apps"].append(app_result)

    result["summary"]["appCount"] = len(result["apps"])

    delete_plan = plan.get("oldViewsDeletePlan") if isinstance(plan.get("oldViewsDeletePlan"), dict) else {}
    delete_targets = delete_plan.get("targets") if isinstance(delete_plan.get("targets"), list) else []
    delete_results = []
    for item in delete_targets:
        if not isinstance(item, dict):
            continue
        app_id = str(item.get("appId", "")).strip()
        ws_id = str(item.get("worksheetId", "")).strip()
        view_id = str(item.get("viewId", "")).strip()
        if not app_id or not ws_id or not view_id:
            continue
        if wanted_app_ids and app_id not in wanted_app_ids:
            continue
        if wanted_ws_ids and ws_id not in wanted_ws_ids:
            continue
        if wanted_view_ids and view_id not in wanted_view_ids:
            continue
        resp = delete_view(app_id, ws_id, view_id, auth, args.dry_run)
        ok = bool(args.dry_run) or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
        delete_results.append({**item, "response": resp, "success": ok})
        if ok:
            result["summary"]["deletedOldViewCount"] += 1
        else:
            result["summary"]["deleteFailedCount"] += 1
    result["oldViewsDeleteAction"] = {
        "choice": str(delete_plan.get("choice", "")).strip(),
        "deleted": delete_results,
        "skipped": delete_plan.get("skipped") if isinstance(delete_plan.get("skipped"), list) else [],
    }

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = (RESULT_DIR / f"tableview_filter_apply_result_{now_ts()}.json").resolve()
    write_json(out_path, result)

    print(f"执行完成: {out_path}")
    print(f"- 应用数: {result['summary']['appCount']}")
    print(f"- 工作表数: {result['summary']['worksheetCount']}")
    print(f"- 视图数: {result['summary']['viewCount']}")
    print(f"- 筛选列表应用次数: {result['summary']['navAppliedCount']}")
    print(f"- 快速筛选应用次数: {result['summary']['fastAppliedCount']}")
    print(f"- 已删除旧视图数: {result['summary']['deletedOldViewCount']}")
    print(f"- 删除失败数: {result['summary']['deleteFailedCount']}")
    print(f"- 失败次数: {result['summary']['failedCount']}")


if __name__ == "__main__":
    main()
