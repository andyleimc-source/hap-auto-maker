#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据应用清单 + icon 库，调用 Gemini 生成应用 icon 匹配结果（待执行 JSON）。
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

NETWORK_MAX_RETRIES = 3
NETWORK_RETRY_DELAY = 5

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))

from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config
from utils import latest_file, load_json

CONFIG_PATH = AI_CONFIG_PATH
ICON_JSON_PATH = BASE_DIR / "data" / "assets" / "icons" / "icon.json"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_INVENTORY_DIR = OUTPUT_ROOT / "app_inventory"
APP_ICON_MATCH_DIR = OUTPUT_ROOT / "app_icon_match_plans"


def resolve_app_inventory_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (APP_INVENTORY_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到应用清单: {value}（也未在 {APP_INVENTORY_DIR} 找到）")
    p = latest_file(APP_INVENTORY_DIR, "app_inventory_*.json")
    if not p:
        raise FileNotFoundError(f"未找到应用清单，请传 --app-json（目录: {APP_INVENTORY_DIR}）")
    return p.resolve()


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
    parser = argparse.ArgumentParser(description="使用 AI 为应用匹配 icon，并输出待执行 JSON")
    parser.add_argument("--app-json", default="", help="应用清单 JSON（文件名或路径，默认取最新）")
    parser.add_argument("--icon-json", default=str(ICON_JSON_PATH), help="icon 库 JSON 路径")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="AI 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    ai_config = load_ai_config(Path(args.config).expanduser().resolve())
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]

    app_json_path = resolve_app_inventory_json(args.app_json)
    app_inventory = load_json(app_json_path)
    apps = app_inventory.get("apps", [])
    if not isinstance(apps, list) or not apps:
        raise ValueError(f"应用清单为空或格式错误: {app_json_path}")

    icon_data = load_json(Path(args.icon_json).expanduser().resolve())
    icon_names = sorted(set(collect_icon_names(icon_data)))
    if not icon_names:
        raise ValueError(f"icon 库为空: {args.icon_json}")

    app_auth_json = str(app_inventory.get("app_auth_json", "")).strip()
    app_brief = [
        {"appId": a.get("appId"), "appName": a.get("appName")}
        for a in apps
        if isinstance(a, dict) and a.get("appId") and a.get("appName")
    ]
    if not app_brief:
        raise ValueError("应用清单中无有效 appId/appName")

    prompt = f"""
你是企业应用 UI 设计助手。请根据应用名称从 icon 库中选择最匹配的 icon。

应用列表：
{json.dumps(app_brief, ensure_ascii=False, indent=2)}

icon 库（fileName）：
{json.dumps(icon_names, ensure_ascii=False)}

请只输出 JSON，对每个应用都给出一个 icon，格式严格如下：
{{
  "app_auth_json": "{app_auth_json}",
  "mappings": [
    {{
      "appId": "xxx",
      "appName": "xxx",
      "icon": "sys_xxx",
      "reason": "简短理由"
    }}
  ]
}}

约束：
1) icon 必须来自 icon 库。
2) 每个 appId 只出现一次，且必须全部覆盖。
3) 不要输出 markdown，不要输出额外文本。
""".strip()

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
    result = extract_json(response.text or "")

    valid_icons = set(icon_names)
    by_id = {a["appId"]: a["appName"] for a in app_brief}
    mappings = result.get("mappings", [])
    if not isinstance(mappings, list):
        raise ValueError("Gemini 返回的 mappings 不是列表")

    normalized = []
    seen = set()
    for m in mappings:
        if not isinstance(m, dict):
            continue
        app_id = str(m.get("appId", "")).strip()
        icon = str(m.get("icon", "")).strip()
        if app_id in by_id and icon in valid_icons and app_id not in seen:
            normalized.append(
                {
                    "appId": app_id,
                    "appName": by_id[app_id],
                    "icon": icon,
                    "reason": str(m.get("reason", "")).strip(),
                }
            )
            seen.add(app_id)

    missing = [app_id for app_id in by_id if app_id not in seen]
    if missing:
        fallback = "sys_8_4_folder" if "sys_8_4_folder" in valid_icons else icon_names[0]
        for app_id in missing:
            normalized.append(
                {
                    "appId": app_id,
                    "appName": by_id[app_id],
                    "icon": fallback,
                    "reason": "fallback",
                }
            )

    final = {
        "app_auth_json": app_auth_json,
        "source_app_json": str(app_json_path),
        "mappings": normalized,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        APP_ICON_MATCH_DIR.mkdir(parents=True, exist_ok=True)
        seed = sanitize_name(normalized[0]["appId"] if normalized else "app")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (APP_ICON_MATCH_DIR / f"app_icon_match_plan_{seed}_{ts}.json").resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_path = (APP_ICON_MATCH_DIR / "app_icon_match_plan_latest.json").resolve()
    latest_path.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(final, ensure_ascii=False, indent=2))
    print(f"\n已保存: {output_path}")
    print(f"已更新: {latest_path}")


if __name__ == "__main__":
    main()
