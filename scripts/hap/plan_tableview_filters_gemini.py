#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规划视图的筛选列表(navGroup)与快速筛选(fastFilters)。

支持：
- 表格视图(type=0): 筛选列表 + 快速筛选
- 看板视图(type=1): 快速筛选
- 画廊视图(type=3): 筛选列表 + 快速筛选
- 日历视图(type=4): 快速筛选
"""

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import auth_retry
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config
from script_locator import resolve_script
from gemini_utils import load_gemini_config

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
PLAN_DIR = OUTPUT_ROOT / "tableview_filter_plans"
VIEW_CREATE_RESULT_DIR = OUTPUT_ROOT / "view_create_results"
GEMINI_CONFIG_PATH = AI_CONFIG_PATH
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
# 加载全局配置
try:
    GEN_API_KEY, GEN_MODEL = load_gemini_config()
except Exception:
    GEN_API_KEY = ""
    GEN_MODEL = "gemini-2.5-flash"

DEFAULT_MODEL = GEN_MODEL
APP_INFO_URL = "https://api.mingdao.com/v3/app"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
SUPPORTED_VIEW_TYPES = {"0", "1", "3", "4"}
NAV_SUPPORTED_VIEW_TYPES = {"0", "3"}
FAST_SUPPORTED_VIEW_TYPES = {"0", "1", "3"}
VIEW_TYPE_LABELS = {"0": "表格视图", "1": "看板视图", "3": "画廊视图", "4": "日历视图"}
DEFAULT_GEMINI_RETRIES = 4


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def parse_selection(text: str, max_index: int) -> List[int]:
    parts = [p for p in re.split(r"[^\d]+", text) if p]
    if not parts:
        return []
    out: List[int] = []
    for p in parts:
        idx = int(p)
        if idx < 1 or idx > max_index:
            raise ValueError(f"序号超出范围: {idx}（有效范围 1-{max_index}）")
        if idx not in out:
            out.append(idx)
    return out


def choose_indexes(prompt: str, items_count: int) -> Optional[List[int]]:
    choice = input(prompt).strip()
    if choice.lower() == "y":
        return list(range(1, items_count + 1))
    try:
        picked = parse_selection(choice, items_count)
    except ValueError:
        return None
    if not picked:
        return None
    return picked


def load_gemini_api_key(path: Path) -> str:
    if GEN_API_KEY:
        return GEN_API_KEY
    data = load_ai_config(path)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"AI 配置缺少 api_key: {path}")
    return api_key


def resolve_view_create_result_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (VIEW_CREATE_RESULT_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到视图创建结果文件: {value}")
    p = latest_file(VIEW_CREATE_RESULT_DIR, "view_create_result_*.json")
    if not p:
        raise FileNotFoundError(f"未找到视图创建结果文件（目录: {VIEW_CREATE_RESULT_DIR}）")
    return p.resolve()


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Gemini 返回为空")
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
    raise ValueError(f"Gemini 未返回可解析 JSON:\n{text}")


def load_app_auth_rows() -> List[dict]:
    rows: List[dict] = []
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload = data.get("data")
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            app_id = str(row.get("appId", "")).strip()
            app_key = str(row.get("appKey", "")).strip()
            sign = str(row.get("sign", "")).strip()
            if not app_id or not app_key or not sign:
                continue
            rows.append(dict(row))
    if not rows:
        raise FileNotFoundError(f"未找到可用授权文件：{APP_AUTH_DIR}")
    dedup: Dict[str, dict] = {}
    for r in rows:
        app_id = str(r.get("appId", "")).strip()
        if app_id not in dedup:
            dedup[app_id] = r
    return list(dedup.values())


def fetch_app_meta(app_key: str, sign: str) -> dict:
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json, text/plain, */*"}
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app = data.get("data", {})
    if not isinstance(app, dict):
        raise RuntimeError(f"应用信息格式错误: {data}")
    return app


def fetch_worksheets(app_key: str, sign: str) -> List[dict]:
    app_meta = fetch_app_meta(app_key, sign)
    worksheets: List[dict] = []

    def walk_sections(section: dict):
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append({"workSheetId": str(item.get("id", "")), "workSheetName": str(item.get("name", ""))})
        for child in section.get("childSections", []) or []:
            walk_sections(child)

    for sec in app_meta.get("sections", []) or []:
        walk_sections(sec)
    return worksheets


def fetch_controls(worksheet_id: str, auth_config_path: Path) -> dict:
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
    if not isinstance(controls, list):
        raise RuntimeError(f"工作表控件格式错误: worksheetId={worksheet_id}, resp={data}")
    return {"fields": controls}


def load_view_targets(path: Path, wanted_app_ids: Optional[set[str]] = None) -> Dict[str, Dict[str, List[dict]]]:
    data = load_json(path)
    apps = data.get("apps")
    if not isinstance(apps, list):
        raise ValueError(f"视图创建结果文件缺少 apps 列表: {path}")
    out: Dict[str, Dict[str, List[dict]]] = {}
    for app in apps:
        if not isinstance(app, dict):
            continue
        app_id = str(app.get("appId", "")).strip()
        if not app_id:
            continue
        if wanted_app_ids and app_id not in wanted_app_ids:
            continue
        ws_map: Dict[str, List[dict]] = {}
        for ws in app.get("worksheets", []) if isinstance(app.get("worksheets"), list) else []:
            if not isinstance(ws, dict):
                continue
            ws_id = str(ws.get("worksheetId", "")).strip()
            if not ws_id:
                continue
            targets: List[dict] = []
            for view in ws.get("views", []) if isinstance(ws.get("views"), list) else []:
                if not isinstance(view, dict):
                    continue
                view_id = str(view.get("createdViewId", "")).strip()
                view_type = str(view.get("viewType", "")).strip()
                if not view_id or view_type not in SUPPORTED_VIEW_TYPES:
                    continue
                view_name = str(view.get("name", "")).strip()
                if not view_name and isinstance(view.get("createPayload"), dict):
                    view_name = str(view["createPayload"].get("name", "")).strip()
                targets.append(
                    {
                        "viewId": view_id,
                        "viewName": view_name,
                        "viewType": view_type,
                        "viewTypeName": VIEW_TYPE_LABELS.get(view_type, view_type),
                    }
                )
            if targets:
                ws_map[ws_id] = targets
        if ws_map:
            out[app_id] = ws_map
    return out


def simplify_field(field: dict) -> dict:
    ftype = field.get("type")
    subtype = field.get("subType")
    options = field.get("options")
    option_count = len(options) if isinstance(options, list) else 0
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
        "optionCount": option_count,
        "isDropdown": is_dropdown,
    }


def build_prompt(app_name: str, worksheet_name: str, worksheet_id: str, target_views: List[dict], fields: List[dict]) -> str:
    return f"""
