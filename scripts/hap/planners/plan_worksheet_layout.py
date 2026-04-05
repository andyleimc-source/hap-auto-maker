#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互式拉取应用 -> 工作表与字段 -> 调用 Gemini 规划字段布局（size/row/col）。
输出规划 JSON，终端仅打印摘要。
"""

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
from typing import Dict, List, Optional, Tuple

NETWORK_MAX_RETRIES = 3
NETWORK_RETRY_DELAY = 5

import requests

import auth_retry
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config
from utils import latest_file, load_json

BASE_DIR = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
LAYOUT_PLAN_DIR = OUTPUT_ROOT / "worksheet_layout_plans"
GEMINI_CONFIG_PATH = AI_CONFIG_PATH
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
VALID_SIZES = (12, 6, 4, 3)


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


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "app"



def load_app_auth_rows() -> List[dict]:
    rows: List[dict] = []
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload = data.get("data")
        if isinstance(payload, list):
            for row in payload:
                if not isinstance(row, dict):
                    continue
                app_id = str(row.get("appId", "")).strip()
                app_key = str(row.get("appKey", "")).strip()
                sign = str(row.get("sign", "")).strip()
                if app_id and app_key and sign:
                    new_row = dict(row)
                    new_row["_auth_path"] = str(path.resolve())
                    rows.append(new_row)
    if not rows:
        raise FileNotFoundError(f"未找到可用应用授权文件: {APP_AUTH_DIR}")
    # 按 appId 去重，仅保留最新文件的记录
    dedup: Dict[str, dict] = {}
    for row in rows:
        app_id = str(row.get("appId", "")).strip()
        if app_id not in dedup:
            dedup[app_id] = row
    return list(dedup.values())


def fetch_app_meta(app_key: str, sign: str) -> dict:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app = data.get("data", {})
    if not isinstance(app, dict):
        raise RuntimeError(f"应用信息返回格式错误: {data}")
    return app


def discover_apps() -> List[dict]:
    rows = load_app_auth_rows()
    apps = []
    for row in rows:
        app_id = str(row.get("appId", "")).strip()
        app_key = str(row.get("appKey", "")).strip()
        sign = str(row.get("sign", "")).strip()
        if not app_id or not app_key or not sign:
            continue
        try:
            app_meta = fetch_app_meta(app_key=app_key, sign=sign)
            app_name = str(app_meta.get("name", "")).strip() or app_id
        except Exception:
            app_name = app_id
        apps.append(
            {
                "appId": app_id,
                "appName": app_name,
                "appKey": app_key,
                "sign": sign,
                "authPath": row["_auth_path"],
            }
        )
    if not apps:
        raise RuntimeError("没有可用应用")
    return apps


def pick_app_interactive(apps: List[dict], app_index: int = 0, app_id: str = "") -> dict:
    if app_id.strip():
        target = next((a for a in apps if a["appId"] == app_id.strip()), None)
        if not target:
            raise ValueError(f"--app-id 未匹配到应用: {app_id}")
        return target

    print("可用应用：")
    print("序号 | 应用名称 | 应用ID")
    for i, app in enumerate(apps, start=1):
        print(f"{i}. {app['appName']} | {app['appId']}")

    if app_index > 0:
        if app_index > len(apps):
            raise ValueError(f"--app-index 超出范围: {app_index}")
        return apps[app_index - 1]

    while True:
        raw = input("请输入要规划的应用序号: ").strip()
        if not raw.isdigit():
            print("请输入数字序号。")
            continue
        idx = int(raw)
        if 1 <= idx <= len(apps):
            return apps[idx - 1]
        print(f"请输入 1 到 {len(apps)} 之间的序号。")


def fetch_worksheets(app_key: str, sign: str) -> List[dict]:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")

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

    for sec in data.get("data", {}).get("sections", []) or []:
        walk_sections(sec)
    return worksheets


def fetch_controls(worksheet_id: str) -> dict:
    resp = auth_retry.hap_web_post(GET_CONTROLS_URL, AUTH_CONFIG_PATH, json={"worksheetId": worksheet_id}, timeout=30)
    data = resp.json()

    # 兼容结构：{"data":{"code":1,"data":{...}},"state":1}
    wrapped = data.get("data", {})
    if isinstance(wrapped, dict) and isinstance(wrapped.get("data"), dict):
        if int(wrapped.get("code", 0)) != 1:
            raise RuntimeError(f"获取工作表控件失败: worksheetId={worksheet_id}, resp={data}")
        payload = wrapped["data"]
    else:
        payload = data.get("data", {})
        if not isinstance(payload, dict):
            raise RuntimeError(f"获取工作表控件失败: worksheetId={worksheet_id}, resp={data}")

    controls = payload.get("controls", [])
    version = int(payload.get("version", 0))
    source_id = str(payload.get("sourceId", worksheet_id))
    if not isinstance(controls, list):
        raise RuntimeError(f"控件格式错误: worksheetId={worksheet_id}, resp={data}")
    return {"sourceId": source_id, "version": version, "controls": controls}


def build_prompt(app_name: str, worksheet_brief: List[dict], requirements: str) -> str:
    return f"""
