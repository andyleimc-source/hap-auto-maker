#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
删除某应用下所有工作表中名称为"全部"或"视图"的默认视图。

流程：
1) 通过 HAP v3 API 获取应用所有工作表 ID
2) 对每张工作表调用 GET /v3/app/worksheets/{worksheet_id} 获取视图列表
3) 过滤出名称为"全部"的视图
4) 调用 DeleteWorksheetView（私有 web 接口）删除
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

_PROXY_VARS = {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
               "ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy"}

def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _PROXY_VARS}

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import auth_retry

HAP_BASE = "https://api.mingdao.com"
APP_INFO_URL = f"{HAP_BASE}/v3/app"
WORKSHEET_INFO_URL = f"{HAP_BASE}/v3/app/worksheets/{{worksheet_id}}"
DELETE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/DeleteWorksheetView"

TARGET_VIEW_NAMES = {"视图"}
DELETE_ALL_VIEWS = False  # 由 --all-views 参数覆盖


# ---------- HAP auth ----------

def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def resolve_app_auth_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.exists():
            return p.resolve()
        candidate = (APP_AUTH_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到授权文件: {value}")
    p = latest_file(APP_AUTH_DIR, "app_authorize_*.json")
    if not p:
        raise FileNotFoundError(f"未找到授权文件（目录: {APP_AUTH_DIR}）")
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
    return rows[0]


def hap_headers(app_key: str, sign: str) -> dict:
    return {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }



# ---------- HAP v3: 获取工作表列表 ----------

def fetch_worksheets(app_key: str, sign: str) -> list[dict]:
    resp = requests.get(APP_INFO_URL, headers=hap_headers(app_key, sign), timeout=30, proxies={})
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")

    worksheets: list[dict] = []

    def walk(section: dict) -> None:
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append({
                    "worksheetId": str(item.get("id", "")),
                    "worksheetName": str(item.get("name", "")),
                })
        for child in section.get("childSections", []) or []:
            walk(child)

    for sec in data.get("data", {}).get("sections", []) or []:
        walk(sec)
    return worksheets


# ---------- HAP v3: 获取单张工作表的视图列表 ----------

def fetch_views(worksheet_id: str, app_key: str, sign: str) -> list[dict]:
    """返回视图列表，每项包含 id、name、type。"""
    url = WORKSHEET_INFO_URL.format(worksheet_id=worksheet_id)
    resp = requests.get(url, headers=hap_headers(app_key, sign), timeout=30, proxies={})
    data = resp.json()
    if not data.get("success"):
        return []
    views = data.get("data", {}).get("views") or []
    return views if isinstance(views, list) else []


# ---------- 删除视图（私有 web 接口）----------

def delete_view(app_id: str, worksheet_id: str, view_id: str, auth_config_path: Path) -> bool:
    payload = {
        "appId": app_id,
        "viewId": view_id,
        "worksheetId": worksheet_id,
        "status": 9,
    }
    resp = auth_retry.hap_web_post(DELETE_VIEW_URL, auth_config_path, json=payload, timeout=30, proxies={})
    data = resp.json()
    return bool(data.get("data"))


# ---------- 主流程 ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="删除应用所有工作表中名称为「全部」或「视图」的默认视图")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--app-auth-json", default="", help="HAP 授权 JSON 文件名或路径（默认取最新）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--refresh-auth", action="store_true", help="执行前先调用 refresh_auth 刷新 Cookie/Authorization")
    parser.add_argument("--headless", action="store_true", help="配合 --refresh-auth 使用，无头模式刷新")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际删除")
    parser.add_argument("--all-views", action="store_true", help="删除所有视图（而不只是名为'全部'/'视图'的默认视图）")
    args = parser.parse_args()

    app_id = args.app_id.strip()

    # HAP 认证
    auth_path = resolve_app_auth_json(args.app_auth_json)
    hap_auth = load_app_auth(auth_path, app_id=app_id)
    app_key = str(hap_auth.get("appKey", "")).strip()
    sign = str(hap_auth.get("sign", "")).strip()

    # 浏览器认证（仅删除用）
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    if args.refresh_auth:
        print("正在刷新浏览器认证...")
        auth_retry.refresh_auth(auth_config_path, headless=args.headless)

    # 获取所有工作表
    print(f"正在获取应用 {app_id} 的工作表列表...")
    worksheets = fetch_worksheets(app_key=app_key, sign=sign)
    print(f"共找到 {len(worksheets)} 张工作表\n")

    total_found = 0
    total_deleted = 0

    for ws in worksheets:
        ws_id = ws["worksheetId"]
        ws_name = ws["worksheetName"]

        views = fetch_views(worksheet_id=ws_id, app_key=app_key, sign=sign)
        if args.all_views:
            # 删除所有视图（至少保留一个，防止工作表无视图）
            target_views = views[:-1] if len(views) > 1 else []
        else:
            target_views = [v for v in views if str(v.get("name", "")).strip() in TARGET_VIEW_NAMES]

        if not target_views:
            continue

        for view in target_views:
            # v3 API 返回的视图字段是 "id"，非 "viewId"
            view_id = str(view.get("id", "")).strip()
            view_name = str(view.get("name", "")).strip()
            total_found += 1
            if args.dry_run:
                print(f"[预览] 工作表《{ws_name}》({ws_id}) → 视图「{view_name}」({view_id}) 待删除")
            else:
                ok = delete_view(app_id=app_id, worksheet_id=ws_id, view_id=view_id, auth_config_path=auth_config_path)
                status = "成功" if ok else "失败"
                print(f"[{status}] 工作表《{ws_name}》({ws_id}) → 视图「{view_name}」({view_id})")
                if ok:
                    total_deleted += 1

    if args.all_views:
        print(f"\n{'[预览] ' if args.dry_run else ''}共发现 {total_found} 个视图（--all-views 模式）"
              + (f"，已删除 {total_deleted} 个" if not args.dry_run else ""))
    else:
        target_names_str = "、".join(f"「{n}」" for n in sorted(TARGET_VIEW_NAMES))
        print(f"\n{'[预览] ' if args.dry_run else ''}共发现 {total_found} 个默认视图（{target_names_str}）"
              + (f"，已删除 {total_deleted} 个" if not args.dry_run else ""))


if __name__ == "__main__":
    main()
