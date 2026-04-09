"""
明道云统计图配置参数 Schema — 完整版（抓包校正 2026-04-04）

来源：浏览器抓包确认的 reportType 映射 + saveReportConfig 实际请求体
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
    "controlId": "字段ID（数值图/仪表盘/进度图填空字符串""）",
    "controlName": "字段名",
    "controlType": 16,        # 字段类型 ID
    "particleSizeType": 0,    # 日期粒度（非日期字段填 0）
    "sortType": 0,            # 排序方向：0=默认 1=升序 2=降序
    "emptyType": 0,           # 空值处理：0=显示空值 1=忽略空值
    "rename": "",             # 轴标签重命名
    "showFormat": "4",        # 显示格式（抓包确认为 "4"）
    "dataSource": "",         # 数据来源（抓包确认为空字符串）
    "advancedSetting": {},    # 高级设置（抓包确认为空对象）
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
    "rangeType": 18,   # 抓包默认：18=近N天
    "rangeValue": 365,
    "today": true
  },
  "displaySetup": {...},  # 由 build_fn 自动生成
  "style": {},
  "yreportType": null,   # 仅双轴图(7)/对称条形图(11)使用
}

reportType 映射（抓包确认 2026-04-04）：
  1=柱图  2=折线图  3=饼图/环形图  6=漏斗图  7=双轴图
  8=透视表/雷达图  9=行政区划图  10=数值图  11=对称条形图
  12=散点图  13=词云图  14=仪表盘  15=进度图  16=排行图  17=地图
  不存在: 4(环形图合并入3), 5

聚合类型 normType（yaxisList 使用）：
  1 = SUM 求和
  2 = AVG 平均值
  3 = MAX 最大值
  4 = MIN 最小值
  5 = COUNT 计数
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
from i18n import normalize_language

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
    "region":    [24],                        # 行政区划（controlType=24 Region）
    "relation":  [21, 29],                    # 关联（适合关系图）
    "null":      [],                          # 数值图/仪表盘/进度图（无 xaxes）
}

YAXES_RECOMMENDED_TYPES: dict[str, list[int]] = {
    "count":   [10000000],                    # record_count（通用统计）
    "numeric": [6, 8, 28, 31, 37],            # 数值字段（求和/平均等）
}

# ── normType 说明 ────────────────────────────────────────────────────────────
NORM_TYPE_NAMES: dict[int, str] = {
    1: "SUM（求和）",
    2: "AVG（平均值）",
    3: "MAX（最大值）",
    4: "MIN（最小值）",
    5: "COUNT（计数）",
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
    "showPercent":      False,   # True=显示百分比（饼图建议 True）
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

# ── 通用 xaxes 模板（抓包确认的默认值）──────────────────────────────────────────
_XAXES_COMMON = {
    "controlId": "<字段ID>",
    "controlName": "<字段名>",
    "controlType": 9,
    "particleSizeType": 0,
    "sortType": 0,
    "emptyType": 0,
    "rename": "",
    "showFormat": "4",
    "dataSource": "",
    "advancedSetting": {},
    "xaxisEmptyType": 0,
    "xaxisEmpty": False,
}

# ── 通用 filter 模板（抓包确认的默认值）──────────────────────────────────────────
_FILTER_DEFAULT = {
    "filterRangeId": "ctime",
    "filterRangeName": "创建时间",
    "rangeType": 18,
    "rangeValue": 365,
    "today": True,
}

# ── 通用 yaxisList record_count 模板 ────────────────────────────────────────────
_YAXIS_RECORD_COUNT = {
    "controlId": "record_count",
    "controlName": "记录数量",
    "controlType": 10000000,
    "normType": 5,
    "rename": "",
}

# ── 完整图表 Schema（抓包校正 2026-04-04）────────────────────────────────────────
CHART_SCHEMA: dict[int, dict] = {

    # ─── 1. 柱图 ─────────────────────────────────────────────────────────────
    1: {
        "name": "柱图",
        "reportType": 1,
        "category": "comparison",
        "verified": True,
        "module": "basic",
        "description": "柱图，showChartType=1竖向/2横向。适合比较不同类别的数值大小",
        "requires": {
            "xaxes": "分类维度字段（单选/下拉/文本/成员等）",
            "yaxisList": "至少 1 个数值指标（record_count 或数值字段）",
            "split": "可选，颜色系列维度（分组柱图）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"] + XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 1,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "最通用的图表类型。showChartType=1为竖向柱图，showChartType=2为横向柱图。"
            "xaxes 优先选单选/下拉字段，展示各分类数量分布。"
            "如需对比时间趋势，xaxes 改用日期字段并设 particleSizeType=1（按月）。"
        ),
    },

    # ─── 2. 折线图 ───────────────────────────────────────────────────────────
    2: {
        "name": "折线图",
        "reportType": 2,
        "category": "trend",
        "verified": True,
        "module": "basic",
        "description": "折线图，showChartType=1折线/2面积(区域)图。适合展示随时间变化的趋势",
        "requires": {
            "xaxes": "日期/日期时间字段（controlType=15/16），推荐 ctime 系统字段",
            "yaxisList": "至少 1 个数值指标",
            "split": "可选，系列维度（多线折线图）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 2,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "ctime",
                "controlName": "创建时间",
                "controlType": 16,
                "particleSizeType": 1,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "趋势分析首选。showChartType=1为折线图，showChartType=2为面积(区域)图。"
            "xaxes 必须为日期字段（ctime/utime 或自定义日期字段），"
            "particleSizeType 建议设 1（按月）或 4（按天）。"
        ),
    },

    # ─── 3. 饼图/环形图 ──────────────────────────────────────────────────────
    3: {
        "name": "饼图",
        "reportType": 3,
        "category": "proportion",
        "verified": True,
        "module": "pie",
        "description": "饼图/环形图，showChartType 区分饼/环。展示各类别占总量的比例",
        "requires": {
            "xaxes": "分类维度字段（单选/下拉，选项数量建议 ≤8），cid 不带 -1 后缀",
            "yaxisList": "1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "build_overrides": {
            "displaySetup.showPercent": True,
        },
        "create_params_template": {
            "reportType": 3,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<单选字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "占比分析首选。showChartType=2 为环形图变体。"
            "xaxes 必须为单选/下拉字段，选项数量不超过 8 个时效果最佳。"
            "xaxes.cid 不带 -1 后缀。showPercent 会自动设为 True。"
            "注意：不存在 reportType=4 的环形图，环形图通过 showChartType 控制。"
        ),
    },

    # ─── 6. 漏斗图 ───────────────────────────────────────────────────────────
    6: {
        "name": "漏斗图",
        "reportType": 6,
        "category": "proportion",
        "verified": True,
        "module": "funnel",
        "description": "漏斗图，适合展示流程转化率（如销售漏斗）",
        "requires": {
            "xaxes": "流程阶段字段（单选/下拉，选项顺序代表漏斗层级），cid 不带 -1",
            "yaxisList": "1 个数值指标（通常为记录数量）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 6,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<阶段字段ID>",
                "controlName": "<阶段字段名>",
                "controlType": 9,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "转化分析场景。xaxes 选代表流程阶段的单选字段（如商机阶段、审批状态）。"
            "xaxes.cid 不带 -1 后缀。基础结构，无特殊参数。"
        ),
    },

    # ─── 7. 双轴图 ───────────────────────────────────────────────────────────
    7: {
        "name": "双轴图",
        "reportType": 7,
        "category": "comparison",
        "verified": True,
        "module": "dual_axis",
        "description": "双轴图，左轴 + 右轴，对比两种量纲不同的指标",
        "requires": {
            "xaxes": "分类/日期维度字段",
            "yaxisList": "左轴指标",
            "rightY": "必填：右轴完整配置对象",
            "yreportType": "必填：左轴图表子类型 1=柱 2=折线",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"] + XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "special_params": {
            "yreportType": {
                1: "左轴为柱状图",
                2: "左轴为折线图",
            },
            "rightY": "右轴完整配置，含 reportType/display/split/summary/yaxisList",
        },
        "create_params_template": {
            "reportType": 7,
            "yreportType": 1,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "数量（左轴）",
                },
            ],
            "rightY": {
                "reportType": 2,
                "display": {
                    "showDial": True,
                    "showTitle": False,
                    "title": "",
                    "minValue": None,
                    "maxValue": None,
                    "lineStyle": 1,
                },
                "split": {
                    "controlId": "",
                    "controlName": "",
                    "controlType": 0,
                },
                "summary": {
                    "name": "",
                    "type": 0,
                    "controlId": "",
                    "controlName": "",
                    "controlType": 0,
                    "normType": 0,
                },
                "yaxisList": [
                    {
                        "controlId": "<数值字段ID>",
                        "controlName": "<数值字段名>",
                        "controlType": 6,
                        "normType": 1,
                        "rename": "金额（右轴）",
                    },
                ],
            },
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "同时展示两个量纲不同的指标（如数量+金额）。"
            "必须设置 yreportType（左轴类型）和 rightY 对象（含右轴的 reportType/yaxisList）。"
            "rightY.reportType=2 表示右轴为折线图。"
        ),
    },

    # ─── 8. 透视表/雷达图 ────────────────────────────────────────────────────
    8: {
        "name": "透视表",
        "reportType": 8,
        "category": "table",
        "verified": True,
        "module": "table",
        "description": "透视表/雷达图共用 reportType=8，通过 pivotTable 结构区分",
        "requires": {
            "xaxes": "空对象 {}",
            "yaxisList": "至少 1 个数值指标",
            "pivotTable": "必填：透视表配置（columns/lines/columnSummary/lineSummary）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"] + XAXES_RECOMMENDED_TYPES["date"],
        "particleSizeType_options": PARTICLE_SIZE_NAMES,
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 8,
            "xaxes": {},
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "pivotTable": {
                "columns": [],
                "lines": [
                    {
                        "controlId": "<行维度字段ID>",
                        "controlName": "<字段名>",
                        "controlType": 9,
                        "particleSizeType": 0,
                        "sortType": 0,
                        "emptyType": 0,
                        "rename": "",
                        "showFormat": "4",
                        "dataSource": "",
                        "advancedSetting": {},
                    }
                ],
                "columnSummary": {
                    "controlId": "",
                    "controlName": "",
                    "controlType": 0,
                    "normType": 0,
                    "location": 1,
                    "name": "",
                    "rename": "",
                    "type": 0,
                },
                "lineSummary": {
                    "controlId": "",
                    "controlName": "",
                    "controlType": 0,
                    "normType": 0,
                    "location": 1,
                    "name": "",
                    "rename": "",
                    "type": 0,
                },
            },
            "style": {"paginationVisible": True},
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "透视表/雷达图共用 reportType=8。xaxes 为空对象 {}。"
            "维度通过 pivotTable.lines（行）和 pivotTable.columns（列）配置。"
            "style.paginationVisible=true 启用分页。"
        ),
    },

    # ─── 9. 行政区划图 ───────────────────────────────────────────────────────
    9: {
        "name": "行政区划图",
        "reportType": 9,
        "category": "distribution",
        "verified": True,
        "module": "special",
        "description": "行政区划地图，按省/市展示地理分布",
        "requires": {
            "xaxes": "地区字段（controlType=24 Region）",
            "yaxisList": "1 个数值指标",
            "country": "必填：区划配置对象",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["region"] + XAXES_RECOMMENDED_TYPES["geo"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 9,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<地区字段ID>",
                "controlName": "<字段名>",
                "controlType": 24,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "country": {
                "filterCode": "",
                "filterCodeName": "",
                "municipality": False,
                "particleSizeType": 1,
            },
            "style": {"isDrillDownLayer": True},
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "行政区划地图。需要工作表中有地区字段（controlType=24 Region）。"
            "必须提供 country 对象。style.isDrillDownLayer=true 启用下钻。"
            "如无地区字段，不要选择此图表类型。"
        ),
    },

    # ─── 10. 数值图（数字卡片）──────────────────────────────────────────────
    10: {
        "name": "数值图",
        "reportType": 10,
        "category": "kpi",
        "verified": True,
        "module": "number",
        "description": "数字卡片，单个 KPI 指标大数字展示",
        "requires": {
            "xaxes": "不需要（controlId 设为空字符串 ''）",
            "yaxisList": "1 个数值指标（record_count 或数值字段的聚合，normType=1求和或5计数）",
        },
        "xaxes_field_types": [],
        "special_params": {
            "xaxes.controlId": "",  # 抓包确认：空字符串
        },
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "build_overrides": {
            "xaxes.controlId": "",
            "xaxes.controlName": "",
            "displaySetup.showLegend": False,
            "displaySetup.showDimension": False,
        },
        "create_params_template": {
            "reportType": 10,
            "xaxes": {
                "controlId": "",
                "controlName": "",
                "controlType": 0,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "showFormat": "4",
                "dataSource": "",
                "advancedSetting": {},
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
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "KPI 看板数字卡片。xaxes.controlId 为空字符串（不是 null）。"
            "可以有 xaxes 维度（用分组字段）。yaxisList normType=1(求和) 或 5(计数)。"
            "通常 2-3 个数值图放在仪表板顶部展示关键指标。"
        ),
    },

    # ─── 11. 对称条形图 ──────────────────────────────────────────────────────
    11: {
        "name": "对称条形图",
        "reportType": 11,
        "category": "comparison",
        "verified": True,
        "module": "dual_axis",
        "description": "对称条形图，左右对比两组指标",
        "requires": {
            "xaxes": "分类维度字段",
            "yaxisList": "左侧指标",
            "rightY": "必填：右侧指标配置",
            "yreportType": "必填：左侧图表子类型",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 11,
            "yreportType": 1,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
            },
            "yaxisList": [
                {
                    "controlId": "record_count",
                    "controlName": "记录数量",
                    "controlType": 10000000,
                    "normType": 5,
                    "rename": "左侧指标",
                },
            ],
            "rightY": {
                "reportType": 1,
                "display": {
                    "showDial": True,
                    "showTitle": False,
                    "title": "",
                    "minValue": None,
                    "maxValue": None,
                },
                "split": {
                    "controlId": "",
                    "controlName": "",
                    "controlType": 0,
                },
                "summary": {
                    "name": "",
                    "type": 0,
                    "controlId": "",
                    "controlName": "",
                    "controlType": 0,
                    "normType": 0,
                },
                "yaxisList": [
                    {
                        "controlId": "<数值字段ID>",
                        "controlName": "<数值字段名>",
                        "controlType": 6,
                        "normType": 1,
                        "rename": "右侧指标",
                    },
                ],
            },
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "对称条形图，左右对比两组指标。结构与双轴图(7)类似，"
            "都有 rightY + yreportType。适合对比两个维度的数据分布。"
        ),
    },

    # ─── 12. 散点图 ──────────────────────────────────────────────────────────
    12: {
        "name": "散点图",
        "reportType": 12,
        "category": "correlation",
        "verified": True,
        "module": "scatter",
        "description": "散点图，分析两个数值维度之间的相关性和分布规律",
        "requires": {
            "xaxes": "数值/分类字段（X 轴维度）",
            "yaxisList": "2-3 个数值指标（Y 轴）",
            "split": "可选，分组维度",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["number"] + XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 12,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<数值或分类字段ID>",
                "controlName": "<字段名>",
                "controlType": 6,
            },
            "yaxisList": [
                {
                    "controlId": "<数值字段ID_1>",
                    "controlName": "<字段名1>",
                    "controlType": 6,
                    "normType": 1,
                    "rename": "",
                },
                {
                    "controlId": "<数值字段ID_2>",
                    "controlName": "<字段名2>",
                    "controlType": 6,
                    "normType": 1,
                    "rename": "",
                },
            ],
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "分析两个数值之间的相关关系（如订单金额 vs 客户评分）。"
            "yaxisList 至少 2-3 个指标。支持 split 分组。"
            "适合有数值字段的工作表，展示数据分布规律。"
        ),
    },

    # ─── 13. 词云图 ──────────────────────────────────────────────────────────
    13: {
        "name": "词云图",
        "reportType": 13,
        "category": "distribution",
        "verified": True,
        "module": "special",
        "description": "词云，适合文本字段的词频分布分析",
        "requires": {
            "xaxes": "文本类字段（controlType=2 文本，或单选字段）",
            "yaxisList": "1 个数值指标（record_count 计数）",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["text"] + XAXES_RECOMMENDED_TYPES["classify"],
        "particleSizeType_options": {},
        "normType_options": {5: "COUNT（计数）"},
        "create_params_template": {
            "reportType": 13,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<文本字段ID>",
                "controlName": "<字段名>",
                "controlType": 2,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "文本频率分析。基础结构，无特殊参数。"
            "适合有文本标签、产品名称、客户来源等文本字段的场景。"
            "xaxes 优先选 controlType=2（文本）字段。"
        ),
    },

    # ─── 14. 仪表盘 ──────────────────────────────────────────────────────────
    14: {
        "name": "仪表盘",
        "reportType": 14,
        "category": "kpi",
        "verified": True,
        "module": "number",
        "description": "仪表盘，圆弧进度展示单个指标完成情况",
        "requires": {
            "xaxes": "不需要（controlId 设为空字符串 ''）",
            "yaxisList": "1 个数值指标",
            "config": "必填：min/max/targetList 目标配置",
        },
        "xaxes_field_types": [],
        "special_params": {
            "xaxes.controlId": "",
            "showChartType": 3,
        },
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "build_overrides": {
            "xaxes.controlId": "",
            "xaxes.controlName": "",
            "displaySetup.showChartType": 3,
        },
        "create_params_template": {
            "reportType": 14,
            "xaxes": {
                "controlId": "",
                "controlName": "",
                "controlType": 0,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "showFormat": "4",
                "dataSource": "",
                "advancedSetting": {},
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "config": {
                "targetList": [],
                "min": {
                    "controlId": "",
                    "controlName": "",
                    "controlType": 0,
                    "normType": 0,
                    "value": 0,
                },
                "max": {
                    "controlId": "",
                    "controlName": "",
                    "controlType": 0,
                    "normType": 0,
                    "value": 100,
                },
            },
            "displaySetup": {"showChartType": 3},
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "仪表盘/仪表图。xaxes.controlId 为空字符串。showChartType=3。"
            "config.min/max 定义刻度范围，config.targetList 定义目标线。"
            "适合展示单个 KPI 指标的完成进度。"
        ),
    },

    # ─── 15. 进度图 ──────────────────────────────────────────────────────────
    15: {
        "name": "进度图",
        "reportType": 15,
        "category": "kpi",
        "verified": True,
        "module": "number",
        "description": "进度条，展示某指标完成进度（当前值 vs 目标值）",
        "requires": {
            "xaxes": "不需要（controlId 设为空字符串 ''）",
            "yaxisList": "1 个数值指标",
            "config": "必填：targetList 目标配置",
        },
        "xaxes_field_types": [],
        "special_params": {
            "xaxes.controlId": "",
        },
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "build_overrides": {
            "xaxes.controlId": "",
            "xaxes.controlName": "",
        },
        "create_params_template": {
            "reportType": 15,
            "xaxes": {
                "controlId": "",
                "controlName": "",
                "controlType": 0,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "showFormat": "4",
                "dataSource": "",
                "advancedSetting": {},
                "xaxisEmptyType": 0,
                "xaxisEmpty": False,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "config": {
                "min": None,
                "max": None,
                "targetList": [
                    {
                        "name": "目标",
                        "value": 100,
                        "color": "#2196F3",
                    }
                ],
            },
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "进度条展示完成率。xaxes.controlId 为空字符串（不是 null）。"
            "config.targetList 定义目标值。适合展示「已完成数/目标数」等达成率场景。"
        ),
    },

    # ─── 16. 排行图 ──────────────────────────────────────────────────────────
    16: {
        "name": "排行图",
        "reportType": 16,
        "category": "comparison",
        "verified": True,
        "module": "special",
        "description": "排行榜，自动按数值降序排列，突出 TOP N",
        "requires": {
            "xaxes": "分类维度字段（展示排名的实体），cid 不带 -1 后缀",
            "yaxisList": "1 个数值指标",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["classify"] + XAXES_RECOMMENDED_TYPES["text"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 16,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<字段ID>",
                "controlName": "<字段名>",
                "controlType": 9,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "style": {
                "topStyle": "crown",
                "valueProgressVisible": True,
            },
            "sorts": [{"record_count": 2}],
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "TOP N 排名场景，如销售额 TOP10 客户、发货量 TOP 产品。"
            "xaxes.cid 不带 -1 后缀。style.topStyle='crown' 展示皇冠图标。"
            "sorts 指定排序：[{'record_count': 2}] 表示按记录数降序。"
        ),
    },

    # ─── 17. 地图 ────────────────────────────────────────────────────────────
    17: {
        "name": "地图",
        "reportType": 17,
        "category": "distribution",
        "verified": True,
        "module": "special",
        "description": "地图，按地理位置展示数据分布",
        "requires": {
            "xaxes": "地理字段（controlType=19 地区，或文本字段含省市信息）",
            "yaxisList": "1 个数值指标",
            "country": "必填：地图区划配置",
            "split": "完整字段对象",
        },
        "xaxes_field_types": XAXES_RECOMMENDED_TYPES["geo"] + XAXES_RECOMMENDED_TYPES["text"],
        "particleSizeType_options": {},
        "normType_options": NORM_TYPE_NAMES,
        "create_params_template": {
            "reportType": 17,
            "xaxes": {
                **_XAXES_COMMON,
                "controlId": "<地区字段ID>",
                "controlName": "<字段名>",
                "controlType": 19,
            },
            "yaxisList": [{**_YAXIS_RECORD_COUNT}],
            "country": {
                "filterCode": "",
                "filterCodeName": "",
                "municipality": False,
                "particleSizeType": 1,
            },
            "split": {
                "controlId": "<分组字段ID>",
                "controlName": "<分组字段名>",
                "controlType": 9,
                "particleSizeType": 0,
                "sortType": 0,
                "emptyType": 0,
                "rename": "",
                "showFormat": "4",
                "dataSource": "",
                "advancedSetting": {},
            },
            "filter": {**_FILTER_DEFAULT},
        },
        "ai_notes": (
            "地理分布分析。需要工作表中有地区字段（controlType=19）。"
            "必须提供 country 对象和 split 字段对象。"
            "如无地区字段，不要选择此图表类型。"
        ),
    },
}

# ── 分类索引（抓包校正 2026-04-04）──────────────────────────────────────────
CHART_CATEGORIES: dict[str, list[int]] = {
    "comparison":   [1, 7, 11, 16],       # 对比分析（柱图、双轴图、对称条形图、排行图）
    "trend":        [2],                   # 趋势分析（折线图；面积图通过 showChartType=2 实现）
    "proportion":   [3, 6],                # 占比分析（饼图/环形图、漏斗图）
    "correlation":  [12],                  # 相关分析（散点图）
    "kpi":          [10, 14, 15],          # KPI 单值（数值图、仪表盘、进度图）
    "distribution": [9, 13, 17],           # 分布分析（行政区划图、词云图、地图）
    "table":        [8],                   # 表格（透视表/雷达图）
}

# ── 特殊行为类型（抓包校正 2026-04-04）──────────────────────────────────────
XAXES_NULL_TYPES: list[int] = [10, 14, 15]       # 不需要 xaxes 维度的图表（数值图、仪表盘、进度图）
SHOW_PERCENT_TYPES: list[int] = [3]               # 自动 showPercent=True（只有饼图）
DUAL_AXIS_TYPE: int = 7                           # 需要额外参数 rightY + yreportType
VERIFIED_TYPES: list[int] = [1, 2, 3, 10]         # 已验证可用的图表类型

# ── AI 规划指南（prompt 片段）─────────────────────────────────────────────────
AI_PLANNING_GUIDE = """
## 明道云统计图规划规则

