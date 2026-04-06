#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mock_data_inline.py

Wave 3.5b 内联造数模块。供 pipeline/waves.py 直接 import 调用（不走 subprocess）。

包含：
- compute_new_record_count  — 根据新规则计算每张表造数条数
- build_mock_prompt         — 注入业务背景的造数 prompt
- plan_and_write_mock_data_for_ws — 单表原子操作：AI生成→校验→批量写入
- apply_relation_phase      — Phase 2：按 tier 并发填写 Relation 字段
"""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

_HAP_DIR = Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_DIR))


def compute_new_record_count(
    ws_id: str,
    relation_pairs: List[dict],
    relation_edges: List[dict],
) -> int:
    """
    新 recordCount 规则：
    - 1:N 明细端（该表有 subType=1 的出边，且参与 1-N pair）→ 6 条
    - 其余（主表端 subType=2、1:1、无关联）→ 3 条
    """
    # 收集该表的出边 subType
    outgoing_subtypes = [
        int(e.get("subType", 0) or 0)
        for e in relation_edges
        if str(e.get("sourceWorksheetId", "")).strip() == ws_id
    ]
    # 检查该表是否参与 1-N pair
    in_1n_pair = any(
        pair.get("pairType") == "1-N"
        and ws_id in (
            str(pair.get("worksheetAId", "")).strip(),
            str(pair.get("worksheetBId", "")).strip(),
        )
        for pair in relation_pairs
    )
    # 明细端条件：有出边 subType=1 且都是 1，且参与 1-N pair
    is_detail_end = (
        bool(outgoing_subtypes)
        and all(s == 1 for s in outgoing_subtypes)
        and in_1n_pair
    )
    return 10 if is_detail_end else 5


def build_mock_prompt(
    app_name: str,
    business_context: str,
    ws_name: str,
    ws_schema: dict,
    record_count: int,
) -> str:
    """
    为单张工作表构建造数 prompt。
    基于 plan_mock_data_gemini.build_prompt_v2，加入业务背景注入，
    并将 Relation 字段从 writableFields 中剔除（Phase 1 不处理关联）。
    """
    # 复用 plan_mock_data_gemini 中已有的工具函数
    from planners.plan_mock_data_gemini import _split_faker_fields

    # 剔除 Relation 字段，Phase 1 不处理
    all_writable = [
        f for f in ws_schema.get("writableFields", [])
        if f.get("type") != "Relation"
    ]
    # 有 options 的选择类字段（SingleSelect/Dropdown/MultiSelect）必须走 AI，
    # faker 不知道实际选项内容，无法生成有业务含义的合法值
    _OPTION_TYPES = {"SingleSelect", "Dropdown", "MultiSelect"}
    ai_only = [f for f in all_writable if f.get("type") in _OPTION_TYPES and f.get("options")]
    ai_only_ids = {f["fieldId"] for f in ai_only}
    rest = [f for f in all_writable if f["fieldId"] not in ai_only_ids]
    ai_fields_rest, faker_field_names = _split_faker_fields(rest)
    ai_fields = ai_only + ai_fields_rest

    faker_note = ""
    if faker_field_names:
        faker_note = (
            "\n\n以下字段将由系统自动生成，你不需要为它们提供值"
            "（也不要在 valuesByFieldId 中输出这些字段）：\n"
            + f"  - {ws_name}: {', '.join(faker_field_names)}"
        )

    ws_input = {
        "worksheetId": ws_schema["worksheetId"],
        "worksheetName": ws_name,
        "tier": 1,
        "order": 1,
        "recordCount": record_count,
        "reason": "inline_mock",
        "writableFields": ai_fields,
        "skippedFields": ws_schema.get("skippedFields", []),
    }

    import json as _json
    return f"""## 应用背景
应用名称：{app_name}
行业/业务背景：{business_context}

请根据上述背景，为「{ws_name}」生成真实有业务含义的数据，避免使用"示例"、"测试"、"sample"等无意义词汇。

---

你是企业应用造数规划助手。请基于给定应用结构，输出严格 JSON，不要 markdown，不要解释。

目标：
1. 为工作表生成指定数量的记录。
2. Relation 字段在本阶段一律不要输出。
3. SingleSelect / Dropdown 字段值必须是包含一个 key 字符串的数组，例如 ["key1"]，不要使用 value 文案，不要使用裸字符串。
4. MultipleSelect 字段值必须是包含一个或多个 key 字符串的数组，例如 ["key1", "key2"]。绝对禁止将数组序列化为字符串后再放进外层数组。
5. Currency（金额）字段使用数字，例如 50000。
6. Region（地区）字段使用中文地址文本，例如 "北京/北京市/朝阳区"。
7. Location（定位）字段使用 JSON 对象，包含 address 字段，例如 {{"address": "上海市浦东新区张江高科技园区"}}。
8. RichText（富文本）字段使用纯文本字符串。
9. valuesByFieldId 的 key 必须是字段 ID。
10. 每条记录都要有一句中文 recordSummary，描述该记录的业务含义。
11. ⚠️ 每个 writableField 都必须填值，禁止遗漏！只有 skippedFields 里的字段和系统自动生成的字段才可以不填。
{faker_note}

