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
from i18n import normalize_language


def build_field_type_enum() -> str:
    """从注册中心生成字段类型枚举字符串（排除 ai_disabled 类型）。"""
    return "|".join(k for k, v in FIELD_REGISTRY.items() if not v.get("ai_disabled"))


def build_field_type_prompt_section(language: str = "zh") -> str:
    """生成 AI prompt 中的字段类型说明（排除 ai_disabled 类型）。"""
    lang = normalize_language(language)
    lines = ["Available field types:"] if lang == "en" else ["可用字段类型："]
    for name, spec in FIELD_REGISTRY.items():
        if spec.get("ai_disabled"):
            continue
        extra = ""
        if spec.get("requires_options"):
            extra = " [option_values required]" if lang == "en" else " [需 option_values]"
        if spec.get("requires_relation_target"):
            extra = " [relation_target required]" if lang == "en" else " [需 relation_target]"
        if spec.get("force_not_required"):
            extra += " [required must be false]" if lang == "en" else " [required 强制 false]"
        lines.append(f"  - {name} (controlType={spec['controlType']}) — {spec['name']}{extra}")
    return "\n".join(lines)


# ─── 3 阶段建表：Step 1 骨架规划 ─────────────────────────────────────────────


def build_skeleton_prompt(
    app_name: str,
    business_context: str,
    extra_requirements: str = "",
    min_worksheets: int = 0,
    max_worksheets: int = 0,
    language: str = "zh",
) -> str:
    """Step 1 — 只规划表名、用途、核心字段（1-3 个）和关联关系。

    不要求 AI 设计完整字段列表，只关注业务建模和表间关系。
    输出的 skeleton plan 将传给 build_fields_prompt_per_ws() 进行逐表字段细化。
    """
    lang = normalize_language(language)
    count_rule = ""
    if min_worksheets > 0:
        count_rule += f"\n10) worksheets 数量必须 >= {min_worksheets}。"
    if max_worksheets > 0:
        count_rule += f"\n11) worksheets 数量必须 <= {max_worksheets}，超出则合并相似业务表。"

    if lang == "en":
        return f"""You are an enterprise app architect. Design worksheet skeleton for app \"{app_name}\" and output strict JSON.

Business context:
{business_context}

Extra requirements:
{extra_requirements}

Task:
1. Plan worksheets (name + purpose)
2. For each worksheet, provide 1-3 core fields
3. Define relationships between worksheets

Output strict JSON:
{{
  "app_name": "{app_name}",
  "summary": "one-line summary",
  "worksheets": [
    {{
      "name": "Worksheet name",
      "purpose": "One-line purpose",
      "core_fields": [
        {{
          "name": "Field name",
          "type": "Text|Number|Money|SingleSelect|MultipleSelect|Dropdown|Date|DateTime|Collaborator|Phone|Email|RichText|Attachment|Rating|Checkbox",
          "required": true,
          "option_values": ["required for select/dropdown fields"],
          "unit": "optional unit, e.g. USD, %, days",
          "dot": "optional decimal places"
        }}
      ],
      "depends_on": ["Worksheet names"]
    }}
  ],
  "relationships": [
    {{"from": "WorksheetA", "field": "Relation field", "to": "WorksheetB", "cardinality": "1-1|1-N", "description": "description"}}
  ],
  "creation_order": ["all worksheet names in topological order"]
}}

Constraints:
1) core_fields should be 1-3 only
2) first core field should be title field (Text + required=true)
3) no Relation type in core_fields
4) creation_order must include every worksheet
5) no N-N relation, only 1-1 or 1-N
6) for 1-N relation: from=1 side, to=N side; relation field is defined on to side
7) select/dropdown fields must provide option_values (3-8 items)
8) Collaborator required must be false{count_rule}"""

    return f"""你是企业应用架构师。请为应用《{app_name}》设计工作表结构骨架，输出严格 JSON。

业务背景：
{business_context}

额外要求：
{extra_requirements}

## 任务

只需规划：
1. 有哪些工作表（表名 + 用途）
2. 每个表的 1-3 个核心字段（最能代表这张表的字段，含类型和选项值）
3. 表之间的关联关系

不需要设计完整字段列表，后续会逐表细化。

## 输出格式（严格 JSON，不要 markdown，不要注释）

{{
  "app_name": "{app_name}",
  "summary": "一句话概述",
  "worksheets": [
    {{
      "name": "工作表名（2-6个中文字）",
      "purpose": "一句话用途说明",
      "core_fields": [
        {{
          "name": "字段名",
          "type": "Text|Number|Money|SingleSelect|MultipleSelect|Dropdown|Date|DateTime|Collaborator|Phone|Email|RichText|Attachment|Rating|Checkbox",
          "required": true,
          "option_values": ["当type为SingleSelect/MultipleSelect/Dropdown时必填"],
          "unit": "数值/金额字段的单位（如 元 % 天），无则留空",
          "dot": "小数位数（整数填0，百分比填1，金额填2），无则留空"
        }}
      ],
      "depends_on": ["依赖的工作表名"]
    }}
  ],
  "relationships": [
    {{"from": "工作表A", "field": "关联字段名", "to": "工作表B", "cardinality": "1-1|1-N", "description": "关系说明"}}
  ],
  "creation_order": ["按依赖拓扑排序的所有工作表名"]
}}

## 约束

1) 每个工作表的 core_fields 只需 1-3 个最核心的字段，不要多
2) core_fields 中第一个字段应为标题字段（type=Text, required=true）
3) core_fields 不要包含 Relation 类型——关联关系通过 relationships 数组声明
4) creation_order 必须包含每一个工作表名，满足 depends_on 拓扑顺序
5) 禁止 N-N 关系，只允许 1-1 或 1-N
6) 1-N 关系：from=1端, to=N端；Relation 字段定义在 to 表
7) SingleSelect/MultipleSelect/Dropdown 必须填 option_values（3-8 项，短语 2-8 字）
8) app_name 必须为 10 个中文字以内的简洁名称，不要带「管理平台」「管理系统」等后缀
9) Collaborator 字段 required 必须为 false{count_rule}"""


