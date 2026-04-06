#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 Gemini 规划某个应用下的工作表、关联关系、创建顺序，并输出 JSON。
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

NETWORK_MAX_RETRIES = 3
NETWORK_RETRY_DELAY = 5  # seconds

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))

from ai_utils import (
    AI_CONFIG_PATH,
    create_generation_config,
    get_ai_client,
    load_ai_config,
    parse_ai_json,
)
from planning.worksheet_planner import (
    build_enhanced_prompt,
    validate_worksheet_plan,
    build_skeleton_prompt,
    validate_skeleton_plan,
    repair_skeleton_plan,
    build_fields_prompt_per_ws,
    validate_fields_plan,
    build_field_type_prompt_section,
)

CONFIG_PATH = AI_CONFIG_PATH
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"
MAX_PLAN_RETRIES = 3


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "app"


def extract_min_worksheet_count(extra_requirements: str) -> int:
    text = str(extra_requirements or "").strip()
    if not text:
        return 0

    patterns = [
        r"(?:不少于|不低于|至少|最少)\s*(\d+)\s*(?:张工作表|个工作表|张表|个表)",
        r"工作表\s*(?:不少于|不低于|至少|最少)\s*(\d+)\s*张",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return max(0, int(match.group(1)))
            except Exception:
                return 0
    return 0


def extract_scene_candidates(business_context: str, extra_requirements: str) -> list[str]:
    text = "\n".join(
        part.strip() for part in (business_context, extra_requirements) if str(part or "").strip()
    )
    if not text:
        return []

    text = (
        text.replace("，", ",")
        .replace("、", ",")
        .replace("；", ",")
        .replace("。", ",")
        .replace("：", ",")
        .replace("覆盖", ",")
        .replace("包含", ",")
        .replace("涵盖", ",")
    )
    raw_parts = [part.strip() for part in text.split(",") if part.strip()]
    candidates: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        cleaned = re.sub(
            r"(要求.*|适合.*|并保持.*|真实企业管理逻辑.*|工作表.*|场景.*|模块.*|应用.*)$",
            "",
            part,
        ).strip()
        cleaned = re.sub(r"^(请创建一个|请创建|一个|大型集团企业|制造企业|连锁零售企业|项目制企业|物业园区企业)", "", cleaned).strip()
        cleaned = cleaned.strip(" ,")
        if not cleaned or len(cleaned) < 2 or len(cleaned) > 12:
            continue
        if cleaned not in seen:
            seen.add(cleaned)
            candidates.append(cleaned)
    return candidates


def normalize_scene_to_worksheet_name(scene: str) -> str:
    scene = str(scene or "").strip()
    if not scene:
        return ""
    suffixes = (
        "台账", "档案", "计划", "申请", "订单", "管理", "记录", "任务",
        "报表", "工单", "排班", "通知", "检验", "盘点", "分析", "考试",
        "预订", "整改", "跟踪", "报修", "验收", "运营", "中台",
    )
    if scene.endswith(suffixes):
        return scene
    if len(scene) <= 4:
        return f"{scene}管理"
    return scene


def build_fallback_worksheet(name: str, scene: str) -> dict:
    return {
        "name": name,
        "purpose": f"管理{scene}相关业务数据",
        "fields": [
            {
                "name": "名称",
                "type": "Text",
                "required": True,
                "description": f"{scene}名称",
                "relation_target": "",
                "option_values": [],
            },
            {
                "name": "状态",
                "type": "SingleSelect",
                "required": True,
                "description": f"{scene}状态",
                "relation_target": "",
                "option_values": ["草稿", "进行中", "已完成"],
            },
            {
                "name": "负责人",
                "type": "Collaborator",
                "required": False,
                "description": f"{scene}负责人",
                "relation_target": "",
                "option_values": [],
            },
            {
                "name": "计划日期",
                "type": "Date",
                "required": False,
                "description": f"{scene}计划日期",
                "relation_target": "",
                "option_values": [],
            },
            {
                "name": "说明",
                "type": "Text",
                "required": False,
                "description": f"{scene}补充说明",
                "relation_target": "",
                "option_values": [],
            },
        ],
        "depends_on": [],
    }


def extract_json(text: str) -> dict:
    # 统一使用 ai_utils 中的 robust 解析
    return parse_ai_json(text)


def build_prompt(app_name: str, business_context: str, extra_requirements: str) -> str:
    min_worksheet_count = extract_min_worksheet_count(extra_requirements)
    count_constraint = ""
    if min_worksheet_count > 0:
        count_constraint = (
            f"\n12) worksheets 数量必须 >= {min_worksheet_count}，"
            f"且不能通过合并业务模块规避该数量要求。"
        )

    return f"""
你是企业应用架构师。请为应用《{app_name}》设计工作表结构，输出严格 JSON。

业务背景：
{business_context}

额外要求：
{extra_requirements}

输出要求（必须是 JSON 对象，不要 markdown，不要注释）：
{{
  "app_name": "{app_name}",
  "summary": "一句话概述",
  "worksheets": [
    {{
      "name": "工作表名",
      "purpose": "用途",
      "fields": [
        {{"name": "字段名", "type": "Text|Number|SingleSelect|MultipleSelect|Date|DateTime|Collaborator|Relation|Attachment", "required": true, "description": "说明", "relation_target": "当type=Relation时填写目标工作表名，否则为空", "option_values": ["当type为SingleSelect或MultipleSelect时必须提供纯净选项值数组，否则为空数组"]}}
      ],
      "depends_on": ["依赖的工作表名"]
    }}
  ],
  "relationships": [
    {{"from": "工作表A", "field": "关联字段名", "to": "工作表B", "cardinality": "1-1|1-N", "description": "关系说明"}}
  ],
  "creation_order": ["按创建顺序排列的【所有】工作表名，必须包含 worksheets 中每一个 name，一个不漏"],
  "notes": ["实施建议1", "实施建议2"]
}}

约束：
1) creation_order 必须包含 worksheets 中的每一个工作表名（一个不漏），同时满足 depends_on 的依赖拓扑顺序。
2) worksheets 中涉及 Relation 的 relation_target 必须在 worksheets 中存在。
3) 字段类型仅允许上述枚举。
4) 当字段 type=SingleSelect 或 MultipleSelect 时，必须填写 option_values，长度 3-8，且每个值是可直接展示的“最终文案”。
5) option_values 里的值禁止包含示例引导词或模糊词，如：`如`、`例如`、`比如`、`等`、`等等`、`其他等`。
6) option_values 每个值需为短语（建议 2-8 个字），且同字段内不得重复。
7) 明确禁止 N-N（多对多）关系，只允许 1-1 或 1-N。
8) 当 relationships.cardinality=1-N 时，语义固定为：from=“1”的一端，to=“N”的一端。
9) 当 relationships.cardinality=1-N 时，Relation 字段应定义在 to 表，relation_target 指向 from 表；同一对表禁止 A->B 与 B->A 同时出现 Relation 字段。
10) 当字段 type=Collaborator 时，required 必须为 false。
11) 输出为合法 JSON。
{count_constraint}
""".strip()


def repair_plan(plan: dict) -> None:
    """自动补全 creation_order：把 worksheets 中遗漏的工作表名追加到末尾。"""
    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list):
        return
    names = [str(w.get("name", "")).strip() for w in worksheets if isinstance(w, dict)]
    order = plan.get("creation_order", [])
    if not isinstance(order, list):
        order = []
    missing = [n for n in names if n not in order]
    if missing:
        plan["creation_order"] = order + missing


