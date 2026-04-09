#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提前创建 Pages（Wave 2.5）—— 在工作表实际创建之前，根据工作表规划创建自定义分析页。

步骤：
1. 从 worksheet_plan.json 提取工作表名称列表
2. 调用 GetApp 获取应用元数据（appSectionId, projectId）
3. 调用 AI 规划 Pages（build_pages_prompt + validate_pages_plan）
4. 调用 AddWorkSheet API 创建 Page
5. 调用 savePage 初始化每个 Page
6. 输出 page_registry.json
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import auth_retry
import requests
from ai_utils import (
    AI_CONFIG_PATH,
    create_generation_config,
    get_ai_client,
    load_ai_config,
    parse_ai_json,
)
from i18n import dashboard_section_name, get_runtime_language, normalize_language
from planning.page_planner import build_pages_prompt, validate_pages_plan
from utils import load_json, log_summary, now_ts, write_json

BASE_DIR = Path(__file__).resolve().parents[3]
APP_AUTH_DIR = BASE_DIR / "data" / "outputs" / "app_authorizations"

# API 端点
V3_APP_URL = "https://api.mingdao.com/v3/app"
GET_APP_URL = "https://www.mingdao.com/api/HomeApp/GetApp"
GET_WORKSHEET_INFO_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetInfo"
ADD_WORKSHEET_URL = "https://www.mingdao.com/api/AppManagement/AddWorkSheet"
SAVE_PAGE_URL = "https://api.mingdao.com/report/custom/savePage"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def is_uuid(value: str) -> bool:
    """判断是否为 UUID 格式（含连字符）。"""
    return bool(re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        value.lower(),
    ))


def resolve_app_uuid(ws_id: str, auth_config_path: Path) -> str:
    """通过 worksheetId 查询 UUID 格式的 appId。"""
    resp = auth_retry.hap_web_post(
        GET_WORKSHEET_INFO_URL, auth_config_path,
        referer="https://www.mingdao.com/",
        json={"worksheetId": ws_id}, timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    app_uuid = str(data.get("appId", "")).strip()
    if not app_uuid:
        raise RuntimeError(f"GetWorksheetInfo 未返回 appId，worksheetId={ws_id}")
    return app_uuid


def fetch_app_info(app_id: str, auth_config_path: Path, language: str = "zh") -> Dict[str, Any]:
    """获取应用元数据：projectId, appSectionId, appName。

    app_id 可以是 UUID 格式（直接调用 GetApp）或 hex 工作表 ID（先解析出 UUID）。
    """
    resolved_app_uuid = app_id
    if not is_uuid(app_id):
        resolved_app_uuid = resolve_app_uuid(app_id, auth_config_path)

    resp = auth_retry.hap_web_post(
        GET_APP_URL, auth_config_path,
        referer="https://www.mingdao.com/",
        json={"appId": resolved_app_uuid, "getSection": True}, timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    app_data = data.get("data", {})

    project_id = str(app_data.get("projectId", "")).strip()
    app_name = str(app_data.get("name", "")).strip() or app_id

    dashboard_name = dashboard_section_name(language)
    # 优先取 dashboard 分组，兜底取"数据分析"相关，再兜底取第一个分组
    sections = app_data.get("sections", [])
    app_section_id = ""
    if sections:
        dashboard_section = next(
            (s for s in sections if s.get("name") == dashboard_name), None
        ) or next(
            (s for s in sections
             if "数据" in str(s.get("name", "")) or "分析" in str(s.get("name", ""))),
            None,
        )
        if dashboard_section:
            app_section_id = str(dashboard_section.get("appSectionId", "")).strip()
        else:
            app_section_id = str(sections[0].get("appSectionId", "")).strip()

    return {
        "appId": resolved_app_uuid,
        "appName": app_name,
        "projectId": project_id,
        "appSectionId": app_section_id,
    }


def resolve_app_api_auth(app_id: str) -> tuple[str, str]:
    """从 app_authorize_*.json 中解析指定 appId 的 v3 凭证。"""
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in data.get("data") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("appId", "")).strip() != app_id:
                continue
            app_key = str(row.get("appKey", "")).strip()
            sign = str(row.get("sign", "")).strip()
            if app_key and sign:
                return app_key, sign
    raise FileNotFoundError(f"未找到 appId={app_id} 的授权信息（目录: {APP_AUTH_DIR}）")


def fetch_existing_pages_v3(app_id: str) -> Dict[str, str]:
    """通过 v3/app 查询现有自定义页，并返回 pageName -> pageId。

    真实链路中，v3/app.sections[].items 里 type=1 表示自定义页面。
    """
    app_key, sign = resolve_app_api_auth(app_id)
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(V3_APP_URL, headers=headers, timeout=30, proxies={})
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"v3/app 查询失败: {body}")

    pages: Dict[str, str] = {}

    def walk(section: dict) -> None:
        for item in section.get("items", []) or []:
            item_type = int(item.get("type", 0) or 0)
            if item_type != 1:
                continue
            page_name = str(item.get("name", "") or item.get("workSheetName", "")).strip()
            page_id = str(item.get("id", "") or item.get("pageId", "") or item.get("workSheetId", "")).strip()
            if page_name and page_id and page_name not in pages:
                pages[page_name] = page_id
        for child in section.get("childSections", []) or []:
            walk(child)

    for section in body.get("data", {}).get("sections", []) or []:
        walk(section)
    return pages


