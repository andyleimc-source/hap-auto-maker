#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行 mock 关联关系更新。
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import sys
from pathlib import Path

from mock_data_common import (
    DEFAULT_BASE_URL,
    MOCK_RELATION_APPLY_DIR,
    MOCK_RELATION_PLAN_DIR,
    choose_app,
    discover_authorized_apps,
    load_json,
    make_output_path,
    resolve_json_input,
    update_row_relation,
    write_json_with_latest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="按规划应用 mock 关联关系")
    parser.add_argument("--relation-plan-json", required=True, help="mock_relation_plan JSON 路径")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--trigger-workflow", action="store_true", help="更新时触发工作流")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际更新")
    parser.add_argument("--output", default="", help="更新结果 JSON 路径")
    args = parser.parse_args()

    plan_path = resolve_json_input(str(args.relation_plan_json), [MOCK_RELATION_PLAN_DIR])
    relation_plan = load_json(plan_path)
    app_id = str(relation_plan.get("app", {}).get("appId", "")).strip()
    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id or app_id, app_index=args.app_index)

    worksheet_results = []
    error_message = ""
    for worksheet in relation_plan.get("worksheets", []):
        updates = worksheet.get("updates", [])
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
                result_updates.append(
                    {
                        **update,
                        "response": response,
                        "success": True,
                    }
                )
            except Exception as exc:
                error_message = str(exc)
                failed_count += 1
                result_updates.append(
                    {
                        **update,
                        "response": {"success": False, "error": str(exc)},
                        "success": False,
                    }
                )
                break
        worksheet_results.append(
            {
                "worksheetId": worksheet["worksheetId"],
                "worksheetName": worksheet["worksheetName"],
                "processTier": worksheet["processTier"],
                "plannedCount": len(updates),
                "successCount": len([item for item in result_updates if item["success"]]),
                "failedCount": failed_count,
                "updates": result_updates,
            }
        )
        if error_message:
            break

    result = {
        "schemaVersion": "mock_relation_apply_result_v1",
        "sourcePlan": str(plan_path),
        "app": relation_plan.get("app", {}),
        "triggerWorkflow": bool(args.trigger_workflow),
        "dryRun": bool(args.dry_run),
        "worksheets": worksheet_results,
    }
    if error_message:
        result["error"] = error_message
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else make_output_path(MOCK_RELATION_APPLY_DIR, "mock_relation_apply_result", app["appId"])
    )
    write_json_with_latest(MOCK_RELATION_APPLY_DIR, output_path, "mock_relation_apply_result_latest.json", result)

    total_updates = sum(item["successCount"] for item in worksheet_results)
    print("关联更新完成")
    print(f"- 应用: {app['appName']} ({app['appId']})")
    print(f"- 模式: {'dry-run' if args.dry_run else 'live'}")
    print(f"- 更新数量: {total_updates}")
    print(f"- 结果文件: {output_path}")
    print(json.dumps([{k: ws[k] for k in ('worksheetName', 'plannedCount', 'successCount')} for ws in worksheet_results], ensure_ascii=False, indent=2))
    if error_message:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
