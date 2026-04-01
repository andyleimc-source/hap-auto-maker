#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2g2 — 获取页面内容（Web POST https://api.mingdao.com/report/custom/getPage）

用法:
    uv run python3 hap-auto-maker/scripts/hap/page_get.py \
        --page-id <pageId>
"""

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_retry

BASE_DIR = Path(__file__).resolve().parents[2]
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
GET_PAGE_URL = "https://api.mingdao.com/report/custom/getPage"


def get_page(page_id: str, auth_config_path: Path) -> dict:
    resp = auth_retry.hap_web_get(GET_PAGE_URL, auth_config_path, params={"appId": page_id}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    is_ok = data.get("status") == 1 or data.get("success") is True
    if not is_ok:
        raise RuntimeError(f"getPage 失败: {data}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="2g2 — 获取页面内容")
    parser.add_argument("--page-id", required=True, help="页面 ID（pageId）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    args = parser.parse_args()

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    data = get_page(args.page_id, auth_config_path)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