工作表规划输入：
{_json.dumps([ws_input], ensure_ascii=False, indent=2)}

请严格输出 JSON，格式如下：
{{
  "notes": ["inline_mock"],
  "worksheets": [
    {{
      "worksheetId": "工作表ID",
      "worksheetName": "工作表名",
      "tier": 1,
      "order": 1,
      "recordCount": {record_count},
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
1. 每张表 records 数量必须严格等于 recordCount（{record_count} 条）。
2. Checkbox 使用 true/false；Number / Currency 使用数字；Date 使用 yyyy-MM-dd；DateTime 使用 yyyy-MM-dd HH:mm:ss。
3. ⚠️ 必须为每个 writableField 都生成合理的值，不允许遗漏任何可写字段。
4. Number 字段：禁止使用 0。字段名含"ID/编号/序号/No/号/码"等时，生成 1001-9999 范围的正整数。
""".strip()


def plan_and_write_mock_data_for_ws(
    client: Any,
    model: str,
    ai_config: dict,
    app_id: str,
    app_name: str,
    business_context: str,
    app_key: str,
    sign: str,
    base_url: str,
    worksheet_id: str,
    worksheet_name: str,
    ws_schema: dict,
    relation_pairs: List[dict],
    relation_edges: List[dict],
    dry_run: bool = False,
    gemini_retries: int = 3,
) -> dict:
    """
    单表原子操作：AI 生成数据 → validate_plan 校验 → 批量 V3 写入。

    Returns:
        {
            "worksheetId": str,
            "worksheetName": str,
            "rowIds": list[str],   # 成功写入的 rowId 列表（dry_run 时为空）
            "recordCount": int,
            "error": str | None,
        }
    """
    from planners.plan_mock_data_gemini import generate_with_retry, validate_plan
    from ai_utils import parse_ai_json
    from mock_data_common import create_rows_batch_v3

    record_count = compute_new_record_count(worksheet_id, relation_pairs, relation_edges)

    # 构建 mini_snapshot（validate_plan 需要此结构）
    # Relation 字段已在 build_mock_prompt 中剔除，这里 ws_schema 保持原样供 validate 用
    ws_schema_no_relation = {
        **ws_schema,
        "writableFields": [
            f for f in ws_schema.get("writableFields", [])
            if f.get("type") != "Relation"
        ],
    }
    mini_snapshot = {
        "app": {"appId": app_id, "appName": app_name},
        "worksheets": [ws_schema_no_relation],
        "worksheetTiers": [{
            "worksheetId": worksheet_id,
            "worksheetName": worksheet_name,
            "tier": 1,
            "order": 1,
            "recordCount": record_count,
            "reason": "inline_mock",
            "pairTypes": [],
            "selfRelationSubTypes": [],
        }],
    }

    try:
        prompt = build_mock_prompt(
            app_name=app_name,
            business_context=business_context,
            ws_name=worksheet_name,
            ws_schema=ws_schema,
            record_count=record_count,
        )
        resp = generate_with_retry(client, model, prompt, gemini_retries, ai_config)
        raw = parse_ai_json(resp.text or "")
        validated = validate_plan(raw, mini_snapshot)
        bundle = validated["bundle"]

        if dry_run:
            print(f"  [dry-run] [{worksheet_name}] 规划完成，recordCount={record_count}，跳过写入")
            return {
                "worksheetId": worksheet_id,
                "worksheetName": worksheet_name,
                "rowIds": [],
                "recordCount": record_count,
                "error": None,
            }

        # 取 bundle 中该表的 records
        ws_bundle = next(
            (w for w in bundle.get("worksheets", []) if w["worksheetId"] == worksheet_id),
            None,
        )
        if not ws_bundle:
            raise ValueError(f"bundle 中找不到 worksheetId={worksheet_id}")

        records = ws_bundle.get("records", [])
        field_meta_map = {
            f["fieldId"]: f
            for f in ws_schema_no_relation.get("writableFields", [])
        }

        row_ids = create_rows_batch_v3(
            base_url=base_url,
            app_key=app_key,
            sign=sign,
            worksheet_id=worksheet_id,
            enriched_records=records,
            field_meta_map=field_meta_map,
            trigger_workflow=False,
        )
        print(f"  ✓ [{worksheet_name}] 写入 {len(row_ids)} 条（计划 {record_count} 条）")
        return {
            "worksheetId": worksheet_id,
            "worksheetName": worksheet_name,
            "rowIds": row_ids,
            "recordCount": record_count,
            "error": None,
        }

    except Exception as exc:
        print(f"  ✗ [{worksheet_name}] 造数失败: {exc}", file=sys.stderr)
        return {
            "worksheetId": worksheet_id,
            "worksheetName": worksheet_name,
            "rowIds": [],
            "recordCount": record_count,
            "error": str(exc),
        }


def _build_relation_assignments(
    source_row_ids: List[str],
    target_row_ids: List[str],
) -> List[tuple]:
    """
    Round-robin 分配：source 每条记录循环取 target 的 rowId。
    返回 [(source_row_id, target_row_id), ...]
    """
    if not target_row_ids:
        return []
    return [
        (src_id, target_row_ids[i % len(target_row_ids)])
        for i, src_id in enumerate(source_row_ids)
    ]


def apply_relation_phase(
    app_id: str,
    app_key: str,
    sign: str,
    base_url: str,
    relation_pairs: List[dict],
    relation_edges: List[dict],
    all_row_ids: Dict[str, List[str]],
    worksheet_schemas: List[dict],
    dry_run: bool = False,
) -> Dict[str, dict]:
    """
    Phase 2：为从属端表的 Relation 字段填写目标表 rowId。

    不调用 AI，使用 round-robin 策略。
    按 tier 分两批并发（Batch A: tier=3 明细端，Batch B: tier=2 1:1 从属端）。

    Returns:
        {worksheetId: {"planned": int, "updated": int, "failed": int}}
    """
    from planners.plan_mock_relations_gemini import build_candidate_fields
    from mock_data_common import update_row_relation

    # 构造 mini_snapshot（build_candidate_fields 需要）
    # tier=3 为明细端，tier=2 为 1:1 从属端
    tier_map: Dict[str, int] = {}
    for ws_id in all_row_ids:
        outgoing = [
            int(e.get("subType", 0) or 0)
            for e in relation_edges
            if str(e.get("sourceWorksheetId", "")).strip() == ws_id
        ]
        in_1n = any(
            p.get("pairType") == "1-N"
            and ws_id in (str(p.get("worksheetAId", "")), str(p.get("worksheetBId", "")))
            for p in relation_pairs
        )
        if outgoing and all(s == 1 for s in outgoing) and in_1n:
            tier_map[ws_id] = 3
        else:
            tier_map[ws_id] = 2

    worksheet_tiers = [
        {"worksheetId": ws_id, "tier": tier_map.get(ws_id, 2)}
        for ws_id in all_row_ids
    ]
    mini_snapshot = {
        "worksheets": worksheet_schemas,
        "relationPairs": relation_pairs,
        "worksheetTiers": worksheet_tiers,
    }
    candidates = build_candidate_fields(mini_snapshot)

    results: Dict[str, dict] = {}
    results_lock = threading.Lock()

    def _process_one(candidate: dict):
        ws_id = candidate["worksheetId"]
        ws_name = candidate["worksheetName"]
        source_row_ids = all_row_ids.get(ws_id, [])
        if not source_row_ids:
            return

        planned = 0
        updated = 0
        failed = 0

        for rel_field in candidate["relationFields"]:
            field_id = rel_field["relationFieldId"]
            target_ws_id = rel_field["targetWorksheetId"]
            target_row_ids = all_row_ids.get(target_ws_id, [])
            if not target_row_ids:
                print(f"  ⚠ [{ws_name}] 目标表 {target_ws_id} 无 rowId，跳过关联字段 {field_id}")
                continue

            assignments = _build_relation_assignments(source_row_ids, target_row_ids)
            planned += len(assignments)

            if dry_run:
                print(f"  [dry-run] [{ws_name}] 关联字段 {field_id} → {len(assignments)} 条分配")
                updated += len(assignments)
                continue

            for src_id, tgt_id in assignments:
                try:
                    update_row_relation(
                        base_url=base_url,
                        app_key=app_key,
                        sign=sign,
                        worksheet_id=ws_id,
                        row_id=src_id,
                        field_id=field_id,
                        target_row_id=tgt_id,
                        trigger_workflow=False,
                    )
                    updated += 1
                except Exception as exc:
                    print(f"  ✗ [{ws_name}] PATCH 失败 row={src_id}: {exc}", file=sys.stderr)
                    failed += 1

        with results_lock:
            results[ws_id] = {"planned": planned, "updated": updated, "failed": failed}
        print(f"  ✓ [{ws_name}] 关联处理完成: updated={updated}, failed={failed}")

    # 按 tier 分两批并发执行
    for batch_tier in (3, 2):
        batch = [c for c in candidates if tier_map.get(c["worksheetId"], 2) == batch_tier]
        if not batch:
            continue
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(_process_one, c) for c in batch]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as exc:
                    print(f"  ✗ 关联处理任务异常: {exc}", file=sys.stderr)

    return results