你是企业级表单布局优化专家。请基于给定的工作表与字段ID，规划每个字段的布局，让可读性更高。

目标应用：{app_name}
额外要求：{requirements or "无"}

输入数据（每个字段都包含 controlId，必须原样返回）：
{json.dumps(worksheet_brief, ensure_ascii=False)}

请只输出 JSON，格式如下：
{{
  "worksheets": [
    {{
      "workSheetId": "xxx",
      "workSheetName": "xxx",
      "fields": [
        {{
          "controlId": "字段ID",
          "controlName": "字段名",
          "size": 12,
          "row": 0,
          "col": 0,
          "reason": "简短说明"
        }}
      ]
    }}
  ]
}}

硬性约束：
1) 必须覆盖输入中的每个 workSheetId。
2) 每个工作表必须覆盖输入中的每个 controlId。
3) size 仅允许 12/6/4/3，分别表示每行 1/2/3/4 列。
4) row 从 0 开始；col 从 0 开始且必须与 size 匹配：
   - size=12 -> col=0
   - size=6 -> col in [0,1]
   - size=4 -> col in [0,1,2]
   - size=3 -> col in [0,1,2,3]
5) 不要输出 markdown 或任何额外文本。
""".strip()


def _safe_int(v, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def normalize_layout(size: int, row: int, col: int) -> Tuple[int, int, int]:
    if size not in VALID_SIZES:
        size = 12
    if row < 0:
        row = 0
    slots = {12: 1, 6: 2, 4: 3, 3: 4}[size]
    if col < 0:
        col = 0
    if col >= slots:
        col = slots - 1
    return size, row, col


def normalize_plan(raw: dict, worksheet_brief: List[dict]) -> dict:
    # 建立输入索引
    ws_index = {}
    for ws in worksheet_brief:
        ws_id = ws["workSheetId"]
        field_index = {f["controlId"]: f for f in ws["fields"]}
        ws_index[ws_id] = {
            "workSheetName": ws["workSheetName"],
            "field_index": field_index,
            "field_ids": list(field_index.keys()),
        }

    normalized_ws = []
    raw_ws = raw.get("worksheets", [])
    raw_map = {}
    if isinstance(raw_ws, list):
        for ws in raw_ws:
            if not isinstance(ws, dict):
                continue
            ws_id = str(ws.get("workSheetId", "")).strip()
            if ws_id and ws_id not in raw_map:
                raw_map[ws_id] = ws

    for ws in worksheet_brief:
        ws_id = ws["workSheetId"]
        ws_name = ws["workSheetName"]
        input_fields = ws_index[ws_id]["field_index"]
        raw_fields = {}
        raw_ws_item = raw_map.get(ws_id, {})
        if isinstance(raw_ws_item.get("fields"), list):
            for f in raw_ws_item["fields"]:
                if not isinstance(f, dict):
                    continue
                cid = str(f.get("controlId", "")).strip()
                if cid and cid not in raw_fields:
                    raw_fields[cid] = f

        fields_out = []
        # fallback 布局：按输入顺序每行3列（size=4）
        for idx, cid in enumerate(ws_index[ws_id]["field_ids"]):
            src_field = input_fields[cid]
            rf = raw_fields.get(cid, {})
            size = _safe_int(rf.get("size"), 4)
            row = _safe_int(rf.get("row"), idx // 3)
            col = _safe_int(rf.get("col"), idx % 3)
            size, row, col = normalize_layout(size, row, col)
            fields_out.append(
                {
                    "controlId": cid,
                    "controlName": src_field["controlName"],
                    "size": size,
                    "row": row,
                    "col": col,
                    "reason": str(rf.get("reason", "")).strip(),
                }
            )

        normalized_ws.append({"workSheetId": ws_id, "workSheetName": ws_name, "fields": fields_out})

    return {"worksheets": normalized_ws}


def main() -> None:
    parser = argparse.ArgumentParser(description="交互式规划工作表字段布局（size/row/col）")
    parser.add_argument("--app-index", type=int, default=0, help="可选，应用序号（免交互）")
    parser.add_argument("--app-id", default="", help="可选，应用 ID（传入后跳过应用选择交互）")
    parser.add_argument("--requirements", default="", help="额外布局要求")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    # 结构化 JSON 输出，使用极速档
    ai_config = load_ai_config(GEMINI_CONFIG_PATH, tier="fast")
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]

    apps = discover_apps()
    picked = pick_app_interactive(apps, app_index=args.app_index, app_id=args.app_id)

    app_id = picked["appId"]
    app_name = picked["appName"]
    app_key = picked["appKey"]
    sign = picked["sign"]
    auth_path = picked["authPath"]

    worksheets = fetch_worksheets(app_key=app_key, sign=sign)
    if not worksheets:
        raise RuntimeError(f"应用下没有工作表: {app_name} ({app_id})")

    worksheet_brief = []
    total_fields = 0
    for ws in worksheets:
        ws_id = ws["workSheetId"]
        ws_controls = fetch_controls(ws_id)
        fields = []
        for ctrl in ws_controls["controls"]:
            if not isinstance(ctrl, dict):
                continue
            cid = str(ctrl.get("controlId", "")).strip()
            cname = str(ctrl.get("controlName", "")).strip()
            ctype = _safe_int(ctrl.get("type"), 0)
            if not cid:
                continue
            fields.append(
                {
                    "controlId": cid,
                    "controlName": cname,
                    "type": ctype,
                    "current": {
                        "size": _safe_int(ctrl.get("size"), 12),
                        "row": _safe_int(ctrl.get("row"), 0),
                        "col": _safe_int(ctrl.get("col"), 0),
                    },
                }
            )
        total_fields += len(fields)
        worksheet_brief.append(
            {
                "workSheetId": ws_id,
                "workSheetName": ws["workSheetName"],
                "fieldCount": len(fields),
                "fields": fields,
            }
        )

    prompt = build_prompt(app_name=app_name, worksheet_brief=worksheet_brief, requirements=args.requirements.strip())
    response = None
    for net_try in range(1, NETWORK_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=create_generation_config(
                    ai_config,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            break
        except Exception as e:
            if net_try < NETWORK_MAX_RETRIES:
                wait = NETWORK_RETRY_DELAY * net_try
                print(f"[网络重试 {net_try}/{NETWORK_MAX_RETRIES}] {type(e).__name__}: {e}，{wait}s 后重试...")
                time.sleep(wait)
            else:
                raise
    raw_result = extract_json(response.text or "")
    normalized = normalize_plan(raw_result, worksheet_brief)

    final = {
        "app": {
            "appId": app_id,
            "appName": app_name,
            "appAuthJson": auth_path,
        },
        "requirements": args.requirements.strip(),
        "source_summary": {
            "worksheetCount": len(worksheet_brief),
            "fieldCount": total_fields,
        },
        "worksheets": normalized["worksheets"],
    }

    if args.output:
        out = Path(args.output).expanduser().resolve()
    else:
        LAYOUT_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = (LAYOUT_PLAN_DIR / f"worksheet_layout_plan_{sanitize_name(app_id)}_{ts}.json").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    latest = (LAYOUT_PLAN_DIR / "worksheet_layout_plan_latest.json").resolve()
    latest.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    print("布局规划完成（摘要）")
    print(f"- 应用: {app_name} ({app_id})")
    print(f"- 工作表数量: {len(worksheet_brief)}")
    print(f"- 字段数量: {total_fields}")
    print(f"- 输出文件: {out}")
    print(f"- 最新文件: {latest}")


if __name__ == "__main__":
    main()
