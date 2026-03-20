#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据 mock_data_bundle 顺序写入记录。
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
    MOCK_BUNDLE_DIR,
    MOCK_WRITE_RESULT_DIR,
    add_worksheet_row_with_fallback,
    append_log,
    build_v3_fields,
    choose_app,
    discover_authorized_apps,
    load_json,
    load_web_auth,
    make_log_path,
    make_output_path,
    resolve_json_input,
    summarize_write_result,
    write_json_with_latest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="按规划顺序写入 mock 数据")
    parser.add_argument("--bundle-json", required=True, help="mock_data_bundle JSON 路径")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--trigger-workflow", action="store_true", help="写入时触发工作流")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际写入")
    parser.add_argument("--output", default="", help="写入结果 JSON 路径")
    args = parser.parse_args()

    bundle_path = resolve_json_input(str(args.bundle_json), [MOCK_BUNDLE_DIR])
    bundle = load_json(bundle_path)
    app_id = str(bundle.get("app", {}).get("appId", "")).strip()
    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id or app_id, app_index=args.app_index)
    web_auth = load_web_auth()
    log_path = make_log_path("write_mock_data", app["appId"])
    append_log(
        log_path,
        "start",
        bundleJson=str(bundle_path),
        appId=app["appId"],
        appName=app["appName"],
        dryRun=bool(args.dry_run),
        triggerWorkflow=bool(args.trigger_workflow),
    )

    worksheets = bundle.get("worksheets", [])
    if not isinstance(worksheets, list):
        raise ValueError("bundle.worksheets 格式错误")

    result_worksheets = []
    created_records_by_ws: Dict[str, List[dict]] = {}
    error_message = ""
    for worksheet in sorted(worksheets, key=lambda item: (int(item.get("order", 0) or 0), item.get("worksheetName", ""))):
        records = worksheet.get("records", [])
        if not isinstance(records, list):
            raise ValueError(f"记录列表格式错误: {worksheet}")
        field_metas = worksheet.get("fieldMetas", [])
        if not isinstance(field_metas, list):
            field_metas = worksheet.get("writableFieldMetas", [])
        if not isinstance(field_metas, list):
            field_metas = []
        field_meta_map = {
            str(field.get("fieldId", "")).strip(): {
                "name": str(field.get("name", "")).strip(),
                "type": str(field.get("type", "")).strip(),
                "controlType": int(field.get("controlType", 0) or 0),
            }
            for field in field_metas
            if isinstance(field, dict) and str(field.get("fieldId", "")).strip()
        }
        required_relation_fields = worksheet.get("requiredRelationFields", [])
        if not isinstance(required_relation_fields, list):
            required_relation_fields = []
        append_log(
            log_path,
            "worksheet_start",
            worksheetId=worksheet["worksheetId"],
            worksheetName=worksheet["worksheetName"],
            order=worksheet["order"],
            plannedCount=len(records),
        )
        created_records = []
        row_plan = []
        response = {"success": True, "dryRun": args.dry_run}
        failed_count = 0
        try:
            enriched_records = []
            for index, record in enumerate(records):
                if not isinstance(record, dict):
                    raise ValueError(f"记录格式错误: {record}")
                values = record.get("valuesByFieldId", {})
                if not isinstance(values, dict):
                    raise ValueError(f"valuesByFieldId 格式错误: {record}")
                final_values = dict(values)
                for rel in required_relation_fields:
                    if not isinstance(rel, dict):
                        continue
                    field_id = str(rel.get("fieldId", "")).strip()
                    target_ws_id = str(rel.get("targetWorksheetId", "")).strip()
                    if not field_id or not target_ws_id or field_id in final_values:
                        continue
                    target_records = created_records_by_ws.get(target_ws_id, [])
                    if not target_records:
                        print(f"[警告] 必填关联字段缺少可用目标记录，已跳过该字段: worksheet={worksheet['worksheetName']}, field={rel.get('fieldName', field_id)}, targetWorksheetId={target_ws_id}")
                        continue
                    target_row_id = str(target_records[index % len(target_records)].get("rowId", "")).strip()
                    if not target_row_id:
                        print(f"[警告] 必填关联字段目标记录缺少 rowId，已跳过该字段: worksheet={worksheet['worksheetName']}, field={rel.get('fieldName', field_id)}, targetWorksheetId={target_ws_id}")
                        continue
                    final_values[field_id] = [target_row_id]
                enriched_record = dict(record)
                enriched_record["valuesByFieldId"] = final_values
                enriched_records.append(enriched_record)

            row_plan = []
            for record in enriched_records:
                row_plan.append({"fields": build_v3_fields(record, field_meta_map)})
            append_log(
                log_path,
                "worksheet_rows_built",
                worksheetId=worksheet["worksheetId"],
                requestRowCount=len(row_plan),
                firstMockRecordKey=enriched_records[0]["mockRecordKey"] if enriched_records else "",
                lastMockRecordKey=enriched_records[-1]["mockRecordKey"] if enriched_records else "",
            )
            row_ids: List[str] = []
            written_enriched_records: List[dict] = []
            if args.dry_run:
                row_ids = [f"dryrun-{item['mockRecordKey']}" for item in enriched_records]
                written_enriched_records = list(enriched_records)
            else:
                account_id, authorization, cookie = web_auth
                row_responses = []
                total_to_write = len(enriched_records)
                print(f"  正在写入 [{worksheet['worksheetName']}] (共 {total_to_write} 条)...", end="", flush=True)
                for i, record in enumerate(enriched_records):
                    api_resp = add_worksheet_row_with_fallback(
                        base_url=args.base_url,
                        app_key=app["appKey"],
                        sign=app["sign"],
                        account_id=account_id,
                        authorization=authorization,
                        cookie=cookie,
                        app_id=app["appId"],
                        worksheet_id=worksheet["worksheetId"],
                        record=record,
                        field_meta_map=field_meta_map,
                        trigger_workflow=bool(args.trigger_workflow),
                    )
                    row_responses.append(api_resp)
                    row_id = str(api_resp.get("rowId", "")).strip()
                    if not row_id:
                        print(f"[警告] 新增返回缺少 rowId，已跳过该记录: worksheetId={worksheet['worksheetId']}, record={record['mockRecordKey']}")
                        continue
                    row_ids.append(row_id)
                    written_enriched_records.append(record)
                    if (i + 1) % 5 == 0:
                        print(f"{i+1}..", end="", flush=True)
                print("完成")
                response = {"success": True, "rows": row_responses}
            append_log(
                log_path,
                "worksheet_rows_created",
                worksheetId=worksheet["worksheetId"],
                returnedRowIdCount=len(row_ids),
            )
            for record, row_id in zip(written_enriched_records, row_ids):
                created_records.append(
                    {
                        "mockRecordKey": record["mockRecordKey"],
                        "rowId": row_id,
                        "recordSummary": record["recordSummary"],
                        "valuesByFieldId": record["valuesByFieldId"],
                    }
                )
        except Exception as exc:
            error_message = str(exc)
            failed_count = len(records) - len(created_records)
            response = {"success": False, "error": str(exc)}
            append_log(
                log_path,
                "worksheet_failed",
                worksheetId=worksheet["worksheetId"],
                worksheetName=worksheet["worksheetName"],
                error=str(exc),
                successCount=len(created_records),
                failedCount=failed_count,
            )
        result_worksheets.append(
            {
                "worksheetId": worksheet["worksheetId"],
                "worksheetName": worksheet["worksheetName"],
                "tier": worksheet["tier"],
                "order": worksheet["order"],
                "plannedCount": len(records),
                "successCount": len(created_records),
                "failedCount": failed_count,
                "requestRows": row_plan,
                "response": response,
                "records": created_records,
            }
        )
        append_log(
            log_path,
            "worksheet_finished",
            worksheetId=worksheet["worksheetId"],
            worksheetName=worksheet["worksheetName"],
            plannedCount=len(records),
            successCount=len(created_records),
            failedCount=failed_count,
        )
        if created_records:
            created_records_by_ws[str(worksheet["worksheetId"])] = created_records
        if error_message:
            break

    result = {
        "schemaVersion": "mock_data_write_result_v1",
        "sourceBundle": str(bundle_path),
        "logFile": str(log_path),
        "app": bundle.get("app", {}),
        "triggerWorkflow": bool(args.trigger_workflow),
        "dryRun": bool(args.dry_run),
        "worksheets": result_worksheets,
    }
    if error_message:
        result["error"] = error_message

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else make_output_path(MOCK_WRITE_RESULT_DIR, "mock_data_write_result", app["appId"])
    )
    write_json_with_latest(MOCK_WRITE_RESULT_DIR, output_path, "mock_data_write_result_latest.json", result)
    append_log(
        log_path,
        "finished",
        outputFile=str(output_path),
        worksheetCount=len(result_worksheets),
        summary=summarize_write_result(result),
        hasError=bool(error_message),
    )

    print("写入完成")
    print(f"- 应用: {app['appName']} ({app['appId']})")
    print(f"- 模式: {'dry-run' if args.dry_run else 'live'}")
    print(f"- 日志文件: {log_path}")
    print(f"- 摘要: {summarize_write_result(result)}")
    print(f"- 结果文件: {output_path}")
    print(json.dumps([{k: ws[k] for k in ('worksheetName', 'plannedCount', 'successCount')} for ws in result_worksheets], ensure_ascii=False, indent=2))
    if error_message:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
