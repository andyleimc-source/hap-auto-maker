#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 配置加载工具。
统一从 config/credentials/gemini_auth.json 加载 API Key 和默认 Model。

也提供 parse_gemini_json(raw) —— 健壮解析 Gemini 返回的 JSON：
  1. 直接 json.loads
  2. 剥离 Markdown 代码块
  3. json_repair 修复（trailing commas / 单引号 / 截断 等）
  4. 提取第一个完整 JSON 对象 { ... }
"""

import json
import re
from pathlib import Path
from typing import Tuple

BASE_DIR = Path(__file__).resolve().parents[2]
GEMINI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
DEFAULT_MODEL = "gemini-2.5-pro"

def load_gemini_config(config_path: Path = GEMINI_CONFIG_PATH) -> Tuple[str, str]:
    """
    加载 Gemini 配置。
    返回: (api_key, model)
    """
    if not config_path.exists():
        raise FileNotFoundError(f"缺少 Gemini 认证配置: {config_path}")
    
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"解析 Gemini 配置文件失败: {config_path}, error={e}")

    api_key = str(data.get("api_key", "")).strip()
    model = str(data.get("model", "")).strip() or DEFAULT_MODEL

    if not api_key:
        raise ValueError(f"Gemini 配置缺少 api_key: {config_path}")
    
    return api_key, model

def parse_gemini_json(raw: str) -> dict:
    """
    从 Gemini 响应文本中健壮地提取并解析 JSON 对象。

    依次尝试：
    1. 直接 json.loads（最快路径）
    2. 剥离 Markdown 代码块（```json ... ``` 或 ``` ... ```）
    3. json_repair 自动修复（处理 trailing commas / 单引号 / 截断 JSON 等）
    4. 提取第一个 { ... } 再修复（应对前后有说明文字的情况）

    所有步骤均失败时抛出 ValueError。
    """
    if not raw:
        raise ValueError("Gemini 返回为空")

    # 1. 直接解析
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 2. 剥离 Markdown 代码块
    stripped = raw.strip()
    for prefix in ("```json", "```"):
        if stripped.startswith(prefix):
            inner = stripped[len(prefix):]
            if inner.endswith("```"):
                inner = inner[:-3]
            inner = inner.strip()
            try:
                obj = json.loads(inner)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                raw = inner  # 用剥离后的内容继续后续步骤
            break

    # 3. json_repair 修复
    try:
        from json_repair import repair_json  # type: ignore
        obj = repair_json(raw, return_objects=True)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 4. 提取第一个完整 { ... } 再修复
    start = raw.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start:i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        pass
                    try:
                        from json_repair import repair_json  # type: ignore
                        obj = repair_json(candidate, return_objects=True)
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        pass
                    break

    raise ValueError(
        f"无法从 Gemini 响应中提取有效 JSON（响应长度 {len(raw)} 字符）\n"
        f"前500字符：{raw[:500]}"
    )


if __name__ == "__main__":
    try:
        key, mod = load_gemini_config()
        print(f"API Key: {key[:6]}...{key[-4:]}")
        print(f"Model: {mod}")
    except Exception as e:
        print(f"Error: {e}")
