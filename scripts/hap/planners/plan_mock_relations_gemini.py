#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据结构快照与写入结果规划 1-1 及 1-N 单选端关联关系更新。
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
import time
from pathlib import Path
from typing import Dict, List, Optional

NETWORK_MAX_RETRIES = 3
NETWORK_RETRY_DELAY = 5

from ai_utils import create_generation_config, get_ai_client, load_ai_config

from mock_data_common import (
    MOCK_RELATION_PLAN_DIR,
    MOCK_SCHEMA_DIR,
    MOCK_WRITE_RESULT_DIR,
    extract_json_object,
    load_json,
    make_output_path,
    resolve_json_input,
    write_json_with_latest,
)

def build_candidate_fields(snapshot: dict) -> List[dict]:
    pair_type_map: Dict[tuple, str] = {}
    for pair in snapshot.get("relationPairs", []):
        if not isinstance(pair, dict):
            continue
        key = tuple(sorted((str(pair.get("worksheetAId", "")).strip(), str(pair.get("worksheetBId", "")).strip())))
        pair_type_map[key] = str(pair.get("pairType", "")).strip()

    tier_map = {item["worksheetId"]: item for item in snapshot.get("worksheetTiers", []) if isinstance(item, dict)}
    candidates = []
    for worksheet in snapshot.get("worksheets", []):
        ws_id = str(worksheet.get("worksheetId", "")).strip()
        tier = int(tier_map.get(ws_id, {}).get("tier", 1) or 1)
        target_fields = []
        for field in worksheet.get("fields", []):
            if field.get("type") != "Relation":
                continue
            target_id = str(field.get("dataSource", "")).strip()
            pair_key = tuple(sorted((ws_id, target_id)))
            pair_type = pair_type_map.get(pair_key, "ambiguous")
            sub_type = int(field.get("subType", 0) or 0)
            handling_mode = ""
            if pair_type == "1-1":
                handling_mode = "1-1"
            elif pair_type == "1-N" and sub_type == 1:
                handling_mode = "1-N-single"
            if not handling_mode:
                continue
            target_fields.append(
                {
                    "relationFieldId": field["fieldId"],
                    "relationFieldName": field["name"],
                    "targetWorksheetId": target_id,
                    "pairType": pair_type,
                    "subType": sub_type,
                    "handlingMode": handling_mode,
                }
            )
        if not target_fields:
            continue
        candidates.append(
            {
                "worksheetId": ws_id,
                "worksheetName": worksheet["worksheetName"],
                "tier": tier,
                "processTier": 1 if tier == 3 else 2,
                "relationFields": target_fields,
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


def build_prompt(snapshot: dict, write_result: dict) -> str:
    candidates = build_candidate_fields(snapshot)
    records_by_ws = build_records_by_ws(write_result)
    worksheet_inputs = []
    for candidate in candidates:
        source_records = records_by_ws.get(candidate["worksheetId"], [])
        relation_fields = []
        for field in candidate["relationFields"]:
            target_records = records_by_ws.get(field["targetWorksheetId"], [])
            relation_fields.append(
                {
                    "relationFieldId": field["relationFieldId"],
                    "relationFieldName": field["relationFieldName"],
                    "targetWorksheetId": field["targetWorksheetId"],
                    "pairType": field["pairType"],
                    "subType": field["subType"],
                    "handlingMode": field["handlingMode"],
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
                "worksheetId": candidate["worksheetId"],
                "worksheetName": candidate["worksheetName"],
                "processTier": candidate["processTier"],
                "sourceRecords": [
                    {
                        "rowId": record["rowId"],
                        "mockRecordKey": record["mockRecordKey"],
                        "recordSummary": record["recordSummary"],
                    }
                    for record in source_records
                ],
                "relationFields": relation_fields,
            }
        )

    return f"""
你是企业应用数据关联规划助手。请仅输出严格 JSON，不要 markdown，不要解释。

任务：
1. 你会收到已经创建好的记录数据。
2. 你需要处理两类关联字段：
   - 所有 1-1 关系字段
   - 1-N 关系里的单选端字段（subType=1），这类字段表示“下级记录指向唯一上级记录”
3. 每个 source record 在每个 relationField 上最多选择一个 targetRowId。
4. 不要处理 1-N 关系里的多选端字段（subType=2）。

输入：
{json.dumps(worksheet_inputs, ensure_ascii=False, indent=2)}

输出 JSON：
{{
  "appId": "{snapshot.get('app', {}).get('appId', '')}",
  "appName": "{snapshot.get('app', {}).get('appName', '')}",
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
          "reason": "为什么选这个目标记录"
        }}
      ]
    }}
  ]
}}

强约束：
1. worksheets 只能覆盖输入里提供的 worksheetId。
2. updates 中的 rowId、mockRecordKey 必须来自对应 sourceRecords。
3. relationFieldId 必须来自对应 relationFields。
4. targetRowId 必须来自该 relationField 的 targetRecords。
5. 对于 handlingMode=1-N-single，必须理解为“为当前下级记录选择唯一上级记录”。
6. 如果某条 source record 找不到合适目标，可以跳过，不必强行输出。
7. 输出必须为合法 JSON。
""".strip()


def validate_relation_plan(raw: dict, snapshot: dict, write_result: dict) -> dict:
    candidates = build_candidate_fields(snapshot)
    candidate_by_ws = {item["worksheetId"]: item for item in candidates}
    records_by_ws = build_records_by_ws(write_result)
    result_items = []
    for raw_item in raw.get("worksheets", []):
        if not isinstance(raw_item, dict):
            raise ValueError(f"工作表项格式错误: {raw_item}")
        worksheet_id = str(raw_item.get("worksheetId", "")).strip()
        candidate = candidate_by_ws.get(worksheet_id)
        if not candidate:
            print(f"[警告] 关联规划返回未知 worksheetId: {worksheet_id}，已跳过")
            continue
        valid_source_records = {
            (record["rowId"], record["mockRecordKey"]): record
            for record in records_by_ws.get(worksheet_id, [])
        }
        field_targets = {}
        for field in candidate["relationFields"]:
            target_records = records_by_ws.get(field["targetWorksheetId"], [])
            field_targets[field["relationFieldId"]] = {
                "targetWorksheetId": field["targetWorksheetId"],
                "targetRowIds": {record["rowId"] for record in target_records},
                "relationFieldName": field["relationFieldName"],
                "pairType": field["pairType"],
                "subType": field["subType"],
                "handlingMode": field["handlingMode"],
            }
        updates = []
        for update in raw_item.get("updates", []):
            if not isinstance(update, dict):
                raise ValueError(f"更新项格式错误: {update}")
            row_id = str(update.get("rowId", "")).strip()
            mock_record_key = str(update.get("mockRecordKey", "")).strip()
            relation_field_id = str(update.get("relationFieldId", "")).strip()
            target_row_id = str(update.get("targetRowId", "")).strip()
            if (row_id, mock_record_key) not in valid_source_records:
                print(f"[警告] 更新项引用了未知源记录，已跳过: worksheetId={worksheet_id}, update={update}")
                continue
            if relation_field_id not in field_targets:
                print(f"[警告] 更新项引用了未知 relationFieldId，已跳过: worksheetId={worksheet_id}, fieldId={relation_field_id}")
                continue
            target_meta = field_targets[relation_field_id]
            if target_row_id not in target_meta["targetRowIds"]:
                print(f"[警告] 更新项引用了未知 targetRowId，已跳过: worksheetId={worksheet_id}, update={update}")
                continue
            updates.append(
                {
                    "worksheetId": worksheet_id,
                    "worksheetName": candidate["worksheetName"],
                    "processTier": candidate["processTier"],
                    "rowId": row_id,
                    "mockRecordKey": mock_record_key,
                    "relationFieldId": relation_field_id,
                    "relationFieldName": target_meta["relationFieldName"],
                    "targetWorksheetId": target_meta["targetWorksheetId"],
                    "targetRowId": target_row_id,
                    "pairType": target_meta["pairType"],
                    "subType": target_meta["subType"],
                    "handlingMode": target_meta["handlingMode"],
                    "reason": str(update.get("reason", "")).strip(),
                }
            )
        result_items.append(
            {
                "worksheetId": worksheet_id,
                "worksheetName": candidate["worksheetName"],
                "processTier": candidate["processTier"],
                "updates": updates,
            }
        )
    result_items.sort(key=lambda item: (item["processTier"], item["worksheetName"]))
    return {
        "schemaVersion": "mock_relation_plan_v1",
        "app": snapshot.get("app", {}),
        "notes": raw.get("notes", []),
        "worksheets": result_items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="调用 Gemini 规划 mock 关系回填")
    parser.add_argument("--schema-json", required=True, help="结构快照 JSON 路径")
    parser.add_argument("--write-result-json", required=True, help="造数写入结果 JSON 路径")
    parser.add_argument("--output", default="", help="关系规划输出路径")
    args = parser.parse_args()

    schema_path = resolve_json_input(str(args.schema_json), [MOCK_SCHEMA_DIR])
    write_result_path = resolve_json_input(str(args.write_result_json), [MOCK_WRITE_RESULT_DIR])
    snapshot = load_json(schema_path)
    write_result = load_json(write_result_path)
    ai_config = load_ai_config()
    client = get_ai_client(ai_config)

    base_prompt = build_prompt(snapshot, write_result)
    validation_retries = 3
    result = None
    last_error: Optional[str] = None
    for val_attempt in range(1, validation_retries + 1):
        prompt = base_prompt
        if last_error:
            prompt = base_prompt + f"\n\n# 上次输出验证失败（第 {val_attempt - 1} 次）\n错误信息：{last_error}\n请仔细检查并修正后重新输出。"
        response = None
        for net_try in range(1, NETWORK_MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=ai_config["model"],
                    contents=prompt,
                    config=create_generation_config(
                        ai_config,
                        response_mime_type="application/json",
                        temperature=0.2,
                    ),
                )
                break
            except Exception as e:
                if net_try < NETWORK_MAX_RETRIES:
                    wait = NETWORK_RETRY_DELAY * net_try
                    print(f"[网络重试 {net_try}/{NETWORK_MAX_RETRIES}] {type(e).__name__}: {e}，{wait}s 后重试...")
                    time.sleep(wait)
                else:
                    raise
        raw = extract_json_object(response.text or "")
        try:
            result = validate_relation_plan(raw, snapshot, write_result)
            break
        except Exception as exc:
            last_error = str(exc)
            if val_attempt >= validation_retries:
                raise
            print(f"[验证重试 {val_attempt}/{validation_retries}] 验证失败，追加错误后重新生成：{exc}")
    assert result is not None
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else make_output_path(MOCK_RELATION_PLAN_DIR, "mock_relation_plan", str(snapshot.get("app", {}).get("appId", "")).strip())
    )
    write_json_with_latest(MOCK_RELATION_PLAN_DIR, output_path, "mock_relation_plan_latest.json", result)

    total_updates = sum(len(item.get("updates", [])) for item in result.get("worksheets", []))
    print("关联规划完成")
    print(f"- 文件: {output_path}")
    print(f"- 工作表数量: {len(result.get('worksheets', []))}")
    print(f"- 更新数量: {total_updates}")


if __name__ == "__main__":
    main()
