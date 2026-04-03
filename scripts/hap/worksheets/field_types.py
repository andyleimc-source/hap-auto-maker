"""
HAP 工作表字段类型定义 — 完整版（38 种，已全部通过 API 创建验证）。

来源：SaveWorksheetControls API 逐 type 测试 + 明道云前端字段编辑面板 + GetWorksheetControls 实测
录制时间：2026-04-03

字段类型 ID（type）与名称对照（API 实测）：
  2  = 文本（单行文本）
  3  = 手机号
  4  = 座机
  5  = 邮箱
  6  = 数值
  7  = 链接
  8  = 金额（货币）
  9  = 单选（平铺）
  10 = 多选（标签）
  11 = 下拉（下拉选择）
  14 = 附件
  15 = 日期
  16 = 日期时间
  22 = 分段（表单布局分段标题，不存储数据）
  24 = 地区（省市区）
  25 = 大写金额
  26 = 成员
  27 = 部门
  28 = 等级（星级评分）
  29 = 关联记录
  30 = 他表字段（关联查询）
  31 = 公式（数值）
  32 = 文本组合（文本公式）
  33 = 自动编号
  34 = 子表
  35 = 级联选择
  36 = 检查框（布尔）
  37 = 汇总（关联聚合）
  38 = 公式（日期）
  40 = 定位（GPS）
  41 = 富文本
  42 = 签名
  43 = 二维码
  45 = 嵌入（外部页面）
  46 = 时间
  47 = 评分
  48 = 组织角色
  49 = 备注说明（表单静态文本，不存储数据）
"""

from __future__ import annotations

