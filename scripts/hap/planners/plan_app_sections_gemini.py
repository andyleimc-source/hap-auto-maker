#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 2c：调用 Gemini 为应用规划工作表分组结构。

读取 worksheet_plan.json，按业务领域将工作表归类为 2-5 个分组，
输出 sections_plan.json 供 create_sections_from_plan.py 使用。
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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

BASE_DIR = Path(__file__).resolve().parents[3]

from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config, parse_ai_json
from utils import now_ts, load_json, write_json

OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
SECTIONS_PLAN_DIR = OUTPUT_ROOT / "sections_plans"


# ---------------------------------------------------------------------------
# AI 规划
# ---------------------------------------------------------------------------

def build_prompt(app_name: str, worksheets: List[dict]) -> str:
    ws_list = "\n".join(
        f"- {ws['name']}: {str(ws.get('purpose', '') or '').strip()}"
        for ws in worksheets
    )
    return f"""你是一名企业应用架构师，正在为「{app_name}」规划应用内的工作表分组结构。

## 工作表列表（共 {len(worksheets)} 张）

{ws_list}

## 任务

请将上述工作表划分为 2-9 个业务分组（Section），每个分组包含功能或业务上相关的工作表。

分组原则：
1. 第一个分组必须固定为"仪表盘"，worksheets 为空数组 []，用于放置统计页面和对话机器人
2. 同一业务领域的工作表放一组（如客户相关、财务相关、生产相关）
3. 每个业务分组最少 2 张工作表，最多 12 张工作表
4. 所有工作表都必须被分配，不能遗漏
5. 分组名称用 2-6 个中文字，简洁明了
6. 如果某分组只剩 1 张工作表，将其合并到最相关的分组中
7. 每个分组内，主表（核心业务表）排在前面，明细表/子表/辅助表排在后面

## 输出格式（严格 JSON，不要任何解释文字）

{{
  "sections": [
    {{
      "name": "仪表盘",
      "worksheets": []
    }},
    {{
      "name": "业务分组名称",
      "worksheets": ["工作表名1", "工作表名2"]
    }}
  ]
}}"""


def call_ai_plan(prompt: str, ai_config: dict, client) -> dict:
    model = ai_config.get("model", "gemini-2.5-flash")
    gen_cfg = create_generation_config(ai_config, response_mime_type="application/json", temperature=0.2)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=gen_cfg,
    )
    return parse_ai_json(response.text)


def validate_sections_plan(plan: dict, worksheet_names: Set[str]) -> None:
    sections = plan.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("sections_plan 缺少 sections 列表或为空")

    assigned: Set[str] = set()
    for i, sec in enumerate(sections):
        name = str(sec.get("name", "")).strip()
        if not name:
            raise ValueError(f"sections[{i}] 缺少 name 字段")
        ws_list = sec.get("worksheets")
        if not isinstance(ws_list, list):
            raise ValueError(f"sections[{i}].worksheets 必须是列表")
        # 允许空分组（如"数据分析"分组，用于后续放统计页面）
        if len(ws_list) > 12:
            raise ValueError(f"分组「{name}」有 {len(ws_list)} 张工作表，每个分组最多允许 12 张")
        for ws_name in ws_list:
            ws_name = str(ws_name).strip()
            if ws_name not in worksheet_names:
                # 工作表名不存在时跳过（AI 可能返回轻微不一致的名称），记录警告
                print(f"[warn] 分组「{name}」中的工作表「{ws_name}」不在 worksheet_plan 中，已跳过", file=sys.stderr)
                continue
            assigned.add(ws_name)

    missing = worksheet_names - assigned
    if missing:
        raise ValueError(f"以下工作表未被分配到任何分组: {missing}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AI 规划工作表分组结构")
    parser.add_argument("--plan-json", required=True, help="worksheet_plan.json 路径")
    parser.add_argument("--output", default="", help="输出 sections_plan.json 路径")
    parser.add_argument("--app-name", default="", help="应用名称（可选，优先从 plan 中读取）")
    args = parser.parse_args()

    plan_path = Path(args.plan_json).expanduser().resolve()
    plan = load_json(plan_path)

    app_name = args.app_name.strip() or str(plan.get("app_name", "") or plan.get("name", "") or "企业应用").strip()
    worksheets = plan.get("worksheets", [])

    if not worksheets:
        print("worksheet_plan 中没有工作表，跳过分组规划")
        sys.exit(0)

    worksheet_names: Set[str] = {str(ws.get("name", "")).strip() for ws in worksheets if ws.get("name")}

    if len(worksheets) < 4:
        # 工作表数量不足以形成多分组，全部放一个默认分组；"仪表盘"排第一
        result = {
            "app_name": app_name,
            "sections": [
                {"name": "仪表盘", "worksheets": []},
                {"name": "全部", "worksheets": list(worksheet_names)},
            ]
        }
    else:
        ai_config = load_ai_config(AI_CONFIG_PATH)
        client = get_ai_client(ai_config)
        prompt = build_prompt(app_name, worksheets)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] 调用 AI 规划分组（{len(worksheets)} 张工作表）...")
        plan_result = call_ai_plan(prompt, ai_config, client)

        validate_sections_plan(plan_result, worksheet_names)
        sections = plan_result["sections"]
        # 确保"仪表盘"分组存在且排第一（防止 AI 不遵守）
        dashboard = next((s for s in sections if s.get("name") == "仪表盘"), None)
        if dashboard is None:
            dashboard = {"name": "仪表盘", "worksheets": []}
            sections.insert(0, dashboard)
        elif sections[0].get("name") != "仪表盘":
            sections.remove(dashboard)
            sections.insert(0, dashboard)
        result = {"app_name": app_name, "sections": sections}

    # 输出路径
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        SECTIONS_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        output_path = SECTIONS_PLAN_DIR / f"sections_plan_{now_ts()}.json"

    write_json(output_path, result)
    print(f"已保存: {output_path}")
    section_names = [s["name"] for s in result["sections"]]
    print(f"规划了 {len(result['sections'])} 个分组: {section_names}")


if __name__ == "__main__":
    main()
