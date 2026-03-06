#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析已写入数据的关联一致性，生成修复计划。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from google import genai
from google.genai import types

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import (
    DEFAULT_BASE_URL,
    DEFAULT_GEMINI_MODEL,
    GEMINI_CONFIG_PATH,
    MOCK_RELATION_REPAIR_PLAN_DIR,
    MOCK_SCHEMA_DIR,
    MOCK_WRITE_RESULT_DIR,
    append_log,
    choose_app,
    discover_authorized_apps,
    extract_json_object,
    fetch_rows,
    load_gemini_api_key,
    load_json,
    make_log_path,
    make_output_path,
    now_iso,
    resolve_json_input,
    write_json_with_latest,
)


def build_relation_pair_type_map(snapshot: dict) -> Dict[Tuple[str, str], str]:
    pair_type_map: Dict[Tuple[str, str], str] = {}
    for pair in snapshot.get("relationPairs", []):
        if not isinstance(pair, dict):
            continue
        key = tuple(sorted((str(pair.get("worksheetAId", "")).strip(), str(pair.get("worksheetBId", "")).strip())))
        pair_type_map[key] = str(pair.get("pairType", "")).strip()
    return pair_type_map


def build_target_candidates(snapshot: dict) -> Dict[str, dict]:
    worksheet_map = {}
    for worksheet in snapshot.get("worksheets", []):
        if not isinstance(worksheet, dict):
            continue
        worksheet_map[str(worksheet.get("worksheetId", "")).strip()] = worksheet
    return worksheet_map


def build_candidate_worksheets(snapshot: dict) -> List[dict]:
    pair_type_map = build_relation_pair_type_map(snapshot)
    tier_map = {item["worksheetId"]: item for item in snapshot.get("worksheetTiers", []) if isinstance(item, dict)}
    worksheet_map = build_target_candidates(snapshot)
    candidates = []
    for worksheet in snapshot.get("worksheets", []):
        ws_id = str(worksheet.get("worksheetId", "")).strip()
        if not ws_id:
            continue
        relation_fields = []
        for field in worksheet.get("fields", []):
            if str(field.get("type", "")).strip() != "Relation":
                continue
            if int(field.get("subType", 0) or 0) != 1:
                continue
            target_id = str(field.get("dataSource", "")).strip()
            pair_type = pair_type_map.get(tuple(sorted((ws_id, target_id))), "ambiguous")
            if pair_type not in {"1-1", "1-N"}:
                continue
            target_ws = worksheet_map.get(target_id, {})
            relation_fields.append(
                {
                    "relationFieldId": field["fieldId"],
                    "relationFieldName": field["name"],
                    "targetWorksheetId": target_id,
                    "targetWorksheetName": target_ws.get("worksheetName", ""),
                    "pairType": pair_type,
                    "subType": 1,
                    "required": bool(field.get("required", False)),
                    "handlingMode": "1-1" if pair_type == "1-1" else "1-N-single",
                }
            )
        if not relation_fields:
            continue
        tier = int(tier_map.get(ws_id, {}).get("tier", 1) or 1)
        candidates.append(
            {
                "worksheetId": ws_id,
                "worksheetName": worksheet["worksheetName"],
                "processTier": tier,
                "relationFields": relation_fields,
            }
        )
    candidates.sort(key=lambda item: (item["processTier"], item["worksheetName"]))
    return candidates


def build_records_by_ws(write_result: dict) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for worksheet in write_result.get("worksheets", []):
        if not isinstance(worksheet, dict):
            continue
        ws_id = str(worksheet.get("worksheetId", "")).strip()
        records = worksheet.get("records", [])
        if ws_id and isinstance(records, list):
            out[ws_id] = records
    return out


def extract_row_id(row: dict) -> str:
    for key in ("rowid", "rowId"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def relation_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value)
    return True


def format_field_value(field_meta: dict, value: Any) -> Any:
    field_type = str(field_meta.get("type", "")).strip()
    if field_type not in {"SingleSelect", "MultipleSelect"}:
        return value
    option_map = {str(item.get("key", "")).strip(): str(item.get("value", "")).strip() for item in field_meta.get("options", [])}
    if isinstance(value, list):
        return [option_map.get(str(item), str(item)) for item in value]
    return option_map.get(str(value), value)


