"""
工作表字段类型注册中心。

管理 HAP 支持的所有字段类型（AI 规划用字符串枚举 ↔ API 用 controlType 数字）。

用法:
    from worksheets import FIELD_REGISTRY, FIELD_TYPE_MAP
"""

from __future__ import annotations
from .field_types import FIELD_REGISTRY, FIELD_TYPE_MAP, FIELD_TYPE_NAMES
