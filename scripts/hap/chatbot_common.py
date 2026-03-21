#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对话机器人流水线共享工具。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import List, Optional

import auth_retry

from mock_data_common import (
    BASE_DIR,
    OUTPUT_ROOT,
    append_log,
    discover_authorized_apps,
    ensure_dir,
    extract_json_object,
    fetch_app_worksheets,
    fetch_worksheet_controls,
    fetch_worksheet_detail_v3,
    load_json,
    load_web_auth,
    now_iso,
    simplify_field,
    write_json,
)

ICON_JSON_PATH = BASE_DIR / "data" / "assets" / "icons" / "icon.json"
CHATBOT_OUTPUT_DIR = OUTPUT_ROOT / "chatbot"
CHATBOT_SCHEMA_DIR = CHATBOT_OUTPUT_DIR / "app_schemas"
CHATBOT_PLAN_DIR = CHATBOT_OUTPUT_DIR / "plans"
CHATBOT_CREATE_DIR = CHATBOT_OUTPUT_DIR / "create_results"
CHATBOT_LOG_DIR = CHATBOT_OUTPUT_DIR / "logs"
CHATBOT_PIPELINE_DIR = CHATBOT_OUTPUT_DIR / "pipeline_runs"

GENERATE_CHATBOT_INFO_URL = "https://www.mingdao.com/api/Mingo/GenerateChatRobotInfo"
ADD_WORKSHEET_URL = "https://www.mingdao.com/api/AppManagement/AddWorkSheet"
SAVE_CHATBOT_CONFIG_URL = "https://api.mingdao.com/workflow/process/saveChatbotConfig"

ICON_COLORS = [
    "#6D4C41",
    "#546E7A",
    "#1E88E5",
    "#00897B",
    "#43A047",
    "#F4511E",
    "#8E24AA",
    "#3949AB",
    "#C62828",
    "#5E35B1",
]


def ensure_chatbot_dirs() -> None:
    for path in [
        CHATBOT_OUTPUT_DIR,
        CHATBOT_SCHEMA_DIR,
        CHATBOT_PLAN_DIR,
        CHATBOT_CREATE_DIR,
        CHATBOT_LOG_DIR,
        CHATBOT_PIPELINE_DIR,
    ]:
        ensure_dir(path)


def now_ts() -> str:
    return now_iso().replace("-", "").replace(":", "").replace("+08:00", "").replace("T", "_")


def make_chatbot_log_path(prefix: str, app_id: str = "") -> Path:
    ensure_chatbot_dirs()
    safe_app = (app_id or "general").replace("/", "_")
    return (CHATBOT_LOG_DIR / f"{prefix}_{safe_app}_{now_ts()}.jsonl").resolve()


def write_json_with_latest(output_dir: Path, output_path: Path, latest_name: str, payload: dict) -> Path:
    ensure_dir(output_dir)
    write_json(output_path, payload)
    write_json((output_dir / latest_name).resolve(), payload)
    return output_path


def flatten_sections(sections: List[dict], level: int = 0) -> List[dict]:
    out: List[dict] = []
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        out.append(
            {
                "index": len(out) + 1,
                "appSectionId": str(section.get("id", "")).strip(),
                "name": str(section.get("name", "")).strip() or "未命名分组",
                "level": level,
                "itemCount": len(section.get("items", []) or []),
            }
        )
        child_sections = section.get("childSections", []) or []
        children = flatten_sections(child_sections, level=level + 1)
        for child in children:
            child["index"] = len(out) + 1
            out.append(child)
    return out


def print_section_choices(sections: List[dict]) -> None:
    print("\n可用分组列表：")
    print("序号 | 分组名称 | appSectionId | 条目数")
    print("-" * 120)
    for section in sections:
        indent = "  " * int(section.get("level", 0) or 0)
        name = f"{indent}{section['name']}"
        print(f"{section['index']:>4} | {name} | {section['appSectionId']} | {section['itemCount']}")


def choose_section(sections: List[dict], section_id: str = "", section_index: int = 0) -> dict:
    if not sections:
        raise RuntimeError("当前应用没有可用分组，无法创建对话机器人")
    if section_id:
        for section in sections:
            if section["appSectionId"] == section_id:
                return section
        raise ValueError(f"未找到 appSectionId={section_id}")
    if section_index > 0:
        for section in sections:
            if int(section["index"]) == section_index:
                return section
        raise ValueError(f"未找到分组序号={section_index}")
    print_section_choices(sections)
    while True:
        raw = input("\n请输入要创建机器人的分组序号: ").strip()
        if raw.isdigit():
            idx = int(raw)
            for section in sections:
                if int(section["index"]) == idx:
                    return section
        print("输入无效，请重新输入数字序号。")


def load_icon_names() -> List[str]:
    payload = load_json(ICON_JSON_PATH)
    data = payload.get("data", {})
    icons: List[str] = []
    if isinstance(data, dict):
        for items in data.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("fileName", "")).strip()
                if name:
                    icons.append(name)
    dedup = sorted(set(icons))
    if not dedup:
        raise RuntimeError(f"图标库为空: {ICON_JSON_PATH}")
    return dedup


def stable_pick(seq: List[str], seed: str) -> str:
    if not seq:
        raise ValueError("stable_pick 传入空序列")
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(seq)
    return seq[idx]