### reportType 对应图表（抓包确认 2026-04-04）
1=柱图(showChartType=1竖向/2横向)  2=折线图(showChartType=1折线/2面积)
3=饼图/环形图(showChartType区分)  6=漏斗图  7=双轴图(rightY+yreportType)
8=透视表/雷达图(pivotTable)  9=行政区划图(country)  10=数值图
11=对称条形图(rightY+yreportType)  12=散点图  13=词云图
14=仪表盘(config.min/max,showChartType=3)  15=进度图(config.targetList)
16=排行图(style.topStyle+sorts)  17=地图(country+split)
注意：不存在 reportType=4(环形图合并入3) 和 5

### 选型规则
- 时间趋势分析 → 折线图(2)，xaxes 用日期字段，particleSizeType=1(月)
- 面积(区域)图 → 折线图(2) + showChartType=2
- 横向柱图     → 柱图(1) + showChartType=2
- 分类占比分析 → 饼图(3)，环形图用 showChartType 切换
- 分类对比分析 → 柱图(1)，xaxes 用单选/下拉/文本字段
- 转化漏斗分析 → 漏斗图(6)，xaxes 用流程阶段字段
- KPI 数字展示 → 数值图(10)，xaxes.controlId 为空字符串
- 仪表盘进度   → 仪表盘(14) showChartType=3，或进度图(15)
- TOP N 排名   → 排行图(16)，style.topStyle + sorts
- 双指标对比   → 双轴图(7)，必须设 rightY + yreportType
- 左右对称对比 → 对称条形图(11)
- 多维交叉分析 → 透视表(8)，用 pivotTable 结构
- 地理分布     → 行政区划图(9) 或 地图(17)

