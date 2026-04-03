"""
明道云统计图配置参数 Schema — 完整版

来源：代码分析（charts/ 注册中心）+ create_charts_from_plan.py 执行逻辑
用于：create_charts_from_plan.py、plan_charts_gemini.py、AI 图表规划 prompt

图表创建 API：
  POST https://api.mingdao.com/report/reportConfig/saveReportConfig
  （使用 browser auth，通过 auth_retry.hap_web_post 调用）

页面布局 API：
  GET  https://api.mingdao.com/report/custom/getPage?appId={pageId}
  POST https://api.mingdao.com/report/custom/savePage

核心参数结构：
{
  "name": "图表名称",
  "reportType": 1,
  "worksheetId": "工作表ID（appId 字段）",
  "xaxes": {
    "controlId": "字段ID（数值图/进度图填 null）",
    "controlName": "字段名",
    "controlType": 16,        # 字段类型 ID
    "particleSizeType": 0,    # 日期粒度（非日期字段填 0）
    "sortType": 0,            # 排序方向：0=默认 1=升序 2=降序
    "emptyType": 0,           # 空值处理：0=显示空值 1=忽略空值
    "rename": "",             # 轴标签重命名
    "xaxisEmptyType": 0,
    "xaxisEmpty": false,
  },
  "yaxisList": [
    {
      "controlId": "字段ID 或 record_count",
      "controlName": "字段名 或 记录数量",
      "controlType": 10000000,  # 记录数量固定值；数值字段用实际 type
      "normType": 5,   # 聚合类型（见下方说明）
      "rename": "",    # 指标显示名称
    }
  ],
  "split": {},         # 系列/颜色维度（可选）
  "filter": {
    "filterRangeId": "ctime",
    "filterRangeName": "创建时间",
    "rangeType": 0,    # 0=不限 18=近N天 等
    "rangeValue": 0,
    "today": false
  },
  "displaySetup": {...},  # 由 build_fn 自动生成
  "style": {},
  "yreportType": null,   # 仅双轴图使用：1=柱 2=折线
}

聚合类型 normType（yaxisList 使用）：
  1 = COUNT 计数
  2 = SUM 求和
  3 = AVG 平均值
  4 = MAX 最大值
  5 = MIN 最小值
  6 = COUNT DISTINCT 去重计数

日期粒度 particleSizeType（xaxes 日期字段使用）：
  0 = 不分组（默认）
  1 = 按月
  2 = 按季度
  3 = 按年
  4 = 按天
  5 = 按周
  6 = 按小时

rangeType 时间范围：
  0  = 不限时间
  1  = 今天
  2  = 昨天
  3  = 本周
  5  = 本月
  6  = 本季度
  7  = 本年
  18 = 近N天（配合 rangeValue）

系统字段（任何工作表都可用）：
  ctime      (controlType=16) 创建时间
  utime      (controlType=16) 最后修改时间
  ownerid    (controlType=26) 负责人
  caid       (controlType=26) 创建人
  record_count (controlType=10000000) 记录数量（仅 yaxisList）
"""

from __future__ import annotations

# ── 字段类型映射（controlType 值含义）───────────────────────────────────────────
CONTROL_TYPE_NAMES: dict[int, str] = {
    2: "文本",
    3: "电话",
    4: "证件",
    5: "密码",
    6: "数值",
    7: "金额（自由）",
    8: "金额",
    9: "单选",
    10: "多选",
    11: "下拉",
    14: "附件",
    15: "日期",
    16: "日期时间",
    19: "地区",
    21: "关联记录",
    23: "定位",
    24: "富文本",
    25: "备注",
    26: "成员",
    27: "部门",
    28: "等级",
    29: "关联",
    30: "查找",
    31: "公式数值",
    32: "文本公式",
    33: "自动编号",
    35: "级联选择",
    36: "检查框",
    37: "汇总",
    38: "他表字段",
    40: "签名",
    41: "子表",
    43: "嵌入",
    45: "摘要",
    46: "时间",
    47: "颜色",
    48: "条形码",
    50: "API 查询",
    10000000: "记录数量（系统虚拟字段）",
}

