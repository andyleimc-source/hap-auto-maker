"""
统计图表注册中心。

用法:
    from scripts.hap.charts import CHART_REGISTRY, build_report_body, REPORT_TYPE_NAMES
    from scripts.hap.charts import CHART_SCHEMA, get_ai_prompt_section, list_chart_types

    # 查看所有图表类型
    for rt, spec in CHART_REGISTRY.items():
        print(f"{rt}: {spec['name']} verified={spec.get('verified')}")

    # 构建 saveReportConfig body
    body = build_report_body(chart_dict, app_id)

    # 获取 AI prompt 用的图表说明
    prompt_section = get_ai_prompt_section()
"""

from __future__ import annotations

from . import basic, pie, funnel, radar, dual_axis, scatter, number, table, special
from .chart_config_schema import (
    CHART_SCHEMA,
    CHART_CATEGORIES,
    XAXES_NULL_TYPES,
    SHOW_PERCENT_TYPES,
    DUAL_AXIS_TYPE,
    VERIFIED_TYPES,
    NORM_TYPE_NAMES,
    PARTICLE_SIZE_NAMES,
    CONTROL_TYPE_NAMES,
    AI_PLANNING_GUIDE,
    get_schema,
    get_ai_prompt_section,
    list_chart_types,
)

_MODULES = [
    (basic,     basic.CHARTS,     basic.build),
    (pie,       pie.CHARTS,       pie.build),
    (funnel,    funnel.CHARTS,    funnel.build),
    (radar,     radar.CHARTS,     radar.build),
    (dual_axis, dual_axis.CHARTS, dual_axis.build),
    (scatter,   scatter.CHARTS,   scatter.build),
    (number,    number.CHARTS,    number.build),
    (table,     table.CHARTS,     table.build),
    (special,   special.CHARTS,   special.build),
]

# CHART_REGISTRY: {reportType(int): {name, verified, doc, build_fn, module}}
CHART_REGISTRY: dict[int, dict] = {}

for mod, charts_dict, build_fn in _MODULES:
    for report_type, spec in charts_dict.items():
        CHART_REGISTRY[report_type] = {
            **spec,
            "build_fn": build_fn,
            "module": mod.__name__,
        }

# 兼容旧 REPORT_TYPE_NAMES
REPORT_TYPE_NAMES: dict[int, str] = {rt: spec["name"] for rt, spec in CHART_REGISTRY.items()}


def build_report_body(chart: dict, app_id: str) -> dict:
    """构建 saveReportConfig 请求体。替代原 create_charts_from_plan.build_report_body()。"""
    report_type = int(chart.get("reportType", 1))
    if report_type not in CHART_REGISTRY:
        raise ValueError(f"未知图表类型: reportType={report_type}。支持: {list(CHART_REGISTRY.keys())}")
    entry = CHART_REGISTRY[report_type]
    return entry["build_fn"](report_type, chart, app_id)
