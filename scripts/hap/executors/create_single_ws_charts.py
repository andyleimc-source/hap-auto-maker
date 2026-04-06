#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单表图表创建+追加到 Page。

由 create_worksheets_from_plan.py 回调调用（library，非 CLI）。
针对单张工作表：AI 规划 → 校验 → saveReportConfig → 追加到 Page。
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import secrets
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import auth_retry
from ai_utils import get_ai_client, create_generation_config, parse_ai_json
from charts import build_report_body, REPORT_TYPE_NAMES
from planning.single_ws_chart_planner import (
    build_single_ws_chart_prompt,
    validate_single_ws_chart_plan,
)

# ---------------------------------------------------------------------------
# API 端点
# ---------------------------------------------------------------------------

SAVE_REPORT_URL = "https://api.mingdao.com/report/reportConfig/saveReportConfig"
SAVE_PAGE_URL = "https://api.mingdao.com/report/custom/savePage"

# Page 写入锁（多线程同时追加图表到同一 Page 时需要）
_page_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 内部：追加图表到 Page
# ---------------------------------------------------------------------------

def _append_charts_to_page(
    page_id: str,
    page_entry: dict,
    charts: List[dict],
    app_id: str,
    auth_config_path: Path,
) -> bool:
    """将成功创建的图表追加到 Page，线程安全。

    Args:
        page_id: 自定义页面 ID
        page_entry: 包含 components/version 的 page 字典（会被 in-place 更新）
        charts: 成功创建的图表列表，每项包含 reportId/chartName/reportType
        app_id: 应用 ID
        auth_config_path: 认证配置路径

    Returns:
        True 表示保存成功
    """
    if not charts:
        return True

    with _page_lock:
        existing_components = list(page_entry.get("components") or [])
        version = int(page_entry.get("version", 1))

        # 计算现有 components 占用的最大 y
        W, H = 24, 12
        max_y = 0
        for comp in existing_components:
            layout = comp.get("web", {}).get("layout") or {}
            bottom = int(layout.get("y", 0)) + int(layout.get("h", 0))
            if bottom > max_y:
                max_y = bottom

        # 两列布局追加新图表
        new_components = []
        for idx, r in enumerate(charts):
            x = (idx % 2) * W
            y = max_y + (idx // 2) * H
            report_id = r["reportId"]
            new_components.append({
                "id": secrets.token_hex(12),
                "type": 1,
                "value": report_id,
                "valueExtend": report_id,
                "config": {"objectId": str(uuid.uuid4())},
                "web": {
                    "titleVisible": False,
                    "title": "",
                    "visible": True,
                    "layout": {"x": x, "y": y, "w": W, "h": H, "minW": 2, "minH": 4},
                },
                "mobile": {"titleVisible": False, "title": "", "visible": True, "layout": None},
                "name": r.get("chartName", ""),
                "reportDesc": "",
                "reportType": r.get("reportType", 1),
                "showChartType": 1,
                "title": "",
                "titleVisible": False,
                "needUpdate": True,
                "worksheetId": app_id,
            })

        all_components = existing_components + new_components

        # savePage
        body = {
            "appId": page_id,
            "version": version,
            "components": all_components,
            "adjustScreen": False,
            "urlParams": [],
            "config": {
                "pageStyleType": "light",
                "pageBgColor": "#f5f6f7",
                "chartColor": "",
                "chartColorIndex": 1,
                "numberChartColor": "",
                "numberChartColorIndex": 1,
                "pivoTableColor": "",
                "refresh": 0,
                "headerVisible": True,
                "shareVisible": True,
                "chartShare": True,
                "chartExportExcel": True,
                "downloadVisible": True,
                "fullScreenVisible": True,
                "customColors": [],
                "webNewCols": 48,
                "orightWebCols": 48,
            },
        }
        resp = auth_retry.hap_web_post(SAVE_PAGE_URL, auth_config_path, json=body, timeout=30)
        resp.raise_for_status()
        result = resp.json()

        success = (
            result.get("status") == 1
            or result.get("success") is True
            or result.get("code") == 1
        )
        if success:
            # in-place 更新 page_entry
            page_entry["components"] = all_components
            page_entry["version"] = version + 1
            return True

        print(f"  ⚠️  savePage 失败: {result}")
        return False


# ---------------------------------------------------------------------------
# 内部：创建单个图表
# ---------------------------------------------------------------------------

def _create_single_chart(
    chart: dict,
    worksheet_id: str,
    app_id: str,
    auth_config_path: Path,
) -> dict:
    """调用 saveReportConfig 创建一个图表，返回结果 dict。"""
    chart_name = str(chart.get("name", "图表"))
    report_type = int(chart.get("reportType", 1))
    type_name = REPORT_TYPE_NAMES.get(report_type, str(report_type))

    # 确保 worksheetId 已设置
    chart["worksheetId"] = worksheet_id

    try:
        body = build_report_body(chart, app_id)
        resp = auth_retry.hap_web_post(SAVE_REPORT_URL, auth_config_path, json=body, timeout=30)
        resp.raise_for_status()
        resp_data = resp.json()

        # 提取 reportId
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
        print(f"    图表「{chart_name}」（{type_name}）-> {status}，reportId={report_id}")
        return {
            "chartName": chart_name,
            "reportType": report_type,
            "reportId": report_id,
            "status": status,
        }
    except Exception as exc:
        print(f"    图表「{chart_name}」（{type_name}）-> 失败: {exc}")
        return {
            "chartName": chart_name,
            "reportType": report_type,
            "reportId": "",
            "status": "error",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def plan_and_create_charts(
    worksheet_id: str,
    worksheet_name: str,
    fields: list[dict],
    page_entry: dict,
    app_id: str,
    auth_config_path: Path,
    ai_config: dict,
    gemini_semaphore: Optional[Any] = None,
) -> dict:
    """为单张工作表规划并创建图表，然后追加到 Page。

    Args:
        worksheet_id: 工作表 ID
        worksheet_name: 工作表名称
        fields: 字段列表
        page_entry: Page 信息 dict（含 pageId, components, version），会被 in-place 更新
        app_id: 应用 ID
        auth_config_path: HAP 认证配置路径
        ai_config: AI 配置 dict（含 provider, api_key, model 等）
        gemini_semaphore: 可选的并发控制信号量

    Returns:
        {
            "worksheet": str,
            "suitable": bool,
            "reason": str,
            "charts_created": int,
            "details": list,
        }
    """
    result: Dict[str, Any] = {
        "worksheet": worksheet_name,
        "suitable": False,
        "reason": "",
        "charts_created": 0,
        "details": [],
    }

    # 1. 构建 prompt
    page_name = page_entry.get("pageName", "") or page_entry.get("name", "")
    prompt = build_single_ws_chart_prompt(worksheet_name, fields, page_name=page_name)

    # 2. AI 调用
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
                import time
                time.sleep(2 * attempt)
                continue
            break

    if not raw_text:
        result["reason"] = f"AI 调用失败: {ai_exc}"
        print(f"  ⚠️  {worksheet_name} 图表规划 AI 调用失败: {ai_exc}")
        return result

    # 3. 解析 + 校验
    try:
        raw_plan = parse_ai_json(raw_text)
    except Exception as exc:
        result["reason"] = f"AI 返回 JSON 解析失败: {exc}"
        print(f"  ⚠️  {worksheet_name} 图表规划 JSON 解析失败: {exc}")
        return result

    result["suitable"] = bool(raw_plan.get("suitable", False))
    result["reason"] = str(raw_plan.get("reason", ""))

    if not result["suitable"]:
        print(f"  ℹ️  {worksheet_name} 不适合创建图表: {result['reason']}")
        return result

    valid_field_ids = {f.get("controlId", "") for f in fields if f.get("controlId")}
    valid_charts = validate_single_ws_chart_plan(raw_plan, valid_field_ids)

    if not valid_charts:
        result["suitable"] = False
        result["reason"] = "校验后无有效图表"
        print(f"  ⚠️  {worksheet_name} 校验后无有效图表")
        return result

    # 4. 逐个创建图表
    print(f"  📊 {worksheet_name}: 创建 {len(valid_charts)} 个图表...")
    created_charts = []
    for chart in valid_charts:
        detail = _create_single_chart(chart, worksheet_id, app_id, auth_config_path)
        result["details"].append(detail)
        if detail["status"] == "success" and detail.get("reportId"):
            created_charts.append(detail)

    result["charts_created"] = len(created_charts)

    # 5. 追加到 Page
    if created_charts:
        page_id = page_entry.get("pageId", "") or page_entry.get("id", "")
        if page_id:
            ok = _append_charts_to_page(page_id, page_entry, created_charts, app_id, auth_config_path)
            if ok:
                print(f"  ✅ {worksheet_name}: {len(created_charts)} 个图表已追加到页面")
            else:
                print(f"  ⚠️  {worksheet_name}: 图表已创建但追加到页面失败")
        else:
            print(f"  ⚠️  {worksheet_name}: 无 pageId，跳过追加到页面")

    return result
