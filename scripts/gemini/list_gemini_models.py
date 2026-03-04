#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询 Gemini 可用模型列表并输出 JSON。
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from google import genai

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
GEMINI_MODELS_DIR = OUTPUT_ROOT / "gemini_models"


def load_api_key(config_path: Path) -> str:
    if not config_path.exists():
        raise FileNotFoundError(f"缺少配置文件: {config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    api_key = data.get("api_key", "").strip()
    if not api_key:
        raise ValueError(f"配置缺少 api_key: {config_path}")
    return api_key


def model_to_dict(model_obj) -> dict:
    return {
        "name": getattr(model_obj, "name", ""),
        "display_name": getattr(model_obj, "display_name", ""),
        "description": getattr(model_obj, "description", ""),
        "input_token_limit": getattr(model_obj, "input_token_limit", None),
        "output_token_limit": getattr(model_obj, "output_token_limit", None),
        "supported_actions": getattr(model_obj, "supported_actions", None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="查询 Gemini 可用模型列表")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    api_key = load_api_key(Path(args.config).expanduser().resolve())
    client = genai.Client(api_key=api_key)

    models = [model_to_dict(m) for m in client.models.list()]
    result = {
        "count": len(models),
        "models": models,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        GEMINI_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (GEMINI_MODELS_DIR / f"gemini_models_{ts}.json").resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n已保存: {output_path}")


if __name__ == "__main__":
    main()
