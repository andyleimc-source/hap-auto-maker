#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 Gemini 规划某个应用下的工作表、关联关系、创建顺序，并输出 JSON。
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
DEFAULT_MODEL = "gemini-3-flash-preview"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"
MIN_WORKSHEETS = 8
MAX_WORKSHEETS = 15
MIN_FIELDS_PER_WORKSHEET = 10
MAX_FIELDS_PER_WORKSHEET = 15
MAX_PLAN_RETRIES = 3


def load_api_key(config_path: Path) -> str:
    if not config_path.exists():
        raise FileNotFoundError(f"缺少配置文件: {config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    api_key = data.get("api_key", "").strip()
    if not api_key:
        raise ValueError(f"配置缺少 api_key: {config_path}")
    return api_key


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "app"


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Gemini 返回为空")

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 容错：提取第一个 JSON 对象
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Gemini 未返回可解析的 JSON:\n{text}")


def build_prompt(app_name: str, business_context: str, extra_requirements: str) -> str:
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
  "creation_order": ["按创建顺序排列的工作表名"],
  "notes": ["实施建议1", "实施建议2"]
}}

约束：
1) creation_order 必须满足 depends_on 的依赖拓扑顺序。
2) worksheets 中涉及 Relation 的 relation_target 必须在 worksheets 中存在。
3) 字段类型仅允许上述枚举。
4) 工作表数量必须在 {MIN_WORKSHEETS}-{MAX_WORKSHEETS} 张之间。
5) 每张工作表的 fields 数量必须在 {MIN_FIELDS_PER_WORKSHEET}-{MAX_FIELDS_PER_WORKSHEET} 个之间，fields 总数包含 Relation 字段。
6) 当字段 type=SingleSelect 或 MultipleSelect 时，必须填写 option_values，长度 3-8，且每个值是可直接展示的“最终文案”。
7) option_values 里的值禁止包含示例引导词或模糊词，如：`如`、`例如`、`比如`、`等`、`等等`、`其他等`。
8) option_values 每个值需为短语（建议 2-8 个字），且同字段内不得重复。
9) 明确禁止 N-N（多对多）关系，只允许 1-1 或 1-N。
10) 当 relationships.cardinality=1-N 时，语义固定为：from=“1”的一端，to=“N”的一端。
11) 当 relationships.cardinality=1-N 时，Relation 字段应定义在 to 表，relation_target 指向 from 表；同一对表禁止 A->B 与 B->A 同时出现 Relation 字段。
12) 当字段 type=Collaborator 时，required 必须为 false。
13) 输出为合法 JSON。
""".strip()


def validate_plan(plan: dict) -> list[str]:
    errors = []
    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list):
        return ["worksheets 必须是数组"]

    worksheet_count = len(worksheets)
    if worksheet_count < MIN_WORKSHEETS or worksheet_count > MAX_WORKSHEETS:
        errors.append(
            f"工作表数量超出范围: 当前 {worksheet_count}，要求 {MIN_WORKSHEETS}-{MAX_WORKSHEETS}"
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
            continue
        field_count = len(fields)
        if field_count < MIN_FIELDS_PER_WORKSHEET or field_count > MAX_FIELDS_PER_WORKSHEET:
            errors.append(
                f"工作表《{name}》字段数量超出范围: 当前 {field_count}，要求 {MIN_FIELDS_PER_WORKSHEET}-{MAX_FIELDS_PER_WORKSHEET}"
            )

    creation_order = plan.get("creation_order", [])
    if isinstance(creation_order, list) and worksheet_names:
        missing = [name for name in worksheet_names if name not in creation_order]
        if missing:
            errors.append(f"creation_order 缺少工作表: {', '.join(missing)}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="使用 Gemini 规划应用工作表结构并输出 JSON")
    parser.add_argument("--app-name", required=True, help="应用名称")
    parser.add_argument("--business-context", default="通用企业管理场景", help="业务背景描述")
    parser.add_argument("--requirements", default="", help="额外要求")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    parser.add_argument("--max-retries", type=int, default=MAX_PLAN_RETRIES, help="规划校验失败后的最大重试次数")
    args = parser.parse_args()

    api_key = load_api_key(Path(args.config).expanduser().resolve())
    client = genai.Client(api_key=api_key)

    prompt = build_prompt(args.app_name, args.business_context, args.requirements)
    plan = None
    validation_errors: list[str] = []
    for attempt in range(1, max(1, args.max_retries) + 1):
        current_prompt = prompt
        if validation_errors:
            current_prompt = (
                f"{prompt}\n\n"
                f"上一次结果不合规，请严格修正以下问题后重新输出完整 JSON：\n"
                + "\n".join(f"- {item}" for item in validation_errors)
            )
        response = client.models.generate_content(
            model=args.model,
            contents=current_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        plan = extract_json(response.text or "")
        validation_errors = validate_plan(plan)
        if not validation_errors:
            break
        if attempt == max(1, args.max_retries):
            raise ValueError(
                "工作表规划未通过校验: " + "；".join(validation_errors)
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
    print(f"- 数量校验: 已通过（工作表 {MIN_WORKSHEETS}-{MAX_WORKSHEETS} 张；每表字段 {MIN_FIELDS_PER_WORKSHEET}-{MAX_FIELDS_PER_WORKSHEET} 个）")
    print(f"- 结果文件: {output_path}")


if __name__ == "__main__":
    main()