def validate_skeleton_plan(
    plan: dict,
    min_worksheets: int = 0,
    max_worksheets: int = 0,
    language: str = "zh",
) -> list[str]:
    """校验骨架 plan：表名、关联关系、creation_order、核心字段类型。"""
    errors = []
    lang = normalize_language(language)

    app_name = str(plan.get("app_name", "")).strip()
    if app_name:
        if lang == "en" and len(app_name) > 40:
            errors.append(f'app_name too long: "{app_name}" ({len(app_name)} chars), must be <= 40 characters')
        if lang != "en" and len(app_name) > 10:
            errors.append(f"app_name 过长: 「{app_name}」({len(app_name)}字)")

    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list):
        return ["worksheets 必须是数组"]

    if not worksheets:
        return ["worksheets 不能为空"]

    if min_worksheets > 0 and len(worksheets) < min_worksheets:
        errors.append(f"worksheets 数量不足: 期望至少 {min_worksheets}，实际 {len(worksheets)}")
    if max_worksheets > 0 and len(worksheets) > max_worksheets:
        errors.append(f"worksheets 数量超限: 期望最多 {max_worksheets}，实际 {len(worksheets)}")

    ws_names: set[str] = set()
    for i, ws in enumerate(worksheets):
        if not isinstance(ws, dict):
            errors.append(f"第 {i+1} 个工作表不是对象")
            continue
        name = str(ws.get("name", "")).strip()
        if not name:
            errors.append(f"第 {i+1} 个工作表缺少 name")
            continue
        if name in ws_names:
            errors.append(f"工作表名重复: 「{name}」")
        ws_names.add(name)

        # 校验 core_fields
        core_fields = ws.get("core_fields", [])
        if not isinstance(core_fields, list):
            errors.append(f"工作表「{name}」的 core_fields 不是数组")
            continue
        if len(core_fields) < 1:
            errors.append(f"工作表「{name}」的 core_fields 至少需要 1 个字段")
        if len(core_fields) > 5:
            errors.append(f"工作表「{name}」的 core_fields 最多 5 个（当前 {len(core_fields)}）")

        for j, f in enumerate(core_fields):
            if not isinstance(f, dict):
                continue
            ftype = str(f.get("type", "")).strip()
            if ftype == "Relation":
                errors.append(f"工作表「{name}」core_fields[{j}] 不应包含 Relation 类型")
            if ftype and ftype in ALLOWED_FIELD_TYPES:
                if FIELD_REGISTRY.get(ftype, {}).get("ai_disabled"):
                    errors.append(f"工作表「{name}」core_fields[{j}] 类型 {ftype} 已禁用")
                if ftype in OPTION_REQUIRED_TYPES:
                    opts = f.get("option_values", [])
                    if not isinstance(opts, list) or len(opts) < 2:
                        errors.append(f"工作表「{name}」core_fields[{j}]「{f.get('name')}」缺少 option_values")

    # 校验 relationships
    relationships = plan.get("relationships", [])
    if isinstance(relationships, list):
        for i, rel in enumerate(relationships):
            if not isinstance(rel, dict):
                continue
            from_ws = str(rel.get("from", "")).strip()
            to_ws = str(rel.get("to", "")).strip()
            card = str(rel.get("cardinality", "")).strip()
            if from_ws and from_ws not in ws_names:
                errors.append(f"relationships[{i}] from「{from_ws}」不在 worksheets 中")
            if to_ws and to_ws not in ws_names:
                errors.append(f"relationships[{i}] to「{to_ws}」不在 worksheets 中")
            if card and card not in ("1-1", "1-N"):
                errors.append(f"relationships[{i}] cardinality「{card}」非法，只允许 1-1 或 1-N")

    # 校验 creation_order
    order = plan.get("creation_order", [])
    if isinstance(order, list) and ws_names:
        missing = ws_names - set(str(n).strip() for n in order)
        if missing:
            errors.append(f"creation_order 缺少: {', '.join(missing)}")

    return errors


