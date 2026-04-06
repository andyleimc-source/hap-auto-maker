"""
明道云视图配置参数 Schema — 完整版

通过 API 实测（worksheetId=69cf74eef9434db36c6e0816）+ 代码分析整理。
所有参数均可直接传给 SaveWorksheetView 接口。

实测时间：2026-04-03
API 端点：POST https://www.mingdao.com/api/Worksheet/SaveWorksheetView

使用方式：
  from views.view_config_schema import VIEW_SCHEMA, COMMON_ADVANCED_KEYS
"""

# SaveWorksheetView 接口地址
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"

# ──────────────────────────────────────────────────────────────────────────────
# 所有视图共有的顶层参数（传给 SaveWorksheetView 的根字段）
# ──────────────────────────────────────────────────────────────────────────────
COMMON_TOP_PARAMS = {
    "viewId": "",            # 创建时为空；更新时填视图 ID
    "appId": "",             # 应用 ID（必填）
    "worksheetId": "",       # 工作表 ID（必填）
    "viewType": "0",         # 视图类型 0-10，字符串形式
    "name": "",              # 视图名称（必填）
    "displayControls": [],   # 显示字段 ID 列表；空列表=显示全部
    "sortType": 0,           # 0=默认，1=升序，2=降序（配合 sortCid）
    "coverType": 0,          # 封面类型，0=无
    "controls": [],          # 过滤条件（通常为空，由 advancedSetting 管理）
    "filters": [],           # 快速筛选条件列表
    "sortCid": "",           # 排序字段 ID；空=默认
    "showControlName": True, # 是否在卡片/看板上显示字段名
    "advancedSetting": {},   # 高级设置（dict；各视图不同，见 VIEW_SCHEMA）
}

# 更新时额外参数（仅 update 调用使用）
COMMON_UPDATE_PARAMS = {
    "editAttrs": [],         # 指定要更新的顶层字段名，如 ["advancedSetting","name"]
    "editAdKeys": [],        # 指定要更新的 advancedSetting 子键，如 ["groupView","calendarcids"]
}