# ── 图表类型适合的字段类型（供 AI 选择）────────────────────────────────────────
XAXES_RECOMMENDED_TYPES: dict[str, list[int]] = {
    "classify":  [9, 10, 11, 26, 27, 35],   # 分类维度（单选/多选/成员/部门等）
    "date":      [15, 16],                    # 时间维度（日期/日期时间）
    "text":      [2, 32, 33],                 # 文本维度（适合词云图）
    "number":    [6, 8, 28, 31, 37],          # 数值（适合散点图 X 轴）
    "geo":       [19, 23],                    # 地理（适合地图）
    "relation":  [21, 29],                    # 关联（适合关系图）
    "null":      [],                          # 数值图/进度图（无 xaxes）
}

YAXES_RECOMMENDED_TYPES: dict[str, list[int]] = {
    "count":   [10000000],                    # record_count（通用统计）
    "numeric": [6, 8, 28, 31, 37],            # 数值字段（求和/平均等）
}

# ── normType 说明 ────────────────────────────────────────────────────────────
NORM_TYPE_NAMES: dict[int, str] = {
    1: "COUNT（计数）",
    2: "SUM（求和）",
    3: "AVG（平均值）",
    4: "MAX（最大值）",
    5: "MIN（最小值）",
    6: "COUNT DISTINCT（去重计数）",
}

# ── particleSizeType 说明 ─────────────────────────────────────────────────────
PARTICLE_SIZE_NAMES: dict[int, str] = {
    0: "不分组",
    1: "按月",
    2: "按季度",
    3: "按年",
    4: "按天",
    5: "按周",
    6: "按小时",
}

# ── rangeType 完整枚举（补充自 HAP Ultra chart-types.md 2026-04-01 录制）──────
RANGE_TYPE_NAMES: dict[int, str] = {
    0:  "不限时间",
    1:  "今天",
    2:  "昨天",
    3:  "本周",
    4:  "上周",
    5:  "本月",
    6:  "上月",
    7:  "本季度",
    8:  "上季度",
    9:  "本年",
    18: "过去N天（rangeValue=天数，today=true 含今天）",
}

# ── displaySetup 完整结构（来源：HAP Ultra chart-types.md 实测 saveReportConfig）
# 所有图表类型共用同一个 displaySetup 对象，AI 规划时保持默认即可
DISPLAY_SETUP_TEMPLATE: dict = {
    # ── 堆叠 / 百分比 ────────────────────────────────────────────────────────
    "isPile":           False,   # True=堆叠柱状图（柱状/条形图）
    "isPerPile":        False,   # True=百分比堆叠
    "isAccumulate":     False,   # True=累计折线
    "accumulatePerPile": None,
    # ── 时间对比 ─────────────────────────────────────────────────────────────
    "isToday":          False,
    "isLifecycle":      False,
    "lifecycleValue":   0,
    "contrastType":     0,       # 0=不对比, 1=同比, 2=环比
    # ── 字体 / 显示控制 ──────────────────────────────────────────────────────
    "fontStyle":        1,       # 1=正常
    "showTotal":        False,   # True=显示汇总行
    "showTitle":        True,    # True=显示图表标题
    "showLegend":       True,    # True=显示图例
    "legendType":       1,       # 1=图例在下方
    "showDimension":    True,    # True=显示维度标签
    "showNumber":       True,    # True=显示数据标签
    "showPercent":      False,   # True=显示百分比（饼图/环形图建议 True）
    "showXAxisCount":   0,       # X 轴显示数量限制（0=不限）
    "showChartType":    1,       # 1=默认图表样式
    "showPileTotal":    True,    # True=堆叠时显示合计
    "hideOverlapText":  False,   # True=隐藏重叠文字
    "showRowList":      True,    # True=透视表显示行列表
    "showControlIds":   [],      # 透视表显示的字段 ID 列表
    "auxiliaryLines":   [],      # 辅助线配置列表
    "showOptionIds":    [],      # 筛选显示的选项 ID 列表
    "contrast":         False,
    "colorRules":       [],      # 颜色规则列表
    # ── 百分比精度 ────────────────────────────────────────────────────────────
    "percent": {
        "enable":    False,
        "type":      2,          # 2=固定小数位
        "dot":       "2",        # 小数位数
        "dotFormat": "1",
        "roundType": 2,          # 2=四舍五入
    },
    # ── 透视表 ───────────────────────────────────────────────────────────────
    "mergeCell":    True,        # True=合并单元格
    "previewUrl":   None,
    "imageUrl":     None,
    # ── X 轴显示设置 ──────────────────────────────────────────────────────────
    "xdisplay": {
        "showDial":  True,       # True=显示刻度
        "showTitle": False,      # True=显示轴标题
        "title":     "",         # 轴标题文字
        "minValue":  None,       # 最小值（None=自动）
        "maxValue":  None,       # 最大值（None=自动）
    },
    "xaxisEmpty": False,
    # ── Y 轴显示设置 ──────────────────────────────────────────────────────────
    "ydisplay": {
        "showDial":   True,
        "showTitle":  False,
        "title":      "",        # 通常填指标名，如 "记录数量"
        "minValue":   None,
        "maxValue":   None,
        "lineStyle":  1,         # 1=实线, 2=虚线（折线图）
        "showNumber": None,
    },
}

