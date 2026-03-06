#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 造数共享工具。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

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
GEMINI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
DEFAULT_BASE_URL = "https://api.mingdao.com"
APP_INFO_URL = "/v3/app"
WORKSHEET_DETAIL_URL = "/v3/app/worksheets/{worksheet_id}"
ROW_LIST_URL = "/v3/app/worksheets/{worksheet_id}/rows/list"
ROW_BATCH_CREATE_URL = "/v3/app/worksheets/{worksheet_id}/rows/batch"
ROW_BATCH_DELETE_URL = "/v3/app/worksheets/{worksheet_id}/rows/batch"
ROW_UPDATE_URL = "/v3/app/worksheets/{worksheet_id}/rows/{row_id}"
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"

SUPPORTED_WRITABLE_FIELD_TYPES = {
    "Text",
    "Number",
    "Date",
    "DateTime",
    "SingleSelect",
    "MultipleSelect",
    "Checkbox",
    "Rating",
    "Location",
    "PhoneNumber",
    "Email",
    "Textarea",
    "Link",
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
    "AutoNumber",
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
    "_initiatedAt",
    "_nodeStartedAt",
    "_completedAt",
    "_dueAt",
}


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "item"


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_json_with_latest(output_dir: Path, output_path: Path, latest_name: str, payload: dict) -> Path:
    ensure_dir(output_dir)
    write_json(output_path, payload)
    latest_path = (output_dir / latest_name).resolve()
    write_json(latest_path, payload)
    return output_path


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
    data = load_json(config_path)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"Gemini 配置缺少 api_key: {config_path}")
    return api_key


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


def request_json(method: str, url: str, headers: dict, payload: Optional[dict] = None, timeout: int = 30) -> dict:
    resp = requests.request(method=method, url=url, headers=headers, json=payload, timeout=timeout)
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"接口返回非 JSON: status={resp.status_code}, body={resp.text[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"接口返回格式错误: {data}")
    if not data.get("success"):
        raise RuntimeError(f"接口调用失败: {data}")
    return data


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


def fetch_worksheet_detail(base_url: str, app_key: str, sign: str, worksheet_id: str) -> dict:
    url = base_url.rstrip("/") + WORKSHEET_DETAIL_URL.format(worksheet_id=worksheet_id)
    data = request_json("GET", url, build_headers(app_key, sign), payload=None)
    ws = data.get("data", {})
    if not isinstance(ws, dict):
        raise RuntimeError(f"工作表结构格式错误: worksheetId={worksheet_id}")
    return ws


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
    ftype = str(field.get("type", "")).strip()
    if ftype:
        return ftype
    control_type = str(field.get("controlType", "")).strip()
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
    simplified = {
        "fieldId": str(field.get("id", "")).strip(),
        "name": str(field.get("name", "")).strip(),
        "alias": str(field.get("alias", "")).strip(),
        "type": normalize_field_type(field),
        "subType": int(field.get("subType", 0) or 0),
        "required": bool(field.get("required", False)),
        "isTitle": bool(field.get("isTitle", False)),
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


def compute_worksheet_tiers(worksheets: List[dict], relation_pairs: List[dict]) -> List[dict]:
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
            tier = 2
            record_count = 10
            reason = "该表自身仅通过单选 Relation 关联上级表，按明细端处理"
        else:
            tier = 3 if all(pair_type == "1-1" for pair_type in pair_types) else 1
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
    tiers.sort(key=lambda item: (item["tier"], item["worksheetName"]))
    for idx, item in enumerate(tiers, start=1):
        item["order"] = idx
    return tiers


def build_schema_snapshot(base_url: str, app: dict) -> dict:
    app_meta, worksheet_refs = fetch_app_worksheets(base_url, app["appKey"], app["sign"])
    worksheets: List[dict] = []
    for ref in worksheet_refs:
        detail = fetch_worksheet_detail(base_url, app["appKey"], app["sign"], ref["worksheetId"])
        simplified_fields = [simplify_field(field) for field in detail.get("fields", []) if isinstance(field, dict)]
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
            }
        )

    relation_edges = build_relation_edges(worksheets)
    relation_pairs, warnings = infer_relation_pairs(relation_edges)
    worksheet_tiers = compute_worksheet_tiers(worksheets, relation_pairs)
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


def summarize_write_result(write_result: dict) -> str:
    worksheets = write_result.get("worksheets", [])
    total_ok = sum(int(item.get("successCount", 0) or 0) for item in worksheets if isinstance(item, dict))
    total_fail = sum(int(item.get("failedCount", 0) or 0) for item in worksheets if isinstance(item, dict))
    return f"工作表 {len(worksheets)} 张，成功写入 {total_ok} 条，失败 {total_fail} 条"
