"""
HAP 工作表字段类型定义。

AI 规划时用字符串（Text/Number/...），API 创建时用 controlType 数字。
此模块统一管理映射关系和各类型的约束。
"""

from __future__ import annotations

# ─── 字段类型注册表 ──────────────────────────────────────────────────────────

FIELD_REGISTRY = {
    "Text": {
        "controlType": 2,
        "name": "文本",
        "can_be_title": True,
        "doc": "单行文本。第一个 Text 字段默认为标题字段(isTitle=1)。",
        "api_extra": {},
    },
    "Number": {
        "controlType": 6,
        "name": "数字",
        "can_be_title": False,
        "doc": "数值字段。默认 precision=2。",
        "api_extra": {"precision": 2},
    },
    "Money": {
        "controlType": 8,
        "name": "金额",
        "can_be_title": False,
        "doc": "金额字段。默认 precision=2，unit='¥'。",
        "api_extra": {"precision": 2, "unit": "¥"},
    },
    "SingleSelect": {
        "controlType": 9,
        "name": "单选",
        "can_be_title": False,
        "doc": "单选字段。必须提供 option_values（3-8 个）。",
        "requires_options": True,
        "api_extra": {},
    },
    "MultipleSelect": {
        "controlType": 10,
        "name": "多选",
        "can_be_title": False,
        "doc": "多选字段。必须提供 option_values。",
        "requires_options": True,
        "api_extra": {},
    },
    "Dropdown": {
        "controlType": 11,
        "name": "下拉框",
        "can_be_title": False,
        "doc": "下拉选择。同单选，用于看板分组。",
        "requires_options": True,
        "api_extra": {},
    },
    "Date": {
        "controlType": 15,
        "name": "日期",
        "can_be_title": False,
        "doc": "日期字段（无时间）。适合甘特图、日历视图。",
        "api_extra": {},
    },
    "DateTime": {
        "controlType": 16,
        "name": "日期时间",
        "can_be_title": False,
        "doc": "日期+时间。适合日历视图、时间线。",
        "api_extra": {},
    },
    "Collaborator": {
        "controlType": 26,
        "name": "成员",
        "can_be_title": False,
        "doc": "成员字段。required 强制为 false。subType=0(单选成员)。",
        "api_extra": {"subType": 0},
        "force_not_required": True,
    },
    "Relation": {
        "controlType": 29,
        "name": "关联",
        "can_be_title": False,
        "doc": "关联字段。需指定 relation_target（目标工作表名）。第二阶段创建。",
        "requires_relation_target": True,
        "api_extra": {},
    },
    "Attachment": {
        "controlType": 14,
        "name": "附件",
        "can_be_title": False,
        "doc": "附件/文件上传。",
        "api_extra": {},
    },
    "RichText": {
        "controlType": 41,
        "name": "富文本",
        "can_be_title": False,
        "doc": "富文本编辑器。适合长文描述。",
        "api_extra": {},
    },
    "Phone": {
        "controlType": 3,
        "name": "电话",
        "can_be_title": False,
        "doc": "电话号码字段。",
        "api_extra": {},
    },
    "Email": {
        "controlType": 5,
        "name": "邮箱",
        "can_be_title": False,
        "doc": "邮箱地址字段。",
        "api_extra": {},
    },
    "Area": {
        "controlType": 24,
        "name": "地区",
        "can_be_title": False,
        "doc": "地区选择（省/市/区）。适合地图图表。",
        "api_extra": {},
    },
}

# ─── 便捷映射 ─────────────────────────────────────────────────────────────────

# AI 字符串 → controlType 数字
FIELD_TYPE_MAP: dict[str, int] = {k: v["controlType"] for k, v in FIELD_REGISTRY.items()}

# controlType 数字 → 中文名
FIELD_TYPE_NAMES: dict[int, str] = {v["controlType"]: v["name"] for v in FIELD_REGISTRY.values()}

# AI 规划时允许的字段类型字符串
ALLOWED_FIELD_TYPES: set[str] = set(FIELD_REGISTRY.keys())

# 需要 option_values 的类型
OPTION_REQUIRED_TYPES: set[str] = {k for k, v in FIELD_REGISTRY.items() if v.get("requires_options")}
