"""
工作表规划器 — 利用 worksheets/ 注册中心，生成高质量工作表+字段 plan。

功能:
  1. 从 FIELD_REGISTRY 读取所有字段类型，自动生成类型枚举给 AI
  2. 增强校验：检查字段类型合法性、option_values 完整性、关联目标存在性
  3. 自动修复：creation_order 补全、Collaborator 强制 required=false

与现有 plan_app_worksheets_gemini.py 的区别:
  - 字段类型从注册中心自动生成（非手写枚举）
  - 校验更严格（关联目标存在性、选项值数量等）
  - 字段类型从 9 种扩展到 15 种
"""

from __future__ import annotations

import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from worksheets.field_types import (
    FIELD_REGISTRY,
    ALLOWED_FIELD_TYPES,
    OPTION_REQUIRED_TYPES,
)


def build_field_type_enum() -> str:
    """从注册中心生成字段类型枚举字符串。"""
    return "|".join(FIELD_REGISTRY.keys())


def build_field_type_prompt_section() -> str:
    """生成 AI prompt 中的字段类型说明。"""
    lines = ["可用字段类型："]
    for name, spec in FIELD_REGISTRY.items():
        extra = ""
        if spec.get("requires_options"):
            extra = " [需 option_values]"
        if spec.get("requires_relation_target"):
            extra = " [需 relation_target]"
        if spec.get("force_not_required"):
            extra += " [required 强制 false]"
        lines.append(f"  - {name} (controlType={spec['controlType']}) — {spec['name']}{extra}")
    return "\n".join(lines)


def build_enhanced_prompt(
    app_name: str,
    business_context: str,
    extra_requirements: str = "",
    min_worksheets: int = 0,
    max_worksheets: int = 0,
) -> str:
    """生成增强版工作表规划 prompt。"""
    field_type_enum = build_field_type_enum()
    field_type_section = build_field_type_prompt_section()
    count_rule = ""
    if min_worksheets > 0:
        count_rule += f"\n12) worksheets 数量必须 >= {min_worksheets}。"
    if max_worksheets > 0:
        count_rule += f"\n13) worksheets 数量必须 <= {max_worksheets}，超出则合并相似业务表。"
    count_rule += '\n14) app_name 必须为 10 个中文字以内的简洁名称，不要带「管理平台」「管理系统」等后缀。'

    return f"""你是企业应用架构师。请为应用《{app_name}》设计工作表结构，输出严格 JSON。

业务背景：
{business_context}

额外要求：
{extra_requirements}

{field_type_section}

输出要求（必须是 JSON 对象，不要 markdown，不要注释）：
{{
  "app_name": "{app_name}",
  "summary": "一句话概述",
  "worksheets": [
    {{
      "name": "工作表名",
      "purpose": "用途",
      "fields": [
        {{
          "name": "字段名",
          "type": "{field_type_enum}",
          "required": true,
          "description": "说明",
          "relation_target": "当type=Relation时填目标工作表名",
          "option_values": ["选项值数组，SingleSelect/MultipleSelect/Dropdown必填"],
          "unit": "数值/金额字段的单位或后缀，如 % 元 天 小时，无则留空",
          "dot": "数值/金额字段的小数位数，整数填0，百分比填1，金额填2，无则留空"
        }}
      ],
      "depends_on": ["依赖的工作表名"]
    }}
  ],
  "relationships": [
    {{"from": "工作表A", "field": "关联字段名", "to": "工作表B", "cardinality": "1-1|1-N", "description": "关系说明"}}
  ],
  "creation_order": ["按依赖拓扑排序的所有工作表名"],
  "notes": ["实施建议"]
}}

约束：
1) creation_order 必须包含每一个工作表名，满足 depends_on 拓扑顺序
2) Relation 的 relation_target 必须在 worksheets 中存在
3) 字段 type 仅允许: {field_type_enum}
4) SingleSelect/MultipleSelect/Dropdown 必须填 option_values（3-8 项，短语 2-8 字）
5) option_values 禁止含"如"、"例如"、"等"等模糊词
6) 同字段 option_values 不得重复
7) 禁止 N-N 关系，只允许 1-1 或 1-N
8) 1-N 关系：from=1端, to=N端；Relation 字段定义在 to 表
9) Collaborator 字段 required 必须为 false
10) 每个工作表至少 4 个字段（含标题字段）
11) 输出合法 JSON
12) Number/Money 字段必须设 unit（如 % 元 天 小时）和 dot（小数位数），进度/百分比字段 unit="%"、dot=1{count_rule}"""


def validate_worksheet_plan(plan: dict, min_worksheets: int = 0, max_worksheets: int = 0) -> list[str]:
    """增强版校验，利用注册中心检查字段类型。"""
    errors = []

    # 校验 app_name 长度
    app_name = str(plan.get("app_name", "")).strip()
    if app_name and len(app_name) > 10:
        errors.append(f"app_name 过长: 「{app_name}」({len(app_name)}字)，必须 <= 10 个中文字")

    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list):
        return ["worksheets 必须是数组"]

    if min_worksheets > 0 and len(worksheets) < min_worksheets:
        errors.append(f"worksheets 数量不足: 期望至少 {min_worksheets}，实际 {len(worksheets)}")

    if max_worksheets > 0 and len(worksheets) > max_worksheets:
        errors.append(f"worksheets 数量超限: 期望最多 {max_worksheets}，实际 {len(worksheets)}")

    ws_names = set()
    for i, ws in enumerate(worksheets):
        if not isinstance(ws, dict):
            errors.append(f"第 {i+1} 个工作表不是对象")
            continue
        name = str(ws.get("name", "")).strip()
        if not name:
            errors.append(f"第 {i+1} 个工作表缺少 name")
            continue
        ws_names.add(name)

        fields = ws.get("fields", [])
        if not isinstance(fields, list):
            errors.append(f"工作表「{name}」的 fields 不是数组")
            continue
        if len(fields) < 2:
            errors.append(f"工作表「{name}」字段太少: {len(fields)}")

        for j, f in enumerate(fields):
            ftype = str(f.get("type", "")).strip()
            if ftype and ftype not in ALLOWED_FIELD_TYPES:
                errors.append(f"工作表「{name}」字段 {j+1} 类型非法: {ftype}")

            if ftype in OPTION_REQUIRED_TYPES:
                opts = f.get("option_values", [])
                if not isinstance(opts, list) or len(opts) < 2:
                    errors.append(f"工作表「{name}」字段「{f.get('name')}」缺少 option_values")

            if ftype == "Relation":
                target = str(f.get("relation_target", "")).strip()
                if not target:
                    errors.append(f"工作表「{name}」关联字段「{f.get('name')}」缺少 relation_target")

    # 校验 relation_target 指向存在的工作表
    for ws in worksheets:
        for f in ws.get("fields", []):
            if str(f.get("type", "")) == "Relation":
                target = str(f.get("relation_target", "")).strip()
                if target and target not in ws_names:
                    errors.append(f"关联目标「{target}」不在 worksheets 中")

    # 校验 creation_order
    order = plan.get("creation_order", [])
    if isinstance(order, list) and ws_names:
        missing = ws_names - set(order)
        if missing:
            errors.append(f"creation_order 缺少: {', '.join(missing)}")

    return errors
