#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 造数共享工具。
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from ai_utils import AI_CONFIG_PATH, load_ai_config

import auth_retry
from utils import now_ts, now_iso, latest_file, load_json, write_json, write_json_with_latest

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
MOCK_APP_INVENTORY_DIR = OUTPUT_ROOT / "mock_data_app_inventory"
MOCK_SCHEMA_DIR = OUTPUT_ROOT / "mock_data_schema_snapshots"
MOCK_PLAN_DIR = OUTPUT_ROOT / "mock_data_plans"
MOCK_BUNDLE_DIR = OUTPUT_ROOT / "mock_data_bundles"
MOCK_WRITE_RESULT_DIR = OUTPUT_ROOT / "mock_data_write_results"
MOCK_RELATION_PLAN_DIR = OUTPUT_ROOT / "mock_relation_plans"
MOCK_RELATION_APPLY_DIR = OUTPUT_ROOT / "mock_relation_apply_results"
MOCK_RELATION_REPAIR_PLAN_DIR = OUTPUT_ROOT / "mock_relation_repair_plans"
MOCK_RELATION_REPAIR_APPLY_DIR = OUTPUT_ROOT / "mock_relation_repair_apply_results"
MOCK_UNRESOLVED_DELETE_DIR = OUTPUT_ROOT / "mock_unresolved_delete_results"
APP_RECORD_CLEAR_DIR = OUTPUT_ROOT / "app_record_clear_results"
MOCK_RUN_DIR = OUTPUT_ROOT / "mock_data_runs"
MOCK_LOG_DIR = OUTPUT_ROOT / "mock_data_logs"
WORKSHEET_LAYOUT_APPLY_DIR = OUTPUT_ROOT / "worksheet_layout_apply_results"
GEMINI_CONFIG_PATH = AI_CONFIG_PATH
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
DEFAULT_BASE_URL = "https://api.mingdao.com"
APP_INFO_URL = "/v3/app"
WORKSHEET_DETAIL_URL = "/v3/app/worksheets/{worksheet_id}"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
ADD_WORKSHEET_ROW_URL = "https://www.mingdao.com/api/Worksheet/AddWorksheetRow"
ROW_LIST_URL = "/v3/app/worksheets/{worksheet_id}/rows/list"
ROW_CREATE_URL = "/v3/app/worksheets/{worksheet_id}/rows"
ROW_BATCH_CREATE_URL = "/v3/app/worksheets/{worksheet_id}/rows/batch"
ROW_BATCH_DELETE_URL = "/v3/app/worksheets/{worksheet_id}/rows/batch"
ROW_UPDATE_URL = "/v3/app/worksheets/{worksheet_id}/rows/{row_id}"

SUPPORTED_WRITABLE_FIELD_TYPES = {
    "Text",
    "Number",
    "Currency",      # type=8 金额，API 接受数值
    "Date",
    "DateTime",
    "SingleSelect",
    "MultipleSelect",
    "Dropdown",      # type=11 下拉单选，等同于 SingleSelect，有 options
    "Checkbox",
    "Rating",
    "Location",
    "PhoneNumber",
    "Email",
    "Textarea",
    "RichText",      # type=41 富文本，API 接受纯文本或 HTML
    "Link",
    "Region",        # type=24 地区（省市区），API 接受地区 ID 或文本
}

KNOWN_COMPLEX_FIELD_TYPES = {
    "Attachment",
    "SubTable",
    "Relation",
    "Collaborator",
    "Department",
    "OrgRole",
    "Lookup",
    "Formula",
    "Summary",
    "Rollup",        # 汇总字段（只读）
    "AutoNumber",
    "Concatenate",   # 文本组合（只读）
    "DateFormula",   # 日期公式（只读）
    "Signature",     # 签名字段（需特殊处理）
    "AreaCity",
    "AreaProvince",
    "AreaCounty",
}

KNOWN_SYSTEM_FIELD_IDS = {
    "rowid",
    "ctime",
    "utime",
    "caid",
    "uaid",
    "ownerid",
    "wfcuaids",
    "wfname",
    "wfctime",
    "wfrtime",
    "wfcotime",
    "wfdtime",
    "wfstatus",    # 流程状态（工作流系统字段）
    "wfftime",     # 剩余时间（工作流系统字段）
    "autoid",
}

KNOWN_SYSTEM_FIELD_ALIASES = {
    "rowId",
    "_createdAt",
    "_updatedAt",
    "_createBy",
    "_updatedBy",
    "_owner",
    "_processName",
    "_processStatus",   # 流程状态
    "_initiatedAt",
    "_nodeStartedAt",
    "_completedAt",
    "_dueAt",
    "_remainingTime",   # 剩余时间
}

CONTROL_TYPE_MAP = {
    2: "Text",
    3: "Textarea",
    4: "Number",
    5: "Number",
    6: "Number",
    9: "SingleSelect",
    10: "MultipleSelect",
    11: "SingleSelect",
    14: "Attachment",
    16: "DateTime",
    15: "Date",
    19: "Location",
    21: "Link",
    23: "Email",
    24: "PhoneNumber",
    26: "Collaborator",
    29: "Relation",
    36: "Checkbox",
    37: "Rating",
}


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "item"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_log_path(prefix: str, app_id: str = "") -> Path:
    ensure_dir(MOCK_LOG_DIR)
    safe_app = sanitize_name(app_id) if app_id else "general"
    return (MOCK_LOG_DIR / f"{prefix}_{safe_app}_{now_ts()}.jsonl").resolve()