# ---------------------------------------------------------------------------
# 工作表名称提取
# ---------------------------------------------------------------------------

def extract_worksheet_names(worksheet_plan_path: Path) -> List[str]:
    """从 worksheet_plan.json 中提取工作表名称列表。"""
    plan = load_json(worksheet_plan_path)

    # 支持两种结构：
    # 1. {"worksheets": [{"name": "xxx"}, ...]}
    # 2. {"worksheets": [{"worksheetName": "xxx"}, ...]}
    worksheets = plan.get("worksheets", [])
    names: List[str] = []
    for ws in worksheets:
        if isinstance(ws, dict):
            name = str(ws.get("name") or ws.get("worksheetName") or "").strip()
            if name:
                names.append(name)
        elif isinstance(ws, str):
            name = ws.strip()
            if name:
                names.append(name)
    if not names:
        raise ValueError(f"worksheet_plan.json 中未找到工作表名称: {worksheet_plan_path}")
    return names


# ---------------------------------------------------------------------------
# AI 调用
# ---------------------------------------------------------------------------

def plan_pages_with_ai(
    app_name: str,
    worksheet_names: List[str],
    ai_config: Dict[str, str],
    language: str = "zh",
    retries: int = 3,
) -> List[dict]:
    """调用 AI 规划 Pages，带重试和校验。"""
    client = get_ai_client(ai_config)
    model = ai_config["model"]
    prompt = build_pages_prompt(app_name, worksheet_names, language=language)
    valid_ws_names = set(worksheet_names)

    last_error: Optional[str] = None
    for attempt in range(1, retries + 1):
        p = prompt
        if last_error:
            p += f"\n\n# 上次验证失败（第 {attempt-1} 次）\n错误：{last_error}\n请修正后重新输出。"

        # 带指数退避重试的 AI 调用
        ai_exc: Optional[Exception] = None
        for ai_attempt in range(1, 5):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=p,
                    config=create_generation_config(
                        ai_config,
                        response_mime_type="application/json",
                        temperature=0.3,
                    ),
                )
                ai_exc = None
                break
            except Exception as exc:
                ai_exc = exc
                if ai_attempt >= 4:
                    break
                wait = min(16, 2 ** (ai_attempt - 1))
                print(f"  AI 调用失败，{wait}s 后重试（{ai_attempt}/4）: {exc}")
                time.sleep(wait)
        if ai_exc is not None:
            raise ai_exc

        raw = parse_ai_json(response.text or "")
        try:
            validated = validate_pages_plan(raw, valid_ws_names)
            if validated:
                return validated
            last_error = "validate_pages_plan 返回空列表"
        except Exception as exc:
            last_error = str(exc)
            print(f"  Pages 规划校验失败（{attempt}/{retries}）: {exc}")
            if attempt >= retries:
                raise

    raise RuntimeError(f"Pages 规划多次校验失败: {last_error}")


