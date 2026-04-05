#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取某个应用下的所有工作表（名称 + ID + 分组信息）并保存为 JSON。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from utils import latest_file

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
WORKSHEET_INVENTORY_DIR = OUTPUT_ROOT / "worksheet_inventory"

APP_INFO_URL = "https://api.mingdao.com/v3/app"


def resolve_app_auth_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (APP_AUTH_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到授权文件: {value}（也未在 {APP_AUTH_DIR} 找到）")
    p = latest_file(APP_AUTH_DIR, "app_authorize_*.json")
    if not p:
        raise FileNotFoundError(f"未找到授权文件，请传 --app-auth-json（目录: {APP_AUTH_DIR}）")
    return p.resolve()


def load_app_auth(path: Path, app_id: str = "") -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"授权文件格式不正确: {path}")
    if app_id:
        for row in rows:
            if isinstance(row, dict) and row.get("appId") == app_id:
                return row
        raise ValueError(f"授权文件中未找到 appId={app_id}: {path}")
    row = rows[0]
    if not isinstance(row, dict):
        raise ValueError(f"授权文件格式不正确: {path}")
    return row


def fetch_worksheets(app_key: str, sign: str) -> List[Dict[str, str]]:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")

    worksheets: List[Dict[str, str]] = []

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

    for sec in data.get("data", {}).get("sections", []) or []:
        walk_sections(sec)
    return worksheets


def main() -> None:
    parser = argparse.ArgumentParser(description="获取某应用下所有工作表列表并保存 JSON")
    parser.add_argument("--app-auth-json", default="", help="应用授权 JSON 文件名或路径（默认取最新）")
    parser.add_argument("--app-id", default="", help="可选，指定 appId（授权文件含多个时可用）")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    auth_path = resolve_app_auth_json(args.app_auth_json)
    auth = load_app_auth(auth_path, app_id=args.app_id)

    app_id = str(auth.get("appId", "")).strip()
    app_key = str(auth.get("appKey", "")).strip()
    sign = str(auth.get("sign", "")).strip()
    if not app_id or not app_key or not sign:
        raise ValueError(f"授权文件缺少 appId/appKey/sign: {auth_path}")

    worksheets = fetch_worksheets(app_key=app_key, sign=sign)
    result = {
        "app_id": app_id,
        "app_auth_json": str(auth_path),
        "count": len(worksheets),
        "worksheets": worksheets,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        WORKSHEET_INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (WORKSHEET_INVENTORY_DIR / f"worksheet_inventory_{app_id}_{ts}.json").resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n已保存: {output_path}")


if __name__ == "__main__":
    main()