def ensure_minimum_worksheets(
    plan: dict,
    min_worksheet_count: int,
    business_context: str,
    extra_requirements: str,
) -> None:
    if min_worksheet_count <= 0:
        return
    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list):
        return
    if len(worksheets) >= min_worksheet_count:
        return

    existing_names = {
        str(item.get("name", "")).strip()
        for item in worksheets
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    }
    candidates = extract_scene_candidates(business_context, extra_requirements)

    for scene in candidates:
        if len(worksheets) >= min_worksheet_count:
            break
        ws_name = normalize_scene_to_worksheet_name(scene)
        if not ws_name or ws_name in existing_names:
            continue
        worksheets.append(build_fallback_worksheet(ws_name, scene))
        existing_names.add(ws_name)

    auto_index = 1
    while len(worksheets) < min_worksheet_count:
        ws_name = f"扩展模块{auto_index}"
        auto_index += 1
        if ws_name in existing_names:
            continue
        worksheets.append(build_fallback_worksheet(ws_name, ws_name))
        existing_names.add(ws_name)

    plan["worksheets"] = worksheets
    repair_plan(plan)
    notes = plan.get("notes")
    if not isinstance(notes, list):
        notes = []
    if "已按最少工作表数量要求自动补齐工作表规划。" not in notes:
        notes.append("已按最少工作表数量要求自动补齐工作表规划。")
    plan["notes"] = notes


