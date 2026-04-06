"""
图表规划器 — 利用 charts/ 注册中心 + 字段分类，生成高质量图表 plan。

功能:
  1. 分析工作表字段，推荐适合的图表类型
  2. 生成包含类型约束的 AI prompt（使用 chart_config_schema 完整 schema）
  3. 校验 AI 输出（字段存在性 + 类型兼容性）
  4. 输出 plan JSON 供 create_charts_from_plan.py 执行

Schema 来源:
  - scripts/hap/charts/chart_config_schema.py — 17 种图表的完整参数定义
  - scripts/hap/charts/__init__.py — 注册中心导出

与 plan_charts_gemini.py 的区别:
  - 利用 CHART_SCHEMA 元数据指导 AI 选型（更详细的类型说明）
  - 字段分类后给 AI 更精准的推荐
  - 校验增加字段类型兼容性检查（基于 XAXES_NULL_TYPES 等常量）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_BASE = Path(__file__).resolve().parents[1]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from planning.constraints import (
    build_chart_type_prompt_section,
    classify_fields,
    suggest_chart_types,
    SYSTEM_FIELDS,
    get_chart_constraints,
)

# 导入完整 schema（优先使用）
try:
    from charts.chart_config_schema import (
        CHART_SCHEMA,
        XAXES_NULL_TYPES,
        SHOW_PERCENT_TYPES,
        DUAL_AXIS_TYPE,
        VERIFIED_TYPES,
        get_ai_prompt_section,
        list_chart_types,
        AI_PLANNING_GUIDE,
    )
    _HAS_SCHEMA = True
except ImportError:
    _HAS_SCHEMA = False


def build_enhanced_prompt(
    app_name: str,
    worksheets_info: list[dict],
    target_count: int = 10,
) -> str:
    """生成增强版图表规划 prompt，包含类型约束和字段推荐。

    Args:
        app_name: 应用名称
        worksheets_info: [{worksheetId, worksheetName, fields: [{controlId, controlName, type, options}]}]
        target_count: 目标图表数量 (8-12)
    """
    # 1. 图表类型说明（优先使用完整 schema）
    if _HAS_SCHEMA:
        chart_type_section = get_ai_prompt_section()
    else:
        chart_type_section = build_chart_type_prompt_section()

    # 2. 工作表 + 字段 + 推荐
    ws_sections = []
    for ws in worksheets_info:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        classified = classify_fields(fields)
        suggestions = suggest_chart_types(classified)

        lines = [f"\n### 工作表「{ws_name}」(ID: {ws_id})"]
        lines.append("字段：")

        for cat_name, cat_label in [
            ("select", "单选/下拉"), ("number", "数值"), ("date", "日期"),
            ("text", "文本"), ("user", "成员"), ("relation", "关联"),
        ]:
            cat_fields = classified.get(cat_name, [])
            if cat_fields:
                field_strs = []
                for f in cat_fields:
                    s = f"  {f['id']}  {f['name']}(type={f['type']})"
                    if f.get("options"):
                        opts = ", ".join(f"{o['key'][:12]}={o['value']}" for o in f["options"][:4])
                        s += f"  选项: {opts}"
                    field_strs.append(s)
                lines.append(f"  [{cat_label}]")
                lines.extend(field_strs)

        if suggestions:
            lines.append("  推荐图表：")
            for sg in suggestions[:3]:
                lines.append(f"    - reportType={sg['reportType']} {sg['reason']}")

        ws_sections.append("\n".join(lines))

    ws_detail = "\n".join(ws_sections)

    return f"""你是一名数据可视化专家，正在为「{app_name}」规划统计图表。

{chart_type_section}

## 应用工作表与字段
{ws_detail}

## 任务

请规划 {target_count} 个统计图表，覆盖多种图表类型，展示不同的业务分析视角。