def build_source_preview(record: dict, worksheet_meta: dict) -> Dict[str, Any]:
    field_map = {field["fieldId"]: field for field in worksheet_meta.get("fields", [])}
    values = record.get("valuesByFieldId", {})
    preview = {}
    if not isinstance(values, dict):
        return preview
    for field_id, value in values.items():
        field_meta = field_map.get(str(field_id), {})
        field_name = str(field_meta.get("name", "")).strip() or str(field_id)
        preview[field_name] = format_field_value(field_meta, value)
    return preview


def collect_consistency_state(
    snapshot: dict,
    write_result: dict,
    base_url: str,
    app_key: str,
    sign: str,
    log_path: Path,
) -> List[dict]:
    candidates = build_candidate_worksheets(snapshot)
    records_by_ws = build_records_by_ws(write_result)
    worksheet_meta_map = build_target_candidates(snapshot)
    states = []
    for candidate in candidates:
        worksheet_id = candidate["worksheetId"]
        source_records = records_by_ws.get(worksheet_id, [])
        relation_field_ids = [field["relationFieldId"] for field in candidate["relationFields"]]
        append_log(
            log_path,
            "load_live_rows_start",
            worksheetId=worksheet_id,
            worksheetName=candidate["worksheetName"],
            relationFieldCount=len(relation_field_ids),
            sourceRecordCount=len(source_records),
        )
        live_rows = fetch_rows(
            base_url=base_url,
            app_key=app_key,
            sign=sign,
            worksheet_id=worksheet_id,
            fields=relation_field_ids,
            include_system_fields=True,
        )
        live_row_map = {}
        for row in live_rows:
            row_id = extract_row_id(row)
            if row_id:
                live_row_map[row_id] = row
        append_log(
            log_path,
            "load_live_rows_finished",
            worksheetId=worksheet_id,
            worksheetName=candidate["worksheetName"],
            liveRowCount=len(live_row_map),
        )

        already_resolved = []
        pending_items = []
        for record in source_records:
            row_id = str(record.get("rowId", "")).strip()
            live_row = live_row_map.get(row_id, {})
            source_preview = build_source_preview(record, worksheet_meta_map.get(worksheet_id, {}))
            for field in candidate["relationFields"]:
                current_value = live_row.get(field["relationFieldId"])
                item = {
                    "rowId": row_id,
                    "mockRecordKey": record["mockRecordKey"],
                    "recordSummary": record["recordSummary"],
                    "sourceValuesPreview": source_preview,
                    **field,
                }
                if relation_value_present(current_value):
                    resolved_row_ids = current_value if isinstance(current_value, list) else [current_value]
                    already_resolved.append(
                        {
                            **item,
                            "currentTargetRowIds": [str(value).strip() for value in resolved_row_ids if str(value).strip()],
                        }
                    )
                else:
                    pending_items.append(item)

        states.append(
            {
                **candidate,
                "sourceRecordCount": len(source_records),
                "alreadyResolved": already_resolved,
                "pendingItems": pending_items,
            }
        )
        append_log(
            log_path,
            "worksheet_consistency_scanned",
            worksheetId=worksheet_id,
            worksheetName=candidate["worksheetName"],
            sourceRecordCount=len(source_records),
            alreadyResolvedCount=len(already_resolved),
            pendingCount=len(pending_items),
        )
    return states


