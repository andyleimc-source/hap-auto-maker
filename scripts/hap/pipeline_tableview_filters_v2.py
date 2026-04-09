#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图筛选流水线 v2：按工作表并发执行 fetch_views -> fetch_controls -> AI规划 -> SaveWorksheetView。
每张表独立线程，受全局 gemini_semaphore 限流（通过 --semaphore-value 传入，默认 1000）。
Gemini 2.5 Flash 付费第一层级：RPD=10K，RPM=1000，TPM=1M。
"""

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parent
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import auth_retry
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config
from i18n import system_default_view_names
from utils import now_ts, latest_file

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
RESULT_DIR = OUTPUT_ROOT / "tableview_filter_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
WORKSHEET_INFO_URL = "https://api.mingdao.com/v3/app/worksheets/{worksheet_id}"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"

SUPPORTED_VIEW_TYPES = {"0", "1", "3", "4"}
NAV_SUPPORTED_VIEW_TYPES = {"0", "3"}
# 日历视图(4)会进入 AI 规划清单，但禁止在本阶段写入 fastFilters。
# SaveWorksheetView 对 advancedSetting 不是字段级 merge，
# 若只补 enablebtn 等快筛参数，可能覆盖创建阶段已落好的
# calendarcids / begindate / enddate，导致再次弹出日历初始化面板。
FAST_SUPPORTED_VIEW_TYPES = {"0", "1", "3"}
VIEW_TYPE_LABELS = {"0": "表格视图", "1": "看板视图", "3": "画廊视图", "4": "日历视图"}
DEFAULT_ALL_VIEW_NAMES = system_default_view_names()


# ── 数据拉取 ──────────────────────────────────────────────────────────────────

def fetch_app_structure(app_key: str, sign: str) -> Tuple[str, List[dict]]:
    """返回 (app_name, worksheets列表)，worksheets 每项含 workSheetId/workSheetName。"""
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json"}
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app_data = data.get("data", {})
    app_name = str(app_data.get("name", "")).strip()

    worksheets: List[dict] = []

    def walk(section: dict):
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append({
                    "workSheetId": str(item.get("id", "")),
                    "workSheetName": str(item.get("name", "")),
                })
        for child in section.get("childSections", []) or []:
            walk(child)

    for sec in app_data.get("sections", []) or []:
        walk(sec)
    return app_name, worksheets


def fetch_app_auth(app_id: str) -> Tuple[str, str]:
    """从 APP_AUTH_DIR 按 appId 读取 (app_key, sign)。"""
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in (data.get("data") or []):
            if isinstance(row, dict) and str(row.get("appId", "")).strip() == app_id:
                app_key = str(row.get("appKey", "")).strip()
                sign = str(row.get("sign", "")).strip()
                if app_key and sign:
                    return app_key, sign
    raise FileNotFoundError(f"未找到 appId={app_id} 的授权信息（目录: {APP_AUTH_DIR}）")


def fetch_worksheet_views(worksheet_id: str, app_key: str, sign: str) -> List[dict]:
    """获取工作表视图列表（v3 API）。"""
    url = WORKSHEET_INFO_URL.format(worksheet_id=worksheet_id)
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        return []
    views = data.get("data", {}).get("views") or []
    return views if isinstance(views, list) else []


def find_default_all_view(views: List[dict]) -> Optional[dict]:
    """从视图列表中找到系统默认的 All/全部 视图（viewType=0）。"""
    for v in views:
        if not isinstance(v, dict):
            continue
        vtype = v.get("viewType") if v.get("viewType") is not None else v.get("type")
        if isinstance(vtype, str):
            try:
                vtype = int(vtype)
            except ValueError:
                continue
        view_name = str(v.get("name", "")).strip()
        if vtype == 0 and view_name in DEFAULT_ALL_VIEW_NAMES:
            view_id = str(v.get("viewId") or v.get("id") or "").strip()
            if view_id:
                return {"viewId": view_id, "viewName": view_name, "viewType": "0"}
    return None


def fetch_controls(worksheet_id: str, auth_config_path: Path) -> List[dict]:
    """获取工作表字段列表。"""
    resp = auth_retry.hap_web_post(
        GET_CONTROLS_URL, auth_config_path,
        referer=f"https://www.mingdao.com/worksheet/field/edit?sourceId={worksheet_id}",
        json={"worksheetId": worksheet_id}, timeout=30,
    )
    data = resp.json()
    wrapped = data.get("data", {})
    if isinstance(wrapped, dict) and isinstance(wrapped.get("data"), dict):
        if int(wrapped.get("code", 0) or 0) != 1:
            raise RuntimeError(f"获取工作表控件失败: worksheetId={worksheet_id}, resp={data}")
        payload = wrapped["data"]
    else:
        payload = data.get("data", {})
        if not isinstance(payload, dict):
            raise RuntimeError(f"获取工作表控件失败: worksheetId={worksheet_id}, resp={data}")
    controls = payload.get("controls", [])
    return controls if isinstance(controls, list) else []


def simplify_field(field: dict) -> dict:
    """压缩字段信息以减少 prompt 体积。"""
    ftype = field.get("type")
    subtype = field.get("subType")
    options = field.get("options")
    field_id = str(field.get("id", "") or field.get("controlId", "")).strip()
    field_name = str(field.get("name", "") or field.get("controlName", "")).strip()
    is_system = bool(field.get("isSystemControl", False))
    if not is_system:
        try:
            is_system = int(field.get("attribute", 0) or 0) == 1
        except Exception:
            is_system = False
    is_dropdown = False
    if isinstance(ftype, str):
        is_dropdown = ftype in ("SingleSelect", "MultipleSelect")
    elif isinstance(ftype, int):
        is_dropdown = ftype in (9, 10, 11)
    if isinstance(subtype, int) and subtype in (10, 11):
        is_dropdown = True
    return {
        "id": field_id,
        "name": field_name,
        "type": ftype,
        "subType": subtype,
        "isTitle": bool(field.get("isTitle", False)),
        "required": bool(field.get("required", False)),
        "isSystem": is_system,
        "optionCount": len(options) if isinstance(options, list) else 0,
        "isDropdown": is_dropdown,
    }


# ── AI 规划 ───────────────────────────────────────────────────────────────────

def build_prompt(app_name: str, worksheet_name: str, worksheet_id: str,
                 target_views: List[dict], fields: List[dict]) -> str:
    return f"""你是明道云视图配置专家。请分析该工作表中支持的视图，是否需要配置：
