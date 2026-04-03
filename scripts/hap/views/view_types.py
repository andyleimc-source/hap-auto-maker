"""
HAP 视图类型定义 — 完整版（11 种，viewType 0-10）。

来源：
  - hap-utral-maker/api-specs/block1-private/worksheet/save-worksheet-view.md（6 种已录制）
  - SaveWorksheetView API 测试（viewType 6-10 全部可创建）
  - 明道云前端视图选择面板

说明：
  - PLANNABLE_VIEWS 是 AI 规划时应使用的视图子集
  - 每种视图标注了字段约束和二次保存配置
"""

from __future__ import annotations

VIEW_REGISTRY = {
    0: {
        "name": "表格视图",
        "category": "basic",
        "verified": True,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": "grouping",
        "doc": "默认视图。名称含'分组'时自动生成 groupView。需要单选字段(type=9/10/11)。",
    },
    1: {
        "name": "看板视图",
        "category": "basic",
        "verified": True,
        "requires_fields": ["single_select"],
        "post_create": None,
        "auto_complete": "viewControl",
        "doc": "必须设 viewControl 为单选字段(type=11) ID。无合适字段则不创建。",
    },
    2: {
        "name": "层级视图",
        "category": "basic",
        "verified": True,
        "requires_fields": ["self_relation"],
        "post_create": {
            "editAttrs": ["childType", "layersControlId"],
            "fields": {"childType": 0, "layersControlId": "<self_relation_field_id>"},
        },
        "auto_complete": "hierarchy",
        "doc": "需要自关联字段(type=29, dataSource=本表)。二次保存 childType + layersControlId。",
    },
    3: {
        "name": "画廊视图",
        "category": "basic",
        "verified": False,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "卡片画廊。可设 coverCid 为图片/附件字段。",
    },
    4: {
        "name": "日历视图",
        "category": "basic",
        "verified": False,
        "requires_fields": ["date"],
        "post_create": {
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["calendarcids"],
            "fields": {"calendarcids": '[{"begin":"<date_field_id>","end":""}]'},
        },
        "auto_complete": "calendar",
        "doc": "需要日期字段(type=15/16)。二次保存 calendarcids JSON。",
    },
    5: {
        "name": "甘特图",
        "category": "basic",
        "verified": True,
        "requires_fields": ["date", "date"],
        "post_create": {
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["begindate", "enddate"],
            "fields": {"begindate": "<date_field_1>", "enddate": "<date_field_2>"},
        },
        "auto_complete": "gantt",
        "doc": "需要开始/结束日期字段(type=15/16)。二次保存 begindate + enddate。",
    },
    6: {
        "name": "详情视图",
        "category": "advanced",
        "verified": False,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "单条记录详情/表单视图。适合数据录入场景。",
    },
    7: {
        "name": "地图视图",
        "category": "advanced",
        "verified": False,
        "requires_fields": ["location"],
        "post_create": None,
        "auto_complete": None,
        "doc": "地图视图。需要地区(type=24)或定位(type=40)字段。",
    },
    8: {
        "name": "快速视图",
        "category": "advanced",
        "verified": False,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "快速视图/打印视图。",
    },
    9: {
        "name": "资源视图",
        "category": "advanced",
        "verified": False,
        "requires_fields": ["collaborator", "date"],
        "post_create": None,
        "auto_complete": None,
        "doc": "按成员分组的时间线视图。需要成员字段(type=26)和日期字段。",
    },
    10: {
        "name": "自定义视图",
        "category": "plugin",
        "verified": False,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "插件自定义视图。需要安装对应插件。",
    },
}

# 便捷映射
ALLOWED_VIEW_TYPES: set[str] = {str(k) for k in VIEW_REGISTRY}
VIEW_TYPE_NAMES: dict[int, str] = {k: v["name"] for k, v in VIEW_REGISTRY.items()}

# AI 规划时应使用的视图子集（排除插件视图）
PLANNABLE_VIEWS: set[int] = {
    k for k, v in VIEW_REGISTRY.items()
    if v.get("category") != "plugin"
}
