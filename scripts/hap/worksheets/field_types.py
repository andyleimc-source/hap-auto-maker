"""
HAP 工作表字段类型定义 — 完整版。

来源：
  - hap-utral-maker/api-specs/block1-private/worksheet/save-worksheet-controls.md（22 种已录制）
  - SaveWorksheetControls API 批量测试（type 1-54 全部可创建，但含内部类型）
  - 明道云前端字段编辑面板（约 36 种用户可见类型）

说明：
  - AI 规划时用 FIELD_REGISTRY 的 key（英文枚举名）
  - API 创建时用 controlType 数字
  - PLANNABLE_TYPES 是 AI 规划时应使用的类型子集（排除系统字段和高级字段）
"""

from __future__ import annotations

# ─── 完整字段类型注册表 ────────────────────────────────────────────────────────

FIELD_REGISTRY = {
    # ── 基础输入 ──
    "Text": {
        "controlType": 2,
        "name": "文本",
        "category": "basic",
        "can_be_title": True,
        "doc": "单行文本。第一个 Text 字段默认为标题(isTitle=1)。",
        "api_extra": {},
    },
    "RichText": {
        "controlType": 41,
        "name": "富文本",
        "category": "basic",
        "doc": "富文本编辑器。适合长文描述。",
        "api_extra": {},
    },
    "AutoNumber": {
        "controlType": 33,
        "name": "自动编号",
        "category": "basic",
        "doc": "自动递增编号。advancedSetting 可配前缀和格式。",
        "api_extra": {},
    },

    # ── 数值 ──
    "Number": {
        "controlType": 6,
        "name": "数值",
        "category": "number",
        "doc": "数字字段。precision=2。",
        "api_extra": {"precision": 2},
    },
    "Money": {
        "controlType": 8,
        "name": "金额",
        "category": "number",
        "doc": "金额字段。precision=2, unit='¥'。",
        "api_extra": {"precision": 2, "unit": "¥"},
    },
    "Formula": {
        "controlType": 31,
        "name": "公式",
        "category": "number",
        "doc": "计算公式字段。通过 advancedSetting 配置公式表达式。",
        "api_extra": {},
    },

    # ── 选择 ──
    "SingleSelect": {
        "controlType": 9,
        "name": "单选",
        "category": "select",
        "doc": "单选字段。必须提供 option_values（3-8 个）。",
        "requires_options": True,
        "api_extra": {},
    },
    "MultipleSelect": {
        "controlType": 10,
        "name": "多选",
        "category": "select",
        "doc": "多选字段。必须提供 option_values。",
        "requires_options": True,
        "api_extra": {},
    },
    "Dropdown": {
        "controlType": 11,
        "name": "下拉框",
        "category": "select",
        "doc": "下拉选择。用于看板分组。必须提供 option_values。",
        "requires_options": True,
        "api_extra": {},
    },
    "Checkbox": {
        "controlType": 36,
        "name": "检查框",
        "category": "select",
        "doc": "布尔值开关（是/否）。",
        "api_extra": {},
    },
    "Rating": {
        "controlType": 28,
        "name": "等级",
        "category": "select",
        "doc": "评分/等级字段（如 1-5 星）。",
        "api_extra": {},
    },
    "Score": {
        "controlType": 47,
        "name": "评分",
        "category": "select",
        "doc": "评分字段。advancedSetting 可配最大分值。",
        "api_extra": {},
    },

    # ── 日期时间 ──
    "Date": {
        "controlType": 15,
        "name": "日期",
        "category": "date",
        "doc": "日期字段（无时间）。适合甘特图、日历视图。",
        "api_extra": {},
    },
    "DateTime": {
        "controlType": 16,
        "name": "日期时间",
        "category": "date",
        "doc": "日期+时间。适合日历视图、时间线。",
        "api_extra": {},
    },
    "Time": {
        "controlType": 46,
        "name": "时间",
        "category": "date",
        "doc": "仅时间字段（时:分）。",
        "api_extra": {},
    },

    # ── 联系方式 ──
    "Phone": {
        "controlType": 3,
        "name": "电话",
        "category": "contact",
        "doc": "电话号码字段。",
        "api_extra": {},
    },
    "Email": {
        "controlType": 5,
        "name": "邮箱",
        "category": "contact",
        "doc": "邮箱地址字段。支持邮件发送。",
        "api_extra": {},
    },
    "Link": {
        "controlType": 7,
        "name": "链接",
        "category": "contact",
        "doc": "URL 链接字段。",
        "api_extra": {},
    },

    # ── 人员组织 ──
    "Collaborator": {
        "controlType": 26,
        "name": "成员",
        "category": "people",
        "doc": "单选成员。required 强制为 false。",
        "api_extra": {"subType": 0},
        "force_not_required": True,
    },
    "MultiCollaborator": {
        "controlType": 48,
        "name": "成员（多选）",
        "category": "people",
        "doc": "多选成员字段。",
        "api_extra": {},
        "force_not_required": True,
    },
    "Department": {
        "controlType": 27,
        "name": "部门",
        "category": "people",
        "doc": "部门选择字段。",
        "api_extra": {},
    },
    "OrgRole": {
        "controlType": 48,
        "name": "组织角色",
        "category": "people",
        "doc": "组织角色字段。",
        "api_extra": {},
    },

    # ── 关联 ──
    "Relation": {
        "controlType": 29,
        "name": "关联记录",
        "category": "relation",
        "doc": "关联字段。需指定 relation_target。第二阶段创建。",
        "requires_relation_target": True,
        "api_extra": {},
    },
    "SubTable": {
        "controlType": 34,
        "name": "子表",
        "category": "relation",
        "doc": "子表（嵌入式关联表）。需要额外配置子表字段。",
        "api_extra": {},
    },
    "Cascade": {
        "controlType": 35,
        "name": "级联选择",
        "category": "relation",
        "doc": "级联多级选择（如省/市/区）。需配置数据源。",
        "api_extra": {},
    },
    "OtherTableField": {
        "controlType": 30,
        "name": "他表字段",
        "category": "relation",
        "doc": "从关联表引用字段值。需要先建立关联。",
        "api_extra": {},
    },
    "Rollup": {
        "controlType": 37,
        "name": "汇总",
        "category": "relation",
        "doc": "汇总关联表的数据（求和/计数/平均等）。",
        "api_extra": {},
    },

    # ── 文件 ──
    "Attachment": {
        "controlType": 14,
        "name": "附件",
        "category": "file",
        "doc": "文件上传字段。支持图片、文档等。",
        "api_extra": {},
    },
    "Signature": {
        "controlType": 42,
        "name": "签名",
        "category": "file",
        "doc": "手写签名字段。",
        "api_extra": {},
    },

    # ── 地理位置 ──
    "Area": {
        "controlType": 24,
        "name": "地区",
        "category": "location",
        "doc": "地区选择（省/市/区）。适合地图图表。",
        "api_extra": {},
    },
    "Location": {
        "controlType": 40,
        "name": "定位",
        "category": "location",
        "doc": "GPS 定位字段。记录经纬度。",
        "api_extra": {},
    },

    # ── 高级 ──
    "QRCode": {
        "controlType": 43,
        "name": "二维码",
        "category": "advanced",
        "doc": "自动生成二维码。",
        "api_extra": {},
    },
    "Embed": {
        "controlType": 45,
        "name": "嵌入",
        "category": "advanced",
        "doc": "嵌入外部网页或 iframe。",
        "api_extra": {},
    },
    "Section": {
        "controlType": 22,
        "name": "分段",
        "category": "layout",
        "doc": "表单分段标题（不存储数据）。",
        "api_extra": {},
    },
    "Remark": {
        "controlType": 10007,
        "name": "备注说明",
        "category": "layout",
        "doc": "表单中的静态文本说明。",
        "api_extra": {},
    },
}

# ── 便捷映射 ────────────────────────────────────────────────────────────────

# AI 枚举名 → controlType
FIELD_TYPE_MAP: dict[str, int] = {k: v["controlType"] for k, v in FIELD_REGISTRY.items()}

# controlType → 中文名
FIELD_TYPE_NAMES: dict[int, str] = {v["controlType"]: v["name"] for v in FIELD_REGISTRY.values()}

# AI 规划时允许的字段类型
ALLOWED_FIELD_TYPES: set[str] = set(FIELD_REGISTRY.keys())

# AI 规划时应该使用的类型子集（排除高级/布局类型）
PLANNABLE_TYPES: set[str] = {
    k for k, v in FIELD_REGISTRY.items()
    if v.get("category") not in ("layout", "advanced")
}

# 需要 option_values 的类型
OPTION_REQUIRED_TYPES: set[str] = {k for k, v in FIELD_REGISTRY.items() if v.get("requires_options")}

# 按 category 分组
FIELD_CATEGORIES: dict[str, list[str]] = {}
for _k, _v in FIELD_REGISTRY.items():
    FIELD_CATEGORIES.setdefault(_v.get("category", "other"), []).append(_k)