FIELD_REGISTRY = {
    # ── 基础文本 ──
    "Text": {
        "controlType": 2, "name": "文本", "category": "basic",
        "can_be_title": True,
        "doc": "单行文本。第一个自动设为标题(attribute=1)。",
        "advancedSetting": {
            "sorttype": "zh",          # 排序方式：zh=中文, en=英文
            "analysislink": "0",       # 解析为超链接：0=否, 1=是
            # 可选验证设置：
            # "regex": "",             # 正则表达式（如手机号格式）
            # "regexmsg": "",          # 正则验证失败提示
            # "minlen": "0",           # 最小字符数
            # "maxlen": "200",         # 最大字符数
            # "defaulttype": "0",      # 默认值：0=无, 1=自定义, 2=当前用户名
        },
    },
    "RichText": {
        "controlType": 41, "name": "富文本", "category": "basic",
        "doc": "富文本编辑器，支持格式化文字、图片、表格等内容。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "AutoNumber": {
        "controlType": 33, "name": "自动编号", "category": "basic",
        "doc": "自动递增编号，创建记录时自动分配。advancedSetting 可配前缀和格式。",
        "api_extra": {"strDefault": "increase"},
        "advancedSetting": {
            "sorttype": "zh",
            # 编号格式（可选）：
            # "prefix": "NO-",        # 前缀（如 ORD-, NO-）
            # "digits": "4",          # 位数（4=0001 起）
            # "start": "1",           # 起始值
            # "step": "1",            # 步长
        },
    },
    "TextCombine": {
        "controlType": 32, "name": "文本组合", "category": "basic",
        "doc": "文本公式：多字段文本拼接，支持引用其他字段。",
        "advancedSetting": {
            "sorttype": "zh",
            "analysislink": "1",       # 结果自动解析为链接
            # "formula": "",           # 拼接公式（引用字段用 $字段名$）
        },
    },

    # ── 数值 ──
    "Number": {
        "controlType": 6, "name": "数值", "category": "number",
        "doc": "数字字段，precision=2。支持千分位、进度条显示。",
        "api_extra": {"dot": 2},
        "advancedSetting": {
            "sorttype": "zh",
            "thousandth": "0",         # 千分位显示：0=否, 1=是
            "numshow": "0",            # 显示方式：0=数字, 1=进度条
            "showtype": "0",           # 0=默认数字显示
            # "unit": "",              # 单位（如 "个", "次", "元"）
            # "unitpos": "0",          # 单位位置：0=后, 1=前
        },
    },
    "Money": {
        "controlType": 8, "name": "金额", "category": "number",
        "doc": "货币金额字段，precision=2, unit=¥。",
        "api_extra": {"dot": 2, "unit": "¥"},
        "advancedSetting": {
            "sorttype": "zh",
            # "thousandth": "1",       # 默认显示千分位
        },
    },
    "MoneyCapital": {
        "controlType": 25, "name": "大写金额", "category": "number",
        "doc": "金额转中文大写（如：壹万元整）。通常引用金额字段自动转换。",
        "advancedSetting": {
            "sorttype": "zh",
            # "dataSource": "",        # 引用金额字段的 controlId
        },
    },
    "Formula": {
        "controlType": 31, "name": "公式", "category": "number",
        "doc": "数值计算公式，支持四则运算和字段引用（$字段名$）。",
        "advancedSetting": {
            "sorttype": "zh",
            "nullzero": "0",           # 空值处理：0=显示空, 1=显示0
            # "formula": "",           # 公式内容（如 "$数量$ * $单价$"）
            # "dot": "2",              # 小数位数
        },
    },
    "FormulaDate": {
        "controlType": 38, "name": "公式日期", "category": "number",
        "doc": "日期计算公式（如剩余天数、在职时长）。",
        "advancedSetting": {
            "sorttype": "zh",
            # "formula": "",           # 日期公式
            # "showtype": "3",         # 结果格式（同日期字段）
        },
    },

    # ── 选择 ──
    "SingleSelect": {
        "controlType": 9, "name": "单选", "category": "select",
        "doc": "单选字段（平铺展示），需 option_values(3-8 项)。适合看板分组。",
        "requires_options": True,
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "1",           # 显示方式：0=下拉, 1=平铺（推荐）, 2=颜色块
        },
        "options_format": {
            "key": "选项唯一 ID（创建时可省略，系统自动生成）",
            "value": "选项显示名称（必填）",
            "index": "排序序号（从0开始）",
            "color": "颜色（如 #2196F3，可选）",
            "score": "分值（用于评分计算，默认0）",
        },
    },
    "MultipleSelect": {
        "controlType": 10, "name": "多选", "category": "select",
        "doc": "多选字段（标签样式），需 option_values。",
        "requires_options": True,
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "Dropdown": {
        "controlType": 11, "name": "下拉框", "category": "select",
        "doc": "下拉选择（下拉展示），用于看板分组、选项较多时。需 option_values。",
        "requires_options": True,
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "0",           # 0=下拉单选（默认）
        },
    },
    "Checkbox": {
        "controlType": 36, "name": "检查框", "category": "select",
        "doc": "布尔开关（是/否），如\"是否完成\"、\"是否优先\"。",
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "0",           # 显示方式：0=方形复选框, 1=开关/拨码
        },
    },
    "Rating": {
        "controlType": 28, "name": "等级", "category": "select",
        "doc": "星级评分（1-5星），用于客户评级、重要程度等。",
        "advancedSetting": {
            "sorttype": "zh",
            # "max": "5",              # 最高等级（默认5）
            # "style": "0",            # 样式：0=星形, 1=心形, 2=旗帜
        },
    },
    "Score": {
        "controlType": 47, "name": "评分", "category": "select",
        "doc": "数值评分字段，用于满意度评分、质量评级等。",
        "advancedSetting": {
            "sorttype": "zh",
            # "max": "5",              # 最高分（默认5）
            # "style": "0",            # 样式：0=星形, 1=心形
        },
    },

    # ── 日期时间 ──
    "Date": {
        "controlType": 15, "name": "日期", "category": "date",
        "doc": "日期字段（无时间）。适合甘特图、日历视图，如开始日期、截止日期。",
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "3",           # 格式：3=YYYY-MM-DD（推荐）, 5=YYYY/MM/DD, 6=YYYY年MM月DD日
            "showformat": "0",         # 0=不显示时间
            # "defaulttype": "0",      # 默认值：0=无, 1=录入时间, 2=自定义
        },
        "advancedSetting_showtype": {
            "3": "YYYY-MM-DD（推荐）",
            "5": "YYYY/MM/DD",
            "6": "YYYY年MM月DD日",
        },
    },
    "DateTime": {
        "controlType": 16, "name": "日期时间", "category": "date",
        "doc": "日期+时间。适合日历视图，如会议时间、操作时间。",
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "1",           # 格式：1=YYYY-MM-DD HH:mm（推荐）
            "showformat": "0",         # 0=显示时间（默认）
            # "defaulttype": "0",      # 默认值：0=无, 1=录入时间
        },
    },
    "Time": {
        "controlType": 46, "name": "时间", "category": "date",
        "doc": "仅时间字段（时:分），不含日期。",
        "advancedSetting": {
            "sorttype": "zh",
            # "showtype": "0",         # 格式：0=HH:mm, 1=HH:mm:ss
        },
    },

    # ── 联系方式 ──
    "Phone": {
        "controlType": 3, "name": "电话", "category": "contact",
        "doc": "手机号码字段，自动验证格式，支持拨号。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "Landline": {
        "controlType": 4, "name": "座机", "category": "contact",
        "doc": "座机电话字段，支持带区号的固定电话。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "Email": {
        "controlType": 5, "name": "邮箱", "category": "contact",
        "doc": "邮箱地址字段，自动验证格式，支持发送邮件。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "Link": {
        "controlType": 7, "name": "链接", "category": "contact",
        "doc": "URL 链接字段，支持点击跳转外部网页。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },

    # ── 人员组织 ──
    "Collaborator": {
        "controlType": 26, "name": "成员", "category": "people",
        "doc": "成员字段（负责人/参与者），required 强制 false。",
        "force_not_required": True,
        "advancedSetting": {
            "sorttype": "zh",
            "usertype": "1",           # 选人类型：0=组织成员范围, 1=多人选择（推荐）, 2=单人选择
            # "appointedate": "0",     # 是否允许选非成员
        },
        "advancedSetting_usertype": {
            "0": "组织成员（仅限组织内成员）",
            "1": "多人选择（推荐，可多选成员）",
            "2": "单人选择（只能选一个）",
        },
    },
    "Department": {
        "controlType": 27, "name": "部门", "category": "people",
        "doc": "部门选择字段，从组织架构中选取部门。",
        "advancedSetting": {
            "sorttype": "zh",
            # "multiple": "1",         # 是否多选：0=单选, 1=多选（默认多选）
        },
    },
    "OrgRole": {
        "controlType": 48, "name": "组织角色", "category": "people",
        "doc": "组织角色选择字段，从系统预定义角色中选择。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },

    # ── 关联 ──
    "Relation": {
        "controlType": 29, "name": "关联记录", "category": "relation",
        "doc": "关联字段，需 relation_target（目标工作表名）。第二阶段创建。",
        "requires_relation_target": True,
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "2",           # 显示类型：2=卡片（推荐）, 1=列表
            "allowlink": "1",          # 允许点击跳转：0=否, 1=是
            "searchrange": "0",        # 搜索范围：0=全部
            "scanlink": "1",           # 允许扫码关联
            "scancontrol": "1",        # 允许扫码控制
            "allowdelete": "1",        # 允许删除关联
            "allowexport": "1",        # 允许导出关联记录
            "allowedit": "1",          # 允许编辑关联记录
            "showquick": "1",          # 显示快速查看按钮
        },
        "api_extra": {
            "dataSource": "<target_worksheetId>",  # 目标工作表 ID（必填）
            "enumDefault": 2,                      # 关联显示模式
            "subType": 1,                          # 1=单条关联
        },
    },
    "OtherTableField": {
        "controlType": 30, "name": "他表字段", "category": "relation",
        "doc": "引用关联表字段值，需先有关联字段。dataSource=关联字段 controlId。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "api_extra": {
            "dataSource": "<relation_controlId>",  # 关联字段的 controlId
        },
    },
    "SubTable": {
        "controlType": 34, "name": "子表", "category": "relation",
        "doc": "子表（嵌入式关联表），在主记录中展示子记录列表。",
        "advancedSetting": {
            "sorttype": "zh",
            "allowadd": "1",           # 允许新增子记录
            "allowcancel": "1",        # 允许取消关联
            "allowedit": "1",          # 允许编辑子记录
            "allowsingle": "1",        # 允许单条操作
            "allowlink": "1",          # 允许点击跳转
            "allowexport": "1",        # 允许导出
            "enablelimit": "1",        # 启用数量限制
            "min": "0",                # 最少子记录数
            "max": "200",              # 最多子记录数
            "blankrow": "1",           # 显示空白行方便录入
        },
    },
    "Cascade": {
        "controlType": 35, "name": "级联选择", "category": "relation",
        "doc": "级联多级选择（如省/市/区），需配置树形数据源。",
        "advancedSetting": {
            "sorttype": "zh",
            "allpath": "0",            # 显示完整路径：0=否, 1=是
            "anylevel": "0",           # 允许选任意级别：0=否（必须选到叶节点）, 1=是
            "allowlink": "1",          # 允许跳转
        },
    },
    "Rollup": {
        "controlType": 37, "name": "汇总", "category": "relation",
        "doc": "汇总关联表数据（求和/计数/平均/最大/最小），需先有关联字段。",
        "advancedSetting": {
            "sorttype": "zh",
            # "aggregateType": "SUM",  # 聚合方式：SUM/COUNT/AVG/MAX/MIN
        },
        "api_extra": {
            "dataSource": "<relation_controlId>",  # 关联字段的 controlId
        },
    },

    # ── 文件 ──
    "Attachment": {
        "controlType": 14, "name": "附件", "category": "file",
        "doc": "文件上传，支持图片、文档、视频等多种格式。",
        "advancedSetting": {
            "sorttype": "zh",
            # "filetypes": "",         # 限制文件类型（如 "image/*"）
            # "filecount": "0",        # 最大文件数（0=不限）
        },
    },
    "Signature": {
        "controlType": 42, "name": "签名", "category": "file",
        "doc": "手写签名字段，用于合同签署、确认签收等。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },

    # ── 地理位置 ──
    "Area": {
        "controlType": 24, "name": "地区", "category": "location",
        "doc": "地区选择（省/市/区级联）。enumDefault2 控制精度（1=省, 2=市, 3=区）。",
        "api_extra": {"enumDefault2": 3},
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_enumDefault2": {
            "1": "仅省级",
            "2": "省+市",
            "3": "省+市+区（默认）",
        },
    },
    "Location": {
        "controlType": 40, "name": "定位", "category": "location",
        "doc": "GPS 定位字段，支持在地图上标记或记录当前坐标。",
        "advancedSetting": {
            "sorttype": "zh",
            # "maptype": "0",          # 地图类型：0=百度, 1=高德
        },
    },

    # ── 高级/特殊 ──
    "QRCode": {
        "controlType": 43, "name": "二维码", "category": "advanced",
        "doc": "自动生成记录链接的二维码，扫码可直接跳转到记录。",
        "advancedSetting": {
            "sorttype": "zh",
            # "qrtype": "0",           # 0=记录链接, 1=指定字段值
            # "sourceControlId": "",   # qrtype=1 时引用的字段 controlId
        },
    },
    "Embed": {
        "controlType": 45, "name": "嵌入", "category": "advanced",
        "doc": "嵌入外部网页，支持动态引用本条记录字段值拼接 URL。",
        "advancedSetting": {
            "sorttype": "zh",
            # "url": "",               # 嵌入 URL（可引用字段值）
            # "height": "400",         # 嵌入区域高度（像素）
        },
    },

    # ── 布局（不存储数据）──
    "Section": {
        "controlType": 22, "name": "分段", "category": "layout",
        "doc": "表单分段标题（不存储数据），用于将字段分组显示。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "Remark": {
        "controlType": 49, "name": "备注说明", "category": "layout",
        "doc": "表单中的静态文本说明（不存储数据），用于填写提示。",
        "advancedSetting": {
            "sorttype": "zh",
            # "remark": "",            # 说明内容（富文本）
        },
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
