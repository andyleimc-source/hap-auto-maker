#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 组织授权接口：创建应用
基于组织密钥 AppKey/SecretKey 生成签名后调用 /v1/open/app/create
"""

import argparse
import base64
import hashlib
import json
import random
import sys
import time
from pathlib import Path
from typing import List

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "organization_auth.json"
DEFAULT_BASE_URL = "https://api.mingdao.com"
ENDPOINT = "/v1/open/app/create"
DEFAULT_GROUP_IDS = "69a794589860d96373beeb4d"
ICON_JSON_PATH = BASE_DIR / "data" / "assets" / "icons" / "icon.json"
COLOR_POOL = [
    "#00bcd4",
    "#4caf50",
    "#2196f3",
    "#ff9800",
    "#e91e63",
    "#9c27b0",
    "#3f51b5",
    "#009688",
    "#8bc34a",
    "#ffc107",
    "#ff5722",
    "#795548",
    "#607d8b",
    "#f44336",
    "#673ab7",
    "#03a9f4",
    "#cddc39",
    "#ffeb3b",
    "#ff6f61",
    "#26a69a",
]


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


def parse_group_ids(value: str) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def collect_icon_file_names(node) -> List[str]:
    result: List[str] = []
    if isinstance(node, dict):
        file_name = node.get("fileName")
        if isinstance(file_name, str) and file_name.strip():
            result.append(file_name.strip())
        for value in node.values():
            result.extend(collect_icon_file_names(value))
    elif isinstance(node, list):
        for item in node:
            result.extend(collect_icon_file_names(item))
    return result


def pick_random_icon() -> str:
    if not ICON_JSON_PATH.exists():
        raise FileNotFoundError(f"缺少图标文件: {ICON_JSON_PATH}")
    data = json.loads(ICON_JSON_PATH.read_text(encoding="utf-8"))
    file_names = collect_icon_file_names(data)
    if not file_names:
        raise ValueError(f"图标文件中未找到可用 fileName: {ICON_JSON_PATH}")
    return random.choice(file_names)


def main() -> None:
    parser = argparse.ArgumentParser(description="创建 HAP 应用")
    parser.add_argument("--name", required=True, help="应用名称")
    parser.add_argument("--icon", default="", help="图标名称，如 0_lego")
    parser.add_argument("--color", default="", help="主题颜色，如 #00bcd4")
    parser.add_argument(
        "--group-ids",
        default=DEFAULT_GROUP_IDS,
        help="应用分组Id列表，逗号分隔",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求体，不发送")
    auth = load_org_auth()
    app_key = auth["app_key"]
    secret_key = auth["secret_key"]
    default_project_id = auth.get("project_id", "")
    default_owner_id = auth.get("owner_id", "")

    parser.add_argument("--project-id", default=default_project_id, help="HAP 组织Id")
    parser.add_argument("--owner-id", default=default_owner_id, help="应用拥有者 HAP 账号Id")
    args = parser.parse_args()

    if not args.project_id:
        raise ValueError("缺少 projectId，请通过 --project-id 或在配置中设置 project_id")
    if not args.owner_id:
        raise ValueError("缺少 ownerId，请通过 --owner-id 或在配置中设置 owner_id")

    icon_value = args.icon.strip() if args.icon else ""
    if not icon_value:
        icon_value = pick_random_icon()
        print(f"随机选择 icon: {icon_value}", file=sys.stderr)

    color_value = args.color.strip() if args.color else ""
    if not color_value:
        color_value = random.choice(COLOR_POOL)
        print(f"随机选择 color: {color_value}", file=sys.stderr)

    timestamp_ms = int(time.time() * 1000)
    sign = build_sign(app_key, secret_key, timestamp_ms)

    payload = {
        "appKey": app_key,
        "sign": sign,
        "timestamp": timestamp_ms,
        "projectId": args.project_id,
        "name": args.name,
        "icon": icon_value,
        "color": color_value,
        "ownerId": args.owner_id,
        "groupIds": parse_group_ids(args.group_ids) or None,
    }
    # remove None fields
    payload = {k: v for k, v in payload.items() if v is not None}

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    url = args.base_url.rstrip("/") + ENDPOINT
    resp = requests.post(url, json=payload, timeout=30)
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise

    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
