#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 模型统一调用工具。
支持 Gemini 和 DeepSeek。
统一从 config/credentials/ai_auth.json 加载配置，同时兼容旧 gemini_auth.json。
"""

import fcntl
import json
import queue
import re
import threading
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

# DeepSeek 统一使用推理模型：deepseek-chat max_tokens 仅 8K，不够骨架规划等大输出场景，
# deepseek-reasoner 支持 64K，统一切换避免截断。仅对 DeepSeek 生效，其他供应商不受影响。
_DEEPSEEK_RUNTIME_MODEL = "deepseek-reasoner"
_DEEPSEEK_RUNTIME_MAX_TOKENS = 65536  # deepseek-reasoner 上限 64K

# OpenAI 兼容流式请求保护参数（可被 create_generation_config 覆盖）
_OPENAI_STREAM_IDLE_TIMEOUT_SEC = 60.0
_OPENAI_STREAM_TOTAL_TIMEOUT_SEC = 420.0
_OPENAI_STREAM_FALLBACK_NON_STREAM = True

# 这些供应商只接受 temperature=1，传其他值会报 400
_PROVIDERS_TEMPERATURE_FIXED_TO_1 = {"kimi"}

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
# 来源：各供应商官方文档（2026-04）。实际调用优先用 list_models()，此为 fallback。
# 经测试：MiniMax /models → 404（已确认不支持）。
PROVIDER_KNOWN_MODELS = {
    # 来源：https://platform.minimaxi.com/docs/guides/text-generation（2026-04）
    "minimax": [
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5",
        "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1",
        "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
    ],
    # 来源：https://platform.moonshot.cn/docs/api/chat（2026-04）
    "kimi": [
        "moonshot-v1-auto",
        "moonshot-v1-8k",
        "moonshot-v1-32k",
        "moonshot-v1-128k",
        "kimi-k2.5",
        "kimi-k2-thinking",
        "kimi-k2-thinking-turbo",
    ],
    # 来源：https://bigmodel.cn/dev/howuse/model（2026-04）
    "zhipu": [
        "glm-5.1",
        "glm-5",
        "glm-5-turbo",
        "glm-4.7",
        "glm-4.7-flash",
        "glm-4.7-flashx",
        "glm-4.6",
        "glm-4.5-air",
        "glm-4.5-airx",
        "glm-4-long",
        "glm-4-flash-250414",
    ],
    # 来源：https://www.volcengine.com/docs/82379/1330310（2026-04）
    # 注意：豆包模型 ID 带日期后缀，需使用完整 ID 调用
    "doubao": [
        "doubao-seed-2-0-pro-260215",
        "doubao-seed-2-0-lite-260215",
        "doubao-seed-2-0-mini-260215",
        "doubao-seed-1-8-251228",
        "doubao-1-5-pro-32k-250115",
        "doubao-1-5-lite-32k-250115",
    ],
    # 来源：https://help.aliyun.com/zh/model-studio/getting-started/models（2026-04）
    "qwen": [
        "qwen3-max",
        "qwen3-plus",
        "qwen3-flash",
        "qwen-max",
        "qwen-plus",
        "qwen-turbo",
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

# Token 使用量追踪（进程内线程安全聚合）
_TOKEN_STATS_LOCK = threading.Lock()
_TOKEN_STATS = {
    "by_model": {},
    "total_input": 0,
    "total_output": 0,
}


def _coerce_token_int(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _read_usage_field(usage: Any, field: str) -> Any:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(field)
    return getattr(usage, field, None)


def _extract_token_usage(usage: Any) -> tuple[int, int]:
    """兼容 Gemini/OpenAI 不同 usage 字段命名。"""
    input_tokens = _coerce_token_int(
        _read_usage_field(usage, "input_tokens")
        or _read_usage_field(usage, "prompt_tokens")
        or _read_usage_field(usage, "prompt_token_count")
    )
    output_tokens = _coerce_token_int(
        _read_usage_field(usage, "output_tokens")
        or _read_usage_field(usage, "completion_tokens")
        or _read_usage_field(usage, "candidates_token_count")
    )

    if output_tokens == 0:
        total_tokens = _coerce_token_int(
            _read_usage_field(usage, "total_tokens")
            or _read_usage_field(usage, "total_token_count")
        )
        if total_tokens > input_tokens:
            output_tokens = total_tokens - input_tokens

    return input_tokens, output_tokens


def record_token_usage(model: str, input_tokens: Any, output_tokens: Any) -> None:
    """记录 token 使用量，失败时由调用方自行兜底。"""
    model_name = str(model or "").strip() or "(unknown)"
    in_tokens = _coerce_token_int(input_tokens)
    out_tokens = _coerce_token_int(output_tokens)
    if in_tokens == 0 and out_tokens == 0:
        return

    with _TOKEN_STATS_LOCK:
        model_stats = _TOKEN_STATS["by_model"].setdefault(
            model_name,
            {"input_tokens": 0, "output_tokens": 0},
        )
        model_stats["input_tokens"] += in_tokens
        model_stats["output_tokens"] += out_tokens
        _TOKEN_STATS["total_input"] += in_tokens
        _TOKEN_STATS["total_output"] += out_tokens


def get_token_stats() -> Dict[str, Any]:
    with _TOKEN_STATS_LOCK:
        return {
            "by_model": {
                model: {
                    "input_tokens": stats["input_tokens"],
                    "output_tokens": stats["output_tokens"],
                }
                for model, stats in _TOKEN_STATS["by_model"].items()
            },
            "total_input": _TOKEN_STATS["total_input"],
            "total_output": _TOKEN_STATS["total_output"],
        }


def _safe_record_response_usage(model: str, usage: Any) -> None:
    try:
        input_tokens, output_tokens = _extract_token_usage(usage)
        record_token_usage(model, input_tokens, output_tokens)
    except Exception:
        pass


def _should_retry_without_usage_stream_option(exc: Exception) -> bool:
    text = str(exc or "").lower()
    return "stream_options" in text or "include_usage" in text


def _create_openai_usage_stream(openai_client, **kwargs):
    try:
        return openai_client.chat.completions.create(
            **kwargs,
            stream=True,
            stream_options={"include_usage": True},
        )
    except Exception as exc:
        if not _should_retry_without_usage_stream_option(exc):
            raise
        return openai_client.chat.completions.create(**kwargs, stream=True)


def _read_config_value(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    if hasattr(config, key):
        value = getattr(config, key, default)
        return default if value is None else value
    if isinstance(config, dict):
        value = config.get(key, default)
        return default if value is None else value
    return default


def _safe_float(value: Any, default: float, *, min_value: float = 0.1) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= min_value else default


def _resolve_effective_model(provider: str, requested_model: str) -> tuple[str, int]:
    """返回当前 provider 实际使用模型和 max_tokens。"""
    effective_model = requested_model
    max_tok = 32768
    if provider == "deepseek":
        effective_model = _DEEPSEEK_RUNTIME_MODEL
        max_tok = _DEEPSEEK_RUNTIME_MAX_TOKENS
    return effective_model, max_tok


def resolve_effective_model_name(provider: str, requested_model: str) -> str:
    """
    对外暴露“实际调用模型”解析，便于入口日志打印，避免用户误判卡在哪个模型。
    """
    return _resolve_effective_model(normalize_provider(provider), requested_model)[0]


def _consume_stream_with_watchdog(
    stream: Any,
    *,
    idle_timeout_sec: float,
    total_timeout_sec: float,
) -> tuple[list[str], Any]:
    """
    用后台线程消费流，主线程通过队列监督空闲/总时长。
    解决 stream 连接不断开但长时间无有效输出时主线程永久阻塞的问题。
    """
    event_q: queue.Queue[tuple[str, Any]] = queue.Queue()
    stop_event = threading.Event()

    def _worker() -> None:
        try:
            for chunk in stream:
                if stop_event.is_set():
                    break
                event_q.put(("chunk", chunk))
            event_q.put(("done", None))
        except Exception as exc:  # pragma: no cover - 通过外层行为验证
            event_q.put(("error", exc))

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()

    started_at = time.monotonic()
    chunks: list[str] = []
    usage = None

    while True:
        elapsed = time.monotonic() - started_at
        remaining_total = total_timeout_sec - elapsed
        if remaining_total <= 0:
            stop_event.set()
            raise TimeoutError(f"流式响应超过总时限 {total_timeout_sec:.1f}s")

        wait_timeout = min(idle_timeout_sec, remaining_total)
        try:
            event_type, payload = event_q.get(timeout=wait_timeout)
        except queue.Empty:
            stop_event.set()
            raise TimeoutError(f"流式响应空闲超过 {idle_timeout_sec:.1f}s")

        if event_type == "error":
            raise payload
        if event_type == "done":
            return chunks, usage

        chunk = payload
        chunk_usage = getattr(chunk, "usage", None)
        if chunk_usage:
            usage = chunk_usage
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            chunks.append(delta)


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
        return FakeChat(self._openai_client, model or self.model, config, provider=self.provider)

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

        if self.provider in _PROVIDERS_TEMPERATURE_FIXED_TO_1:
            temperature = 1

        # DeepSeek：运行时强制切换到推理模型，获得 64K 输出上限
        effective_model, max_tok = _resolve_effective_model(self.provider, model or self.model)

        messages = [{"role": "user", "content": contents}]
        request_timeout_sec = _safe_float(
            _read_config_value(config, "request_timeout_sec", 300.0),
            300.0,
        )
        stream_idle_timeout_sec = _safe_float(
            _read_config_value(config, "stream_idle_timeout_sec", _OPENAI_STREAM_IDLE_TIMEOUT_SEC),
            _OPENAI_STREAM_IDLE_TIMEOUT_SEC,
        )
        stream_total_timeout_sec = _safe_float(
            _read_config_value(config, "stream_total_timeout_sec", _OPENAI_STREAM_TOTAL_TIMEOUT_SEC),
            _OPENAI_STREAM_TOTAL_TIMEOUT_SEC,
        )
        fallback_non_stream = bool(
            _read_config_value(config, "stream_fallback_non_stream", _OPENAI_STREAM_FALLBACK_NON_STREAM)
        )

        # 增加重试逻辑，应对推理模型长时间思考导致的连接中断
        max_retries = 3
        last_exception = None

        for attempt in range(max_retries):
            try:
                # 使用流式请求，逐 chunk 接收，避免大响应时服务端 chunked 连接中断
                stream = _create_openai_usage_stream(
                    self._openai_client,
                    model=effective_model,
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format,
                    max_tokens=max_tok,
                    timeout=request_timeout_sec,
                )
                chunks, usage = _consume_stream_with_watchdog(
                    stream,
                    idle_timeout_sec=stream_idle_timeout_sec,
                    total_timeout_sec=stream_total_timeout_sec,
                )
                _safe_record_response_usage(effective_model, usage)

                class FakeResponse:
                    def __init__(self, text):
                        self.text = text

                return FakeResponse("".join(chunks))
            except (openai.APIConnectionError, openai.APITimeoutError, TimeoutError) as e:
                last_exception = e
                wait_time = (attempt + 1) * 5
                print(f"\n      ⚠️  AI 连接异常 ({type(e).__name__})，正在进行第 {attempt+1}/{max_retries} 次重试，等待 {wait_time}s...")
                time.sleep(wait_time)
            except Exception as e:
                # 其他异常直接抛出
                raise e

        if fallback_non_stream:
            try:
                print("\n      ↪️  流式模式失败，回退到非流式请求重试一次...")
                resp = self._openai_client.chat.completions.create(
                    model=effective_model,
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format,
                    max_tokens=max_tok,
                    timeout=request_timeout_sec,
                )
                _safe_record_response_usage(effective_model, getattr(resp, "usage", None))
                text = resp.choices[0].message.content or ""

                class FakeResponse:
                    def __init__(self, text):
                        self.text = text

                return FakeResponse(text)
            except Exception as fallback_exc:
                last_exception = fallback_exc

        detail = (
            f"AI 请求失败(provider={self.provider}, configured_model={model or self.model}, "
            f"effective_model={effective_model}, request_timeout={request_timeout_sec}s, "
            f"stream_idle_timeout={stream_idle_timeout_sec}s, stream_total_timeout={stream_total_timeout_sec}s, "
            f"retries={max_retries}, fallback_non_stream={fallback_non_stream})"
        )
        if last_exception:
            raise RuntimeError(f"{detail}，last_error={type(last_exception).__name__}: {last_exception}") from last_exception
        raise RuntimeError(detail)


class FakeChat:
    def __init__(self, openai_client, model, config, provider: str = ""):
        self.client = openai_client
        self.model = model
        self.config = config
        self.provider = provider
        self.history = []

    def send_message(self, message: str) -> Any:
        self.history.append({"role": "user", "content": message})

        temperature = 0.2
        if self.config:
            if hasattr(self.config, "temperature"):
                temperature = self.config.temperature or 0.2
            elif isinstance(self.config, dict):
                temperature = self.config.get("temperature", 0.2)

        if self.provider in _PROVIDERS_TEMPERATURE_FIXED_TO_1:
            temperature = 1

        # DeepSeek：运行时强制切换到推理模型
        effective_model, max_tok = _resolve_effective_model(self.provider, self.model)

        response = self.client.chat.completions.create(
            model=effective_model,
            messages=self.history,
            temperature=temperature,
            max_tokens=max_tok,
        )
        _safe_record_response_usage(effective_model, getattr(response, "usage", None))

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
        resp = self._client.models.generate_content(model=model, contents=contents, config=config)
        _safe_record_response_usage(model or self._model, getattr(resp, "usage_metadata", None))
        return resp


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
        resp = self._chat.send_message(message)
        _safe_record_response_usage(self._model, getattr(resp, "usage_metadata", None))
        return resp


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
    request_timeout_sec: Optional[float] = None,
    stream_idle_timeout_sec: Optional[float] = None,
    stream_total_timeout_sec: Optional[float] = None,
    stream_fallback_non_stream: Optional[bool] = None,
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
    if request_timeout_sec is not None:
        payload["request_timeout_sec"] = request_timeout_sec
    if stream_idle_timeout_sec is not None:
        payload["stream_idle_timeout_sec"] = stream_idle_timeout_sec
    if stream_total_timeout_sec is not None:
        payload["stream_total_timeout_sec"] = stream_total_timeout_sec
    if stream_fallback_non_stream is not None:
        payload["stream_fallback_non_stream"] = stream_fallback_non_stream
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
