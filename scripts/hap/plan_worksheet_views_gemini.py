#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按应用/工作表结构规划视图：
1) 选择应用（y=全部；序号=部分；其他取消）
2) 拉取每张工作表字段
3) 调用 Gemini 规划可创建视图与参数
4) 输出为 JSON
"""

import argparse
import importlib.util
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
VIEW_PLAN_DIR = OUTPUT_ROOT / "view_plans"
GEMINI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
DEFAULT_MODEL = "gemini-2.5-pro"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
ALLOWED_VIEW_TYPES = {"0", "1", "3", "4"}


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_selection(text: str, max_index: int) -> List[int]:
    parts = [p for p in re.split(r"[^\d]+", text) if p]
    if not parts:
        return []
    out: List[int] = []
    for p in parts:
        idx = int(p)
        if idx < 1 or idx > max_index:
            raise ValueError(f"序号超出范围: {idx}（有效范围 1-{max_index}）")
        if idx not in out:
            out.append(idx)
    return out


def choose_indexes(prompt: str, items_count: int) -> Optional[List[int]]:
    choice = input(prompt).strip()
    if choice.lower() == "y":
        return list(range(1, items_count + 1))
    try:
        picked = parse_selection(choice, items_count)
    except ValueError:
        return None
    if not picked:
        return None
    return picked


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "app"


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


def extract_json(text: str) -> dict:
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
    raise ValueError(f"Gemini 未返回可解析 JSON:\n{text}")


def load_app_auth_rows() -> List[dict]:
    rows: List[dict] = []
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload = data.get("data")
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            app_id = str(row.get("appId", "")).strip()
            app_key = str(row.get("appKey", "")).strip()
            sign = str(row.get("sign", "")).strip()
            if not app_id or not app_key or not sign:
                continue
            x = dict(row)
            x["_auth_path"] = str(path.resolve())
            rows.append(x)
    if not rows:
        raise FileNotFoundError(f"未找到可用授权文件：{APP_AUTH_DIR}")
    dedup: Dict[str, dict] = {}
    for r in rows:
        app_id = str(r.get("appId", "")).strip()
        if app_id not in dedup:
            dedup[app_id] = r
    return list(dedup.values())


def fetch_app_meta(app_key: str, sign: str) -> dict:
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json, text/plain, */*"}
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app = data.get("data", {})
    if not isinstance(app, dict):
        raise RuntimeError(f"应用信息格式错误: {data}")
    return app


def fetch_worksheets(app_key: str, sign: str) -> List[dict]:
    app_meta = fetch_app_meta(app_key, sign)
    worksheets: List[dict] = []

    def walk_sections(section: dict):
        section_id = str(section.get("id", ""))
        section_name = str(section.get("name", ""))
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append(
                    {
                        "workSheetId": str(item.get("id", "")),
                        "workSheetName": str(item.get("name", "")),
                        "appSectionId": section_id,
                        "appSectionName": section_name,
                    }
                )
        for child in section.get("childSections", []) or []:
            walk_sections(child)

    for sec in app_meta.get("sections", []) or []:
        walk_sections(sec)
    return worksheets


def fetch_controls(worksheet_id: str, web_auth: tuple[str, str, str]) -> dict:
    account_id, authorization, cookie = web_auth
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.mingdao.com",
        "Referer": f"https://www.mingdao.com/worksheet/field/edit?sourceId={worksheet_id}",
    }
    resp = requests.post(GET_CONTROLS_URL, headers=headers, json={"worksheetId": worksheet_id}, timeout=30)
    data = resp.json()
    wrapped = data.get("data", {})
    if isinstance(wrapped, dict) and isinstance(wrapped.get("data"), dict):
        if int(wrapped.get("code", 0) or 0) != 1:
            raise RuntimeError(f"获取工作表控件失败: worksheetId={worksheet_id}, resp={data}")
        payload = wrapped["data"]
    else:
        payload = data.get("data", {})
        if not isinstance(payload, dict):
            raise RuntimeError(f"获取工作表控件失败: worksheetId={worksheet_id}, resp={data}")
    controls = payload.get("controls", [])
    if not isinstance(controls, list):
        raise RuntimeError(f"工作表控件格式错误: worksheetId={worksheet_id}, resp={data}")
    return {
        "worksheetId": worksheet_id,
        "worksheetName": str(payload.get("worksheetName", "") or ""),
        "fields": controls,
    }


def simplify_field(field: dict) -> dict:
    options = []
    raw_opts = field.get("options")
    if isinstance(raw_opts, list):
        for o in raw_opts:
            if not isinstance(o, dict):
                continue
            if o.get("isDeleted", False):
                continue
            options.append(
                {
                    "key": str(o.get("key", "")).strip(),
                    "value": str(o.get("value", "")).strip(),
                }
            )
            if len(options) >= 20:
                break
    field_id = str(field.get("id", "") or field.get("controlId", "")).strip()
    field_name = str(field.get("name", "") or field.get("controlName", "")).strip()
    is_system = bool(field.get("isSystemControl", False))
    if not is_system:
        try:
            is_system = int(field.get("attribute", 0) or 0) == 1
        except Exception:
            is_system = False
    return {
        "id": field_id,
        "name": field_name,
        "type": str(field.get("type", "")).strip(),
        "subType": int(field.get("subType", 0) or 0),
        "isTitle": bool(field.get("isTitle", False)),
        "required": bool(field.get("required", False)),
        "isSystem": is_system,
        "options": options,
    }


def default_display_controls(fields: List[dict]) -> List[str]:
    ids = []
    title_id = ""
    for f in fields:
        fid = str(f.get("id", "")).strip()
        if not fid:
            continue
        if bool(f.get("isTitle", False)) and not title_id:
            title_id = fid
        if not bool(f.get("isSystem", False)):
            ids.append(fid)
    out = []
    if title_id:
        out.append(title_id)
    for fid in ids:
        if fid not in out:
            out.append(fid)
        if len(out) >= 3:
            break
    return out


def build_prompt(app_name: str, worksheet_name: str, worksheet_id: str, fields: List[dict]) -> str:
    return f"""
