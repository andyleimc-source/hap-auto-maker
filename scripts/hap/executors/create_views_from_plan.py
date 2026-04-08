#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按视图规划 JSON 创建工作表视图。
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
from typing import Any, Dict, List, Optional

import auth_retry
from utils import now_ts, latest_file, load_json, write_json

# 导入视图注册中心（用于自动补全 postCreateUpdates）
try:
    from views.view_types import VIEW_REGISTRY
    _HAS_VIEW_REGISTRY = True
except ImportError:
    _HAS_VIEW_REGISTRY = False
    VIEW_REGISTRY = {}

BASE_DIR = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
VIEW_PLAN_DIR = OUTPUT_ROOT / "view_plans"
VIEW_CREATE_RESULT_DIR = OUTPUT_ROOT / "view_create_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"




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
        if k == "groupsetting":
            # 表格视图分组字段必须是 JSON 数组字符串：
            # ✅ [{"controlId":"...","isAsc":true}]
            # ❌ {"controlId":"...","isAsc":true}
            # ❌ ["fieldId"]  ← AI 常见错误格式
            # 若写成非法格式，前端打开工作表会出现「服务异常」。
            parsed = parse_json_loose(v)
            if isinstance(parsed, dict):
                parsed = [parsed]
            if isinstance(parsed, list):
                # 修正 AI 生成的纯字符串数组：["fieldId"] → [{"controlId":"fieldId","isAsc":true}]
                normalized = []
                for item in parsed:
                    if isinstance(item, str) and item.strip():
                        normalized.append({"controlId": item.strip(), "isAsc": True})
                    elif isinstance(item, dict):
                        normalized.append(item)
                out["groupsetting"] = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(v, str):
                out["groupsetting"] = v
            elif v is None:
                out["groupsetting"] = "[]"
            else:
                out["groupsetting"] = str(v)
            continue
        if k == "groupView":
            # groupView 是 navGroup（左侧导航筛选栏）配置，不是表格行分组。
            # 表格视图行分组应使用 groupsetting，见 view_config_schema.py。
            # 这里保留序列化逻辑以兼容可能真正需要 groupView 的场景（如分组看板）。
            if isinstance(v, dict):
                out["groupView"] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(v, str) and v.strip():
                try:
                    gv_obj = json.loads(v)
                    out["groupView"] = json.dumps(gv_obj, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    out["groupView"] = v
            else:
                out["groupView"] = str(v) if v else ""
        elif isinstance(v, (dict, list)):
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


def auto_complete_post_updates(view: dict, ws_fields: list[dict] | None = None) -> list[dict]:
    """从注册中心自动生成 postCreateUpdates，补全 AI 未填写的关键配置。

    针对甘特图(5)、层级视图(2)、资源视图(9)等需要二次保存的视图类型，
    当 AI 规划时未输出 postCreateUpdates（或输出为空）时，自动从 view 字段中
    提取必要参数并构建更新 payload。

    Args:
        view: AI 规划的单个视图 dict，含 viewType、begindate/enddate/
              layersControlId/resourceId/calendarcids 等字段

    Returns:
        postCreateUpdates 列表，可直接传给执行逻辑
    """
    if not _HAS_VIEW_REGISTRY:
        return []

    view_type = int(str(view.get("viewType", "0")).strip() or "0")
    spec = VIEW_REGISTRY.get(view_type, {})
    post_create = spec.get("post_create")
    if not post_create:
        return []

    edit_attrs = post_create.get("editAttrs", [])
    edit_ad_keys = post_create.get("editAdKeys", [])

    # ── 甘特图(5): begindate + enddate ──────────────────────────────────────
    if view_type == 5:
        begindate = str(view.get("begindate", "") or "").strip()
        enddate = str(view.get("enddate", "") or "").strip()
        # 也从 postCreateUpdates 旧格式中提取
        for upd in view.get("postCreateUpdates") or []:
            adv = upd.get("advancedSetting") or {}
            begindate = begindate or str(adv.get("begindate", "")).strip()
            enddate = enddate or str(adv.get("enddate", "")).strip()
        # 如果 AI 没有提供日期字段 ID，从工作表字段列表中自动查找日期字段(type=15/16)
        if not begindate and ws_fields:
            date_field_ids = []
            for f in ws_fields:
                f_type = int(f.get("type", 0) or f.get("controlType", 0) or 0)
                f_id = str(f.get("id", "") or f.get("controlId", "")).strip()
                if f_type in (15, 16) and f_id:
                    date_field_ids.append(f_id)
            if date_field_ids:
                begindate = date_field_ids[0]
                enddate = date_field_ids[1] if len(date_field_ids) >= 2 else date_field_ids[0]
        if not begindate:
            return []
        return [{
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["begindate", "enddate"],
            "advancedSetting": {"begindate": begindate, "enddate": enddate},
        }]

    # ── 层级视图(2): viewControl + childType ────────────────────────────────
    # 抓包确认（2026-04-04）：保存时用 viewControl='create' 让 HAP 自动创建
    # 自关联字段，或用具体字段 ID。childType=1 表示使用关联字段模式。
    # ⚠️ 重要：如果工作表已有自关联字段(type=29, dataSource=本表)，必须复用，
    #    禁止用 "create" 重复创建，否则每次跑都会新建一对父/子字段。
    if view_type == 2:
        layers_id = str(view.get("layersControlId", "") or "").strip()
        for upd in view.get("postCreateUpdates") or []:
            layers_id = layers_id or str(upd.get("layersControlId", "")).strip()
        # 如果 AI 没有提供字段 ID，从工作表字段列表中查找已有的自关联字段
        if not layers_id and ws_fields:
            ws_id_self = str(view.get("_worksheetId", "") or "").strip()
            for f in ws_fields:
                f_type = int(f.get("type", 0) or f.get("controlType", 0) or 0)
                f_datasource = str(f.get("dataSource", "")).strip()
                f_id = str(f.get("id", "") or f.get("controlId", "")).strip()
                # 自关联：type=29 且 dataSource 是本表
                if f_type == 29 and f_datasource and (not ws_id_self or f_datasource == ws_id_self):
                    layers_id = f_id
                    break
        view_control = layers_id or "create"
        return [{
            "editAttrs": ["viewControl", "childType", "viewType"],
            "viewControl": view_control,
            "childType": 1,
            "viewType": 2,
        }]

    # ── 日历视图(4): calendarcids ────────────────────────────────────────────
    if view_type == 4:
        calendarcids = str(view.get("calendarcids", "") or "").strip()
        for upd in view.get("postCreateUpdates") or []:
            adv = upd.get("advancedSetting") or {}
            calendarcids = calendarcids or str(adv.get("calendarcids", "")).strip()
        # 兜底：AI 没提供时从字段列表自动查找日期字段(type=15/16)
        if not calendarcids and ws_fields:
            date_field_ids = []
            for f in ws_fields:
                f_type = int(f.get("type", 0) or f.get("controlType", 0) or 0)
                f_id = str(f.get("id", "") or f.get("controlId", "")).strip()
                if f_type in (15, 16) and f_id:
                    date_field_ids.append(f_id)
            if date_field_ids:
                begin_id = date_field_ids[0]
                end_id = date_field_ids[1] if len(date_field_ids) >= 2 else ""
                calendarcids = json.dumps(
                    [{"begin": begin_id, "end": end_id}],
                    ensure_ascii=False, separators=(",", ":")
                )
        if not calendarcids:
            return []
        return [{
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["calendarcids"],
            "advancedSetting": {"calendarcids": calendarcids},
        }]

    # ── 资源视图(9): resourceId + startdate + enddate ────────────────────────
    if view_type == 9:
        resource_id = str(view.get("resourceId", "") or "").strip()
        startdate = str(view.get("startdate", "") or "").strip()
        enddate = str(view.get("enddate", "") or "").strip()
        for upd in view.get("postCreateUpdates") or []:
            adv = upd.get("advancedSetting") or {}
            resource_id = resource_id or str(adv.get("resourceId", "")).strip()
            startdate = startdate or str(adv.get("startdate", "")).strip()
            enddate = enddate or str(adv.get("enddate", "")).strip()
        if not resource_id or not startdate:
            return []
        return [{
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["resourceId", "startdate", "enddate"],
            "advancedSetting": {
                "resourceId": resource_id,
                "startdate": startdate,
                "enddate": enddate,
            },
        }]

    return []


def merge_post_updates(ai_updates: list, auto_updates: list, view_type: int) -> list:
    """合并 AI 提供的和自动补全的 postCreateUpdates，自动补全优先级更高。

    对于同一视图类型，如果 AI 已经填了正确的配置，则使用 AI 的；
    如果 AI 未填或填了空值，则使用自动补全的。
    """
    if not auto_updates:
        return ai_updates if isinstance(ai_updates, list) else []
    if not ai_updates:
        return auto_updates

    # 提取 AI 配置中的关键值（用于判断是否有效）
    def _has_valid_keys(updates: list, keys: list[str]) -> bool:
        for upd in updates:
            adv = upd.get("advancedSetting") or {}
            top = upd
            for k in keys:
                v = str(adv.get(k, "") or top.get(k, "") or "").strip()
                if v and not v.startswith("<"):
                    return True
        return False

    need_keys = {
        5: ["begindate"],
        2: ["layersControlId"],
        4: ["calendarcids"],
        9: ["resourceId", "startdate"],
    }
    keys = need_keys.get(view_type, [])
    if keys and _has_valid_keys(ai_updates, keys):
        return ai_updates  # AI 已填有效值，优先用 AI 的
    return auto_updates  # AI 未填或填了占位符，使用自动补全


def build_create_payload(app_id: str, worksheet_id: str, view: dict) -> dict:
    # viewType 统一转整数字符串；0 是合法的表格/列表视图
    _vt_raw = view.get("viewType", 0)
    try:
        _vt_int = int(str(_vt_raw).strip())
    except (ValueError, TypeError):
        _vt_int = 0
    view_type = str(_vt_int)
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

    # 地图视图(7)：latlng 写入 advancedSetting
    if str(view_type) == "7":
        latlng = str(view.get("latlng", "") or "").strip()
        if latlng:
            payload["advancedSetting"]["latlng"] = latlng

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
            # 分组视图：groupView.viewId 必须填实际视图 ID，且必须使用紧凑格式（无空格）
            if "groupView" in adv and view_id:
                try:
                    gv_obj = json.loads(adv["groupView"])
                    if isinstance(gv_obj, dict):
                        if not gv_obj.get("viewId"):
                            gv_obj["viewId"] = view_id
                        # 始终使用紧凑格式（separators 无空格），否则明道云前端无法识别
                        adv["groupView"] = json.dumps(gv_obj, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    pass
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


def update_default_view(
    app_id: str,
    worksheet_id: str,
    view_id: str,
    update_plan: dict,
    auth_config_path: Path,
    dry_run: bool = False,
) -> dict:
    """改造默认视图：改名 + 修改 displayControls + 加配置。

    Args:
        app_id: 应用 ID
        worksheet_id: 工作表 ID
        view_id: 默认视图的 viewId
        update_plan: AI 输出的 default_view_update dict
        auth_config_path: 认证配置路径
        dry_run: 是否仅演练

    Returns:
        API 响应 dict
    """
    view_type = str(update_plan.get("viewType", "0")).strip()
    payload = {
        "viewId": view_id,
        "appId": app_id,
        "worksheetId": worksheet_id,
        "name": str(update_plan.get("name", "")).strip() or "数据总览",
        "editAttrs": ["name", "displayControls", "advancedSetting"],
    }

    display_controls = update_plan.get("displayControls")
    if isinstance(display_controls, list):
        payload["displayControls"] = [str(x).strip() for x in display_controls if str(x).strip()]

    adv = update_plan.get("advancedSetting")
    if isinstance(adv, dict):
        payload["advancedSetting"] = normalize_advanced_setting(view_type, adv)

    if dry_run:
        return {"dry_run": True, "payload": payload}

    return post_web_api(SAVE_VIEW_URL, payload, auth_config_path, app_id=app_id, worksheet_id=worksheet_id, view_id=view_id)


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

                view_type_int = int(str(view.get("viewType", "0")).strip() or "0")
                ai_updates = view.get("postCreateUpdates")
                if not isinstance(ai_updates, list):
                    ai_updates = []
                # 传入工作表字段列表和工作表 ID，供层级视图复用已有自关联字段
                view_with_ws = dict(view)
                view_with_ws["_worksheetId"] = ws_id
                ws_fields = ws.get("fields", [])
                auto_updates = auto_complete_post_updates(view_with_ws, ws_fields)
                post_updates = merge_post_updates(ai_updates, auto_updates, view_type_int)
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
