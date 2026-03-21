#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调用 Gemini 为指定应用规划多个自定义分析页（Page）。

步骤：
1. GetApp 获取应用结构（工作表列表、appSectionId、projectId）
2. GetWorksheetControls 获取各工作表字段信息
3. 调用 Gemini 规划 3-5 个业务分析页
4. 输出 page_plan JSON（含 appSectionId / projectId 供 create 脚本使用）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import auth_retry
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
PAGE_PLAN_DIR = OUTPUT_ROOT / "page_plans"
LOG_DIR = BASE_DIR / "data" / "logs"
GEMINI_CONFIG_PATH = AI_CONFIG_PATH
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

GET_APP_URL = "https://www.mingdao.com/api/HomeApp/GetApp"
GET_WORKSHEET_INFO_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetInfo"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"

# 图标候选列表（仅使用明道云 customIcon CDN 中存在的图标）
ICON_CANDIDATES = [
    "dashboard",    # 仪表盘/概览（已验证可用）
]

# 颜色池（Material Design 主色调）
COLOR_POOL = [
    "#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336",
    "#00BCD4", "#795548", "#607D8B", "#E91E63", "#3F51B5",
]


# ---------------------------------------------------------------------------
# 日志工具
# ---------------------------------------------------------------------------

class Logger:
    def __init__(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._f = log_path.open("a", encoding="utf-8")
        self._path = log_path
        self._print(f"=== plan_pages_gemini 启动 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    def log(self, msg: str) -> None:
        self._print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _print(self, msg: str) -> None:
        print(msg)
        self._f.write(msg + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()

    @property
    def path(self) -> Path:
        return self._path


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


# ---------------------------------------------------------------------------
# 数据拉取
# ---------------------------------------------------------------------------

def resolve_app_uuid(ws_id: str, auth_config_path: Path) -> tuple[str, str, str, str]:
    """通过 worksheetId 查询 UUID 格式的 appId、appName、appSectionId、projectId。"""
    resp = auth_retry.hap_web_post(GET_WORKSHEET_INFO_URL, auth_config_path,
                                   referer="https://www.mingdao.com/",
                                   json={"worksheetId": ws_id}, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    app_uuid = str(data.get("appId", "")).strip()
    app_name = str(data.get("appName", "")).strip()
    app_section_id = str(data.get("groupId", "")).strip()
    project_id = str(data.get("projectId", "")).strip()
    if not app_uuid:
        raise RuntimeError(f"GetWorksheetInfo 未返回 appId，worksheetId={ws_id}")
    return app_uuid, app_name, app_section_id, project_id


def is_uuid(value: str) -> bool:
    """判断是否为 UUID 格式（含连字符）。"""
    import re
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                         value.lower()))


def fetch_app_info(app_id: str, auth_config_path: Path) -> dict:
    """获取应用结构：projectId, appSectionId, 工作表列表。

    app_id 可以是 UUID 格式（直接调用 GetApp）或 hex 工作表 ID（先解析出 UUID）。
    """
    # 若不是 UUID 格式，先通过 GetWorksheetInfo 解析真实 appId
    resolved_app_uuid = app_id
    if not is_uuid(app_id):
        resolved_app_uuid, _name, _section, _proj = resolve_app_uuid(app_id, auth_config_path)

    resp = auth_retry.hap_web_post(GET_APP_URL, auth_config_path,
                                   referer="https://www.mingdao.com/",
                                   json={"appId": resolved_app_uuid, "getSection": True}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    app_data = data.get("data", {})

    project_id = str(app_data.get("projectId", "")).strip()
    app_name = str(app_data.get("name", "")).strip() or app_id

    # 取第一个 section 的 appSectionId
    sections = app_data.get("sections", [])
    app_section_id = ""
    worksheets = []
    if sections:
        app_section_id = str(sections[0].get("appSectionId", "")).strip()
        for section in sections:
            for ws in section.get("workSheetInfo", []):
                ws_type = int(ws.get("type", 0) or 0)
                ws_id = str(ws.get("workSheetId", "")).strip()
                if ws_id and ws_type == 0:  # type=0 是普通工作表，type=1 是 page
                    worksheets.append({
                        "worksheetId": ws_id,
                        "worksheetName": str(ws.get("workSheetName", "")).strip(),
                    })

    return {
        "appId": resolved_app_uuid,   # 始终返回 UUID 格式 appId
        "appName": app_name,
        "projectId": project_id,
        "appSectionId": app_section_id,
        "worksheets": worksheets,
    }


def fetch_worksheet_controls(worksheet_id: str, auth_config_path: Path) -> dict:
    resp = auth_retry.hap_web_post(GET_CONTROLS_URL, auth_config_path,
                                   referer="https://www.mingdao.com/",
                                   json={"worksheetId": worksheet_id}, timeout=30)
    data = resp.json()
    wrapped = data.get("data", {})
    if isinstance(wrapped, dict) and isinstance(wrapped.get("data"), dict):
        return wrapped["data"]
    elif isinstance(wrapped, dict):
        return wrapped
    return {}


def simplify_controls(controls: list) -> List[dict]:
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
                    opts.append(str(o.get("value", "")))
            entry["options"] = opts[:10]
        simplified.append(entry)
    return simplified


# ---------------------------------------------------------------------------
# Gemini 调用
# ---------------------------------------------------------------------------

def build_prompt(app_id: str, app_name: str, worksheets_detail: List[dict],
                 icon_candidates: List[str], color_pool: List[str]) -> str:
    ws_json = json.dumps(worksheets_detail, ensure_ascii=False, indent=2)
    colors_str = "、".join(color_pool[:6])
    return f"""
你是企业数据分析架构师。请根据下面的应用结构，为该应用规划 3~5 个自定义数据分析页（Page）。
每个 Page 聚焦一个独立的业务分析主题，供经营层快速查看数据。

应用信息：
- appId: {app_id}
- appName: {app_name}

工作表与字段信息（含字段类型和选项值）：
{ws_json}

设计要求：
1. 规划恰好 2 个 Page，每个 Page 聚焦不同业务主题（选取最有价值的 2 个业务维度）。
2. 每个 Page 的 worksheetIds 列出该 Page 需要统计分析的工作表 ID（从上面的工作表中选择）。
3. icon 统一使用：dashboard
4. iconColor 从以下选择（两个 Page 颜色不重复）：{colors_str}
5. desc 简短说明该 Page 的业务分析价值（20 字以内）。
6. 各 Page 名称简洁有业务含义（10 字以内）。
7. 每个 Page 必须关联至少 1 个工作表。

输出严格 JSON，不要 markdown，不要任何解释：
{{
  "appId": "{app_id}",
  "appName": "{app_name}",
  "pages": [
    {{
      "name": "Page 名称",
      "icon": "dashboard",
      "iconColor": "#2196F3",
      "desc": "简短业务描述",
      "worksheetIds": ["工作表ID1", "工作表ID2"],
      "worksheetNames": ["工作表名称1", "工作表名称2"]
    }}
  ]
}}
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


def validate_page_plan(raw: dict, valid_ws_ids: set) -> List[dict]:
    pages = raw.get("pages", [])
    if not isinstance(pages, list) or len(pages) == 0:
        raise ValueError("Gemini 未返回 pages 数组")
    if len(pages) != 2:
        raise ValueError(f"期望恰好 2 个 Page，实际返回 {len(pages)} 个")

    validated = []
    for i, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ValueError(f"Page {i+1} 格式错误")
        name = str(page.get("name", "")).strip()
        if not name:
            raise ValueError(f"Page {i+1} 缺少 name")
        ws_ids = page.get("worksheetIds", [])
        if not isinstance(ws_ids, list) or len(ws_ids) == 0:
            raise ValueError(f"Page {i+1} 缺少 worksheetIds")
        # 过滤掉不存在的工作表 ID
        valid_ids = [wid for wid in ws_ids if str(wid).strip() in valid_ws_ids]
        if not valid_ids:
            print(f"[警告] Page {i+1} 的 worksheetIds 均不在应用工作表中，已跳过: {ws_ids}")
            continue
        page["worksheetIds"] = valid_ids
        page["icon"] = "dashboard"   # 只用已验证的图标
        page["iconColor"] = str(page.get("iconColor", "#2196F3")).strip() or "#2196F3"
        page["iconUrl"] = "https://fp1.mingdaoyun.cn/customIcon/dashboard.svg"
        validated.append(page)
    return validated


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="调用 AI 为应用规划自定义分析页")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="AI 配置 JSON 路径")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径（可选）")
    parser.add_argument("--gemini-retries", type=int, default=4, help="AI 最大重试次数")
    args = parser.parse_args()

    app_id = args.app_id.strip()
    ts = now_ts()

    # 初始化日志
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = Logger(LOG_DIR / f"plan_pages_{app_id}_{ts}.log")

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    # 结构化 JSON 输出，使用极速档
    ai_config = load_ai_config(Path(args.config).expanduser().resolve(), tier="fast")
    model_name = ai_config["model"]

    # Step 1: 获取应用结构
    log.log(f"[1/3] 拉取应用结构: {app_id}")
    app_info = fetch_app_info(app_id, auth_config_path)
    app_name = app_info["appName"]
    log.log(f"  应用名称: {app_name}")
    log.log(f"  projectId: {app_info['projectId']}")
    log.log(f"  appSectionId: {app_info['appSectionId']}")
    log.log(f"  工作表数量: {len(app_info['worksheets'])}")
    for ws in app_info["worksheets"]:
        log.log(f"    - {ws['worksheetName']} ({ws['worksheetId']})")

    if not app_info["worksheets"]:
        log.log("ERROR: 未发现工作表，无法规划 Page")
        sys.exit(1)

    # Step 2: 拉取工作表字段
    log.log("\n[2/3] 拉取工作表字段信息...")
    worksheets_detail = []
    valid_ws_ids: set = set()
    for ws in app_info["worksheets"]:
        ws_id = ws["worksheetId"]
        ws_name = ws["worksheetName"]
        try:
            payload = fetch_worksheet_controls(ws_id, auth_config_path)
            fields = simplify_controls(payload.get("controls", []))
            log.log(f"  - {ws_name} ({ws_id}): {len(fields)} 个字段")
            worksheets_detail.append({
                "worksheetId": ws_id,
                "worksheetName": ws_name,
                "fields": fields,
            })
            valid_ws_ids.add(ws_id)
        except Exception as exc:
            log.log(f"  警告: 拉取 {ws_name} ({ws_id}) 失败: {exc}")
            # 仍然加入有效集合，让 Gemini 知道这个工作表存在
            worksheets_detail.append({
                "worksheetId": ws_id,
                "worksheetName": ws_name,
                "fields": [],
            })
            valid_ws_ids.add(ws_id)

    # Step 3: Gemini 规划
    log.log(f"\n[3/3] 调用 AI 规划 Page（模型: {model_name}）...")
    client = get_ai_client(ai_config)
    prompt = build_prompt(app_id, app_name, worksheets_detail, ICON_CANDIDATES, COLOR_POOL)

    validated: Optional[List[dict]] = None
    last_error: Optional[str] = None
    for attempt in range(1, 4):
        p = prompt
        if last_error:
            p = prompt + f"\n\n# 上次验证失败（第 {attempt-1} 次）\n错误：{last_error}\n请修正后重新输出。"
        response = generate_with_retry(client, model_name, p, ai_config, args.gemini_retries)
        raw = extract_json_object(response.text or "")
        try:
            validated = validate_page_plan(raw, valid_ws_ids)
            break
        except Exception as exc:
            last_error = str(exc)
            log.log(f"  验证失败（{attempt}/3）: {exc}")
            if attempt >= 3:
                raise

    assert validated is not None

    plan = {
        "schemaVersion": "page_plan_v1",
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "appId": app_info["appId"],          # 始终 UUID 格式，供 create_pages 使用
        "appIdInput": app_id,                # 原始输入 ID（可能是 worksheetId）
        "appName": app_name,
        "projectId": app_info["projectId"],
        "appSectionId": app_info["appSectionId"],
        "logFile": str(log.path),
        "pages": validated,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        PAGE_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        output_path = (PAGE_PLAN_DIR / f"page_plan_{app_id}_{ts}.json").resolve()
        write_json(PAGE_PLAN_DIR / "page_plan_latest.json", plan)

    write_json(output_path, plan)

    log.log(f"\n规划完成，共 {len(validated)} 个 Page：")
    for i, p in enumerate(validated, 1):
        ws_names = "、".join(p.get("worksheetNames", p.get("worksheetIds", [])))
        log.log(f"  {i}. [{p['icon']}] {p['name']} — {p.get('desc', '')}（工作表: {ws_names}）")
    log.log(f"\n输出文件: {output_path}")
    log.log(f"日志文件: {log.path}")
    log.close()

    print(f"\n规划完成，共 {len(validated)} 个 Page")
    print(f"输出文件: {output_path}")


if __name__ == "__main__":
    main()
