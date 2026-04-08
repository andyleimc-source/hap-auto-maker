#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图规划数据工具。

提供 HAP API 数据拉取函数，被 pipeline_views.py 和 pipeline/waves.py 导入：
  - load_app_auth_rows: 加载应用授权信息
  - fetch_app_meta: 获取应用元数据
  - fetch_worksheets: 获取工作表列表
  - fetch_controls: 获取工作表字段
  - simplify_field: 简化字段信息
  - default_display_controls: 默认显示字段

视图规划和配置已迁移至：
  - planners/view_recommender.py（AI 推荐）
  - planners/view_configurator.py（AI 配置）
  - pipeline_views.py（并行编排）
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import json
from pathlib import Path
from typing import Dict, List

import requests
import auth_retry

BASE_DIR = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"


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
            x = dict(row)
            x["_auth_path"] = str(path.resolve())
            rows.append(x)
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
        section_id = str(section.get("id", ""))
        section_name = str(section.get("name", ""))
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append(
                    {
                        "workSheetId": str(item.get("id", "")),
                        "workSheetName": str(item.get("name", "")),
                        "appSectionId": section_id,
                        "appSectionName": section_name,
                    }
                )
        for child in section.get("childSections", []) or []:
            walk_sections(child)

    for sec in app_meta.get("sections", []) or []:
        walk_sections(sec)

    # 按工作表名称去重（保留同名中最后一个，因为 pipeline 多次重试时最新批次排在后面）
    seen_names: dict = {}
    for ws in worksheets:
        seen_names[ws["workSheetName"]] = ws
    deduped = list(seen_names.values())
    if len(deduped) < len(worksheets):
        print(f"  [去重] 工作表总数 {len(worksheets)}，按名称去重后 {len(deduped)} 个")
    return deduped


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
    return {
        "worksheetId": worksheet_id,
        "worksheetName": str(payload.get("worksheetName", "") or ""),
        "fields": controls,
    }


def simplify_field(field: dict) -> dict:
    options = []
    raw_opts = field.get("options")
    if isinstance(raw_opts, list):
        for o in raw_opts:
            if not isinstance(o, dict):
                continue
            if o.get("isDeleted", False):
                continue
            options.append(
                {
                    "key": str(o.get("key", "")).strip(),
                    "value": str(o.get("value", "")).strip(),
                }
            )
            if len(options) >= 20:
                break
    field_id = str(field.get("id", "") or field.get("controlId", "")).strip()
    field_name = str(field.get("name", "") or field.get("controlName", "")).strip()
    is_system = bool(field.get("isSystemControl", False))
    if not is_system:
        try:
            is_system = int(field.get("attribute", 0) or 0) == 1
        except Exception:
            is_system = False
    return {
        "id": field_id,
        "name": field_name,
        "type": str(field.get("type", "")).strip(),
        "subType": int(field.get("subType", 0) or 0),
        "isTitle": bool(field.get("isTitle", False)),
        "required": bool(field.get("required", False)),
        "isSystem": is_system,
        "options": options,
    }


def default_display_controls(fields: List[dict]) -> List[str]:
    ids = []
    title_id = ""
    for f in fields:
        fid = str(f.get("id", "")).strip()
        if not fid:
            continue
        if bool(f.get("isTitle", False)) and not title_id:
            title_id = fid
        if not bool(f.get("isSystem", False)):
            ids.append(fid)
    out = []
    if title_id:
        out.append(title_id)
    for fid in ids:
        if fid not in out:
            out.append(fid)
        if len(out) >= 3:
            break
    return out
