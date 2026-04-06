#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_chart.py — 为已有应用/页面增量添加统计图表。

流程：
  1. 加载应用上下文（工作表 + 字段）
  2. 可选：筛选指定工作表（--worksheet-id）
  3. AI 规划图表配置（chart_planner）
  4. 调用 saveReportConfig 创建图表
  5. 可选：将图表布局到指定 page（--page-id）

用法（CLI）：
    python3 add_chart.py \\
        --app-id <appId> \\
        --description "展示各部门销售额和月度趋势"

    # 指定工作表和 page
    python3 add_chart.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --page-id <pageId> \\
        --description "按状态分布的饼图"

    # 只生成规划，不实际创建
    python3 add_chart.py \\
        --app-id <appId> \\
        --description "..." \\
        --no-execute

用法（Python）：
    from incremental.add_chart import add_chart
    result = add_chart(
        app_id="xxx",
        description="展示销售额月度趋势",
        page_id="yyy",   # 可选
    )
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_HAP = BASE_DIR / "scripts" / "hap"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
CHART_PLAN_DIR = OUTPUT_ROOT / "chart_plans"
INCREMENTAL_OUTPUT_DIR = OUTPUT_ROOT / "incremental"

for p in [str(SCRIPTS_HAP)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import auth_retry
from incremental.app_context import load_app_context
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json
from planning.chart_planner import build_enhanced_prompt, validate_enhanced_plan
from create_charts_from_plan import (
    build_report_body,
    save_report_config,
    get_page,
    build_page_components,
    save_page,
)

AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"


# ── 字段归一化 ─────────────────────────────────────────────────────────────────

def _normalize_fields(fields: list[dict]) -> list[dict]:
    """归一化字段 id/name/type，兼容 V3 API 和 web API 字段命名。"""
    result = []
    for f in fields:
        nf = dict(f)
        if not nf.get("id"):
            nf["id"] = nf.get("controlId", "")
        if not nf.get("name"):
            nf["name"] = nf.get("controlName", "")
        if "type" not in nf or nf.get("type") is None:
            nf["type"] = nf.get("controlType", 2)
        if "options" not in nf:
            nf["options"] = f.get("options", [])
        result.append(nf)
    return result


def _build_worksheets_info(worksheets: list[dict], filter_ws_id: str = "") -> list[dict]:
    """将 app_context 的工作表列表转为 chart_planner 所需格式。"""
    result = []
    for ws in worksheets:
        ws_id = ws.get("worksheetId", "")
        if filter_ws_id and ws_id != filter_ws_id:
            continue
        ws_name = ws.get("worksheetName", "")
        raw_fields = ws.get("fields", [])
        normalized = _normalize_fields(raw_fields)

        # chart_planner 期望的字段格式
        fields_for_planner = []
        for f in normalized:
            fields_for_planner.append({
                "controlId": f["id"],
                "controlName": f["name"],
                "type": f["type"],
                "options": f.get("options", []),
            })

        result.append({
            "worksheetId": ws_id,
            "worksheetName": ws_name,
            "fields": fields_for_planner,
        })
    return result


# ── AI 规划 ────────────────────────────────────────────────────────────────────

def plan_charts(
    app_name: str,
    worksheets_info: list[dict],
    description: str,
    target_count: int,
    ai_config: dict,
) -> list[dict]:
    """
    调用 chart_planner 规划图表，返回校验后的 charts 列表。

    Args:
        app_name: 应用名称（用于 prompt）
        worksheets_info: [{worksheetId, worksheetName, fields: [...]}]
        description: 用户描述（追加到 prompt）
        target_count: 期望图表数量
        ai_config: AI 配置
    Returns:
        校验后的 charts 列表
    """
    # chart_planner 的 prompt 是基于通用的"多表"格式
    base_prompt = build_enhanced_prompt(
        app_name=app_name,
        worksheets_info=worksheets_info,
        target_count=target_count,
    )

    # 如果有用户描述，追加到 prompt 末尾
    if description:
        full_prompt = base_prompt + f"\n\n## 附加需求\n{description}"
    else:
        full_prompt = base_prompt

    client = get_ai_client(ai_config)
    gen_cfg = create_generation_config(ai_config, response_mime_type="application/json")
    resp = client.models.generate_content(
        model=ai_config["model"],
        contents=full_prompt,
        config=gen_cfg,
    )
    raw_text = resp.text if hasattr(resp, "text") else str(resp)
    raw = parse_ai_json(raw_text)

    # 构建 worksheets_by_id 供校验用
    worksheets_by_id = {ws["worksheetId"]: ws for ws in worksheets_info}

    validated = validate_enhanced_plan(raw, worksheets_by_id, min_count=1)
    return validated


# ── 图表创建 ───────────────────────────────────────────────────────────────────

def create_charts(
    charts: list[dict],
    app_id: str,
    auth_config_path: Path,
    page_id: str = "",
) -> list[dict]:
    """
    逐个调用 saveReportConfig 创建图表。

    Args:
        charts: 校验后的图表规划列表
        app_id: 应用 ID
        auth_config_path: auth_config.py 路径
        page_id: 若非空，创建完后调用 savePage 布局到指定页面
    Returns:
        results 列表，每项包含 {chartName, status, reportId, ...}
    """
    chart_referer = ""
    if page_id:
        chart_referer = f"https://www.mingdao.com/app/{app_id}/{page_id}"

    results = []
    for i, chart in enumerate(charts):
        chart_name = str(chart.get("name", f"图表{i+1}"))
        report_type = int(chart.get("reportType", 1))
        try:
            body = build_report_body(chart, app_id)
            resp_data = save_report_config(body, auth_config_path, referer=chart_referer)

            report_id = ""
            if isinstance(resp_data, dict):
                data_field = resp_data.get("data", {})
                if isinstance(data_field, dict):
                    report_id = str(data_field.get("reportId", "") or data_field.get("id", "")).strip()
                else:
                    report_id = str(data_field or "").strip()

            is_success = (
                resp_data.get("success") is True
                or resp_data.get("status") == 1
                or resp_data.get("code") == 1
                or bool(report_id)
            )
            status = "success" if is_success else "failed"
            print(f"  [{i+1}/{len(charts)}] {chart_name}（reportType={report_type}）→ {status}  reportId={report_id}")
            results.append({
                "chartName": chart_name,
                "reportType": report_type,
                "worksheetId": str(chart.get("worksheetId", "")),
                "status": status,
                "reportId": report_id,
            })
        except Exception as exc:
            print(f"  [{i+1}/{len(charts)}] {chart_name} → 失败: {exc}")
            results.append({
                "chartName": chart_name,
                "status": "error",
                "error": str(exc),
            })

    # 布局到 page
    if page_id:
        success_count = sum(1 for r in results if r.get("status") == "success")
        if success_count > 0:
            print(f"\n[savePage] 将 {success_count} 个图表布局到 page: {page_id}")
            try:
                current_page = get_page(page_id, auth_config_path)
                current_version = int(current_page.get("version", 1))
                existing_components = current_page.get("components", []) or []
                print(f"  当前 page version={current_version}，已有 {len(existing_components)} 个组件")

                all_components = build_page_components(results, app_id, existing_components)
                page_resp = save_page(page_id, all_components, current_version, auth_config_path, referer=chart_referer)

                page_ok = (
                    page_resp.get("success") is True
                    or page_resp.get("status") == 1
                    or page_resp.get("code") == 1
                )
                if page_ok:
                    new_version = page_resp.get("data", {}).get("version", current_version + 1)
                    print(f"  → savePage 成功，version {current_version} → {new_version}，共 {len(all_components)} 个组件")
                else:
                    print(f"  → savePage 返回异常: {page_resp}")
            except Exception as exc:
                print(f"  → savePage 失败: {exc}")

    return results


# ── 公共接口 ───────────────────────────────────────────────────────────────────

def add_chart(
    app_id: str,
    description: str = "",
    worksheet_id: str = "",
    page_id: str = "",
    target_count: int = 6,
    app_auth_json: str = "",
    ai_config: Optional[dict] = None,
    auth_config_path: Optional[Path] = None,
    execute: bool = True,
) -> dict:
    """
    为已有应用增量添加图表。

    Args:
        app_id: 应用 ID
        description: 业务描述，指导 AI 规划图表内容
        worksheet_id: 可选，只针对某张工作表规划图表
        page_id: 可选，创建后布局到指定统计页面
        target_count: 期望图表数量（默认 6）
        app_auth_json: 授权 JSON 文件路径
        ai_config: AI 配置（默认 fast tier）
        auth_config_path: auth_config.py 路径
        execute: 是否真实创建（False 时只生成规划）
    Returns:
        {"plan": [...], "results": [...], "plan_file": "..."}
    """
    if ai_config is None:
        ai_config = load_ai_config()
    if auth_config_path is None:
        auth_config_path = AUTH_CONFIG_PATH

    print(f"\n[add_chart] 加载应用上下文 app_id={app_id}...")
    ctx = load_app_context(app_id=app_id, app_auth_json=app_auth_json, with_field_details=True)

    resolved_app_id = ctx["app_id"] or app_id

    # 构建 worksheets_info
    worksheets_info = _build_worksheets_info(ctx["worksheets"], filter_ws_id=worksheet_id)
    if not worksheets_info:
        if worksheet_id:
            available = [f"{ws['worksheetName']}({ws['worksheetId']})" for ws in ctx["worksheets"]]
            raise ValueError(f"找不到工作表 {worksheet_id}，可用: {', '.join(available)}")
        raise ValueError("应用中没有工作表")

    print(f"  目标工作表数: {len(worksheets_info)}")
    for ws in worksheets_info:
        print(f"    - {ws['worksheetName']} ({ws['worksheetId']})  {len(ws['fields'])} 字段")

    # 应用名称：取第一张工作表所在应用，或直接用 app_id
    app_name = ctx.get("app_name", "") or resolved_app_id

    # AI 规划
    print(f"\n  [AI 规划] 为应用规划 {target_count} 个图表...")
    charts = plan_charts(
        app_name=app_name,
        worksheets_info=worksheets_info,
        description=description,
        target_count=target_count,
        ai_config=ai_config,
    )
    print(f"  AI 规划完成，共 {len(charts)} 个图表")
    for i, c in enumerate(charts):
        print(f"    [{i+1}] {c.get('name')} (reportType={c.get('reportType')})")

    # 保存规划
    INCREMENTAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    plan_file = INCREMENTAL_OUTPUT_DIR / f"chart_plan_{resolved_app_id}_{ts}.json"
    plan_data = {
        "appId": resolved_app_id,
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": description,
        "charts": charts,
    }
    plan_file.write_text(json.dumps(plan_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  规划已保存: {plan_file}")

    # 创建图表
    results = []
    if execute:
        print(f"\n  [创建] 开始创建 {len(charts)} 个图表...")
        results = create_charts(
            charts=charts,
            app_id=resolved_app_id,
            auth_config_path=auth_config_path,
            page_id=page_id,
        )
        success = sum(1 for r in results if r.get("status") == "success")
        print(f"\n  完成：{success}/{len(charts)} 个图表创建成功")
    else:
        print("  [no-execute] 跳过创建步骤")

    return {
        "plan": charts,
        "results": results,
        "plan_file": str(plan_file),
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="增量为已有应用添加统计图表")
    parser.add_argument("--app-id", default="", help="应用 ID")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON 文件路径")
    parser.add_argument("--worksheet-id", default="", help="只针对该工作表规划（可选）")
    parser.add_argument("--page-id", default="", help="创建后布局到该统计页面（可选）")
    parser.add_argument("--description", default="", help="业务描述，指导 AI 规划图表内容")
    parser.add_argument("--count", type=int, default=6, help="期望图表数量（默认 6）")
    parser.add_argument("--no-execute", action="store_true", help="只生成规划，不实际创建")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    args = parser.parse_args()

    if not args.app_id and not args.app_auth_json:
        parser.error("请传 --app-id 或 --app-auth-json")

    result = add_chart(
        app_id=args.app_id,
        description=args.description,
        worksheet_id=args.worksheet_id,
        page_id=args.page_id,
        target_count=args.count,
        app_auth_json=args.app_auth_json,
        auth_config_path=Path(args.auth_config),
        execute=not args.no_execute,
    )

    print("\n[add_chart] 完成")
    print(f"规划文件: {result['plan_file']}")
    if result["results"]:
        success = sum(1 for r in result["results"] if r.get("status") == "success")
        print(f"创建结果: {success}/{len(result['results'])} 个成功")
        print(json.dumps(result["results"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
