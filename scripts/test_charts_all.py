#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 12 种图表类型能否在明道云 CRM 应用中成功创建。

图表类型：环形图(4), 雷达图(6), 条形图(7), 双轴图(8), 散点图(9),
         区域图(11), 进度图(12), 透视表(13), 词云图(14),
         排行图(15), 地图(16), 关系图(17)
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))

import auth_retry
from charts import build_report_body

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

APP_ID = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"
PROJECT_ID = "faa2f6b1-f706-4084-9a8d-50616817f890"
PAGE_ID = "69cf23ea0a5c9f9c3bdf1f16"
WORKSHEET_ID = "69cf74eef9434db36c6e0816"
AUTH_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

SAVE_REPORT_URL = "https://api.mingdao.com/report/reportConfig/saveReportConfig"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"

REFERER = f"https://www.mingdao.com/app/{APP_ID}/{PAGE_ID}"


# ---------------------------------------------------------------------------
# 获取工作表字段
# ---------------------------------------------------------------------------

def get_worksheet_controls() -> list[dict]:
    """获取 WORKSHEET_ID 的字段列表。"""
    resp = auth_retry.hap_web_post(
        GET_CONTROLS_URL,
        AUTH_PATH,
        referer=REFERER,
        json={"worksheetId": WORKSHEET_ID, "appId": APP_ID},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("state") != 1:
        raise RuntimeError(f"GetWorksheetControls 失败: {data}")
    raw = data.get("data", {})
    if isinstance(raw, dict):
        controls = raw.get("controls", [])
    else:
        controls = []
    return controls


# ---------------------------------------------------------------------------
# 创建图表
# ---------------------------------------------------------------------------

def save_report(body: dict) -> dict:
    resp = auth_retry.hap_web_post(
        SAVE_REPORT_URL,
        AUTH_PATH,
        referer=REFERER,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def extract_report_id(resp_data: dict) -> str:
    if not isinstance(resp_data, dict):
        return ""
    data_field = resp_data.get("data", {})
    if isinstance(data_field, dict):
        return str(data_field.get("reportId", "") or data_field.get("id", "")).strip()
    return str(data_field or "").strip()


def is_success(resp_data: dict, report_id: str) -> bool:
    return (
        resp_data.get("success") is True
        or resp_data.get("status") == 1
        or resp_data.get("code") == 1
        or bool(report_id)
    )


# ---------------------------------------------------------------------------
# 主测试逻辑
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("图表类型验证测试 — 明道云 CRM 应用")
    print("=" * 70)

    # Step 1: 获取字段
    print("\n[Step 1] 获取工作表字段...")
    try:
        controls = get_worksheet_controls()
        print(f"  共获取 {len(controls)} 个字段")
        for c in controls[:10]:
            print(f"    controlId={c.get('controlId')}  type={c.get('type')}  name={c.get('controlName')}")
        if len(controls) > 10:
            print(f"    ... (共 {len(controls)} 个，仅显示前 10)")
    except Exception as e:
        print(f"  ✗ 获取字段失败: {e}")
        controls = []

    # 选取合适字段：优先文本/选项类(type in 2,6,9,15,26,29)作为 xaxes
    # 优先数值类(type in 6,8)作为 yaxisList
    text_ctrl = None
    num_ctrl = None
    option_ctrl = None
    for c in controls:
        ct = c.get("type")
        if ct in (2,) and text_ctrl is None:
            text_ctrl = c
        if ct in (6, 8) and num_ctrl is None:
            num_ctrl = c
        if ct in (9, 10, 11) and option_ctrl is None:
            option_ctrl = c

    # 默认 fallback：用第一个非标题字段，或标题字段
    fallback_ctrl = controls[0] if controls else {
        "controlId": "ctime", "controlName": "创建时间", "type": 16
    }

    def pick_xaxes_ctrl(prefer_text=False, prefer_option=False):
        """选取合适的 xaxes 字段。"""
        if prefer_option and option_ctrl:
            return option_ctrl
        if prefer_text and text_ctrl:
            return text_ctrl
        # 优先文本 > 选项 > fallback
        return text_ctrl or option_ctrl or fallback_ctrl

    def pick_num_ctrl():
        return num_ctrl or fallback_ctrl

    def make_xaxes(ctrl: dict) -> dict:
        return {
            "controlId": ctrl.get("controlId", ""),
            "controlName": ctrl.get("controlName", ""),
            "controlType": ctrl.get("type", 16),
        }

    def make_yaxis(ctrl: dict | None = None, label: str = "记录数量") -> dict:
        if ctrl is None:
            return {"controlId": "record_count", "controlName": label, "controlType": 10000000}
        return {
            "controlId": ctrl.get("controlId", "record_count"),
            "controlName": ctrl.get("controlName", label),
            "controlType": ctrl.get("type", 10000000),
        }

    x_ctrl = pick_xaxes_ctrl(prefer_option=True)
    x_ctrl_text = pick_xaxes_ctrl(prefer_text=True)

    # 地理字段：找 province/city/address 类型
    geo_ctrl = None
    for c in controls:
        if c.get("type") in (19, 23, 24, 25):  # 地区/定位相关
            geo_ctrl = c
            break
    if geo_ctrl is None:
        geo_ctrl = fallback_ctrl

    # ---------------------------------------------------------------------------
    # 定义 12 种图表测试用例
    # ---------------------------------------------------------------------------

    test_cases = [
        {
            "reportType": 4,
            "name": "【测试】环形图-客户来源分布",
            "desc": "reportType=4 环形图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 6,
            "name": "【测试】雷达图-多维对比",
            "desc": "reportType=6 雷达图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 7,
            "name": "【测试】条形图-横向排名",
            "desc": "reportType=7 条形图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 8,
            "name": "【测试】双轴图-数量与金额",
            "desc": "reportType=8 双轴图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis(label="记录数量"), make_yaxis(pick_num_ctrl(), "数值")],
            "yreportType": 2,
        },
        {
            "reportType": 9,
            "name": "【测试】散点图-分布分析",
            "desc": "reportType=9 散点图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 11,
            "name": "【测试】区域图-趋势面积",
            "desc": "reportType=11 区域图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 12,
            "name": "【测试】进度图-目标进度",
            "desc": "reportType=12 进度图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": {},  # 进度图不需要 xaxes
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 13,
            "name": "【测试】透视表-数据汇总",
            "desc": "reportType=13 透视表 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 14,
            "name": "【测试】词云图-文本分析",
            "desc": "reportType=14 词云图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl_text or x_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 15,
            "name": "【测试】排行图-TOP排名",
            "desc": "reportType=15 排行图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 16,
            "name": "【测试】地图-地区分布",
            "desc": "reportType=16 地图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(geo_ctrl),
            "yaxisList": [make_yaxis()],
        },
        {
            "reportType": 17,
            "name": "【测试】关系图-层级关系",
            "desc": "reportType=17 关系图 auto-test",
            "worksheetId": WORKSHEET_ID,
            "xaxes": make_xaxes(x_ctrl),
            "yaxisList": [make_yaxis()],
        },
    ]

    REPORT_TYPE_LABELS = {
        4: "环形图", 6: "雷达图", 7: "条形图", 8: "双轴图",
        9: "散点图", 11: "区域图", 12: "进度图", 13: "透视表",
        14: "词云图", 15: "排行图", 16: "地图", 17: "关系图",
    }

    # ---------------------------------------------------------------------------
    # Step 2: 逐个创建图表
    # ---------------------------------------------------------------------------

    print(f"\n[Step 2] 开始测试 {len(test_cases)} 种图表类型...\n")
    results = []

    for i, chart in enumerate(test_cases, 1):
        rt = chart["reportType"]
        label = REPORT_TYPE_LABELS.get(rt, str(rt))
        name = chart["name"]
        print(f"  [{i:02d}/{len(test_cases)}] reportType={rt} {label}  →  {name}")

        try:
            body = build_report_body(chart, APP_ID)
            resp_data = save_report(body)
            report_id = extract_report_id(resp_data)
            ok = is_success(resp_data, report_id)
            status = "PASS" if ok else "FAIL"
            note = ""
            if not ok:
                note = f"响应: {json.dumps(resp_data, ensure_ascii=False)[:200]}"
        except Exception as exc:
            status = "ERROR"
            report_id = ""
            note = str(exc)

        result = {
            "reportType": rt,
            "name": label,
            "chartName": name,
            "status": status,
            "reportId": report_id,
            "note": note,
        }
        results.append(result)

        if status == "PASS":
            print(f"         ✓ PASS  reportId={report_id}")
        else:
            print(f"         ✗ {status}  {note}")

    # ---------------------------------------------------------------------------
    # Step 3: 汇总
    # ---------------------------------------------------------------------------

    print("\n" + "=" * 70)
    print("测试汇总")
    print("=" * 70)
    print(f"{'reportType':<12} {'名称':<10} {'状态':<8} {'reportId'}")
    print("-" * 70)
    pass_count = 0
    fail_count = 0
    for r in results:
        status = r["status"]
        if status == "PASS":
            pass_count += 1
            icon = "✓"
        else:
            fail_count += 1
            icon = "✗"
        print(f"{icon} {r['reportType']:<10} {r['name']:<10} {status:<8} {r['reportId']}")
        if r["note"]:
            print(f"    备注: {r['note'][:120]}")

    print("-" * 70)
    print(f"总计: {len(results)} 种  PASS: {pass_count}  FAIL/ERROR: {fail_count}")
    print("=" * 70)

    if fail_count:
        print("\n失败项明细:")
        for r in results:
            if r["status"] != "PASS":
                print(f"  reportType={r['reportType']} {r['name']}: {r['note'][:200]}")


if __name__ == "__main__":
    main()
