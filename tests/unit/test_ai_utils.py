"""
tests/unit/test_ai_utils.py

parse_ai_json、normalize_provider 的单元测试。
不需要网络，不需要真实 API key。
"""

import json
import sys
from pathlib import Path

import pytest

# 让 import 能找到 scripts/hap
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))

from ai_utils import (
    GeminiCompatibilityClient,
    normalize_provider,
    parse_ai_json,
)


# ---------------------------------------------------------------------------
# normalize_provider
# ---------------------------------------------------------------------------


class TestNormalizeProvider:
    def test_empty_string_defaults_to_gemini(self):
        assert normalize_provider("") == "gemini"

    def test_gemini_variants(self):
        for v in ("gemini", "google", "google-genai", "Gemini", "GEMINI"):
            assert normalize_provider(v) == "gemini"

    def test_deepseek_variants(self):
        for v in ("deepseek", "deepseek-chat", "deepseek-reasoner"):
            assert normalize_provider(v) == "deepseek"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="不支持的 AI 供应商"):
            normalize_provider("openai")

    def test_minimax_variants(self):
        assert normalize_provider("minimax") == "minimax"
        assert normalize_provider("MiniMax") == "minimax"

    def test_kimi_variants(self):
        assert normalize_provider("kimi") == "kimi"
        assert normalize_provider("moonshot") == "kimi"

    def test_zhipu_variants(self):
        assert normalize_provider("zhipu") == "zhipu"
        assert normalize_provider("glm") == "zhipu"
        assert normalize_provider("bigmodel") == "zhipu"

    def test_doubao_variants(self):
        assert normalize_provider("doubao") == "doubao"
        assert normalize_provider("ark") == "doubao"
        assert normalize_provider("volcengine") == "doubao"

    def test_qwen_variants(self):
        assert normalize_provider("qwen") == "qwen"
        assert normalize_provider("qianwen") == "qwen"
        assert normalize_provider("dashscope") == "qwen"


# ---------------------------------------------------------------------------
# parse_ai_json — 核心场景
# ---------------------------------------------------------------------------


class TestParseAiJson:
    # 1. 正常 JSON 字符串
    def test_plain_json(self):
        raw = '{"key": "value", "num": 42}'
        result = parse_ai_json(raw)
        assert result == {"key": "value", "num": 42}

    # 2. JSON 包在 markdown fence 里
    def test_markdown_fence_json(self):
        raw = '```json\n{"a": 1}\n```'
        result = parse_ai_json(raw)
        assert result == {"a": 1}

    # 3. markdown fence 无语言标签
    def test_markdown_fence_no_lang(self):
        raw = '```\n{"b": 2}\n```'
        result = parse_ai_json(raw)
        assert result == {"b": 2}

    # 4. JSON 前后有多余文字（AI 常见输出）
    def test_json_with_surrounding_text(self):
        raw = '这是我的回答：\n{"plan": "ok"}\n以上是计划。'
        result = parse_ai_json(raw)
        assert result == {"plan": "ok"}

    # 5. 截断的 JSON（缺少结尾花括号）
    def test_truncated_json(self):
        # 有 json_repair 时能修复，没有时抛 ValueError —— 两种都接受
        raw = '{"name": "test", "value": 123'
        try:
            result = parse_ai_json(raw)
            assert isinstance(result, dict)
            assert result.get("name") == "test"
        except ValueError:
            pass  # json_repair 未安装时的预期行为

    # 6. 带尾随逗号的 JSON（非标准但 AI 常产生）
    def test_trailing_comma(self):
        # 有 json_repair 时能修复，没有时抛 ValueError —— 两种都接受
        raw = '{"items": [1, 2, 3,]}'
        try:
            result = parse_ai_json(raw)
            assert isinstance(result, dict)
            assert "items" in result
        except ValueError:
            pass  # json_repair 未安装时的预期行为

    # 7. 空字符串 → 抛出 ValueError
    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="AI 返回为空"):
            parse_ai_json("")

    # 8. 完全乱码 → 抛出 ValueError
    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            parse_ai_json("这不是JSON，完全无法解析的随机文字！@#$%")

    # 9. 嵌套对象
    def test_nested_object(self):
        raw = '{"outer": {"inner": [1, 2, 3]}}'
        result = parse_ai_json(raw)
        assert result["outer"]["inner"] == [1, 2, 3]

    # 10. 返回 list 而非 dict（应抛出或用 json_repair 包装）
    def test_list_root_raises_or_repairs(self):
        # AI 返回数组不是 dict，parse_ai_json 应报错（因为它期望 dict）
        raw = "[1, 2, 3]"
        with pytest.raises((ValueError, Exception)):
            parse_ai_json(raw)

    # 11. 单引号 JSON（非标准）
    def test_single_quote_json(self):
        raw = "{'key': 'value'}"
        # json_repair 通常能处理，不强制断言成功，但不应崩溃
        try:
            result = parse_ai_json(raw)
            assert isinstance(result, dict)
        except ValueError:
            pass  # 也接受失败，只要不是未捕获异常


