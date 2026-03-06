#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按关联修复计划批量更新关系字段。
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
    MOCK_RELATION_REPAIR_APPLY_DIR,
    MOCK_RELATION_REPAIR_PLAN_DIR,
    append_log,
    choose_app,
    discover_authorized_apps,
    load_json,
    make_log_path,
    make_output_path,
    resolve_json_input,
    update_row_relation,
    write_json_with_latest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="按修复计划应用关联关系")
    parser.add_argument("--repair-plan-json", required=True, help="mock_relation_repair_plan JSON 路径")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--trigger-workflow", action="store_true", help="更新时触发工作流")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际更新")
    parser.add_argument("--output", default="", help="更新结果 JSON 路径")
    args = parser.parse_args()

    plan_path = resolve_json_input(str(args.repair_plan_json), [MOCK_RELATION_REPAIR_PLAN_DIR])
    repair_plan = load_json(plan_path)
    app_id = str(repair_plan.get("app", {}).get("appId", "")).strip()
    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id or app_id, app_index=args.app_index)
    log_path = make_log_path("apply_relation_repair", app["appId"])
    append_log(
        log_path,
        "start",
        repairPlanJson=str(plan_path),
        appId=app["appId"],
        appName=app["appName"],
        dryRun=bool(args.dry_run),
        triggerWorkflow=bool(args.trigger_workflow),
    )

    worksheet_results = []
    total_failed = 0
    for worksheet in repair_plan.get("worksheets", []):
        updates = worksheet.get("updates", [])
        unresolved = worksheet.get("unresolved", [])
        already_resolved = worksheet.get("alreadyResolved", [])
        append_log(
            log_path,
            "worksheet_start",
            worksheetId=worksheet["worksheetId"],
            worksheetName=worksheet["worksheetName"],
            plannedCount=len(updates),
            unresolvedCount=len(unresolved),
            alreadyResolvedCount=len(already_resolved),
        )
        result_updates = []
        failed_count = 0
        for update in updates:
            try:
                response = {"success": True, "dryRun": args.dry_run}
                if not args.dry_run:
                    response = update_row_relation(
                        base_url=args.base_url,
                        app_key=app["appKey"],
                        sign=app["sign"],
                        worksheet_id=worksheet["worksheetId"],
                        row_id=update["rowId"],
                        field_id=update["relationFieldId"],
                        target_row_id=update["targetRowId"],
                        trigger_workflow=args.trigger_workflow,
                    )
                result_updates.append({**update, "response": response, "success": True})
                append_log(
                    log_path,
                    "update_success",
                    worksheetId=worksheet["worksheetId"],
                    rowId=update["rowId"],
                    relationFieldId=update["relationFieldId"],
                    targetRowId=update["targetRowId"],
                )
            except Exception as exc:
                failed_count += 1
                total_failed += 1
                result_updates.append(
                    {
                        **update,
                        "response": {"success": False, "error": str(exc)},
                        "success": False,
                    }
                )
                append_log(
                    log_path,
                    "update_failed",
                    worksheetId=worksheet["worksheetId"],
                    rowId=update["rowId"],
                    relationFieldId=update["relationFieldId"],
                    targetRowId=update["targetRowId"],
                    error=str(exc),
                )
        worksheet_results.append(
            {
                "worksheetId": worksheet["worksheetId"],
                "worksheetName": worksheet["worksheetName"],
                "processTier": worksheet["processTier"],
                "plannedCount": len(updates),
                "successCount": len([item for item in result_updates if item["success"]]),
                "failedCount": failed_count,
                "alreadyResolvedCount": len(already_resolved),
                "unresolvedCount": len(unresolved),
                "alreadyResolved": already_resolved,
                "unresolved": unresolved,
                "updates": result_updates,
            }
        )
        append_log(
            log_path,
            "worksheet_finished",
            worksheetId=worksheet["worksheetId"],
            worksheetName=worksheet["worksheetName"],
            successCount=len([item for item in result_updates if item["success"]]),
            failedCount=failed_count,
            unresolvedCount=len(unresolved),
        )

    result = {
        "schemaVersion": "mock_relation_repair_apply_result_v1",
        "sourcePlan": str(plan_path),
        "logFile": str(log_path),
        "app": repair_plan.get("app", {}),
        "triggerWorkflow": bool(args.trigger_workflow),
        "dryRun": bool(args.dry_run),
        "worksheets": worksheet_results,
        "summary": {
            "worksheetCount": len(worksheet_results),
            "plannedCount": sum(item["plannedCount"] for item in worksheet_results),
            "successCount": sum(item["successCount"] for item in worksheet_results),
            "failedCount": sum(item["failedCount"] for item in worksheet_results),
            "alreadyResolvedCount": sum(item["alreadyResolvedCount"] for item in worksheet_results),
            "unresolvedCount": sum(item["unresolvedCount"] for item in worksheet_results),
        },
    }
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else make_output_path(MOCK_RELATION_REPAIR_APPLY_DIR, "mock_relation_repair_apply_result", app["appId"])
    )
    write_json_with_latest(
        MOCK_RELATION_REPAIR_APPLY_DIR,
        output_path,
        "mock_relation_repair_apply_result_latest.json",
        result,
    )
    append_log(log_path, "finished", outputFile=str(output_path), summary=result["summary"])

    print("关联修复执行完成")
    print(f"- 应用: {app['appName']} ({app['appId']})")
    print(f"- 模式: {'dry-run' if args.dry_run else 'live'}")
    print(f"- 日志文件: {log_path}")
    print(f"- 成功更新: {result['summary']['successCount']}")
    print(f"- 更新失败: {result['summary']['failedCount']}")
    print(f"- 未解决: {result['summary']['unresolvedCount']}")
    print(f"- 结果文件: {output_path}")
    print(json.dumps([{k: ws[k] for k in ('worksheetName', 'plannedCount', 'successCount', 'failedCount', 'unresolvedCount')} for ws in worksheet_results], ensure_ascii=False, indent=2))
    if total_failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
