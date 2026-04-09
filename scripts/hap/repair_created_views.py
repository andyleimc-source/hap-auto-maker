#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对刚创建出来的视图做完整性校验与补修。

目的：
1) 日历/甘特/资源视图若缺少关键 advancedSetting，自动按 HAR 固化规则补写；
2) 自定义视图若名称被冲成空串，按视图创建结果中的计划名称回写；
3) 英文应用在存在非系统视图时，删除残留的系统默认视图（全部/All/View/空名）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = Path(__file__).resolve().parents[2]
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from delete_view import delete_view
from executors.create_views_from_plan import auto_complete_post_updates, build_update_payload, save_view
from i18n import normalize_language, system_default_view_names
from pipeline_tableview_filters_v2 import fetch_controls, fetch_worksheet_views
from utils import now_ts, write_json

OUTPUT_DIR = BASE_DIR / "data" / "outputs" / "view_repair_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"


def load_app_auth(path: Path, app_id: str) -> tuple[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("data") or []
    for row in rows:
        if isinstance(row, dict) and str(row.get("appId", "")).strip() == app_id:
            app_key = str(row.get("appKey", "")).strip()
            sign = str(row.get("sign", "")).strip()
            if app_key and sign:
                return app_key, sign
    raise ValueError(f"授权文件中未找到 appId={app_id}: {path}")


def load_targets(view_create_result: Path, app_id: str) -> List[dict]:
    data = json.loads(view_create_result.read_text(encoding="utf-8"))
    apps = data.get("apps") or []
    for app in apps:
        if isinstance(app, dict) and str(app.get("appId", "")).strip() == app_id:
            return app.get("worksheets") or []
    raise ValueError(f"视图创建结果中未找到 appId={app_id}: {view_create_result}")


def _view_id(view: dict) -> str:
    return str(view.get("viewId") or view.get("id") or "").strip()


def _view_name(view: dict) -> str:
    return str(view.get("name") or view.get("viewName") or "").strip()


def _view_type(view: dict) -> str:
    return str(view.get("viewType") if view.get("viewType") is not None else view.get("type") or "").strip()


def _advanced_setting(view: dict) -> dict:
    adv = view.get("advancedSetting")
    return adv if isinstance(adv, dict) else {}


def _current_missing_required(view: dict, view_type: str) -> bool:
    adv = _advanced_setting(view)
    if view_type == "4":
        return not str(adv.get("calendarcids", "") or "").strip()
    if view_type == "5":
        begin = str(adv.get("begindate", "") or view.get("begindate", "") or "").strip()
        end = str(adv.get("enddate", "") or view.get("enddate", "") or "").strip()
        return not begin or not end
    if view_type == "7":
        begin = str(adv.get("begindate", "") or "").strip()
        view_control = str(view.get("viewControl", "") or "").strip()
        return not begin or not view_control
    return False


def _build_seed_view(target: dict, current_view: dict) -> dict:
    adv = _advanced_setting(current_view)
    seed = {
        "name": str(target.get("name", "")).strip() or _view_name(current_view),
        "viewType": _view_type(target) or _view_type(current_view),
    }
    for key in ("calendarcids", "begindate", "enddate", "startdate"):
        value = str(adv.get(key, "") or current_view.get(key, "") or "").strip()
        if value:
            seed[key] = value
    for key in ("viewControl", "resourceId"):
        value = str(current_view.get(key, "") or "").strip()
        if value:
            seed[key] = value
    for key in ("navshow", "navfilters"):
        value = str(adv.get(key, "") or "").strip()
        if value:
            seed[key] = value
    return seed


def _rename_view(
    app_id: str,
    worksheet_id: str,
    view_id: str,
    name: str,
    auth_config_path: Path,
    dry_run: bool,
) -> dict:
    payload = {
        "appId": app_id,
        "worksheetId": worksheet_id,
        "viewId": view_id,
        "name": name,
        "editAttrs": ["name"],
    }
    return save_view(payload, auth_config_path, app_id, worksheet_id, dry_run)


def repair_worksheet(
    app_id: str,
    worksheet_target: dict,
    app_key: str,
    sign: str,
    auth_config_path: Path,
    lang: str,
    dry_run: bool,
) -> dict:
    ws_id = str(worksheet_target.get("worksheetId", "")).strip()
    ws_name = str(worksheet_target.get("worksheetName", "")).strip()
    targets = worksheet_target.get("views") or []

    current_views = fetch_worksheet_views(ws_id, app_key, sign)
    current_by_id = {_view_id(v): v for v in current_views if _view_id(v)}
    ws_fields = fetch_controls(ws_id, auth_config_path)

    repairs: list[dict] = []

    for target in targets:
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("createdViewId", "")).strip()
        target_name = str(target.get("name", "")).strip()
        target_type = str(target.get("viewType", "")).strip()
        if not target_id:
            continue
        current = current_by_id.get(target_id)
        if not current:
            repairs.append({"viewId": target_id, "action": "missing_view", "ok": True, "skipped": True})
            continue

        current_name = _view_name(current)
        if not current_name and target_name:
            resp = _rename_view(app_id, ws_id, target_id, target_name, auth_config_path, dry_run)
            ok = dry_run or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
            repairs.append({
                "viewId": target_id,
                "viewName": target_name,
                "action": "rename_empty_view",
                "ok": ok,
                "response": resp,
            })
            if ok:
                current["name"] = target_name

        if target_type in {"4", "5", "7"} and _current_missing_required(current, target_type):
            seed = _build_seed_view(target, current)
            updates = auto_complete_post_updates(seed, ws_fields)
            update_results = []
            all_ok = True
            for upd in updates:
                payload = build_update_payload(app_id, ws_id, target_id, upd)
                skip_reason = str(payload.pop("_skip_reason", "")).strip()
                if skip_reason:
                    update_results.append({"skipped": True, "reason": skip_reason, "payload": payload})
                    continue
                resp = save_view(payload, auth_config_path, app_id, ws_id, dry_run)
                ok = dry_run or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)
                all_ok = all_ok and ok
                update_results.append({"payload": payload, "response": resp, "ok": ok})
            repairs.append({
                "viewId": target_id,
                "viewName": target_name or current_name,
                "action": "repair_required_settings",
                "ok": all_ok and bool(updates),
                "updates": update_results,
            })

    if normalize_language(lang) == "en":
        current_views = fetch_worksheet_views(ws_id, app_key, sign)
        non_default = [v for v in current_views if _view_name(v) not in system_default_view_names()]
        if non_default:
            for view in current_views:
                name = _view_name(view)
                view_id = _view_id(view)
                if name in system_default_view_names() and view_id:
                    ok = True if dry_run else delete_view(app_id, ws_id, view_id, auth_config_path)
                    repairs.append({
                        "viewId": view_id,
                        "viewName": name,
                        "action": "delete_system_default_view",
                        "ok": ok,
                    })

    return {
        "worksheetId": ws_id,
        "worksheetName": ws_name,
        "repairCount": len(repairs),
        "repairs": repairs,
        "ok": all(r.get("ok", True) for r in repairs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="修复创建后缺关键配置或空名称的视图")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--app-auth-json", required=True, help="应用授权 JSON 路径")
    parser.add_argument("--view-create-result", required=True, help="视图创建结果 JSON 路径")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--language", default="zh", help="应用语言（zh/en）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际写入")
    args = parser.parse_args()

    app_id = args.app_id.strip()
    app_auth_json = Path(args.app_auth_json).expanduser().resolve()
    view_create_result = Path(args.view_create_result).expanduser().resolve()
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    lang = normalize_language(args.language)

    app_key, sign = load_app_auth(app_auth_json, app_id)
    worksheet_targets = load_targets(view_create_result, app_id)

    results = [
        repair_worksheet(app_id, ws, app_key, sign, auth_config_path, lang, args.dry_run)
        for ws in worksheet_targets
    ]
    payload = {
        "appId": app_id,
        "language": lang,
        "dryRun": args.dry_run,
        "worksheetCount": len(results),
        "repairCount": sum(item.get("repairCount", 0) for item in results),
        "worksheets": results,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"view_repair_result_{app_id}_{now_ts()}.json"
    write_json(out_path, payload)
    write_json(OUTPUT_DIR / "view_repair_result_latest.json", payload)
    print(f"视图补修完成: {out_path}")

    failed = [item for item in results if not item.get("ok", True)]
    if failed:
        print(f"⚠ 存在补修失败工作表: {[item['worksheetName'] for item in failed]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