def build_prompt(states: List[dict], write_result: dict) -> str:
    records_by_ws = build_records_by_ws(write_result)
    worksheet_inputs = []
    for state in states:
        if not state["pendingItems"]:
            continue
        pending_inputs = []
        for item in state["pendingItems"]:
            target_records = records_by_ws.get(item["targetWorksheetId"], [])
            pending_inputs.append(
                {
                    "rowId": item["rowId"],
                    "mockRecordKey": item["mockRecordKey"],
                    "recordSummary": item["recordSummary"],
                    "sourceValuesPreview": item["sourceValuesPreview"],
                    "relationFieldId": item["relationFieldId"],
                    "relationFieldName": item["relationFieldName"],
                    "targetWorksheetId": item["targetWorksheetId"],
                    "targetWorksheetName": item["targetWorksheetName"],
                    "required": item["required"],
                    "pairType": item["pairType"],
                    "handlingMode": item["handlingMode"],
                    "targetRecords": [
                        {
                            "rowId": record["rowId"],
                            "mockRecordKey": record["mockRecordKey"],
                            "recordSummary": record["recordSummary"],
                        }
                        for record in target_records
                    ],
                }
            )
        worksheet_inputs.append(
            {
                "worksheetId": state["worksheetId"],
                "worksheetName": state["worksheetName"],
                "processTier": state["processTier"],
                "pendingItems": pending_inputs,
            }
        )

    return f"""
你是企业应用数据关联修复助手。请只输出严格 JSON，不要 markdown，不要解释。

目标：
1. 你会收到所有“当前仍为空的单选关联字段”。
2. 你必须为每个 pendingItem 给出一个结果，二选一：
   - updates: 找到最合适的 targetRowId
   - unresolved: 明确说明为什么暂时无法确定
3. 不允许静默跳过任何 pendingItem。
4. 只能处理单选关联字段：1-1 或 1-N 的单选端。

输入：
{json.dumps(worksheet_inputs, ensure_ascii=False, indent=2)}

输出 JSON：
{{
  "notes": ["可选说明"],
  "worksheets": [
    {{
      "worksheetId": "工作表ID",
      "worksheetName": "工作表名",
      "processTier": 1,
      "updates": [
        {{
          "rowId": "源记录rowId",
          "mockRecordKey": "源记录mockRecordKey",
          "relationFieldId": "关联字段ID",
          "relationFieldName": "关联字段名",
          "targetWorksheetId": "目标工作表ID",
          "targetRowId": "目标rowId",
          "reason": "匹配理由"
        }}
      ],
      "unresolved": [
        {{
          "rowId": "源记录rowId",
          "mockRecordKey": "源记录mockRecordKey",
          "relationFieldId": "关联字段ID",
          "relationFieldName": "关联字段名",
          "targetWorksheetId": "目标工作表ID",
          "reason": "无法确定的原因"
        }}
      ]
    }}
  ]
}}

强约束：
1. 每个 pendingItem 必须且只能出现在 updates 或 unresolved 之一。
2. updates 中的 targetRowId 必须从该 pendingItem 的 targetRecords 中选择。
3. 不允许输出输入之外的 worksheetId、rowId、relationFieldId、targetWorksheetId。
4. 如果 source record 和任何 target 都语义不匹配，必须输出 unresolved，并说明“上游记录不存在/语义不闭合/无法唯一判断”等原因。
5. 输出必须为合法 JSON。
""".strip()


