#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2c4 — 更新记录（v3 PATCH /v3/app/worksheets/{worksheetId}/rows/{rowId}）

用法:
    uv run python3 hap-auto-maker/scripts/hap/update_row.py \
        --worksheet-id <worksheetId> --row-id <rowId> \
        --fields '{"fieldId1": "value1", "fieldId2": "value2"}' \
        [--app-auth-json <file>]

--fields 为字段ID到值的字典，值格式取决于字段类型：
  文本字段:    "hello"
  数字字段:    123
  选项字段:    "optionKey"
  日期字段:    "2024-01-01"
  关联字段:    ["rowId1", "rowId2"]
"""

import argparse
import json
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
APP_AUTH_DIR = BASE_DIR / "data" / "outputs" / "app_authorizations"
V3_BASE = "https://api.mingdao.com"


def latest_file(base_dir: Path, pattern: str):
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def resolve_auth(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (APP_AUTH_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到授权文件: {value}")
    p = latest_file(APP_AUTH_DIR, "app_authorize_*.json")
    if not p:
        raise FileNotFoundError(f"未找到授权文件，请传 --app-auth-json（目录: {APP_AUTH_DIR}）")
    return p.resolve()


def load_auth(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("data")
    if isinstance(rows, list) and rows:
        return rows[0]
    raise ValueError(f"授权文件格式不正确: {path}")


def update_row(app_key: str, sign: str, worksheet_id: str, row_id: str, fields: dict) -> dict:
    url = f"{V3_BASE}/v3/app/worksheets/{worksheet_id}/rows/{row_id}"
    headers = {
        "Content-Type": "application/json",
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
    }
    payload = {"fields": fields, "triggerWorkflow": False}
    resp = requests.patch(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"更新记录失败 [{body.get('error_code')}]: {body.get('error_msg')}")
    return body.get("data", {})


def main() -> None:
    parser = argparse.ArgumentParser(description="更新单条记录（v3 API）")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--row-id", required=True, help="记录 ID")
    parser.add_argument("--fields", required=True, help='字段更新字典 JSON，如 \'{"fieldId": "value"}\'')
    parser.add_argument("--trigger-workflow", action="store_true", help="是否触发工作流（默认 False）")
    parser.add_argument("--app-auth-json", default="", help="应用授权 JSON 文件名或路径（默认取最新）")
    args = parser.parse_args()

    auth_path = resolve_auth(args.app_auth_json)
    auth = load_auth(auth_path)

    app_key = str(auth.get("appKey", "")).strip()
    sign = str(auth.get("sign", "")).strip()
    if not app_key or not sign:
        raise ValueError(f"授权文件缺少 appKey/sign: {auth_path}")

    fields = json.loads(args.fields)
    data = update_row(app_key, sign, args.worksheet_id, args.row_id, fields)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