### 硬性约束
- 数值图(10)、仪表盘(14)、进度图(15) 的 xaxes.controlId 为空字符串 ""
- 双轴图(7)、对称条形图(11) 必须设置 rightY 和 yreportType
- 透视表(8) 的 xaxes 为空对象 {}，维度通过 pivotTable.lines/columns 配置
- yaxisList 不能为空，至少 1 项
- controlId 必须是工作表中真实存在的字段 ID，或系统字段(ctime/utime/record_count)
- 饼图(3) 的 xaxes 不能用日期字段
- filter 默认: rangeType=18, rangeValue=365, today=true
- xaxes 通用字段: showFormat="4", dataSource="", advancedSetting={}

### particleSizeType（仅日期字段有效）
0=不分组  1=按月  2=按季度  3=按年  4=按天  5=按周  6=按小时

### normType（yaxisList 聚合类型）
1=SUM求和  2=AVG平均  3=MAX最大  4=MIN最小  5=COUNT计数  6=COUNT DISTINCT去重计数
（record_count 固定用 normType=5，其他数值字段按需选择）
"""


def get_schema(report_type: int) -> dict:
    """获取指定图表类型的完整 schema。"""
    if report_type not in CHART_SCHEMA:
        raise ValueError(f"未知图表类型: reportType={report_type}，支持: {sorted(CHART_SCHEMA.keys())}")
    return CHART_SCHEMA[report_type]


def get_ai_prompt_section(language: str = "zh") -> str:
    """生成适合注入 AI prompt 的图表类型说明。"""
    lang = normalize_language(language)
    if lang == "en":
        lines = ["Available chart types (reportType):"]
    else:
        lines = ["可用统计图类型（reportType）："]
    for rt, schema in sorted(CHART_SCHEMA.items()):
        if lang == "en":
            verified_tag = " [Verified]" if schema.get("verified") else ""
        else:
            verified_tag = "【已验证】" if schema.get("verified") else ""
        lines.append(f"  {rt:2d} = {schema['name']}{verified_tag} — {schema['description']}")
    lines.append("")
    if lang == "en":
        lines.append(
            "Hard constraints: for reportType 10/14/15 use empty xaxes.controlId; "
            "for reportType 7/11 provide rightY and yreportType; yaxisList cannot be empty; "
            "controlId must come from worksheet fields or system fields (ctime/utime/record_count)."
        )
    else:
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