# ── yaxisList 单项完整结构（HAP Ultra 实测补充）──────────────────────────────
YAXIS_ITEM_TEMPLATE: dict = {
    "controlId":   "record_count",  # 字段 ID 或 "record_count"
    "controlName": "记录数量",
    "controlType": 10000000,
    "normType":    5,            # 聚合方式（见 NORM_TYPE_NAMES）
    "rename":      "",           # 指标显示名（空=用字段名）
    "magnitude":   0,            # 数量级：0=原始值, 1=千, 2=万, 3=百万
    "roundType":   2,            # 取整：1=向上, 2=四舍五入, 3=向下
    "dotFormat":   "1",          # 小数格式
    "suffix":      "",           # 单位后缀
    "ydot":        2,            # Y 轴小数位
    "fixType":     0,            # 固定数量级类型
    "showNumber":  True,
    "hide":        False,        # True=隐藏该指标
    "percent": {
        "enable": False, "type": 2, "dot": "2", "dotFormat": "1", "roundType": 2,
    },
    "emptyShowType": 0,          # 空值显示：0=显示0, 1=显示空
    "dot":         0,
    "advancedSetting": {},
}

# ── savePage 布局接口说明（将图表添加到自定义页面）────────────────────────────
# POST https://api.mingdao.com/report/custom/savePage
SAVE_PAGE_COMPONENT_TEMPLATE: dict = {
    "id":          "<24位hex>",   # 组件唯一 ID
    "type":        1,            # 1=图表组件
    "value":       "<reportId>", # 图表 ID
    "valueExtend": "<reportId>",
    "config":      {"objectId": "<uuid>"},
    "worksheetId": "<worksheetId>",
    "name":        "图表名称",
    "reportType":  1,
    "showChartType": 1,
    "titleVisible":  False,
    "needUpdate":    True,
    "web": {
        "title":        "",
        "titleVisible": False,
        "visible":      True,
        "layout": {"x": 0, "y": 0, "w": 24, "h": 12, "minW": 2, "minH": 4},
    },
    "mobile": {"title": "", "titleVisible": False, "visible": True, "layout": None},
}

# getData 接口（查询图表数据）
# POST https://api.mingdao.com/report/report/getData
GET_DATA_PAYLOAD_TEMPLATE: dict = {
    "reportId":   "<reportId>",
    "pageId":     "<pageId>",
    "filters":    [],
    "isPersonal": False,
    "reload":     False,
}

# saveReportConfig 请求体中的 version 字段（固定值）
SAVE_REPORT_VERSION = "6.5"