def repair_skeleton_plan(plan: dict) -> None:
    """自动修复骨架 plan：补全 creation_order、修复 Collaborator required。"""
    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list):
        return

    names = [str(w.get("name", "")).strip() for w in worksheets if isinstance(w, dict)]

    # 补全 creation_order
    order = plan.get("creation_order", [])
    if not isinstance(order, list):
        order = []
    missing = [n for n in names if n not in order]
    if missing:
        plan["creation_order"] = order + missing

    # 修复 Collaborator required
    for ws in worksheets:
        for f in ws.get("core_fields", []):
            if isinstance(f, dict) and str(f.get("type", "")).strip() == "Collaborator":
                f["required"] = False


# ─── 3 阶段建表：Step 3 逐表字段细化 ─────────────────────────────────────────


def build_fields_prompt_per_ws(
    ws_name: str,
    ws_purpose: str,
    ws_id: str,
    existing_fields: list[dict],
    all_worksheets_summary: list[dict],
    language: str = "zh",
) -> str:
    """Step 3 — 为单张工作表生成完整字段列表。

    Args:
        ws_name: 工作表名称
        ws_purpose: 工作表用途
        ws_id: 真实 worksheetId
        existing_fields: 该表已有的字段（核心字段+关联字段）[{name, type}]
        all_worksheets_summary: 全局表名列表 [{name, purpose}]，轻量上下文
    """
    field_type_enum = build_field_type_enum()
    field_type_section = build_field_type_prompt_section(language=lang)
    lang = normalize_language(language)

    existing_lines = "\n".join(
        f"  - {f['name']}（{f.get('type', '未知')}）"
        for f in existing_fields
    )

    global_context_lines = "\n".join(
        f"  - {ws['name']}: {ws.get('purpose', '')}"
        for ws in all_worksheets_summary
    )

    if lang == "en":
        return f"""You are an enterprise app field-design expert. Design additional business fields for worksheet \"{ws_name}\".

## Worksheet info
- Name: {ws_name}
- Purpose: {ws_purpose}
- worksheetId: {ws_id}

## Existing fields (do not duplicate)
{existing_lines}

## Other worksheets (for context)
{global_context_lines}

{field_type_section}

## Output strict JSON (no markdown)
{{
  "worksheetId": "{ws_id}",
  "worksheetName": "{ws_name}",
  "fields": [
    {{
      "name": "Field name",
      "type": "{field_type_enum}",
      "required": true,
      "description": "description",
      "option_values": ["required when select/dropdown, 3-8 items"],
      "unit": "optional unit",
      "dot": "optional decimals"
    }}
  ]
}}

Constraints:
1) Do not generate Relation fields in this step
2) Do not duplicate existing field names
3) Field count should be 5-12
4) type must be one of: {field_type_enum}
5) Select/MultipleSelect/Dropdown must provide option_values
6) Number/Money fields must provide unit and dot
7) Collaborator required must be false
8) Return valid JSON only"""

    return f"""你是企业应用字段设计专家。请为工作表「{ws_name}」设计完整的业务字段。

## 工作表信息
- 名称：{ws_name}
- 用途：{ws_purpose}
- worksheetId：{ws_id}

## 已有字段（不要重复生成）
{existing_lines}

## 应用中的其他工作表（仅供参考，了解业务全貌）
{global_context_lines}

{field_type_section}

## 任务

为这张工作表设计 **额外的** 业务字段（不包含上面已有的字段）。

## 输出格式（严格 JSON，不要 markdown）

{{
  "worksheetId": "{ws_id}",
  "worksheetName": "{ws_name}",
  "fields": [
    {{
      "name": "字段名",
      "type": "{field_type_enum}",
      "required": true或false,
      "description": "字段说明",
      "option_values": ["当type为SingleSelect/MultipleSelect/Dropdown时必填，3-8项"],
      "unit": "数值/金额字段的单位（如 元 % 天 小时），无则留空",
      "dot": "小数位数（整数填0，百分比填1，金额填2），无则留空"
    }}
  ]
}}

## 约束

1) 不要生成 Relation 类型字段——关联字段已在上方「已有字段」中
2) 不要重复已有字段的名称
3) 字段数量 5-12 个，覆盖该业务场景的关键维度
4) 字段 type 仅允许: {field_type_enum}（不含 Relation）
5) SingleSelect/MultipleSelect/Dropdown 必须填 option_values（3-8 项，短语 2-8 字）
6) option_values 禁止含"如"、"例如"、"等"等模糊词
7) Number/Money 字段必须设 unit 和 dot
8) Collaborator 字段 required 必须为 false
9) 字段命名要专业、简洁（2-6 个中文字）
10) 输出合法 JSON"""


