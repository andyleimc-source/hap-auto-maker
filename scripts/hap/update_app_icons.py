#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量修改应用 icon（开放接口）。
"""

import argparse
import base64
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "organization_auth.json"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
APP_ICON_MATCH_DIR = OUTPUT_ROOT / "app_icon_match_plans"
RESULT_DIR = OUTPUT_ROOT / "app_icon_updates"
APP_INFO_URL = "https://api.mingdao.com/v3/app"
DEFAULT_BASE_URL = "https://api.mingdao.com"
DEFAULT_ENDPOINT = "/v1/open/app/edit"


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def resolve_path(value: str, default_dir: Path, pattern: str, missing_tip: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (default_dir / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到文件: {value}（也未在 {default_dir} 找到）")
    p = latest_file(default_dir, pattern)
    if not p:
        raise FileNotFoundError(missing_tip)
    return p.resolve()


def load_org_auth() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"缺少配置文件: {CONFIG_PATH}")
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for k in ("app_key", "secret_key"):
        if not data.get(k):
            raise ValueError(f"配置缺少字段: {k}")
    return data


def build_sign(app_key: str, secret_key: str, timestamp_ms: int) -> str:
    raw = f"AppKey={app_key}&SecretKey={secret_key}&Timestamp={timestamp_ms}"
    digest_hex = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return base64.b64encode(digest_hex.encode("utf-8")).decode("utf-8")


def load_app_auth_rows(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"授权文件格式不正确: {path}")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        app_id = str(row.get("appId", "")).strip()
        if app_id:
            result[app_id] = row
    return result


def load_mappings(path: Path) -> tuple[Optional[str], list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    app_auth_json = data.get("app_auth_json")
    app_auth_json = app_auth_json.strip() if isinstance(app_auth_json, str) and app_auth_json.strip() else None
    mappings = data.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError(f"映射文件格式错误或 mappings 为空: {path}")
    cleaned = []
    for m in mappings:
        if not isinstance(m, dict):
            continue
        app_id = str(m.get("appId", "")).strip()
        app_name = str(m.get("appName", "")).strip()
        icon = str(m.get("icon", "")).strip()
        if app_id and icon:
            cleaned.append({"appId": app_id, "appName": app_name, "icon": icon})
    if not cleaned:
        raise ValueError(f"映射文件中无有效 appId/icon: {path}")
    return app_auth_json, cleaned


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
    parser = argparse.ArgumentParser(description="批量修改应用 icon（导入 Gemini 映射 JSON）")
    parser.add_argument("--mapping-json", default="", help="应用 icon 待执行 JSON（默认取最新）")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON（不传则优先用 mapping 中的 app_auth_json）")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="编辑应用接口路径")
    parser.add_argument("--project-id", default="", help="HAP 组织Id（默认读取 organization_auth.json）")
    parser.add_argument("--operator-id", default="", help="编辑者账号Id（默认读取 organization_auth.json 的 owner_id）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印请求，不实际调用")
    parser.add_argument("--max-workers", type=int, default=8, help="并发请求数（默认 8）")
    args = parser.parse_args()

    mapping_path = resolve_path(
        args.mapping_json,
        APP_ICON_MATCH_DIR,
        "app_icon_match_plan_*.json",
        f"未找到应用 icon 映射文件，请传 --mapping-json（目录: {APP_ICON_MATCH_DIR}）",
    )
    app_auth_from_mapping, mappings = load_mappings(mapping_path)

    app_auth_path = resolve_path(
        args.app_auth_json or (app_auth_from_mapping or ""),
        APP_AUTH_DIR,
        "app_authorize_*.json",
        f"未找到授权文件，请传 --app-auth-json（目录: {APP_AUTH_DIR}）",
    )
    app_auth_map = load_app_auth_rows(app_auth_path)

    org_auth = load_org_auth()
    org_app_key = str(org_auth.get("app_key", "")).strip()
    secret_key = str(org_auth.get("secret_key", "")).strip()
    project_id = args.project_id or str(org_auth.get("project_id", "")).strip()
    operator_id = args.operator_id or str(org_auth.get("owner_id", "")).strip()
    if not project_id:
        raise ValueError("缺少 projectId，请传 --project-id 或在 organization_auth.json 配置 project_id")
    if not operator_id:
        raise ValueError("缺少 operatorId，请传 --operator-id 或在 organization_auth.json 配置 owner_id")

    url = args.base_url.rstrip("/") + args.endpoint

    def _update_app_icon(idx_m):
        idx, m = idx_m
        app_id = m["appId"]
        icon = m["icon"]
        row = app_auth_map.get(app_id)
        if not row:
            raise ValueError(f"授权文件中不存在 appId: {app_id}")
        app_key = str(row.get("appKey", "")).strip()
        sign = str(row.get("sign", "")).strip()
        if not app_key or not sign:
            raise ValueError(f"授权记录缺少 appKey/sign: appId={app_id}")

        app_meta = fetch_app_meta(app_key=app_key, sign=sign)
        app_name = str(app_meta.get("name", "")).strip() or m.get("appName", "")
        color = str(app_meta.get("color", "")).strip() or "#00bcd4"

        timestamp_ms = int(time.time() * 1000)
        req_sign = build_sign(org_app_key, secret_key, timestamp_ms)
        payload = {
            "appKey": org_app_key, "sign": req_sign, "timestamp": timestamp_ms,
            "projectId": project_id, "appId": app_id, "name": app_name,
            "icon": icon, "color": color, "operatorId": operator_id,
        }

        if args.dry_run:
            return idx, {"appId": app_id, "payload": payload, "dry_run": True}

        resp = requests.post(url, json=payload, timeout=30)
        try:
            data = resp.json()
        except Exception:
            data = {"status_code": resp.status_code, "text": resp.text}
        return idx, {"appId": app_id, "status_code": resp.status_code, "response": data, "payload": payload}

    indexed: dict = {}
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = [executor.submit(_update_app_icon, (i, m)) for i, m in enumerate(mappings)]
        for future in as_completed(futures):
            idx, r = future.result()
            indexed[idx] = r
    results = [indexed[i] for i in range(len(mappings))]

    summary = {
        "source_mapping_json": str(mapping_path),
        "app_auth_json": str(app_auth_path),
        "endpoint": url,
        "total": len(results),
        "dry_run": args.dry_run,
        "results": results,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"app_icon_update_{ts}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    latest = RESULT_DIR / "app_icon_update_latest.json"
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n已保存: {out.resolve()}")
    print(f"已更新: {latest.resolve()}")


if __name__ == "__main__":
    main()
