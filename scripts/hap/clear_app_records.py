#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清空指定应用下所有工作表的全部记录。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import (
    APP_RECORD_CLEAR_DIR,
    DEFAULT_BASE_URL,
    append_log,
    choose_app,
    delete_rows_batch,
    discover_authorized_apps,
    fetch_app_worksheets,
    fetch_rows,
    make_log_path,
    make_output_path,
    write_json_with_latest,
)


def chunked(items: List[str], size: int) -> List[List[str]]:
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def collect_worksheet_rows(base_url: str, app: dict, worksheet: dict) -> Dict[str, object]:
    rows = fetch_rows(
        base_url=base_url,
        app_key=app["appKey"],
        sign=app["sign"],
        worksheet_id=worksheet["worksheetId"],
        fields=["rowid"],
        include_system_fields=True,
    )
    row_ids: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("rowid", "")).strip()
        if row_id:
            row_ids.append(row_id)
    return {
        "worksheetId": worksheet["worksheetId"],
        "worksheetName": worksheet["worksheetName"],
        "appSectionId": worksheet.get("appSectionId", ""),
        "appSectionName": worksheet.get("appSectionName", ""),
        "rowIds": row_ids,
        "rowCount": len(row_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="清空指定应用下所有工作表的全部记录")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--trigger-workflow", action="store_true", help="删除时触发工作流")
    parser.add_argument("--permanent", action="store_true", help="永久删除，不进入回收站")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际删除")
    parser.add_argument("--batch-size", type=int, default=500, help="每批删除的记录数，默认 500")
    parser.add_argument("--output", default="", help="结果 JSON 路径")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size 必须大于 0")

    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id, app_index=args.app_index)
    _, worksheets = fetch_app_worksheets(args.base_url, app["appKey"], app["sign"])

    log_path = make_log_path("clear_app_records", app["appId"])
    append_log(
        log_path,
        "start",
        appId=app["appId"],
        appName=app["appName"],
        worksheetCount=len(worksheets),
        dryRun=bool(args.dry_run),
        permanent=bool(args.permanent),
        triggerWorkflow=bool(args.trigger_workflow),
        batchSize=int(args.batch_size),
    )

    worksheet_results = []
    total_batches = 0
    total_failed = 0
    total_deleted = 0
    total_planned = 0

    for worksheet in worksheets:
        worksheet_info = collect_worksheet_rows(args.base_url, app, worksheet)
        row_ids = list(worksheet_info["rowIds"])
        batches = chunked(row_ids, args.batch_size)
        total_planned += len(row_ids)
        total_batches += len(batches)
        append_log(
            log_path,
            "worksheet_start",
            worksheetId=worksheet_info["worksheetId"],
            worksheetName=worksheet_info["worksheetName"],
            rowCount=worksheet_info["rowCount"],
            batchCount=len(batches),
        )

        batch_results = []
        deleted_count = 0
        failed_count = 0

        for idx, batch_row_ids in enumerate(batches, start=1):
            response = {"success": True, "dryRun": True} if args.dry_run else {}
            try:
                if not args.dry_run:
                    response = delete_rows_batch(
                        base_url=args.base_url,
                        app_key=app["appKey"],
                        sign=app["sign"],
                        worksheet_id=str(worksheet_info["worksheetId"]),
                        row_ids=batch_row_ids,
                        permanent=args.permanent,
                        trigger_workflow=args.trigger_workflow,
                    )
                deleted_count += len(batch_row_ids)
                append_log(
                    log_path,
                    "batch_deleted",
                    worksheetId=worksheet_info["worksheetId"],
                    worksheetName=worksheet_info["worksheetName"],
                    batchIndex=idx,
                    batchSize=len(batch_row_ids),
                )
            except Exception as exc:
                failed_count += len(batch_row_ids)
                total_failed += len(batch_row_ids)
                response = {"success": False, "error": str(exc)}
                append_log(
                    log_path,
                    "batch_delete_failed",
                    worksheetId=worksheet_info["worksheetId"],
                    worksheetName=worksheet_info["worksheetName"],
                    batchIndex=idx,
                    batchSize=len(batch_row_ids),
                    error=str(exc),
                )
            batch_results.append(
                {
                    "batchIndex": idx,
                    "plannedCount": len(batch_row_ids),
                    "successCount": 0 if "error" in response else len(batch_row_ids),
                    "failedCount": len(batch_row_ids) if "error" in response else 0,
                    "response": response,
                }
            )

        total_deleted += deleted_count
        worksheet_results.append(
            {
                "worksheetId": worksheet_info["worksheetId"],
                "worksheetName": worksheet_info["worksheetName"],
                "appSectionId": worksheet_info["appSectionId"],
                "appSectionName": worksheet_info["appSectionName"],
                "rowCount": worksheet_info["rowCount"],
                "batchCount": len(batches),
                "deletePlannedCount": len(row_ids),
                "deleteSuccessCount": deleted_count,
                "deleteFailedCount": failed_count,
                "batches": batch_results,
            }
        )
        append_log(
            log_path,
            "worksheet_finished",
            worksheetId=worksheet_info["worksheetId"],
            worksheetName=worksheet_info["worksheetName"],
            deletePlannedCount=len(row_ids),
            deleteSuccessCount=deleted_count,
            deleteFailedCount=failed_count,
        )

    result = {
        "schemaVersion": "app_record_clear_result_v1",
        "logFile": str(log_path),
        "app": {
            "appId": app["appId"],
            "appName": app["appName"],
            "authPath": app["authPath"],
            "authFile": app["authFile"],
        },
        "dryRun": bool(args.dry_run),
        "permanent": bool(args.permanent),
        "triggerWorkflow": bool(args.trigger_workflow),
        "batchSize": int(args.batch_size),
        "worksheets": worksheet_results,
        "summary": {
            "worksheetCount": len(worksheet_results),
            "batchCount": total_batches,
            "deletePlannedCount": total_planned,
            "deleteSuccessCount": total_deleted,
            "deleteFailedCount": total_failed,
        },
    }

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else make_output_path(APP_RECORD_CLEAR_DIR, "app_record_clear_result", app["appId"])
    )
    write_json_with_latest(
        APP_RECORD_CLEAR_DIR,
        output_path,
        "app_record_clear_result_latest.json",
        result,
    )
    append_log(log_path, "finished", outputFile=str(output_path), summary=result["summary"])

    print("应用记录清空完成")
    print(f"- 应用: {app['appName']} ({app['appId']})")
    print(f"- 模式: {'dry-run' if args.dry_run else 'live'}")
    print(f"- 删除方式: {'永久删除' if args.permanent else '逻辑删除'}")
    print(f"- 工作表数: {result['summary']['worksheetCount']}")
    print(f"- 计划删除: {result['summary']['deletePlannedCount']}")
    print(f"- 删除成功: {result['summary']['deleteSuccessCount']}")
    print(f"- 删除失败: {result['summary']['deleteFailedCount']}")
    print(f"- 日志文件: {log_path}")
    print(f"- 结果文件: {output_path}")

    if total_failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
