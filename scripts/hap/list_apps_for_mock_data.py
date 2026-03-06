#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输出可用于造数的应用 JSON。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import (
    DEFAULT_BASE_URL,
    MOCK_APP_INVENTORY_DIR,
    discover_authorized_apps,
    make_output_path,
    write_json_with_latest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="输出可用于 HAP 造数的应用列表 JSON")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    parser.add_argument("--pretty", action="store_true", help="终端额外打印可读表格")
    args = parser.parse_args()

    apps = discover_authorized_apps(base_url=args.base_url)
    result = {
        "schemaVersion": "mock_data_app_inventory_v1",
        "count": len(apps),
        "apps": [
            {
                "index": app["index"],
                "appId": app["appId"],
                "appName": app["appName"],
                "authFile": app["authFile"],
                "authPath": app["authPath"],
                "createTime": app["createTime"],
            }
            for app in apps
        ],
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = make_output_path(MOCK_APP_INVENTORY_DIR, "mock_data_app_inventory", "all")

    write_json_with_latest(MOCK_APP_INVENTORY_DIR, output_path, "mock_data_app_inventory_latest.json", result)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.pretty:
        print("\n应用概览：")
        for app in apps:
            print(f"- [{app['index']}] {app['appName']} ({app['appId']})")


if __name__ == "__main__":
    main()
