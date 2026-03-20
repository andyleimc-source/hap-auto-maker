#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 模型统一调用工具。
支持 Gemini 和 DeepSeek。
统一从 config/credentials/ai_auth.json 加载配置，同时兼容旧 gemini_auth.json。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parents[2]
AI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "ai_auth.json"
GEMINI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 任务档位映射
TIER_MODELS = {
    "gemini": {
        "reasoning": "gemini-2.5-pro",
        "fast": "gemini-2.5-flash",
    },
    "deepseek": {
        "reasoning": "deepseek-reasoner",
        "fast": "deepseek-chat",
    },
}


def normalize_provider(provider: str) -> str:
    raw = str(provider or "").strip().lower()
    if raw in {"", "gemini", "google", "google-genai"}:
        return "gemini"
    if raw in {"deepseek", "deepseek-chat", "deepseek-reasoner"}:
        return "deepseek"
    raise ValueError(f"不支持的 AI 供应商: {provider}")


def get_model_by_tier(provider: str, tier: str = "fast") -> str:
    """
    根据供应商和任务档位获取模型名称。
    tier: "reasoning" (推理档) | "fast" (极速档)
    """
    p = normalize_provider(provider)
    t = str(tier or "fast").strip().lower()
    if t not in {"reasoning", "fast"}:
        t = "fast"
    return TIER_MODELS.get(p, {}).get(t, TIER_MODELS[p]["fast"])


def default_model_for_provider(provider: str) -> str:
    return get_model_by_tier(provider, "fast")


def default_base_url_for_provider(provider: str) -> str:
    return "" if normalize_provider(provider) == "gemini" else DEFAULT_DEEPSEEK_BASE_URL


def mask_secret(value: str, show: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "(未填写)"
    if len(text) <= show:
        return text
    return text[:show] + "****"


def load_ai_config(config_path: Optional[Path] = None, tier: Optional[str] = None) -> Dict[str, str]:
    """
    加载 AI 配置。
    如果指定了 tier，则根据 provider 自动选择模型；
    否则，优先使用配置文件中的 model，若无则使用默认的 fast 模型。
    返回: {"provider": "gemini|deepseek", "api_key": "...", "model": "...", "base_url": "...", "tier": "..."}
    """
    if config_path is None:
        config_path = AI_CONFIG_PATH

    target_path = config_path
    if config_path == GEMINI_CONFIG_PATH and AI_CONFIG_PATH.exists():
        target_path = AI_CONFIG_PATH
    if not target_path.exists():
        if config_path == AI_CONFIG_PATH and GEMINI_CONFIG_PATH.exists():
            target_path = GEMINI_CONFIG_PATH
        else:
            raise FileNotFoundError(f"缺少 AI 认证配置: {config_path}")

    try:
        data = json.loads(target_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"解析 AI 配置文件失败: {target_path}, error={e}")

    provider = normalize_provider(str(data.get("provider", "gemini")).strip().lower())
    api_key = str(data.get("api_key", "")).strip()

    # 模型选择逻辑
    if tier:
        model = get_model_by_tier(provider, tier)
    else:
        model = str(data.get("model", "")).strip() or get_model_by_tier(provider, "fast")

    base_url = str(data.get("base_url", "")).strip() or default_base_url_for_provider(provider)

    if not api_key:
        raise ValueError(f"AI 配置缺少 api_key: {target_path}")

    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "tier": tier or ("reasoning" if "reasoner" in model or "pro" in model.lower() else "fast"),
    }


