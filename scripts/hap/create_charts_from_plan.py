#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据 chart_plan JSON 调用 saveReportConfig 接口创建统计图。
"""

from __future__ import annotations

import argparse
import json
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, List

import auth_retry

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
CHART_PLAN_DIR = OUTPUT_ROOT / "chart_plans"
CHART_CREATE_DIR = OUTPUT_ROOT / "chart_create_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

SAVE_REPORT_URL = "https://api.mingdao.com/report/reportConfig/saveReportConfig"
SAVE_PAGE_URL = "https://api.mingdao.com/report/custom/savePage"

from charts import CHART_REGISTRY, REPORT_TYPE_NAMES, build_report_body as _charts_build_report_body


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_plan_path(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (CHART_PLAN_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到规划文件: {value}")
    latest = CHART_PLAN_DIR / "chart_plan_latest.json"
    if latest.exists():
        return latest.resolve()
    files = sorted(CHART_PLAN_DIR.glob("chart_plan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if files:
        return files[0].resolve()
    raise FileNotFoundError(f"未找到规划文件，请传 --plan-json（目录: {CHART_PLAN_DIR}）")


# ---------------------------------------------------------------------------
# 构建 saveReportConfig 请求体
# ---------------------------------------------------------------------------

def build_default_display_setup(report_type: int, xaxes: dict) -> dict:
    """生成通用的 displaySetup 配置，根据图表类型自动调整。"""
    x_control_name = str(xaxes.get("controlName", "")).strip()
    setup = {
        "isPerPile": False,
        "isPile": False,
        "isAccumulate": False,
        "accumulatePerPile": None,
        "isToday": False,
        "isLifecycle": False,
        "lifecycleValue": 0,
        "contrastType": 0,
        "fontStyle": 1,
        "showTotal": False,
        "showTitle": True,
        "showLegend": True,
        "legendType": 1,
        "showDimension": True,
        "showNumber": True,
        "showPercent": report_type in {3, 4, 5},  # 饼图/环形图/漏斗图显示百分比
        "showXAxisCount": 0,
        "showChartType": 1,
        "showPileTotal": True,
        "hideOverlapText": False,
        "showRowList": True,
        "showControlIds": [],
        "auxiliaryLines": [],
        "showOptionIds": [],
        "contrast": False,
        "colorRules": [],
        "percent": {
            "enable": False,
            "type": 2,
            "dot": "2",
            "dotFormat": "1",
            "roundType": 2,
        },
        "mergeCell": True,
        "previewUrl": None,
        "imageUrl": None,
        "xdisplay": {
            "showDial": True,
            "showTitle": False,
            "title": x_control_name,
            "minValue": None,
            "maxValue": None,
        },
        "xaxisEmpty": False,
        "ydisplay": {
            "showDial": True,
            "showTitle": False,
            "title": "记录数量",
            "minValue": None,
            "maxValue": None,
            "lineStyle": 1,
            "showNumber": None,
        },
    }
    # 数值图（数字卡片）：不显示图例和维度
    if report_type == 10:
        setup["showLegend"] = False
        setup["showDimension"] = False
    # 透视表：启用合并单元格
    if report_type == 13:
        setup["mergeCell"] = True
        setup["showRowList"] = True
    return setup


def build_xaxes_payload(xaxes: dict) -> dict:
    control_id = str(xaxes.get("controlId", "")).strip()
    control_type = int(xaxes.get("controlType", 16) or 16)
    control_name = str(xaxes.get("controlName", "")).strip()
    particle_size = int(xaxes.get("particleSizeType", 0) or 0)
    cid = f"{control_id}-1"
    return {
        "controlId": control_id,
        "sortType": int(xaxes.get("sortType", 0) or 0),
        "particleSizeType": particle_size,
        "rename": str(xaxes.get("rename", "") or ""),
        "emptyType": int(xaxes.get("emptyType", 0) or 0),
        "fields": None,
        "subTotal": False,
        "subTotalName": None,
        "showFormat": "0",
        "displayMode": "text",
        "controlName": control_name,
        "controlType": control_type,
        "dataSource": None,
        "options": [],
        "advancedSetting": None,
        "relationControl": None,
        "cid": cid,
        "cname": control_name,
        "xaxisEmptyType": int(xaxes.get("xaxisEmptyType", 0) or 0),
        "xaxisEmpty": bool(xaxes.get("xaxisEmpty", False)),
        "c_Id": cid,
    }


def build_yaxis_payload(y: dict) -> dict:
    control_id = str(y.get("controlId", "record_count")).strip()
    control_name = str(y.get("controlName", "记录数量")).strip()
    control_type = int(y.get("controlType", 10000000) or 10000000)
    return {
        "controlId": control_id,
        "controlName": control_name,
        "controlType": control_type,
        "magnitude": 0,
        "roundType": 2,
        "dotFormat": "1",
        "suffix": "",
        "ydot": 2,
        "fixType": 0,
        "showNumber": True,
        "hide": False,
        "percent": {
            "enable": False,
            "type": 2,
            "dot": "2",
            "dotFormat": "1",
            "roundType": 2,
        },
        "normType": 5,
        "emptyShowType": 0,
        "dot": 0,
        "rename": str(y.get("rename", "") or ""),
        "advancedSetting": {},
    }


def build_report_body(chart: dict, app_id: str) -> dict:
    """将 Gemini 规划的图表转换为 saveReportConfig 请求体。代理到 charts/ 模块。"""
    return _charts_build_report_body(chart, app_id)


def _build_report_body_legacy(chart: dict, app_id: str) -> dict:
    """旧实现，保留备用。"""
    report_type = int(chart.get("reportType", 1))
    name = str(chart.get("name", "")).strip()
    desc = str(chart.get("desc", "") or "").strip()
    views = chart.get("views", [])
    xaxes_raw = chart.get("xaxes", {})
    yaxis_list_raw = chart.get("yaxisList", [])
    # 注意：chart.get("filter", default) 在 Gemini 输出 "filter":null 时返回 None，
    # 必须用 `or` 兜底，确保 filter 永不为 null（API 收到 null 会返回服务异常）
    _DEFAULT_FILTER = {
        "filterRangeId": "ctime",
        "filterRangeName": "创建时间",
        "rangeType": 0,    # 0 = 不限时间，避免空范围导致图表无数据
        "rangeValue": 0,
        "today": False,
    }
    filter_cfg = chart.get("filter") or _DEFAULT_FILTER
    # 二次兜底：确保必要字段完整
    if not isinstance(filter_cfg, dict):
        filter_cfg = _DEFAULT_FILTER
    filter_cfg.setdefault("filterRangeId", "ctime")
    filter_cfg.setdefault("filterRangeName", "创建时间")
    filter_cfg.setdefault("rangeType", 0)
    filter_cfg.setdefault("rangeValue", 0)
    filter_cfg.setdefault("today", False)

    xaxes_payload = build_xaxes_payload(xaxes_raw)
    yaxis_payload = [build_yaxis_payload(y) for y in yaxis_list_raw]
    display_setup = build_default_display_setup(report_type, xaxes_raw)

    # 数值图（reportType=10）不需要 xaxes 维度字段
    if report_type == 10:
        xaxes_payload["controlId"] = None
        xaxes_payload["cid"] = "null-1"
        xaxes_payload["c_Id"] = "null-1"
        xaxes_payload["controlName"] = ""
        xaxes_payload["cname"] = ""

    # 双轴图（reportType=7）需要设置第二轴类型和 rightY
    yreport_type = chart.get("yreportType")
    if report_type == 7 and yreport_type is None:
        yreport_type = 2  # 默认第二轴为折线图

    right_y_raw = chart.get("rightY")

    body = {
        "splitId": "",
        "split": {},
        "displaySetup": display_setup,
        "name": name,
        "desc": desc,
        "reportType": report_type,
        "filter": filter_cfg,
        "createdDate": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "account": {"accountId": "", "fullName": None, "avatar": None, "status": None},
        "appId": str(chart.get("worksheetId", "") or app_id).strip() or app_id,
        "appType": 1,
        "sorts": [],
        "summary": {
            "controlId": "",
            "type": 1,
            "name": "总计",
            "number": True,
            "percent": False,
            "sum": 0,
            "contrastSum": 0,
            "contrastMapSum": 0,
            "rename": "",
            "all": False,
        },
        "style": {},
        "formulas": [],
        "views": views,
        "auth": 1,
        "yreportType": yreport_type,
        "yaxisList": yaxis_payload,
        "xaxes": xaxes_payload,
        "sourceType": 1,
        "isPublic": True,
        "id": "",
        "version": "6.5",
    }

    # 双轴图：把 rightY 的 yaxisList 序列化后写入 body
    if report_type == 7 and isinstance(right_y_raw, dict):
        right_y_list = right_y_raw.get("yaxisList", [])
        body["rightY"] = {
            "reportType": int(right_y_raw.get("reportType", 2)),
            "yaxisList": [build_yaxis_payload(y) for y in right_y_list],
        }

    return body


# ---------------------------------------------------------------------------
# API 调用
# ---------------------------------------------------------------------------

def save_report_config(body: dict, auth_config_path: Path, referer: str = "") -> dict:
    resp = auth_retry.hap_web_post(SAVE_REPORT_URL, auth_config_path, referer=referer, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


GET_PAGE_URL = "https://api.mingdao.com/report/custom/getPage"


def get_page(page_id: str, auth_config_path: Path) -> dict:
    """GET 当前 page 的版本号和现有 components。"""
    resp = auth_retry.hap_web_get(f"{GET_PAGE_URL}?appId={page_id}", auth_config_path, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != 1:
        raise RuntimeError(f"getPage 失败: {data}")
    return data.get("data", {})


def build_page_components(results: List[dict], app_id: str, existing_components: List[dict]) -> List[dict]:
    """将成功创建的图表追加到已有 components 后面（两列布局，y 从现有内容下方开始）。"""
    W, H = 24, 12
    success = [r for r in results if r.get("status") == "success" and r.get("reportId")]

    # 计算现有 components 占用的最大 y，新组件从其下方排列
    max_y = 0
    for comp in existing_components:
        layout = comp.get("web", {}).get("layout") or {}
        bottom = int(layout.get("y", 0)) + int(layout.get("h", 0))
        if bottom > max_y:
            max_y = bottom

    new_components = []
    for idx, r in enumerate(success):
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
    return existing_components + new_components


def save_page(page_id: str, components: List[dict], version: int, auth_config_path: Path, referer: str = "") -> dict:
    body = {
        "appId": page_id,
        "version": version,
        "components": components,
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
    resp = auth_retry.hap_web_post(SAVE_PAGE_URL, auth_config_path, referer=referer, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="根据 chart_plan 创建统计图")
    parser.add_argument("--plan-json", default="", help="chart_plan JSON 文件路径（默认取最新）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--output", default="", help="结果 JSON 输出路径")
    parser.add_argument("--page-id", default="", help="统计图 Page ID（URL 最后一段），用于 savePage 布局")
    parser.add_argument("--dry-run", action="store_true", help="仅打印请求体，不实际调用")
    parser.add_argument("--max-workers", type=int, default=16, help="并发创建图表数（默认 16）")
    args = parser.parse_args()

    plan_path = resolve_plan_path(args.plan_json)
    plan = load_json(plan_path)
    charts: List[dict] = plan.get("charts", [])
    app_id: str = str(plan.get("appId", "")).strip()
    app_name: str = str(plan.get("appName", "")).strip()

    if not charts:
        raise ValueError("规划文件中没有 charts")
    if not app_id:
        raise ValueError("规划文件缺少 appId")

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    page_id = args.page_id.strip()
    chart_referer = ""
    if page_id:
        chart_referer = f"https://www.mingdao.com/app/{app_id}/{page_id}"

    print(f"应用: {app_name} ({app_id})")
    print(f"规划文件: {plan_path}")
    print(f"准备创建 {len(charts)} 个统计图\n")

    indexed_results: dict = {}

    def _create_chart(idx_chart):
        i, chart = idx_chart
        chart_name = str(chart.get("name", f"图表{i + 1}"))
        report_type = int(chart.get("reportType", 1))
        type_name = REPORT_TYPE_NAMES.get(report_type, str(report_type))
        body = build_report_body(chart, app_id)

        if args.dry_run:
            return i, {"chartName": chart_name, "status": "dry-run", "body": body}

        try:
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
            print(f"  [{i + 1}/{len(charts)}] {chart_name}（{type_name}）-> {status}，reportId={report_id}")
            return i, {
                "chartName": chart_name,
                "reportType": report_type,
                "worksheetId": str(chart.get("worksheetId", "")),
                "status": status,
                "reportId": report_id,
                "response": resp_data,
            }
        except Exception as exc:
            print(f"  [{i + 1}/{len(charts)}] {chart_name} -> 失败: {exc}")
            return i, {"chartName": chart_name, "status": "error", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = [executor.submit(_create_chart, (i, c)) for i, c in enumerate(charts)]
        for future in as_completed(futures):
            i, r = future.result()
            indexed_results[i] = r

    results: List[dict] = [indexed_results[i] for i in range(len(charts))]

    output_data = {
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "appId": app_id,
        "appName": app_name,
        "planFile": str(plan_path),
        "totalCharts": len(charts),
        "successCount": sum(1 for r in results if r.get("status") == "success"),
        "results": results,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        CHART_CREATE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (CHART_CREATE_DIR / f"chart_create_{app_id}_{ts}.json").resolve()
        write_json(CHART_CREATE_DIR / "chart_create_latest.json", output_data)

    write_json(output_path, output_data)

    success = output_data["successCount"]
    total = output_data["totalCharts"]
    print(f"\n完成：{success}/{total} 个图表创建成功")
    print(f"结果文件: {output_path}")

    # Step: savePage（把图表布局到 page）
    # page_id 已在上方解析
    if page_id and not args.dry_run and success > 0:
        print(f"\n[savePage] 将 {success} 个图表布局到 page: {page_id}")
        try:
            # 1. 先 GET 当前 page，获取真实 version 和已有 components
            current_page = get_page(page_id, auth_config_path)
            current_version = int(current_page.get("version", 1))
            existing_components = current_page.get("components", []) or []
            print(f"  当前 page version={current_version}，已有 {len(existing_components)} 个组件")

            # 2. 追加新图表 components
            all_components = build_page_components(results, app_id, existing_components)

            # 3. savePage
            page_resp = save_page(page_id, all_components, current_version, auth_config_path, referer=chart_referer)
            page_ok = (
                page_resp.get("success") is True
                or page_resp.get("status") == 1
                or page_resp.get("code") == 1
            )
            if page_ok:
                new_version = page_resp.get("data", {}).get("version", current_version + 1)
                print(f"  -> savePage 成功，page version {current_version} → {new_version}，共 {len(all_components)} 个组件")
            else:
                print(f"  -> savePage 返回异常: {page_resp}")
        except Exception as exc:
            print(f"  -> savePage 失败: {exc}")


if __name__ == "__main__":
    main()
