"""
HAP 工作表字段类型定义 — 完整版（38 种，已全部通过 API 创建验证）。

来源：SaveWorksheetControls API 逐 type 测试 + 明道云前端字段编辑面板。
录制时间：2026-04-03
"""

from __future__ import annotations

FIELD_REGISTRY = {
    # ── 基础文本 ──
    "Text": {
        "controlType": 2, "name": "文本", "category": "basic",
        "can_be_title": True,
        "doc": "单行文本。第一个自动设为标题(attribute=1)。",
    },
    "RichText": {
        "controlType": 41, "name": "富文本", "category": "basic",
        "doc": "富文本编辑器，支持格式化。",
    },
    "AutoNumber": {
        "controlType": 33, "name": "自动编号", "category": "basic",
        "doc": "自动递增编号，advancedSetting 可配前缀和格式。",
    },
    "TextCombine": {
        "controlType": 32, "name": "文本组合", "category": "basic",
        "doc": "多字段文本拼接。",
    },

    # ── 数值 ──
    "Number": {
        "controlType": 6, "name": "数值", "category": "number",
        "doc": "数字字段，precision=2。",
        "api_extra": {"dot": 2},
    },
    "Money": {
        "controlType": 8, "name": "金额", "category": "number",
        "doc": "金额字段，precision=2, unit=¥。",
        "api_extra": {"dot": 2, "unit": "¥"},
    },
    "MoneyCapital": {
        "controlType": 25, "name": "大写金额", "category": "number",
        "doc": "金额转大写（中文）。",
    },
    "Formula": {
        "controlType": 31, "name": "公式", "category": "number",
        "doc": "数值计算公式。",
    },
    "FormulaDate": {
        "controlType": 38, "name": "公式日期", "category": "number",
        "doc": "日期计算公式（如到期天数）。",
    },

    # ── 选择 ──
    "SingleSelect": {
        "controlType": 9, "name": "单选", "category": "select",
        "doc": "单选字段，需 option_values(3-8 项)。",
        "requires_options": True,
    },
    "MultipleSelect": {
        "controlType": 10, "name": "多选", "category": "select",
        "doc": "多选字段，需 option_values。",
        "requires_options": True,
    },
    "Dropdown": {
        "controlType": 11, "name": "下拉框", "category": "select",
        "doc": "下拉选择，用于看板分组。需 option_values。",
        "requires_options": True,
    },
    "Checkbox": {
        "controlType": 36, "name": "检查框", "category": "select",
        "doc": "布尔开关（是/否）。",
    },
    "Rating": {
        "controlType": 28, "name": "等级", "category": "select",
        "doc": "等级评分（如 1-5 星）。",
    },
    "Score": {
        "controlType": 47, "name": "评分", "category": "select",
        "doc": "评分字段，可配最大分值。",
    },

    # ── 日期时间 ──
    "Date": {
        "controlType": 15, "name": "日期", "category": "date",
        "doc": "日期字段（无时间）。适合甘特图、日历视图。",
    },
    "DateTime": {
        "controlType": 16, "name": "日期时间", "category": "date",
        "doc": "日期+时间。适合日历视图。",
    },
    "Time": {
        "controlType": 46, "name": "时间", "category": "date",
        "doc": "仅时间字段（时:分）。",
    },

    # ── 联系方式 ──
    "Phone": {
        "controlType": 3, "name": "电话", "category": "contact",
        "doc": "手机号码字段。",
    },
    "Landline": {
        "controlType": 4, "name": "座机", "category": "contact",
        "doc": "座机电话字段。",
    },
    "Email": {
        "controlType": 5, "name": "邮箱", "category": "contact",
        "doc": "邮箱地址字段。",
    },
    "Link": {
        "controlType": 7, "name": "链接", "category": "contact",
        "doc": "URL 链接字段。",
    },

    # ── 人员组织 ──
    "Collaborator": {
        "controlType": 26, "name": "成员", "category": "people",
        "doc": "成员字段，required 强制 false。",
        "force_not_required": True,
    },
    "Department": {
        "controlType": 27, "name": "部门", "category": "people",
        "doc": "部门选择字段。",
    },
    "OrgRole": {
        "controlType": 48, "name": "组织角色", "category": "people",
        "doc": "组织角色选择字段。",
    },

    # ── 关联 ──
    "Relation": {
        "controlType": 29, "name": "关联记录", "category": "relation",
        "doc": "关联字段，需 relation_target。第二阶段创建。",
        "requires_relation_target": True,
    },
    "OtherTableField": {
        "controlType": 30, "name": "他表字段", "category": "relation",
        "doc": "引用关联表字段值，需先有关联字段。",
    },
    "SubTable": {
        "controlType": 34, "name": "子表", "category": "relation",
        "doc": "子表（嵌入式关联表）。",
    },
    "Cascade": {
        "controlType": 35, "name": "级联选择", "category": "relation",
        "doc": "级联多级选择（如省/市/区）。",
    },
    "Rollup": {
        "controlType": 37, "name": "汇总", "category": "relation",
        "doc": "汇总关联表数据（求和/计数/平均等），需先有关联字段。",
    },

    # ── 文件 ──
    "Attachment": {
        "controlType": 14, "name": "附件", "category": "file",
        "doc": "文件上传，支持图片、文档等。",
    },
    "Signature": {
        "controlType": 42, "name": "签名", "category": "file",
        "doc": "手写签名字段。",
    },

    # ── 地理位置 ──
    "Area": {
        "controlType": 24, "name": "地区", "category": "location",
        "doc": "地区选择（省/市/区）。适合地图图表。",
    },
    "Location": {
        "controlType": 40, "name": "定位", "category": "location",
        "doc": "GPS 定位字段。",
    },

    # ── 高级/布局 ──
    "QRCode": {
        "controlType": 43, "name": "二维码", "category": "advanced",
        "doc": "自动生成二维码。",
    },
    "Embed": {
        "controlType": 45, "name": "嵌入", "category": "advanced",
        "doc": "嵌入外部网页。",
    },
    "Section": {
        "controlType": 22, "name": "分段", "category": "layout",
        "doc": "表单分段标题（不存储数据）。",
    },
    "Remark": {
        "controlType": 49, "name": "备注说明", "category": "layout",
        "doc": "表单中的静态文本说明。",
    },
}

# ── 便捷映射 ────────────────────────────────────────────────────────────────

FIELD_TYPE_MAP: dict[str, int] = {k: v["controlType"] for k, v in FIELD_REGISTRY.items()}
FIELD_TYPE_NAMES: dict[int, str] = {v["controlType"]: v["name"] for v in FIELD_REGISTRY.values()}
ALLOWED_FIELD_TYPES: set[str] = set(FIELD_REGISTRY.keys())
PLANNABLE_TYPES: set[str] = {k for k, v in FIELD_REGISTRY.items() if v.get("category") not in ("layout", "advanced")}
OPTION_REQUIRED_TYPES: set[str] = {k for k, v in FIELD_REGISTRY.items() if v.get("requires_options")}
FIELD_CATEGORIES: dict[str, list[str]] = {}
for _k, _v in FIELD_REGISTRY.items():
    FIELD_CATEGORIES.setdefault(_v.get("category", "other"), []).append(_k)