def build_icon_url(icon_name: str) -> str:
    return f"https://fp1.mingdaoyun.cn/customIcon/{icon_name}.svg"


def pick_icon_bundle(seed: str) -> dict:
    icon_name = stable_pick(load_icon_names(), seed)
    color = stable_pick(ICON_COLORS, seed + "::color")
    return {
        "icon": icon_name,
        "iconColor": color,
        "iconUrl": build_icon_url(icon_name),
    }


def print_app_choices_for_chatbot(apps: List[dict]) -> None:
    print("\n可用应用列表：")
    print("序号 | 应用名称 | appId | 授权文件")
    print("-" * 120)
    for app in apps:
        print(f"{app['index']:>4} | {app['appName']} | {app['appId']} | {app['authFile']}")
    print("\n输入规则：")
    print("- 输入序号：选择单个应用")
    print("- 输入 Y：选择全部应用")
    print("- 输入其他任意键：取消")


def choose_apps_for_chatbot(apps: List[dict], app_id: str = "", app_index: int = 0) -> List[dict]:
    if not apps:
        raise RuntimeError("未发现可用应用授权文件")
    if app_id:
        for app in apps:
            if app["appId"] == app_id:
                return [app]
        raise ValueError(f"未找到 appId={app_id}")
    if app_index > 0:
        for app in apps:
            if int(app["index"]) == app_index:
                return [app]
        raise ValueError(f"未找到序号={app_index}")

    print_app_choices_for_chatbot(apps)
    raw = input("\n请输入选择: ").strip()
    if raw.isdigit():
        idx = int(raw)
        for app in apps:
            if int(app["index"]) == idx:
                return [app]
        raise ValueError(f"未找到序号={idx}")
    if raw.lower() == "y":
        return list(apps)
    return []


def build_web_headers(account_id: str, authorization: str, cookie: str, referer: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "accountid": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "Origin": "https://www.mingdao.com",
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    }


def post_json(url: str, payload: dict, auth_config_path: Path, referer: str = "", timeout: int = 30) -> dict:
    resp = auth_retry.hap_web_post(url, auth_config_path, referer=referer, json=payload, timeout=timeout)
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"接口返回非 JSON: url={url}, status={resp.status_code}, body={resp.text[:500]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"接口返回格式错误: url={url}, data={data}")
    return data


def ensure_state_success(data: dict, label: str) -> dict:
    if int(data.get("state", 0) or 0) != 1:
        raise RuntimeError(f"{label} 失败: {json.dumps(data, ensure_ascii=False)}")
    return data


def ensure_status_success(data: dict, label: str) -> dict:
    if int(data.get("status", 0) or 0) != 1:
        raise RuntimeError(f"{label} 失败: {json.dumps(data, ensure_ascii=False)}")
    return data


def load_schema_json(path: Path) -> dict:
    data = load_json(path)
    if str(data.get("schemaVersion", "")).strip() != "chatbot_app_schema_v1":
        raise ValueError(f"不是支持的 schemaVersion: {path}")
    return data


def load_plan_json(path: Path) -> dict:
    data = load_json(path)
    if str(data.get("schemaVersion", "")).strip() != "chatbot_plan_v1":
        raise ValueError(f"不是支持的 plan schemaVersion: {path}")
    return data


def fetch_app_schema(
    app: dict,
    base_url: str,
    log_path: Path,
) -> dict:
    app_meta, worksheets = fetch_app_worksheets(base_url=base_url, app_key=app["appKey"], sign=app["sign"])
    append_log(log_path, "app_loaded", worksheetCount=len(worksheets))
    web_auth: Optional[tuple[str, str, str]] = None

    worksheet_items: List[dict] = []
    total_field_count = 0
    for worksheet in worksheets:
        worksheet_id = str(worksheet.get("worksheetId", "")).strip()
        worksheet_name = str(worksheet.get("worksheetName", "")).strip() or worksheet_id
        detail_source = "v3"
        try:
            detail = fetch_worksheet_detail_v3(base_url, app["appKey"], app["sign"], worksheet_id)
            raw_fields = detail.get("fields", [])
        except Exception as exc:
            if web_auth is None:
                web_auth = load_web_auth()
            append_log(log_path, "worksheet_detail_v3_failed", worksheetId=worksheet_id, error=str(exc))
            detail = fetch_worksheet_controls(worksheet_id, web_auth)
            raw_fields = detail.get("controls", [])
            detail_source = "web_controls"

        fields = [simplify_field(field) for field in raw_fields if isinstance(field, dict)]
        total_field_count += len(fields)
        worksheet_items.append(
            {
                "worksheetId": worksheet_id,
                "worksheetName": worksheet_name,
                "appSectionId": str(worksheet.get("appSectionId", "")).strip(),
                "appSectionName": str(worksheet.get("appSectionName", "")).strip(),
                "detailSource": detail_source,
                "fieldCount": len(fields),
                "fields": fields,
            }
        )
        append_log(
            log_path,
            "worksheet_loaded",
            worksheetId=worksheet_id,
            worksheetName=worksheet_name,
            detailSource=detail_source,
            fieldCount=len(fields),
        )

    return {
        "appMeta": app_meta,
        "worksheets": worksheet_items,
        "worksheetCount": len(worksheet_items),
        "fieldCount": total_field_count,
    }