1) 筛选列表(navGroup + advancedSetting中的导航参数)
2) 快速筛选(fastFilters + advancedSetting.enablebtn)

应用：{app_name}
工作表：{worksheet_name}
worksheetId：{worksheet_id}
目标视图：
{json.dumps(target_views, ensure_ascii=False, indent=2)}
字段：
{json.dumps(fields, ensure_ascii=False, indent=2)}

只输出 JSON：
{{
  "worksheetId": "{worksheet_id}",
  "viewPlans": [
    {{
      "viewId": "表格视图ID",
      "viewName": "视图名",
      "needNavGroup": true,
      "navGroup": [{{"controlId": "字段ID", "isAsc": true, "navshow": "0"}}],
      "navAdvancedSetting": {{
        "shownullitem": "1",
        "navsorts": "",
        "customnavs": "",
        "navlayer": "",
        "navshow": "0",
        "navfilters": "[]",
        "usenav": "0",
        "navsearchtype": "0"
      }},
      "navEditAdKeys": ["shownullitem","navsorts","customnavs","navlayer","navshow","navfilters","usenav","navsearchtype","navsearchcontrol"],
      "needFastFilters": true,
      "fastFilters": [
        {{"controlId": "字段ID", "filterType": 1}},
        {{"controlId": "字段ID", "filterType": 2, "advancedSetting": {{"direction":"2","allowitem":"1"}}}}
      ],
      "fastAdvancedSetting": {{"enablebtn": "1"}},
      "fastEditAdKeys": ["enablebtn"],
      "needColor": true,
      "colorControlId": "单选字段ID，用于记录颜色标记",
      "needGroup": true,
      "groupControlId": "单选字段ID，用于分组显示",
      "reason": "原因"
    }}
  ]
}}

