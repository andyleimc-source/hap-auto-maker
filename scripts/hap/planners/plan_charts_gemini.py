#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调用 Gemini 为指定应用规划 8-12 个有业务意义的统计图配置。

只依赖 auth_config.py（browser auth），不需要 HAP-Appkey/Sign。

步骤：
1. 通过 --worksheet-ids 接收工作表 ID 列表（逗号分隔）
   若未提供，尝试从已有的 schema snapshot 自动读取
2. 拉取每张工作表的字段与视图（GetWorksheetControls，browser auth）
3. 构建 Gemini prompt，生成 8-12 个图表规划
4. 验证并输出 chart_plan JSON
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import auth_retry
from ai_utils import create_generation_config, get_ai_client, load_ai_config
from utils import now_ts, load_json, write_json
from planning.chart_planner import build_enhanced_prompt as chart_planner_build_prompt

BASE_DIR = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
CHART_PLAN_DIR = OUTPUT_ROOT / "chart_plans"
MOCK_SCHEMA_DIR = OUTPUT_ROOT / "mock_data_schema_snapshots"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
GET_VIEWS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetViews"
GET_WORKSHEET_INFO_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetInfo"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_gemini_api_key(config_path: Path) -> str:
    data = load_ai_config(config_path)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"AI 配置缺少 api_key: {config_path}")
    return api_key


def extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Gemini 返回为空")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Gemini 未返回可解析 JSON:\n{text[:500]}")


