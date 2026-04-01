#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2b3 — 更新工作表字段（SaveWorksheetControls）

修改指定字段的名称、说明、必填、唯一等属性。
先调 GetWorksheetControls 取当前 version，修改后回写。

用法:
    uv run python3 hap-auto-maker/scripts/hap/update_worksheet_field.py \
        --worksheet-id <id> --field-id <controlId> \
        [--name <新名称>] [--hint <说明>] [--required] [--no-required] [--unique] [--no-unique]
"""

import argparse
import json
import sys
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR.parent / "src"))

from auth import web_auth_headers

WEB_BASE = "https://www.mingdao.com"


def get_controls(worksheet_id: str, headers: dict) -> dict:
    r = requests.post(f"{WEB_BASE}/api/Worksheet/GetWorksheetControls",
                      headers=headers, json={"worksheetId": worksheet_id}, timeout=30)
    r.raise_for_status()
    body = r.json()
    return body["data"]["data"]


def save_controls(source_id: str, version: int, controls: list, headers: dict) -> dict:
    r = requests.post(f"{WEB_BASE}/api/Worksheet/SaveWorksheetControls",
                      headers=headers,
                      json={"version": version, "sourceId": source_id, "controls": controls},
                      timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("data", {}).get("code") != 1:
        raise RuntimeError(f"SaveWorksheetControls 失败: {body}")
    return body["data"]["data"]


def main() -> None:
    parser = argparse.ArgumentParser(description="更新工作表字段属性（2b3）")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--field-id", required=True, help="字段 controlId")
    parser.add_argument("--name", default=None, help="新字段名称")
    parser.add_argument("--hint", default=None, help="字段说明/提示")
    parser.add_argument("--required", dest="required", action="store_true", default=None,
                        help="设为必填")
    parser.add_argument("--no-required", dest="required", action="store_false",
                        help="取消必填")
    parser.add_argument("--unique", dest="unique", action="store_true", default=None,
                        help="设为唯一")
    parser.add_argument("--no-unique", dest="unique", action="store_false",
                        help="取消唯一")
    args = parser.parse_args()

    if args.name is None and args.hint is None and args.required is None and args.unique is None:
        parser.error("至少指定一个要修改的属性：--name / --hint / --required / --unique")

    headers = web_auth_headers()
    payload = get_controls(args.worksheet_id, headers)
    controls = payload["controls"]
    version = payload["version"]
    source_id = payload["sourceId"]

    target = next((c for c in controls if c["controlId"] == args.field_id), None)
    if not target:
        raise SystemExit(f"字段 {args.field_id} 不存在于工作表 {args.worksheet_id}")

    updated = []
    for c in controls:
        if c["controlId"] == args.field_id:
            c = dict(c)
            if args.name is not None:
                c["controlName"] = args.name
            if args.hint is not None:
                c["hint"] = args.hint
            if args.required is not None:
                c["required"] = args.required
            if args.unique is not None:
                c["unique"] = args.unique
        updated.append(c)

    result = save_controls(source_id, version, updated, headers)

    saved = next((c for c in result["controls"] if c["controlId"] == args.field_id), None)
    print(json.dumps({
        "ok": True,
        "version": result["version"],
        "field": {
            "controlId": saved["controlId"],
            "controlName": saved.get("controlName"),
            "hint": saved.get("hint"),
            "required": saved.get("required"),
            "unique": saved.get("unique"),
        } if saved else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