规划原则：
1. 每个图表必须有明确的业务分析目的
2. 图表类型要多样化（至少使用 6 种不同 reportType），且必须包含至少 1 个 KPI 类图表(数值图10/仪表盘14/进度图15)和至少 1 个非柱图/饼图类型(如漏斗图6/排行图16/透视表8/双轴图7)
3. 覆盖尽可能多的工作表（不要集中在一个表上）
4. xaxes.controlId 和 yaxisList[].controlId 必须来自上方字段列表或系统字段（ctime/utime/record_count）
5. 数值图(10)/仪表盘(14)/进度图(15)的 xaxes.controlId 必须设为空字符串
6. 饼图(3) xaxes 应使用单选/下拉字段（type=9/11），不能用布尔(36)或关联(29/30)字段
7. 折线图(2) xaxes 必须使用日期字段（type=15/16），设 particleSizeType=1(月)或4(日)，不能用季度(0)
8. 关联字段(controlType=29/30/34) 绝对不能作为 xaxes 维度，无法聚合。改用该表的单选/文本字段
9. 词云图(13) xaxes 必须使用单选/下拉字段（type=9/11），不能用普通文本(type=2)
8. 图表名称 ≤10 个字，简洁有业务含义
9. yaxisList 至少 1 项，可用 record_count（记录数量）或数值字段

## 输出格式（严格 JSON）

{{
  "charts": [
    {{
      "name": "图表名称",
      "desc": "一句话描述分析目的",
      "reportType": 1,
      "worksheetId": "来自上方的工作表 ID",
      "xaxes": {{
        "controlId": "字段ID 或 null(仅数值图)",
        "controlType": 字段type数字,
        "particleSizeType": 0,
        "sortType": 0,
        "emptyType": 0
      }},
      "yaxisList": [
        {{
          "controlId": "字段ID 或 record_count",
          "controlType": 字段type数字或0,
          "rename": "显示名称"
        }}
      ],
      "filter": {{
        "filterRangeId": "ctime",
        "filterRangeName": "创建时间",
        "rangeType": 0,
        "rangeValue": 0,
        "today": false
      }}
    }}
  ]
}}"""


# ─── Phase 1: 图表结构规划（轻量 prompt，只决定图表分配）────────────────────────


def build_chart_structure_prompt(
    app_id: str,
    app_name: str,
    worksheets_summary: list[dict],
) -> str:
    """Phase 1 — 只决定哪些表出哪些类型的图表，每个图叫什么名字。

    不要求 AI 填写 xaxes/yaxisList/filter 等详细配置。
    输出的 plan 将传给 build_chart_config_prompt_per_ws() 进行逐表细化。

    Args:
        app_id: 应用 ID
        app_name: 应用名称
        worksheets_summary: [{worksheetId, worksheetName, field_summary: str}]
            field_summary 是字段名和类型的摘要文本，不含 options/详细配置
    """
    # 图表类型说明
    if _HAS_SCHEMA:
        chart_type_section = get_ai_prompt_section()
    else:
        chart_type_section = build_chart_type_prompt_section()

    # 工作表摘要
    ws_lines = []
    for ws in worksheets_summary:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        field_summary = ws.get("field_summary", "")
        ws_lines.append(f"\n### 工作表「{ws_name}」(ID: {ws_id})")
        ws_lines.append(field_summary)

    ws_detail = "\n".join(ws_lines)

    return f"""你是一名数据可视化专家，正在为「{app_name}」规划统计图表的整体结构。

{chart_type_section}

## 应用工作表摘要
{ws_detail}

## 任务

请规划 8-12 个统计图表，只需决定：
- 每个图表属于哪个工作表
- 每个图表的类型（reportType）
- 每个图表的名称

不需要填写 xaxes、yaxisList、filter 等详细配置。

## 规划原则

