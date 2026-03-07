#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于结构快照调用 Gemini 规划造数顺序与记录内容。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_CONFIG_PATH,
    MOCK_BUNDLE_DIR,
    MOCK_PLAN_DIR,
    MOCK_SCHEMA_DIR,
    append_log,
    extract_json_object,
    load_gemini_api_key,
    load_json,
    make_log_path,
    make_output_path,
    resolve_json_input,
    write_json_with_latest,
)


def generate_with_retry(client: genai.Client, model: str, prompt: str, retries: int) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= max(1, retries):
                break
            wait_seconds = min(16, 2 ** (attempt - 1))
            print(f"Gemini 调用失败，第 {attempt} 次重试前等待 {wait_seconds}s：{exc}")
            time.sleep(wait_seconds)
    assert last_exc is not None
    raise last_exc


def build_prompt(snapshot: dict) -> str:
    app = snapshot.get("app", {})
    worksheets = []
    for item in snapshot.get("worksheetTiers", []):
        ws_id = str(item.get("worksheetId", "")).strip()
        worksheet = next((ws for ws in snapshot.get("worksheets", []) if ws.get("worksheetId") == ws_id), None)
        if not worksheet:
            continue
        worksheets.append(
            {
                "worksheetId": worksheet["worksheetId"],
                "worksheetName": worksheet["worksheetName"],
                "tier": item["tier"],
                "order": item["order"],
                "recordCount": item["recordCount"],
                "reason": item["reason"],
                "writableFields": worksheet.get("writableFields", []),
                "skippedFields": worksheet.get("skippedFields", []),
            }
        )
    return f"""
你是企业应用造数规划助手。请基于给定应用结构，输出严格 JSON，不要 markdown，不要解释。

目标：
1. 按给定 tier/order 保持工作表造数顺序。
2. 为每张表生成指定数量的记录。
3. Relation 字段在本阶段一律不要输出。
4. SingleSelect/MultipleSelect 字段必须使用 options 里的 key，不要使用 value 文案。
5. valuesByFieldId 的 key 必须是字段 ID。
6. 每条记录都要有一句中文 recordSummary，描述该记录的业务含义。
7. 如果某字段不适合填值，可以不输出该字段，但请尽量保证记录语义完整。

应用信息：
{json.dumps(app, ensure_ascii=False, indent=2)}

工作表输入：
{json.dumps(worksheets, ensure_ascii=False, indent=2)}

输出 JSON 结构：
{{
  "appId": "{app.get('appId', '')}",
  "appName": "{app.get('appName', '')}",
  "notes": ["可选说明"],
  "worksheets": [
    {{
      "worksheetId": "工作表ID",
      "worksheetName": "工作表名",
      "tier": 1,
      "order": 1,
      "recordCount": 5,
      "reason": "沿用输入原因",
      "writableFields": ["字段ID1"],
      "skippedFields": [{{"fieldId": "字段ID", "reason": "原因"}}],
      "records": [
        {{
          "recordSummary": "一句中文摘要",
          "valuesByFieldId": {{
            "字段ID": "值或数组"
          }}
        }}
      ]
    }}
  ]
}}

强约束：
1. worksheets 数量、worksheetId、tier、order、recordCount、reason 必须与输入一致。
2. 每张表 records 数量必须严格等于 recordCount。
3. valuesByFieldId 里禁止出现任何 skippedFields 对应字段。
4. Relation / Attachment / SubTable / Collaborator / Department / OrgRole / Formula / Summary / AutoNumber 禁止出现在 valuesByFieldId。
5. Checkbox 使用 true/false；Number 使用数字；Date 使用 yyyy-MM-dd；DateTime 使用 yyyy-MM-dd HH:mm:ss。
6. 输出必须是合法 JSON 对象。
""".strip()


