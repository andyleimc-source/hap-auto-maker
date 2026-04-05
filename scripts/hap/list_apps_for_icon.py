#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取应用名称清单（用于应用 icon 匹配）。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from utils import latest_file

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
APP_INVENTORY_DIR = OUTPUT_ROOT / "app_inventory"
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


def load_app_auth_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"授权文件格式不正确: {path}")
    return [r for r in rows if isinstance(r, dict)]


def parse_app_ids(value: str) -> set[str]:
    if not value.strip():
        return set()
    return {x.strip() for x in value.split(",") if x.strip()}


def fetch_app_meta(app_key: str, sign: str) -> dict:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app = data.get("data", {})
    if not isinstance(app, dict):
        raise RuntimeError(f"应用信息返回格式错误: {data}")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="获取应用名称和当前 icon 信息，输出本地 JSON")
    parser.add_argument("--app-auth-json", default="", help="应用授权 JSON 文件名或路径（默认取最新）")
    parser.add_argument("--app-ids", default="", help="可选，逗号分隔，仅导出这些 appId")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    auth_path = resolve_app_auth_json(args.app_auth_json)
    rows = load_app_auth_rows(auth_path)
    app_id_filter = parse_app_ids(args.app_ids)

    apps = []
    for row in rows:
        app_id = str(row.get("appId", "")).strip()
        if not app_id:
            continue
        if app_id_filter and app_id not in app_id_filter:
            continue
        app_key = str(row.get("appKey", "")).strip()
        sign = str(row.get("sign", "")).strip()
        if not app_key or not sign:
            continue
        app_meta = fetch_app_meta(app_key=app_key, sign=sign)
        apps.append(
            {
                "appId": app_id,
                "appName": str(app_meta.get("name", "")).strip(),
                "currentIconUrl": str(app_meta.get("iconUrl", "")).strip(),
                "currentColor": str(app_meta.get("color", "")).strip(),
            }
        )

    result = {
        "app_auth_json": str(auth_path),
        "apps": apps,
    }

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        APP_INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = (APP_INVENTORY_DIR / f"app_inventory_{ts}.json").resolve()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_path = (APP_INVENTORY_DIR / "app_inventory_latest.json").resolve()
    latest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n已保存: {out_path}")
    print(f"已更新: {latest_path}")


if __name__ == "__main__":
    main()