class GeminiCompatibilityClient:
    """
    一个简单的兼容层，让 DeepSeek 客户端看起来像 google.genai.Client。
    仅实现本场景用到的 models.generate_content 和 chats.create。
    """

    def __init__(self, provider: str, api_key: str, model: str, base_url: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or DEFAULT_DEEPSEEK_BASE_URL

        from openai import OpenAI

        self._openai_client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    @property
    def models(self):
        return self

    @property
    def chats(self):
        return self

    def create(self, model: str, config: Any = None) -> Any:
        return FakeChat(self._openai_client, model or self.model, config)

    def generate_content(self, model: str, contents: str, config: Any = None) -> Any:
        temperature = 0.2
        response_format = None

        if config:
            if hasattr(config, "temperature"):
                temperature = config.temperature or 0.2
            elif isinstance(config, dict):
                temperature = config.get("temperature", 0.2)

            mime_type = ""
            if hasattr(config, "response_mime_type"):
                mime_type = config.response_mime_type
            elif isinstance(config, dict):
                mime_type = config.get("response_mime_type", "")

            if mime_type == "application/json":
                response_format = {"type": "json_object"}
                if "JSON" not in contents.upper():
                    contents += "\nReturn JSON only."

        messages = [{"role": "user", "content": contents}]

        response = self._openai_client.chat.completions.create(
            model=model or self.model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )

        class FakeResponse:
            def __init__(self, text):
                self.text = text

        return FakeResponse(response.choices[0].message.content or "")


class FakeChat:
    def __init__(self, openai_client, model, config):
        self.client = openai_client
        self.model = model
        self.config = config
        self.history = []

    def send_message(self, message: str) -> Any:
        self.history.append({"role": "user", "content": message})

        temperature = 0.2
        if self.config:
            if hasattr(self.config, "temperature"):
                temperature = self.config.temperature or 0.2
            elif isinstance(self.config, dict):
                temperature = self.config.get("temperature", 0.2)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.history,
            temperature=temperature,
        )

        reply = response.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": reply})

        class FakeResponse:
            def __init__(self, text):
                self.text = text

        return FakeResponse(reply)


def get_ai_client(config: Optional[Dict[str, str]] = None, tier: Optional[str] = None):
    """
    根据配置获取相应的 AI 客户端。
    如果指定了 tier，则会根据配置的 provider 自动选择对应的推理或极速模型。
    """
    if config is None:
        config = load_ai_config(tier=tier)
    elif tier:
        # 如果提供了 config 但又指定了 tier，则更新 config 中的 model
        provider = normalize_provider(config.get("provider", "gemini"))
        config["model"] = get_model_by_tier(provider, tier)

    provider = normalize_provider(config.get("provider", "gemini"))
    api_key = config.get("api_key", "")
    model = config.get("model", "") or get_model_by_tier(provider, "fast")

    if provider == "gemini":
        from google import genai

        return genai.Client(api_key=api_key)
    if provider == "deepseek":
        return GeminiCompatibilityClient(provider, api_key, model, config.get("base_url"))
    raise ValueError(f"不支持的 AI 供应商: {provider}")


def create_generation_config(
    config: Dict[str, str],
    *,
    response_mime_type: str = "",
    temperature: float = 0.2,
    seed: Optional[int] = None,
    thinking_budget: Optional[int] = None,
) -> Any:
    provider = normalize_provider(config.get("provider", "gemini"))
    if provider == "gemini":
        from google.genai import types

        kwargs: Dict[str, Any] = {"temperature": temperature}
        if response_mime_type:
            kwargs["response_mime_type"] = response_mime_type
        if seed is not None:
            kwargs["seed"] = seed
        if thinking_budget is not None:
            try:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
            except (AttributeError, TypeError):
                pass
        try:
            return types.GenerateContentConfig(**kwargs)
        except TypeError:
            kwargs.pop("seed", None)
            return types.GenerateContentConfig(**kwargs)

    payload: Dict[str, Any] = {"temperature": temperature}
    if response_mime_type:
        payload["response_mime_type"] = response_mime_type
    if seed is not None:
        payload["seed"] = seed
    return payload


def parse_ai_json(raw: str) -> dict:
    """
    从 AI 响应文本中健壮地提取并解析 JSON 对象。
    """
    if not raw:
        raise ValueError("AI 返回为空")

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    stripped = raw.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if match:
        inner = match.group(1)
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            raw = inner

    try:
        from json_repair import repair_json  # type: ignore

        obj = repair_json(raw, return_objects=True)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    start = raw.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(raw[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start : i + 1]
                    try:
                        return json.loads(candidate)
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
        f"无法从 AI 响应中提取有效 JSON（响应长度 {len(raw)} 字符）\n"
        f"前500字符：{raw[:500]}"
    )


def parse_gemini_json(raw: str) -> dict:
    """旧函数名兼容"""
    return parse_ai_json(raw)


if __name__ == "__main__":
    try:
        cfg = load_ai_config()
        print(f"Provider: {cfg['provider']}")
        print(f"Model: {cfg['model']}")
        print(f"API Key: {mask_secret(cfg['api_key'], show=6)}")
    except Exception as e:
        print(f"Error: {e}")
