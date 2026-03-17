#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调用 Gemini 为指定应用规划 3 个有业务意义的统计图配置。

只依赖 auth_config.py（browser auth），不需要 HAP-Appkey/Sign。

步骤：
1. 通过 --worksheet-ids 接收工作表 ID 列表（逗号分隔）
   若未提供，尝试从已有的 schema snapshot 自动读取
2. 拉取每张工作表的字段与视图（GetWorksheetControls，browser auth）
3. 构建 Gemini prompt，生成 3 个图表规划
4. 验证并输出 chart_plan JSON
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
CHART_PLAN_DIR = OUTPUT_ROOT / "chart_plans"
MOCK_SCHEMA_DIR = OUTPUT_ROOT / "mock_data_schema_snapshots"
GEMINI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
DEFAULT_MODEL = "gemini-2.5-pro"

GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
GET_VIEWS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetViews"
GET_WORKSHEET_INFO_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetInfo"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_gemini_api_key(config_path: Path) -> str:
    data = load_json(config_path)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"Gemini 配置缺少 api_key: {config_path}")
    return api_key


def load_web_auth(path: Path) -> tuple[str, str, str]:
    if not path.exists():
        raise FileNotFoundError(f"缺少认证配置: {path}")
    spec = importlib.util.spec_from_file_location("auth_config_runtime", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载认证文件: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    account_id = str(getattr(module, "ACCOUNT_ID", "")).strip()
    authorization = str(getattr(module, "AUTHORIZATION", "")).strip()
    cookie = str(getattr(module, "COOKIE", "")).strip()
    if not account_id or not authorization or not cookie:
        raise ValueError(f"auth_config.py 缺少 ACCOUNT_ID/AUTHORIZATION/COOKIE: {path}")
    return account_id, authorization, cookie


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

def fetch_worksheet_controls(worksheet_id: str, web_auth: tuple[str, str, str]) -> dict:
    """拉取工作表字段与视图详情（使用 browser auth）。"""
    account_id, authorization, cookie = web_auth
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.mingdao.com",
        "Referer": "https://www.mingdao.com/",
    }
    resp = requests.post(GET_CONTROLS_URL, headers=headers, json={"worksheetId": worksheet_id}, timeout=30)
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


def resolve_app_uuid_from_ws(ws_id: str, web_auth: tuple[str, str, str]) -> str:
    """通过 worksheetId 解析 UUID 格式的 appId（用于调用 GetWorksheetViews）。"""
    import re
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                ws_id.lower()):
        return ws_id  # already UUID
    account_id, authorization, cookie = web_auth
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.mingdao.com",
        "Referer": "https://www.mingdao.com/",
    }
    resp = requests.post(GET_WORKSHEET_INFO_URL, headers=headers,
                         json={"worksheetId": ws_id}, timeout=15)
    data = resp.json().get("data", {})
    return str(data.get("appId", "")).strip()


