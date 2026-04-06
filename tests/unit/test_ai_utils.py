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
