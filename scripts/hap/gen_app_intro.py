#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互式应用简介生成器。
1. 列出所有已授权应用
2. 用户选择序号
3. 调用 AI（Gemini / DeepSeek）生成约 300 字 Markdown 简介
4. 保存到 app_intro/<appName>/ 子文件夹
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

BASE_DIR = Path(__file__).resolve().parents[2]
APP_INTRO_DIR = BASE_DIR / "app_intro"

from mock_data_common import (
    DEFAULT_BASE_URL,
    discover_authorized_apps,
    fetch_app_worksheets,
    print_app_choices,
)
from ai_utils import get_ai_client, load_ai_config


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────

def sanitize_folder_name(name: str) -> str:
    """将应用名称转为合法文件夹名（保留中文、字母、数字、下划线、连字符）。"""
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return cleaned or "unnamed_app"


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ──────────────────────────────────────────────
# Prompt 构建
# ──────────────────────────────────────────────

def build_intro_prompt(app_name: str, worksheet_names: List[str]) -> str:
    ws_section = (
        "\n".join(f"- {ws}" for ws in worksheet_names)
        if worksheet_names
        else "（该应用暂无工作表信息）"
    )
    return f"""你是一位专业的企业软件产品文案专家。请为以下低代码应用撰写一篇简介，要求：

1. 约 300 字（可在 280-320 字范围内浮动）
2. 输出格式为 Markdown，包含至少：
   - 一级标题（# 应用名称 简介）
   - 核心功能描述（2-3 段）
   - 应用场景（1 段）
   - 小结（1-2 句话）
3. 语言简洁、专业、有吸引力
4. 不要出现虚假数据或未知品牌名称
5. 不要在回复中加任何 markdown 代码块围栏

应用名称：{app_name}

包含的工作表（功能模块）：
{ws_section}

请直接输出 Markdown 内容，不要其他说明文字。""".strip()


# ──────────────────────────────────────────────
# AI 调用
# ──────────────────────────────────────────────

def call_ai_for_intro(prompt: str, config: dict, max_retries: int = 3) -> str:
    """调用 AI 生成简介文本，返回原始字符串。"""
    client = get_ai_client(config)
    provider = config.get("provider", "gemini")
    model = config.get("model", "")
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            if provider == "gemini":
                from google.genai import types
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                    ),
                )
                return resp.text or ""
            else:
                # DeepSeek / OpenAI 兼容层
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={"temperature": 0.7},
                )
                return resp.text or ""
        except Exception as exc:
            last_error = str(exc)
            print(f"  [第 {attempt} 次尝试失败] {last_error}")

    raise RuntimeError(f"AI 生成失败，已重试 {max_retries} 次: {last_error}")


# ──────────────────────────────────────────────
# 保存文件
# ──────────────────────────────────────────────

def save_intro(app_name: str, app_id: str, content: str) -> Path:
    """将简介保存到 app_intro/<appName>/<timestamp>.md，同时更新 latest.md。"""
    folder_name = sanitize_folder_name(app_name)
    target_dir = APP_INTRO_DIR / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    ts = now_ts()
    file_name = f"intro_{app_id}_{ts}.md"
    file_path = target_dir / file_name
    file_path.write_text(content, encoding="utf-8")

    latest_path = target_dir / "latest.md"
    latest_path.write_text(content, encoding="utf-8")

    return file_path


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="为 HAP 应用生成 Markdown 简介（约 300 字）")
    parser.add_argument("--app-index", type=int, default=0, help="直接指定应用序号，跳过交互选择")
    parser.add_argument("--app-id", default="", help="直接指定 appId，跳过交互选择")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--max-retries", type=int, default=3, help="AI 调用失败重试次数")
    parser.add_argument("--output", default="", help="可选，指定输出文件路径（覆盖默认路径）")
    args = parser.parse_args()

    # ── 1. 获取应用列表 ──────────────────────────────
    print("正在获取应用列表……")
    apps = discover_authorized_apps(base_url=args.base_url)
    if not apps:
        print("❌ 未发现任何已授权应用，请先运行 get_app_authorize.py 生成授权文件。")
        sys.exit(1)

    # ── 2. 选择应用 ──────────────────────────────────
    selected_app = None

    if args.app_id:
        for app in apps:
            if app["appId"] == args.app_id.strip():
                selected_app = app
                break
        if selected_app is None:
            print(f"❌ 未找到 appId={args.app_id}")
            sys.exit(1)

    elif args.app_index > 0:
        for app in apps:
            if int(app["index"]) == args.app_index:
                selected_app = app
                break
        if selected_app is None:
            print(f"❌ 未找到序号={args.app_index}")
            sys.exit(1)

    else:
        # 交互式选择
        print_app_choices(apps)
        while True:
            raw = input("\n请输入要生成简介的应用序号: ").strip()
            if raw.isdigit():
                idx = int(raw)
                for app in apps:
                    if int(app["index"]) == idx:
                        selected_app = app
                        break
                if selected_app:
                    break
            print("输入无效，请重新输入数字序号。")

    app_name = selected_app["appName"]
    app_id = selected_app["appId"]
    print(f"\n✅ 已选择应用: {app_name} ({app_id})")

    # ── 3. 获取工作表信息（用于 prompt 丰富度）────────
    print("正在获取工作表列表……")
    worksheet_names: List[str] = []
    try:
        _, worksheets = fetch_app_worksheets(
            base_url=args.base_url,
            app_key=selected_app["appKey"],
            sign=selected_app["sign"],
        )
        worksheet_names = [
            str(ws.get("worksheetName", "")).strip()
            for ws in worksheets
            if str(ws.get("worksheetName", "")).strip()
        ]
        print(f"  获取到 {len(worksheet_names)} 个工作表")
    except Exception as exc:
        print(f"  ⚠️  获取工作表失败，将仅使用应用名称生成简介: {exc}")

    # ── 4. 构建 Prompt 并调用 AI ─────────────────────
    print("\n正在调用 AI 生成简介……")
    ai_config = load_ai_config()
    prompt = build_intro_prompt(app_name, worksheet_names)

    intro_text = call_ai_for_intro(prompt, ai_config, max_retries=args.max_retries)

    if not intro_text.strip():
        print("❌ AI 返回内容为空，请检查 AI 配置。")
        sys.exit(1)

    # ── 5. 保存文件 ───────────────────────────────────
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(intro_text, encoding="utf-8")
        saved_path = output_path
    else:
        saved_path = save_intro(app_name, app_id, intro_text)

    # ── 6. 输出结果 ───────────────────────────────────
    print("\n" + "─" * 60)
    print(intro_text)
    print("─" * 60)
    print(f"\n✅ 简介已保存至: {saved_path}")
    print(f"   目录: {saved_path.parent}")


if __name__ == "__main__":
    main()
