#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
删除关联修复后仍 unresolved 的源记录。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import (
    DEFAULT_BASE_URL,
    MOCK_RELATION_REPAIR_APPLY_DIR,
    MOCK_UNRESOLVED_DELETE_DIR,
    append_log,
    choose_app,
    delete_rows_batch,
    discover_authorized_apps,
    load_json,
    make_log_path,
    make_output_path,
    resolve_json_input,
    write_json_with_latest,
)


def collect_delete_candidates(apply_result: dict) -> List[dict]:
    worksheet_items = []
    for worksheet in apply_result.get("worksheets", []):
        if not isinstance(worksheet, dict):
            continue
        unresolved = worksheet.get("unresolved", [])
        row_map: Dict[str, dict] = {}
        for item in unresolved:
            if not isinstance(item, dict):
                continue
            row_id = str(item.get("rowId", "")).strip()
            if not row_id:
                continue
            entry = row_map.setdefault(
                row_id,
                {
                    "rowId": row_id,
                    "mockRecordKey": str(item.get("mockRecordKey", "")).strip(),
                    "reasons": [],
                    "relationFields": [],
                },
            )
            reason = str(item.get("reason", "")).strip()
            field_name = str(item.get("relationFieldName", "")).strip()
            if reason and reason not in entry["reasons"]:
                entry["reasons"].append(reason)
            if field_name and field_name not in entry["relationFields"]:
                entry["relationFields"].append(field_name)
        worksheet_items.append(
            {
                "worksheetId": worksheet["worksheetId"],
                "worksheetName": worksheet["worksheetName"],
                "processTier": worksheet.get("processTier"),
                "unresolvedCount": len(unresolved),
                "deleteCandidates": list(row_map.values()),
            }
        )
    return worksheet_items


def main() -> None:
    parser = argparse.ArgumentParser(description="删除 unresolved 对应的源记录")
    parser.add_argument("--repair-apply-result-json", required=True, help="关联修复执行结果 JSON 路径")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--trigger-workflow", action="store_true", help="删除时触发工作流")
    parser.add_argument("--permanent", action="store_true", help="永久删除，不进入回收站")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际删除")
    parser.add_argument("--output", default="", help="删除结果 JSON 路径")
    args = parser.parse_args()

    apply_result_path = resolve_json_input(str(args.repair_apply_result_json), [MOCK_RELATION_REPAIR_APPLY_DIR])
    apply_result = load_json(apply_result_path)
    app_id = str(apply_result.get("app", {}).get("appId", "")).strip()
    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id or app_id, app_index=args.app_index)
    log_path = make_log_path("delete_unresolved_records", app["appId"])
    append_log(
        log_path,
        "start",
        repairApplyResultJson=str(apply_result_path),
        appId=app["appId"],
        appName=app["appName"],
        dryRun=bool(args.dry_run),
        permanent=bool(args.permanent),
        triggerWorkflow=bool(args.trigger_workflow),
    )

    worksheet_candidates = collect_delete_candidates(apply_result)
    worksheet_results = []
    total_failed = 0
    for worksheet in worksheet_candidates:
        candidates = worksheet["deleteCandidates"]
        row_ids = [item["rowId"] for item in candidates]
        append_log(
            log_path,
            "worksheet_start",
            worksheetId=worksheet["worksheetId"],
            worksheetName=worksheet["worksheetName"],
            unresolvedCount=worksheet["unresolvedCount"],
            deleteCandidateCount=len(candidates),
        )
        response = {"success": True, "dryRun": args.dry_run}
        failed_count = 0
        if row_ids:
            try:
                if not args.dry_run:
                    response = delete_rows_batch(
                        base_url=args.base_url,
                        app_key=app["appKey"],
                        sign=app["sign"],
                        worksheet_id=worksheet["worksheetId"],
                        row_ids=row_ids,
                        permanent=args.permanent,
                        trigger_workflow=args.trigger_workflow,
                    )
                append_log(
                    log_path,
                    "worksheet_deleted",
                    worksheetId=worksheet["worksheetId"],
                    deleteCandidateCount=len(candidates),
                    rowIds=row_ids,
                )
            except Exception as exc:
                response = {"success": False, "error": str(exc)}
                failed_count = len(candidates)
                total_failed += failed_count
                append_log(
                    log_path,
                    "worksheet_delete_failed",
                    worksheetId=worksheet["worksheetId"],
                    worksheetName=worksheet["worksheetName"],
                    error=str(exc),
                    rowIds=row_ids,
                )
        worksheet_results.append(
            {
                "worksheetId": worksheet["worksheetId"],
                "worksheetName": worksheet["worksheetName"],
                "processTier": worksheet["processTier"],
                "unresolvedCount": worksheet["unresolvedCount"],
                "deletePlannedCount": len(candidates),
                "deleteSuccessCount": 0 if failed_count else len(candidates),
                "deleteFailedCount": failed_count,
                "deleteCandidates": candidates,
                "response": response,
            }
        )
        append_log(
            log_path,
            "worksheet_finished",
            worksheetId=worksheet["worksheetId"],
            worksheetName=worksheet["worksheetName"],
            deletePlannedCount=len(candidates),
            deleteFailedCount=failed_count,
        )

    result = {
        "schemaVersion": "mock_unresolved_delete_result_v1",
        "sourceRepairApplyResult": str(apply_result_path),
        "logFile": str(log_path),
        "app": apply_result.get("app", {}),
        "dryRun": bool(args.dry_run),
        "permanent": bool(args.permanent),
        "triggerWorkflow": bool(args.trigger_workflow),
        "worksheets": worksheet_results,
        "summary": {
            "worksheetCount": len(worksheet_results),
            "unresolvedCount": sum(item["unresolvedCount"] for item in worksheet_results),
            "deletePlannedCount": sum(item["deletePlannedCount"] for item in worksheet_results),
            "deleteSuccessCount": sum(item["deleteSuccessCount"] for item in worksheet_results),
            "deleteFailedCount": sum(item["deleteFailedCount"] for item in worksheet_results),
        },
    }
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else make_output_path(MOCK_UNRESOLVED_DELETE_DIR, "mock_unresolved_delete_result", app["appId"])
    )
    write_json_with_latest(
        MOCK_UNRESOLVED_DELETE_DIR,
        output_path,
        "mock_unresolved_delete_result_latest.json",
        result,
    )
    append_log(log_path, "finished", outputFile=str(output_path), summary=result["summary"])

    print("unresolved 记录删除完成")
    print(f"- 应用: {app['appName']} ({app['appId']})")
    print(f"- 模式: {'dry-run' if args.dry_run else 'live'}")
    print(f"- 删除方式: {'永久删除' if args.permanent else '逻辑删除'}")
    print(f"- 日志文件: {log_path}")
    print(f"- 计划删除: {result['summary']['deletePlannedCount']}")
    print(f"- 删除成功: {result['summary']['deleteSuccessCount']}")
    print(f"- 删除失败: {result['summary']['deleteFailedCount']}")
    print(f"- 结果文件: {output_path}")
    print(json.dumps([{k: ws[k] for k in ("worksheetName", "deletePlannedCount", "deleteSuccessCount", "deleteFailedCount")} for ws in worksheet_results], ensure_ascii=False, indent=2))
    if total_failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
