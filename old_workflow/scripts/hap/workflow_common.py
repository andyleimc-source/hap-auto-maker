#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流模块共享工具。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sys

CURRENT_DIR = Path(__file__).resolve().parent
REPO_HAP_DIR = CURRENT_DIR.parents[2] / "scripts" / "hap"
if str(REPO_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_HAP_DIR))

from mock_data_common import (
    APP_AUTH_DIR,
    AUTH_CONFIG_PATH,
    DEFAULT_BASE_URL,
    GEMINI_CONFIG_PATH,
    OUTPUT_ROOT,
    append_log,
    build_headers,
    choose_app,
    discover_authorized_apps,
    ensure_dir,
    extract_json_object,
    fetch_app_worksheets,
    fetch_worksheet_controls,
    fetch_worksheet_detail_v3,
    load_gemini_api_key,
    load_json,
    load_web_auth,
    make_output_path,
    now_iso,
    now_ts,
    request_json,
    simplify_field,
    write_json,
    write_json_with_latest,
)

WORKFLOW_OUTPUT_DIR = OUTPUT_ROOT / "workflow"
WORKFLOW_SCHEMA_DIR = OUTPUT_ROOT / "workflow_schema_snapshots"
WORKFLOW_PLAN_DIR = OUTPUT_ROOT / "workflow_plans"
WORKFLOW_CREATE_DIR = OUTPUT_ROOT / "workflow_create_results"
WORKFLOW_LOG_DIR = OUTPUT_ROOT / "workflow_logs"
WORKFLOW_PIPELINE_DIR = OUTPUT_ROOT / "workflow_pipeline_runs"

WORKFLOW_DOC_DIR = Path(__file__).resolve().parents[2] / "data" / "api_docs" / "workflow"
PRIVATE_WORKFLOW_API_MD = WORKFLOW_DOC_DIR / "private_workflow_api.md"
PRIVATE_WORKFLOW_API_JSON = WORKFLOW_DOC_DIR / "private_workflow_api.json"

PROCESS_ADD_URL = "https://api.mingdao.com/workflow/process/add"
PROCESS_GET_URL = "https://api.mingdao.com/workflow/flowNode/get"
PROCESS_UPDATE_URL = "https://api.mingdao.com/workflow/process/update"
PROCESS_PUBLISH_URL = "https://api.mingdao.com/workflow/process/publish"
APP_MANAGEMENT_ADD_WORKFLOW_URL = "https://www.mingdao.com/api/AppManagement/AddWorkflow"
FLOW_NODE_ADD_URL = "https://api.mingdao.com/workflow/flowNode/add"
FLOW_NODE_SAVE_URL = "https://api.mingdao.com/workflow/flowNode/saveNode"
FLOW_NODE_DETAIL_URL = "https://api.mingdao.com/workflow/flowNode/getNodeDetail"
FLOW_NODE_APP_TEMPLATE_CONTROLS_URL = "https://api.mingdao.com/workflow/flowNode/getAppTemplateControls"
FLOW_NODE_APP_DTOS_URL = "https://api.mingdao.com/workflow/flowNode/getFlowNodeAppDtos"

SUPPORTED_TRIGGER_EVENTS = {"create", "update", "schedule"}
SUPPORTED_NODE_TYPES = {"update_fields", "create_record", "send_notice"}

DATE_FIELD_TYPES = {"Date", "DateTime"}
DEFAULT_NOTICE_CHANNEL = "worksheet_comment"


def ensure_workflow_dirs() -> None:
    for path in [
        WORKFLOW_OUTPUT_DIR,
        WORKFLOW_SCHEMA_DIR,
        WORKFLOW_PLAN_DIR,
        WORKFLOW_CREATE_DIR,
        WORKFLOW_LOG_DIR,
        WORKFLOW_PIPELINE_DIR,
        WORKFLOW_DOC_DIR,
    ]:
        ensure_dir(path)


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "item"


def make_workflow_log_path(prefix: str, app_id: str = "") -> Path:
    ensure_workflow_dirs()
    safe_app = sanitize_name(app_id) if app_id else "general"
    return (WORKFLOW_LOG_DIR / f"{prefix}_{safe_app}_{now_ts()}.jsonl").resolve()


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0].resolve() if files else None


def resolve_json_input(value: str, search_dirs: List[Path], default_pattern: str) -> Path:
    if value:
        raw = Path(value).expanduser()
        if raw.exists():
            return raw.resolve()
        for base_dir in search_dirs:
            candidate = (base_dir / value).resolve()
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"找不到文件: {value}")
    found = None
    for base_dir in search_dirs:
        found = latest_file(base_dir, default_pattern)
        if found:
            return found
    raise FileNotFoundError(f"未找到匹配文件: {default_pattern}")


def resolve_workflow_schema_json(value: str = "") -> Path:
    return resolve_json_input(value, [WORKFLOW_SCHEMA_DIR], "workflow_schema_snapshot_*.json")