def validate_plan(raw: dict, snapshot: dict) -> Dict[str, Any]:
    worksheets_by_id = {ws["worksheetId"]: ws for ws in snapshot.get("worksheets", [])}
    tier_by_id = {item["worksheetId"]: item for item in snapshot.get("worksheetTiers", [])}
    raw_worksheets = raw.get("worksheets", [])
    if not isinstance(raw_worksheets, list):
        raise ValueError("Gemini 返回的 worksheets 不是数组")

    normalized_plan_items: List[dict] = []
    bundle_items: List[dict] = []
    diagnostics: List[dict] = []
    for raw_item in raw_worksheets:
        if not isinstance(raw_item, dict):
            raise ValueError(f"工作表项格式错误: {raw_item}")
        worksheet_id = str(raw_item.get("worksheetId", "")).strip()
        schema_ws = worksheets_by_id.get(worksheet_id)
        tier_info = tier_by_id.get(worksheet_id)
        if not schema_ws or not tier_info:
            raise ValueError(f"Gemini 返回未知 worksheetId: {worksheet_id}")
        records = raw_item.get("records", [])
        if not isinstance(records, list):
            raise ValueError(f"记录列表格式错误: worksheetId={worksheet_id}")
        expected_count = int(tier_info["recordCount"])
        if len(records) != expected_count:
            raise ValueError(f"记录数量不匹配: worksheetId={worksheet_id}, expected={expected_count}, actual={len(records)}")

        allowed_fields = {field["fieldId"]: field for field in schema_ws.get("writableFields", [])}
        skipped_field_ids = {field["fieldId"] for field in schema_ws.get("skippedFields", [])}
        normalized_records = []
        single_select_normalized = 0
        multi_select_normalized = 0
        fallback_used_count = 0
        total_field_values = 0
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                raise ValueError(f"记录格式错误: worksheetId={worksheet_id}, record={record}")
            summary = str(record.get("recordSummary", "")).strip() or f"{schema_ws['worksheetName']} 示例记录 {index}"
            values = record.get("valuesByFieldId", {})
            if not isinstance(values, dict):
                raise ValueError(f"valuesByFieldId 格式错误: worksheetId={worksheet_id}, index={index}")
            final_values: Dict[str, Any] = {}
            for field_id, value in values.items():
                field_id = str(field_id).strip()
                if field_id in skipped_field_ids:
                    raise ValueError(f"记录包含跳过字段: worksheetId={worksheet_id}, fieldId={field_id}")
                if field_id not in allowed_fields:
                    raise ValueError(f"记录包含非可写字段: worksheetId={worksheet_id}, fieldId={field_id}")
                field_meta = allowed_fields[field_id]
                field_type = str(field_meta.get("type", "")).strip()
                if field_type == "SingleSelect":
                    valid_keys = {item["key"] for item in field_meta.get("options", []) if item.get("key")}
                    if isinstance(value, str):
                        value = [value]
                        single_select_normalized += 1
                    if not isinstance(value, list) or len(value) != 1 or any(str(item) not in valid_keys for item in value):
                        raise ValueError(f"单选字段值非法: worksheetId={worksheet_id}, fieldId={field_id}, value={value}")
                elif field_type == "MultipleSelect":
                    valid_keys = {item["key"] for item in field_meta.get("options", []) if item.get("key")}
                    if isinstance(value, str):
                        value = [value]
                        multi_select_normalized += 1
                    if not isinstance(value, list) or any(str(item) not in valid_keys for item in value):
                        raise ValueError(f"多选字段值非法: worksheetId={worksheet_id}, fieldId={field_id}, value={value}")
                final_values[field_id] = value
            if not final_values:
                fallback_text_field = next(
                    (
                        field
                        for field in schema_ws.get("writableFields", [])
                        if str(field.get("type", "")).strip() in {"Text", "Textarea"} or bool(field.get("isTitle", False))
                    ),
                    None,
                )
                if not fallback_text_field:
                    raise ValueError(f"记录无可用 fallback 字段: worksheetId={worksheet_id}, index={index}")
                final_values[fallback_text_field["fieldId"]] = summary
                fallback_used_count += 1
            total_field_values += len(final_values)
            mock_record_key = f"{worksheet_id}-{index:03d}"
            normalized_records.append(
                {
                    "mockRecordKey": mock_record_key,
                    "recordSummary": summary,
                    "valuesByFieldId": final_values,
                }
            )

        normalized_plan_items.append(
            {
                "worksheetId": worksheet_id,
                "worksheetName": schema_ws["worksheetName"],
                "tier": int(tier_info["tier"]),
                "order": int(tier_info["order"]),
                "recordCount": expected_count,
                "reason": str(tier_info["reason"]),
                "writableFields": [field["fieldId"] for field in schema_ws.get("writableFields", [])],
                "skippedFields": schema_ws.get("skippedFields", []),
            }
        )
        bundle_items.append(
            {
                "worksheetId": worksheet_id,
                "worksheetName": schema_ws["worksheetName"],
                "tier": int(tier_info["tier"]),
                "order": int(tier_info["order"]),
                "recordCount": expected_count,
                "reason": str(tier_info["reason"]),
                "fieldMetas": [
                    {
                        "fieldId": field["fieldId"],
                        "name": field["name"],
                        "type": field["type"],
                        "controlType": int(field.get("controlType", 0) or 0),
                        "options": field.get("options", []),
                        "required": bool(field.get("required", False)),
                        "dataSource": field.get("dataSource", ""),
                    }
                    for field in schema_ws.get("fields", [])
                ],
                "writableFieldMetas": [
                    {
                        "fieldId": field["fieldId"],
                        "name": field["name"],
                        "type": field["type"],
                        "controlType": int(field.get("controlType", 0) or 0),
                        "options": field.get("options", []),
                        "required": bool(field.get("required", False)),
                        "dataSource": field.get("dataSource", ""),
                    }
                    for field in schema_ws.get("writableFields", [])
                ],
                "requiredRelationFields": [
                    {
                        "fieldId": field["fieldId"],
                        "fieldName": field["name"],
                        "targetWorksheetId": field["dataSource"],
                        "targetWorksheetName": next(
                            (
                                ws.get("worksheetName", "")
                                for ws in snapshot.get("worksheets", [])
                                if ws.get("worksheetId") == field["dataSource"]
                            ),
                            "",
                        ),
                    }
                    for field in schema_ws.get("fields", [])
                    if str(field.get("type", "")).strip() == "Relation"
                    and bool(field.get("required", False))
                    and int(field.get("subType", 0) or 0) == 1
                    and str(field.get("dataSource", "")).strip()
                ],
                "records": normalized_records,
            }
        )
        diagnostics.append(
            {
                "worksheetId": worksheet_id,
                "worksheetName": schema_ws["worksheetName"],
                "recordCount": expected_count,
                "filledFieldValueCount": total_field_values,
                "fallbackUsedCount": fallback_used_count,
                "singleSelectStringNormalizedCount": single_select_normalized,
                "multiSelectStringNormalizedCount": multi_select_normalized,
            }
        )

    normalized_plan_items.sort(key=lambda item: (item["order"], item["worksheetName"]))
    bundle_items.sort(key=lambda item: (item["order"], item["worksheetName"]))
    if len(normalized_plan_items) != len(snapshot.get("worksheetTiers", [])):
        missing = sorted(set(tier_by_id) - {item["worksheetId"] for item in normalized_plan_items})
        raise ValueError(f"Gemini 返回缺少工作表规划: {missing}")
    return {
        "plan": {
            "schemaVersion": "mock_data_plan_v1",
            "generatedAt": snapshot.get("generatedAt"),
            "app": snapshot.get("app", {}),
            "notes": raw.get("notes", []),
            "worksheets": normalized_plan_items,
        },
        "bundle": {
            "schemaVersion": "mock_data_bundle_v1",
            "generatedAt": snapshot.get("generatedAt"),
            "app": snapshot.get("app", {}),
            "notes": raw.get("notes", []),
            "worksheets": bundle_items,
        },
        "diagnostics": {
            "worksheets": diagnostics,
            "totalFallbackUsedCount": sum(item["fallbackUsedCount"] for item in diagnostics),
            "totalSingleSelectStringNormalizedCount": sum(item["singleSelectStringNormalizedCount"] for item in diagnostics),
            "totalMultiSelectStringNormalizedCount": sum(item["multiSelectStringNormalizedCount"] for item in diagnostics),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="根据结构快照调用 Gemini 规划造数")
    parser.add_argument("--schema-json", required=True, help="结构快照 JSON 路径")
    parser.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--gemini-retries", type=int, default=4, help="Gemini 调用失败时的最大重试次数")
    parser.add_argument("--plan-output", default="", help="mock_data_plan 输出路径")
    parser.add_argument("--bundle-output", default="", help="mock_data_bundle 输出路径")
    args = parser.parse_args()

    schema_path = resolve_json_input(str(args.schema_json), [MOCK_SCHEMA_DIR])
    snapshot = load_json(schema_path)
    app_id = str(snapshot.get("app", {}).get("appId", "")).strip()
    log_path = make_log_path("plan_mock_data", app_id)
    append_log(
        log_path,
        "start",
        schemaJson=str(schema_path),
        worksheetCount=len(snapshot.get("worksheets", [])),
        model=args.model,
    )
    api_key = load_gemini_api_key(Path(args.config).expanduser().resolve())
    client = genai.Client(api_key=api_key)
    prompt = build_prompt(snapshot)
    append_log(
        log_path,
        "prompt_ready",
        promptLength=len(prompt),
        worksheetTiers=len(snapshot.get("worksheetTiers", [])),
    )

    response = generate_with_retry(client, args.model, prompt, args.gemini_retries)
    append_log(
        log_path,
        "gemini_response_received",
        responseLength=len(response.text or ""),
    )
    raw = extract_json_object(response.text or "")
    try:
        validated = validate_plan(raw, snapshot)
    except Exception as exc:
        append_log(log_path, "validate_failed", error=str(exc))
        raise

    plan_output = (
        Path(args.plan_output).expanduser().resolve()
        if args.plan_output
        else make_output_path(MOCK_PLAN_DIR, "mock_data_plan", app_id)
    )
    bundle_output = (
        Path(args.bundle_output).expanduser().resolve()
        if args.bundle_output
        else make_output_path(MOCK_BUNDLE_DIR, "mock_data_bundle", app_id)
    )
    validated["plan"]["sourceSchema"] = str(schema_path)
    validated["plan"]["logFile"] = str(log_path)
    validated["plan"]["generationDiagnostics"] = validated["diagnostics"]
    validated["bundle"]["sourceSchema"] = str(schema_path)
    validated["bundle"]["logFile"] = str(log_path)
    validated["bundle"]["generationDiagnostics"] = validated["diagnostics"]
    write_json_with_latest(MOCK_PLAN_DIR, plan_output, "mock_data_plan_latest.json", validated["plan"])
    write_json_with_latest(MOCK_BUNDLE_DIR, bundle_output, "mock_data_bundle_latest.json", validated["bundle"])
    for item in validated["diagnostics"]["worksheets"]:
        append_log(log_path, "worksheet_validated", **item)
    append_log(
        log_path,
        "finished",
        planFile=str(plan_output),
        bundleFile=str(bundle_output),
        worksheetCount=len(validated["plan"].get("worksheets", [])),
        totalRecordCount=sum(item["recordCount"] for item in validated["plan"].get("worksheets", [])),
        totalFallbackUsedCount=validated["diagnostics"]["totalFallbackUsedCount"],
    )

    print("造数规划完成")
    print(f"- plan 文件: {plan_output}")
    print(f"- bundle 文件: {bundle_output}")
    print(f"- 日志文件: {log_path}")
    print(f"- 工作表数量: {len(validated['plan'].get('worksheets', []))}")
    print(f"- 记录总数: {sum(item['recordCount'] for item in validated['plan'].get('worksheets', []))}")


if __name__ == "__main__":
    main()