# ──────────────────────────────────────────────────────────────────────────────
# 所有视图 advancedSetting 中通用的键
# ──────────────────────────────────────────────────────────────────────────────
COMMON_ADVANCED_KEYS = {
    "enablerules": {
        "type": "string",
        "values": ["1", "0"],
        "default": "1",
        "desc": "是否启用颜色规则。'1'=启用（推荐始终设置）",
    },
    "navempty": {
        "type": "string",
        "values": ["1", "0"],
        "default": "1",
        "desc": "分组时是否显示空分组列。'1'=显示",
    },
    "detailbtns": {
        "type": "string",
        "default": "[]",
        "desc": "记录详情页按钮配置，JSON 数组字符串。[] 表示无自定义按钮",
    },
    "listbtns": {
        "type": "string",
        "default": "[]",
        "desc": "列表行操作按钮配置，JSON 数组字符串。[] 表示无自定义按钮",
    },
    "coverstyle": {
        "type": "string",
        "default": '{"position":"1","style":3}',
        "desc": "封面图样式。position: '1'=顶部,'2'=左侧; style: 整数（1-5）",
        "examples": [
            '{"position":"1","style":3}',  # 表格/看板视图默认
            '{"position":"2"}',             # 画廊视图默认
        ],
    },
    "rowHeight": {
        "type": "string",
        "values": ["0", "1", "2", "3"],
        "default": "0",
        "desc": "行高。0=紧凑,1=中等,2=宽松,3=超高（仅表格/甘特图有效）",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# 各视图类型的完整配置 schema
# ──────────────────────────────────────────────────────────────────────────────
VIEW_SCHEMA = {
    # ════════════════════════════════════════════════════════════════════════
    0: {
        "name": "表格视图",
        "category": "basic",
        # 创建时直接传给 SaveWorksheetView 的参数
        "create_params": {
            "viewType": "0",
            "displayControls": [],       # 显示的字段 ID 列表
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "coverstyle": '{"position":"1","style":3}',
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
            },
        },
        # 创建成功后的二次更新
        "post_create": {
            # groupsetting：表格视图行分组（把记录按字段值分组显示），通过二次保存写入
            # 注意：groupView 是看板/导航筛选栏配置，与行分组完全无关，不要混用
            "groupsetting": {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["groupsetting", "groupsorts", "groupcustom", "groupshow", "groupfilters", "groupopen"],
                "description": "表格视图行分组配置（按字段值把记录分组显示）",
                "advancedSetting": {
                    "groupsetting": '[{"controlId":"<fieldId>","isAsc":true}]',
                    "groupsorts": "",
                    "groupcustom": "",
                    "groupshow": "0",
                    "groupfilters": "[]",
                    "groupopen": "",
                },
                "notes": [
                    "groupsetting 是 JSON 字符串数组，controlId 为分组字段 ID（推荐单选 type=9/11），isAsc 控制升序",
                    "【重要】用 controlId+isAsc，不要用 groupid（旧格式，HAP 已不识别）",
                    "groupshow: '0'=全部, '1'=筛选, '2'=自定义",
                    "不需要 viewId，创建后立即可二次保存",
                    "【重要】此配置与 navGroup/groupView（导航筛选栏）完全不同，不要混用",
                ],
            }
        },
        # advancedSetting 全部可用键说明
        "advanced_setting_keys": {
            # 行分组：把记录按字段值分组显示（正确配置）
            "groupsetting": {
                "type": "string",
                "desc": "行分组配置，JSON 字符串数组。格式：[{controlId, isAsc}]",
                "example": '[{"controlId":"fieldId123","isAsc":true}]',
                "requires_post_create": True,
            },
            "groupsorts": {"type": "string", "default": "", "desc": "分组排序，JSON 字符串"},
            "groupcustom": {"type": "string", "default": "", "desc": "自定义分组"},
            "groupshow": {"type": "string", "default": "0", "desc": "分组显示：'0'=全部, '1'=筛选, '2'=自定义"},
            "groupfilters": {"type": "string", "default": "[]", "desc": "分组筛选条件 JSON 数组"},
            "groupopen": {"type": "string", "default": "", "desc": "分组展开"},
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "coverstyle": {"type": "string", "default": '{"position":"1","style":3}', "desc": "封面样式"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "rowHeight": {"type": "string", "default": "0", "desc": "行高 0/1/2/3"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    1: {
        "name": "看板视图",
        "category": "basic",
        "requires_fields": {
            "viewControl": "单选字段 ID（type=11），看板分组依据。必填，无则不创建"
        },
        "create_params": {
            "viewType": "1",
            "viewControl": "<single_select_field_id>",  # 必须是 type=11 的字段
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "coverstyle": '{"position":"1","style":3}',
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
            },
        },
        "post_create": None,  # 无需二次保存
        "advanced_setting_keys": {
            "coverCid": {"type": "string", "desc": "封面字段 ID（顶层字段，非 advancedSetting 内）"},
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "coverstyle": {"type": "string", "default": '{"position":"1","style":3}', "desc": "封面样式"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
        "top_level_extra": {
            "viewControl": "必须是 type=11（下拉单选）字段的 ID",
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    2: {
        "name": "层级视图",
        "category": "basic",
        "requires_fields": {
            "layersControlId": "自关联字段 ID（type=29，dataSource=本工作表ID）"
        },
        "create_params": {
            "viewType": "2",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
                # 注意：层级视图不设 coverstyle
            },
        },
        # 二次保存：设置层级字段（顶层字段，不在 advancedSetting 内）
        "post_create": {
            "hierarchy": {
                "editAttrs": ["childType", "layersControlId"],
                "childType": 0,
                "layersControlId": "<self_relation_field_id>",
                "description": "配置层级字段。childType=0，layersControlId=自关联字段ID",
                "notes": [
                    "editAttrs 是顶层字段，不含 advancedSetting",
                    "不需要 editAdKeys",
                    "childType 固定为 0",
                ],
            }
        },
        "advanced_setting_keys": {
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空节点"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
        "top_level_extra": {
            "childType": "0（固定）",
            "layersControlId": "自关联字段 ID，通过 editAttrs 二次保存",
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    3: {
        "name": "画廊视图",
        "category": "basic",
        "create_params": {
            "viewType": "3",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "coverstyle": '{"position":"2"}',  # 画廊视图默认 position="2"（左侧）
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
            },
        },
        "post_create": None,
        "advanced_setting_keys": {
            "coverstyle": {
                "type": "string",
                "default": '{"position":"2"}',
                "desc": "封面样式。画廊默认 position='2'（左侧封面）",
                "examples": ['{"position":"2"}', '{"position":"1","style":3}'],
            },
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
        "top_level_extra": {
            "coverCid": "封面字段 ID（图片/附件字段，可选）",
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    4: {
        "name": "日历视图",
        "category": "basic",
        "requires_fields": {
            "calendarcids.begin": "开始日期字段 ID（type=15 日期 或 type=16 日期时间）"
        },
        "create_params": {
            "viewType": "4",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
                # calendarcids 通过 post_create 二次保存
            },
        },
        # 二次保存：设置日历字段
        "post_create": {
            "calendarcids": {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["calendarcids"],
                "description": "设置日历视图的日期字段",
                "format": '[{"begin":"<date_field_id>","end":"<end_date_field_id_or_empty>"}]',
                "notes": [
                    "begin 是开始日期字段 ID（必填）",
                    "end 是结束日期字段 ID（无则填空字符串 ''）",
                    "JSON 必须使用紧凑格式（无空格）",
                    "可配置多组日期，数组可有多个元素",
                    "同时服务器会存储 begindate 和 enddate 为顶层快捷键（自动）",
                ],
                "example": '[{"begin":"dateFieldId","end":""}]',
                "multi_date_example": '[{"begin":"startFieldId","end":"endFieldId"}]',
            }
        },
        "advanced_setting_keys": {
            "calendarcids": {
                "type": "string",
                "desc": "日历字段配置，JSON 数组字符串（紧凑格式）",
                "example": '[{"begin":"fieldId","end":""}]',
                "requires_post_create": True,
            },
            "begindate": {
                "type": "string",
                "desc": "开始日期字段 ID（服务器自动从 calendarcids 同步，无需手动设置）",
            },
            "enddate": {
                "type": "string",
                "desc": "结束日期字段 ID（服务器自动从 calendarcids 同步，无需手动设置）",
            },
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    5: {
        "name": "甘特图",
        "category": "basic",
        "requires_fields": {
            "begindate": "开始日期字段 ID（type=15/16）",
            "enddate": "结束日期字段 ID（type=15/16，可与 begindate 相同）",
        },
        "create_params": {
            "viewType": "5",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
                # begindate/enddate 通过 post_create 二次保存
                # 注意：甘特图不设 coverstyle
            },
        },
        # 二次保存：设置开始/结束日期字段
        "post_create": {
            "gantt_dates": {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["begindate", "enddate"],
                "description": "配置甘特图的时间轴字段",
                "notes": [
                    "begindate = 开始日期字段 ID",
                    "enddate = 结束日期字段 ID",
                    "可用同一字段（则甘特条无结束）",
                ],
                "example": {"begindate": "startFieldId", "enddate": "endFieldId"},
            }
        },
        "advanced_setting_keys": {
            "begindate": {
                "type": "string",
                "desc": "开始日期字段 ID（通过 editAdKeys 二次保存）",
                "requires_post_create": True,
            },
            "enddate": {
                "type": "string",
                "desc": "结束日期字段 ID（通过 editAdKeys 二次保存）",
                "requires_post_create": True,
            },
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "rowHeight": {"type": "string", "default": "0", "desc": "行高 0/1/2/3"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    6: {
        "name": "详情视图",
        "category": "advanced",
        "create_params": {
            "viewType": "6",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
            },
        },
        "post_create": None,
        "advanced_setting_keys": {
            "showpc": {
                "type": "string",
                "values": ["1", "0"],
                "default": "1",
                "desc": "是否为 PC 布局。'1'=PC 多列布局",
            },
            "showRows": {
                "type": "string",
                "default": "2",
                "desc": "显示列数（PC 布局有效）。'1'=1列,'2'=2列,'3'=3列",
            },
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    7: {
        "name": "地图视图",
        "category": "advanced",
        "requires_fields": {
            "latlng": "地理位置字段 ID（type=24 地区 或 type=40 定位）（可选）"
        },
        "create_params": {
            "viewType": "7",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
                # latlng 可选，不设则地图自动识别地区字段
            },
        },
        "post_create": None,
        "advanced_setting_keys": {
            "latlng": {
                "type": "string",
                "desc": "指定地理位置字段 ID（type=24 地区 或 type=40 定位）。不设则自动",
                "example": "fieldId",
            },
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    8: {
        "name": "快速视图",
        "category": "advanced",
        "create_params": {
            "viewType": "8",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
            },
        },
        "post_create": None,
        "advanced_setting_keys": {
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    9: {
        "name": "资源视图",
        "category": "advanced",
        "requires_fields": {
            "resourceId": "成员/协作者字段 ID（type=26/27），资源轴分组依据",
            "startdate": "开始日期字段 ID（type=15/16）",
            "enddate": "结束日期字段 ID（type=15/16）",
        },
        "create_params": {
            "viewType": "9",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
            },
        },
        # 二次保存：设置资源字段和时间字段
        "post_create": {
            "resource_config": {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["resourceId", "startdate", "enddate"],
                "description": "配置资源视图的成员字段和时间字段",
                "notes": [
                    "resourceId = 成员字段 ID（type=26 成员 或 type=27 部门）",
                    "startdate = 开始日期字段 ID",
                    "enddate = 结束日期字段 ID",
                ],
                "example": {
                    "resourceId": "memberFieldId",
                    "startdate": "startDateFieldId",
                    "enddate": "endDateFieldId",
                },
            }
        },
        "advanced_setting_keys": {
            "resourceId": {
                "type": "string",
                "desc": "成员/部门字段 ID（type=26/27），资源轴。通过 editAdKeys 二次保存",
                "requires_post_create": True,
            },
            "startdate": {
                "type": "string",
                "desc": "开始日期字段 ID。通过 editAdKeys 二次保存",
                "requires_post_create": True,
            },
            "enddate": {
                "type": "string",
                "desc": "结束日期字段 ID。通过 editAdKeys 二次保存",
                "requires_post_create": True,
            },
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
    },

    # ════════════════════════════════════════════════════════════════════════
    10: {
        "name": "自定义视图",
        "category": "plugin",
        "create_params": {
            "viewType": "10",
            "displayControls": [],
            "sortType": 0,
            "coverType": 0,
            "controls": [],
            "filters": [],
            "sortCid": "",
            "showControlName": True,
            "advancedSetting": {
                "enablerules": "1",
                "navempty": "1",
                "detailbtns": "[]",
                "listbtns": "[]",
            },
        },
        "post_create": None,
        "advanced_setting_keys": {
            "enablerules": {"type": "string", "default": "1", "desc": "启用颜色规则"},
            "navempty": {"type": "string", "default": "1", "desc": "显示空分组"},
            "detailbtns": {"type": "string", "default": "[]", "desc": "详情按钮"},
            "listbtns": {"type": "string", "default": "[]", "desc": "列表按钮"},
        },
        "notes": "需要安装对应插件。pluginId 在顶层字段中指定。",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# 表格视图行分组配置说明（2026-04-06 HAR 抓包验证）
# ──────────────────────────────────────────────────────────────────────────────
GROUP_SETTING_FORMAT_NOTES = """
表格视图行分组配置（groupsetting）——2026-04-06 HAR 抓包实测确认：

【正确配置】
- 字段名：advancedSetting.groupsetting（JSON 字符串数组）
- 格式：[{"controlId":"<fieldId>","isAsc":true}]
- 通过 editAttrs=["advancedSetting"] + editAdKeys=["groupsetting","groupsorts","groupcustom","groupshow","groupfilters","groupopen"] 二次保存
- 无需 viewId，创建后立即可配置

【常见错误（已修复）】
- 错误：用 groupView 配置行分组 → groupView 是看板/导航筛选栏配置，不是行分组
- groupView 格式：{"viewId":"...","groupFilters":[...],"navShow":true} 这是 navGroup，与行分组无关
- 历史版本（2026-04-03 之前）用 groupView 导致分组设置无效
- 历史版本用 {groupid:...,filterType:11} 格式，HAP 前端不识别，导致「服务异常」。正确用 controlId+isAsc

【实测保存请求体】
{
  "editAttrs": ["advancedSetting"],
  "editAdKeys": ["groupsetting","groupsorts","groupcustom","groupshow","groupfilters","groupopen"],
  "advancedSetting": {
    "groupsetting": "[{\\"controlId\\":\\"<fieldId>\\",\\"isAsc\\":true}]",
    "groupsorts": "",
    "groupcustom": "",
    "groupshow": "0",
    "groupfilters": "[]",
    "groupopen": ""
  }
}
"""

# ──────────────────────────────────────────────────────────────────────────────
# 实测 API 数据汇总（worksheetId=69cf74eef9434db36c6e0816）
# ──────────────────────────────────────────────────────────────────────────────
API_OBSERVED_DATA = {
    "worksheet_id": "69cf74eef9434db36c6e0816",
    "app_id": "f11f2128-c4de-46cb-a2be-fe1c62ed1481",
    "views": [
        # viewType 0 — 基础表格
        {"viewType": 0, "name": "全部", "advancedSetting": {"navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
        # viewType 0 — 分组表格（正确配置：groupsetting，2026-04-06 HAR 验证）
        # 注意：旧版本错误用了 groupView，已修复。groupView 是 navGroup 配置，与行分组无关。
        {"viewType": 0, "name": "按状态分组", "advancedSetting": {
            "groupsetting": '[{"controlId":"69cf74f0f9434db36c6e0827","isAsc":true}]',
            "groupsorts": "", "groupcustom": "", "groupshow": "0", "groupfilters": "[]", "groupopen": "",
            "navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]",
        }},
        # viewType 1 — 看板
        {"viewType": 1, "name": "看板视图", "viewControl": "69cf74f0f9434db36c6e0825",
         "advancedSetting": {"navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
        # viewType 3 — 画廊
        {"viewType": 3, "name": "画廊视图", "advancedSetting": {"coverstyle": '{"position":"2"}', "navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
        # viewType 4 — 日历（单日期）
        {"viewType": 4, "name": "日历视图", "advancedSetting": {
            "navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]",
            "calendarcids": '[{"begin":"69cf74f1465f750591359248","end":""}]',
            "begindate": "69cf74f1465f750591359248", "enddate": "",
        }},
        # viewType 4 — 日历（双日期）
        {"viewType": 4, "name": "高级日历视图_多日期", "advancedSetting": {
            "navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]",
            "calendarcids": '[{"begin":"69cf74f1465f750591359248","end":"69cf74f1465f750591359249"}]',
            "begindate": "69cf74f1465f750591359248", "enddate": "69cf74f1465f750591359249",
        }},
        # viewType 5 — 甘特图
        {"viewType": 5, "name": "甘特图", "advancedSetting": {
            "navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]",
            "begindate": "69cf74f1465f750591359248", "enddate": "69cf74f1465f750591359249",
        }},
        # viewType 6 — 详情视图
        {"viewType": 6, "name": "详情视图", "advancedSetting": {"navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
        # viewType 6 — 详情视图（PC多列布局）
        {"viewType": 6, "name": "详情视图_多列布局", "advancedSetting": {"showpc": "1", "showRows": "2", "navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
        # viewType 7 — 地图视图（无字段）
        {"viewType": 7, "name": "地图视图", "advancedSetting": {"navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
        # viewType 7 — 地图视图（指定字段）
        {"viewType": 7, "name": "地图视图_指定地理字段", "advancedSetting": {
            "latlng": "69cf74f322449cdbb24b6593",
            "navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]",
        }},
        # viewType 8 — 快速视图
        {"viewType": 8, "name": "快速视图", "advancedSetting": {"navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
        # viewType 9 — 资源视图（无字段）
        {"viewType": 9, "name": "资源视图", "advancedSetting": {"navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
        # viewType 9 — 资源视图（带字段配置）
        {"viewType": 9, "name": "资源视图_带字段配置", "advancedSetting": {
            "resourceId": "69cf74f3f9434db36c6e0841",
            "startdate": "69cf74f1465f750591359248",
            "enddate": "69cf74f1465f750591359249",
            "navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]",
        }},
        # viewType 10 — 自定义视图
        {"viewType": 10, "name": "自定义视图", "advancedSetting": {"navempty": "1", "enablerules": "1", "detailbtns": "[]", "listbtns": "[]"}},
    ],
}
