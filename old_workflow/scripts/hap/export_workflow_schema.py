#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选择应用并导出工作流规划所需 schema。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from workflow_common import (
    DEFAULT_BASE_URL,
    WORKFLOW_SCHEMA_DIR,
    append_log,
    build_workflow_schema_snapshot,
    choose_app,
    discover_authorized_apps,
    ensure_workflow_dirs,
    make_workflow_log_path,
    make_workflow_output_path,
    write_json_with_latest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="选择一个应用并导出工作流 schema JSON")
    parser.add_argument("--app-id", default="", help="指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    ensure_workflow_dirs()
    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id, app_index=args.app_index)
    log_path = make_workflow_log_path("workflow_schema", app["appId"])
    append_log(
        log_path,
        "start",
        appId=app["appId"],
        appName=app["appName"],
        baseUrl=args.base_url,
    )

    snapshot = build_workflow_schema_snapshot(args.base_url, app, log_path=log_path)
    snapshot["logFile"] = str(log_path)

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = make_workflow_output_path(WORKFLOW_SCHEMA_DIR, "workflow_schema_snapshot", app["appId"])

    write_json_with_latest(
        WORKFLOW_SCHEMA_DIR,
        output_path,
        "workflow_schema_snapshot_latest.json",
        snapshot,
    )
    append_log(
        log_path,
        "finished",
        outputFile=str(output_path),
        worksheetCount=len(snapshot.get("worksheets", [])),
        dateFieldCount=len(snapshot.get("workflowPlanningHints", {}).get("dateFields", [])),
        warningCount=len(snapshot.get("warnings", [])),
    )

    print("工作流 schema 导出完成")
    print(f"- 应用: {snapshot['app']['appName']} ({snapshot['app']['appId']})")
    print(f"- 工作表数量: {len(snapshot.get('worksheets', []))}")
    print(f"- 日期字段数量: {len(snapshot.get('workflowPlanningHints', {}).get('dateFields', []))}")
    print(f"- 结果文件: {output_path}")
    print(f"- 日志文件: {log_path}")
    print(json.dumps(snapshot.get("workflowPlanningHints", {}), ensure_ascii=False, indent=2))
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {log_path}")


if __name__ == "__main__":
    main()
