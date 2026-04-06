#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Per-Page 图表规划+创建。

对 page_registry 中每个 Page，聚合该 Page 所有工作表字段，
调用 AI 规划 8-12 个图表，逐一创建并追加到 Page。
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_utils import get_ai_client, create_generation_config, parse_ai_json
from planning.chart_planner import build_enhanced_prompt
from planners.plan_charts_gemini import validate_plan
from executors.create_single_ws_charts import _create_single_chart, _append_charts_to_page


def build_page_worksheets_info(
    page_entry: dict,
    ws_fields_map: Dict[str, dict],
) -> List[dict]:
    """筛选出属于该 Page 的工作表信息列表。

    Args:
        page_entry: page_registry 中单个 page 条目，含 worksheetNames 列表
        ws_fields_map: ws_name -> {worksheetId, worksheetName, fields, views} 的映射

    Returns:
        该 Page 包含的工作表信息列表（仅保留在 ws_fields_map 中存在的）
    """
    ws_names = page_entry.get("worksheetNames") or []
    result = []
    for name in ws_names:
        info = ws_fields_map.get(name)
        if info and isinstance(info, dict):
            result.append(info)
    return result


def plan_and_create_page_charts(
    page_entry: dict,
    ws_fields_map: Dict[str, dict],
    app_id: str,
    app_name: str,
    auth_config_path: Path,
    ai_config: dict,
    gemini_semaphore: Optional[Any] = None,
    worksheets_by_id: Optional[Dict[str, dict]] = None,
) -> dict:
    """为单个 Page 规划并创建 8-12 个图表。

    Args:
        page_entry: page_registry 中的 page 条目（含 pageId, worksheetNames, components, name）
        ws_fields_map: ws_name -> {worksheetId, worksheetName, fields, views}
        app_id: 应用 ID
        app_name: 应用名称
        auth_config_path: 认证配置路径
        ai_config: AI 配置 dict
        gemini_semaphore: 可选并发控制信号量
        worksheets_by_id: ws_id -> ws_info 映射（用于 validate_plan 校验），None 时自动构建

    Returns:
        {"page": str, "worksheets_count": int, "charts_created": int, "error": str or None}
    """
    page_name = page_entry.get("name", "")
    page_id = page_entry.get("pageId", "")

    result: Dict[str, Any] = {
        "page": page_name,
        "worksheets_count": 0,
        "charts_created": 0,
        "error": None,
    }

    # 1. 聚合该 Page 的工作表信息
    ws_infos = build_page_worksheets_info(page_entry, ws_fields_map)
    result["worksheets_count"] = len(ws_infos)

    if not ws_infos:
        result["error"] = "该 Page 无可用工作表字段"
        print(f"  [chart-page] {page_name}: 无可用工作表，跳过")
        return result

    # 2. 构建 worksheets_by_id（validate_plan 需要）
    if worksheets_by_id is None:
        worksheets_by_id = {info["worksheetId"]: info for info in ws_infos}

    # 3. 计算目标图表数量
    n = len(ws_infos)
    if n <= 1:
        target_count = 4
    elif n <= 3:
        target_count = 6
    elif n <= 6:
        target_count = 8
    else:
        target_count = 10

    # 4. 构建 prompt
    prompt = build_enhanced_prompt(app_name, ws_infos, target_count=target_count)

    # 5. AI 调用（带重试）
    client = get_ai_client(ai_config)
    model = ai_config.get("model", "gemini-2.5-flash")
    gen_config = create_generation_config(
        ai_config,
        response_mime_type="application/json",
        temperature=0.3,
    )

    raw_text = ""
    ai_exc: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            if gemini_semaphore:
                gemini_semaphore.acquire()
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=gen_config,
                )
                raw_text = response.text or ""
            finally:
                if gemini_semaphore:
                    gemini_semaphore.release()
            break
        except Exception as exc:
            ai_exc = exc
            if attempt < 3:
                time.sleep(2 * attempt)

    if not raw_text:
        result["error"] = f"AI 调用失败: {ai_exc}"
        print(f"  [chart-page] {page_name}: AI 调用失败: {ai_exc}")
        return result

    # 6. 解析 + 校验
    try:
        raw_plan = parse_ai_json(raw_text)
    except Exception as exc:
        result["error"] = f"JSON 解析失败: {exc}"
        print(f"  [chart-page] {page_name}: JSON 解析失败: {exc}")
        return result

    try:
        validated_charts = validate_plan(raw_plan, worksheets_by_id)
    except Exception as exc:
        result["error"] = f"图表校验失败: {exc}"
        print(f"  [chart-page] {page_name}: 图表校验失败: {exc}")
        return result

    if not validated_charts:
        result["error"] = "校验后无有效图表"
        return result

    # 7. 逐个创建图表
    print(f"  📊 Page「{page_name}」({len(ws_infos)} 张表): 创建 {len(validated_charts)} 个图表...")
    created_charts = []
    for chart in validated_charts:
        ws_id = str(chart.get("worksheetId", "")).strip()
        detail = _create_single_chart(chart, ws_id, app_id, auth_config_path)
        if detail["status"] == "success" and detail.get("reportId"):
            created_charts.append(detail)

    # 8. 追加到 Page
    if created_charts and page_id:
        ok = _append_charts_to_page(page_id, page_entry, created_charts, app_id, auth_config_path)
        if ok:
            print(f"  ✅ Page「{page_name}」: {len(created_charts)} 个图表已追加")
        else:
            print(f"  ⚠️  Page「{page_name}」: 图表已创建但追加失败")

    result["charts_created"] = len(created_charts)
    return result
