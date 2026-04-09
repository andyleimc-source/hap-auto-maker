#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HAP 多语言辅助（当前支持 zh / en）。"""

from __future__ import annotations

import os
from typing import Any

SUPPORTED_LANGUAGES = {"zh", "en"}
DEFAULT_LANGUAGE = "zh"


def normalize_language(value: Any, default: str = DEFAULT_LANGUAGE) -> str:
    lang = str(value or "").strip().lower()
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return default if default in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def get_runtime_language(default: str = DEFAULT_LANGUAGE) -> str:
    return normalize_language(os.environ.get("HAP_LANGUAGE", ""), default=default)


def language_from_spec(spec: dict | None, default: str = DEFAULT_LANGUAGE) -> str:
    if not isinstance(spec, dict):
        return normalize_language(default)
    meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
    return normalize_language(meta.get("language"), default=default)


def set_runtime_language(lang: str) -> str:
    normalized = normalize_language(lang)
    os.environ["HAP_LANGUAGE"] = normalized
    return normalized


def default_app_name(lang: str) -> str:
    return "CRM Automation App" if normalize_language(lang) == "en" else "CRM自动化应用"


def default_business_context(lang: str) -> str:
    return "General enterprise management scenario" if normalize_language(lang) == "en" else "通用企业管理场景"


def dashboard_section_name(lang: str) -> str:
    return "Dashboard" if normalize_language(lang) == "en" else "仪表盘"


def all_worksheets_section_name(lang: str) -> str:
    return "All Worksheets" if normalize_language(lang) == "en" else "全部"


def system_default_view_names(lang: str | None = None) -> set[str]:
    names = {"全部", "All", "视图", "View", ""}
    if lang:
        normalized = normalize_language(lang)
        if normalized == "en":
            return {"All", "View", ""}
        if normalized == "zh":
            return {"全部", "视图", ""}
    return names


def chatbot_lang_type(lang: str) -> int:
    return 1 if normalize_language(lang) == "en" else 0


def chatbot_fallback_greeting(name: str, lang: str) -> str:
    return f"Hello, I am {name}." if normalize_language(lang) == "en" else f"您好，我是{name}。"


def chart_time_label(lang: str) -> str:
    return "Created Time" if normalize_language(lang) == "en" else "创建时间"


def chart_record_count_label(lang: str) -> str:
    return "Record Count" if normalize_language(lang) == "en" else "记录数量"


def chart_summary_label(lang: str) -> str:
    return "Total" if normalize_language(lang) == "en" else "总计"


def record_summary_hint(lang: str) -> str:
    return (
        "One concise English summary describing the business meaning of this record"
        if normalize_language(lang) == "en"
        else "一句中文摘要"
    )


def region_example(lang: str) -> str:
    return "California/Los Angeles/Westwood" if normalize_language(lang) == "en" else "北京/北京市/朝阳区"


def location_example(lang: str) -> str:
    return (
        "1600 Amphitheatre Parkway, Mountain View, CA"
        if normalize_language(lang) == "en"
        else "上海市浦东新区张江高科技园区"
    )
