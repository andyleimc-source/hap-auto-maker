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
import re
import sys
import time
from pathlib import Path
from typing import List

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "organization_auth.json"
DEFAULT_BASE_URL = "https://api.mingdao.com"
ENDPOINT = "/v1/open/app/create"
ICON_JSON_PATH = BASE_DIR / "data" / "assets" / "icons" / "icon.json"
COLOR_POLICY_PATH = BASE_DIR / "config" / "policies" / "theme_color_policy.json"
DEFAULT_COLOR_POOL = [
    "#00BCD4",
    "#4CAF50",
    "#2196F3",
    "#FF9800",
    "#E91E63",
    "#9C27B0",
    "#3F51B5",
    "#009688",
    "#FF5722",
    "#795548",
    "#607D8B",
    "#F44336",
    "#673AB7",
    "#03A9F4",
    "#26A69A",
    "#1565C0",
    "#2E7D32",
    "#00838F",
    "#6A1B9A",
    "#AD1457",
    "#283593",
    "#EF6C00",
    "#C62828",
    "#37474F",
    "#5D4037",
    "#0277BD",
    "#00695C",
    "#4527A0",
    "#7B1FA2",
    "#880E4F",
    "#D84315",
    "#424242",
    "#546E7A",
    "#1E88E5",
    "#43A047",
    "#00897B",
    "#3949AB",
    "#8E24AA",
    "#D81B60",
    "#FB8C00",
    "#F4511E",
    "#6D4C41",
    "#0D47A1",
    "#1B5E20",
    "#004D40",
    "#311B92",
    "#4A148C",
    "#B71C1C",
    "#BF360C",
    "#263238",
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


def normalize_hex_color(color: str) -> str:
    c = (color or "").strip().upper()
    if not c:
        return ""
    if not c.startswith("#"):
        c = f"#{c}"
    if re.fullmatch(r"#[0-9A-F]{6}", c):
        return c
    return ""


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = normalize_hex_color(color)
    if not c:
        raise ValueError(f"非法颜色值: {color}")
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def _channel_to_linear(v: int) -> float:
    x = v / 255.0
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    r, g, b = hex_to_rgb(color)
    rl, gl, bl = _channel_to_linear(r), _channel_to_linear(g), _channel_to_linear(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def contrast_ratio_with_white(color: str) -> float:
    # 白字对背景色的对比度： (L1+0.05)/(L2+0.05)，L1为白色1.0
    lum = relative_luminance(color)
    return 1.05 / (lum + 0.05)


def load_color_policy() -> dict:
    if not COLOR_POLICY_PATH.exists():
        return {}
    data = json.loads(COLOR_POLICY_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def pick_random_safe_color() -> str:
    policy = load_color_policy()
    candidates = policy.get("candidate_colors")
    if not isinstance(candidates, list) or not candidates:
        candidates = DEFAULT_COLOR_POOL
    normalized_candidates = []
    for c in candidates:
        n = normalize_hex_color(str(c))
        if n:
            normalized_candidates.append(n)

    excluded = set()
    for c in policy.get("exclude_hex", []) if isinstance(policy.get("exclude_hex"), list) else []:
        n = normalize_hex_color(str(c))
        if n:
            excluded.add(n)

    rule = policy.get("white_text_accessibility", {}) if isinstance(policy.get("white_text_accessibility"), dict) else {}
    enabled = bool(rule.get("enabled", True))
    min_contrast = float(rule.get("min_contrast_ratio", 4.5))
    max_luminance = float(rule.get("max_luminance", 0.18))

    safe_colors = []
    for c in normalized_candidates:
        if c in excluded:
            continue
        if not enabled:
            safe_colors.append(c)
            continue
        lum = relative_luminance(c)
        cr = contrast_ratio_with_white(c)
        if lum <= max_luminance and cr >= min_contrast:
            safe_colors.append(c)

    if safe_colors:
        return random.choice(safe_colors)
    if normalized_candidates:
        # 如果策略过严导致全被过滤，退回候选池，保证可用性
        return random.choice(normalized_candidates)
    return "#00BCD4"


def main() -> None:
    # 尝试加载本地默认分组
    local_group_id = ""
    try:
        sys.path.append(str(Path(__file__).resolve().parent))
        from local_config import load_local_group_id
        local_group_id = load_local_group_id()
    except Exception:
        pass

    auth = load_org_auth()
    app_key = auth["app_key"]
    secret_key = auth["secret_key"]
    default_project_id = auth.get("project_id", "")
    default_owner_id = auth.get("owner_id", "")
    
    # 优先级：.env.local > organization_auth.json
    default_group_ids = local_group_id if local_group_id else auth.get("group_ids", "").strip()

    parser = argparse.ArgumentParser(description="创建 HAP 应用")
    parser.add_argument("--name", required=True, help="应用名称")
    parser.add_argument("--icon", default="", help="图标名称，如 0_lego")
    parser.add_argument("--color", default="", help="主题颜色，如 #00bcd4")
    parser.add_argument(
        "--group-ids",
        default=default_group_ids if default_group_ids else None,
        help="应用分组Id列表，逗号分隔 (可选，默认不指定分组)",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求体，不发送")
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
        color_value = pick_random_safe_color()
        cr = contrast_ratio_with_white(color_value)
        print(f"随机选择 color: {color_value} (white-contrast={cr:.2f})", file=sys.stderr)

    timestamp_ms = int(time.time() * 1000)
    sign = build_sign(app_key, secret_key, timestamp_ms)

    # 处理 group_ids: 只有非空且不是占位符时才加入 payload
    group_ids_list = parse_group_ids(args.group_ids)
    
    payload = {
        "appKey": app_key,
        "sign": sign,
        "timestamp": timestamp_ms,
        "projectId": args.project_id,
        "name": args.name,
        "icon": icon_value,
        "color": color_value,
        "ownerId": args.owner_id,
        "groupIds": group_ids_list if group_ids_list else None,
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

    if not data.get("success") and data.get("error_code") == 10102:
        masked_key = app_key[:4] + "****" + app_key[-4:] if len(app_key) >= 8 else "****"
        masked_secret = secret_key[:4] + "****" if len(secret_key) >= 4 else "****"
        print(
            f"\n[诊断] 签名不合法，请检查 organization_auth.json 中的凭据：\n"
            f"  app_key    = {masked_key} (长度 {len(app_key)})\n"
            f"  secret_key = {masked_secret} (长度 {len(secret_key)})\n"
            f"  project_id = {args.project_id}\n"
            f"  owner_id   = {args.owner_id}\n"
            f"  group_ids  = {args.group_ids}\n"
            f"  提示: 运行 python3 setup.py --force 重新配置",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