你是明道云视图配置专家。请分析该工作表中支持的视图，是否需要配置：
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
      "reason": "原因"
    }}
  ]
}}

规则：
1) 仅针对输入中的目标视图输出。
2) controlId 必须来自字段列表。
3) 只有 表格视图(type=0) 和 画廊视图(type=3) 允许配置 navGroup。
4) navGroup（筛选列表）只能使用“下拉字段”（SingleSelect/MultipleSelect）。
5) 若存在多个下拉字段，优先选择业务管理意义最强的那个（如状态/类型/分类/等级/阶段等）。
6) 仅表格/看板/画廊视图允许配置 fastFilters；日历视图不要配置。
7) 若不需要某功能，对应 needXxx=false，数组留空。
8) fastFilters 建议 1-4 个。
9) 输出必须为合法 JSON。
""".strip()


def build_batch_filter_prompt(app_name: str, worksheets_data: List[dict]) -> str:
    """一次 Prompt 规划所有工作表视图筛选。worksheets_data: [{worksheetId, worksheetName, targetViews, fields}]"""
    count = len(worksheets_data)
    ws_section = json.dumps(worksheets_data, ensure_ascii=False, indent=2)
    return f"""你是明道云视图配置专家。请分析以下 {count} 个工作表中支持的视图，是否需要配置筛选列表和快速筛选。

应用：{app_name}
工作表列表：
{ws_section}

只输出 JSON：
{{
  "worksheets": [
    {{
      "worksheetId": "工作表ID",
      "viewPlans": [
        {{
          "viewId": "视图ID",
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
          "reason": "原因"
        }}
      ]
    }}
  ]
}}

