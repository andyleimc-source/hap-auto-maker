#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 配置加载工具。
统一从 config/credentials/gemini_auth.json 加载 API Key 和默认 Model。
"""

import json
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

if __name__ == "__main__":
    try:
        key, mod = load_gemini_config()
        print(f"API Key: {key[:6]}...{key[-4:]}")
        print(f"Model: {mod}")
    except Exception as e:
        print(f"Error: {e}")
