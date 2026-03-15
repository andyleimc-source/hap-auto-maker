#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据工作表清单 + icon 库，调用 Gemini 生成工作表 icon 匹配结果（待执行 JSON）。
"""

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

NETWORK_MAX_RETRIES = 3
NETWORK_RETRY_DELAY = 5

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
ICON_JSON_PATH = BASE_DIR / "data" / "assets" / "icons" / "icon.json"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
WORKSHEET_INVENTORY_DIR = OUTPUT_ROOT / "worksheet_inventory"
ICON_MATCH_DIR = OUTPUT_ROOT / "worksheet_icon_match_plans"
DEFAULT_MODEL = "gemini-2.5-pro"


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def resolve_inventory_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (WORKSHEET_INVENTORY_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到工作表清单: {value}（也未在 {WORKSHEET_INVENTORY_DIR} 找到）")
    p = latest_file(WORKSHEET_INVENTORY_DIR, "worksheet_inventory_*.json")
    if not p:
        raise FileNotFoundError(f"未找到工作表清单，请传 --worksheet-json（目录: {WORKSHEET_INVENTORY_DIR}）")
    return p.resolve()


def load_api_key(config_path: Path) -> str:
    data = load_json(config_path)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"配置缺少 api_key: {config_path}")
    return api_key


def collect_icon_names(node) -> list[str]:
    result = []
    if isinstance(node, dict):
        f = node.get("fileName")
        if isinstance(f, str) and f.strip():
            result.append(f.strip())
        for v in node.values():
            result.extend(collect_icon_names(v))
    elif isinstance(node, list):
        for i in node:
            result.extend(collect_icon_names(i))
    return result


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


def main() -> None:
    parser = argparse.ArgumentParser(description="使用 Gemini 为工作表匹配 icon，并输出待执行 JSON")
    parser.add_argument("--worksheet-json", default="", help="工作表清单 JSON（文件名或路径，默认取最新）")
    parser.add_argument("--icon-json", default=str(ICON_JSON_PATH), help="icon 库 JSON 路径")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    inventory_path = resolve_inventory_json(args.worksheet_json)
    inventory = load_json(inventory_path)
    worksheets = inventory.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError(f"工作表清单为空或格式错误: {inventory_path}")

    icon_data = load_json(Path(args.icon_json).expanduser().resolve())
    icon_names = sorted(set(collect_icon_names(icon_data)))
    if not icon_names:
        raise ValueError(f"icon 库为空: {args.icon_json}")

    app_id = str(inventory.get("app_id", "")).strip()
    app_auth_json = str(inventory.get("app_auth_json", "")).strip()

    worksheet_brief = [
        {"workSheetId": w.get("workSheetId"), "workSheetName": w.get("workSheetName")}
        for w in worksheets
        if isinstance(w, dict) and w.get("workSheetId") and w.get("workSheetName")
    ]
    if not worksheet_brief:
        raise ValueError("工作表清单中无有效 workSheetId/workSheetName")

    prompt = f"""
你是企业应用 UI 设计助手。请根据工作表名称从 icon 库中选择最匹配的 icon。

工作表列表：
{json.dumps(worksheet_brief, ensure_ascii=False, indent=2)}

icon 库（fileName）：
{json.dumps(icon_names, ensure_ascii=False)}

请只输出 JSON，对每个工作表都给出一个 icon，格式严格如下：
{{
  "app_id": "{app_id}",
  "app_auth_json": "{app_auth_json}",
  "mappings": [
    {{
      "workSheetId": "xxx",
      "workSheetName": "xxx",
      "icon": "sys_xxx",
      "reason": "简短理由"
    }}
  ]
}}

约束：
1) icon 必须来自 icon 库。
2) 每个 workSheetId 只出现一次，且必须全部覆盖。
3) 不要输出 markdown，不要输出额外文本。
""".strip()

    api_key = load_api_key(Path(args.config).expanduser().resolve())
    client = genai.Client(api_key=api_key)
    response = None
    for net_try in range(1, NETWORK_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=args.model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
            )
            break
        except Exception as e:
            if net_try < NETWORK_MAX_RETRIES:
                wait = NETWORK_RETRY_DELAY * net_try
                print(f"[网络重试 {net_try}/{NETWORK_MAX_RETRIES}] {type(e).__name__}: {e}，{wait}s 后重试...")
                time.sleep(wait)
            else:
                raise
    result = extract_json(response.text or "")

    # basic validate & normalize
    valid_icons = set(icon_names)
    by_id = {w["workSheetId"]: w["workSheetName"] for w in worksheet_brief}
    mappings = result.get("mappings", [])
    if not isinstance(mappings, list):
        raise ValueError("Gemini 返回的 mappings 不是列表")

    normalized = []
    seen = set()
    for m in mappings:
        if not isinstance(m, dict):
            continue
        ws_id = str(m.get("workSheetId", "")).strip()
        icon = str(m.get("icon", "")).strip()
        if ws_id in by_id and icon in valid_icons and ws_id not in seen:
            normalized.append(
                {
                    "workSheetId": ws_id,
                    "workSheetName": by_id[ws_id],
                    "icon": icon,
                    "reason": str(m.get("reason", "")).strip(),
                }
            )
            seen.add(ws_id)

    missing = [ws_id for ws_id in by_id if ws_id not in seen]
    if missing:
        # 如果 Gemini 漏了，兜底给默认 icon
        fallback = "sys_8_4_folder" if "sys_8_4_folder" in valid_icons else icon_names[0]
        for ws_id in missing:
            normalized.append(
                {
                    "workSheetId": ws_id,
                    "workSheetName": by_id[ws_id],
                    "icon": fallback,
                    "reason": "fallback",
                }
            )

    final = {
        "app_id": app_id,
        "app_auth_json": app_auth_json,
        "source_worksheet_json": str(inventory_path),
        "mappings": normalized,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        ICON_MATCH_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (ICON_MATCH_DIR / f"worksheet_icon_match_plan_{sanitize_name(app_id)}_{ts}.json").resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(final, ensure_ascii=False, indent=2))
    print(f"\n已保存: {output_path}")


if __name__ == "__main__":
    main()
