#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史 Gemini 配置兼容工具。
优先读取统一的 config/credentials/ai_auth.json；
若不存在，再回退到旧 gemini_auth.json。
"""

from pathlib import Path
from typing import Dict, Tuple

from ai_utils import (
    AI_CONFIG_PATH,
    GEMINI_CONFIG_PATH,
    create_generation_config,
    default_base_url_for_provider,
    default_model_for_provider,
    load_ai_config,
    mask_secret,
    parse_ai_json,
)

DEFAULT_MODEL = default_model_for_provider("gemini")


def load_ai_provider_config(config_path: Path = AI_CONFIG_PATH) -> Dict[str, str]:
    return load_ai_config(config_path)


def load_gemini_config(config_path: Path = GEMINI_CONFIG_PATH) -> Tuple[str, str]:
    """
    历史函数名兼容。
    实际返回当前已配置 AI 平台的 (api_key, model)。
    """
    actual_path = AI_CONFIG_PATH if AI_CONFIG_PATH.exists() else config_path
    cfg = load_ai_config(actual_path)
    return cfg["api_key"], cfg["model"]


def parse_gemini_json(raw: str) -> dict:
    return parse_ai_json(raw)


if __name__ == "__main__":
    try:
        cfg = load_ai_provider_config()
        print(f"Provider: {cfg['provider']}")
        print(f"API Key: {mask_secret(cfg['api_key'], show=6)}")
        print(f"Model: {cfg['model']}")
        print(f"Base URL: {cfg.get('base_url') or default_base_url_for_provider(cfg['provider']) or '(默认)'}")
    except Exception as e:
        print(f"Error: {e}")
