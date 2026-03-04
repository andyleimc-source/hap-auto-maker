#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量修改工作表 icon。

用法示例：
python3 scripts/hap/update_worksheet_icons.py \
  --app-auth-json app_authorize_xxx.json \
  --items "worksheetId1=sys_6_1_user_group,worksheetId2=sys_8_4_folder"
"""

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
RESULT_DIR = OUTPUT_ROOT / "worksheet_icon_updates"
ICON_MATCH_DIR = OUTPUT_ROOT / "worksheet_icon_match_plans"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
REFRESH_AUTH_SCRIPT = BASE_DIR / "scripts" / "auth" / "refresh_auth.py"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
EDIT_ICON_URL = "https://www.mingdao.com/api/AppManagement/EditWorkSheetInfoForApp"


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


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


def load_web_auth() -> Tuple[str, str, str]:
    if not AUTH_CONFIG_PATH.exists():
        raise FileNotFoundError(f"缺少认证配置: {AUTH_CONFIG_PATH}")
    spec = importlib.util.spec_from_file_location("auth_config_runtime", str(AUTH_CONFIG_PATH))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    account_id = str(getattr(module, "ACCOUNT_ID", "")).strip()
    authorization = str(getattr(module, "AUTHORIZATION", "")).strip()
    cookie = str(getattr(module, "COOKIE", "")).strip()
    if not account_id or not authorization or not cookie:
        raise ValueError(f"auth_config.py 缺少 ACCOUNT_ID/AUTHORIZATION/COOKIE: {AUTH_CONFIG_PATH}")
    return account_id, authorization, cookie


def refresh_web_auth(headless: bool) -> None:
    if not REFRESH_AUTH_SCRIPT.exists():
        raise FileNotFoundError(f"找不到 refresh_auth 脚本: {REFRESH_AUTH_SCRIPT}")
    cmd = [sys.executable, str(REFRESH_AUTH_SCRIPT)]
    if headless:
        cmd.append("--headless")
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"refresh_auth 执行失败，退出码: {proc.returncode}")


def parse_items(item_args: List[str], items_text: str) -> List[Tuple[str, str]]:
    raw_items: List[str] = []
    raw_items.extend(item_args or [])
    if items_text:
        raw_items.extend([x.strip() for x in items_text.split(",") if x.strip()])

    result: List[Tuple[str, str]] = []
    for raw in raw_items:
        if "=" not in raw:
            raise ValueError(f"格式错误: {raw}，应为 worksheetId=icon")
        ws_id, icon = raw.split("=", 1)
        ws_id = ws_id.strip()
        icon = icon.strip()
        if not ws_id or not icon:
            raise ValueError(f"格式错误: {raw}，worksheetId 或 icon 为空")
        result.append((ws_id, icon))
    if not result:
        raise ValueError("请至少传一个工作表 icon 映射：--item worksheetId=icon 或 --items \"...\"")
    return result


def resolve_mapping_json(value: str) -> Path:
    p = Path(value).expanduser()
    if p.is_absolute() and p.exists():
        return p.resolve()
    if p.exists():
        return p.resolve()
    candidate = (ICON_MATCH_DIR / value).resolve()
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"找不到映射文件: {value}（也未在 {ICON_MATCH_DIR} 找到）")


def parse_items_from_mapping_json(path: Path) -> Tuple[Optional[str], List[Tuple[str, str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    app_auth_json = data.get("app_auth_json")
    app_auth_json = app_auth_json.strip() if isinstance(app_auth_json, str) and app_auth_json.strip() else None
    mappings = data.get("mappings")
    if not isinstance(mappings, list):
        raise ValueError(f"映射文件格式错误，缺少 mappings 数组: {path}")
    result: List[Tuple[str, str]] = []
    for m in mappings:
        if not isinstance(m, dict):
            continue
        ws_id = str(m.get("workSheetId", "")).strip()
        icon = str(m.get("icon", "")).strip()
        if ws_id and icon:
            result.append((ws_id, icon))
    if not result:
        raise ValueError(f"映射文件中无有效 workSheetId/icon: {path}")
    return app_auth_json, result


def fetch_worksheet_meta(app_key: str, sign: str) -> Dict[str, dict]:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")

    result: Dict[str, dict] = {}

    def walk_sections(section: dict):
        section_id = section.get("id", "")
        section_name = section.get("name", "")
        for item in section.get("items", []) or []:
            # type=0 表示工作表
            if item.get("type") == 0:
                ws_id = str(item.get("id", "")).strip()
                if ws_id:
                    result[ws_id] = {
                        "workSheetId": ws_id,
                        "workSheetName": item.get("name", ""),
                        "appSectionId": section_id,
                        "appSectionName": section_name,
                    }
        for child in section.get("childSections", []) or []:
            walk_sections(child)

    for sec in data.get("data", {}).get("sections", []) or []:
        walk_sections(sec)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="批量修改工作表 icon")
    parser.add_argument("--app-auth-json", default="", help="应用授权 JSON 文件名或路径（默认取 app_authorizations 最新）")
    parser.add_argument("--app-id", default="", help="可选，指定 appId（授权文件含多个时可用）")
    parser.add_argument("--item", action="append", default=[], help="单条映射：worksheetId=icon，可重复传入")
    parser.add_argument("--items", default="", help="多条映射：worksheetId1=icon1,worksheetId2=icon2")
    parser.add_argument("--mapping-json", default="", help="待执行映射 JSON（由 Gemini 匹配脚本生成）")
    parser.add_argument("--refresh-auth", action="store_true", help="执行前先调用已有 refresh_auth 刷新 Cookie/Authorization")
    parser.add_argument("--headless", action="store_true", help="配合 --refresh-auth 使用，无头模式刷新")
    parser.add_argument("--dry-run", action="store_true", help="仅打印请求，不实际调用")
    args = parser.parse_args()

    mappings: List[Tuple[str, str]]
    app_auth_json_from_mapping = None
    if args.mapping_json:
        mapping_path = resolve_mapping_json(args.mapping_json)
        app_auth_json_from_mapping, mappings = parse_items_from_mapping_json(mapping_path)
    else:
        mappings = parse_items(args.item, args.items)

    app_auth_input = args.app_auth_json or (app_auth_json_from_mapping or "")
    app_auth_path = resolve_app_auth_json(app_auth_input)
    app_auth = load_app_auth(app_auth_path, app_id=args.app_id)
    app_id = str(app_auth.get("appId", "")).strip()
    app_key = str(app_auth.get("appKey", "")).strip()
    sign = str(app_auth.get("sign", "")).strip()
    if not app_id or not app_key or not sign:
        raise ValueError(f"授权文件缺少 appId/appKey/sign: {app_auth_path}")

    if args.refresh_auth:
        refresh_web_auth(headless=args.headless)
    account_id, authorization, cookie = load_web_auth()

    ws_meta_map = fetch_worksheet_meta(app_key=app_key, sign=sign)

    requests_plan = []
    for ws_id, icon in mappings:
        meta = ws_meta_map.get(ws_id)
        if not meta:
            raise ValueError(f"未在应用中找到 worksheetId: {ws_id}")
        payload = {
            "appId": app_id,
            "appSectionId": meta["appSectionId"],
            "workSheetId": ws_id,
            "workSheetName": meta["workSheetName"],
            "icon": icon,
        }
        requests_plan.append(payload)

    headers_base = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.mingdao.com",
    }

    results = []
    for payload in requests_plan:
        headers = dict(headers_base)
        headers["Referer"] = f"https://www.mingdao.com/app/{payload['appId']}/{payload['appSectionId']}/{payload['workSheetId']}"
        if args.dry_run:
            results.append({"payload": payload, "dry_run": True})
            continue
        resp = requests.post(EDIT_ICON_URL, headers=headers, json=payload, timeout=30)
        try:
            data = resp.json()
        except Exception:
            data = {"status_code": resp.status_code, "text": resp.text}
        results.append({"payload": payload, "response": data, "status_code": resp.status_code})

    summary = {
        "app_auth_json": str(app_auth_path),
        "app_id": app_id,
        "total": len(results),
        "dry_run": args.dry_run,
        "results": results,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"worksheet_icon_update_{ts}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n已保存: {out.resolve()}")


if __name__ == "__main__":
    main()
