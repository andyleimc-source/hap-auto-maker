"""
视图类型注册中心。

管理 HAP 支持的所有视图类型及其配置约束。

用法:
    from views import VIEW_REGISTRY, ALLOWED_VIEW_TYPES
"""

from __future__ import annotations
from .view_types import VIEW_REGISTRY, ALLOWED_VIEW_TYPES, VIEW_TYPE_NAMES
