#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 模型统一调用工具。
支持 Gemini 和 DeepSeek。
统一从 config/credentials/ai_auth.json 加载配置，同时兼容旧 gemini_auth.json。
"""

import fcntl
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parents[2]
AI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "ai_auth.json"
GEMINI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"  # 向后兼容别名

# 所有 OpenAI 兼容供应商的默认 base_url（Gemini 不在此表，使用 google-genai SDK）
PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "minimax":  "https://api.minimaxi.com/v1",
    "kimi":     "https://api.moonshot.cn/v1",
    "zhipu":    "https://open.bigmodel.cn/api/paas/v4",
    "doubao":   "https://ark.cn-beijing.volces.com/api/v3",
    "qwen":     "https://dashscope.aliyuncs.com/compatible-mode/v1",
}

# 各供应商已知模型列表（供 /models 端点不支持时作 fallback）。
# 经测试：MiniMax /models → 404；其余供应商按文档收录，实际支持情况以 list_models() 为准。
PROVIDER_KNOWN_MODELS = {
    "minimax": [
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ],
    "kimi": [
        "moonshot-v1-auto",
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
        "kimi-k2.5",
    ],
    "zhipu": [
        "glm-4-flash",
        "glm-4-air",
        "glm-4",
        "glm-4-long",
    ],
    "doubao": [
        "doubao-pro-32k",
        "doubao-pro-128k",
        "doubao-lite-32k",
        "doubao-lite-128k",
    ],
    "qwen": [
        "qwen-plus",
        "qwen-turbo",
        "qwen-max",
        "qwen-long",
    ],
}

# RPD 使用量追踪（跨进程，按日期 + 模型统计）
_RPD_USAGE_FILE = BASE_DIR / "config" / "gemini_rpd_usage.json"
_RPD_USAGE_LOCK = BASE_DIR / "config" / "gemini_rpd_usage.json.lock"

# RPD 配置上限（每日请求次数限额）- 付费账号第一层级实际限额
# gemini-2.5-flash: RPD=10K, RPM=1000, TPM=1M
RPD_LIMITS = {
    "gemini-2.5-flash": 10000,
    "gemini-2.5-pro":   1000,
}
# 留 5% 安全余量
RPD_SAFETY_MARGIN = 0.05


def _record_rpd(model: str) -> Dict[str, int]:
    """
    记录一次 Gemini 请求，返回今日当前计数 {"count": N, "limit": M}。
    多进程安全（文件锁 + 合并写入）。
    """
    today = date.today().isoformat()
    _RPD_USAGE_LOCK.touch(exist_ok=True)
    with open(_RPD_USAGE_LOCK, "r") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)
        try:
            if _RPD_USAGE_FILE.exists() and _RPD_USAGE_FILE.stat().st_size > 0:
                data = json.loads(_RPD_USAGE_FILE.read_text(encoding="utf-8"))
            else:
                data = {}
            day_data = data.setdefault(today, {})
            day_data[model] = day_data.get(model, 0) + 1
            _RPD_USAGE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            count = day_data[model]
        finally:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
    limit = RPD_LIMITS.get(model, 0)
    return {"count": count, "limit": limit}


def get_rpd_usage(model: str = None) -> Dict:
    """查询今日 RPD 使用量。不传 model 则返回所有模型的汇总。"""
    today = date.today().isoformat()
    if not _RPD_USAGE_FILE.exists():
        return {}
    data = json.loads(_RPD_USAGE_FILE.read_text(encoding="utf-8"))
    day_data = data.get(today, {})
    if model:
        count = day_data.get(model, 0)
        limit = RPD_LIMITS.get(model, 0)
        used_pct = round(count / limit * 100, 1) if limit else 0
        return {"model": model, "date": today, "count": count, "limit": limit, "used_pct": used_pct}
    # 返回所有模型
    result = {}
    for m, cnt in day_data.items():
        lim = RPD_LIMITS.get(m, 0)
        result[m] = {
            "count": cnt,
            "limit": lim,
            "used_pct": round(cnt / lim * 100, 1) if lim else 0,
        }
    return {"date": today, "models": result}

# Gemini/DeepSeek 保留 fallback；新供应商无预设模型，必须由用户选择
DEFAULT_MODELS = {
    "gemini":   DEFAULT_GEMINI_MODEL,
    "deepseek": DEFAULT_DEEPSEEK_MODEL,
}


def normalize_provider(provider: str) -> str:
    raw = str(provider or "").strip().lower()
    if raw in {"", "gemini", "google", "google-genai"}:
        return "gemini"
    if raw in {"deepseek", "deepseek-chat", "deepseek-reasoner"}:
        return "deepseek"
    if raw == "minimax":
        return "minimax"
    if raw in {"kimi", "moonshot"}:
        return "kimi"
    if raw in {"zhipu", "glm", "bigmodel"}:
        return "zhipu"
    if raw in {"doubao", "ark", "volcengine"}:
        return "doubao"
    if raw in {"qwen", "qianwen", "dashscope"}:
        return "qwen"
    supported = "gemini / deepseek / minimax / kimi / zhipu / doubao / qwen"
    raise ValueError(f"不支持的 AI 供应商: {provider}。支持的供应商: {supported}")


def default_model_for_provider(provider: str) -> str:
    """返回供应商的 fallback 模型名。新供应商无默认，返回空字符串。"""
    return DEFAULT_MODELS.get(normalize_provider(provider), "")


def list_models(provider: str, api_key: str, base_url: str = "") -> list:
    """
    从厂商 API 拉取可用模型列表。失败时返回空列表。
    Gemini 使用 google-genai SDK；其余供应商均 OpenAI 兼容，统一使用 openai SDK。
    """
    p = normalize_provider(provider)
    try:
        if p == "gemini":
            from google import genai
            client = genai.Client(api_key=api_key)
            models = []
            for m in client.models.list():
                name = m.name or ""
                short = name.replace("models/", "") if name.startswith("models/") else name
                if not short:
                    continue
                actions = [a.value if hasattr(a, "value") else str(a) for a in (m.supported_actions or [])]
                if "generateContent" not in actions:
                    continue
                if not short.startswith("gemini-"):
                    continue
                skip_keywords = ("-tts", "-audio", "-robotics", "-image", "-live", "-computer-use")
                if any(kw in short for kw in skip_keywords):
                    continue
                models.append(short)
            return sorted(models)

        # 所有 OpenAI 兼容供应商（deepseek / minimax / kimi / zhipu / doubao / qwen）
        if p in PROVIDER_BASE_URLS:
            from openai import OpenAI
            url = base_url or PROVIDER_BASE_URLS[p]
            client = OpenAI(api_key=api_key, base_url=url, timeout=15.0)
            resp = client.models.list()
            return sorted(m.id for m in resp.data if m.id)

    except Exception as e:
        print(f"  ⚠️  拉取 {p} 模型列表失败: {e}")
        if p in PROVIDER_KNOWN_MODELS:
            print(f"  📋  使用文档记载的已知模型列表作为备用")
            return PROVIDER_KNOWN_MODELS[p]
    return []


def default_base_url_for_provider(provider: str) -> str:
    return PROVIDER_BASE_URLS.get(normalize_provider(provider), "")


def mask_secret(value: str, show: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "(未填写)"
    if len(text) <= show:
        return text
    return text[:show] + "****"


def load_ai_config(config_path: Optional[Path] = None) -> Dict[str, str]:
    """
    加载 AI 配置。
    直接使用配置文件中的 model，若无则使用供应商默认模型。
    返回: {"provider": "gemini|deepseek", "api_key": "...", "model": "...", "base_url": "..."}
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
    model = str(data.get("model", "")).strip() or default_model_for_provider(provider)
    base_url = str(data.get("base_url", "")).strip() or default_base_url_for_provider(provider)

    if not api_key:
        raise ValueError(f"AI 配置缺少 api_key: {target_path}")

    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
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

        # 增加 300s 超时设置，防止推理模型思考时间过长导致连接断开
        self._openai_client = OpenAI(
            api_key=self.api_key, 
            base_url=self.base_url,
            timeout=300.0 
        )

    @property
    def models(self):
        return self

    @property
    def chats(self):
        return self

    def create(self, model: str, config: Any = None) -> Any:
        return FakeChat(self._openai_client, model or self.model, config)

    def generate_content(self, model: str, contents: str, config: Any = None) -> Any:
        import time
        import openai
        
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

        # 增加重试逻辑，应对推理模型长时间思考导致的连接中断
        max_retries = 3
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                # 使用流式请求，逐 chunk 接收，避免大响应时服务端 chunked 连接中断
                stream = self._openai_client.chat.completions.create(
                    model=model or self.model,
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format,
                    max_tokens=32768,
                    stream=True,
                )
                chunks = []
                for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        chunks.append(delta)

                class FakeResponse:
                    def __init__(self, text):
                        self.text = text

                return FakeResponse("".join(chunks))
            except (openai.APIConnectionError, openai.APITimeoutError) as e:
                last_exception = e
                wait_time = (attempt + 1) * 5
                print(f"\n      ⚠️  AI 连接异常 ({type(e).__name__})，正在进行第 {attempt+1}/{max_retries} 次重试，等待 {wait_time}s...")
                time.sleep(wait_time)
            except Exception as e:
                # 其他异常直接抛出
                raise e

        raise last_exception or RuntimeError("AI 请求多次重试后依然失败")


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


