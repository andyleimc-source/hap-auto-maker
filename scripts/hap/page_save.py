#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2g3 — 保存页面布局（Web POST https://api.mingdao.com/report/custom/savePage）

用法:
    uv run python3 hap-auto-maker/scripts/hap/page_save.py \
        --page-id <pageId> \
        [--version <version>]

示例（初始化空白页）:
    uv run python3 hap-auto-maker/scripts/hap/page_save.py --page-id <pageId> --version 0
"""

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_retry

BASE_DIR = Path(__file__).resolve().parents[2]
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
SAVE_PAGE_URL = "https://api.mingdao.com/report/custom/savePage"


def save_page(page_id: str, version: int, auth_config_path: Path) -> dict:
    body = {
        "appId": page_id,
        "version": version,
        "components": [],
        "adjustScreen": False,
        "urlParams": [],
        "config": {
            "pageStyleType": "light",
            "pageBgColor": "#f5f6f7",
            "chartColor": "",
            "chartColorIndex": 1,
            "numberChartColor": "",
            "numberChartColorIndex": 1,
            "pivoTableColor": "",
            "refresh": 0,
            "headerVisible": True,
            "shareVisible": True,
            "chartShare": True,
            "chartExportExcel": True,
            "downloadVisible": True,
            "fullScreenVisible": True,
            "customColors": [],
            "webNewCols": 48,
        },
    }
    resp = auth_retry.hap_web_post(SAVE_PAGE_URL, auth_config_path, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    is_ok = data.get("status") == 1 or data.get("success") is True
    if not is_ok:
        raise RuntimeError(f"savePage 失败: {data}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="2g3 — 保存页面布局（初始化空白页）")
    parser.add_argument("--page-id", required=True, help="页面 ID（pageId）")
    parser.add_argument("--version", type=int, default=0, help="页面版本号（默认 0，初始化空白页）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    args = parser.parse_args()

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    data = save_page(args.page_id, args.version, auth_config_path)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print("\nOK — savePage 成功")


if __name__ == "__main__":
    main()