def append_log(log_path: Path, event: str, **payload: Any) -> None:
    record = {
        "ts": now_iso(),
        "event": event,
        **payload,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_gemini_api_key(config_path: Path = GEMINI_CONFIG_PATH) -> str:
    data = load_ai_config(config_path)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"AI 配置缺少 api_key: {config_path}")
    return api_key


from auth_retry import load_web_auth  # re-exported for backward compatibility


def extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("返回内容为空")

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
    raise ValueError(f"未解析到 JSON 对象:\n{text}")


def resolve_json_input(value: str, search_dirs: List[Path], default_pattern: str = "") -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        for base_dir in search_dirs:
            candidate = (base_dir / value).resolve()
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"找不到文件: {value}")

    if default_pattern:
        for base_dir in search_dirs:
            found = latest_file(base_dir, default_pattern)
            if found:
                return found.resolve()
    raise FileNotFoundError(f"未找到匹配文件: {default_pattern}")


def build_headers(app_key: str, sign: str) -> dict:
    return {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
    }


_TRANSIENT_PATTERNS = ("429", "503", "rate limit", "too many", "频率", "限流", "throttl")


def call_with_backoff(fn: Callable, *args, max_retries: int = 5, **kwargs):
    """
    带指数退避 + jitter 的重试包装。
    - 网络错误（ConnectionError / Timeout）：无条件重试
    - RuntimeError：仅当消息中含限流特征词时重试，其余直接抛出
    退避时间：2^attempt + random(0,1) 秒，最多重试 max_retries 次。
    """
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            if attempt == max_retries - 1:
                raise
            wait = (2 ** attempt) + random.uniform(0, 2 ** attempt)
            print(f"\n[退避] 网络错误，第{attempt + 1}次重试，等待 {wait:.1f}s: {exc}", flush=True)
            time.sleep(wait)
        except RuntimeError as exc:
            msg = str(exc).lower()
            if not any(p in msg for p in _TRANSIENT_PATTERNS) or attempt == max_retries - 1:
                raise
            wait = (2 ** attempt) + random.uniform(0, 2 ** attempt)
            print(f"\n[退避] 限流错误，第{attempt + 1}次重试，等待 {wait:.1f}s", flush=True)
            time.sleep(wait)


def request_json(method: str, url: str, headers: dict, payload: Optional[dict] = None, timeout: int = 30) -> dict:
    resp = requests.request(method=method, url=url, headers=headers, json=payload, timeout=timeout)
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"接口返回非 JSON: status={resp.status_code}, body={resp.text[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"接口返回格式错误: {data}")
    
    # 特殊处理：HAP v3 批量删除接口 (DELETE) 有时会返回 success: False, error_code: 0, error_msg: '成功'
    # 但实际上删除是成功的。
    is_delete = method.upper() == "DELETE"
    is_weird_success = (
        not data.get("success") and 
        data.get("error_code") == 0 and 
        data.get("error_msg") == "成功"
    )
    
    if not data.get("success") and not (is_delete and is_weird_success):
        raise RuntimeError(f"接口调用失败: {data}")
    return data


def build_web_headers(account_id: str, authorization: str, cookie: str, app_id: str, worksheet_id: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.mingdao.com",
        "Referer": f"https://www.mingdao.com/app/{app_id}/{worksheet_id}",
    }


def load_app_auth_rows() -> List[dict]:
    rows: List[dict] = []
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = load_json(path)
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
            item = dict(row)
            item["_auth_path"] = str(path.resolve())
            rows.append(item)
    dedup: Dict[str, dict] = {}
    for row in rows:
        app_id = str(row.get("appId", "")).strip()
        if app_id not in dedup:
            dedup[app_id] = row
    return list(dedup.values())


def fetch_app_meta(base_url: str, app_key: str, sign: str) -> dict:
    url = base_url.rstrip("/") + APP_INFO_URL
    data = request_json("GET", url, build_headers(app_key, sign), payload=None)
    app = data.get("data", {})
    if not isinstance(app, dict):
        raise RuntimeError(f"应用信息格式错误: {data}")
    return app


def discover_authorized_apps(base_url: str = DEFAULT_BASE_URL) -> List[dict]:
    apps: List[dict] = []
    for row in load_app_auth_rows():
        app_id = str(row.get("appId", "")).strip()
        app_key = str(row.get("appKey", "")).strip()
        sign = str(row.get("sign", "")).strip()
        app_name = app_id
        try:
            app_meta = fetch_app_meta(base_url, app_key, sign)
            app_name = str(app_meta.get("name", "")).strip() or app_id
        except Exception:
            pass
        apps.append(
            {
                "index": len(apps) + 1,
                "appId": app_id,
                "appName": app_name,
                "appKey": app_key,
                "sign": sign,
                "authFile": Path(str(row.get("_auth_path", ""))).name,
                "authPath": str(row.get("_auth_path", "")),
                "createTime": str(row.get("createTime", "")).strip(),
            }
        )
    return apps


