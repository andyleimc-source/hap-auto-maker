#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行视图筛选配置规划：
- 筛选列表：navGroup + advancedSetting
- 快速筛选：fastFilters + advancedSetting
"""

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import auth_retry
from utils import now_ts, latest_file, load_json, write_json

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
PLAN_DIR = OUTPUT_ROOT / "tableview_filter_plans"
RESULT_DIR = OUTPUT_ROOT / "tableview_filter_apply_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"
NAV_SUPPORTED_VIEW_TYPES = {"0", "3"}
FAST_SUPPORTED_VIEW_TYPES = {"0", "1", "3"}


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


def save_view(payload: dict, auth_config_path: Path, app_id: str, worksheet_id: str, view_id: str, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "payload": payload}
    referer = f"https://www.mingdao.com/app/{app_id}/{worksheet_id}/{view_id}"
    resp = auth_retry.hap_web_post(SAVE_VIEW_URL, auth_config_path, referer=referer, json=payload, timeout=30)
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
    parser.add_argument("--max-workers", type=int, default=16, help="并发视图数（默认 16）")
    parser.add_argument("--output", default="", help="输出结果 JSON 路径")
    args = parser.parse_args()

    plan_path = resolve_plan_json(args.plan_json)
    plan = load_json(plan_path)
    auth_config_path = Path(args.auth_config).expanduser().resolve()

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
            "colorAppliedCount": 0,
            "groupAppliedCount": 0,
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

        def _process_vp(task):
            ws_id, ws_name, vp = task
            view_id = str(vp.get("viewId", "")).strip()
            view_name = str(vp.get("viewName", "")).strip()
            view_type = str(vp.get("viewType", "")).strip()
            view_result = {"viewId": view_id, "viewName": view_name, "viewType": view_type, "navApply": None, "fastApply": None}
            stats = {"navAppliedCount": 0, "fastAppliedCount": 0, "colorAppliedCount": 0, "groupAppliedCount": 0, "failedCount": 0}

            if bool(vp.get("needNavGroup", False)) and view_type in NAV_SUPPORTED_VIEW_TYPES:
                payload = {
                    "appId": app_id, "worksheetId": ws_id, "viewId": view_id,
                    "editAttrs": ["navGroup", "advancedSetting"],
                    "navGroup": vp.get("navGroup") if isinstance(vp.get("navGroup"), list) else [],
                    "advancedSetting": to_adv_str_dict(vp.get("navAdvancedSetting")),
                    "editAdKeys": vp.get("navEditAdKeys") if isinstance(vp.get("navEditAdKeys"), list) else [],
                }
                resp = save_view(payload, auth_config_path, app_id, ws_id, view_id, args.dry_run)
                ok = bool(args.dry_run) or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
                view_result["navApply"] = {"payload": payload, "response": resp, "success": ok}
                if ok:
                    stats["navAppliedCount"] += 1
                else:
                    stats["failedCount"] += 1
            else:
                reason = "needNavGroup=false"
                if bool(vp.get("needNavGroup", False)) and view_type not in NAV_SUPPORTED_VIEW_TYPES:
                    reason = f"viewType={view_type} 不支持筛选列表"
                view_result["navApply"] = {"skipped": True, "reason": reason}

            if bool(vp.get("needFastFilters", False)) and view_type in FAST_SUPPORTED_VIEW_TYPES:
                payload = {
                    "appId": app_id, "worksheetId": ws_id, "viewId": view_id,
                    "editAttrs": ["fastFilters", "advancedSetting"],
                    "fastFilters": vp.get("fastFilters") if isinstance(vp.get("fastFilters"), list) else [],
                    "advancedSetting": to_adv_str_dict(vp.get("fastAdvancedSetting")),
                    "editAdKeys": vp.get("fastEditAdKeys") if isinstance(vp.get("fastEditAdKeys"), list) else [],
                }
                resp = save_view(payload, auth_config_path, app_id, ws_id, view_id, args.dry_run)
                ok = bool(args.dry_run) or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
                view_result["fastApply"] = {"payload": payload, "response": resp, "success": ok}
                if ok:
                    stats["fastAppliedCount"] += 1
                else:
                    stats["failedCount"] += 1
            else:
                reason = "needFastFilters=false"
                if bool(vp.get("needFastFilters", False)) and view_type not in FAST_SUPPORTED_VIEW_TYPES:
                    reason = f"viewType={view_type} 不支持快速筛选"
                view_result["fastApply"] = {"skipped": True, "reason": reason}

            # ── 颜色配置 ──
            color_control_id = str(vp.get("colorControlId", "")).strip()
            if bool(vp.get("needColor", False)) and color_control_id and view_type == "0":
                payload = {
                    "appId": app_id, "worksheetId": ws_id, "viewId": view_id,
                    "editAttrs": ["advancedSetting"],
                    "advancedSetting": {
                        "enablerules": "1",
                        "colorid": color_control_id,
                        "colortype": "0",
                    },
                    "editAdKeys": ["enablerules", "colorid", "colortype"],
                }
                resp = save_view(payload, auth_config_path, app_id, ws_id, view_id, args.dry_run)
                ok = bool(args.dry_run) or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
                view_result["colorApply"] = {"payload": payload, "response": resp, "success": ok}
                if ok:
                    stats["colorAppliedCount"] += 1
                else:
                    stats["failedCount"] += 1
            else:
                view_result["colorApply"] = {"skipped": True, "reason": "needColor=false or no colorControlId"}

            # ── 分组配置 ──
            group_control_id = str(vp.get("groupControlId", "")).strip()
            if bool(vp.get("needGroup", False)) and group_control_id and view_type == "0":
                group_view_obj = {
                    "viewId": view_id,
                    "groupFilters": [{
                        "controlId": group_control_id,
                        "values": [],
                        "dataType": 11,
                        "spliceType": 1,
                        "filterType": 2,
                        "dateRange": 0,
                        "minValue": "",
                        "maxValue": "",
                        "isGroup": True,
                    }],
                    "navShow": True,
                }
                group_view_str = json.dumps(group_view_obj, ensure_ascii=False, separators=(",", ":"))
                payload = {
                    "appId": app_id, "worksheetId": ws_id, "viewId": view_id,
                    "editAttrs": ["advancedSetting"],
                    "advancedSetting": {
                        "groupView": group_view_str,
                        "navempty": "1",
                    },
                    "editAdKeys": ["groupView", "navempty"],
                }
                resp = save_view(payload, auth_config_path, app_id, ws_id, view_id, args.dry_run)
                ok = bool(args.dry_run) or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
                view_result["groupApply"] = {"payload": payload, "response": resp, "success": ok}
                if ok:
                    stats["groupAppliedCount"] += 1
                else:
                    stats["failedCount"] += 1
            else:
                view_result["groupApply"] = {"skipped": True, "reason": "needGroup=false or no groupControlId"}

            return ws_id, ws_name, view_result, stats

        # 构建所有视图任务（跨工作表展平）
        all_tasks = []
        ws_order = []
        ws_meta = {}
        for ws in ws_list:
            if not isinstance(ws, dict):
                continue
            ws_id = str(ws.get("worksheetId", "")).strip()
            ws_name = str(ws.get("worksheetName", "")).strip() or ws_id
            if not ws_id or (wanted_ws_ids and ws_id not in wanted_ws_ids):
                continue
            view_plans = ws.get("viewPlans")
            if not isinstance(view_plans, list):
                view_plans = []
            if ws_id not in ws_meta:
                ws_meta[ws_id] = ws_name
                ws_order.append(ws_id)
            for vp in view_plans:
                if not isinstance(vp, dict):
                    continue
                view_id = str(vp.get("viewId", "")).strip()
                if not view_id or (wanted_view_ids and view_id not in wanted_view_ids):
                    continue
                all_tasks.append((ws_id, ws_name, vp))

        result["summary"]["worksheetCount"] += len(ws_meta)
        result["summary"]["viewCount"] += len(all_tasks)

        ws_results: dict = {ws_id: {"worksheetId": ws_id, "worksheetName": ws_meta[ws_id], "views": []} for ws_id in ws_order}
        _lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [executor.submit(_process_vp, task) for task in all_tasks]
            for future in as_completed(futures):
                ws_id, ws_name, view_result, stats = future.result()
                with _lock:
                    ws_results[ws_id]["views"].append(view_result)
                    for k in ("navAppliedCount", "fastAppliedCount", "colorAppliedCount", "groupAppliedCount", "failedCount"):
                        result["summary"][k] += stats[k]

        for ws_id in ws_order:
            app_result["worksheets"].append(ws_results[ws_id])

        if app_result["worksheets"]:
            result["apps"].append(app_result)

    result["summary"]["appCount"] = len(result["apps"])

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
    print(f"- 颜色配置应用次数: {result['summary']['colorAppliedCount']}")
    print(f"- 分组配置应用次数: {result['summary']['groupAppliedCount']}")
    print(f"- 失败次数: {result['summary']['failedCount']}")


if __name__ == "__main__":
    main()