def validate_fields_plan(
    plan: dict,
    existing_field_names: set[str],
) -> list[str]:
    """校验逐表生成的字段：类型合法性、options 完整性、不与已有字段重复。"""
    errors = []

    fields = plan.get("fields", [])
    if not isinstance(fields, list):
        return ["fields 必须是数组"]

    if len(fields) < 3:
        errors.append(f"字段数量过少: {len(fields)}（至少 3 个）")

    seen_names: set[str] = set()
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            errors.append(f"fields[{i}] 不是对象")
            continue

        fname = str(f.get("name", "")).strip()
        if not fname:
            errors.append(f"fields[{i}] 缺少 name")
            continue

        if fname in existing_field_names:
            errors.append(f"fields[{i}]「{fname}」与已有字段重复")
        if fname in seen_names:
            errors.append(f"fields[{i}]「{fname}」在本次输出中重复")
        seen_names.add(fname)

        ftype = str(f.get("type", "")).strip()
        if not ftype:
            errors.append(f"fields[{i}]「{fname}」缺少 type")
            continue

        if ftype == "Relation":
            errors.append(f"fields[{i}]「{fname}」不应包含 Relation 类型")
            continue

        if ftype not in ALLOWED_FIELD_TYPES:
            errors.append(f"fields[{i}]「{fname}」类型非法: {ftype}")
        elif FIELD_REGISTRY.get(ftype, {}).get("ai_disabled"):
            reason = FIELD_REGISTRY[ftype].get("ai_disabled_reason", "AI 禁用")
            errors.append(f"fields[{i}]「{fname}」类型 {ftype} 已禁用: {reason}")

        if ftype in OPTION_REQUIRED_TYPES:
            opts = f.get("option_values", [])
            if not isinstance(opts, list) or len(opts) < 2:
                errors.append(f"fields[{i}]「{fname}」缺少 option_values")

        if ftype == "Collaborator" and f.get("required") is True:
            f["required"] = False  # 自动修复

    return errors