# ---------------------------------------------------------------------------
# parse_ai_json — 边界值
# ---------------------------------------------------------------------------


class TestParseAiJsonEdge:
    def test_unicode_values(self):
        raw = '{"名称": "测试应用", "count": 3}'
        result = parse_ai_json(raw)
        assert result["名称"] == "测试应用"

    def test_large_json(self):
        big = {"field_" + str(i): i for i in range(200)}
        raw = json.dumps(big)
        result = parse_ai_json(raw)
        assert len(result) == 200

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            parse_ai_json("   \n\t  ")

    def test_json_with_comments_style_prefix(self):
        # 有些 AI 在 JSON 前加 // 注释
        raw = '// 以下是规划结果\n{"step": 1}'
        result = parse_ai_json(raw)
        assert result.get("step") == 1


# ---------------------------------------------------------------------------
# default_base_url_for_provider
# ---------------------------------------------------------------------------


class TestDefaultBaseUrl:
    def test_gemini_has_no_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("gemini") == ""

    def test_deepseek_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("deepseek") == "https://api.deepseek.com"

    def test_minimax_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("minimax") == "https://api.minimaxi.com/v1"

    def test_kimi_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("kimi") == "https://api.moonshot.cn/v1"

    def test_zhipu_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("zhipu") == "https://open.bigmodel.cn/api/paas/v4"

    def test_doubao_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("doubao") == "https://ark.cn-beijing.volces.com/api/v3"

    def test_qwen_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("qwen") == "https://dashscope.aliyuncs.com/compatible-mode/v1"


class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content, usage=None):
        self.choices = [_Choice(content)]
        self.usage = usage


class _NeverEndingStream:
    def __iter__(self):
        return self

    def __next__(self):
        import time

        time.sleep(10)
        return _Chunk("")


class _NonStreamResponse:
    def __init__(self, text):
        class _Message:
            def __init__(self, content):
                self.content = content

        class _ResponseChoice:
            def __init__(self, content):
                self.message = _Message(content)

        self.choices = [_ResponseChoice(text)]
        self.usage = None


class TestGeminiCompatibilityClient:
    def test_deepseek_force_reasoner_model(self):
        captured = []

        def fake_create(**kwargs):
            captured.append(kwargs)
            return [_Chunk('{"ok":1}')]

        client = GeminiCompatibilityClient(
            provider="deepseek",
            api_key="test",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        client._openai_client.chat.completions.create = fake_create
        resp = client.generate_content(
            model="deepseek-chat",
            contents="JSON only",
            config={"response_mime_type": "application/json"},
        )

        assert resp.text == '{"ok":1}'
        assert captured[0]["model"] == "deepseek-reasoner"
        assert captured[0]["max_tokens"] == 65536

    def test_stream_timeout_has_bounded_failure(self, monkeypatch):
        monkeypatch.setattr("ai_utils.time.sleep", lambda *_args, **_kwargs: None)

        client = GeminiCompatibilityClient(
            provider="deepseek",
            api_key="test",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        client._openai_client.chat.completions.create = lambda **_kwargs: _NeverEndingStream()

        with pytest.raises(RuntimeError) as exc_info:
            client.generate_content(
                model="deepseek-chat",
                contents="JSON only",
                config={
                    "response_mime_type": "application/json",
                    "stream_idle_timeout_sec": 0.2,
                    "stream_total_timeout_sec": 0.3,
                    "stream_fallback_non_stream": False,
                },
            )

        error_text = str(exc_info.value)
        assert "provider=deepseek" in error_text
        assert "configured_model=deepseek-chat" in error_text
        assert "effective_model=deepseek-reasoner" in error_text
        assert "stream_idle_timeout=0.2s" in error_text
        assert "stream_total_timeout=0.3s" in error_text

    def test_stream_timeout_fallback_to_non_stream_once(self, monkeypatch):
        monkeypatch.setattr("ai_utils.time.sleep", lambda *_args, **_kwargs: None)
        calls = []

        def fake_create(**kwargs):
            calls.append(kwargs)
            if kwargs.get("stream"):
                return _NeverEndingStream()
            return _NonStreamResponse('{"via":"fallback"}')

        client = GeminiCompatibilityClient(
            provider="deepseek",
            api_key="test",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        client._openai_client.chat.completions.create = fake_create

        resp = client.generate_content(
            model="deepseek-chat",
            contents="JSON only",
            config={
                "response_mime_type": "application/json",
                "stream_idle_timeout_sec": 0.2,
                "stream_total_timeout_sec": 0.3,
                "stream_fallback_non_stream": True,
            },
        )

        assert resp.text == '{"via":"fallback"}'
        assert any(call.get("stream") is True for call in calls)
        assert any(call.get("stream") is None for call in calls)
