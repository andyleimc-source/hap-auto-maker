#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导出应用结构快照，供造数和关联规划使用。
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
    MOCK_SCHEMA_DIR,
    append_log,
    build_schema_snapshot,
    choose_app,
    discover_authorized_apps,
    make_log_path,
    make_output_path,
    write_json_with_latest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="导出应用的工作表结构与关系快照")
    parser.add_argument("--app-id", default="", help="指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id, app_index=args.app_index)
    log_path = make_log_path("export_mock_schema", app["appId"])
    append_log(log_path, "start", appId=app["appId"], appName=app["appName"], baseUrl=args.base_url)
    snapshot = build_schema_snapshot(args.base_url, app)

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = make_output_path(MOCK_SCHEMA_DIR, "mock_schema_snapshot", app["appId"])

    snapshot["logFile"] = str(log_path)
    write_json_with_latest(MOCK_SCHEMA_DIR, output_path, "mock_schema_snapshot_latest.json", snapshot)
    for worksheet in snapshot.get("worksheets", []):
        append_log(
            log_path,
            "worksheet_snapshot",
            worksheetId=worksheet["worksheetId"],
            worksheetName=worksheet["worksheetName"],
            fieldCount=len(worksheet.get("fields", [])),
            writableFieldCount=len(worksheet.get("writableFields", [])),
            skippedFieldCount=len(worksheet.get("skippedFields", [])),
            tier=worksheet.get("tier"),
            recordCount=worksheet.get("recordCount"),
        )
    append_log(
        log_path,
        "finished",
        outputFile=str(output_path),
        worksheetCount=len(snapshot.get("worksheets", [])),
        relationEdgeCount=len(snapshot.get("relationEdges", [])),
        relationPairCount=len(snapshot.get("relationPairs", [])),
        warningCount=len(snapshot.get("warnings", [])),
    )

    print("结构快照导出完成")
    print(f"- 应用: {snapshot['app']['appName']} ({snapshot['app']['appId']})")
    print(f"- 日志文件: {log_path}")
    print(f"- 工作表数量: {len(snapshot.get('worksheets', []))}")
    print(f"- 关系边数量: {len(snapshot.get('relationEdges', []))}")
    print(f"- 关系对数量: {len(snapshot.get('relationPairs', []))}")
    print(f"- warnings: {len(snapshot.get('warnings', []))}")
    print(f"- 结果文件: {output_path}")
    print(json.dumps(snapshot["worksheetTiers"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
