#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选择应用并导出对话机器人生成所需的应用结构 JSON。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from chatbot_common import (
    CHATBOT_SCHEMA_DIR,
    append_log,
    choose_apps_for_chatbot,
    choose_section,
    discover_authorized_apps,
    fetch_app_schema,
    flatten_sections,
    load_json,
    make_chatbot_log_path,
    now_iso,
    write_json_with_latest,
)

DEFAULT_BASE_URL = "https://api.mingdao.com"


def auto_pick_section(sections: list[dict]) -> dict:
    if not sections:
        raise RuntimeError("当前应用没有可用分组，无法创建对话机器人")
    # 优先找"仪表盘"分组（统计页面和机器人专用）
    for section in sections:
        if section.get("name") == "仪表盘" and str(section.get("appSectionId", "")).strip():
            return section
    # 兜底：第一个有 ID 的分组
    for section in sections:
        if str(section.get("appSectionId", "")).strip():
            return section
    return sections[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="选择应用并导出对话机器人应用结构 JSON")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--section-id", default="", help="可选，指定目标分组 appSectionId")
    parser.add_argument("--section-index", type=int, default=0, help="可选，指定目标分组序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    apps = discover_authorized_apps(base_url=args.base_url)
    selected_apps = choose_apps_for_chatbot(apps, app_id=args.app_id, app_index=args.app_index)
    if not selected_apps:
        print("已取消，不生成任何 JSON。")
        raise SystemExit(0)

    bundle_log_path = make_chatbot_log_path(
        "chatbot_schema_bundle",
        "all" if len(selected_apps) > 1 else selected_apps[0]["appId"],
    )
    append_log(bundle_log_path, "start", appCount=len(selected_apps))

    schema_items = []
    for app in selected_apps:
        log_path = make_chatbot_log_path("chatbot_schema", app["appId"])
        append_log(log_path, "start", appId=app["appId"], appName=app["appName"])

        schema = fetch_app_schema(app=app, base_url=args.base_url, log_path=log_path)
        app_meta = schema["appMeta"]
        sections = flatten_sections(app_meta.get("sections", []) or [])
        if args.section_id or args.section_index:
            section = choose_section(sections, section_id=args.section_id, section_index=args.section_index)
            append_log(
                log_path,
                "section_selected_manual",
                appSectionId=section["appSectionId"],
                sectionName=section["name"],
            )
        else:
            section = auto_pick_section(sections)
            append_log(
                log_path,
                "section_selected_auto",
                appSectionId=section["appSectionId"],
                sectionName=section["name"],
            )
        append_log(log_path, "section_selected", appSectionId=section["appSectionId"], sectionName=section["name"])

        project_id = str(app_meta.get("projectId", "")).strip()
        if not project_id:
            auth_payload = load_json(Path(app["authPath"]))
            for row in auth_payload.get("data", []) or []:
                if isinstance(row, dict) and str(row.get("appId", "")).strip() == app["appId"]:
                    project_id = str(row.get("projectId", "")).strip()
                    break

        item = {
            "schemaVersion": "chatbot_app_schema_v1",
            "generatedAt": now_iso(),
            "appName": str(app_meta.get("name", "")).strip() or app["appName"],
            "summary": {
                "worksheetCount": schema["worksheetCount"],
                "fieldCount": schema["fieldCount"],
            },
            "worksheets": [
                {
                    "worksheetName": str(ws.get("worksheetName", "")).strip(),
                    "fields": [
                        {
                            "fieldName": str(field.get("name", "")).strip(),
                            "fieldType": str(field.get("type", "")).strip(),
                            "values": [
                                str(opt.get("value", "")).strip()
                                for opt in field.get("options", []) or []
                                if str(opt.get("value", "")).strip()
                            ],
                        }
                        for field in ws.get("fields", []) or []
                        if str(field.get("name", "")).strip()
                    ],
                    "relations": [
                        {
                            "sourceFieldName": str(field.get("name", "")).strip(),
                            "targetWorksheetId": str(field.get("dataSource", "")).strip(),
                            "targetWorksheetName": next(
                                (
                                    str(target_ws.get("worksheetName", "")).strip()
                                    for target_ws in schema["worksheets"]
                                    if str(target_ws.get("worksheetId", "")).strip()
                                    == str(field.get("dataSource", "")).strip()
                                ),
                                "",
                            ),
                            "multiple": int(field.get("subType", 0) or 0) == 2,
                        }
                        for field in ws.get("fields", []) or []
                        if str(field.get("type", "")).strip() == "Relation"
                        and str(field.get("name", "")).strip()
                        and str(field.get("dataSource", "")).strip()
                    ],
                    "fieldNames": [
                        str(field.get("name", "")).strip()
                        for field in ws.get("fields", []) or []
                        if str(field.get("name", "")).strip()
                    ],
                }
                for ws in schema["worksheets"]
            ],
            "runtime": {
                "app": {
                    "appId": app["appId"],
                    "appName": str(app_meta.get("name", "")).strip() or app["appName"],
                    "projectId": project_id,
                    "baseUrl": args.base_url,
                    "authFile": app["authFile"],
                    "authPath": app["authPath"],
                },
                "selectedSection": section,
            },
        }
        schema_items.append(item)
        append_log(log_path, "finished", worksheetCount=schema["worksheetCount"])

    if len(schema_items) == 1:
        result = schema_items[0]
        if args.output:
            output_path = Path(args.output).expanduser().resolve()
        else:
            output_path = (CHATBOT_SCHEMA_DIR / f"chatbot_app_schema_{result['app']['appId']}.json").resolve()
        write_json_with_latest(
            CHATBOT_SCHEMA_DIR,
            output_path,
            "chatbot_app_schema_latest.json",
            result,
        )
        append_log(bundle_log_path, "finished", output=str(output_path), appCount=1)
        print("应用结构导出完成")
        print(f"- 应用: {result['runtime']['app']['appName']} ({result['runtime']['app']['appId']})")
        print(f"- 目标分组: {result['runtime']['selectedSection']['name']} ({result['runtime']['selectedSection']['appSectionId']})")
        print(f"- 工作表数量: {result['summary']['worksheetCount']}")
        print(f"- 字段数量: {result['summary']['fieldCount']}")
        print(f"- 结果文件: {output_path}")
        print(f"- 日志文件: {bundle_log_path}")
        print(f"RESULT_JSON: {output_path}")
        print(f"LOG_FILE: {bundle_log_path}")
        return

    result = {
        "schemaVersion": "chatbot_app_schema_bundle_v1",
        "generatedAt": now_iso(),
        "appCount": len(schema_items),
        "items": schema_items,
    }
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = (CHATBOT_SCHEMA_DIR / "chatbot_app_schema_bundle_all.json").resolve()
    write_json_with_latest(
        CHATBOT_SCHEMA_DIR,
        output_path,
        "chatbot_app_schema_bundle_latest.json",
        result,
    )
    append_log(bundle_log_path, "finished", output=str(output_path), appCount=len(schema_items))
    print("应用结构批量导出完成")
    print(f"- 应用数量: {len(schema_items)}")
    print(f"- 结果文件: {output_path}")
    print(f"- 日志文件: {bundle_log_path}")
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {bundle_log_path}")


if __name__ == "__main__":
    main()