你是明道云视图规划助手。请基于工作表名称和字段，规划“建议创建的视图列表”。

应用名：{app_name}
工作表名：{worksheet_name}
工作表ID：{worksheet_id}
字段列表：
{json.dumps(fields, ensure_ascii=False, indent=2)}

仅输出 JSON（不要 markdown）：
{{
  "worksheetId": "{worksheet_id}",
  "worksheetName": "{worksheet_name}",
  "views": [
    {{
      "name": "视图名",
      "viewType": "0|1|3|4",
      "reason": "建议理由",
      "displayControls": ["字段ID1", "字段ID2"],
      "coverCid": "封面字段ID或空字符串",
      "viewControl": "看板分组字段ID或空字符串",
      "advancedSetting": {{}},
      "postCreateUpdates": [
        {{
          "editAttrs": ["advancedSetting"],
          "editAdKeys": ["calendarcids"],
          "advancedSetting": {{}}
        }}
      ]
    }}
  ]
}}

规则：
1) 仅允许 viewType=0(表格),1(看板),3(画廊),4(日历)。
2) 视图数量 1-4 个，必须实用，不要凑数。
3) displayControls / coverCid / viewControl 必须来自提供的字段ID；无法确定时填空或省略。
4) 日历视图建议在 postCreateUpdates.advancedSetting 中提供 calendarcids（字符串化 JSON）。
5) 看板视图建议设置 viewControl 为单选字段ID（若存在）。
6) 若字段不支持某视图，请不要输出该视图类型。
7) 输出必须是可解析 JSON。
""".strip()


def normalize_views(raw_views: Any, fields: List[dict]) -> List[dict]:
    if not isinstance(raw_views, list):
        return []
    field_ids = {str(f.get("id", "")).strip() for f in fields if str(f.get("id", "")).strip()}
    fallback_display = default_display_controls(fields)
    out: List[dict] = []
    seen_names = set()

    for item in raw_views:
        if not isinstance(item, dict):
            continue
        view_type = str(item.get("viewType", "")).strip()
        if view_type not in ALLOWED_VIEW_TYPES:
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            name = f"视图_{view_type}_{len(out)+1}"
        if name in seen_names:
            name = f"{name}_{len(out)+1}"
        seen_names.add(name)

        display_controls = item.get("displayControls")
        if not isinstance(display_controls, list):
            display_controls = []
        display_controls = [str(x).strip() for x in display_controls if str(x).strip() in field_ids]
        if not display_controls:
            display_controls = fallback_display

        cover_cid = str(item.get("coverCid", "")).strip()
        if cover_cid and cover_cid not in field_ids:
            cover_cid = ""
        view_control = str(item.get("viewControl", "")).strip()
        if view_control and view_control not in field_ids:
            view_control = ""

        advanced_setting = item.get("advancedSetting")
        if not isinstance(advanced_setting, dict):
            advanced_setting = {}

        post_updates = item.get("postCreateUpdates")
        if not isinstance(post_updates, list):
            post_updates = []
        normalized_updates = []
        for upd in post_updates:
            if not isinstance(upd, dict):
                continue
            normalized_updates.append(upd)

        out.append(
            {
                "name": name,
                "viewType": view_type,
                "reason": str(item.get("reason", "")).strip(),
                "displayControls": display_controls,
                "coverCid": cover_cid,
                "viewControl": view_control,
                "advancedSetting": advanced_setting,
                "postCreateUpdates": normalized_updates,
            }
        )
        if len(out) >= 8:
            break
    return out


def plan_views_for_worksheet(client: genai.Client, model: str, app_name: str, worksheet: dict, fields: List[dict]) -> dict:
    prompt = build_prompt(app_name, worksheet["workSheetName"], worksheet["workSheetId"], fields)
    last_exc: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= 3:
                raise
            wait_seconds = attempt * 2
            print(
                f"Gemini 规划视图请求失败，worksheet={worksheet['workSheetName']} "
                f"attempt={attempt}/3，{wait_seconds} 秒后重试: {exc}"
            )
            time.sleep(wait_seconds)
    else:
        raise last_exc or RuntimeError("Gemini 规划视图失败")
    parsed = extract_json(resp.text or "")
    views = normalize_views(parsed.get("views"), fields)
    return {
        "worksheetId": worksheet["workSheetId"],
        "worksheetName": worksheet["workSheetName"],
        "fields": fields,
        "views": views,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="遍历应用工作表并使用 Gemini 规划视图")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--app-ids", default="", help="可选，应用ID列表（逗号分隔）；不传则交互选择")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    api_key = load_gemini_api_key(Path(args.config).expanduser().resolve())
    client = genai.Client(api_key=api_key)
    web_auth = load_web_auth(Path(args.auth_config).expanduser().resolve())

    app_rows = load_app_auth_rows()
    apps = []
    for r in app_rows:
        app_id = str(r.get("appId", "")).strip()
        app_key = str(r.get("appKey", "")).strip()
        sign = str(r.get("sign", "")).strip()
        app_name = str(r.get("name", "")).strip() or app_id
        if not app_id or not app_key or not sign:
            continue
        try:
            meta = fetch_app_meta(app_key, sign)
            app_name = str(meta.get("name", "")).strip() or app_name
        except Exception:
            pass
        apps.append({"appId": app_id, "appName": app_name, "appKey": app_key, "sign": sign})
    if not apps:
        raise RuntimeError("没有可用应用")

    picked_apps = []
    app_ids_arg = str(args.app_ids or "").strip()
    if app_ids_arg:
        wanted = {x.strip() for x in app_ids_arg.split(",") if x.strip()}
        picked_apps = [a for a in apps if a["appId"] in wanted]
        if not picked_apps:
            raise ValueError(f"--app-ids 未匹配到应用: {app_ids_arg}")
    else:
        print("可选应用：")
        print("序号 | 应用名称 | 应用ID")
        for i, app in enumerate(apps, start=1):
            print(f"{i}. {app['appName']} | {app['appId']}")
        picked_idx = choose_indexes(
            "请选择应用：输入 y=全部；输入序号(如 1,2,3 / 1.2.3)；任意键取消: ",
            len(apps),
        )
        if not picked_idx:
            print("已取消。")
            return
        picked_apps = [apps[i - 1] for i in picked_idx]

    result_apps = []
    total_worksheets = 0
    total_views = 0
    for app in picked_apps:
        print(f"\n处理应用: {app['appName']} ({app['appId']})")
        worksheets = fetch_worksheets(app["appKey"], app["sign"])
        app_out = {"appId": app["appId"], "appName": app["appName"], "worksheets": []}
        for ws in worksheets:
            schema = fetch_controls(ws["workSheetId"], web_auth)
            fields = [simplify_field(f) for f in schema.get("fields", []) if isinstance(f, dict)]
            planned = plan_views_for_worksheet(client, args.model, app["appName"], ws, fields)
            app_out["worksheets"].append(planned)
            total_worksheets += 1
            total_views += len(planned.get("views", []))
            print(f"- {ws['workSheetName']}：规划 {len(planned.get('views', []))} 个视图")
        result_apps.append(app_out)

    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "source": "gemini_view_planner_v1",
        "apps": result_apps,
        "summary": {
            "appCount": len(result_apps),
            "worksheetCount": total_worksheets,
            "viewCount": total_views,
        },
    }

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        app_part = "multi" if len(result_apps) != 1 else sanitize_name(str(result_apps[0].get("appName", "")))
        out_path = (VIEW_PLAN_DIR / f"view_plan_{app_part}_{now_ts()}.json").resolve()
    write_json(out_path, payload)
    print(f"\n规划完成: {out_path}")
    print(f"- 应用数: {payload['summary']['appCount']}")
    print(f"- 工作表数: {payload['summary']['worksheetCount']}")
    print(f"- 视图总数: {payload['summary']['viewCount']}")


if __name__ == "__main__":
    main()
