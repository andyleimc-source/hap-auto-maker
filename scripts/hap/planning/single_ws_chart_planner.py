"""
单表图表规划器 — 针对单个工作表，判断是否适合出图并规划 1-3 个图表。

与 chart_planner.py 的区别:
  - 输入单张工作表而非多表
  - AI 同时判断 suitable + 输出图表配置
  - 更轻量的 prompt，适用于逐表并行调用

Schema 来源:
  - scripts/hap/charts/chart_config_schema.py — 17 种图表的完整参数定义
  - scripts/hap/planning/constraints.py — 图表类型约束 + 字段分类
"""

from __future__ import annotations

import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from planning.constraints import (
    build_chart_type_prompt_section,
    SYSTEM_FIELDS,
)

# 导入完整 schema（优先使用）
try:
    from charts.chart_config_schema import get_ai_prompt_section
    _HAS_SCHEMA = True
except ImportError:
    _HAS_SCHEMA = False

# 系统字段 + 空字符串（数值图 xaxes 用）
_VALID_SYSTEM_XAXES = {"ctime", "utime", "record_count", ""}

# 默认时间筛选器
_DEFAULT_FILTER = {
    "filterRangeId": "ctime",
    "filterRangeName": "创建时间",
    "rangeType": 0,
    "rangeValue": 0,
    "today": False,
}


# ─── Prompt 构建 ─────────────────────────────────────────────────────────────


def build_single_ws_chart_prompt(
    ws_name: str,
    fields: list[dict],
    page_name: str = "",
) -> str:
    """为单张工作表生成图表规划 prompt。

    Args:
        ws_name: 工作表名称
        fields: 字段列表，每项包含 controlId, controlName, controlType, options
        page_name: 所属自定义页面名称（可选，用于上下文）

    Returns:
        完整的 AI prompt 字符串
    """
    # 1. 图表类型说明
    if _HAS_SCHEMA:
        chart_type_section = get_ai_prompt_section()
    else:
        chart_type_section = build_chart_type_prompt_section()

    # 2. 字段列表
    field_lines = []
    for f in fields:
        cid = f.get("controlId", "")
        cname = f.get("controlName", "")
        ctype = f.get("controlType", 0)
        line = f"  {cid}  {cname}  (type={ctype})"
        opts = f.get("options")
        if opts and isinstance(opts, list):
            opt_vals = ", ".join(str(o.get("value", o.get("key", ""))) for o in opts[:6])
            line += f"  选项: {opt_vals}"
        field_lines.append(line)

    field_section = "\n".join(field_lines) if field_lines else "  （无用户字段）"

    # 3. 页面上下文
    page_hint = f"（所属页面：{page_name}）" if page_name else ""

    return f"""你是一名数据可视化专家。请判断工作表「{ws_name}」{page_hint}是否适合创建统计图表，如果适合则规划 1-3 个图表。

{chart_type_section}

## 工作表「{ws_name}」的字段
{field_section}

## 任务

1. 先判断这张表是否适合做统计图表（字段太少或全是文本/附件则不适合）
2. 如果适合，规划 1-3 个图表，类型不要重复（reportType 不同）

规划约束：
- 数值图(10)/仪表盘(14)/进度图(15) 的 xaxes.controlId 必须设为空字符串 ""
- 饼图(3) 的 xaxes 应使用单选/下拉字段（type=9/11）
- 折线图(2) 的 xaxes 必须使用日期字段（type=15/16），设 particleSizeType=1(月)或4(日)
- 关联字段(type=29/30/34) 不能作为 xaxes
- 词云图(13) xaxes 必须使用单选/下拉字段（type=9/11）
- xaxes.controlId 和 yaxisList[].controlId 必须来自上方字段列表或系统字段（ctime/utime/record_count）
- yaxisList 至少 1 项，可用 record_count（记录数量）或数值字段
- 图表名称 ≤10 个字，简洁有业务含义

## 输出格式（严格 JSON）

{{
  "suitable": true,
  "reason": "一句话说明为什么适合/不适合",
  "charts": [
    {{
      "name": "图表名称",
      "desc": "一句话描述分析目的",
      "reportType": 1,
      "xaxes": {{
        "controlId": "字段ID 或空字符串(数值图)",
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
}}

如果不适合，返回：
{{
  "suitable": false,
  "reason": "不适合的原因",
  "charts": []
}}"""


# ─── 校验 ─────────────────────────────────────────────────────────────────────


def validate_single_ws_chart_plan(
    raw: dict,
    valid_field_ids: set[str],
) -> list[dict]:
    """校验 AI 返回的单表图表规划，返回合法的图表列表。

    Args:
        raw: AI 返回的 JSON dict，包含 suitable/reason/charts
        valid_field_ids: 该工作表的合法字段 ID 集合

    Returns:
        校验通过的图表配置列表（最多 3 个），不合适则返回空列表
    """
    if not isinstance(raw, dict):
        return []

    # suitable=false 直接返回空
    if not raw.get("suitable", False):
        return []

    charts = raw.get("charts")
    if not isinstance(charts, list):
        return []

    # 合并系统字段到校验集
    all_valid = valid_field_ids | SYSTEM_FIELDS | _VALID_SYSTEM_XAXES

    seen_types: set[int] = set()
    result: list[dict] = []

    for chart in charts:
        if len(result) >= 3:
            break

        if not isinstance(chart, dict):
            continue

        # reportType 必须 > 0 且不重复
        rt = chart.get("reportType", 0)
        if not isinstance(rt, int) or rt <= 0:
            continue
        if rt in seen_types:
            continue

        # xaxes 校验
        xaxes = chart.get("xaxes")
        if not isinstance(xaxes, dict):
            continue

        xaxes_cid = xaxes.get("controlId", "")
        # 数值图/仪表盘/进度图：xaxes 必须为空字符串
        if rt in (10, 14, 15):
            xaxes["controlId"] = ""
            xaxes_cid = ""
        elif xaxes_cid not in all_valid:
            continue  # 无效字段，跳过此图表

        # yaxisList 校验：至少 1 项有效
        y_list = chart.get("yaxisList")
        if not isinstance(y_list, list) or len(y_list) == 0:
            y_list = []

        valid_y = []
        for y in y_list:
            if not isinstance(y, dict):
                continue
            y_cid = y.get("controlId", "")
            if y_cid == "record_count" or y_cid in valid_field_ids or y_cid in SYSTEM_FIELDS:
                valid_y.append(y)

        # fallback: 无有效 y 轴则用 record_count
        if not valid_y:
            valid_y = [{
                "controlId": "record_count",
                "controlType": 0,
                "rename": "记录数量",
            }]

        chart["yaxisList"] = valid_y

        # 默认 filter
        if not chart.get("filter") or not isinstance(chart.get("filter"), dict):
            chart["filter"] = dict(_DEFAULT_FILTER)

        seen_types.add(rt)
        result.append(chart)

    return result