def print_app_choices(apps: List[dict]) -> None:
    print("\n可用应用列表：")
    print("序号 | 应用名称 | appId | 授权文件")
    print("-" * 120)
    for app in apps:
        print(f"{app['index']:>4} | {app['appName']} | {app['appId']} | {app['authFile']}")


def choose_app(apps: List[dict], app_id: str = "", app_index: int = 0) -> dict:
    if not apps:
        raise RuntimeError(f"未发现可用应用授权文件: {APP_AUTH_DIR}")
    if app_id:
        for app in apps:
            if app["appId"] == app_id:
                return app
        raise ValueError(f"未找到 appId={app_id}")
    if app_index > 0:
        for app in apps:
            if int(app["index"]) == app_index:
                return app
        raise ValueError(f"未找到序号={app_index}")
    print_app_choices(apps)
    while True:
        raw = input("\n请输入要执行的应用序号: ").strip()
        if raw.isdigit():
            idx = int(raw)
            for app in apps:
                if int(app["index"]) == idx:
                    return app
        print("输入无效，请重新输入数字序号。")


def walk_sections_collect_worksheets(section: dict, out: List[dict]) -> None:
    section_id = str(section.get("id", "")).strip()
    section_name = str(section.get("name", "")).strip()
    for item in section.get("items", []) or []:
        if item.get("type") != 0:
            continue
        out.append(
            {
                "worksheetId": str(item.get("id", "")).strip(),
                "worksheetName": str(item.get("name", "")).strip(),
                "appSectionId": section_id,
                "appSectionName": section_name,
            }
        )
    for child in section.get("childSections", []) or []:
        walk_sections_collect_worksheets(child, out)


def fetch_app_worksheets(base_url: str, app_key: str, sign: str) -> Tuple[dict, List[dict]]:
    app_meta = fetch_app_meta(base_url, app_key, sign)
    worksheets: List[dict] = []
    for section in app_meta.get("sections", []) or []:
        if isinstance(section, dict):
            walk_sections_collect_worksheets(section, worksheets)
    return app_meta, worksheets


def fetch_worksheet_controls(worksheet_id: str, web_auth: tuple[str, str, str], auth_config_path: Path = AUTH_CONFIG_PATH) -> dict:
    resp = auth_retry.hap_web_post(
        GET_CONTROLS_URL,
        auth_config_path,
        referer=f"https://www.mingdao.com/worksheet/field/edit?sourceId={worksheet_id}",
        json={"worksheetId": worksheet_id},
        timeout=30,
    )
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"工作表控件返回非 JSON: status={resp.status_code}, body={resp.text[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"工作表控件返回格式错误: {data}")
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
    return payload


def fetch_worksheet_detail_v3(base_url: str, app_key: str, sign: str, worksheet_id: str) -> dict:
    url = base_url.rstrip("/") + WORKSHEET_DETAIL_URL.format(worksheet_id=worksheet_id)
    data = request_json("GET", url, build_headers(app_key, sign), payload=None)
    detail = data.get("data", {})
    if not isinstance(detail, dict):
        raise RuntimeError(f"V3 工作表结构格式错误: worksheetId={worksheet_id}, resp={data}")
    fields = detail.get("fields", [])
    if not isinstance(fields, list):
        raise RuntimeError(f"V3 工作表结构缺少 fields: worksheetId={worksheet_id}, resp={data}")
    return detail