规则：
1) 仅针对每个工作表 targetViews 中的视图输出 viewPlans。
2) controlId 必须来自对应工作表的 fields 列表。
3) 只有 表格视图(type=0) 和 画廊视图(type=3) 允许配置 navGroup。
4) navGroup（筛选列表）只能使用"下拉字段"（isDropdown=true）。
5) 若存在多个下拉字段，优先选择业务管理意义最强的（如状态/类型/分类/等级/阶段等）。
6) 仅表格/看板/画廊视图允许配置 fastFilters；日历视图不要配置。
7) 若不需要某功能，对应 needXxx=false，数组留空。
8) fastFilters 建议 1-4 个。
9) 输出必须为合法 JSON，worksheets 数组长度必须等于 {count}。""".strip()


def generate_with_retry(client, model: str, prompt: str, retries: int, ai_config: dict) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=create_generation_config(
                    ai_config,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= max(1, retries):
                break
            wait_seconds = min(8, 2 ** (attempt - 1))
            print(f"  Gemini 调用失败，第 {attempt} 次重试前等待 {wait_seconds}s：{exc}")
            time.sleep(wait_seconds)
    assert last_exc is not None
    raise last_exc


def pick_best_dropdown_field(fields: List[dict]) -> str:
    """
    选“最有业务管理意义”的下拉字段。
    """
    keywords = ("状态", "类型", "分类", "等级", "阶段", "级别", "优先级", "标签", "归属")
    best_id = ""
    best_score = -10**9
    for f in fields:
        if not isinstance(f, dict):
            continue
        if not bool(f.get("isDropdown", False)):
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
        if isinstance(f.get("optionCount"), int):
            oc = int(f["optionCount"])
            if 2 <= oc <= 20:
                score += 2
        for kw in keywords:
            if kw in name:
                score += 8
                break
        if score > best_score:
            best_score = score
            best_id = fid
    return best_id


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

    def norm_control_id(cid: str) -> str:
        x = str(cid or "").strip()
        return x if x in field_map else ""

    need_nav = bool(item.get("needNavGroup", False))
    nav_group_raw = item.get("navGroup")
    nav_group = []
    best_dropdown_id = pick_best_dropdown_field(fields)
    if isinstance(nav_group_raw, list):
        for g in nav_group_raw:
            if not isinstance(g, dict):
                continue
            cid = norm_control_id(g.get("controlId", ""))
            if not cid:
                continue
            # 筛选列表强约束：必须是下拉字段
            if not bool(field_map.get(cid, {}).get("isDropdown", False)):
                continue
            out = {"controlId": cid}
            if "dataType" in g and isinstance(g.get("dataType"), int):
                out["dataType"] = int(g["dataType"])
            else:
                dt = field_map[cid].get("type")
                if isinstance(dt, int):
                    out["dataType"] = dt
            out["isAsc"] = bool(g.get("isAsc", True))
            if "navshow" in g:
                out["navshow"] = str(g.get("navshow", "0"))
            nav_group.append(out)
    # 若 Gemini 没给或给错（非下拉），自动兜底一个最优下拉字段
    if need_nav and view_type in NAV_SUPPORTED_VIEW_TYPES and not nav_group and best_dropdown_id:
        fallback = {"controlId": best_dropdown_id, "isAsc": True, "navshow": "0"}
        dt = field_map[best_dropdown_id].get("type")
        if isinstance(dt, int):
            fallback["dataType"] = dt
        nav_group = [fallback]
    reason = str(item.get("reason", "")).strip()
    if view_type not in NAV_SUPPORTED_VIEW_TYPES:
        need_nav = False
        nav_group = []
        reason = (reason + f"；{VIEW_TYPE_LABELS.get(view_type, view_type)}不支持筛选列表").strip("；")
    elif not best_dropdown_id:
        need_nav = False
        nav_group = []
        reason = (reason + "；无可用下拉字段，已禁用筛选列表").strip("；")

    nav_adv = item.get("navAdvancedSetting") if isinstance(item.get("navAdvancedSetting"), dict) else {}
    nav_edit_keys = item.get("navEditAdKeys") if isinstance(item.get("navEditAdKeys"), list) else []
    nav_edit_keys = [str(x).strip() for x in nav_edit_keys if str(x).strip()]

    need_fast = bool(item.get("needFastFilters", False))
    fast_raw = item.get("fastFilters")
    fast_filters = []
    if isinstance(fast_raw, list):
        for f in fast_raw:
            if not isinstance(f, dict):
                continue
            cid = norm_control_id(f.get("controlId", ""))
            if not cid:
                continue
            out = {"controlId": cid}
            dt = f.get("dataType")
            if isinstance(dt, int):
                out["dataType"] = dt
            else:
                mapped = field_map[cid].get("type")
                if isinstance(mapped, int):
                    out["dataType"] = mapped
            if "filterType" in f:
                try:
                    out["filterType"] = int(f.get("filterType"))
                except Exception:
                    pass
            if isinstance(f.get("advancedSetting"), dict):
                out["advancedSetting"] = f["advancedSetting"]
            fast_filters.append(out)
    if view_type not in FAST_SUPPORTED_VIEW_TYPES:
        need_fast = False
        fast_filters = []
        reason = (reason + f"；{VIEW_TYPE_LABELS.get(view_type, view_type)}不支持快速筛选").strip("；")
    elif need_fast and not fast_filters:
        need_fast = False
        reason = (reason + "；无有效快速筛选字段，已禁用快速筛选").strip("；")

    fast_adv = item.get("fastAdvancedSetting") if isinstance(item.get("fastAdvancedSetting"), dict) else {}
    fast_edit_keys = item.get("fastEditAdKeys") if isinstance(item.get("fastEditAdKeys"), list) else []
    fast_edit_keys = [str(x).strip() for x in fast_edit_keys if str(x).strip()]

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
        "reason": reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="规划视图的筛选列表与快速筛选")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--view-create-result", default="", help="视图创建结果 JSON 路径（默认取最新）")
    parser.add_argument("--app-ids", default="", help="可选，应用ID列表（逗号分隔）；不传则交互选择")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    parser.add_argument("--gemini-retries", type=int, default=DEFAULT_GEMINI_RETRIES, help="Gemini 请求失败时的重试次数")
    args = parser.parse_args()

    load_gemini_api_key(Path(args.config).expanduser().resolve())
    ai_config = load_ai_config(Path(args.config).expanduser().resolve())
    client = get_ai_client(ai_config)
    auth_config_path = Path(args.auth_config).expanduser().resolve()

    app_rows = load_app_auth_rows()
    apps = []
    for r in app_rows:
        app_id = str(r.get("appId", "")).strip()
        app_key = str(r.get("appKey", "")).strip()
        sign = str(r.get("sign", "")).strip()
        app_name = str(r.get("name", "")).strip() or app_id
        if not app_id or not app_key or not sign:
            continue
        try:
            meta = fetch_app_meta(app_key, sign)
            app_name = str(meta.get("name", "")).strip() or app_name
        except Exception:
            pass
        apps.append({"appId": app_id, "appName": app_name, "appKey": app_key, "sign": sign})
    if not apps:
        raise RuntimeError("没有可用应用")

    picked_apps = []
    app_ids_arg = str(args.app_ids or "").strip()
    if app_ids_arg:
        wanted = {x.strip() for x in app_ids_arg.split(",") if x.strip()}
        picked_apps = [a for a in apps if a["appId"] in wanted]
        if not picked_apps:
            raise ValueError(f"--app-ids 未匹配到应用: {app_ids_arg}")
    else:
        print("可选应用：")
        print("序号 | 应用名称 | 应用ID")
        for i, app in enumerate(apps, start=1):
            print(f"{i}. {app['appName']} | {app['appId']}")
        picked = choose_indexes("请选择应用：输入 y=全部；输入序号(如1,2,3)；任意键取消: ", len(apps))
        if not picked:
            print("已取消。")
            return
        picked_apps = [apps[i - 1] for i in picked]

    wanted_app_ids = {app["appId"] for app in picked_apps}
    view_create_result_path = resolve_view_create_result_json(args.view_create_result.strip())
    view_targets_by_app = load_view_targets(view_create_result_path, wanted_app_ids=wanted_app_ids)

    output_apps = []
    total_views = 0
    for app in picked_apps:
        print(f"\n处理应用: {app['appName']} ({app['appId']})")
        ws_list = fetch_worksheets(app["appKey"], app["sign"])
        app_out = {"appId": app["appId"], "appName": app["appName"], "worksheets": []}

        # 筛选出有目标视图的工作表，并行拉取字段
        ws_with_targets = [
            ws for ws in ws_list
            if view_targets_by_app.get(app["appId"], {}).get(ws["workSheetId"])
        ]
        if not ws_with_targets:
            output_apps.append(app_out)
            continue

        def _fetch_controls(ws):
            detail = fetch_controls(ws["workSheetId"], auth_config_path)
            return ws, [simplify_field(f) for f in detail.get("fields", []) if isinstance(f, dict)]

        with ThreadPoolExecutor(max_workers=min(8, len(ws_with_targets))) as ex:
            ws_fields_pairs = list(ex.map(_fetch_controls, ws_with_targets))

        # 组装批量 Prompt 数据
        worksheets_batch = []
        ws_meta = {}  # ws_id -> (fields, field_map, views_by_id, target_views)
        for ws, fields in ws_fields_pairs:
            ws_id = ws["workSheetId"]
            target_views = view_targets_by_app[app["appId"]][ws_id]
            field_map = {str(f.get("id", "")).strip(): f for f in fields if str(f.get("id", "")).strip()}
            views_by_id = {str(v.get("viewId", "")).strip(): v for v in target_views}
            ws_meta[ws_id] = (fields, field_map, views_by_id, target_views)
            worksheets_batch.append({
                "worksheetId": ws_id,
                "worksheetName": ws["workSheetName"],
                "targetViews": target_views,
                "fields": fields,
            })
            total_views += len(target_views)
            print(f"- {ws['workSheetName']}：目标视图 {len(target_views)} 个")

        # 一次 Gemini 批量调用
        print(f"  调用 Gemini 批量规划 {len(worksheets_batch)} 个工作表筛选...")
        batch_prompt = build_batch_filter_prompt(app["appName"], worksheets_batch)
        resp = generate_with_retry(client, args.model, batch_prompt, args.gemini_retries, ai_config)
        parsed = extract_json(resp.text or "")

        # 解析批量结果
        ws_plans_map: Dict[str, List] = {}
        for ws_item in parsed.get("worksheets", []):
            if not isinstance(ws_item, dict):
                continue
            ws_id = str(ws_item.get("worksheetId", "")).strip()
            if ws_id:
                ws_plans_map[ws_id] = ws_item.get("viewPlans", [])

        # 逐工作表 normalize 并写入结果
        for ws_data in worksheets_batch:
            ws_id = ws_data["worksheetId"]
            ws_name = ws_data["worksheetName"]
            fields, field_map, views_by_id, target_views = ws_meta[ws_id]
            view_plans_raw = ws_plans_map.get(ws_id, [])
            view_plans = []
            for item in view_plans_raw:
                norm = normalize_view_plan(item, field_map, fields, views_by_id)
                if norm:
                    view_plans.append(norm)
            for vid, v in views_by_id.items():
                if not any(p.get("viewId") == vid for p in view_plans):
                    view_plans.append({
                        "viewId": vid,
                        "viewName": v.get("viewName", ""),
                        "viewType": v.get("viewType", ""),
                        "needNavGroup": False,
                        "navGroup": [],
                        "navAdvancedSetting": {},
                        "navEditAdKeys": [],
                        "needFastFilters": False,
                        "fastFilters": [],
                        "fastAdvancedSetting": {"enablebtn": "0"},
                        "fastEditAdKeys": ["enablebtn"],
                        "reason": "Gemini 未返回该视图，默认不改",
                    })
            app_out["worksheets"].append({
                "worksheetId": ws_id,
                "worksheetName": ws_name,
                "targetViews": target_views,
                "viewPlans": view_plans,
            })
        output_apps.append(app_out)

    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "source": "view_filter_plan_gemini_v2",
        "viewCreateResultJson": str(view_create_result_path),
        "apps": output_apps,
        "summary": {"appCount": len(output_apps), "viewCount": total_views},
    }
    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = (PLAN_DIR / f"tableview_filter_plan_{now_ts()}.json").resolve()
    write_json(out_path, payload)

    print(f"\n规划完成: {out_path}")
    print(f"- 应用数: {payload['summary']['appCount']}")
    print(f"- 目标视图数: {payload['summary']['viewCount']}")


if __name__ == "__main__":
    main()