def fetch_worksheet_views(worksheet_id: str, app_uuid: str,
                          web_auth: tuple[str, str, str]) -> List[dict]:
    """拉取工作表的视图列表（需要 UUID 格式的 appId）。"""
    if not app_uuid:
        return []
    account_id, authorization, cookie = web_auth
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.mingdao.com",
        "Referer": "https://www.mingdao.com/",
    }
    resp = requests.post(GET_VIEWS_URL, headers=headers,
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

REPORT_TYPE_NAMES = {1: "柱状图", 2: "折线图", 3: "饼图", 4: "环形图"}


def build_prompt(app_id: str, app_name: str, worksheets_info: List[dict]) -> str:
    ws_json = json.dumps(worksheets_info, ensure_ascii=False, indent=2)
    return f"""
你是企业数据分析助手。请根据下面的应用结构，为该应用设计 3 个有业务意义的统计图，输出严格 JSON，不要 markdown，不要任何解释。

应用信息：
- appId: {app_id}
- appName: {app_name}

工作表与字段信息：
{ws_json}

设计要求：
1. 共输出 3 个图表，每个图表针对不同的业务维度（如：时间趋势、分类分布、状态占比等）。
2. 图表类型使用不同种类，从以下选择：1=柱状图、2=折线图、3=饼图。
3. xaxes 优先选择 _isSelect=true（controlType=9）字段用于分类图，_isDate=true（controlType=15/16）字段用于趋势图。
   也可以使用系统字段 ctime（创建时间，controlType=16）作为 X 轴时间维度。
4. yaxisList 使用 controlId="record_count"（记录数量统计，controlType=10000000）。
   若有 _isNumeric=true 的字段，也可以用于数值汇总。
5. 每个图表名称简洁有业务含义（10 字以内）。
6. views 数组填入该工作表的 views 列表（若为空则输出 []）。
7. 3 个图表中：至少 1 个饼图/环形图（分类占比）、至少 1 个折线图/柱状图（趋势或分类对比）。

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
      "views": [
        {{"viewId": "视图ID", "name": "视图名", "viewType": 0}}
      ],
      "xaxes": {{
        "controlId": "字段ID或ctime",
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
""".strip()


def generate_with_retry(client: genai.Client, model: str, prompt: str, retries: int = 4) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
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


def validate_plan(raw: dict, worksheets_by_id: Dict[str, dict]) -> List[dict]:
    charts = raw.get("charts", [])
    if not isinstance(charts, list) or len(charts) == 0:
        raise ValueError("Gemini 未返回 charts 数组")
    if len(charts) != 3:
        raise ValueError(f"期望 3 个图表，实际返回 {len(charts)} 个")

    validated = []
    for i, chart in enumerate(charts):
        if not isinstance(chart, dict):
            raise ValueError(f"图表 {i+1} 格式错误")
        name = str(chart.get("name", "")).strip()
        if not name:
            raise ValueError(f"图表 {i+1} 缺少 name")
        report_type = int(chart.get("reportType", 0) or 0)
        if report_type not in {1, 2, 3, 4}:
            raise ValueError(f"图表 {i+1} reportType 非法: {report_type}")
        worksheet_id = str(chart.get("worksheetId", "")).strip()
        if worksheet_id not in worksheets_by_id:
            raise ValueError(f"图表 {i+1} worksheetId 不存在: {worksheet_id}")
        xaxes = chart.get("xaxes", {})
        if not isinstance(xaxes, dict) or not str(xaxes.get("controlId", "")).strip():
            raise ValueError(f"图表 {i+1} xaxes 缺少 controlId")
        yaxis_list = chart.get("yaxisList", [])
        if not isinstance(yaxis_list, list) or len(yaxis_list) == 0:
            raise ValueError(f"图表 {i+1} yaxisList 为空")
        validated.append(chart)
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
你是企业数据分析助手。请为以下应用设计 3 个业务统计图，输出严格 JSON，不要 markdown，不要任何解释。

应用信息：
- appId: {app_id}
- appName: {app_name}
- {context}

只能使用以下系统字段（无法获取自定义字段）：
- ctime：创建时间，controlType=16（用于时间趋势）
- utime：最后修改时间，controlType=16
- record_count：记录数量统计，controlType=10000000

设计要求：
1. 共 3 个图表，各图表侧重不同时间维度（日/月/季）。
2. 至少 1 个折线图（reportType=2），1 个柱状图（reportType=1），1 个柱状图或饼图（reportType=3）。
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

注意：particleSizeType：1=按月，2=按季度，3=按年，4=按天。3 个图表使用不同 particleSizeType。
""".strip()


def validate_plan_relaxed(raw: dict) -> List[dict]:
    """宽松验证：只检查必要结构，不验证 worksheetId。"""
    charts = raw.get("charts", [])
    if not isinstance(charts, list) or len(charts) == 0:
        raise ValueError("Gemini 未返回 charts 数组")
    if len(charts) != 3:
        raise ValueError(f"期望 3 个图表，实际返回 {len(charts)} 个")
    validated = []
    for i, chart in enumerate(charts):
        if not isinstance(chart, dict):
            raise ValueError(f"图表 {i+1} 格式错误")
        if not str(chart.get("name", "")).strip():
            raise ValueError(f"图表 {i+1} 缺少 name")
        if int(chart.get("reportType", 0) or 0) not in {1, 2, 3, 4}:
            raise ValueError(f"图表 {i+1} reportType 非法")
        xaxes = chart.get("xaxes", {})
        if not isinstance(xaxes, dict) or not str(xaxes.get("controlId", "")).strip():
            raise ValueError(f"图表 {i+1} xaxes 缺少 controlId")
        if not isinstance(chart.get("yaxisList", []), list) or not chart.get("yaxisList"):
            raise ValueError(f"图表 {i+1} yaxisList 为空")
        validated.append(chart)
    return validated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="调用 Gemini 为应用规划 3 个业务统计图（只需 auth_config.py）",
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
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    parser.add_argument("--gemini-retries", type=int, default=4, help="Gemini 最大重试次数")
    args = parser.parse_args()

    app_id = args.app_id.strip()
    app_name = args.app_name.strip() or app_id
    web_auth = load_web_auth(Path(args.auth_config).expanduser().resolve())
    api_key = load_gemini_api_key(Path(args.config).expanduser().resolve())

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
        print(f"[模式] 仅系统字段模式（未提供 --worksheet-ids）")
        print(f"  使用字段: ctime（创建时间）+ record_count（记录数）")
        print(f"  如需更丰富的图表，请添加 --worksheet-ids（从应用 URL 的路径中复制工作表 ID）")
        worksheets_info = []
        worksheets_by_id: Dict[str, dict] = {SYSTEM_ONLY_WORKSHEET_ID: {"worksheetId": SYSTEM_ONLY_WORKSHEET_ID}}
    else:
        print(f"[1/3] 拉取工作表字段与视图（{len(ws_ids)} 张）...")
        worksheets_info = []
        worksheets_by_id = {}
        # 解析 UUID 格式 appId（用于获取视图，GetWorksheetViews 需要 UUID appId）
        app_uuid = resolve_app_uuid_from_ws(ws_ids[0], web_auth) if ws_ids else ""
        for ws_id in ws_ids:
            payload = fetch_worksheet_controls(ws_id, web_auth)
            ws_name = str(payload.get("worksheetName", ws_id)).strip()
            controls = simplify_controls(payload.get("controls", []))
            # 优先从 GetWorksheetViews 获取真实视图（需 UUID appId）
            views = fetch_worksheet_views(ws_id, app_uuid, web_auth)
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

    # Gemini 规划
    step = "1/1" if use_system_fields_only else "3/3"
    print(f"[{step}] 调用 Gemini 规划图表（模型: {args.model}）...")
    client = genai.Client(api_key=api_key)

    if use_system_fields_only:
        prompt = build_prompt_system_only(app_id, app_name, preset_views)
        validate_fn = lambda raw, _: validate_plan_relaxed(raw)
    else:
        prompt = build_prompt(app_id, app_name, worksheets_info)
        validate_fn = validate_plan

    validated: Optional[List[dict]] = None
    last_error: Optional[str] = None
    for val_attempt in range(1, 4):
        p = prompt
        if last_error:
            p = prompt + f"\n\n# 上次验证失败（第 {val_attempt - 1} 次）\n错误信息：{last_error}\n请修正后重新输出。"
        response = generate_with_retry(client, args.model, p, args.gemini_retries)
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