def resolve_workflow_plan_json(value: str = "") -> Path:
    return resolve_json_input(value, [WORKFLOW_PLAN_DIR], "workflow_plan_*.json")


def resolve_workflow_create_json(value: str = "") -> Path:
    return resolve_json_input(value, [WORKFLOW_CREATE_DIR], "workflow_create_result_*.json")


def field_type_priority(field_type: str) -> int:
    mapping = {
        "DateTime": 1,
        "Date": 2,
        "SingleSelect": 3,
        "MultipleSelect": 4,
        "Text": 5,
        "Textarea": 6,
        "Number": 7,
        "Relation": 8,
        "Checkbox": 9,
    }
    return mapping.get(field_type, 99)


def normalize_schema_field(field: dict) -> Optional[dict]:
    if not isinstance(field, dict):
        return None
    field_id = str(field.get("fieldId", "")).strip()
    field_name = str(field.get("name", "")).strip()
    field_type = str(field.get("type", "")).strip()
    if not field_id or not field_name or not field_type:
        return None
    if bool(field.get("isSystem", False)):
        return None
    return {
        "fieldId": field_id,
        "fieldName": field_name,
        "fieldType": field_type,
    }


def collect_workflow_hints(worksheets: List[dict]) -> dict:
    date_fields: List[dict] = []
    updatable: List[dict] = []
    triggerable: List[dict] = []
    schedule_targets: List[dict] = []

    for worksheet in worksheets:
        ws_id = str(worksheet.get("worksheetId", "")).strip()
        ws_name = str(worksheet.get("worksheetName", "")).strip()
        fields = worksheet.get("fields", []) or []
        if not ws_id or not ws_name:
            continue
        normal_fields = [field for field in fields if isinstance(field, dict)]
        date_like = [field for field in normal_fields if field.get("fieldType") in DATE_FIELD_TYPES]
        if normal_fields:
            triggerable.append({"worksheetId": ws_id, "worksheetName": ws_name})
            updatable.append({"worksheetId": ws_id, "worksheetName": ws_name})
            schedule_targets.append({"worksheetId": ws_id, "worksheetName": ws_name})
        for field in sorted(date_like, key=lambda item: field_type_priority(str(item.get("fieldType", "")))):
            date_fields.append(
                {
                    "worksheetId": ws_id,
                    "worksheetName": ws_name,
                    "fieldId": field["fieldId"],
                    "fieldName": field["fieldName"],
                    "fieldType": field["fieldType"],
                }
            )

    return {
        "dateFields": date_fields,
        "updatableWorksheets": updatable,
        "triggerableWorksheets": triggerable,
        "scheduledTargetWorksheets": schedule_targets,
    }


def build_workflow_schema_snapshot(base_url: str, app: dict, log_path: Path) -> dict:
    app_meta, worksheet_refs = fetch_app_worksheets(base_url, app["appKey"], app["sign"])
    web_auth = load_web_auth(AUTH_CONFIG_PATH)
    warnings: List[str] = []
    worksheets: List[dict] = []

    append_log(log_path, "app_loaded", appId=app["appId"], worksheetCount=len(worksheet_refs))
    for ref in worksheet_refs:
        detail_source = "v3"
        try:
            detail = fetch_worksheet_detail_v3(base_url, app["appKey"], app["sign"], ref["worksheetId"])
            raw_fields = detail.get("fields", [])
        except Exception as exc_v3:
            detail_source = "web_controls"
            append_log(log_path, "worksheet_detail_v3_failed", worksheetId=ref["worksheetId"], error=str(exc_v3))
            detail = fetch_worksheet_controls(ref["worksheetId"], web_auth)
            raw_fields = detail.get("controls", [])
            warnings.append(
                f"工作表 {ref['worksheetName']} ({ref['worksheetId']}) 的 v3 字段读取失败，已回退到网页控件结构。"
            )

        fields = []
        for raw_field in raw_fields:
            simple = normalize_schema_field(simplify_field(raw_field))
            if simple:
                fields.append(simple)

        fields.sort(key=lambda item: (field_type_priority(item["fieldType"]), item["fieldName"]))
        worksheet_item = {
            "worksheetId": ref["worksheetId"],
            "worksheetName": ref["worksheetName"],
            "appSectionId": ref["appSectionId"],
            "appSectionName": ref["appSectionName"],
            "fields": fields,
            "fieldCount": len(fields),
            "detailSource": detail_source,
        }
        worksheets.append(worksheet_item)
        append_log(
            log_path,
            "worksheet_snapshot",
            worksheetId=ref["worksheetId"],
            worksheetName=ref["worksheetName"],
            fieldCount=len(fields),
            detailSource=detail_source,
        )

    worksheets.sort(key=lambda item: (item["appSectionName"], item["worksheetName"]))
    hints = collect_workflow_hints(worksheets)

    return {
        "schemaVersion": "workflow_schema_snapshot_v1",
        "createdAt": now_iso(),
        "app": {
            "appId": app["appId"],
            "appName": str(app_meta.get("name", "")).strip() or app["appName"],
            "authFile": app["authFile"],
            "authPath": app["authPath"],
            "baseUrl": base_url,
        },
        "worksheets": worksheets,
        "workflowPlanningHints": hints,
        "warnings": warnings,
        "logFile": str(log_path),
    }