def load_layout_controls_from_artifacts(worksheet_ids: List[str]) -> Tuple[Dict[str, List[dict]], List[str]]:
    pending = {str(item).strip() for item in worksheet_ids if str(item).strip()}
    controls_by_ws: Dict[str, List[dict]] = {}
    source_paths: List[str] = []
    files = sorted(WORKSHEET_LAYOUT_APPLY_DIR.glob("worksheet_layout_apply_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        if not pending:
            break
        try:
            data = load_json(path)
        except Exception:
            continue
        found_in_file = False
        for item in data.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            worksheet_id = str(item.get("workSheetId", "")).strip()
            if worksheet_id not in pending:
                continue
            controls = (
                item.get("response", {})
                .get("data", {})
                .get("data", {})
                .get("controls", [])
            )
            if not isinstance(controls, list) or not controls:
                continue
            controls_by_ws[worksheet_id] = controls
            pending.discard(worksheet_id)
            found_in_file = True
        if found_in_file:
            source_paths.append(str(path.resolve()))
    return controls_by_ws, source_paths


def simplify_options(raw_options: Any) -> List[dict]:
    out: List[dict] = []
    if not isinstance(raw_options, list):
        return out
    for item in raw_options:
        if not isinstance(item, dict):
            continue
        if item.get("isDeleted", False):
            continue
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key and not value:
            continue
        out.append({"key": key, "value": value})
    return out


def normalize_field_type(field: dict) -> str:
    raw_type = field.get("type")
    if isinstance(raw_type, int):
        return CONTROL_TYPE_MAP.get(raw_type, str(raw_type))
    ftype = str(raw_type or "").strip()
    if ftype:
        if ftype.isdigit():
            return CONTROL_TYPE_MAP.get(int(ftype), ftype)
        return ftype
    control_type = str(field.get("controlType", "")).strip()
    if control_type.isdigit():
        return CONTROL_TYPE_MAP.get(int(control_type), control_type)
    return control_type or "Unknown"


def classify_skipped_field(field: dict) -> Optional[str]:
    field_type = normalize_field_type(field)
    field_id = str(field.get("fieldId", "") or field.get("id", "")).strip()
    alias = str(field.get("alias", "")).strip()
    if bool(field.get("isSystemControl", False)) or bool(field.get("isSystem", False)):
        return "system_field"
    if field_id in KNOWN_SYSTEM_FIELD_IDS or alias in KNOWN_SYSTEM_FIELD_ALIASES:
        return "system_field"
    if field_type == "Relation":
        return "relation_field"
    if field_type in KNOWN_COMPLEX_FIELD_TYPES:
        return "complex_field"
    if field_type not in SUPPORTED_WRITABLE_FIELD_TYPES:
        return "unsupported_type"
    if field_type in {"SingleSelect", "MultipleSelect"} and not simplify_options(field.get("options")):
        return "missing_options"
    return None


def simplify_field(field: dict) -> dict:
    relation = field.get("relation")
    relation_bidirectional = False
    if isinstance(relation, dict):
        relation_bidirectional = bool(relation.get("bidirectional", False))
    field_id = str(field.get("id", "") or field.get("controlId", "")).strip()
    field_name = str(field.get("name", "") or field.get("controlName", "")).strip()
    alias = str(field.get("alias", "")).strip()
    field_type = normalize_field_type(field)
    subtype = int(field.get("subType", 0) or 0)
    if field_type == "Relation" and subtype == 0:
        try:
            enum_default = int(field.get("enumDefault", 0) or 0)
        except Exception:
            enum_default = 0
        if enum_default in (1, 2):
            subtype = enum_default
    raw_type = field.get("type")
    control_type = raw_type if isinstance(raw_type, int) else 0
    if not control_type:
        try:
            control_type = int(field.get("controlType", 0) or 0)
        except Exception:
            control_type = 0
    simplified = {
        "fieldId": field_id,
        "name": field_name,
        "alias": alias,
        "type": field_type,
        "controlType": control_type,
        "subType": subtype,
        "required": bool(field.get("required", False)),
        "isTitle": bool(field.get("isTitle", False)) or int(field.get("attribute", 0) or 0) == 1,
        "isSystem": bool(field.get("isSystemControl", False)),
        "dataSource": str(field.get("dataSource", "")).strip(),
        "sourceControl": str(field.get("sourceControl", "") or field.get("sourceControlId", "")).strip(),
        "relation": {"bidirectional": relation_bidirectional},
        "options": simplify_options(field.get("options")),
    }
    return simplified


def build_relation_edges(worksheets: List[dict]) -> List[dict]:
    id_to_name = {ws["worksheetId"]: ws["worksheetName"] for ws in worksheets}
    edges: List[dict] = []
    for worksheet in worksheets:
        for field in worksheet.get("fields", []):
            if field.get("type") != "Relation":
                continue
            target_id = str(field.get("dataSource", "")).strip()
            edges.append(
                {
                    "sourceWorksheetId": worksheet["worksheetId"],
                    "sourceWorksheetName": worksheet["worksheetName"],
                    "targetWorksheetId": target_id,
                    "targetWorksheetName": id_to_name.get(target_id, ""),
                    "fieldId": field["fieldId"],
                    "fieldName": field["name"],
                    "subType": int(field.get("subType", 0) or 0),
                    "bidirectional": bool(field.get("relation", {}).get("bidirectional", False)),
                }
            )
    return edges


def infer_relation_pairs(relation_edges: List[dict]) -> Tuple[List[dict], List[str]]:
    pair_map: Dict[Tuple[str, str], List[dict]] = {}
    warnings: List[str] = []
    for edge in relation_edges:
        src = str(edge.get("sourceWorksheetId", "")).strip()
        dst = str(edge.get("targetWorksheetId", "")).strip()
        if not src or not dst:
            warnings.append(f"检测到缺失 targetWorksheetId 的 Relation 字段: {edge}")
            continue
        pair_key = tuple(sorted((src, dst)))
        pair_map.setdefault(pair_key, []).append(edge)

    out: List[dict] = []
    for pair_key, edges in pair_map.items():
        names = {edge["sourceWorksheetId"]: edge["sourceWorksheetName"] for edge in edges}
        names.update({edge["targetWorksheetId"]: edge["targetWorksheetName"] for edge in edges})
        subtypes = sorted({int(edge.get("subType", 0) or 0) for edge in edges})
        pair_type = "ambiguous"
        if len(edges) >= 2 and subtypes == [1]:
            pair_type = "1-1"
        elif len(edges) >= 2 and 1 in subtypes and 2 in subtypes:
            pair_type = "1-N"
        elif len(edges) == 1 and subtypes == [1]:
            pair_type = "1-N"
        else:
            warnings.append(f"关系对判定为 ambiguous: {pair_key}, subTypes={subtypes}, edgeCount={len(edges)}")
        ws_a, ws_b = pair_key
        out.append(
            {
                "worksheetAId": ws_a,
                "worksheetAName": names.get(ws_a, ""),
                "worksheetBId": ws_b,
                "worksheetBName": names.get(ws_b, ""),
                "pairType": pair_type,
                "edgeCount": len(edges),
                "subTypes": subtypes,
                "edges": edges,
            }
        )
    out.sort(key=lambda item: (item["worksheetAName"], item["worksheetBName"]))
    return out, warnings


def compute_worksheet_tiers(worksheets: List[dict], relation_pairs: List[dict], relation_edges: List[dict]) -> List[dict]:
    by_ws: Dict[str, List[dict]] = {ws["worksheetId"]: [] for ws in worksheets}
    outgoing_edge_subtypes: Dict[str, List[int]] = {ws["worksheetId"]: [] for ws in worksheets}
    for pair in relation_pairs:
        pair_type = str(pair.get("pairType", "")).strip()
        for key in ("worksheetAId", "worksheetBId"):
            ws_id = str(pair.get(key, "")).strip()
            if ws_id in by_ws:
                by_ws[ws_id].append({"pairType": pair_type, "pair": pair})
        for edge in pair.get("edges", []) or []:
            if not isinstance(edge, dict):
                continue
            source_ws_id = str(edge.get("sourceWorksheetId", "")).strip()
            if source_ws_id in outgoing_edge_subtypes:
                outgoing_edge_subtypes[source_ws_id].append(int(edge.get("subType", 0) or 0))

    tiers: List[dict] = []
    for worksheet in worksheets:
        ws_id = worksheet["worksheetId"]
        matches = by_ws.get(ws_id, [])
        pair_types = [item["pairType"] for item in matches]
        self_edge_subtypes = outgoing_edge_subtypes.get(ws_id, [])
        if not matches:
            tier = 1
            record_count = 5
            reason = "该表与其他表不存在关联关系"
        elif (
            self_edge_subtypes
            and all(sub_type == 1 for sub_type in self_edge_subtypes)
            and any(pair_type == "1-N" for pair_type in pair_types)
        ):
            tier = 3
            record_count = 10
            reason = "该表自身仅通过单选 Relation 关联上级表，按明细端处理"
        else:
            tier = 2 if all(pair_type == "1-1" for pair_type in pair_types) else 1
            record_count = 5
            if any(sub_type == 2 for sub_type in self_edge_subtypes):
                reason = "该表存在聚合端 Relation 字段，按主表处理"
            elif all(pair_type == "1-1" for pair_type in pair_types):
                reason = "该表存在关联关系，且涉及的关系对均判定为 1-1"
            elif any(pair_type == "1-N" for pair_type in pair_types):
                reason = "该表参与 1-N 关系，但自身不是明细单选端，按主表处理"
            else:
                reason = "该表存在 ambiguous 关系，按主表处理"
        tiers.append(
            {
                "worksheetId": ws_id,
                "worksheetName": worksheet["worksheetName"],
                "tier": tier,
                "recordCount": record_count,
                "reason": reason,
                "pairTypes": pair_types,
                "selfRelationSubTypes": self_edge_subtypes,
            }
        )
    ws_meta = {item["worksheetId"]: item for item in tiers}
    incoming_count: Dict[str, int] = {item["worksheetId"]: 0 for item in tiers}
    outgoing_map: Dict[str, List[str]] = {item["worksheetId"]: [] for item in tiers}
    seen_edges: set[tuple[str, str]] = set()
    for edge in relation_edges:
        if not isinstance(edge, dict):
            continue
        if int(edge.get("subType", 0) or 0) != 1:
            continue
        source_ws_id = str(edge.get("sourceWorksheetId", "")).strip()
        target_ws_id = str(edge.get("targetWorksheetId", "")).strip()
        if not source_ws_id or not target_ws_id or source_ws_id == target_ws_id:
            continue
        if source_ws_id not in ws_meta or target_ws_id not in ws_meta:
            continue
        dep = (target_ws_id, source_ws_id)
        if dep in seen_edges:
            continue
        seen_edges.add(dep)
        outgoing_map[target_ws_id].append(source_ws_id)
        incoming_count[source_ws_id] += 1

    ordered_ids: List[str] = []
    ready = sorted(
        [ws_id for ws_id, cnt in incoming_count.items() if cnt == 0],
        key=lambda ws_id: (int(ws_meta[ws_id]["tier"]), ws_meta[ws_id]["worksheetName"]),
    )
    while ready:
        ws_id = ready.pop(0)
        ordered_ids.append(ws_id)
        for nxt in sorted(outgoing_map.get(ws_id, []), key=lambda item: (int(ws_meta[item]["tier"]), ws_meta[item]["worksheetName"])):
            incoming_count[nxt] -= 1
            if incoming_count[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=lambda item: (int(ws_meta[item]["tier"]), ws_meta[item]["worksheetName"]))

    if len(ordered_ids) != len(tiers):
        remaining = [ws_id for ws_id in ws_meta if ws_id not in ordered_ids]
        remaining.sort(key=lambda ws_id: (int(ws_meta[ws_id]["tier"]), ws_meta[ws_id]["worksheetName"]))
        ordered_ids.extend(remaining)

    for idx, ws_id in enumerate(ordered_ids, start=1):
        ws_meta[ws_id]["order"] = idx
    tiers = [ws_meta[ws_id] for ws_id in ordered_ids]
    return tiers


def build_schema_snapshot(base_url: str, app: dict) -> dict:
    app_meta, worksheet_refs = fetch_app_worksheets(base_url, app["appKey"], app["sign"])
    web_auth = load_web_auth()
    layout_controls_by_ws, layout_sources = load_layout_controls_from_artifacts([ref["worksheetId"] for ref in worksheet_refs])
    worksheets: List[dict] = []
    warnings: List[str] = []
    for ref in worksheet_refs:
        detail_source = "v3"
        try:
            detail = fetch_worksheet_detail_v3(base_url, app["appKey"], app["sign"], ref["worksheetId"])
            raw_fields = detail.get("fields", [])
        except Exception as exc_v3:
            try:
                detail = fetch_worksheet_controls(ref["worksheetId"], web_auth)
                raw_fields = detail.get("controls", [])
                detail_source = "web_controls"
                warnings.append(
                    f"worksheet={ref['worksheetName']} ({ref['worksheetId']}) 的 v3 结构读取失败，已回退到 Web controls"
                )
            except Exception as exc_web:
                detail_source = "layout_apply_artifact"
                fallback_controls = layout_controls_by_ws.get(ref["worksheetId"], [])
                if not fallback_controls:
                    raise RuntimeError(
                        f"获取工作表结构失败，且未找到可用兜底: worksheet={ref['worksheetName']} "
                        f"worksheetId={ref['worksheetId']} v3_error={exc_v3} web_error={exc_web}"
                    ) from exc_web
                detail = {"controls": fallback_controls}
                raw_fields = fallback_controls
                warnings.append(
                    f"worksheet={ref['worksheetName']} ({ref['worksheetId']}) 的 v3/Web 结构读取都失败，"
                    f"已回退到布局产物中的 controls 快照"
                )
        simplified_fields = [simplify_field(field) for field in raw_fields if isinstance(field, dict)]
        writable_fields = []
        skipped_fields = []
        for field in simplified_fields:
            skip_reason = classify_skipped_field(field)
            if skip_reason:
                skipped_fields.append(
                    {
                        "fieldId": field["fieldId"],
                        "name": field["name"],
                        "type": field["type"],
                        "reason": skip_reason,
                    }
                )
            else:
                writable_fields.append(field)
        worksheets.append(
            {
                "worksheetId": ref["worksheetId"],
                "worksheetName": ref["worksheetName"],
                "appSectionId": ref["appSectionId"],
                "appSectionName": ref["appSectionName"],
                "fields": simplified_fields,
                "writableFields": writable_fields,
                "skippedFields": skipped_fields,
                "detailSource": detail_source,
            }
        )

    relation_edges = build_relation_edges(worksheets)
    relation_pairs, relation_warnings = infer_relation_pairs(relation_edges)
    warnings.extend(relation_warnings)
    worksheet_tiers = compute_worksheet_tiers(worksheets, relation_pairs, relation_edges)
    tier_by_id = {item["worksheetId"]: item for item in worksheet_tiers}
    for worksheet in worksheets:
        tier_info = tier_by_id.get(worksheet["worksheetId"], {})
        worksheet["tier"] = int(tier_info.get("tier", 1) or 1)
        worksheet["recordCount"] = int(tier_info.get("recordCount", 5) or 5)
        worksheet["tierReason"] = str(tier_info.get("reason", "")).strip()

    return {
        "schemaVersion": "mock_data_schema_snapshot_v1",
        "generatedAt": now_iso(),
        "app": {
            "appId": app["appId"],
            "appName": str(app_meta.get("name", "")).strip() or app["appName"],
            "authPath": app["authPath"],
            "authFile": app["authFile"],
        },
        "worksheets": worksheets,
        "relationEdges": relation_edges,
        "relationPairs": relation_pairs,
        "worksheetTiers": worksheet_tiers,
        "layoutArtifactSources": layout_sources,
        "warnings": warnings,
    }


def make_output_path(output_dir: Path, prefix: str, app_id: str, suffix: str = "") -> Path:
    safe_suffix = f"_{sanitize_name(suffix)}" if suffix else ""
    return (output_dir / f"{prefix}_{app_id}{safe_suffix}_{now_ts()}.json").resolve()


def normalize_record_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


def build_batch_rows(records: List[dict]) -> List[dict]:
    rows: List[dict] = []
    for record in records:
        values = record.get("valuesByFieldId", {})
        if not isinstance(values, dict):
            raise ValueError(f"记录缺少 valuesByFieldId: {record}")
        fields = []
        for field_id, raw_value in values.items():
            value = normalize_record_value(raw_value)
            if value is None:
                continue
            fields.append({"id": str(field_id), "value": value})
        if not fields:
            raise ValueError(f"记录没有任何可写字段: {record}")
        rows.append({"fields": fields})
    return rows


def to_receive_control_value(field_meta: dict, value: Any) -> Any:
    field_type = str(field_meta.get("type", "")).strip()
    if field_type in {"SingleSelect", "MultipleSelect", "Dropdown"}:
        if isinstance(value, list):
            return json.dumps([str(item) for item in value], ensure_ascii=False)
        return json.dumps([str(value)], ensure_ascii=False)
    if field_type == "Relation":
        if isinstance(value, list):
            return json.dumps([{"sid": str(item)} for item in value], ensure_ascii=False)
        return json.dumps([{"sid": str(value)}], ensure_ascii=False)
    if field_type == "Location":
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return value
            except (json.JSONDecodeError, ValueError):
                pass
            return json.dumps({"address": value}, ensure_ascii=False)
        return json.dumps({"address": str(value)}, ensure_ascii=False)
    return value


def to_v3_field_value(field_meta: dict, value: Any) -> Any:
    if value is None:
        return None
    field_type = str(field_meta.get("type", "")).strip()
    if field_type == "Location":
        # V3 API 接受 JSON 字符串或 dict，统一转为 JSON 字符串
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return value  # 已经是合法 JSON 字符串
            except (json.JSONDecodeError, ValueError):
                pass
            return json.dumps({"address": value}, ensure_ascii=False)
        return json.dumps({"address": str(value)}, ensure_ascii=False)
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return value
    return value


def build_v3_fields(record: dict, field_meta_map: Dict[str, dict]) -> List[dict]:
    values = record.get("valuesByFieldId", {})
    if not isinstance(values, dict):
        raise ValueError(f"记录缺少 valuesByFieldId: {record}")
    fields = []
    for field_id, raw_value in values.items():
        field_id = str(field_id).strip()
        if not field_id:
            continue
        if field_id not in field_meta_map:
            print(f"[警告] 字段元数据缺失，已跳过该字段: fieldId={field_id}")
            continue
        value = to_v3_field_value(field_meta_map[field_id], raw_value)
        if value is None:
            continue
        fields.append({"id": field_id, "value": value})
    if not fields:
        raise ValueError(f"记录没有任何可写字段: {record}")
    return fields


def build_web_receive_controls(record: dict, field_meta_map: Dict[str, dict]) -> List[dict]:
    values = record.get("valuesByFieldId", {})
    if not isinstance(values, dict):
        raise ValueError(f"记录缺少 valuesByFieldId: {record}")
    receive_controls = []
    for field_id, raw_value in values.items():
        field_id = str(field_id).strip()
        if not field_id:
            continue
        field_meta = field_meta_map.get(field_id)
        if not field_meta:
            raise ValueError(f"字段元数据缺失: fieldId={field_id}")
        receive_controls.append(
            {
                "controlId": field_id,
                "controlName": str(field_meta.get("name", "")).strip(),
                "type": int(field_meta.get("controlType", 0) or 0) or field_meta.get("type"),
                "value": to_receive_control_value(field_meta, raw_value),
            }
        )
    if not receive_controls:
        raise ValueError(f"记录没有任何可写字段: {record}")
    return receive_controls


def add_worksheet_row_web(
    account_id: str,
    authorization: str,
    cookie: str,
    app_id: str,
    worksheet_id: str,
    record: dict,
    field_meta_map: Dict[str, dict],
    auth_config_path: Path = AUTH_CONFIG_PATH,
) -> dict:
    payload = {
        "appId": app_id,
        "worksheetId": worksheet_id,
        "viewId": "",
        "receiveControls": build_web_receive_controls(record, field_meta_map),
    }
    resp = auth_retry.hap_web_post(
        ADD_WORKSHEET_ROW_URL,
        auth_config_path,
        referer=f"https://www.mingdao.com/app/{app_id}/{worksheet_id}",
        json=payload,
        timeout=30,
    )
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"Web 写入返回非 JSON: status={resp.status_code}, body={resp.text[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Web 写入返回格式错误: {data}")
    wrapped = data.get("data", {})
    if not isinstance(wrapped, dict) or int(wrapped.get("resultCode", 0) or 0) != 1:
        raise RuntimeError(f"Web 写入失败: {data}")
    return {"payload": payload, "response": data}


def add_worksheet_row_v3(
    base_url: str,
    app_key: str,
    sign: str,
    worksheet_id: str,
    record: dict,
    field_meta_map: Dict[str, dict],
    trigger_workflow: bool,
) -> dict:
    payload = {
        "fields": build_v3_fields(record, field_meta_map),
        "triggerWorkflow": trigger_workflow,
    }
    url = base_url.rstrip("/") + ROW_CREATE_URL.format(worksheet_id=worksheet_id)
    data = request_json("POST", url, build_headers(app_key, sign), payload=payload)
    row_id = str(data.get("data", {}).get("id", "")).strip()
    if not row_id:
        raise RuntimeError(f"V3 单条新增返回缺少 rowId: worksheetId={worksheet_id}, resp={data}")
    return {"payload": payload, "response": data, "rowId": row_id, "source": "v3"}


def add_worksheet_row_with_fallback(
    base_url: str,
    app_key: str,
    sign: str,
    account_id: str,
    authorization: str,
    cookie: str,
    app_id: str,
    worksheet_id: str,
    record: dict,
    field_meta_map: Dict[str, dict],
    trigger_workflow: bool,
) -> dict:
    try:
        return add_worksheet_row_v3(
            base_url=base_url,
            app_key=app_key,
            sign=sign,
            worksheet_id=worksheet_id,
            record=record,
            field_meta_map=field_meta_map,
            trigger_workflow=trigger_workflow,
        )
    except Exception as exc_v3:
        api_resp = add_worksheet_row_web(
            account_id=account_id,
            authorization=authorization,
            cookie=cookie,
            app_id=app_id,
            worksheet_id=worksheet_id,
            record=record,
            field_meta_map=field_meta_map,
        )
        row_id = str(
            (
                api_resp.get("response", {})
                .get("data", {})
                .get("data", {})
                .get("rowid", "")
            )
        ).strip()
        if not row_id:
            raise RuntimeError(
                f"Web 兜底新增返回缺少 rowId: worksheetId={worksheet_id}, record={record.get('mockRecordKey', '')}"
            ) from exc_v3
        api_resp["rowId"] = row_id
        api_resp["source"] = "web_fallback"
        api_resp["fallbackFrom"] = str(exc_v3)
        return api_resp


def create_rows_batch(
    base_url: str,
    app_key: str,
    sign: str,
    worksheet_id: str,
    records: List[dict],
    trigger_workflow: bool,
) -> dict:
    payload = {
        "rows": build_batch_rows(records),
        "triggerWorkflow": trigger_workflow,
    }
    url = base_url.rstrip("/") + ROW_BATCH_CREATE_URL.format(worksheet_id=worksheet_id)
    return request_json("POST", url, build_headers(app_key, sign), payload=payload)


def create_rows_batch_v3(
    base_url: str,
    app_key: str,
    sign: str,
    worksheet_id: str,
    enriched_records: List[dict],
    field_meta_map: Dict[str, dict],
    trigger_workflow: bool,
) -> List[str]:
    """批量写入记录（使用 build_v3_fields 做字段校验），返回 rowId 列表。"""
    rows = []
    for record in enriched_records:
        rows.append({"fields": build_v3_fields(record, field_meta_map)})
    payload = {
        "rows": rows,
        "triggerWorkflow": trigger_workflow,
    }
    url = base_url.rstrip("/") + ROW_BATCH_CREATE_URL.format(worksheet_id=worksheet_id)
    data = request_json("POST", url, build_headers(app_key, sign), payload=payload)
    # 批量接口返回 {"success": true, "data": {"ids": ["rowId1", ...]}}
    ids = data.get("data", {}).get("ids", [])
    if not isinstance(ids, list):
        ids = []
    return [str(rid).strip() for rid in ids if str(rid).strip()]


def delete_rows_batch(
    base_url: str,
    app_key: str,
    sign: str,
    worksheet_id: str,
    row_ids: List[str],
    permanent: bool,
    trigger_workflow: bool,
) -> dict:
    payload = {
        "rowIds": row_ids,
        "permanent": permanent,
        "triggerWorkflow": trigger_workflow,
    }
    url = base_url.rstrip("/") + ROW_BATCH_DELETE_URL.format(worksheet_id=worksheet_id)
    return request_json("DELETE", url, build_headers(app_key, sign), payload=payload)


def update_row_relation(
    base_url: str,
    app_key: str,
    sign: str,
    worksheet_id: str,
    row_id: str,
    field_id: str,
    target_row_id: str,
    trigger_workflow: bool,
) -> dict:
    payload = {
        "fields": [
            {
                "id": field_id,
                "value": [target_row_id],
            }
        ],
        "triggerWorkflow": trigger_workflow,
    }
    url = base_url.rstrip("/") + ROW_UPDATE_URL.format(worksheet_id=worksheet_id, row_id=row_id)
    return request_json("PATCH", url, build_headers(app_key, sign), payload=payload)


def fetch_rows(
    base_url: str,
    app_key: str,
    sign: str,
    worksheet_id: str,
    fields: Optional[List[str]] = None,
    include_system_fields: bool = False,
) -> List[dict]:
    url = base_url.rstrip("/") + ROW_LIST_URL.format(worksheet_id=worksheet_id)
    rows: List[dict] = []
    page_index = 1
    while True:
        payload: Dict[str, Any] = {
            "pageSize": 1000,
            "pageIndex": page_index,
            "includeTotalCount": True,
            "includeSystemFields": include_system_fields,
            "useFieldIdAsKey": True,
        }
        if fields:
            payload["fields"] = fields
        data = request_json("POST", url, build_headers(app_key, sign), payload=payload)
        part = data.get("data", {})
        page_rows = part.get("rows", [])
        total = int(part.get("total", 0) or 0)
        if not isinstance(page_rows, list):
            break
        rows.extend(page_rows)
        if len(rows) >= total or not page_rows:
            break
        page_index += 1
    return rows


def call_with_backoff(
    fn: Callable,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> dict:
    """调用 fn(**kwargs)，失败时以指数退避最多重试 max_retries 次。"""
    last_exc: Exception = RuntimeError("call_with_backoff: 未执行")
    for attempt in range(max_retries + 1):
        try:
            result = fn(**kwargs)
            if isinstance(result, dict) and result.get("success") is False and attempt < max_retries:
                raise RuntimeError(f"API 返回 success=false: {result.get('error', '')}")
            return result
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
    raise last_exc


def summarize_write_result(write_result: dict) -> str:
    worksheets = write_result.get("worksheets", [])
    total_ok = sum(int(item.get("successCount", 0) or 0) for item in worksheets if isinstance(item, dict))
    total_fail = sum(int(item.get("failedCount", 0) or 0) for item in worksheets if isinstance(item, dict))
    return f"工作表 {len(worksheets)} 张，成功写入 {total_ok} 条，失败 {total_fail} 条"