# ---------------------------------------------------------------------------
# API 调用：创建 Page
# ---------------------------------------------------------------------------

def create_page(
    app_id: str,
    app_section_id: str,
    project_id: str,
    page_name: str,
    icon: str,
    icon_color: str,
    auth_config_path: Path,
) -> str:
    """调用 AddWorkSheet 创建自定义 Page，返回 pageId。"""
    icon_url = f"https://fp1.mingdaoyun.cn/customIcon/{icon}.svg"
    body = {
        "appId": app_id,
        "appSectionId": app_section_id,
        "name": page_name,
        "remark": "",
        "iconColor": icon_color,
        "projectId": project_id,
        "icon": icon,
        "iconUrl": icon_url,
        "type": 1,        # 1 = 自定义页
        "createType": 0,
    }
    resp = auth_retry.hap_web_post(ADD_WORKSHEET_URL, auth_config_path, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    is_ok = data.get("state") == 1 or data.get("status") == 1
    if not is_ok:
        raise RuntimeError(f"AddWorkSheet 失败: {data}")
    page_id = str(data.get("data", {}).get("pageId", "")).strip()
    if not page_id:
        raise RuntimeError(f"AddWorkSheet 未返回 pageId: {data}")
    return page_id


def initialize_page(page_id: str, auth_config_path: Path) -> None:
    """用 savePage（version=0, components=[]）初始化空白 Page。"""
    body = {
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
    resp = auth_retry.hap_web_post(SAVE_PAGE_URL, auth_config_path, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    is_ok = data.get("status") == 1 or data.get("success") is True
    if not is_ok:
        raise RuntimeError(f"初始化 Page 失败: {data}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="提前创建 Pages（根据工作表规划，在工作表创建之前）",
    )
    parser.add_argument("--app-id", required=True, help="应用 ID（UUID 或 hex worksheetId）")
    parser.add_argument("--worksheet-plan-json", required=True, help="worksheet_plan.json 路径")
    parser.add_argument("--auth-config", required=True, help="auth_config.py 路径")
    parser.add_argument("--output", default="", help="输出 page_registry.json 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅规划，不实际创建 Page")
    parser.add_argument("--language", default="", help="规划语言（zh/en，默认读取 HAP_LANGUAGE）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--skip-existing", dest="skip_existing", action="store_true",
                       help="若页面已存在则跳过 AddWorkSheet（默认）")
    group.add_argument("--no-skip-existing", dest="skip_existing", action="store_false",
                       help="即使页面已存在也继续调用 AddWorkSheet")
    parser.set_defaults(skip_existing=True)
    args = parser.parse_args()

    app_id = args.app_id.strip()
    lang = normalize_language(args.language or get_runtime_language())
    worksheet_plan_path = Path(args.worksheet_plan_json).expanduser().resolve()
    auth_config_path = Path(args.auth_config).expanduser().resolve()

    if not worksheet_plan_path.exists():
        print(f"✗ worksheet_plan.json 不存在: {worksheet_plan_path}")
        sys.exit(1)

    # Step 1: 提取工作表名称
    print(f"[1/4] 提取工作表名称: {worksheet_plan_path}")
    worksheet_names = extract_worksheet_names(worksheet_plan_path)
    print(f"  找到 {len(worksheet_names)} 个工作表: {', '.join(worksheet_names)}")

    # Step 2: 获取应用元数据
    print(f"[2/4] 获取应用元数据: {app_id}")
    app_info = fetch_app_info(app_id, auth_config_path, language=lang)
    app_name = app_info["appName"]
    project_id = app_info["projectId"]
    app_section_id = app_info["appSectionId"]
    resolved_app_id = app_info["appId"]
    print(f"  应用名称: {app_name}")
    print(f"  projectId: {project_id}")
    print(f"  appSectionId: {app_section_id}")

    if not project_id or not app_section_id:
        print("✗ 缺少 projectId 或 appSectionId，无法创建 Page")
        sys.exit(1)

    existing_pages: Dict[str, str] = {}
    if args.skip_existing and not args.dry_run:
        print(f"[2.5/4] 通过 v3/app 查询已有 Pages...")
        existing_pages = fetch_existing_pages_v3(resolved_app_id)
        print(f"  已发现 {len(existing_pages)} 个已有 Page")

    # Step 3: AI 规划 Pages
    print(f"[3/4] AI 规划 Pages...")
    ai_config = load_ai_config()
    print(f"  模型: {ai_config['model']}")
    planned_pages = plan_pages_with_ai(app_name, worksheet_names, ai_config, language=lang)
    print(f"  规划了 {len(planned_pages)} 个 Page:")
    for i, p in enumerate(planned_pages, 1):
        ws_str = "、".join(p.get("worksheetNames", []))
        print(f"    {i}. {p['name']} — {p.get('desc', '')}（工作表: {ws_str}）")

    # Step 4: 创建 Pages
    print(f"[4/4] 创建 Pages（dry-run={args.dry_run}）")
    pages_result: List[dict] = []

    for i, page in enumerate(planned_pages, 1):
        page_name = str(page.get("name", f"Page{i}")).strip()
        icon = str(page.get("icon", "sys_dashboard")).strip()
        icon_color = str(page.get("iconColor", "#2196F3")).strip()
        desc = str(page.get("desc", "")).strip()
        ws_names = page.get("worksheetNames", [])

        page_entry: Dict[str, Any] = {
            "name": page_name,
            "desc": desc,
            "icon": icon,
            "iconColor": icon_color,
            "worksheetNames": ws_names,
            "components": [],
            "version": 1,
        }

        if args.dry_run:
            page_entry["pageId"] = f"dry-run-{i}"
            print(f"  [dry-run] {i}. {page_name}")
            pages_result.append(page_entry)
            continue

        existing_page_id = existing_pages.get(page_name, "")
        if existing_page_id and args.skip_existing:
            page_entry["pageId"] = existing_page_id
            page_entry["skipped"] = True
            page_entry["status"] = "skipped_existing"
            print(f"  [跳过] 页面「{page_name}」已存在，pageId={existing_page_id}")
            log_summary(f"[跳过] 页面「{page_name}」已存在")
            pages_result.append(page_entry)
            continue

        # 创建 Page
        try:
            print(f"  [{i}/{len(planned_pages)}] 创建 Page: {page_name}...")
            page_id = create_page(
                resolved_app_id, app_section_id, project_id,
                page_name, icon, icon_color, auth_config_path,
            )
            page_entry["pageId"] = page_id
            page_entry["skipped"] = False
            print(f"    ✓ pageId={page_id}")
            log_summary(f"✓ Page「{page_name}」已创建")
        except Exception as exc:
            print(f"    ✗ 创建失败: {exc}")
            page_entry["pageId"] = ""
            page_entry["error"] = str(exc)
            pages_result.append(page_entry)
            continue

        # 初始化 Page
        try:
            initialize_page(page_id, auth_config_path)
            print(f"    ✓ 初始化完成")
        except Exception as exc:
            print(f"    ⚠ 初始化失败（非致命）: {exc}")

        pages_result.append(page_entry)

    # 输出 page_registry.json
    registry = {
        "appId": resolved_app_id,
        "appName": app_name,
        "projectId": project_id,
        "appSectionId": app_section_id,
        "pages": pages_result,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = (BASE_DIR / "data" / "outputs" / "page_registry.json").resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, registry)

    success_count = sum(1 for p in pages_result if p.get("pageId") and not p.get("error"))
    print(f"\n完成：{success_count}/{len(planned_pages)} 个 Page 创建成功")
    print(f"RESULT_JSON: {output_path}")


if __name__ == "__main__":
    main()
