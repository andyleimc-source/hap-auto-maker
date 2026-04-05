#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app_context.py — 根据 app_id 获取完整应用上下文。

功能：
  - 从 app_authorizations/ 目录加载指定 app_id 的授权
  - 调用 V3 API 获取所有工作表列表
  - 并发获取每个工作表的字段详情
  - 可选地获取工作流列表

用法（CLI）：
    python3 app_context.py --app-id <appId>
    python3 app_context.py --app-auth-json <file>

用法（Python）：
    from incremental.app_context import load_app_context
    ctx = load_app_context(app_id="xxx")
    # ctx = {"app_id": "...", "worksheets": [...], "workflows": [...]}
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests

_HAP_DIR = Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_DIR))

from utils import latest_file

BASE_DIR = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
V3_BASE = "https://api.mingdao.com"
APP_INFO_URL = f"{V3_BASE}/v3/app"


# ── 授权加载 ───────────────────────────────────────────────────────────────────


def resolve_app_auth(app_auth_json: str = "", app_id: str = "") -> Path:
    if app_auth_json:
        p = Path(app_auth_json).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (APP_AUTH_DIR / app_auth_json).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到授权文件: {app_auth_json}")
    if app_id:
        p = latest_file(APP_AUTH_DIR, f"app_authorize_{app_id}_*.json")
        if p:
            return p
        # 尝试扫描所有授权文件
        for f in sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                rows = data.get("data") or []
                for row in rows:
                    if isinstance(row, dict) and row.get("appId") == app_id:
                        return f
            except Exception:
                continue
    p = latest_file(APP_AUTH_DIR, "app_authorize_*.json")
    if not p:
        raise FileNotFoundError(f"未找到授权文件，请传 --app-auth-json 或 --app-id（目录: {APP_AUTH_DIR}）")
    return p


def load_auth_row(path: Path, app_id: str = "") -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"授权文件格式不正确: {path}")
    if app_id:
        for row in rows:
            if isinstance(row, dict) and row.get("appId") == app_id:
                return row
    return rows[0]


# ── V3 API 调用 ────────────────────────────────────────────────────────────────

def _v3_headers(app_key: str, sign: str) -> dict:
    return {
        "Content-Type": "application/json",
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
    }


def fetch_app_worksheets(app_key: str, sign: str) -> list[dict]:
    """获取应用所有工作表列表（id + name + section）。"""
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"获取应用信息失败: {body}")

    worksheets: list[dict] = []

    def walk(section: dict):
        section_id = str(section.get("id", ""))
        section_name = str(section.get("name", ""))
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append({
                    "worksheetId": str(item.get("id", "")),
                    "worksheetName": str(item.get("name", "")),
                    "appSectionId": section_id,
                    "appSectionName": section_name,
                })
        for child in section.get("childSections", []) or []:
            walk(child)

    for sec in body.get("data", {}).get("sections", []) or []:
        walk(sec)
    return worksheets


def fetch_worksheet_detail(app_key: str, sign: str, worksheet_id: str) -> dict:
    """获取单个工作表字段详情。"""
    url = f"{V3_BASE}/v3/app/worksheets/{worksheet_id}"
    resp = requests.get(url, headers=_v3_headers(app_key, sign), timeout=30)
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"获取工作表详情失败 [{worksheet_id}]: {body.get('error_msg')}")
    return body["data"]


# ── 主逻辑 ─────────────────────────────────────────────────────────────────────

def load_app_context(
    app_id: str = "",
    app_auth_json: str = "",
    with_field_details: bool = True,
    max_workers: int = 5,
) -> dict:
    """
    加载应用完整上下文。

    Returns:
        {
          "app_id": "...",
          "app_key": "...",
          "sign": "...",
          "worksheets": [
            {
              "worksheetId": "...",
              "worksheetName": "...",
              "fields": [...],   # 仅 with_field_details=True 时有
            }
          ]
        }
    """
    auth_path = resolve_app_auth(app_auth_json, app_id)
    auth = load_auth_row(auth_path, app_id)

    resolved_app_id = str(auth.get("appId", "")).strip()
    app_key = str(auth.get("appKey", "")).strip()
    sign = str(auth.get("sign", "")).strip()
    if not app_key or not sign:
        raise ValueError(f"授权文件缺少 appKey/sign: {auth_path}")

    worksheets = fetch_app_worksheets(app_key, sign)

    if with_field_details and worksheets:
        def fetch_detail(ws: dict) -> dict:
            try:
                detail = fetch_worksheet_detail(app_key, sign, ws["worksheetId"])
                ws = dict(ws)
                ws["fields"] = detail.get("controls", [])
                ws["views"] = detail.get("views", [])
                return ws
            except Exception as e:
                ws = dict(ws)
                ws["fields"] = []
                ws["views"] = []
                ws["_error"] = str(e)
                return ws

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(fetch_detail, ws): ws for ws in worksheets}
            result_map: dict[str, dict] = {}
            for fut in as_completed(futures):
                ws = futures[fut]
                try:
                    result_map[ws["worksheetId"]] = fut.result()
                except Exception as e:
                    result_map[ws["worksheetId"]] = {**ws, "fields": [], "_error": str(e)}

        worksheets = [result_map[ws["worksheetId"]] for ws in worksheets]

    return {
        "app_id": resolved_app_id,
        "app_key": app_key,
        "sign": sign,
        "auth_path": str(auth_path),
        "worksheets": worksheets,
    }


def format_context_summary(ctx: dict) -> str:
    """生成适合展示给用户的上下文摘要。"""
    lines = [f"应用 ID: {ctx['app_id']}", f"工作表数量: {len(ctx['worksheets'])}"]
    for ws in ctx["worksheets"]:
        fields = ws.get("fields", [])
        err = ws.get("_error", "")
        err_str = f" [错误: {err}]" if err else ""
        lines.append(f"  - {ws['worksheetName']} ({ws['worksheetId']})  {len(fields)} 字段{err_str}")
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="获取应用完整上下文（工作表 + 字段 + 视图）")
    parser.add_argument("--app-id", default="", help="应用 ID")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON 文件名或路径")
    parser.add_argument("--no-fields", action="store_true", help="跳过字段详情，只获取工作表列表")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径（不传则只打印摘要）")
    args = parser.parse_args()

    ctx = load_app_context(
        app_id=args.app_id,
        app_auth_json=args.app_auth_json,
        with_field_details=not args.no_fields,
    )

    print(format_context_summary(ctx))

    if args.output:
        out = Path(args.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已保存: {out}")


if __name__ == "__main__":
    main()