def resolve_worksheet_ids_from_snapshot(app_id: str) -> List[str]:
    """从 schema snapshot 提取该应用的工作表 ID 列表。"""
    # 按修改时间找最新匹配该 appId 的 snapshot
    candidates = sorted(
        MOCK_SCHEMA_DIR.glob(f"mock_schema_snapshot_{app_id}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        # 也尝试 latest
        latest = MOCK_SCHEMA_DIR / "mock_schema_snapshot_latest.json"
        if latest.exists():
            data = load_json(latest)
            if str(data.get("app", {}).get("appId", "")).strip() == app_id:
                candidates = [latest]
    if not candidates:
        return []
    data = load_json(candidates[0])
    ws_ids = [str(ws.get("worksheetId", "")).strip()
              for ws in data.get("worksheets", [])
              if str(ws.get("worksheetId", "")).strip()]
    return ws_ids


# ---------------------------------------------------------------------------
# 数据拉取（仅 browser auth）
# ---------------------------------------------------------------------------

def fetch_worksheet_controls(worksheet_id: str, auth_config_path: Path) -> dict:
    """拉取工作表字段与视图详情（使用 browser auth）。"""
    resp = auth_retry.hap_web_post(GET_CONTROLS_URL, auth_config_path,
                                   referer="https://www.mingdao.com/",
                                   json={"worksheetId": worksheet_id}, timeout=30)
    data = resp.json()
    # 兼容两层包装
    wrapped = data.get("data", {})
    if isinstance(wrapped, dict) and isinstance(wrapped.get("data"), dict):
        payload = wrapped["data"]
    elif isinstance(wrapped, dict):
        payload = wrapped
    else:
        payload = {}
    return payload


def resolve_app_uuid_from_ws(ws_id: str, auth_config_path: Path) -> str:
    """通过 worksheetId 解析 UUID 格式的 appId（用于调用 GetWorksheetViews）。"""
    import re
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                ws_id.lower()):
        return ws_id  # already UUID
    resp = auth_retry.hap_web_post(GET_WORKSHEET_INFO_URL, auth_config_path,
                                   referer="https://www.mingdao.com/",
                                   json={"worksheetId": ws_id}, timeout=15)
    data = resp.json().get("data", {})
    return str(data.get("appId", "")).strip()


def fetch_worksheet_views(worksheet_id: str, app_uuid: str,
                          auth_config_path: Path) -> List[dict]:
    """拉取工作表的视图列表（需要 UUID 格式的 appId）。"""
    if not app_uuid:
        return []
    resp = auth_retry.hap_web_post(GET_VIEWS_URL, auth_config_path,
                                   referer="https://www.mingdao.com/",
                                   json={"worksheetId": worksheet_id, "appId": app_uuid},
                                   timeout=15)
    raw = resp.json()
    views_raw = raw.get("data", []) or []
    result = []
    for v in views_raw:
        if not isinstance(v, dict):
            continue
        view_id = str(v.get("viewId", "")).strip()
        if not view_id:
            continue
        result.append({
            "viewId": view_id,
            "name": str(v.get("name", "")).strip(),
            "viewType": int(v.get("viewType", 0) or 0),
        })
    return result


def simplify_controls(controls: list) -> List[dict]:
    """简化字段信息供 Gemini 分析。"""
    SKIP_TYPES = {14, 21, 22, 26, 27, 48, 31, 37, 33, 43, 45, 51, 10010}
    NUMERIC_TYPES = {6, 8, 28, 31, 37}
    DATE_TYPES = {15, 16}
    SELECT_TYPES = {9, 10, 11}

    simplified = []
    for c in controls or []:
        t = int(c.get("type", 0) or c.get("controlType", 0) or 0)
        if t in SKIP_TYPES:
            continue
        field_id = str(c.get("id", "") or c.get("controlId", "")).strip()
        if not field_id:
            continue
        entry: Dict[str, Any] = {
            "controlId": field_id,
            "controlName": str(c.get("controlName", "") or c.get("name", "")).strip(),
            "controlType": t,
            "_isNumeric": t in NUMERIC_TYPES,
            "_isDate": t in DATE_TYPES,
            "_isSelect": t in SELECT_TYPES,
        }
        if t in SELECT_TYPES:
            opts = []
            for o in (c.get("options") or []):
                if isinstance(o, dict) and not o.get("isDeleted"):
                    opts.append({"key": str(o.get("key", "")), "value": str(o.get("value", ""))})
            entry["options"] = opts[:20]
        simplified.append(entry)
    return simplified


def extract_views_from_payload(payload: dict) -> List[dict]:
    """从 GetWorksheetControls payload 提取视图列表。"""
    views = payload.get("views", [])
    if not isinstance(views, list):
        return []
    result = []
    for v in views:
        if not isinstance(v, dict):
            continue
        view_id = str(v.get("viewId", "") or v.get("id", "")).strip()
        if not view_id:
            continue
        result.append({
            "viewId": view_id,
            "name": str(v.get("name", "")).strip(),
            "viewType": int(v.get("viewType", 0) or 0),
        })
    return result


# ---------------------------------------------------------------------------
# Gemini 调用
# ---------------------------------------------------------------------------

REPORT_TYPE_NAMES = {
    1: "柱图", 2: "折线图", 3: "饼图/环形图",
    6: "漏斗图", 7: "双轴图", 8: "透视表/雷达图",
    9: "行政区划图", 10: "数值图", 11: "对称条形图", 12: "散点图",
    13: "词云图", 14: "仪表盘", 15: "进度图", 16: "排行图", 17: "地图",
}


def build_prompt(app_id: str, app_name: str, worksheets_info: List[dict]) -> str:
    ws_json = json.dumps(worksheets_info, ensure_ascii=False, indent=2)
    return f"""
你是企业数据分析助手。请根据下面的应用结构，为该应用设计 8-12 个有业务意义的统计图，输出严格 JSON，不要 markdown，不要任何解释。

应用信息：
- appId: {app_id}
- appName: {app_name}

工作表与字段信息：
{ws_json}

设计要求：
1. 共输出 8-12 个图表，覆盖尽可能多的工作表和业务维度（时间趋势、分类分布、状态占比、数量统计、排行对比等）。
2. 图表类型必须多样化，至少使用 5 种不同的 reportType。可选类型如下：
   1=柱图, 2=折线图, 3=饼图/环形图, 6=漏斗图,
   7=双轴图（需要 rightY 结构）, 10=数值图（数字卡片，不需要 xaxes 维度）,
   11=对称条形图, 12=散点图, 15=进度图, 16=排行图
3. xaxes 优先选择 _isSelect=true（controlType=9/10/11）字段用于分类图，_isDate=true（controlType=15/16）字段用于趋势图。
   也可以使用系统字段 ctime（创建时间，controlType=16）作为 X 轴时间维度。
4. yaxisList 使用 controlId="record_count"（记录数量统计，controlType=10000000）。
   若有 _isNumeric=true 的字段，也可以用于数值汇总。
5. 每个图表名称简洁有业务含义（10 字以内）。
6. views 数组填入该工作表的 views 列表（若为空则输出 []）。
7. 建议组合：2-3 个数值卡片(reportType=10) + 2-3 个柱状/条形/折线图 + 1-2 个饼图/环形图 + 1-2 个漏斗/雷达/排行/区域图。
8. 数值图(reportType=10)：xaxes.controlId 设为 null，只需 yaxisList，适合展示关键指标总数。
9. 双轴图(reportType=7)：需要额外添加 "yreportType": 2（第二轴为折线图），以及 "rightY": {"yaxisList": [...]} 结构（右轴指标），yaxisList 至少 2 个指标。

输出 JSON 结构（严格按此格式）：
{{
  "appId": "{app_id}",
  "appName": "{app_name}",
  "charts": [
    {{
      "name": "图表名称",
      "desc": "简短描述，说明业务意义",
      "reportType": 1,
      "worksheetId": "工作表ID",
      "worksheetName": "工作表名称",
      "yreportType": null,
      "views": [
        {{"viewId": "视图ID", "name": "视图名", "viewType": 0}}
      ],
      "xaxes": {{
        "controlId": "字段ID或ctime或null",
        "controlName": "字段名称",
        "controlType": 16,
        "particleSizeType": 1,
        "sortType": 0,
        "emptyType": 0,
        "rename": "",
        "xaxisEmptyType": 0,
        "xaxisEmpty": false
      }},
      "yaxisList": [
        {{
          "controlId": "record_count",
          "controlName": "记录数量",
          "controlType": 10000000,
          "rename": ""
        }}
      ],
      "filter": {{
        "filterRangeId": "ctime",
        "filterRangeName": "创建时间",
        "rangeType": 18,
        "rangeValue": 365,
        "today": true
      }}
    }}
  ]
}}

注意：
- controlId="ctime" 固定：controlType=16，controlName="创建时间"。
- controlId="record_count" 固定：controlType=10000000，controlName="记录数量"。
- 只选择该工作表实际存在的字段 ID（或 ctime 系统字段）。
- particleSizeType 仅对 _isDate 字段有效：1=按月，2=按季度，3=按年，4=按天；非日期字段设为 0。
- 数值图(reportType=10)的 xaxes.controlId 必须为 null。
""".strip()


def generate_with_retry(client, model: str, prompt: str, ai_config: dict, retries: int = 4) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=create_generation_config(
                    ai_config,
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            wait = min(16, 2 ** (attempt - 1))
            print(f"Gemini 调用失败，{wait}s 后重试（{attempt}/{retries}）: {exc}")
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


VALID_REPORT_TYPES = set(range(1, 18))  # reportType 1-17


def _force_ctime_filter(chart: dict) -> None:
    """统一强制时间筛选来源为创建时间 ctime，保留原有时间范围设置。"""
    filter_cfg = chart.get("filter")
    if not isinstance(filter_cfg, dict):
        filter_cfg = {}
    filter_cfg["filterRangeId"] = "ctime"
    filter_cfg["filterRangeName"] = "创建时间"
    chart["filter"] = filter_cfg


def _default_record_count_yaxis(rename: str = "记录数量") -> dict:
    return {
        "controlId": "record_count",
        "controlType": 10000000,
        "controlName": "记录数量",
        "rename": rename,
    }


def _sanitize_yaxis_list(yaxis_list: list, valid_fids: set[str], *, log_prefix: str) -> list[dict]:
    """过滤掉字段不存在的 y 轴项。"""
    clean: list[dict] = []
    for j, yaxis in enumerate(yaxis_list):
        if not isinstance(yaxis, dict):
            print(f"[跳过yaxis] {log_prefix}[{j}] 不是对象，已移除")
            continue
        y_cid = str(yaxis.get("controlId", "")).strip()
        if y_cid and y_cid not in valid_fids:
            print(f"[跳过yaxis] {log_prefix}[{j}].controlId「{y_cid}」不在字段中，已移除该 yaxis")
            continue
        clean.append(yaxis)
    return clean


def _ensure_symmetric_right_axis(chart: dict, valid_fids: set[str], *, chart_label: str) -> None:
    """对称条形图(reportType=11) 兜底：保证方向2有可用数值轴。"""
    right_y = chart.get("rightY", {})
    if isinstance(right_y, list):
        right_y = {"yaxisList": right_y}
    if not isinstance(right_y, dict):
        right_y = {}

    raw_right_list = right_y.get("yaxisList", [])
    if not isinstance(raw_right_list, list):
        raw_right_list = []
    clean_right = _sanitize_yaxis_list(
        raw_right_list,
        valid_fids,
        log_prefix=f"{chart_label} rightY.yaxisList",
    )
    if not clean_right:
        print(f"[补全] {chart_label} 方向2(数值)无有效字段，自动补全 record_count")
        clean_right = [_default_record_count_yaxis("方向2记录数量")]

    right_y["yaxisList"] = clean_right
    if right_y.get("reportType") is None:
        right_y["reportType"] = 2
    chart["rightY"] = right_y

    if chart.get("yreportType") is None:
        chart["yreportType"] = 1


def validate_plan(raw: dict, worksheets_by_id: Dict[str, dict]) -> List[dict]:
    charts = raw.get("charts", [])
    if not isinstance(charts, list) or len(charts) == 0:
        raise ValueError("Gemini 未返回 charts 数组")
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
        if report_type not in VALID_REPORT_TYPES:
            raise ValueError(f"图表 {i+1} reportType 非法: {report_type}")
        worksheet_id = str(chart.get("worksheetId", "")).strip()
        if worksheet_id not in worksheets_by_id:
            print(f"[警告] 图表 {i+1} worksheetId 不存在，已跳过: {worksheet_id}")
            continue
        # 构建该工作表的有效字段 ID 集合
        ws_info = worksheets_by_id[worksheet_id]
        ws_fields = ws_info.get("fields", [])
        valid_fids = {str(f.get("id", "") or f.get("controlId", "")).strip()
                      for f in ws_fields if str(f.get("id", "") or f.get("controlId", "")).strip()}
        valid_fids.update({"ctime", "utime", "ownerid", "caid", "record_count"})
        xaxes = chart.get("xaxes", {})
        if not isinstance(xaxes, dict):
            print(f"[跳过] 图表 {i+1}「{name}」xaxes 格式错误，已跳过")
            continue
        # 数值图 (reportType=10) xaxes.controlId 可以为 null
        x_control_id = xaxes.get("controlId")
        if report_type != 10 and not str(x_control_id or "").strip():
            print(f"[跳过] 图表 {i+1}「{name}」xaxes 缺少 controlId，已跳过")
            continue
        # 校验 xaxes.controlId 是否在工作表字段中
        x_cid_str = str(x_control_id or "").strip()
        if report_type != 10 and x_cid_str and x_cid_str not in valid_fids:
            print(f"[跳过] 图表 {i+1}「{name}」xaxes.controlId「{x_cid_str}」不在字段中，已跳过")
            continue
        yaxis_list = chart.get("yaxisList", [])
        if not isinstance(yaxis_list, list) or len(yaxis_list) == 0:
            print(f"[跳过] 图表 {i+1}「{name}」yaxisList 为空，已跳过")
            continue
        # 校验 yaxisList 中的 controlId（跳过无效的 yaxis 条目而非整张图）
        clean_yaxis = _sanitize_yaxis_list(
            yaxis_list,
            valid_fids,
            log_prefix=f"图表 {i+1}「{name}」yaxisList",
        )
        if not clean_yaxis:
            print(f"[跳过] 图表 {i+1}「{name}」所有 yaxis 均无效，已跳过整张图")
            continue
        chart["yaxisList"] = clean_yaxis

        # 双轴图(reportType=7) 必须有 rightY 且 rightY.yaxisList 非空，否则降级为柱状图(1)
        if report_type == 7:
            right_y = chart.get("rightY")
            right_y_list = right_y.get("yaxisList", []) if isinstance(right_y, dict) else []
            if not isinstance(right_y, dict) or not right_y_list:
                print(f"[降级] 图表 {i+1}「{name}」双轴图缺少 rightY/辅助Y轴，降级为柱状图(reportType=1)")
                chart["reportType"] = 1
                chart.pop("yreportType", None)
                chart.pop("rightY", None)

        # 对称条形图(reportType=11) 必须保证方向2(数值)有可用字段
        if report_type == 11:
            _ensure_symmetric_right_axis(
                chart,
                valid_fids,
                chart_label=f"图表 {i+1}「{name}」",
            )

        # 所有图表统一强制时间来源为 ctime
        _force_ctime_filter(chart)
        validated.append(chart)
    if not validated:
        raise ValueError("所有图表均未通过校验，请重新规划")
    return validated


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

SYSTEM_ONLY_WORKSHEET_ID = "__system_fields_only__"


def build_prompt_system_only(app_id: str, app_name: str, views_hint: List[dict]) -> str:
    """当没有工作表字段数据时，仅用视图名称和系统字段规划图表。"""
    view_names = [v.get("name", "") for v in views_hint if v.get("name")]
    context = f"视图列表（可从视图名称推断业务场景）：{json.dumps(view_names, ensure_ascii=False)}" if view_names else "无视图信息"
    return f"""
你是企业数据分析助手。请为以下应用设计 8 个业务统计图，输出严格 JSON，不要 markdown，不要任何解释。

应用信息：
- appId: {app_id}
- appName: {app_name}
- {context}

只能使用以下系统字段（无法获取自定义字段）：
- ctime：创建时间，controlType=16（用于时间趋势）
- utime：最后修改时间，controlType=16
- record_count：记录数量统计，controlType=10000000

设计要求：
1. 共 8 个图表，各图表侧重不同时间维度和统计视角。
2. 图表类型多样化：2-3 个数值卡片(reportType=10) + 2 个柱状/折线图 + 1 个饼图 + 1-2 个其他类型(条形/区域/排行)。数值图的 xaxes.controlId 设为 null。
3. 图表名称简洁有业务含义（10 字以内）。
4. views 数组使用：{json.dumps(views_hint, ensure_ascii=False)}

输出 JSON 结构：
{{
  "appId": "{app_id}",
  "appName": "{app_name}",
  "charts": [
    {{
      "name": "图表名称",
      "desc": "简短描述",
      "reportType": 1,
      "worksheetId": "{SYSTEM_ONLY_WORKSHEET_ID}",
      "worksheetName": "（使用系统字段）",
      "views": {json.dumps(views_hint, ensure_ascii=False)},
      "xaxes": {{
        "controlId": "ctime",
        "controlName": "创建时间",
        "controlType": 16,
        "particleSizeType": 1,
        "sortType": 0,
        "emptyType": 0,
        "rename": "",
        "xaxisEmptyType": 0,
        "xaxisEmpty": false
      }},
      "yaxisList": [
        {{
          "controlId": "record_count",
          "controlName": "记录数量",
          "controlType": 10000000,
          "rename": ""
        }}
      ],
      "filter": {{
        "filterRangeId": "ctime",
        "filterRangeName": "创建时间",
        "rangeType": 18,
        "rangeValue": 365,
        "today": true
      }}
    }}
  ]
}}

注意：
- particleSizeType：1=按月，2=按季度，3=按年，4=按天。不同图表使用不同 particleSizeType。
- 数值图(reportType=10)的 xaxes.controlId 必须为 null，不需要维度字段。
""".strip()


def validate_plan_relaxed(raw: dict) -> List[dict]:
    """宽松验证：只检查必要结构，不验证 worksheetId。"""
    charts = raw.get("charts", [])
    if not isinstance(charts, list) or len(charts) == 0:
        raise ValueError("Gemini 未返回 charts 数组")
    if len(charts) < 3:
        raise ValueError(f"图表数量不足，只返回 {len(charts)} 个")
    validated = []
    for i, chart in enumerate(charts):
        if not isinstance(chart, dict):
            raise ValueError(f"图表 {i+1} 格式错误")
        if not str(chart.get("name", "")).strip():
            raise ValueError(f"图表 {i+1} 缺少 name")
        report_type = int(chart.get("reportType", 0) or 0)
        if report_type not in VALID_REPORT_TYPES:
            raise ValueError(f"图表 {i+1} reportType 非法: {report_type}")
        xaxes = chart.get("xaxes", {})
        if not isinstance(xaxes, dict):
            raise ValueError(f"图表 {i+1} xaxes 格式错误")
        if report_type != 10 and not str(xaxes.get("controlId") or "").strip():
            raise ValueError(f"图表 {i+1} xaxes 缺少 controlId")
        if not isinstance(chart.get("yaxisList", []), list) or not chart.get("yaxisList"):
            raise ValueError(f"图表 {i+1} yaxisList 为空")
        validated.append(chart)
    return validated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="调用 Gemini 为应用规划 8-12 个业务统计图（只需 auth_config.py）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用方式（任选一种）：
  # 方式 1：提供工作表 ID（从应用 URL 复制），获取最丰富的字段信息
  python plan_charts_gemini.py --app-id APP_ID --worksheet-ids WS_ID1,WS_ID2

  # 方式 2：只提供应用信息，用系统字段（ctime/record_count）创建通用图表
  python plan_charts_gemini.py --app-id APP_ID --app-name 供应商管理

  # 方式 3：提供 views JSON（从已有图表的 curl 里复制 views 数组）
  python plan_charts_gemini.py --app-id APP_ID --views-json '[{"viewId":"xxx","name":"所有供应商","viewType":0}]'
        """,
    )
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--app-name", default="", help="应用名称")
    parser.add_argument("--worksheet-ids", default="", help="工作表 ID 列表，逗号分隔（从应用 URL 复制）")
    parser.add_argument("--views-json", default="", help="视图数组 JSON 字符串（从已有图表 curl 的 views 字段复制）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    parser.add_argument("--gemini-retries", type=int, default=4, help="Gemini 最大重试次数")
    args = parser.parse_args()

    app_id = args.app_id.strip()
    app_name = args.app_name.strip() or app_id
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    
    ai_config = load_ai_config()
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]

    # 解析 views_json（如果提供）
    preset_views: List[dict] = []
    if args.views_json.strip():
        try:
            preset_views = json.loads(args.views_json.strip())
            if not isinstance(preset_views, list):
                preset_views = []
        except json.JSONDecodeError as e:
            print(f"警告：--views-json 解析失败，将使用空视图: {e}")

    # 解析工作表 ID 列表
    ws_ids: List[str] = []
    if args.worksheet_ids.strip():
        ws_ids = [x.strip() for x in args.worksheet_ids.split(",") if x.strip()]
    else:
        # 尝试从 schema snapshot 读取
        ws_ids = resolve_worksheet_ids_from_snapshot(app_id)

    use_system_fields_only = len(ws_ids) == 0

    if use_system_fields_only:
        print("[模式] 仅系统字段模式（未提供 --worksheet-ids）")
        print("  使用字段: ctime（创建时间）+ record_count（记录数）")
        print("  如需更丰富的图表，请添加 --worksheet-ids（从应用 URL 的路径中复制工作表 ID）")
        worksheets_info = []
        worksheets_by_id: Dict[str, dict] = {SYSTEM_ONLY_WORKSHEET_ID: {"worksheetId": SYSTEM_ONLY_WORKSHEET_ID}}
    else:
        print(f"[1/3] 拉取工作表字段与视图（{len(ws_ids)} 张）...")
        worksheets_info = []
        worksheets_by_id = {}
        # 解析 UUID 格式 appId（用于获取视图，GetWorksheetViews 需要 UUID appId）
        app_uuid = resolve_app_uuid_from_ws(ws_ids[0], auth_config_path) if ws_ids else ""
        for ws_id in ws_ids:
            payload = fetch_worksheet_controls(ws_id, auth_config_path)
            ws_name = str(payload.get("worksheetName", ws_id)).strip()
            controls = simplify_controls(payload.get("controls", []))
            # 优先从 GetWorksheetViews 获取真实视图（需 UUID appId）
            views = fetch_worksheet_views(ws_id, app_uuid, auth_config_path)
            if not views:
                views = extract_views_from_payload(payload)
            if not views and preset_views:
                views = preset_views
            print(f"  - {ws_name} ({ws_id}): {len(controls)} 个字段，{len(views)} 个视图")
            info = {
                "worksheetId": ws_id,
                "worksheetName": ws_name,
                "views": views,
                "fields": controls,
            }
            worksheets_info.append(info)
            worksheets_by_id[ws_id] = info

    # AI 规划
    step = "1/1" if use_system_fields_only else "3/3"
    print(f"[{step}] 调用 AI 规划图表（模型: {model_name}）...")

    if use_system_fields_only:
        prompt = build_prompt_system_only(app_id, app_name, preset_views)
        validate_fn = lambda raw, _: validate_plan_relaxed(raw)
    else:
        # 使用 chart_planner 增强版 prompt（含注册中心类型约束+字段分类推荐）
        num_ws_for_page = len(worksheets_info)
        if num_ws_for_page <= 1:
            target_count = 4
        elif num_ws_for_page <= 3:
            target_count = 6
        elif num_ws_for_page <= 6:
            target_count = 8
        else:
            target_count = 10
        prompt = chart_planner_build_prompt(app_name, worksheets_info, target_count=target_count)
        print(f"[chart_planner] prompt 长度={len(prompt)}，前200字: {prompt[:200]!r}")
        validate_fn = validate_plan

    validated: Optional[List[dict]] = None
    last_error: Optional[str] = None
    for val_attempt in range(1, 4):
        p = prompt
        if last_error:
            p = prompt + f"\n\n# 上次验证失败（第 {val_attempt - 1} 次）\n错误信息：{last_error}\n请修正后重新输出。"
        response = generate_with_retry(client, model_name, p, ai_config, args.gemini_retries)
        raw = extract_json_object(response.text or "")
        try:
            validated = validate_fn(raw, worksheets_by_id)
            break
        except Exception as exc:
            last_error = str(exc)
            print(f"  验证失败（{val_attempt}/3）: {exc}")
            if val_attempt >= 3:
                raise

    assert validated is not None

    # 系统字段模式：清理占位 worksheetId
    for chart in validated:
        if str(chart.get("worksheetId", "")).strip() == SYSTEM_ONLY_WORKSHEET_ID:
            chart.pop("worksheetId", None)
            chart.pop("worksheetName", None)

    plan = {
        "schemaVersion": "chart_plan_v1",
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "appId": app_id,
        "appName": app_name,
        "charts": validated,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        CHART_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        ts = now_ts()
        output_path = (CHART_PLAN_DIR / f"chart_plan_{app_id}_{ts}.json").resolve()
        write_json(CHART_PLAN_DIR / "chart_plan_latest.json", plan)

    write_json(output_path, plan)
    print(f"\n规划完成，共 {len(validated)} 个图表")
    for i, c in enumerate(validated, 1):
        print(f"  {i}. [{REPORT_TYPE_NAMES.get(c['reportType'], '?')}] {c['name']} — {c.get('desc', '')}")
    print(f"\n输出文件: {output_path}")


if __name__ == "__main__":
    main()