def summarize_schema_for_prompt(schema: dict) -> str:
    lines: List[str] = []
    hints = schema.get("workflowPlanningHints", {}) if isinstance(schema, dict) else {}
    date_field_map: Dict[str, List[str]] = {}
    for item in hints.get("dateFields", []) or []:
        if not isinstance(item, dict):
            continue
        ws_id = str(item.get("worksheetId", "")).strip()
        if not ws_id:
            continue
        date_field_map.setdefault(ws_id, []).append(
            f"{item.get('fieldName', '')}<{item.get('fieldType', '')}>[{item.get('fieldId', '')}]"
        )

    for worksheet in schema.get("worksheets", []) or []:
        if not isinstance(worksheet, dict):
            continue
        ws_id = str(worksheet.get("worksheetId", "")).strip()
        ws_name = str(worksheet.get("worksheetName", "")).strip()
        if not ws_id or not ws_name:
            continue
        field_texts = []
        for field in worksheet.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            field_texts.append(
                f"{field.get('fieldName', '')}<{field.get('fieldType', '')}>[{field.get('fieldId', '')}]"
            )
        date_text = "；".join(date_field_map.get(ws_id, []))
        line = f"- {ws_name}[{ws_id}]：字段 { '；'.join(field_texts[:12]) or '无'}"
        if len(field_texts) > 12:
            line += "；等"
        if date_text:
            line += f"；日期字段 {date_text}"
        lines.append(line)
    return "\n".join(lines) if lines else "- 当前应用下没有可用工作表"


def find_worksheet(schema: dict, worksheet_id: str) -> Optional[dict]:
    worksheet_id = str(worksheet_id).strip()
    for worksheet in schema.get("worksheets", []) or []:
        if str(worksheet.get("worksheetId", "")).strip() == worksheet_id:
            return worksheet
    return None


def find_field(schema: dict, worksheet_id: str, field_id: str) -> Optional[dict]:
    worksheet = find_worksheet(schema, worksheet_id)
    if not worksheet:
        return None
    for field in worksheet.get("fields", []) or []:
        if str(field.get("fieldId", "")).strip() == str(field_id).strip():
            return field
    return None


def extract_result_json(output: str) -> str:
    for line in reversed((output or "").splitlines()):
        text = line.strip()
        if text.startswith("RESULT_JSON:"):
            return text.split(":", 1)[1].strip()
    return ""


def load_private_workflow_api_doc() -> Tuple[Optional[dict], Optional[Path]]:
    if PRIVATE_WORKFLOW_API_JSON.exists():
        payload = load_json(PRIVATE_WORKFLOW_API_JSON)
        if isinstance(payload, dict):
            return payload, PRIVATE_WORKFLOW_API_JSON.resolve()
    if PRIVATE_WORKFLOW_API_MD.exists():
        return None, PRIVATE_WORKFLOW_API_MD.resolve()
    return None, None


def build_private_headers(referer: str, content_type: str = "application/json") -> dict:
    account_id, authorization, cookie = load_web_auth(AUTH_CONFIG_PATH)
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": content_type,
        "AccountId": account_id,
        "accountid": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "Origin": "https://www.mingdao.com",
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    }


def post_private_json(url: str, payload: dict, referer: str) -> dict:
    import requests

    response = requests.post(url, headers=build_private_headers(referer), json=payload, timeout=30)
    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError(f"私有接口返回非 JSON: status={response.status_code}, body={response.text[:500]}") from exc


def get_private_json(url: str, referer: str, params: Optional[dict] = None) -> dict:
    import requests

    response = requests.get(url, headers=build_private_headers(referer), params=params or None, timeout=30)
    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError(f"私有接口返回非 JSON: status={response.status_code}, body={response.text[:500]}") from exc


def ensure_state_success(data: dict, api_name: str) -> None:
    state = data.get("state", data.get("status"))
    if state in (1, "1", True):
        return
    msg = str(data.get("message", "") or data.get("msg", "") or data.get("error", "")).strip()
    raise RuntimeError(f"{api_name} 调用失败: state={state}, message={msg or data}")


def default_notice_text(workflow_name: str, worksheet_name: str) -> str:
    return f"工作流《{workflow_name}》已处理工作表《{worksheet_name}》的数据。"


def build_schedule_defaults() -> dict:
    return {
        "frequency": "weekday",
        "interval": 1,
        "time": "09:00",
        "timezone": "Asia/Shanghai",
    }


def make_workflow_output_path(output_dir: Path, prefix: str, app_id: str, suffix: str = "") -> Path:
    return make_output_path(output_dir, prefix, app_id, suffix=suffix)