class _GeminiRpdWrapper:
    """
    包装原生 genai.Client，拦截 models.generate_content 和 chats.create，
    在每次实际请求前后记录 RPD 使用量。
    """

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    @property
    def models(self):
        return self

    @property
    def chats(self):
        return _GeminiChatsProxy(self._client.chats, self._model)

    def generate_content(self, model: str, contents, config=None):
        _record_rpd(model or self._model)
        return self._client.models.generate_content(model=model, contents=contents, config=config)


class _GeminiChatsProxy:
    def __init__(self, chats_obj, model: str):
        self._chats = chats_obj
        self._model = model

    def create(self, model: str, config=None):
        return _GeminiChatWrapper(self._chats.create(model=model, config=config), model or self._model)


class _GeminiChatWrapper:
    def __init__(self, chat, model: str):
        self._chat = chat
        self._model = model

    def send_message(self, message):
        _record_rpd(self._model)
        return self._chat.send_message(message)


def get_ai_client(config: Optional[Dict[str, str]] = None):
    """根据配置获取相应的 AI 客户端。"""
    if config is None:
        config = load_ai_config()

    provider = normalize_provider(config.get("provider", "gemini"))
    api_key = config.get("api_key", "")
    model = config.get("model", "") or default_model_for_provider(provider)

    if provider == "gemini":
        from google import genai
        raw_client = genai.Client(api_key=api_key)
        return _GeminiRpdWrapper(raw_client, model)

    # 所有 OpenAI 兼容供应商
    if provider in PROVIDER_BASE_URLS:
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
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "rpd":
        # 查询今日 RPD 使用量：python ai_utils.py rpd [model]
        model_arg = _sys.argv[2] if len(_sys.argv) > 2 else None
        usage = get_rpd_usage(model_arg)
        print(json.dumps(usage, ensure_ascii=False, indent=2))
    else:
        try:
            cfg = load_ai_config()
            print(f"Provider: {cfg['provider']}")
            print(f"Model: {cfg['model']}")
            print(f"API Key: {mask_secret(cfg['api_key'], show=6)}")
            print()
            usage = get_rpd_usage()
            today = usage.get("date", "")
            models_data = usage.get("models", {})
            if models_data:
                print(f"今日 RPD 使用量 ({today}):")
                for m, info in models_data.items():
                    print(f"  {m}: {info['count']}/{info['limit']} ({info['used_pct']}%)")
            else:
                print(f"今日 ({today}) 暂无 RPD 记录")
        except Exception as e:
            print(f"Error: {e}")
