#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2b4 — 删除工作表字段（SaveWorksheetControls）

从 controls 数组中移除指定字段后回写。
WARNING: 不可逆，字段及所有数据将永久删除。标题字段（attribute=1）不可删除。

用法:
    uv run python3 hap-auto-maker/scripts/hap/delete_worksheet_field.py \
        --worksheet-id <id> --field-id <controlId> [--yes]
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
    parser = argparse.ArgumentParser(description="删除工作表字段（2b4，不可逆）")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--field-id", required=True, help="字段 controlId")
    parser.add_argument("--yes", action="store_true", help="跳过确认直接执行")
    args = parser.parse_args()

    headers = web_auth_headers()
    payload = get_controls(args.worksheet_id, headers)
    controls = payload["controls"]
    version = payload["version"]
    source_id = payload["sourceId"]

    target = next((c for c in controls if c["controlId"] == args.field_id), None)
    if not target:
        raise SystemExit(f"字段 {args.field_id} 不存在于工作表 {args.worksheet_id}")
    if target.get("attribute") == 1:
        raise SystemExit("标题字段（attribute=1）不可删除")

    if not args.yes:
        print(f"将删除字段「{target.get('controlName')}」({args.field_id})，此操作不可逆。")
        confirm = input("确认？[y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("已取消")
            return

    remaining = [c for c in controls if c["controlId"] != args.field_id]
    result = save_controls(source_id, version, remaining, headers)

    print(json.dumps({
        "ok": True,
        "deleted": args.field_id,
        "version": result["version"],
        "remaining_fields": len(result["controls"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
