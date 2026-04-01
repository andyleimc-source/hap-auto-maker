#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按视图规划 JSON 创建工作表视图。
"""

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import auth_retry

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
VIEW_PLAN_DIR = OUTPUT_ROOT / "view_plans"
VIEW_CREATE_RESULT_DIR = OUTPUT_ROOT / "view_create_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"


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
        candidate = (VIEW_PLAN_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到规划文件: {value}")
    p = latest_file(VIEW_PLAN_DIR, "view_plan_*.json")
    if not p:
        raise FileNotFoundError(f"未找到规划文件（目录: {VIEW_PLAN_DIR}）")
    return p.resolve()



def normalize_advanced_setting(view_type: str, value: Any) -> dict:
    if isinstance(value, dict):
        raw = dict(value)
    else:
        raw = {}
    if "enablerules" not in raw:
        raw["enablerules"] = "1"
    if "coverstyle" not in raw:
        if str(view_type) == "3":
            raw["coverstyle"] = '{"position":"2"}'
        elif str(view_type) in ("2", "5"):
            pass  # 层级视图和甘特图不需要 coverstyle
        else:
            raw["coverstyle"] = '{"position":"1","style":3}'
    out = {}
    for k, v in raw.items():
        if isinstance(v, (dict, list)):
            out[str(k)] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(v, bool):
            out[str(k)] = "1" if v else "0"
        elif v is None:
            out[str(k)] = ""
        else:
            out[str(k)] = str(v)
    return out


def parse_json_loose(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def normalize_calendarcids(value: Any) -> str:
    raw = parse_json_loose(value)
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return ""

    normalized: List[Dict[str, str]] = []
    for item in raw:
        # 支持纯字符串元素，视为 begin 字段 ID
        if isinstance(item, str):
            cid = item.strip()
            if cid:
                normalized.append({"begin": cid, "end": ""})
            continue
        if not isinstance(item, dict):
            continue
        # 兼容多种键名: begin/begindate/start/cid
        begin = str(
            item.get("begin")
            or item.get("begindate")
            or item.get("start")
            or item.get("cid")
            or ""
        ).strip()
        end = str(
            item.get("end")
            or item.get("enddate")
            or item.get("endCid")
            or ""
        ).strip()
        color = str(item.get("color") or "").strip()
        if not begin:
            continue
        one = {"begin": begin, "end": end}
        if color:
            one["color"] = color
        normalized.append(one)
    if not normalized:
        return ""
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def build_create_payload(app_id: str, worksheet_id: str, view: dict) -> dict:
    view_type = str(view.get("viewType", "0")).strip() or "0"
    display_controls = view.get("displayControls")
    if not isinstance(display_controls, list):
        display_controls = []
    display_controls = [str(x).strip() for x in display_controls if str(x).strip()]

    payload = {
        "viewId": "",
        "appId": app_id,
        "worksheetId": worksheet_id,
        "viewType": view_type,
        "name": str(view.get("name", "")).strip() or f"视图_{view_type}",
        "displayControls": display_controls,
        "sortType": 0,
        "coverType": 0,
        "controls": [],
        "filters": [],
        "sortCid": "",
        "showControlName": True,
        "advancedSetting": normalize_advanced_setting(view_type, view.get("advancedSetting")),
    }

    cover_cid = str(view.get("coverCid", "")).strip()
    if cover_cid:
        payload["coverCid"] = cover_cid
    view_control = str(view.get("viewControl", "")).strip()
    if view_control:
        payload["viewControl"] = view_control
    return payload


def build_update_payload(app_id: str, worksheet_id: str, view_id: str, update: dict) -> dict:
    payload = {"appId": app_id, "worksheetId": worksheet_id, "viewId": view_id}
    for k, v in update.items():
        if k in ("appId", "worksheetId", "viewId"):
            continue
        if k == "advancedSetting":
            adv = normalize_advanced_setting("", v)
            if "calendarcids" in adv:
                fixed = normalize_calendarcids(adv.get("calendarcids", ""))
                if fixed:
                    adv["calendarcids"] = fixed
                else:
                    adv.pop("calendarcids", None)
            payload[k] = adv
        else:
            payload[k] = v
    edit_ad_keys = payload.get("editAdKeys")
    if isinstance(edit_ad_keys, list):
        cleaned = []
        for x in edit_ad_keys:
            key = str(x).strip()
            if not key:
                continue
            if key == "calendarcids" and not str((payload.get("advancedSetting") or {}).get("calendarcids", "")).strip():
                continue
            cleaned.append(key)
        if cleaned:
            payload["editAdKeys"] = cleaned
        else:
            payload.pop("editAdKeys", None)
            payload["_skip_reason"] = "无有效 editAdKeys，跳过本次 postCreateUpdate"
    return payload


def post_web_api(url: str, payload: dict, auth_config_path: Path, app_id: str, worksheet_id: str, view_id: str = "") -> dict:
    referer = f"https://www.mingdao.com/app/{app_id}/{worksheet_id}"
    if view_id:
        referer = f"{referer}/{view_id}"
    resp = auth_retry.hap_web_post(url, auth_config_path, referer=referer, json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


def save_view(payload: dict, auth_config_path: Path, app_id: str, worksheet_id: str, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "payload": payload}
    return post_web_api(SAVE_VIEW_URL, payload, auth_config_path, app_id=app_id, worksheet_id=worksheet_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="执行视图规划 JSON，批量创建工作表视图")
    parser.add_argument("--plan-json", default="", help="视图规划 JSON 路径（默认取最新）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="认证配置 auth_config.py 路径")
    parser.add_argument("--app-ids", default="", help="可选，仅执行指定 appId（逗号分隔）")
    parser.add_argument("--worksheet-ids", default="", help="可选，仅执行指定 worksheetId（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际调用接口")
    parser.add_argument("--max-workers", type=int, default=16, help="并发工作表数（默认 16）")
    parser.add_argument("--output", default="", help="输出结果 JSON 路径")
    args = parser.parse_args()

    plan_path = resolve_plan_json(args.plan_json)
    plan = load_json(plan_path)
    auth_config_path = Path(args.auth_config).expanduser().resolve()

    wanted_app_ids = {x.strip() for x in str(args.app_ids).split(",") if x.strip()}
    wanted_ws_ids = {x.strip() for x in str(args.worksheet_ids).split(",") if x.strip()}

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
            "plannedViewCount": 0,
            "createdViewCount": 0,
            "updateCallCount": 0,
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

        def _process_ws(ws):
            if not isinstance(ws, dict):
                return None
            ws_id = str(ws.get("worksheetId", "")).strip()
            ws_name = str(ws.get("worksheetName", "")).strip() or ws_id
            if not ws_id:
                return None
            if wanted_ws_ids and ws_id not in wanted_ws_ids:
                return None
            views = ws.get("views")
            if not isinstance(views, list):
                views = []
            ws_result = {"worksheetId": ws_id, "worksheetName": ws_name, "views": []}
            stats = {"worksheetCount": 1, "plannedViewCount": len(views), "createdViewCount": 0, "updateCallCount": 0, "failedCount": 0}

            for view in views:
                if not isinstance(view, dict):
                    continue
                create_payload = build_create_payload(app_id, ws_id, view)
                create_resp = save_view(create_payload, auth_config_path, app_id, ws_id, args.dry_run)

                view_result = {
                    "name": create_payload["name"],
                    "viewType": create_payload["viewType"],
                    "createPayload": create_payload,
                    "createResponse": create_resp,
                    "createdViewId": "",
                    "updates": [],
                    "success": False,
                }

                created_view_id = ""
                final_success = False
                if args.dry_run:
                    created_view_id = "__DRY_RUN_VIEW_ID__"
                    final_success = True
                else:
                    if isinstance(create_resp, dict) and int(create_resp.get("state", 0) or 0) == 1:
                        created_view_id = str((create_resp.get("data") or {}).get("viewId", "")).strip()
                        final_success = bool(created_view_id)
                view_result["createdViewId"] = created_view_id

                post_updates = view.get("postCreateUpdates")
                if not isinstance(post_updates, list):
                    post_updates = []
                if created_view_id and final_success:
                    for upd in post_updates:
                        if not isinstance(upd, dict):
                            continue
                        upd_payload = build_update_payload(app_id, ws_id, created_view_id, upd)
                        skip_reason = str(upd_payload.pop("_skip_reason", "")).strip()
                        if skip_reason:
                            view_result["updates"].append({"payload": upd_payload, "skipped": True, "reason": skip_reason})
                            continue
                        upd_resp = save_view(upd_payload, auth_config_path, app_id, ws_id, args.dry_run)
                        view_result["updates"].append({"payload": upd_payload, "response": upd_resp})
                        stats["updateCallCount"] += 1
                        if not args.dry_run:
                            ok = isinstance(upd_resp, dict) and int(upd_resp.get("state", 0) or 0) == 1
                            if not ok:
                                final_success = False

                view_result["success"] = final_success
                if final_success:
                    stats["createdViewCount"] += 1
                else:
                    stats["failedCount"] += 1

                ws_result["views"].append(view_result)
            return ws_result, stats

        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [executor.submit(_process_ws, ws) for ws in ws_list]
            for future in as_completed(futures):
                ret = future.result()
                if ret is None:
                    continue
                ws_result, stats = ret
                app_result["worksheets"].append(ws_result)
                for k in ("worksheetCount", "plannedViewCount", "createdViewCount", "updateCallCount", "failedCount"):
                    result["summary"][k] += stats[k]

        if app_result["worksheets"]:
            result["apps"].append(app_result)

    result["summary"]["appCount"] = len(result["apps"])

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = (VIEW_CREATE_RESULT_DIR / f"view_create_result_{now_ts()}.json").resolve()
    write_json(out_path, result)

    print(f"执行完成: {out_path}")
    print(f"- 应用数: {result['summary']['appCount']}")
    print(f"- 工作表数: {result['summary']['worksheetCount']}")
    print(f"- 计划视图数: {result['summary']['plannedViewCount']}")
    print(f"- 创建成功视图数: {result['summary']['createdViewCount']}")
    print(f"- 更新调用次数: {result['summary']['updateCallCount']}")
    print(f"- 失败次数: {result['summary']['failedCount']}")


if __name__ == "__main__":
    main()