# ─── 原有一体化接口 ──────────────────────────────────────────────────────────


def build_enhanced_prompt(
    app_name: str,
    business_context: str,
    extra_requirements: str = "",
    min_worksheets: int = 0,
    max_worksheets: int = 0,
    language: str = "zh",
) -> str:
    """生成增强版工作表规划 prompt。"""
    lang = normalize_language(language)
    field_type_enum = build_field_type_enum()
    field_type_section = build_field_type_prompt_section(language=lang)
    count_rule = ""
    if min_worksheets > 0:
        count_rule += f"\n12) worksheets 数量必须 >= {min_worksheets}。"
    if max_worksheets > 0:
        count_rule += f"\n13) worksheets 数量必须 <= {max_worksheets}，超出则合并相似业务表。"
    count_rule += '\n14) app_name 必须为 10 个中文字以内的简洁名称，不要带「管理平台」「管理系统」等后缀。'

    if lang == "en":
        return f"""You are an enterprise app architect. Design worksheet structure for app \"{app_name}\" and output strict JSON.

Business context:
{business_context}

Extra requirements:
{extra_requirements}

{field_type_section}

Output strict JSON:
{{
  "app_name": "{app_name}",
  "summary": "one-line summary",
  "worksheets": [
    {{
      "name": "Worksheet name",
      "purpose": "purpose",
      "fields": [
        {{
          "name": "Field name",
          "type": "{field_type_enum}",
          "required": true,
          "description": "description",
          "relation_target": "",
          "option_values": [],
          "unit": "",
          "dot": ""
        }}
      ],
      "depends_on": ["dependencies"]
    }}
  ],
  "relationships": [
    {{"from": "WorksheetA", "field": "Relation field", "to": "WorksheetB", "cardinality": "1-1|1-N", "description": "description"}}
  ],
  "creation_order": ["all worksheet names in topological order"],
  "notes": ["implementation notes"]
}}

Constraints:
1) creation_order must include every worksheet and satisfy dependencies
2) relation_target must exist in worksheets
3) field type must be one of: {field_type_enum}
4) select/dropdown fields must provide option_values
5) no N-N relation, only 1-1 or 1-N
6) Collaborator required must be false
7) Number/Money fields must provide unit and dot{count_rule}"""

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


def validate_worksheet_plan(
    plan: dict,
    min_worksheets: int = 0,
    max_worksheets: int = 0,
    language: str = "zh",
) -> list[str]:
    """增强版校验，利用注册中心检查字段类型。"""
    errors = []
    lang = normalize_language(language)

    # 校验 app_name 长度
    app_name = str(plan.get("app_name", "")).strip()
    if app_name:
        if lang == "en" and len(app_name) > 40:
            errors.append(f'app_name too long: "{app_name}" ({len(app_name)} chars), must be <= 40 characters')
        if lang != "en" and len(app_name) > 10:
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
            elif ftype and FIELD_REGISTRY.get(ftype, {}).get("ai_disabled"):
                reason = FIELD_REGISTRY[ftype].get("ai_disabled_reason", "AI 规划禁止使用")
                errors.append(f"工作表「{name}」字段 {j+1} 类型 {ftype} 已禁用: {reason}")

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
