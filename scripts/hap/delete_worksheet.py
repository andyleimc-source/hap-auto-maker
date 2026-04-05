#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2a4 — 删除工作表（v3 DELETE /v3/app/worksheets/{worksheetId}）

WARNING: 不可逆操作，工作表及所有记录将被永久删除。

用法:
    uv run python3 hap-auto-maker/scripts/hap/delete_worksheet.py \
        --worksheet-id <worksheetId> [--app-auth-json <file>] [--yes]
"""

import argparse
import json
from pathlib import Path

import requests
from utils import latest_file

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
V3_BASE = "https://api.mingdao.com"


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


def delete_worksheet(app_key: str, sign: str, worksheet_id: str) -> bool:
    """删除工作表，成功返回 True。"""
    url = f"{V3_BASE}/v3/app/worksheets/{worksheet_id}"
    headers = {
        "Content-Type": "application/json",
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
    }
    resp = requests.delete(url, headers=headers, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"删除工作表失败 [{body.get('error_code')}]: {body.get('error_msg')}")
    return bool(body.get("data"))


def main() -> None:
    parser = argparse.ArgumentParser(description="删除工作表（v3 API，不可逆）")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--app-auth-json", default="", help="应用授权 JSON 文件名或路径（默认取最新）")
    parser.add_argument("--yes", action="store_true", help="跳过确认提示直接执行")
    args = parser.parse_args()

    if not args.yes:
        confirm = input(f"确认删除工作表 {args.worksheet_id}？此操作不可逆 [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("已取消")
            return

    auth_path = resolve_auth(args.app_auth_json)
    auth = load_auth(auth_path)

    app_key = str(auth.get("appKey", "")).strip()
    sign = str(auth.get("sign", "")).strip()
    if not app_key or not sign:
        raise ValueError(f"授权文件缺少 appKey/sign: {auth_path}")

    ok = delete_worksheet(app_key, sign, args.worksheet_id)
    result = {"ok": ok, "worksheetId": args.worksheet_id}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
