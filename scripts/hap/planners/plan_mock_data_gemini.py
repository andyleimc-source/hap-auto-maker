#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于结构快照调用 AI 规划造数顺序与记录内容。
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import hashlib
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config, parse_ai_json

from mock_data_common import (
    MOCK_BUNDLE_DIR,
    MOCK_PLAN_DIR,
    MOCK_SCHEMA_DIR,
    append_log,
    load_json,
    make_log_path,
    make_output_path,
    resolve_json_input,
    write_json_with_latest,
)


def generate_with_retry(client, model: str, prompt: str, retries: int, ai_config: dict) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=create_generation_config(
                    ai_config,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= max(1, retries):
                break
            wait_seconds = min(16, 2 ** (attempt - 1))
            print(f"AI 调用失败，第 {attempt} 次重试前等待 {wait_seconds}s：{exc}")
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
4. SingleSelect / Dropdown 字段值必须是包含一个 key 字符串的数组，例如 ["key1"]，不要使用 value 文案，不要使用裸字符串。
5. MultipleSelect 字段值必须是包含一个或多个 key 字符串的数组，例如 ["key1", "key2"]。绝对禁止将数组序列化为字符串后再放进外层数组，即禁止 ["[\"key1\", \"key2\"]"] 这种格式。
6. Currency（金额）字段使用数字，例如 50000。
7. Region（地区）字段使用中文地址文本，例如 "北京/北京市/朝阳区"。
8. Location（定位）字段使用 JSON 对象，包含 address 字段，例如 {{"address": "上海市浦东新区张江高科技园区"}}。
9. RichText（富文本）字段使用纯文本字符串。
10. valuesByFieldId 的 key 必须是字段 ID。
11. 每条记录都要有一句中文 recordSummary，描述该记录的业务含义。
12. ⚠️ 每个 writableField 都必须填值，禁止遗漏！只有 skippedFields 里的字段才可以不填。

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
            "文本字段ID": "文本值",
            "数字字段ID": 100,
            "金额字段ID": 50000,
            "单选字段ID": ["optionKey1"],
            "下拉字段ID": ["optionKey1"],
            "多选字段ID": ["optionKey1", "optionKey2"],
            "日期字段ID": "2026-03-15",
            "地区字段ID": "广东/深圳市/南山区",
            "定位字段ID": {{"address": "上海市浦东新区张江高科技园区"}},
            "富文本字段ID": "详细描述内容",
            "布尔字段ID": true
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
4. Relation / Attachment / SubTable / Collaborator / Department / OrgRole / Formula / Summary / AutoNumber / Concatenate / DateFormula / Rollup / Signature 禁止出现在 valuesByFieldId。
5. Checkbox 使用 true/false；Number / Currency 使用数字；Date 使用 yyyy-MM-dd；DateTime 使用 yyyy-MM-dd HH:mm:ss，且日期时间必须在最近 7 天内。
6. ⚠️ 必须为每个 writableField 都生成合理的值，不允许遗漏任何可写字段。
""".strip()


def build_prompt_v2(app: dict, worksheets: List[dict]) -> str:
    """V2 Prompt: 支持单表或多表分片，结构更紧凑。"""
    return f"""
你是企业应用造数规划助手。请基于给定应用结构，输出严格 JSON，不要 markdown，不要解释。

目标：
1. 为每张表生成指定数量的记录。
2. Relation 字段在本阶段一律不要输出。
3. SingleSelect / Dropdown 字段值必须是包含一个 key 字符串的数组，例如 ["key1"]。
4. MultipleSelect 字段值必须是包含一个或多个 key 字符串的数组，例如 ["key1", "key2"]。
5. Currency（金额）字段使用数字，例如 50000。
6. Region（地区）字段使用中文地址文本，例如 "北京/北京市/朝阳区"。
7. Location（定位）字段使用 JSON 对象，包含 address 字段，例如 {{"address": "上海市浦东新区张江高科技园区"}}。
8. RichText（富文本）字段使用纯文本字符串。
9. valuesByFieldId 的 key 必须是字段 ID。
10. 每条记录都要有一句中文 recordSummary。
11. ⚠️ 每个 writableField 都必须填值，禁止遗漏！

应用信息：
{json.dumps(app, ensure_ascii=False, indent=2)}

工作表规划输入：
{json.dumps(worksheets, ensure_ascii=False, indent=2)}

请严格输出 JSON，格式如下：
{{
  "notes": ["分片模式生成"],
  "worksheets": [
    {{
      "worksheetId": "工作表ID",
      "worksheetName": "工作表名",
      "tier": 1,
      "order": 1,
      "recordCount": 5,
      "records": [
        {{
          "recordSummary": "摘要",
          "valuesByFieldId": {{
            "字段ID": "值"
          }}
        }}
      ]
    }}
  ]
}}

约束：
1. 每张表 records 数量必须严格等于 recordCount。
2. Checkbox 使用 true/false；Number / Currency 使用数字；Date 使用 yyyy-MM-dd；DateTime 使用 yyyy-MM-dd HH:mm:ss，且日期必须在最近 7 天内。
3. ⚠️ 必须为每个 writableField 都生成合理的值，不允许遗漏任何可写字段。
""".strip()


def normalize_recent_datetime_value(field_type: str, seed_key: str) -> str:
    """
    强制生成最近 7 天内的日期/日期时间值。
    使用稳定 seed，保证同一条记录重复运行时结果可复现。
    """
    now = datetime.now()
    seven_days_seconds = 7 * 24 * 60 * 60
    seed = int(hashlib.sha256(seed_key.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    offset_seconds = rng.randint(0, seven_days_seconds - 1)
    dt = now - timedelta(seconds=offset_seconds)
    if field_type == "Date":
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def validate_plan(raw: dict, snapshot: dict) -> Dict[str, Any]:
    worksheets_by_id = {ws["worksheetId"]: ws for ws in snapshot.get("worksheets", [])}
    tier_by_id = {item["worksheetId"]: item for item in snapshot.get("worksheetTiers", [])}
    raw_worksheets = raw.get("worksheets", [])
    if not isinstance(raw_worksheets, list):
        if isinstance(raw_worksheets, dict):
            raw_worksheets = [raw_worksheets]
        else:
            print("[警告] AI 返回的 worksheets 不是数组，已跳过")
            raw_worksheets = []

    normalized_plan_items: List[dict] = []
    bundle_items: List[dict] = []
    diagnostics: List[dict] = []
    for raw_item in raw_worksheets:
        if not isinstance(raw_item, dict):
            print(f"[警告] 工作表项格式错误，已跳过: {raw_item}")
            continue
        worksheet_id = str(raw_item.get("worksheetId", "")).strip()
        schema_ws = worksheets_by_id.get(worksheet_id)
        tier_info = tier_by_id.get(worksheet_id)
        if not schema_ws or not tier_info:
            print(f"[跳过] AI 返回了未知的 worksheetId: {worksheet_id}")
            continue
        records = raw_item.get("records", [])
        if not isinstance(records, list):
            raise ValueError(f"记录列表格式错误: worksheetId={worksheet_id}")
        expected_count = int(tier_info["recordCount"])
        if len(records) != expected_count:
            print(f"[警告] 记录数量不匹配: worksheetId={worksheet_id}, expected={expected_count}, actual={len(records)}")
            # 这里可以选择截断或补充，暂不抛错，让后续流程尽量跑通
            if len(records) > expected_count:
                records = records[:expected_count]

        allowed_fields = {field["fieldId"]: field for field in schema_ws.get("writableFields", [])}
        skipped_field_ids = {field["fieldId"] for field in schema_ws.get("skippedFields", [])}
        normalized_records = []
        single_select_normalized = 0
        multi_select_normalized = 0
        date_recent_normalized = 0
        fallback_used_count = 0
        total_field_values = 0
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            summary = str(record.get("recordSummary", "")).strip() or f"{schema_ws['worksheetName']} 示例记录 {index}"
            values = record.get("valuesByFieldId", {})
            if not isinstance(values, dict):
                values = {}
            final_values: Dict[str, Any] = {}
            for field_id, value in values.items():
                field_id = str(field_id).strip()
                if field_id in skipped_field_ids or field_id not in allowed_fields:
                    continue
                field_meta = allowed_fields[field_id]
                field_type = str(field_meta.get("type", "")).strip()
                if field_type in {"SingleSelect", "Dropdown"}:
                    valid_keys = [item["key"] for item in field_meta.get("options", []) if item.get("key")]
                    valid_keys_set = set(valid_keys)
                    if isinstance(value, str):
                        value = [value]
                        single_select_normalized += 1
                    if not isinstance(value, list) or len(value) != 1:
                        # 格式不对：用第一个合法 key 兜底
                        if valid_keys:
                            value = [valid_keys[index % len(valid_keys)]]
                        else:
                            continue
                    elif str(value[0]) not in valid_keys_set:
                        # AI 用了中文 value 而非 key：尝试按 value 找到对应 key，否则随机选
                        matched = next((item["key"] for item in field_meta.get("options", [])
                                        if item.get("value") == str(value[0])), None)
                        if matched:
                            value = [matched]
                        elif valid_keys:
                            value = [valid_keys[index % len(valid_keys)]]
                        else:
                            continue
                elif field_type == "MultipleSelect":
                    valid_keys = [item["key"] for item in field_meta.get("options", []) if item.get("key")]
                    valid_keys_set = set(valid_keys)
                    if isinstance(value, str):
                        try:
                            parsed = json.loads(value)
                            value = parsed if isinstance(parsed, list) else [value]
                        except (json.JSONDecodeError, ValueError):
                            value = [value]
                        multi_select_normalized += 1
                    if not isinstance(value, list):
                        if valid_keys:
                            value = [valid_keys[index % len(valid_keys)]]
                        else:
                            continue
                    # 过滤非法 key，替换为按 value 匹配的 key，找不到则丢弃该项
                    fixed = []
                    for item_val in value:
                        if str(item_val) in valid_keys_set:
                            fixed.append(str(item_val))
                        else:
                            matched = next((k["key"] for k in field_meta.get("options", [])
                                            if k.get("value") == str(item_val)), None)
                            if matched:
                                fixed.append(matched)
                    if not fixed and valid_keys:
                        fixed = [valid_keys[index % len(valid_keys)]]
                    if not fixed:
                        continue
                    value = fixed
                elif field_type == "Location":
                    # AI 可能返回字符串、dict 或 JSON 字符串，统一转为 dict
                    if isinstance(value, str):
                        try:
                            parsed = json.loads(value)
                            if isinstance(parsed, dict):
                                value = parsed
                            else:
                                value = {"address": value}
                        except (json.JSONDecodeError, ValueError):
                            value = {"address": value}
                    elif not isinstance(value, dict):
                        value = {"address": str(value)}
                    if "address" not in value or not str(value.get("address", "")).strip():
                        # 兜底：用 recordSummary 提取地址
                        value["address"] = summary
                elif field_type in {"Date", "DateTime"}:
                    value = normalize_recent_datetime_value(
                        field_type,
                        f"{worksheet_id}|{field_id}|{index}|{summary}",
                    )
                    date_recent_normalized += 1
                final_values[field_id] = value
            
            # 如果 AI 没填任何有效字段，强行填入标题字段
            if not final_values:
                title_field = next((f for f in schema_ws.get("writableFields", []) if f.get("isTitle")), schema_ws.get("writableFields", [None])[0])
                if title_field:
                    final_values[title_field["fieldId"]] = summary
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

        # 补全缺失的记录数量
        while len(normalized_records) < expected_count:
            idx = len(normalized_records) + 1
            summary = f"{schema_ws['worksheetName']} 自动生成的示例 {idx}"
            title_field = next((f for f in schema_ws.get("writableFields", []) if f.get("isTitle")), schema_ws.get("writableFields", [None])[0])
            p_values = {}
            if title_field:
                p_values[title_field["fieldId"]] = summary
            normalized_records.append({
                "mockRecordKey": f"{worksheet_id}-{idx:03d}",
                "recordSummary": summary,
                "valuesByFieldId": p_values
            })

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
                "fieldMetas": schema_ws.get("fields", []),
                "writableFieldMetas": schema_ws.get("writableFields", []),
                "records": normalized_records,
                "selfRelationFieldId": schema_ws.get("selfRelationFieldId") or None,
                "selfRelationFieldName": schema_ws.get("selfRelationFieldName") or None,
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
                "dateRecentNormalizedCount": date_recent_normalized,
            }
        )

    # 容错处理：如果某些工作表完全缺失
    missing = sorted(set(tier_by_id) - {item["worksheetId"] for item in normalized_plan_items})
    for mid in missing:
        tinfo = tier_by_id[mid]
        sws = next(x for x in snapshot["worksheets"] if x["worksheetId"] == mid)
        normalized_records = []
        for idx in range(1, int(tinfo["recordCount"]) + 1):
            summary = f"{sws['worksheetName']} 自动生成的示例 {idx}"
            title_field = next((f for f in sws.get("writableFields", []) if f.get("isTitle")), sws.get("writableFields", [None])[0])
            p_values = {}
            if title_field:
                p_values[title_field["fieldId"]] = summary
            normalized_records.append({
                "mockRecordKey": f"{mid}-{idx:03d}",
                "recordSummary": summary,
                "valuesByFieldId": p_values
            })
        
        normalized_plan_items.append({
            "worksheetId": mid,
            "worksheetName": sws["worksheetName"],
            "tier": tinfo["tier"],
            "order": tinfo["order"],
            "recordCount": tinfo["recordCount"],
            "reason": "auto_fallback_missing_plan",
            "writableFields": [f["fieldId"] for f in sws.get("writableFields", [])],
            "skippedFields": sws.get("skippedFields", []),
        })
        bundle_items.append({
            "worksheetId": mid,
            "worksheetName": sws["worksheetName"],
            "tier": tinfo["tier"],
            "order": tinfo["order"],
            "recordCount": tinfo["recordCount"],
            "reason": "auto_fallback_missing_plan",
            "fieldMetas": sws.get("fields", []),
            "writableFieldMetas": sws.get("writableFields", []),
            "records": normalized_records,
            "selfRelationFieldId": sws.get("selfRelationFieldId") or None,
            "selfRelationFieldName": sws.get("selfRelationFieldName") or None,
        })

    normalized_plan_items.sort(key=lambda item: (item["order"], item["worksheetName"]))
    bundle_items.sort(key=lambda item: (item["order"], item["worksheetName"]))

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
            "totalDateRecentNormalizedCount": sum(item["dateRecentNormalizedCount"] for item in diagnostics),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="根据结构快照调用 AI 规划造数")
    parser.add_argument("--schema-json", required=True, help="结构快照 JSON 路径")
    parser.add_argument("--config", default=str(AI_CONFIG_PATH), help="AI 配置 JSON 路径")
    parser.add_argument("--gemini-retries", type=int, default=4, help="AI 调用失败时的最大重试次数")
    parser.add_argument("--plan-output", default="", help="mock_data_plan 输出路径")
    parser.add_argument("--bundle-output", default="", help="mock_data_bundle 输出路径")
    parser.add_argument("--max-workers", type=int, default=8, help="DeepSeek 分片并发数（默认 8）")
    args = parser.parse_args()

    schema_path = resolve_json_input(str(args.schema_json), [MOCK_SCHEMA_DIR])
    snapshot = load_json(schema_path)
    app_id = str(snapshot.get("app", {}).get("appId", "")).strip()
    log_path = make_log_path("plan_mock_data", app_id)

    # 显式使用 fast 档位
    ai_config = load_ai_config(Path(args.config).expanduser().resolve(), tier="fast")
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]
    provider = ai_config.get("provider", "gemini")

    append_log(log_path, "start", appId=app_id, model=model_name)

    app = snapshot.get("app", {})
    all_worksheets_to_plan = []
    for item in snapshot.get("worksheetTiers", []):
        ws_id = str(item.get("worksheetId", "")).strip()
        ws_schema = next((ws for ws in snapshot.get("worksheets", []) if ws.get("worksheetId") == ws_id), None)
        if not ws_schema:
            continue
        all_worksheets_to_plan.append({
            "worksheetId": ws_id,
            "worksheetName": ws_schema["worksheetName"],
            "tier": item["tier"],
            "order": item["order"],
            "recordCount": item["recordCount"],
            "reason": item["reason"],
            "writableFields": ws_schema.get("writableFields", []),
            "skippedFields": ws_schema.get("skippedFields", []),
        })

    # 分片阈值：超过此数量的工作表时启用并发分片模式（避免 AI 单次响应过长截断）
    CHUNK_THRESHOLD = 20
    validated = None
    # 策略：如果工作表超过 CHUNK_THRESHOLD 张或 provider 是 deepseek，采用分片生成（每张表调用一次）
    # NOTE: Gemini 在工作表较多（>50张）时单次响应可能超 100KB 导致截断，需分片处理
    if len(all_worksheets_to_plan) > CHUNK_THRESHOLD or (provider == "deepseek" and len(all_worksheets_to_plan) > 1):
        print(f"[策略] 工作表数量 {len(all_worksheets_to_plan)} > {CHUNK_THRESHOLD}，开启并发分片生成模式（max_workers={args.max_workers}）...")
        notes = [f"并发分片生成模式 (provider={provider}): {datetime.now().isoformat()}"]

        def _plan_one_ws(idx_ws):
            idx, ws_to_plan = idx_ws
            p = build_prompt_v2(app, [ws_to_plan])
            resp = generate_with_retry(client, model_name, p, args.gemini_retries, ai_config)
            chunk = parse_ai_json(resp.text or "")
            chunk_ws = chunk.get("worksheets", [])
            if not chunk_ws or not isinstance(chunk_ws, list):
                print(f"  [警告] [{ws_to_plan['worksheetName']}] 生成结果为空或格式错误")
                return idx, []
            print(f"  [{ws_to_plan['worksheetName']}] 完成")
            return idx, chunk_ws

        indexed_chunks: dict = {}
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [executor.submit(_plan_one_ws, (i, ws)) for i, ws in enumerate(all_worksheets_to_plan)]
            for future in as_completed(futures):
                idx, chunk_ws = future.result()
                indexed_chunks[idx] = chunk_ws

        # 按原始顺序拼接结果
        raw_worksheets = []
        for i in range(len(all_worksheets_to_plan)):
            raw_worksheets.extend(indexed_chunks.get(i, []))

        raw = {"appId": app_id, "appName": app.get("appName", ""), "notes": notes, "worksheets": raw_worksheets}
        validated = validate_plan(raw, snapshot)
    else:
        # Gemini 或少量表，仍采用全量模式，带验证重试
        base_prompt = build_prompt(snapshot)
        validation_retries = 4
        last_error: Optional[str] = None
        for val_attempt in range(1, validation_retries + 1):
            prompt = base_prompt
            if last_error:
                prompt = base_prompt + (
                    f"\n\n# 上次输出验证失败（第 {val_attempt - 1} 次）\n"
                    f"错误信息：{last_error}\n\n"
                    f"常见修正方向：\n"
                    f"- 记录数量不匹配 → records 数组长度必须严格等于 recordCount\n"
                    f"- worksheetId 错误 → 必须与输入的 worksheetId 完全一致\n"
                    f"- 格式错误 → records 是数组，valuesByFieldId 是对象\n"
                    f"- 不要输出 skippedFields 中的字段\n"
                    f"请严格修正后重新输出完整 JSON。"
                )
            response = generate_with_retry(client, model_name, prompt, args.gemini_retries, ai_config)
            raw = parse_ai_json(response.text or "")
            try:
                validated = validate_plan(raw, snapshot)
                break
            except Exception as exc:
                last_error = str(exc)
                if val_attempt >= validation_retries:
                    raise
                print(f"[验证重试 {val_attempt}/{validation_retries}] 验证失败，追加错误后重新生成：{exc}")

    assert validated is not None

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
    
    print("造数规划完成")
    print(f"- plan 文件: {plan_output}")
    print(f"- bundle 文件: {bundle_output}")


if __name__ == "__main__":
    main()