1. 图表类型要多样化（至少使用 6 种不同 reportType）
2. 必须包含至少 1 个 KPI 类图表（数值图10/仪表盘14/进度图15）
3. 必须包含至少 1 个非柱图/饼图类型（如漏斗图6/排行图16/透视表8/双轴图7）
4. 覆盖尽可能多的工作表（不要集中在一个表上）
5. 图表名称 ≤10 个字，简洁有业务含义
6. worksheetId 必须来自上方

## 输出 JSON 格式（严格 JSON，无注释）

{{
  "charts": [
    {{
      "name": "图表名称",
      "reportType": 1,
      "worksheetId": "来自上方的工作表 ID",
      "worksheetName": "工作表名称"
    }}
  ]
}}"""


def validate_chart_structure(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> list[dict]:
    """Phase 1 校验 — 检查图表分配的基本合法性。

    Args:
        raw: AI 输出的原始 JSON
        worksheets_by_id: {worksheetId: {fields: [...]}}

    Returns:
        校验通过的 charts 列表

    Raises:
        ValueError: 校验失败
    """
    if _HAS_SCHEMA:
        valid_types = set(CHART_SCHEMA.keys())
    else:
        constraints = get_chart_constraints()
        valid_types = set(constraints["types"].keys())

    charts = raw.get("charts", [])
    if not isinstance(charts, list) or len(charts) == 0:
        raise ValueError("未返回 charts 数组")
    if len(charts) < 5:
        raise ValueError(f"图表数量不足，只返回 {len(charts)} 个，至少需要 5 个")

    validated = []
    for i, chart in enumerate(charts):
        if not isinstance(chart, dict):
            raise ValueError(f"图表 {i+1} 格式错误")

        name = str(chart.get("name", "")).strip()
        if not name:
            raise ValueError(f"图表 {i+1} 缺少 name")

        report_type = int(chart.get("reportType", 0) or 0)
        if report_type not in valid_types:
            raise ValueError(f"图表 {i+1} reportType={report_type} 不在支持列表 {sorted(valid_types)} 中")

        worksheet_id = str(chart.get("worksheetId", "")).strip()
        if not worksheet_id:
            raise ValueError(f"图表 {i+1}「{name}」缺少 worksheetId")
        if worksheet_id not in worksheets_by_id:
            raise ValueError(f"图表 {i+1}「{name}」worksheetId={worksheet_id!r} 不存在")

        validated.append(chart)

    # 检查类型多样性
    used_types = {int(c.get("reportType", 0)) for c in validated}
    if len(used_types) < 4:
        raise ValueError(f"图表类型太少，只使用了 {len(used_types)} 种，至少需要 4 种不同 reportType")

    return validated


# ─── Phase 2 逐表: 图表详细配置（单工作表粒度）──────────────────────────────────


def build_chart_config_prompt_per_ws(
    app_id: str,
    app_name: str,
    ws_info: dict,
    assigned_charts: list[dict],
) -> str:
    """Phase 2 逐表版 — 为分配给该工作表的图表生成完整配置。

    Args:
        app_id: 应用 ID
        app_name: 应用名称
        ws_info: 该表的完整字段信息
            {worksheetId, worksheetName, fields: [{id, name, type, options}]}
        assigned_charts: Phase1 分配给该表的图表列表
            [{"name": "...", "reportType": 1, "worksheetId": "...", "worksheetName": "..."}]
    """
    ws_id = ws_info.get("worksheetId", "")
    ws_name = ws_info.get("worksheetName", "")
    fields = ws_info.get("fields", [])
    classified = classify_fields(fields)

    # 完整字段参考
    field_lines = [f"### 工作表「{ws_name}」(ID: {ws_id})"]
    for cat_name, cat_label in [
        ("select", "单选/下拉"), ("number", "数值"), ("date", "日期"),
        ("text", "文本"), ("user", "成员"), ("relation", "关联"),
    ]:
        cat_fields = classified.get(cat_name, [])
        if cat_fields:
            field_lines.append(f"  [{cat_label}]")
            for f in cat_fields:
                s = f"  {f['id']}  {f['name']}(type={f['type']})"
                if f.get("options"):
                    opts = ", ".join(
                        f"{o['key'][:12]}={o['value']}" for o in f["options"][:4]
                    )
                    s += f"  选项: {opts}"
                field_lines.append(s)

    ws_detail = "\n".join(field_lines)

    # 待配置的图表列表
    import json as _json
    charts_list = _json.dumps(assigned_charts, ensure_ascii=False, indent=2)

    return f"""你是一名数据可视化专家，正在为「{app_name}」的图表填写详细配置。