def validate_plan(plan: dict, min_worksheet_count: int = 0) -> list[str]:
    errors = []
    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list):
        return ["worksheets 必须是数组"]

    if min_worksheet_count > 0 and len(worksheets) < min_worksheet_count:
        errors.append(
            f"worksheets 数量不足: 期望至少 {min_worksheet_count} 张，实际 {len(worksheets)} 张"
        )

    worksheet_names = []
    for index, worksheet in enumerate(worksheets, start=1):
        if not isinstance(worksheet, dict):
            errors.append(f"第 {index} 个工作表不是对象")
            continue
        name = str(worksheet.get("name", "")).strip() or f"第{index}个工作表"
        worksheet_names.append(name)
        fields = worksheet.get("fields", [])
        if not isinstance(fields, list):
            errors.append(f"工作表《{name}》的 fields 必须是数组")

    creation_order = plan.get("creation_order", [])
    if isinstance(creation_order, list) and worksheet_names:
        missing = [name for name in worksheet_names if name not in creation_order]
        if missing:
            errors.append(f"creation_order 缺少工作表: {', '.join(missing)}")
    return errors


def _ai_call(client, model_name: str, prompt: str, ai_config: dict):
    """统一的 AI 调用 + 网络重试。"""
    response = None
    for net_try in range(1, NETWORK_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
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
    return response


def plan_skeleton(
    client,
    model_name: str,
    ai_config: dict,
    app_name: str,
    business_context: str,
    extra_requirements: str,
    min_worksheet_count: int,
    max_worksheet_count: int,
    max_retries: int = MAX_PLAN_RETRIES,
) -> dict:
    """Step 1: 骨架规划 — 表名+用途+核心字段+关联关系。"""
    prompt = build_skeleton_prompt(
        app_name=app_name,
        business_context=business_context,
        extra_requirements=extra_requirements,
        min_worksheets=min_worksheet_count,
        max_worksheets=max_worksheet_count,
    )
    print(f"[skeleton] prompt 长度={len(prompt)}")

    plan = None
    validation_errors: list[str] = []
    for attempt in range(1, max(1, max_retries) + 1):
        current_prompt = prompt
        if validation_errors:
            current_prompt = (
                f"{prompt}\n\n"
                f"上一次结果不合规，请修正以下问题后重新输出完整 JSON：\n"
                + "\n".join(f"- {e}" for e in validation_errors)
            )
        response = _ai_call(client, model_name, current_prompt, ai_config)
        raw_text = response.text or ""

        # 保存原始输出
        raw_path = WORKSHEET_PLAN_DIR / f"skeleton_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}_attempt{attempt}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(raw_text, encoding="utf-8")

        plan = extract_json(raw_text)
        repair_skeleton_plan(plan)
        validation_errors = validate_skeleton_plan(plan, min_worksheets=min_worksheet_count, max_worksheets=max_worksheet_count)
        if validation_errors:
            print(f"[skeleton validate attempt={attempt}] {len(validation_errors)} 个错误: {validation_errors}")
        if not validation_errors:
            break
        if attempt == max(1, max_retries):
            raise ValueError("骨架规划未通过校验: " + "；".join(validation_errors))

    print(f"[skeleton] 完成: {len(plan.get('worksheets', []))} 张表, {len(plan.get('relationships', []))} 条关联")
    return plan


def plan_fields_per_ws(
    client,
    model_name: str,
    ai_config: dict,
    ws_name: str,
    ws_purpose: str,
    ws_id: str,
    existing_fields: list[dict],
    all_worksheets_summary: list[dict],
    max_retries: int = MAX_PLAN_RETRIES,
) -> dict:
    """Step 3: 逐表字段细化 — 为单张表生成完整字段。"""
    prompt = build_fields_prompt_per_ws(
        ws_name=ws_name,
        ws_purpose=ws_purpose,
        ws_id=ws_id,
        existing_fields=existing_fields,
        all_worksheets_summary=all_worksheets_summary,
    )

    existing_names = {str(f.get("name", "")).strip() for f in existing_fields}

    plan = None
    validation_errors: list[str] = []
    for attempt in range(1, max(1, max_retries) + 1):
        current_prompt = prompt
        if validation_errors:
            current_prompt = (
                f"{prompt}\n\n"
                f"上一次结果不合规，请修正以下问题后重新输出完整 JSON：\n"
                + "\n".join(f"- {e}" for e in validation_errors)
            )
        response = _ai_call(client, model_name, current_prompt, ai_config)
        raw_text = response.text or ""

        plan = extract_json(raw_text)
        validation_errors = validate_fields_plan(plan, existing_names)
        if validation_errors:
            print(f"[fields {ws_name} attempt={attempt}] {len(validation_errors)} 个错误: {validation_errors}")
        if not validation_errors:
            break
        if attempt == max(1, max_retries):
            print(f"[fields {ws_name}] 校验仍有错误但已用尽重试，使用最后结果: {validation_errors}", file=sys.stderr)

    fields = plan.get("fields", [])
    print(f"[fields] {ws_name}: {len(fields)} 个新字段")
    return plan


def skeleton_to_full_plan(skeleton: dict, fields_by_ws: dict[str, list[dict]]) -> dict:
    """将骨架 plan + 逐表字段合并为完整的 worksheet_plan.json 格式。

    输出格式与现有 build_enhanced_prompt 的输出完全一致，
    确保下游 create_worksheets_from_plan.py 无需改动。
    """
    worksheets = []
    for ws in skeleton.get("worksheets", []):
        ws_name = str(ws.get("name", "")).strip()
        # 核心字段
        core_fields = []
        for f in ws.get("core_fields", []):
            field = {
                "name": str(f.get("name", "")).strip(),
                "type": str(f.get("type", "Text")).strip(),
                "required": bool(f.get("required", False)),
                "description": str(f.get("description", "")).strip(),
                "relation_target": "",
                "option_values": f.get("option_values", []) or [],
            }
            if f.get("unit"):
                field["unit"] = str(f["unit"])
            if f.get("dot") is not None and f.get("dot") != "":
                field["dot"] = f["dot"]
            core_fields.append(field)

        # 逐表细化的字段
        extra_fields = []
        for f in fields_by_ws.get(ws_name, []):
            field = {
                "name": str(f.get("name", "")).strip(),
                "type": str(f.get("type", "Text")).strip(),
                "required": bool(f.get("required", False)),
                "description": str(f.get("description", "")).strip(),
                "relation_target": str(f.get("relation_target", "")).strip(),
                "option_values": f.get("option_values", []) or [],
            }
            if f.get("unit"):
                field["unit"] = str(f["unit"])
            if f.get("dot") is not None and f.get("dot") != "":
                field["dot"] = f["dot"]
            extra_fields.append(field)

        # 关联字段（从 relationships 提取，定义在 to 表）
        relation_fields = []
        for rel in skeleton.get("relationships", []):
            to_ws = str(rel.get("to", "")).strip()
            if to_ws == ws_name:
                from_ws = str(rel.get("from", "")).strip()
                rel_field_name = str(rel.get("field", from_ws)).strip()
                relation_fields.append({
                    "name": rel_field_name,
                    "type": "Relation",
                    "required": False,
                    "description": str(rel.get("description", "")).strip(),
                    "relation_target": from_ws,
                    "option_values": [],
                })

        worksheets.append({
            "name": ws_name,
            "purpose": str(ws.get("purpose", "")).strip(),
            "fields": core_fields + extra_fields + relation_fields,
            "depends_on": ws.get("depends_on", []) or [],
        })

    return {
        "app_name": str(skeleton.get("app_name", "")).strip(),
        "summary": str(skeleton.get("summary", "")).strip(),
        "worksheets": worksheets,
        "relationships": skeleton.get("relationships", []),
        "creation_order": skeleton.get("creation_order", []),
        "notes": ["使用 layered 模式生成（骨架规划+逐表字段细化）"],
    }


def _run_layered_mode(client, model_name, ai_config, args, min_worksheet_count, max_worksheet_count) -> dict:
    """layered 模式：骨架规划 → 逐表字段细化 → 合并为完整 plan。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Step 1: 骨架规划
    print("=" * 50)
    print("[layered] Step 1: 骨架规划（表名+关联+核心字段）")
    print("=" * 50)
    skeleton = plan_skeleton(
        client, model_name, ai_config,
        app_name=args.app_name,
        business_context=args.business_context,
        extra_requirements=args.requirements,
        min_worksheet_count=min_worksheet_count,
        max_worksheet_count=max_worksheet_count,
        max_retries=args.max_retries,
    )

    # 保存骨架 plan
    WORKSHEET_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    skeleton_path = WORKSHEET_PLAN_DIR / f"skeleton_plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    skeleton_path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[layered] 骨架 plan 已保存: {skeleton_path}")

    # 准备全局表名列表（轻量上下文）
    all_ws_summary = [
        {"name": str(ws.get("name", "")).strip(), "purpose": str(ws.get("purpose", "")).strip()}
        for ws in skeleton.get("worksheets", [])
    ]

    # Step 3: 逐表字段细化（并行）
    print("=" * 50)
    print(f"[layered] Step 3: 逐表字段细化（{len(all_ws_summary)} 张表，并发={args.concurrency}）")
    print("=" * 50)

    semaphore = threading.Semaphore(args.concurrency)
    fields_by_ws: dict[str, list[dict]] = {}

    def _plan_one_ws(ws: dict) -> tuple[str, list[dict]]:
        ws_name = str(ws.get("name", "")).strip()
        ws_purpose = str(ws.get("purpose", "")).strip()
        # 已有字段 = 核心字段 + 关联字段
        existing = []
        for f in ws.get("core_fields", []):
            existing.append({"name": str(f.get("name", "")).strip(), "type": str(f.get("type", "")).strip()})
        # 关联字段（from relationships，定义在 to 表）
        for rel in skeleton.get("relationships", []):
            if str(rel.get("to", "")).strip() == ws_name:
                from_ws = str(rel.get("from", "")).strip()
                rel_field = str(rel.get("field", from_ws)).strip()
                existing.append({"name": rel_field, "type": "Relation"})

        with semaphore:
            result = plan_fields_per_ws(
                client, model_name, ai_config,
                ws_name=ws_name,
                ws_purpose=ws_purpose,
                ws_id="",  # 骨架模式下还没有真实 ID，逐表细化先用空
                existing_fields=existing,
                all_worksheets_summary=all_ws_summary,
                max_retries=args.max_retries,
            )
        return ws_name, result.get("fields", [])

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(_plan_one_ws, ws): ws
            for ws in skeleton.get("worksheets", [])
        }
        for future in as_completed(futures):
            ws_name, fields = future.result()
            fields_by_ws[ws_name] = fields

    # 合并为完整 plan
    full_plan = skeleton_to_full_plan(skeleton, fields_by_ws)

    # 使用增强校验
    repair_plan(full_plan)
    ensure_minimum_worksheets(
        full_plan,
        min_worksheet_count=min_worksheet_count,
        business_context=args.business_context,
        extra_requirements=args.requirements,
    )
    validation_errors = validate_worksheet_plan(full_plan, min_worksheets=min_worksheet_count, max_worksheets=max_worksheet_count)
    if validation_errors:
        print(f"[layered] 合并后校验发现 {len(validation_errors)} 个错误: {validation_errors}", file=sys.stderr)
        # 不抛异常，允许带部分错误通过（下游 create 脚本有自己的容错）

    return full_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="使用 AI 规划应用工作表结构并输出 JSON")
    parser.add_argument("--app-name", required=True, help="应用名称")
    parser.add_argument("--business-context", default="通用企业管理场景", help="业务背景描述")
    parser.add_argument("--requirements", default="", help="额外要求")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="AI 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    parser.add_argument("--max-retries", type=int, default=MAX_PLAN_RETRIES, help="规划校验失败后的最大重试次数")
    parser.add_argument("--max-worksheets", type=int, default=0, help="工作表数量上限（0=不限）")
    parser.add_argument("--concurrency", type=int, default=3, help="逐表字段细化的并发数")
    args = parser.parse_args()

    ai_config = load_ai_config(Path(args.config).expanduser().resolve())
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]
    min_worksheet_count = extract_min_worksheet_count(args.requirements)
    max_worksheet_count = args.max_worksheets

    plan = _run_layered_mode(
        client, model_name, ai_config, args,
        min_worksheet_count, max_worksheet_count,
    )

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        WORKSHEET_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (WORKSHEET_PLAN_DIR / f"worksheet_plan_{sanitize_name(args.app_name)}_{ts}.json").resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    worksheets = plan.get("worksheets", [])
    relationships = plan.get("relationships", [])
    creation_order = plan.get("creation_order", [])
    app_name = str(plan.get("app_name", args.app_name)).strip() or args.app_name
    summary = str(plan.get("summary", "")).strip()

    print("规划完成（概览）")
    print(f"- 应用: {app_name}")
    if summary:
        print(f"- 概述: {summary}")
    print(f"- 工作表数量: {len(worksheets) if isinstance(worksheets, list) else 0}")
    print(f"- 关系数量: {len(relationships) if isinstance(relationships, list) else 0}")
    print(f"- 创建顺序项数: {len(creation_order) if isinstance(creation_order, list) else 0}")
    print(f"- 结果文件: {output_path}")


if __name__ == "__main__":
    main()
