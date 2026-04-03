"""
HAP 视图类型定义 — 完整版（11 种，viewType 0-10）。

来源：
  - hap-utral-maker/api-specs/block1-private/worksheet/save-worksheet-view.md（6 种已录制）
  - SaveWorksheetView API 测试（viewType 6-10 全部可创建）
  - 明道云前端视图选择面板
  - 2026-04-03 API 实测（worksheetId=69cf74eef9434db36c6e0816）

说明：
  - PLANNABLE_VIEWS 是 AI 规划时应使用的视图子集
  - 每种视图标注了字段约束和二次保存配置
  - 完整 advancedSetting 参数详见 view_config_schema.py

advancedSetting 通用键（所有视图）：
  - enablerules: "1"=启用颜色规则（推荐始终设置）
  - navempty: "1"=显示空分组
  - detailbtns: "[]"=详情页按钮（JSON 数组字符串）
  - listbtns: "[]"=列表操作按钮（JSON 数组字符串）
  - coverstyle: 封面样式，表格/看板默认 '{"position":"1","style":3}'，画廊默认 '{"position":"2"}'
  - rowHeight: "0"=紧凑/"1"=中等/"2"=宽松/"3"=超高

groupView BUG 修复（2026-04-03）：
  - groupView JSON 必须使用紧凑格式（separators=(',',':')，无空格）
  - viewId 必须填当前视图的真实 ID（二次保存时）
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
        "advancedSetting_keys": {
            "groupView": "分组配置 JSON 字符串（紧凑格式，viewId=当前视图ID，需二次保存）",
            "enablerules": "'1'=启用颜色规则",
            "coverstyle": "封面样式，默认 '{\"position\":\"1\",\"style\":3}'",
            "navempty": "'1'=显示空分组",
            "rowHeight": "行高 0=紧凑/1=中等/2=宽松/3=超高",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
    },
    1: {
        "name": "看板视图",
        "category": "basic",
        "verified": True,
        "requires_fields": ["single_select"],
        "post_create": None,
        "auto_complete": "viewControl",
        "doc": "必须设 viewControl 为单选字段(type=11) ID。无合适字段则不创建。",
        "advancedSetting_keys": {
            "enablerules": "'1'=启用颜色规则",
            "coverstyle": "封面样式，默认 '{\"position\":\"1\",\"style\":3}'",
            "navempty": "'1'=显示空分组",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
        "top_level_extra": {
            "viewControl": "必须是 type=11（下拉单选）字段的 ID",
            "coverCid": "封面字段 ID（可选）",
        },
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
        "doc": "需要自关联字段(type=29, dataSource=本表)。二次保存 childType + layersControlId（顶层字段，不在 advancedSetting 内）。",
        "advancedSetting_keys": {
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空节点",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
        "top_level_extra": {
            "childType": "0（固定），通过 editAttrs 二次保存",
            "layersControlId": "自关联字段 ID，通过 editAttrs 二次保存",
        },
    },
    3: {
        "name": "画廊视图",
        "category": "basic",
        "verified": True,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "卡片画廊。可设 coverCid（顶层）为图片/附件字段。advancedSetting.coverstyle 默认 '{\"position\":\"2\"}'。",
        "advancedSetting_keys": {
            "coverstyle": "封面样式，画廊默认 '{\"position\":\"2\"}' (左侧)",
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空分组",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
        "top_level_extra": {
            "coverCid": "封面字段 ID（图片/附件字段，可选）",
        },
    },
    4: {
        "name": "日历视图",
        "category": "basic",
        "verified": True,
        "requires_fields": ["date"],
        "post_create": {
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["calendarcids"],
            "fields": {"calendarcids": '[{"begin":"<date_field_id>","end":""}]'},
        },
        "auto_complete": "calendar",
        "doc": "需要日期字段(type=15/16)。二次保存 calendarcids（紧凑 JSON 字符串）。支持多日期：[{\"begin\":\"id1\",\"end\":\"id2\"}]。",
        "advancedSetting_keys": {
            "calendarcids": "日历字段配置，JSON 数组字符串（紧凑格式），需二次保存。格式：'[{\"begin\":\"fieldId\",\"end\":\"\"}]'",
            "begindate": "开始日期字段 ID（服务器自动同步，无需手动设置）",
            "enddate": "结束日期字段 ID（服务器自动同步，无需手动设置）",
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空分组",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
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
        "doc": "需要开始/结束日期字段(type=15/16)。二次保存 begindate + enddate。不设 coverstyle。",
        "advancedSetting_keys": {
            "begindate": "开始日期字段 ID，通过 editAdKeys 二次保存",
            "enddate": "结束日期字段 ID，通过 editAdKeys 二次保存",
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空分组",
            "rowHeight": "行高 0=紧凑/1=中等/2=宽松/3=超高",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
    },
    6: {
        "name": "详情视图",
        "category": "advanced",
        "verified": True,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "单条记录详情/表单视图。适合数据录入场景。支持 PC 多列布局（showpc+showRows）。",
        "advancedSetting_keys": {
            "showpc": "'1'=PC 多列布局",
            "showRows": "列数：'1'=1列/'2'=2列/'3'=3列（showpc='1' 时有效）",
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空分组",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
    },
    7: {
        "name": "地图视图",
        "category": "advanced",
        "verified": True,
        "requires_fields": ["location"],
        "post_create": None,
        "auto_complete": None,
        "doc": "地图视图。advancedSetting.latlng 可指定地区(type=24)或定位(type=40)字段 ID；不设则自动识别。",
        "advancedSetting_keys": {
            "latlng": "指定地理位置字段 ID（type=24 地区 或 type=40 定位），可选",
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空分组",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
    },
    8: {
        "name": "快速视图",
        "category": "advanced",
        "verified": True,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "快速视图/打印视图。无特殊 advancedSetting 参数。",
        "advancedSetting_keys": {
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空分组",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
    },
    9: {
        "name": "资源视图",
        "category": "advanced",
        "verified": True,
        "requires_fields": ["collaborator", "date"],
        "post_create": {
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["resourceId", "startdate", "enddate"],
            "fields": {
                "resourceId": "<member_field_id>",
                "startdate": "<date_field_1>",
                "enddate": "<date_field_2>",
            },
        },
        "auto_complete": None,
        "doc": "按成员分组的时间线视图。需要成员字段(type=26)和日期字段。二次保存 resourceId+startdate+enddate。",
        "advancedSetting_keys": {
            "resourceId": "成员/部门字段 ID（type=26/27），资源轴。通过 editAdKeys 二次保存",
            "startdate": "开始日期字段 ID，通过 editAdKeys 二次保存",
            "enddate": "结束日期字段 ID，通过 editAdKeys 二次保存",
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空分组",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
    },
    10: {
        "name": "自定义视图",
        "category": "plugin",
        "verified": False,
        "requires_fields": [],
        "post_create": None,
        "auto_complete": None,
        "doc": "插件自定义视图。需要安装对应插件。pluginId 在顶层字段中指定。",
        "advancedSetting_keys": {
            "enablerules": "'1'=启用颜色规则",
            "navempty": "'1'=显示空分组",
            "detailbtns": "详情页按钮 JSON 数组字符串",
            "listbtns": "列表操作按钮 JSON 数组字符串",
        },
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