规则：
1) 【强制】目标视图中的每个视图都必须在 viewPlans 中输出，不得遗漏。
2) controlId 必须来自字段列表。
3) 只有 表格视图(type=0) 和 画廊视图(type=3) 允许配置 navGroup。
4) navGroup（筛选列表）只能使用"下拉字段"（isDropdown=true）。
5) 若存在多个下拉字段，优先选择业务管理意义最强的那个（如状态/类型/分类/等级/阶段等）。
6) 仅表格/看板/画廊视图允许配置 fastFilters；日历视图不要配置。
7) 若不需要某功能，对应 needXxx=false，数组/字段留空。即使某视图不需要任何配置也必须输出（needXxx 全 false）。
8) fastFilters 建议 1-4 个。表格视图（viewType=0）默认应配置快速筛选，除非完全没有合适的筛选字段。
9) 输出必须为合法 JSON，viewPlans 长度必须等于目标视图数量。
10) 颜色(needColor): 仅 viewType=0 的表格视图支持。选一个最能代表记录状态/分类的单选字段(type=9 或 type=11)作为 colorControlId。若无合适单选字段，needColor=false，colorControlId 留空。
11) 分组(needGroup): 仅 viewType=0 的表格视图支持。选一个有业务分类意义的单选字段(type=9 或 type=11)作为 groupControlId（可与 colorControlId 相同）。若无合适字段或分组无业务意义，needGroup=false，groupControlId 留空。""".strip()


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("AI 返回为空")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"AI 未返回可解析 JSON:\n{text[:500]}")


def generate_with_retry(client: Any, model: str, prompt: str, ai_config: dict, retries: int = 4) -> str:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=create_generation_config(
                    ai_config,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return resp.text or ""
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            wait = min(8, 2 ** (attempt - 1))
            print(f"  AI 调用失败（第{attempt}次），{wait}s 后重试：{exc}")
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


# ── 字段归一化 ────────────────────────────────────────────────────────────────

def pick_best_dropdown_field(fields: List[dict]) -> str:
    """选"最有业务管理意义"的下拉字段。"""
    keywords = ("状态", "类型", "分类", "等级", "阶段", "级别", "优先级", "标签", "归属")
    best_id = ""
    best_score = -10 ** 9
    for f in fields:
        if not isinstance(f, dict) or not bool(f.get("isDropdown", False)):
            continue
        fid = str(f.get("id", "")).strip()
        if not fid:
            continue
        score = 0
        name = str(f.get("name", "")).strip()
        if bool(f.get("required", False)):
            score += 5
        if not bool(f.get("isSystem", False)):
            score += 2
        if isinstance(f.get("optionCount"), int) and 2 <= int(f["optionCount"]) <= 20:
            score += 2
        for kw in keywords:
            if kw in name:
                score += 8
                break
        if score > best_score:
            best_score = score
            best_id = fid
    return best_id


def _normalize_field_type(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _build_fast_filter_item(cid: str, field_meta: dict) -> dict:
    """按字段类型固化快速筛选配置，避免再次回退为缺少关键 UI 配置的最小结构。"""
    field_type = _normalize_field_type(field_meta.get("type"))
    if field_type in (9, 11):
        return {
            "controlId": cid,
            "filterType": 2,
            "advancedSetting": {"direction": "2", "allowitem": "1"},
        }
    if field_type == 10:
        return {
            "controlId": cid,
            "filterType": 2,
            "advancedSetting": {"direction": "2", "allowitem": "2"},
        }
    return {"controlId": cid}


def normalize_view_plan(
    item: dict,
    field_map: Dict[str, dict],
    fields: List[dict],
    views_by_id: Dict[str, dict],
) -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    view_id = str(item.get("viewId", "")).strip()
    if not view_id or view_id not in views_by_id:
        return None
    view_type = str(views_by_id[view_id].get("viewType", "")).strip()

    def norm_cid(cid: str) -> str:
        x = str(cid or "").strip()
        return x if x in field_map else ""

    best_dropdown_id = pick_best_dropdown_field(fields)

    # navGroup
    need_nav = bool(item.get("needNavGroup", False))
    nav_group = []
    for g in (item.get("navGroup") or []):
        if not isinstance(g, dict):
            continue
        cid = norm_cid(g.get("controlId", ""))
        if not cid or not bool(field_map.get(cid, {}).get("isDropdown", False)):
            continue
        out: dict = {"controlId": cid, "isAsc": bool(g.get("isAsc", True)), "navshow": str(g.get("navshow", "0"))}
        dt = field_map[cid].get("type")
        if isinstance(dt, int):
            out["dataType"] = dt
        nav_group.append(out)
    if need_nav and view_type in NAV_SUPPORTED_VIEW_TYPES and not nav_group and best_dropdown_id:
        fb: dict = {"controlId": best_dropdown_id, "isAsc": True, "navshow": "0"}
        dt = field_map[best_dropdown_id].get("type")
        if isinstance(dt, int):
            fb["dataType"] = dt
        nav_group = [fb]
    reason = str(item.get("reason", "")).strip()
    if view_type not in NAV_SUPPORTED_VIEW_TYPES:
        need_nav = False
        nav_group = []
    elif not best_dropdown_id:
        need_nav = False
        nav_group = []

    # fastFilters
    need_fast = bool(item.get("needFastFilters", False))
    fast_filters = []
    seen_fast_ids: set[str] = set()
    for f in (item.get("fastFilters") or []):
        if not isinstance(f, dict):
            continue
        cid = norm_cid(f.get("controlId", ""))
        if not cid or cid in seen_fast_ids:
            continue
        seen_fast_ids.add(cid)
        # 基于字段类型生成稳定默认配置，避免“允许选择数量 / 显示方式”再次丢失。
        fast_filters.append(_build_fast_filter_item(cid, field_map.get(cid, {})))
    if view_type not in FAST_SUPPORTED_VIEW_TYPES:
        need_fast = False
        fast_filters = []
    elif need_fast and not fast_filters:
        need_fast = False

    nav_adv = item.get("navAdvancedSetting") if isinstance(item.get("navAdvancedSetting"), dict) else {}
    nav_edit_keys = [str(x).strip() for x in (item.get("navEditAdKeys") or []) if str(x).strip()]
    fast_adv = item.get("fastAdvancedSetting") if isinstance(item.get("fastAdvancedSetting"), dict) else {}
    fast_edit_keys = [str(x).strip() for x in (item.get("fastEditAdKeys") or []) if str(x).strip()]
    if need_fast and fast_filters:
        fast_adv = {"enablebtn": "1", **fast_adv}
        if "enablebtn" not in fast_edit_keys:
            fast_edit_keys = ["enablebtn", *fast_edit_keys]

    # color
    need_color = bool(item.get("needColor", False))
    color_cid = str(item.get("colorControlId", "")).strip()
    if color_cid not in field_map:
        color_cid = ""
    if color_cid and field_map.get(color_cid, {}).get("type") not in (9, 11):
        color_cid = ""
    if need_color and not color_cid:
        for f in fields:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id", "")).strip()
            if fid and f.get("type") in (9, 11) and not bool(f.get("isSystem", False)):
                color_cid = fid
                break
    if not color_cid or view_type != "0":
        need_color = False
        color_cid = ""

    # group
    need_group = bool(item.get("needGroup", False))
    group_cid = str(item.get("groupControlId", "")).strip()
    if group_cid not in field_map:
        group_cid = ""
    if group_cid and field_map.get(group_cid, {}).get("type") not in (9, 11):
        group_cid = ""
    if need_group and not group_cid:
        for f in fields:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id", "")).strip()
            if fid and f.get("type") in (9, 11) and not bool(f.get("isSystem", False)):
                group_cid = fid
                break
    if not group_cid or view_type != "0":
        need_group = False
        group_cid = ""

    return {
        "viewId": view_id,
        "viewName": str(item.get("viewName", "")).strip(),
        "viewType": view_type,
        "needNavGroup": need_nav,
        "navGroup": nav_group,
        "navAdvancedSetting": nav_adv,
        "navEditAdKeys": nav_edit_keys,
        "needFastFilters": need_fast,
        "fastFilters": fast_filters,
        "fastAdvancedSetting": fast_adv,
        "fastEditAdKeys": fast_edit_keys,
        "needColor": need_color,
        "colorControlId": color_cid,
        "needGroup": need_group,
        "groupControlId": group_cid,
        "reason": reason,
    }


# ── 视图保存 ──────────────────────────────────────────────────────────────────

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


def _save_view_request(app_id: str, worksheet_id: str, view_id: str,
                       payload: dict, auth_config_path: Path, dry_run: bool) -> dict:
    """底层 SaveWorksheetView 调用。"""
    if dry_run:
        return {"dry_run": True, "payload": payload}
    referer = f"https://www.mingdao.com/app/{app_id}/{worksheet_id}/{view_id}"
    resp = auth_retry.hap_web_post(SAVE_VIEW_URL, auth_config_path, referer=referer, json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


def save_view_nav(app_id: str, worksheet_id: str, view_id: str, plan: dict,
                  auth_config_path: Path, dry_run: bool) -> dict:
    """保存筛选列表（navGroup）。"""
    payload = {
        "appId": app_id, "worksheetId": worksheet_id, "viewId": view_id,
        "editAttrs": ["navGroup", "advancedSetting"],
        "navGroup": plan.get("navGroup") if isinstance(plan.get("navGroup"), list) else [],
        "advancedSetting": to_adv_str_dict(plan.get("navAdvancedSetting")),
        "editAdKeys": plan.get("navEditAdKeys") if isinstance(plan.get("navEditAdKeys"), list) else [],
    }
    return _save_view_request(app_id, worksheet_id, view_id, payload, auth_config_path, dry_run)


def save_view_fast_filters(app_id: str, worksheet_id: str, view_id: str, plan: dict,
                           auth_config_path: Path, dry_run: bool) -> dict:
    """保存快速筛选（fastFilters）。"""
    payload = {
        "appId": app_id,
        "worksheetId": worksheet_id,
        "viewId": view_id,
        "editAttrs": ["fastFilters"],
        "fastFilters": plan.get("fastFilters") if isinstance(plan.get("fastFilters"), list) else [],
    }
    fast_adv = to_adv_str_dict(plan.get("fastAdvancedSetting"))
    fast_edit_keys = plan.get("fastEditAdKeys") if isinstance(plan.get("fastEditAdKeys"), list) else []
    # 仅当确实有可写入项时再提交 advancedSetting，避免空配置污染默认 UI 行为。
    if fast_adv and fast_edit_keys:
        payload["editAttrs"] = ["fastFilters", "advancedSetting"]
        payload["advancedSetting"] = fast_adv
        payload["editAdKeys"] = fast_edit_keys
    return _save_view_request(app_id, worksheet_id, view_id, payload, auth_config_path, dry_run)


def save_view_color(app_id: str, worksheet_id: str, view_id: str, color_control_id: str,
                    auth_config_path: Path, dry_run: bool) -> dict:
    """保存颜色配置。"""
    payload = {
        "appId": app_id, "worksheetId": worksheet_id, "viewId": view_id,
        "editAttrs": ["advancedSetting"],
        "advancedSetting": {"enablerules": "1", "colorid": color_control_id, "colortype": "0"},
        "editAdKeys": ["enablerules", "colorid", "colortype"],
    }
    return _save_view_request(app_id, worksheet_id, view_id, payload, auth_config_path, dry_run)


def save_view_group(app_id: str, worksheet_id: str, view_id: str, group_control_id: str,
                    group_data_type: int,
                    auth_config_path: Path, dry_run: bool) -> dict:
    """保存分组配置。"""
    group_view_obj = {
        "viewId": view_id,
        "groupFilters": [{
            "controlId": group_control_id,
            # dataType 必须与真实单选字段类型一致；此前写死 11 会把 type=9 的视图保存坏。
            "values": [], "dataType": int(group_data_type or 0), "spliceType": 1, "filterType": 2,
            "dateRange": 0, "minValue": "", "maxValue": "", "isGroup": True,
        }],
        "navShow": True,
    }
    payload = {
        "appId": app_id, "worksheetId": worksheet_id, "viewId": view_id,
        "editAttrs": ["advancedSetting"],
        "advancedSetting": {
            "groupView": json.dumps(group_view_obj, ensure_ascii=False, separators=(",", ":")),
            "navempty": "1",
        },
        "editAdKeys": ["groupView", "navempty"],
    }
    return _save_view_request(app_id, worksheet_id, view_id, payload, auth_config_path, dry_run)


# ── Per-worksheet worker ──────────────────────────────────────────────────────

def process_worksheet(
    ws: dict,
    app_id: str,
    app_name: str,
    app_key: str,
    sign: str,
    view_create_targets: List[dict],
    semaphore: threading.Semaphore,
    client: Any,
    model: str,
    ai_config: dict,
    auth_config_path: Path,
    dry_run: bool,
) -> dict:
    ws_id = ws["workSheetId"]
    ws_name = ws["workSheetName"]
    result: dict = {
        "workSheetId": ws_id,
        "workSheetName": ws_name,
        "viewCount": 0,
        "savedCount": 0,
        "ok": False,
        "error": None,
    }
    try:
        # 1. 获取视图列表，注入默认"全部"视图
        raw_views = fetch_worksheet_views(ws_id, app_key, sign)
        default_view = find_default_all_view(raw_views)
        existing_ids = {t["viewId"] for t in view_create_targets}
        targets = list(view_create_targets)
        if default_view and default_view["viewId"] not in existing_ids:
            targets.insert(0, default_view)
        if not targets:
            result["ok"] = True
            result["error"] = "no_target_views"
            return result

        # 2. 获取字段
        raw_controls = fetch_controls(ws_id, auth_config_path)
        fields = [simplify_field(f) for f in raw_controls if isinstance(f, dict)]
        field_map = {str(f.get("id", "")).strip(): f for f in fields if str(f.get("id", "")).strip()}
        views_by_id = {str(v.get("viewId", "")).strip(): v for v in targets}

        # 3. AI 规划（受 semaphore 限流）
        prompt = build_prompt(app_name, ws_name, ws_id, targets, fields)
        with semaphore:
            raw_text = generate_with_retry(client, model, prompt, ai_config)

        parsed = extract_json(raw_text)
        view_plans_raw = parsed.get("viewPlans", [])

        # 4. 归一化
        view_plans = []
        for item in view_plans_raw:
            norm = normalize_view_plan(item, field_map, fields, views_by_id)
            if norm:
                view_plans.append(norm)
        # 补漏：AI 未覆盖的视图
        covered_ids = {p["viewId"] for p in view_plans}
        for vid, v in views_by_id.items():
            if vid not in covered_ids:
                view_plans.append({
                    "viewId": vid, "viewName": v.get("viewName", ""), "viewType": v.get("viewType", ""),
                    "needNavGroup": False, "navGroup": [], "navAdvancedSetting": {}, "navEditAdKeys": [],
                    "needFastFilters": False, "fastFilters": [], "fastAdvancedSetting": {"enablebtn": "0"},
                    "fastEditAdKeys": ["enablebtn"], "needColor": False, "colorControlId": "",
                    "needGroup": False, "groupControlId": "", "reason": "AI未返回，默认不配置",
                })

        result["viewCount"] = len(view_plans)

        # 5. 保存视图（内层并发，每个视图可能需要多个 API 调用）
        def _save_plan(plan: dict) -> int:
            """保存单个视图的所有配置，返回成功调用次数（校验 state==1）。"""
            view_id = plan["viewId"]
            view_type = plan.get("viewType", "")
            saved = 0

            def _ok(resp: dict) -> bool:
                return dry_run or (isinstance(resp, dict) and int(resp.get("state", 0) or 0) == 1)

            if plan.get("needNavGroup") and plan.get("navGroup") and view_type in NAV_SUPPORTED_VIEW_TYPES:
                resp = save_view_nav(app_id, ws_id, view_id, plan, auth_config_path, dry_run)
                if _ok(resp):
                    saved += 1
                else:
                    print(f"    ⚠ navGroup 保存失败 ({view_id}): {resp}")
            if plan.get("needFastFilters") and plan.get("fastFilters") and view_type in FAST_SUPPORTED_VIEW_TYPES:
                resp = save_view_fast_filters(app_id, ws_id, view_id, plan, auth_config_path, dry_run)
                if _ok(resp):
                    saved += 1
                else:
                    print(f"    ⚠ fastFilters 保存失败 ({view_id}): {resp}")
            if plan.get("needColor") and plan.get("colorControlId") and view_type == "0":
                resp = save_view_color(app_id, ws_id, view_id, plan["colorControlId"], auth_config_path, dry_run)
                if _ok(resp):
                    saved += 1
                else:
                    print(f"    ⚠ color 保存失败 ({view_id}): {resp}")
            if plan.get("needGroup") and plan.get("groupControlId") and view_type == "0":
                group_data_type = _normalize_field_type(field_map.get(plan["groupControlId"], {}).get("type"))
                if group_data_type not in (9, 11):
                    print(f"    ⚠ group 跳过，字段类型非法 ({view_id}): {plan['groupControlId']} type={group_data_type}")
                else:
                    resp = save_view_group(
                        app_id, ws_id, view_id, plan["groupControlId"], group_data_type,
                        auth_config_path, dry_run,
                    )
                    if _ok(resp):
                        saved += 1
                    else:
                        print(f"    ⚠ group 保存失败 ({view_id}): {resp}")
            return saved

        needs_save = [p for p in view_plans if p.get("needNavGroup") or p.get("needFastFilters") or p.get("needColor") or p.get("needGroup")]
        saved_count = 0
        if needs_save:
            with ThreadPoolExecutor(max_workers=min(8, len(needs_save))) as inner:
                futs = {inner.submit(_save_plan, p): p for p in needs_save}
                for fut in as_completed(futs):
                    try:
                        saved_count += fut.result()
                    except Exception as e:
                        print(f"    ⚠ SaveWorksheetView 失败 ({futs[fut]['viewId']}): {e}")

        result["savedCount"] = saved_count
        result["ok"] = True
        print(f"  ✓ {ws_name}：{len(view_plans)} 个视图，保存操作 {saved_count} 次", flush=True)
    except Exception as exc:
        result["error"] = str(exc)
        print(f"  ✗ {ws_name}：{exc}", flush=True)
    return result


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="视图筛选流水线 v2（per-worksheet 并发）")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--semaphore-value", type=int, default=1000, help="Gemini 并发数（默认 1000）")
    parser.add_argument("--view-create-result", default="", help="视图创建结果 JSON 路径（可选）")
    parser.add_argument("--app-auth-json", default="", help="HAP 授权 JSON 文件路径（可选）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际调用接口")
    args = parser.parse_args()

    app_id = args.app_id.strip()
    semaphore = threading.Semaphore(args.semaphore_value)
    dry_run = args.dry_run

    # 读取 AI 配置
    ai_config = load_ai_config(AI_CONFIG_PATH)
    client = get_ai_client(ai_config)
    model = ai_config["model"]

    # 读取应用授权
    if args.app_auth_json.strip():
        auth_data = json.loads(Path(args.app_auth_json).read_text(encoding="utf-8"))
        row = next(
            (r for r in (auth_data.get("data") or []) if str(r.get("appId", "")).strip() == app_id),
            None,
        )
        if not row:
            raise ValueError(f"--app-auth-json 中未找到 appId={app_id}")
        app_key = str(row.get("appKey", "")).strip()
        sign = str(row.get("sign", "")).strip()
    else:
        app_key, sign = fetch_app_auth(app_id)

    # 获取应用结构
    print(f"获取应用结构：{app_id}", flush=True)
    app_name, worksheets = fetch_app_structure(app_key, sign)
    print(f"应用：{app_name}，工作表数：{len(worksheets)}", flush=True)

    # 读取视图创建结果
    view_create_targets_by_ws: Dict[str, List[dict]] = {}
    vcr_path: Optional[Path] = None
    vcr_str = args.view_create_result.strip()
    if vcr_str:
        p = Path(vcr_str).expanduser().resolve()
        if p.exists():
            vcr_path = p
        else:
            print(f"  ⚠ 视图创建结果文件不存在: {vcr_str}，仅处理默认视图", flush=True)
    if not vcr_path:
        vcr_path = latest_file(OUTPUT_ROOT / "view_create_results", "view_create_result_*.json")

    if vcr_path:
        try:
            vcr_data = json.loads(vcr_path.read_text(encoding="utf-8"))
            for app_item in (vcr_data.get("apps") or []):
                if str(app_item.get("appId", "")).strip() != app_id:
                    continue
                for ws_item in (app_item.get("worksheets") or []):
                    ws_id = str(ws_item.get("worksheetId", "")).strip()
                    targets = []
                    for view in (ws_item.get("views") or []):
                        view_id = str(view.get("createdViewId", "")).strip()
                        view_type = str(view.get("viewType", "")).strip()
                        if not view_id or view_type not in SUPPORTED_VIEW_TYPES:
                            continue
                        view_name = str(view.get("name", "")).strip()
                        if not view_name and isinstance(view.get("createPayload"), dict):
                            view_name = str(view["createPayload"].get("name", "")).strip()
                        targets.append({"viewId": view_id, "viewName": view_name, "viewType": view_type})
                    if targets:
                        view_create_targets_by_ws[ws_id] = targets
        except Exception as e:
            print(f"  ⚠ 读取视图创建结果失败，仅处理默认视图：{e}", flush=True)
    else:
        print("  ⚠ 未找到视图创建结果，仅处理默认视图", flush=True)

    # 并发处理所有工作表
    t0 = time.time()
    ws_results: List[dict] = []
    max_workers = min(args.semaphore_value, len(worksheets)) if worksheets else 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {
            pool.submit(
                process_worksheet,
                ws, app_id, app_name, app_key, sign,
                view_create_targets_by_ws.get(ws["workSheetId"], []),
                semaphore, client, model, ai_config, AUTH_CONFIG_PATH, dry_run,
            ): ws
            for ws in worksheets
        }
        for fut in as_completed(futs):
            try:
                ws_results.append(fut.result())
            except Exception as e:
                ws = futs[fut]
                ws_results.append({
                    "workSheetId": ws["workSheetId"],
                    "workSheetName": ws["workSheetName"],
                    "viewCount": 0, "savedCount": 0,
                    "ok": False, "error": str(e),
                })

    elapsed = time.time() - t0
    total_views = sum(r["viewCount"] for r in ws_results)
    total_saved = sum(r["savedCount"] for r in ws_results)
    failed = [r for r in ws_results if not r["ok"] and r.get("error") != "no_target_views"]

    payload = {
        "app": {"appId": app_id, "appName": app_name},
        "worksheetCount": len(worksheets),
        "totalViews": total_views,
        "totalSaved": total_saved,
        "elapsedSeconds": round(elapsed, 1),
        "dryRun": dry_run,
        "worksheets": ws_results,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = now_ts()
    out_path = (RESULT_DIR / f"tableview_filter_result_{app_id}_{ts}.json").resolve()
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path = RESULT_DIR / "tableview_filter_result_latest.json"
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n视图筛选完成  工作表={len(worksheets)}  视图={total_views}  保存={total_saved}  耗时={elapsed:.0f}s", flush=True)
    if failed:
        print(f"⚠ 失败 {len(failed)} 张表：{[r['workSheetName'] for r in failed]}", flush=True)
        sys.exit(1)
    print(f"结果：{out_path}", flush=True)


if __name__ == "__main__":
    main()
