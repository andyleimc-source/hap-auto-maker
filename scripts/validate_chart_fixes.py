#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证图表 bug 修复的端到端测试脚本。

测试场景：
  1. 在已创建的应用中创建2个工作表（员工表、考勤表）
  2. 创建2个图表验证 bug 修复：
     - 在职状态人数排名（排行图 type=15，SingleSelect 维度 — 非关联字段）
     - 每日迟到趋势（区域图 type=11，Date 维度 particleSizeType=4=日，不用年=0）
  3. 创建统计页面，将图表放入
  4. 输出应用链接和统计页面链接

Bug 修复验证点：
  Fix 1: 关联字段不能作为 xaxes（此脚本仅使用 SingleSelect + Date，跳过关联字段）
  Fix 2: 区域图 particleSizeType=4 (日)，不再用 0 (年)
  Fix 3: saveReportConfig 请求体中包含 appId
"""

from __future__ import annotations

import json
import secrets
import sys
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))

import auth_retry
from charts import build_report_body

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

APP_ID = "e33e2d3d-b424-4bbf-b0b6-ea8d8d9ca24d"  # 已创建的"图表修复验证"应用
PROJECT_ID = "faa2f6b1-f706-4084-9a8d-50616817f890"
BASE_URL = "https://api.mingdao.com"
WEB_BASE = "https://www.mingdao.com"

AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

CREATE_WS_URL = BASE_URL + "/v3/app/worksheets"
GET_APP_URL = WEB_BASE + "/api/HomeApp/GetApp"
ADD_SECTION_URL = WEB_BASE + "/api/HomeApp/AddAppSection"
ADD_WORKSHEET_URL = WEB_BASE + "/api/AppManagement/AddWorkSheet"
SAVE_REPORT_URL = BASE_URL + "/report/reportConfig/saveReportConfig"
SAVE_PAGE_URL = BASE_URL + "/report/custom/savePage"
GET_PAGE_URL = BASE_URL + "/report/custom/getPage"
GET_CONTROLS_URL = WEB_BASE + "/api/Worksheet/GetWorksheetControls"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def hap_post(url: str, payload: dict, referer: str = "") -> dict:
    resp = auth_retry.hap_web_post(url, AUTH_CONFIG_PATH, referer=referer, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def step(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print('='*60)


def ok(msg: str) -> None:
    print(f"  OK: {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL: {msg}")


# ---------------------------------------------------------------------------
# Step 1: 获取应用的 appSectionId
# ---------------------------------------------------------------------------

def get_app_section_id(app_id: str) -> tuple[str, str]:
    """返回 (appSectionId, projectId)."""
    step("Step 1: 获取应用分组信息")
    data = hap_post(GET_APP_URL, {"appId": app_id, "getSection": True},
                    referer="https://www.mingdao.com/")
    app_data = data.get("data", {})
    project_id = str(app_data.get("projectId", "")).strip() or PROJECT_ID
    sections = app_data.get("sections", [])

    if not sections:
        # 新应用没有分组，先创建一个
        print("  应用无分组，正在创建默认分组...")
        resp = hap_post(ADD_SECTION_URL, {"appId": app_id, "name": "默认"},
                        referer=f"https://www.mingdao.com/app/{app_id}")
        section_data = resp.get("data", {})
        app_section_id = str(section_data.get("appSectionId", "") or section_data.get("data", "")).strip()
        if not app_section_id:
            raise RuntimeError(f"创建分组失败: {resp}")
    else:
        app_section_id = str(sections[0].get("appSectionId", "")).strip()

    ok(f"appSectionId={app_section_id}, projectId={project_id}")
    return app_section_id, project_id


# ---------------------------------------------------------------------------
# Step 2: 创建工作表（V3 API）
# ---------------------------------------------------------------------------

def load_app_auth() -> dict:
    """加载应用授权信息（HAP-Appkey / HAP-Sign）。"""
    app_auth_path = (BASE_DIR / "data" / "outputs" / "app_authorizations" /
                     f"app_authorize_{APP_ID}.json")
    if not app_auth_path.exists():
        raise FileNotFoundError(
            f"未找到应用授权文件: {app_auth_path}\n"
            f"请先运行: python3 scripts/hap/get_app_authorize.py --app-id {APP_ID}"
        )
    data = json.loads(app_auth_path.read_text(encoding="utf-8"))
    rows = data.get("data", [])
    if not rows:
        raise RuntimeError(f"应用授权文件无数据: {app_auth_path}")
    return rows[0]


def create_worksheet(name: str, fields: list) -> str:
    """调用 V3 API 创建工作表，返回 worksheetId。"""
    import requests

    app_auth = load_app_auth()
    app_key = str(app_auth.get("appKey", "")).strip()
    sign = str(app_auth.get("sign", "")).strip()

    headers = {
        "Content-Type": "application/json",
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
    }
    payload = {"name": name, "fields": fields}
    resp = requests.post(CREATE_WS_URL, headers=headers, json=payload,
                         proxies={}, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"创建工作表 [{name}] 失败: {data}")
    ws_id = str(data.get("data", {}).get("worksheetId", "")).strip()
    if not ws_id:
        raise RuntimeError(f"创建工作表 [{name}] 未返回 worksheetId: {data}")
    return ws_id


def create_worksheets() -> tuple[str, str]:
    """创建员工表和考勤表，返回 (employee_ws_id, attendance_ws_id)。"""
    step("Step 2: 创建工作表")

    # 员工表字段
    employee_fields = [
        {"name": "姓名", "type": "Text", "required": True, "isTitle": 1},
        {
            "name": "在职状态",
            "type": "SingleSelect",
            "required": False,
            "options": [
                {"value": "在职", "index": 1},
                {"value": "离职", "index": 2},
                {"value": "试用期", "index": 3},
            ]
        },
        {"name": "入职日期", "type": "Date", "required": False},
    ]

    print("  创建员工表...")
    emp_ws_id = create_worksheet("员工表", employee_fields)
    ok(f"员工表 worksheetId={emp_ws_id}")

    # 考勤表字段
    attendance_fields = [
        {"name": "日期", "type": "Date", "required": True, "isTitle": 0},
        {"name": "是否迟到", "type": "Checkbox", "required": False},
    ]

    print("  创建考勤表...")
    att_ws_id = create_worksheet("考勤表", attendance_fields)
    ok(f"考勤表 worksheetId={att_ws_id}")

    return emp_ws_id, att_ws_id


# ---------------------------------------------------------------------------
# Step 3: 获取工作表字段（用于确定 controlId）
# ---------------------------------------------------------------------------

def get_worksheet_controls(worksheet_id: str) -> list:
    """获取工作表字段控件列表。"""
    data = hap_post(GET_CONTROLS_URL, {"worksheetId": worksheet_id},
                    referer="https://www.mingdao.com/")
    # 响应格式: {"data": {"code": 1, "data": {"controls": [...]}}}
    inner = data.get("data", {})
    if isinstance(inner, dict) and "data" in inner:
        controls = inner["data"].get("controls", [])
    else:
        controls = inner.get("controls", [])
    return controls


def find_control(controls: list, name: str) -> dict:
    """按名称查找控件。"""
    for c in controls:
        if str(c.get("controlName", "")).strip() == name:
            return c
    raise RuntimeError(f"未找到字段: {name}，已有字段: {[c.get('controlName') for c in controls]}")


# ---------------------------------------------------------------------------
# Step 4: 创建统计图
# ---------------------------------------------------------------------------

def create_chart(chart_dict: dict) -> str:
    """调用 saveReportConfig，返回 reportId。"""
    body = build_report_body(chart_dict, APP_ID)

    # Fix 3 验证：确保请求体中有 appId
    assert "appId" in body, "bug Fix 3 失败: 请求体缺少 appId"

    resp = auth_retry.hap_web_post(
        SAVE_REPORT_URL, AUTH_CONFIG_PATH,
        referer=f"https://www.mingdao.com/app/{APP_ID}",
        json=body, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()

    # 判断成功
    is_ok = (
        data.get("success") is True
        or data.get("status") == 1
        or data.get("code") == 1
    )
    report_id = ""
    if isinstance(data.get("data"), dict):
        report_id = str(data["data"].get("reportId", "") or data["data"].get("id", "")).strip()
    elif isinstance(data.get("data"), str):
        report_id = data["data"].strip()

    if not is_ok and not report_id:
        raise RuntimeError(f"saveReportConfig 失败: {data}")

    # 若没有明确 success 但有 reportId 也视为成功
    if not report_id and is_ok:
        # 某些接口直接在 data 顶层返回 id
        report_id = str(data.get("id", "") or data.get("reportId", "")).strip()

    if not report_id:
        raise RuntimeError(f"saveReportConfig 未返回 reportId: {data}")

    return report_id


def create_charts(emp_ws_id: str, att_ws_id: str) -> list[dict]:
    """创建验证图表，返回结果列表。"""
    step("Step 3: 获取工作表字段")

    print("  获取员工表字段...")
    emp_controls = get_worksheet_controls(emp_ws_id)
    print(f"  员工表字段: {[c.get('controlName') for c in emp_controls]}")

    print("  获取考勤表字段...")
    att_controls = get_worksheet_controls(att_ws_id)
    print(f"  考勤表字段: {[c.get('controlName') for c in att_controls]}")

    # 找到目标字段
    status_ctrl = find_control(emp_controls, "在职状态")
    date_ctrl = find_control(att_controls, "日期")

    ok(f"在职状态 controlId={status_ctrl['controlId']}, controlType={status_ctrl['type']}")
    ok(f"日期 controlId={date_ctrl['controlId']}, controlType={date_ctrl['type']}")

    step("Step 4: 创建验证图表")

    results = []

    # 图表1: 在职状态人数排名（排行图 type=15）
    # Fix 1 验证：使用 SingleSelect 而非关联字段
    print("  创建图表1: 在职状态人数排名（排行图 type=15）...")
    chart1 = {
        "name": "在职状态人数排名",
        "reportType": 15,
        "worksheetId": emp_ws_id,
        "xaxes": {
            "controlId": status_ctrl["controlId"],
            "controlName": "在职状态",
            "controlType": status_ctrl["type"],  # 9=SingleSelect
            "particleSizeType": 0,
            "sortType": 0,
            "emptyType": 0,
        },
        "yaxisList": [
            {
                "controlId": "record_count",
                "controlName": "记录数量",
                "controlType": 10000000,
                "rename": "",
            }
        ],
        "filter": {
            "filterRangeId": "ctime",
            "filterRangeName": "创建时间",
            "rangeType": 0,
            "rangeValue": 0,
            "today": False,
        },
    }
    try:
        report_id1 = create_chart(chart1)
        ok(f"图表1创建成功 reportId={report_id1}")
        results.append({"name": "在职状态人数排名", "reportType": 15, "reportId": report_id1, "status": "success"})
    except Exception as e:
        fail(f"图表1失败: {e}")
        results.append({"name": "在职状态人数排名", "reportType": 15, "status": "error", "error": str(e)})

    # 图表2: 每日迟到趋势（区域图 type=11）
    # Fix 2 验证：particleSizeType=4 (日)，不使用 0 (年)
    print("  创建图表2: 每日迟到趋势（区域图 type=11）...")
    chart2 = {
        "name": "每日迟到趋势",
        "reportType": 11,
        "worksheetId": att_ws_id,
        "xaxes": {
            "controlId": date_ctrl["controlId"],
            "controlName": "日期",
            "controlType": date_ctrl["type"],  # 15=Date
            "particleSizeType": 4,  # Fix 2: 4=日，不用 0=年（会导致显示"日期(季)"）
            "sortType": 0,
            "emptyType": 0,
        },
        "yaxisList": [
            {
                "controlId": "record_count",
                "controlName": "记录数量",
                "controlType": 10000000,
                "rename": "",
            }
        ],
        "filter": {
            "filterRangeId": "ctime",
            "filterRangeName": "创建时间",
            "rangeType": 0,
            "rangeValue": 0,
            "today": False,
        },
    }
    try:
        report_id2 = create_chart(chart2)
        ok(f"图表2创建成功 reportId={report_id2}")
        results.append({"name": "每日迟到趋势", "reportType": 11, "reportId": report_id2, "status": "success"})
    except Exception as e:
        fail(f"图表2失败: {e}")
        results.append({"name": "每日迟到趋势", "reportType": 11, "status": "error", "error": str(e)})

    return results


# ---------------------------------------------------------------------------
# Step 5: 创建统计页面并放入图表
# ---------------------------------------------------------------------------

def create_stats_page(app_section_id: str, project_id: str, chart_results: list) -> str:
    """创建统计页面（自定义页），返回 pageId。"""
    step("Step 5: 创建统计页面")

    # Step 5a: 创建 Page
    icon_url = "https://fp1.mingdaoyun.cn/customIcon/dashboard.svg"
    body = {
        "appId": APP_ID,
        "appSectionId": app_section_id,
        "name": "图表修复验证页",
        "remark": "",
        "iconColor": "#2196F3",
        "projectId": project_id,
        "icon": "dashboard",
        "iconUrl": icon_url,
        "type": 1,
        "createType": 0,
    }
    resp = hap_post(ADD_WORKSHEET_URL, body, referer=f"https://www.mingdao.com/app/{APP_ID}")
    is_ok = resp.get("state") == 1 or resp.get("status") == 1
    if not is_ok:
        raise RuntimeError(f"AddWorkSheet 创建 Page 失败: {resp}")
    page_id = str(resp.get("data", {}).get("pageId", "")).strip()
    if not page_id:
        raise RuntimeError(f"未返回 pageId: {resp}")
    ok(f"页面创建成功 pageId={page_id}")

    # Step 5b: 初始化空白 Page（version=0）
    init_body = {
        "appId": page_id,
        "version": 0,
        "components": [],
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
        },
    }
    auth_retry.hap_web_post(SAVE_PAGE_URL, AUTH_CONFIG_PATH,
                            referer=f"https://www.mingdao.com/app/{APP_ID}/{page_id}",
                            json=init_body, timeout=30)
    ok("页面初始化完成")

    # Step 5c: 获取当前 page version
    get_resp = auth_retry.hap_web_get(
        f"{GET_PAGE_URL}?appId={page_id}", AUTH_CONFIG_PATH, timeout=30
    )
    get_resp.raise_for_status()
    page_data = get_resp.json().get("data", {})
    version = int(page_data.get("version", 0))
    ok(f"当前 page version={version}")

    # Step 5d: 构建图表组件并 savePage
    success_charts = [r for r in chart_results if r.get("status") == "success" and r.get("reportId")]
    W, H = 24, 12
    components = []
    for idx, r in enumerate(success_charts):
        x = (idx % 2) * W
        y = (idx // 2) * H
        report_id = r["reportId"]
        components.append({
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
            "name": r.get("name", ""),
            "reportDesc": "",
            "reportType": r.get("reportType", 1),
            "showChartType": 1,
            "title": "",
            "titleVisible": False,
            "needUpdate": True,
            "worksheetId": APP_ID,
        })

    save_body = {
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
    save_resp = auth_retry.hap_web_post(
        SAVE_PAGE_URL, AUTH_CONFIG_PATH,
        referer=f"https://www.mingdao.com/app/{APP_ID}/{page_id}",
        json=save_body, timeout=30
    )
    save_resp.raise_for_status()
    save_data = save_resp.json()
    page_ok = (
        save_data.get("success") is True
        or save_data.get("status") == 1
        or save_data.get("code") == 1
    )
    if not page_ok:
        print(f"  WARNING: savePage 返回: {save_data}")
    else:
        new_ver = save_data.get("data", {}).get("version", version + 1) if isinstance(save_data.get("data"), dict) else version + 1
        ok(f"savePage 成功，version {version} -> {new_ver}，放入 {len(components)} 个图表")

    return page_id


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "="*70)
    print("  HAP 图表 Bug 修复验证脚本")
    print(f"  应用 ID: {APP_ID}")
    print("="*70)

    try:
        # Step 1: 获取 appSectionId
        app_section_id, project_id = get_app_section_id(APP_ID)

        # Step 2: 创建工作表
        emp_ws_id, att_ws_id = create_worksheets()

        # Step 3+4: 获取字段并创建图表
        chart_results = create_charts(emp_ws_id, att_ws_id)

        # Step 5: 创建统计页面
        success_count = sum(1 for r in chart_results if r.get("status") == "success")
        if success_count > 0:
            page_id = create_stats_page(app_section_id, project_id, chart_results)
        else:
            page_id = None
            print("\n  WARNING: 没有成功的图表，跳过页面创建")

        # 输出结果
        step("验证结果汇总")
        app_url = f"https://www.mingdao.com/app/{APP_ID}"
        page_url = f"https://www.mingdao.com/app/{APP_ID}/{page_id}" if page_id else "N/A"

        print(f"\n  应用链接:       {app_url}")
        print(f"  统计页面链接:   {page_url}")
        print()
        print(f"  员工表 ID:      {emp_ws_id}")
        print(f"  考勤表 ID:      {att_ws_id}")
        print()
        print(f"  图表结果 ({success_count}/{len(chart_results)} 成功):")
        for r in chart_results:
            status_mark = "OK" if r.get("status") == "success" else "FAIL"
            report_id = r.get("reportId", r.get("error", ""))
            print(f"    [{status_mark}] {r['name']} (type={r['reportType']}) -> {report_id}")

        print()
        print("  Bug 修复验证点:")
        print("    Fix 1: SingleSelect 字段作为 xaxes 维度 (非关联字段) - 已使用")
        print("    Fix 2: 区域图 particleSizeType=4 (日) - 已设置（非 0=年）")
        print("    Fix 3: saveReportConfig 请求体包含 appId - 已验证")
        print()

        if page_id:
            print(f"\n  请访问以下链接查看验证结果:")
            print(f"  {page_url}")

    except Exception as e:
        print(f"\n  FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