## 待配置的图表（已由 Phase1 分配）
{charts_list}

## 完整字段参考
{ws_detail}

## 任务

为上方每个图表生成完整配置（xaxes, yaxisList, filter 等）。

## 关键规则

1. xaxes.controlId 和 yaxisList[].controlId 必须来自上方字段列表或系统字段（ctime/utime/record_count）
2. 数值图(10)/仪表盘(14)/进度图(15)的 xaxes.controlId 必须设为空字符串
3. 饼图(3) xaxes 应使用单选/下拉字段（type=9/11），不能用布尔(36)或关联(29/30)字段
4. 折线图(2) xaxes 必须使用日期字段（type=15/16），设 particleSizeType=1(月)或4(日)
5. 关联字段(controlType=29/30/34) 绝对不能作为 xaxes 维度
6. 词云图(13) xaxes 必须使用单选/下拉字段（type=9/11）
7. yaxisList 至少 1 项，可用 record_count（记录数量）或数值字段
8. 双轴图(7) 须设 yreportType（右轴图表类型，一般为 2=折线）

## 输出 JSON 格式（严格 JSON，无注释）

{{
  "charts": [
    {{
      "name": "图表名称",
      "desc": "一句话描述分析目的",
      "reportType": 1,
      "worksheetId": "{ws_id}",
      "xaxes": {{
        "controlId": "字段ID 或空字符串(仅数值图/仪表盘/进度图)",
        "controlType": 字段type数字,
        "particleSizeType": 0,
        "sortType": 0,
        "emptyType": 0
      }},
      "yaxisList": [
        {{
          "controlId": "字段ID 或 record_count",
          "controlType": 字段type数字或0,
          "rename": "显示名称"
        }}
      ],
      "filter": {{
        "filterRangeId": "ctime",
        "filterRangeName": "创建时间",
        "rangeType": 0,
        "rangeValue": 0,
        "today": false
      }}
    }}
  ]
}}"""


def validate_chart_config_per_ws(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> list[dict]:
    """Phase 2 逐表校验 — 检查单个工作表的图表详细配置。

    与 validate_enhanced_plan() 逻辑一致，但用于逐表场景。

    Args:
        raw: AI 输出的 JSON，包含 charts 数组（仅当前工作表的图表）
        worksheets_by_id: {worksheetId: {fields: [...]}}

    Returns:
        校验通过的 charts 列表

    Raises:
        ValueError: 校验失败
    """
    constraints = get_chart_constraints()

    if _HAS_SCHEMA:
        valid_types = set(CHART_SCHEMA.keys())
        xaxes_null_types = set(XAXES_NULL_TYPES)
    else:
        valid_types = set(constraints["types"].keys())
        xaxes_null_types = set(constraints.get("xaxes_null_types", [10, 14, 15]))

    charts = raw.get("charts", [])
    if not isinstance(charts, list) or len(charts) == 0:
        raise ValueError("未返回 charts 数组")

    validated = []
    for i, chart in enumerate(charts):
        if not isinstance(chart, dict):
            raise ValueError(f"图表 {i+1} 格式错误")
        name = str(chart.get("name", "")).strip()
        if not name:
            raise ValueError(f"图表 {i+1} 缺少 name")

        report_type = int(chart.get("reportType", 0) or 0)
        if report_type not in valid_types:
            raise ValueError(f"图表 {i+1} reportType={report_type} 不在支持列表 {sorted(valid_types)} 中")

        worksheet_id = str(chart.get("worksheetId", "")).strip()
        if worksheet_id and worksheet_id not in worksheets_by_id:
            print(f"[警告] 图表 {i+1} worksheetId 不存在，跳过: {worksheet_id}")
            continue

        # 字段存在性校验
        if worksheet_id and worksheet_id in worksheets_by_id:
            ws_info = worksheets_by_id[worksheet_id]
            ws_fields = ws_info.get("fields", [])
            valid_fids = {
                str(f.get("id", "") or f.get("controlId", "")).strip()
                for f in ws_fields
                if str(f.get("id", "") or f.get("controlId", "")).strip()
            }
            valid_fids.update(SYSTEM_FIELDS)

            xaxes = chart.get("xaxes", {})
            x_cid = str(xaxes.get("controlId") or "").strip()
            if report_type not in xaxes_null_types and x_cid and x_cid not in valid_fids:
                raise ValueError(f"图表 {i+1}「{name}」xaxes.controlId「{x_cid}」不在工作表字段中")

            yaxis_list = chart.get("yaxisList", [])
            for j, y in enumerate(yaxis_list):
                y_cid = str(y.get("controlId", "")).strip()
                if y_cid and y_cid not in valid_fids:
                    raise ValueError(f"图表 {i+1}「{name}」yaxisList[{j}].controlId「{y_cid}」不在工作表字段中")

        # 类型兼容性校验 + 自动修正
        xaxes = chart.get("xaxes", {})

        XAXES_FORBIDDEN_TYPES = {29, 30, 34}  # 关联类字段，不能做维度
        x_type = int(xaxes.get("controlType", 0) or 0)
        if report_type not in xaxes_null_types and x_type in XAXES_FORBIDDEN_TYPES:
            raise ValueError(
                f"图表 {i+1}「{name}」xaxes.controlType={x_type} 是关联字段，不能作为图表维度。"
                f"请改用单选/文本/日期字段。"
            )

        if report_type in xaxes_null_types:
            if xaxes.get("controlId") not in (None, "", "null"):
                chart["xaxes"]["controlId"] = None  # 自动修正
                print(f"  [自动修正] 图表 {i+1}「{name}」reportType={report_type}，xaxes.controlId 已修正为 null")

        # 双轴图：确保有 yreportType
        if _HAS_SCHEMA and report_type == DUAL_AXIS_TYPE:
            if chart.get("yreportType") is None:
                chart["yreportType"] = 2
                print(f"  [自动补全] 图表 {i+1}「{name}」双轴图自动设置 yreportType=2")

        yaxis_list = chart.get("yaxisList", [])
        if not isinstance(yaxis_list, list) or len(yaxis_list) == 0:
            raise ValueError(f"图表 {i+1} yaxisList 为空")

        validated.append(chart)

    return validated


# ─── 原有一体化接口（向后兼容）───────────────────────────────────────────────────


def validate_enhanced_plan(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> list[dict]:
    """增强版校验：字段存在性 + 类型兼容性。

    使用 chart_config_schema 中定义的约束常量（若可用）：
      XAXES_NULL_TYPES  — 不需要 xaxes 的图表类型
      CHART_SCHEMA.keys() — 全部支持的 reportType

    Args:
        raw: AI 输出的原始 JSON
        worksheets_by_id: {worksheetId: {fields: [...]}}

    Returns:
        校验通过的 charts 列表

    Raises:
        ValueError: 校验失败（触发 AI 重试）
    """
    constraints = get_chart_constraints()

    # 优先使用 schema 常量，兜底用 constraints 字典
    if _HAS_SCHEMA:
        valid_types = set(CHART_SCHEMA.keys())
        xaxes_null_types = set(XAXES_NULL_TYPES)
    else:
        valid_types = set(constraints["types"].keys())
        xaxes_null_types = set(constraints.get("xaxes_null_types", [10, 14, 15]))

    charts = raw.get("charts", [])
    if not isinstance(charts, list) or len(charts) == 0:
        raise ValueError("未返回 charts 数组")
    if len(charts) < 3:
        raise ValueError(f"图表数量不足，只返回 {len(charts)} 个")

    validated = []
    for i, chart in enumerate(charts):
        if not isinstance(chart, dict):
            raise ValueError(f"图表 {i+1} 格式错误")
        name = str(chart.get("name", "")).strip()
        if not name:
            raise ValueError(f"图表 {i+1} 缺少 name")

        report_type = int(chart.get("reportType", 0) or 0)
        if report_type not in valid_types:
            raise ValueError(f"图表 {i+1} reportType={report_type} 不在支持列表 {sorted(valid_types)} 中")

        worksheet_id = str(chart.get("worksheetId", "")).strip()
        if worksheet_id and worksheet_id not in worksheets_by_id:
            print(f"[警告] 图表 {i+1} worksheetId 不存在，跳过: {worksheet_id}")
            continue

        # 字段存在性校验
        if worksheet_id and worksheet_id in worksheets_by_id:
            ws_info = worksheets_by_id[worksheet_id]
            ws_fields = ws_info.get("fields", [])
            valid_fids = {
                str(f.get("id", "") or f.get("controlId", "")).strip()
                for f in ws_fields
                if str(f.get("id", "") or f.get("controlId", "")).strip()
            }
            valid_fids.update(SYSTEM_FIELDS)

            xaxes = chart.get("xaxes", {})
            x_cid = str(xaxes.get("controlId") or "").strip()
            if report_type not in xaxes_null_types and x_cid and x_cid not in valid_fids:
                raise ValueError(f"图表 {i+1}「{name}」xaxes.controlId「{x_cid}」不在工作表字段中")

            yaxis_list = chart.get("yaxisList", [])
            for j, y in enumerate(yaxis_list):
                y_cid = str(y.get("controlId", "")).strip()
                if y_cid and y_cid not in valid_fids:
                    raise ValueError(f"图表 {i+1}「{name}」yaxisList[{j}].controlId「{y_cid}」不在工作表字段中")

        # 类型兼容性校验 + 自动修正
        xaxes = chart.get("xaxes", {})

        # xaxes 字段类型约束
        # 关联字段(29/30/34)不能作为图表维度（xaxes），因为前端无法聚合关联记录
        # 布尔/检查框(36)只有2个值，不适合用作图表维度（饼图/柱状图等）
        XAXES_FORBIDDEN_TYPES = {29, 30, 34}  # 关联类字段，不能做维度
        x_type = int(xaxes.get("controlType", 0) or 0)
        if report_type not in xaxes_null_types and x_type in XAXES_FORBIDDEN_TYPES:
            raise ValueError(
                f"图表 {i+1}「{name}」xaxes.controlType={x_type} 是关联字段，不能作为图表维度。"
                f"请改用单选/文本/日期字段。"
            )

        if report_type in xaxes_null_types:
            # 数值图/进度图 xaxes.controlId 必须为 null
            if xaxes.get("controlId") not in (None, "", "null"):
                chart["xaxes"]["controlId"] = None  # 自动修正
                print(f"  [自动修正] 图表 {i+1}「{name}」reportType={report_type}，xaxes.controlId 已修正为 null")

        # 双轴图：确保有 yreportType
        if _HAS_SCHEMA and report_type == DUAL_AXIS_TYPE:
            if chart.get("yreportType") is None:
                chart["yreportType"] = 2  # 默认右轴为折线图
                print(f"  [自动补全] 图表 {i+1}「{name}」双轴图自动设置 yreportType=2")

        yaxis_list = chart.get("yaxisList", [])
        if not isinstance(yaxis_list, list) or len(yaxis_list) == 0:
            raise ValueError(f"图表 {i+1} yaxisList 为空")

        validated.append(chart)

    return validated