def validate_repair_plan(raw: dict, states: List[dict], write_result: dict) -> dict:
    records_by_ws = build_records_by_ws(write_result)
    state_by_ws = {item["worksheetId"]: item for item in states}
    raw_items = raw.get("worksheets", [])
    if not isinstance(raw_items, list):
        raise ValueError("Gemini 返回的 worksheets 不是数组")

    raw_by_ws = {}
    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError(f"工作表项格式错误: {item}")
        worksheet_id = str(item.get("worksheetId", "")).strip()
        if worksheet_id not in state_by_ws:
            raise ValueError(f"Gemini 返回未知 worksheetId: {worksheet_id}")
        raw_by_ws[worksheet_id] = item

    result_items = []
    total_updates = 0
    total_unresolved = 0
    total_already_resolved = 0
    for state in states:
        worksheet_id = state["worksheetId"]
        pending_items = state["pendingItems"]
        raw_item = raw_by_ws.get(worksheet_id, {"updates": [], "unresolved": []})
        pending_map = {(item["rowId"], item["relationFieldId"]): item for item in pending_items}
        target_row_ids_by_field = {}
        for field in state["relationFields"]:
            target_records = records_by_ws.get(field["targetWorksheetId"], [])
            target_row_ids_by_field[field["relationFieldId"]] = {record["rowId"] for record in target_records}

        seen = set()
        updates = []
        for update in raw_item.get("updates", []):
            if not isinstance(update, dict):
                raise ValueError(f"更新项格式错误: {update}")
            row_id = str(update.get("rowId", "")).strip()
            relation_field_id = str(update.get("relationFieldId", "")).strip()
            key = (row_id, relation_field_id)
            pending_item = pending_map.get(key)
            if not pending_item:
                raise ValueError(f"更新项引用未知待修复关系: worksheetId={worksheet_id}, update={update}")
            target_row_id = str(update.get("targetRowId", "")).strip()
            if target_row_id not in target_row_ids_by_field.get(relation_field_id, set()):
                raise ValueError(f"更新项目标记录非法: worksheetId={worksheet_id}, update={update}")
            if key in seen:
                raise ValueError(f"同一待修复关系重复出现: worksheetId={worksheet_id}, key={key}")
            seen.add(key)
            updates.append(
                {
                    "rowId": row_id,
                    "mockRecordKey": pending_item["mockRecordKey"],
                    "relationFieldId": relation_field_id,
                    "relationFieldName": pending_item["relationFieldName"],
                    "targetWorksheetId": pending_item["targetWorksheetId"],
                    "targetWorksheetName": pending_item["targetWorksheetName"],
                    "targetRowId": target_row_id,
                    "pairType": pending_item["pairType"],
                    "handlingMode": pending_item["handlingMode"],
                    "required": pending_item["required"],
                    "reason": str(update.get("reason", "")).strip(),
                }
            )

        unresolved = []
        for item in raw_item.get("unresolved", []):
            if not isinstance(item, dict):
                raise ValueError(f"未解决项格式错误: {item}")
            row_id = str(item.get("rowId", "")).strip()
            relation_field_id = str(item.get("relationFieldId", "")).strip()
            key = (row_id, relation_field_id)
            pending_item = pending_map.get(key)
            if not pending_item:
                raise ValueError(f"未解决项引用未知待修复关系: worksheetId={worksheet_id}, item={item}")
            if key in seen:
                raise ValueError(f"同一待修复关系重复出现: worksheetId={worksheet_id}, key={key}")
            seen.add(key)
            unresolved.append(
                {
                    "rowId": row_id,
                    "mockRecordKey": pending_item["mockRecordKey"],
                    "relationFieldId": relation_field_id,
                    "relationFieldName": pending_item["relationFieldName"],
                    "targetWorksheetId": pending_item["targetWorksheetId"],
                    "targetWorksheetName": pending_item["targetWorksheetName"],
                    "pairType": pending_item["pairType"],
                    "handlingMode": pending_item["handlingMode"],
                    "required": pending_item["required"],
                    "reason": str(item.get("reason", "")).strip() or "模型未提供原因",
                }
            )

        missing = sorted([f"{key[0]}::{key[1]}" for key in pending_map if key not in seen])
        if missing:
            raise ValueError(f"存在未覆盖的待修复关系: worksheetId={worksheet_id}, missing={missing}")

        total_updates += len(updates)
        total_unresolved += len(unresolved)
        total_already_resolved += len(state["alreadyResolved"])
        result_items.append(
            {
                "worksheetId": worksheet_id,
                "worksheetName": state["worksheetName"],
                "processTier": state["processTier"],
                "sourceRecordCount": state["sourceRecordCount"],
                "alreadyResolved": state["alreadyResolved"],
                "updates": updates,
                "unresolved": unresolved,
                "counts": {
                    "sourceRecordCount": state["sourceRecordCount"],
                    "alreadyResolvedCount": len(state["alreadyResolved"]),
                    "pendingCount": len(pending_items),
                    "updateCount": len(updates),
                    "unresolvedCount": len(unresolved),
                },
            }
        )
    result_items.sort(key=lambda item: (item["processTier"], item["worksheetName"]))
    return {
        "schemaVersion": "mock_relation_repair_plan_v1",
        "generatedAt": now_iso(),
        "notes": raw.get("notes", []),
        "worksheets": result_items,
        "summary": {
            "worksheetCount": len(result_items),
            "alreadyResolvedCount": total_already_resolved,
            "updateCount": total_updates,
            "unresolvedCount": total_unresolved,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="分析并生成关联一致性修复计划")
    parser.add_argument("--schema-json", required=True, help="结构快照 JSON 路径")
    parser.add_argument("--write-result-json", required=True, help="写入结果 JSON 路径")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="修复计划输出路径")
    args = parser.parse_args()

    schema_path = resolve_json_input(str(args.schema_json), [MOCK_SCHEMA_DIR])
    write_result_path = resolve_json_input(str(args.write_result_json), [MOCK_WRITE_RESULT_DIR])
    snapshot = load_json(schema_path)
    write_result = load_json(write_result_path)
    app_id = str(snapshot.get("app", {}).get("appId", "")).strip()
    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id or app_id, app_index=args.app_index)
    log_path = make_log_path("analyze_relation_consistency", app["appId"])
    append_log(
        log_path,
        "start",
        schemaJson=str(schema_path),
        writeResultJson=str(write_result_path),
        appId=app["appId"],
        appName=app["appName"],
        model=args.model,
    )

    states = collect_consistency_state(snapshot, write_result, args.base_url, app["appKey"], app["sign"], log_path)
    pending_count = sum(len(item["pendingItems"]) for item in states)
    append_log(
        log_path,
        "consistency_state_ready",
        worksheetCount=len(states),
        pendingCount=pending_count,
        alreadyResolvedCount=sum(len(item["alreadyResolved"]) for item in states),
    )

    if pending_count == 0:
        result = {
            "schemaVersion": "mock_relation_repair_plan_v1",
            "generatedAt": now_iso(),
            "sourceSchema": str(schema_path),
            "sourceWriteResult": str(write_result_path),
            "logFile": str(log_path),
            "app": snapshot.get("app", {}),
            "notes": ["未发现待修复的单选关联字段。"],
            "worksheets": [
                {
                    "worksheetId": item["worksheetId"],
                    "worksheetName": item["worksheetName"],
                    "processTier": item["processTier"],
                    "sourceRecordCount": item["sourceRecordCount"],
                    "alreadyResolved": item["alreadyResolved"],
                    "updates": [],
                    "unresolved": [],
                    "counts": {
                        "sourceRecordCount": item["sourceRecordCount"],
                        "alreadyResolvedCount": len(item["alreadyResolved"]),
                        "pendingCount": 0,
                        "updateCount": 0,
                        "unresolvedCount": 0,
                    },
                }
                for item in states
            ],
            "summary": {
                "worksheetCount": len(states),
                "alreadyResolvedCount": sum(len(item["alreadyResolved"]) for item in states),
                "updateCount": 0,
                "unresolvedCount": 0,
            },
        }
    else:
        api_key = load_gemini_api_key(Path(args.config).expanduser().resolve())
        client = genai.Client(api_key=api_key)
        prompt = build_prompt(states, write_result)
        append_log(log_path, "prompt_ready", promptLength=len(prompt), pendingCount=pending_count)
        response = client.models.generate_content(
            model=args.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        append_log(log_path, "gemini_response_received", responseLength=len(response.text or ""))
        raw = extract_json_object(response.text or "")
        try:
            result = validate_repair_plan(raw, states, write_result)
        except Exception as exc:
            append_log(log_path, "validate_failed", error=str(exc))
            raise
        result["app"] = snapshot.get("app", {})
        result["sourceSchema"] = str(schema_path)
        result["sourceWriteResult"] = str(write_result_path)
        result["logFile"] = str(log_path)

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else make_output_path(MOCK_RELATION_REPAIR_PLAN_DIR, "mock_relation_repair_plan", app["appId"])
    )
    write_json_with_latest(MOCK_RELATION_REPAIR_PLAN_DIR, output_path, "mock_relation_repair_plan_latest.json", result)
    for worksheet in result.get("worksheets", []):
        append_log(
            log_path,
            "worksheet_repair_plan_ready",
            worksheetId=worksheet["worksheetId"],
            worksheetName=worksheet["worksheetName"],
            processTier=worksheet["processTier"],
            alreadyResolvedCount=worksheet["counts"]["alreadyResolvedCount"],
            updateCount=worksheet["counts"]["updateCount"],
            unresolvedCount=worksheet["counts"]["unresolvedCount"],
        )
    append_log(
        log_path,
        "finished",
        outputFile=str(output_path),
        summary=result.get("summary", {}),
    )

    print("关联一致性分析完成")
    print(f"- 文件: {output_path}")
    print(f"- 日志文件: {log_path}")
    print(f"- 已存在关联: {result['summary']['alreadyResolvedCount']}")
    print(f"- 待补关联: {result['summary']['updateCount']}")
    print(f"- 未解决: {result['summary']['unresolvedCount']}")


if __name__ == "__main__":
    main()