# ── 完整图表 Schema ──────────────────────────────────────────────────────────
CHART_SCHEMA: dict[int, dict] = {

    # ─── 1. 柱状图 ────────────────────────────────────────────────────────────
    1: {
        "name": "柱状图",
        "reportType": 1,
        "category": "comparison",
        "verified": True,
        "module": "basic",
        "description": "垂直柱状图，适合比较不同类别的数值大小",
        "requires": {
            "xaxes": "分类维度字段（单选/下拉/文本/成员等）",
            "yaxisList": "至少 1 个数值指标（record_count 或数值字段）",
            "split": "可选，颜色系列维度（分组柱状图）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"] + XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "isPile": "True = 堆叠柱状图",
            "isPerPile": "True = 百分比堆叠",
            "showNumber": "True = 显示数值标签",
            "showLegend": "True = 显示图例",
        },
        "create_params_template": {
            "reportType": 1,
            "xaxes": {
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "最通用的图表类型。xaxes 优先选单选/下拉字段，展示各分类数量分布。"
            "如需对比时间趋势，xaxes 改用日期字段并设 particleSizeType=1（按月）。"
        ),
    },

    # ─── 2. 折线图 ────────────────────────────────────────────────────────────
    2: {
        "name": "折线图",
        "reportType": 2,
        "category": "trend",
        "verified": True,
        "module": "basic",
        "description": "折线图，适合展示随时间变化的趋势",
        "requires": {
            "xaxes": "日期/日期时间字段（controlType=15/16），推荐 ctime 系统字段",
            "yaxisList": "至少 1 个数值指标",
            "split": "可选，系列维度（多线折线图）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "showLegend": "True = 显示图例",
            "showNumber": "True = 显示数据点标签",
        },
        "create_params_template": {
            "reportType": 2,
            "xaxes": {
                "controlId": "ctime",
                "controlName": "创建时间",
                "controlType": 16,
                "particleSizeType": 1,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "趋势分析首选。xaxes 必须为日期字段（ctime/utime 或自定义日期字段），"
            "particleSizeType 建议设 1（按月）或 4（按天）。"
        ),
    },

    # ─── 3. 饼图 ─────────────────────────────────────────────────────────────
    3: {
        "name": "饼图",
        "reportType": 3,
        "category": "proportion",
        "verified": True,
        "module": "pie",
        "description": "饼图，展示各类别占总量的比例",
        "requires": {
            "xaxes": "分类维度字段（单选/下拉，选项数量建议 ≤8）",
            "yaxisList": "1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "showPercent": "自动设为 True（显示百分比）",
            "showLegend": "True = 显示图例",
        },
        "build_overrides": {
            "displaySetup.showPercent": True,
        },
        "create_params_template": {
            "reportType": 3,
            "xaxes": {
                "controlId": "<单选字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "占比分析首选。xaxes 必须为单选/下拉字段，选项数量不超过 8 个时效果最佳。"
            "showPercent 会自动设为 True。"
        ),
    },

    # ─── 4. 环形图 ───────────────────────────────────────────────────────────
    4: {
        "name": "环形图",
        "reportType": 4,
        "category": "proportion",
        "verified": True,
        "module": "pie",
        "description": "环形图（空心饼图），适合展示占比并在中心显示总计",
        "requires": {
            "xaxes": "分类维度字段（单选/下拉，选项数量建议 ≤8）",
            "yaxisList": "1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "showPercent": "自动设为 True（显示百分比）",
        },
        "build_overrides": {
            "displaySetup.showPercent": True,
        },
        "create_params_template": {
            "reportType": 4,
            "xaxes": {
                "controlId": "<单选字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "与饼图用法相同，但视觉上更现代。中心空白处可显示总数。"
            "xaxes 必须为单选/下拉字段。"
        ),
    },

    # ─── 5. 漏斗图 ───────────────────────────────────────────────────────────
    5: {
        "name": "漏斗图",
        "reportType": 5,
        "category": "proportion",
        "verified": True,
        "module": "funnel",
        "description": "漏斗图，适合展示流程转化率（如销售漏斗）",
        "requires": {
            "xaxes": "流程阶段字段（单选/下拉，选项顺序代表漏斗层级）",
            "yaxisList": "1 个数值指标（通常为记录数量）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "showPercent": "自动设为 True（显示转化百分比）",
        },
        "build_overrides": {
            "displaySetup.showPercent": True,
        },
        "create_params_template": {
            "reportType": 5,
            "xaxes": {
                "controlId": "<阶段字段ID>",
                "controlName": "<阶段字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "转化分析场景。xaxes 选代表流程阶段的单选字段（如商机阶段、审批状态）。"
            "showPercent 自动设为 True 以显示各层转化率。"
        ),
    },

    # ─── 6. 雷达图 ───────────────────────────────────────────────────────────
    6: {
        "name": "雷达图",
        "reportType": 6,
        "category": "comparison",
        "verified": False,
        "module": "radar",
        "description": "雷达图（蜘蛛网图），适合多维度综合评估对比",
        "requires": {
            "xaxes": "分类维度字段（代表雷达的各个维度轴）",
            "yaxisList": "1-2 个数值指标（不同系列）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "showLegend": "True = 显示图例",
        },
        "create_params_template": {
            "reportType": 6,
            "xaxes": {
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "多维度综合评估场景。xaxes 为分类字段，每个分类值成为雷达的一条轴。"
            "适合展示不同实体在多个维度上的综合表现（如各部门绩效）。"
        ),
    },

    # ─── 7. 条形图 ───────────────────────────────────────────────────────────
    7: {
        "name": "条形图",
        "reportType": 7,
        "category": "comparison",
        "verified": False,
        "module": "basic",
        "description": "横向条形图，适合类别名称较长或强调排名对比",
        "requires": {
            "xaxes": "分类维度字段（单选/下拉/文本）",
            "yaxisList": "至少 1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "isPile": "True = 堆叠条形图",
        },
        "create_params_template": {
            "reportType": 7,
            "xaxes": {
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "横向柱状图，与柱状图(1)用法相同，但横向排列。"
            "当类别名称较长或需要突出排名对比时优先选用。"
        ),
    },

    # ─── 8. 双轴图 ───────────────────────────────────────────────────────────
    8: {
        "name": "双轴图",
        "reportType": 8,
        "category": "comparison",
        "verified": False,
        "module": "dual_axis",
        "description": "双轴图，左轴柱状图 + 右轴折线图，对比两种量纲不同的指标",
        "requires": {
            "xaxes": "分类/日期维度字段",
            "yaxisList": "至少 2 个数值指标（第 1 个对应左轴柱，第 2 个对应右轴线）",
            "yreportType": "必填：右轴图表类型 1=柱状 2=折线（推荐 2）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"] + XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "special_params": {
            "yreportType": {
                1: "右轴为柱状图",
                2: "右轴为折线图（推荐）",
            }
        },
        "displaySetup_notes": {
            "showLegend": "True = 显示图例",
        },
        "create_params_template": {
            "reportType": 8,
            "yreportType": 2,
            "xaxes": {
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "数量（左轴）",
                },
                {
                    "controlId": "<数值字段ID>",
                    "controlName": "<数值字段名>",
                    "controlType": 6,
                    "normType": 2,
                    "rename": "金额（右轴）",
                },
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "同时展示两个量纲不同的指标（如数量+金额）。"
            "必须设置 yreportType=2（右轴折线图）。"
            "yaxisList 至少 2 项：第 1 项为左轴，第 2 项为右轴。"
        ),
    },

    # ─── 9. 散点图 ───────────────────────────────────────────────────────────
    9: {
        "name": "散点图",
        "reportType": 9,
        "category": "correlation",
        "verified": False,
        "module": "scatter",
        "description": "散点图，分析两个数值维度之间的相关性和分布规律",
        "requires": {
            "xaxes": "数值/分类字段（X 轴维度）",
            "yaxisList": "1-2 个数值指标（Y 轴）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["number"] + XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 9,
            "xaxes": {
                "controlId": "<数值或分类字段ID>",
                "controlName": "<字段名>",
                "controlType": 6,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "<数值字段ID>",
                    "controlName": "<字段名>",
                    "controlType": 6,
                    "normType": 2,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "分析两个数值之间的相关关系（如订单金额 vs 客户评分）。"
            "适合有数值字段的工作表，展示数据分布规律。"
        ),
    },

    # ─── 10. 数值图（数字卡片）───────────────────────────────────────────────
    10: {
        "name": "数值图",
        "reportType": 10,
        "category": "kpi",
        "verified": True,
        "module": "number",
        "description": "数字卡片，单个 KPI 指标大数字展示",
        "requires": {
            "xaxes": "不需要（controlId 必须设为 null）",
            "yaxisList": "1 个数值指标（record_count 或数值字段的聚合）",
        },
        "xaxes_field_types": [],
        "special_params": {
            "xaxes.controlId": None,  # 必须为 null
        },
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "showLegend": "自动设为 False",
            "showDimension": "自动设为 False",
            "fontStyle": "1=普通 2=大字体",
        },
        "build_overrides": {
            "xaxes.controlId": None,
            "xaxes.cid": "null-1",
            "xaxes.c_Id": "null-1",
            "xaxes.controlName": "",
            "xaxes.cname": "",
            "displaySetup.showLegend": False,
            "displaySetup.showDimension": False,
        },
        "create_params_template": {
            "reportType": 10,
            "xaxes": {
                "controlId": None,
                "controlName": "",
                "controlType": 0,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "总记录数",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "KPI 看板数字卡片。xaxes.controlId 必须为 null（这是硬性要求）。"
            "yaxisList 只需 1 个指标。通常 2-3 个数值图放在仪表板顶部展示关键指标。"
        ),
    },

    # ─── 11. 区域图 ───────────────────────────────────────────────────────────
    11: {
        "name": "区域图",
        "reportType": 11,
        "category": "trend",
        "verified": False,
        "module": "basic",
        "description": "带面积填充的折线图，更直观展示数量规模变化",
        "requires": {
            "xaxes": "日期/日期时间字段（同折线图）",
            "yaxisList": "至少 1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "showLegend": "自动设为 False（单系列时通常隐藏）",
            "showDimension": "自动设为 False",
        },
        "build_overrides": {
            "displaySetup.showLegend": False,
            "displaySetup.showDimension": False,
        },
        "create_params_template": {
            "reportType": 11,
            "xaxes": {
                "controlId": "ctime",
                "controlName": "创建时间",
                "controlType": 16,
                "particleSizeType": 1,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "趋势分析，视觉上比折线图更突出面积（数量规模）。"
            "xaxes 必须为日期字段，particleSizeType=1（按月）是常见选择。"
        ),
    },

    # ─── 12. 进度图 ───────────────────────────────────────────────────────────
    12: {
        "name": "进度图",
        "reportType": 12,
        "category": "kpi",
        "verified": False,
        "module": "number",
        "description": "进度条，展示某指标完成进度（当前值 vs 目标值）",
        "requires": {
            "xaxes": "不需要（同数值图，controlId 设为 null）",
            "yaxisList": "1 个数值指标",
        },
        "xaxes_field_types": [],
        "special_params": {
            "xaxes.controlId": None,
        },
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "build_overrides": {
            "xaxes.controlId": None,
            "xaxes.cid": "null-1",
            "xaxes.c_Id": "null-1",
            "xaxes.controlName": "",
            "xaxes.cname": "",
        },
        "create_params_template": {
            "reportType": 12,
            "xaxes": {
                "controlId": None,
                "controlName": "",
                "controlType": 0,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "进度条展示完成率。xaxes.controlId 必须为 null。"
            "适合展示「已完成数/总数」等达成率场景。"
        ),
    },

    # ─── 13. 透视表 ───────────────────────────────────────────────────────────
    13: {
        "name": "透视表",
        "reportType": 13,
        "category": "table",
        "verified": False,
        "module": "table",
        "description": "数据透视表，多维交叉分析，行列交叉展示汇总数据",
        "requires": {
            "xaxes": "行维度字段（单选/下拉/成员/日期）",
            "yaxisList": "至少 1 个数值指标",
            "split": "可选，列维度字段",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"] + XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "displaySetup_notes": {
            "mergeCell": "自动设为 True（合并相同单元格）",
            "showRowList": "自动设为 True（显示行列表）",
        },
        "build_overrides": {
            "displaySetup.mergeCell": True,
            "displaySetup.showRowList": True,
        },
        "create_params_template": {
            "reportType": 13,
            "xaxes": {
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "多维交叉分析，类似 Excel 透视表。"
            "xaxes 为行维度，split 为列维度（可选），yaxisList 为汇总指标。"
        ),
    },

    # ─── 14. 词云图 ───────────────────────────────────────────────────────────
    14: {
        "name": "词云图",
        "reportType": 14,
        "category": "distribution",
        "verified": False,
        "module": "special",
        "description": "词云，适合文本字段的词频分布分析",
        "requires": {
            "xaxes": "文本类字段（controlType=2 文本，或单选字段）",
            "yaxisList": "1 个数值指标（record_count 计数）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["text"] + XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": {1: "COUNT（计数）"},
        "create_params_template": {
            "reportType": 14,
            "xaxes": {
                "controlId": "<文本字段ID>",
                "controlName": "<字段名>",
                "controlType": 2,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "文本频率分析，适合有文本标签、产品名称、客户来源等文本字段的场景。"
            "xaxes 优先选 controlType=2（文本）字段。"
        ),
    },

    # ─── 15. 排行图 ───────────────────────────────────────────────────────────
    15: {
        "name": "排行图",
        "reportType": 15,
        "category": "comparison",
        "verified": False,
        "module": "special",
        "description": "横向排名条形图，自动按数值降序排列，突出 TOP N",
        "requires": {
            "xaxes": "分类维度字段（展示排名的实体，如产品/客户）",
            "yaxisList": "1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"] + XAXES_RECOMMENDED_TYPES["text"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 15,
            "xaxes": {
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "TOP N 排名场景，如销售额 TOP10 客户、发货量 TOP 产品。"
            "图表自动按数值大小排序，适合展示排行榜。"
        ),
    },

    # ─── 16. 地图 ─────────────────────────────────────────────────────────────
    16: {
        "name": "地图",
        "reportType": 16,
        "category": "distribution",
        "verified": False,
        "module": "special",
        "description": "行政地图，按省/市展示地理分布",
        "requires": {
            "xaxes": "地理字段（controlType=19 地区，或文本字段含省市信息）",
            "yaxisList": "1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["geo"] + XAXES_RECOMMENDED_TYPES["text"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 16,
            "xaxes": {
                "controlId": "<地区字段ID>",
                "controlName": "<字段名>",
                "controlType": 19,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "地理分布分析。需要工作表中有地区字段（controlType=19）。"
            "如无地区字段，不要选择此图表类型。"
        ),
    },

    # ─── 17. 关系图 ───────────────────────────────────────────────────────────
    17: {
        "name": "关系图",
        "reportType": 17,
        "category": "special",
        "verified": False,
        "module": "special",
        "description": "层级关系可视化，展示树状或网络关系结构",
        "requires": {
            "xaxes": "关联/层级字段",
            "yaxisList": "1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["relation"] + XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 17,
            "xaxes": {
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "",
                }
            ],
            "filter": {
                "filterRangeId": "ctime",
                "filterRangeName": "创建时间",
                "rangeType": 0,
                "rangeValue": 0,
                "today": False,
            },
        },
        "ai_notes": (
            "层级关系展示。适合有关联关系的数据（如上下级关系、分类树）。"
            "如无明确层级/关联字段，建议改用其他图表类型。"
        ),
    },
}

# ── 分类索引 ─────────────────────────────────────────────────────────────────
CHART_CATEGORIES: dict[str, list[int]] = {
    "comparison":   [1, 6, 7, 8, 15],      # 对比分析
    "trend":        [2, 11],               # 趋势分析
    "proportion":   [3, 4, 5],             # 占比分析
    "correlation":  [9],                   # 相关分析
    "kpi":          [10, 12],              # KPI 单值
    "distribution": [14, 16],             # 分布分析
    "table":        [13],                  # 表格
    "special":      [17],                  # 特殊
}

# ── 特殊行为类型 ───────────────────────────────────────────────────────────────
XAXES_NULL_TYPES: list[int] = [10, 12]           # 不需要 xaxes 维度的图表
SHOW_PERCENT_TYPES: list[int] = [3, 4, 5]        # 自动 showPercent=True
DUAL_AXIS_TYPE: int = 8                          # 需要额外参数 yreportType
VERIFIED_TYPES: list[int] = [1, 2, 3, 4, 5, 10] # 已验证可用的图表类型

# ── AI 规划指南（prompt 片段）─────────────────────────────────────────────────
AI_PLANNING_GUIDE = """
## 明道云统计图规划规则

### reportType 对应图表
1=柱状图  2=折线图  3=饼图  4=环形图  5=漏斗图  6=雷达图
7=条形图  8=双轴图  9=散点图  10=数值图  11=区域图  12=进度图
13=透视表  14=词云图  15=排行图  16=地图  17=关系图

### 选型规则
- 时间趋势分析 → 折线图(2) 或 区域图(11)，xaxes 用日期字段，particleSizeType=1(月)
- 分类占比分析 → 饼图(3) 或 环形图(4)，xaxes 用单选/下拉字段
- 分类对比分析 → 柱状图(1) 或 条形图(7)，xaxes 用单选/下拉/文本字段
- 转化漏斗分析 → 漏斗图(5)，xaxes 用流程阶段字段
- KPI 数字展示 → 数值图(10)，xaxes.controlId 必须为 null
- TOP N 排名   → 排行图(15)，自动按值降序
- 多维对比     → 雷达图(6)
- 两指标对比   → 双轴图(8)，必须设 yreportType=2，yaxisList 至少 2 项

### 硬性约束
- 数值图(10)、进度图(12) 的 xaxes.controlId 必须为 null
- 双轴图(8) 必须设置 yreportType=2（右轴折线图）
- yaxisList 不能为空，至少 1 项
- controlId 必须是工作表中真实存在的字段 ID，或系统字段(ctime/utime/record_count)
- 饼图/环形图(3/4) 的 xaxes 不能用日期字段

### particleSizeType（仅日期字段有效）
0=不分组  1=按月  2=按季度  3=按年  4=按天  5=按周  6=按小时

### normType（yaxisList 聚合类型）
1=COUNT计数  2=SUM求和  3=AVG平均  4=MAX最大  5=MIN最小  6=COUNT DISTINCT去重计数
（record_count 固定用 normType=5，其他数值字段按需选择）
"""


def get_schema(report_type: int) -> dict:
    """获取指定图表类型的完整 schema。"""
    if report_type not in CHART_SCHEMA:
        raise ValueError(f"未知图表类型: reportType={report_type}，支持: {sorted(CHART_SCHEMA.keys())}")
    return CHART_SCHEMA[report_type]


def get_ai_prompt_section() -> str:
    """生成适合注入 AI prompt 的图表类型说明。"""
    lines = ["可用统计图类型（reportType）："]
    for rt, schema in sorted(CHART_SCHEMA.items()):
        verified_tag = "【已验证】" if schema.get("verified") else ""
        lines.append(f"  {rt:2d} = {schema['name']}{verified_tag} — {schema['description']}")
    lines.append("")
    lines.append(AI_PLANNING_GUIDE)
    return "\n".join(lines)


def list_chart_types() -> list[dict]:
    """返回所有图表类型的摘要列表，用于 UI 展示或调试。"""
    return [
        {
            "reportType": rt,
            "name": s["name"],
            "category": s["category"],
            "verified": s.get("verified", False),
            "requires_null_xaxes": rt in XAXES_NULL_TYPES,
            "requires_yreportType": rt == DUAL_AXIS_TYPE,
            "auto_show_percent": rt in SHOW_PERCENT_TYPES,
            "description": s["description"],
        }
        for rt, s in sorted(CHART_SCHEMA.items())
    ]
