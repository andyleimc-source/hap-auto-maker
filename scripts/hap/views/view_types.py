"""
HAP 视图类型定义。

每种视图类型包含：创建参数、二次保存要求、字段约束、自动补全逻辑。
"""

from __future__ import annotations

VIEW_REGISTRY = {
    0: {
        "name": "表格视图",
        "verified": True,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": "grouping",
        "doc": "默认视图。名称含'分组'/'分类'时自动生成 groupView 配置。需要 type=9/10/11 的单选/多选字段。",
    },
    1: {
        "name": "看板视图",
        "verified": True,
        "requires_fields": ["single_select"],  # type=11
        "post_create": None,
        "auto_complete": "viewControl",
        "doc": "必须设 viewControl 为单选字段(type=11)的 ID。无合适字段则不创建。",
    },
    2: {
        "name": "层级视图",
        "verified": True,
        "requires_fields": ["self_relation"],  # type=29 且 dataSource=本表
        "post_create": {
            "editAttrs": ["childType", "layersControlId"],
            "fields": {"childType": 0, "layersControlId": "<self_relation_field_id>"},
        },
        "auto_complete": "hierarchy",
        "doc": "需要自关联字段(type=29, dataSource=本表ID)。二次保存 childType=0 + layersControlId。",
    },
    3: {
        "name": "画廊视图",
        "verified": False,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "卡片画廊。可设 coverCid 为图片/附件字段。",
    },
    4: {
        "name": "日历视图",
        "verified": False,
        "requires_fields": ["date"],  # type=15/16
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
        "verified": True,
        "requires_fields": ["date", "date"],  # 需要两个日期字段
        "post_create": {
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["begindate", "enddate"],
            "fields": {"begindate": "<date_field_1>", "enddate": "<date_field_2>"},
        },
        "auto_complete": "gantt",
        "doc": "需要开始/结束日期字段(type=15/16)。二次保存 begindate + enddate。",
    },
}

# 便捷映射
ALLOWED_VIEW_TYPES: set[str] = {str(k) for k in VIEW_REGISTRY}
VIEW_TYPE_NAMES: dict[int, str] = {k: v["name"] for k, v in VIEW_REGISTRY.items()}
