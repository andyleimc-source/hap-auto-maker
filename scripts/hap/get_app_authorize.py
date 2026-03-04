#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 组织授权接口：获取应用授权信息
调用 /v1/open/app/getAppAuthorize，并将结果保存到本地 JSON 文件。
"""

import argparse
import base64
import hashlib
import json
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "organization_auth.json"
DEFAULT_BASE_URL = "https://api.mingdao.com"
ENDPOINT = "/v1/open/app/getAppAuthorize"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"


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


def main() -> None:
    parser = argparse.ArgumentParser(description="获取 HAP 应用授权信息并保存到本地 JSON")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求参数，不发送")
    parser.add_argument(
        "--output",
        default="",
        help="输出文件路径（默认: data/outputs/app_authorizations/app_authorize_<appId>.json）",
    )

    auth = load_org_auth()
    app_key = auth["app_key"]
    secret_key = auth["secret_key"]
    default_project_id = auth.get("project_id", "")

    parser.add_argument("--project-id", default=default_project_id, help="HAP 组织Id")
    args = parser.parse_args()

    if not args.project_id:
        raise ValueError("缺少 projectId，请通过 --project-id 或在配置中设置 project_id")

    timestamp_ms = int(time.time() * 1000)
    sign = build_sign(app_key, secret_key, timestamp_ms)

    params = {
        "appKey": app_key,
        "sign": sign,
        "timestamp": timestamp_ms,
        "projectId": args.project_id,
        "appId": args.app_id,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        APP_AUTH_DIR.mkdir(parents=True, exist_ok=True)
        output_path = (APP_AUTH_DIR / f"app_authorize_{args.app_id}.json").resolve()

    if args.dry_run:
        print(json.dumps({"url": args.base_url.rstrip('/') + ENDPOINT, "params": params}, ensure_ascii=False, indent=2))
        print(f"output: {output_path}")
        return

    url = args.base_url.rstrip("/") + ENDPOINT
    resp = requests.get(url, params=params, timeout=30)
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n已保存: {output_path}")


if __name__ == "__main__":
    main()
