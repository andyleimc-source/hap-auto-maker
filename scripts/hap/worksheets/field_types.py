"""
HAP 工作表字段类型定义 — 完整版（38 种，已全部通过 API 创建验证）。

来源：
  1. SaveWorksheetControls API 逐 type 创建 + GetWorksheetControls 实测返回 (2026-04-04)
  2. pd-openweb GitHub 源码 src/pages/widgetConfig 提取完整配置项
  3. UI 创建的工作表采样对比

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
        "doc": "单行文本。第一个自动设为标题(attribute=1)。enumDefault: 0=自动, 1=多行, 2=单行, 3=Markdown。",
        "advancedSetting": {
            "sorttype": "zh",
            "analysislink": "1",       # "0"=不解析链接, "1"=自动解析超链接
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式: zh/en",
            "analysislink": "解析为超链接: 0=否, 1=是",
            "datamask": "数据掩码: 0=禁用, 1=启用",
            "filterregex": "正则过滤模式（字符串）",
            "encryId": "加密标识（字符串，Markdown 模式下清空）",
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
        "doc": "自动递增编号，创建记录时自动分配。strDefault='increase' 必填。",
        "api_extra": {"strDefault": "increase"},
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "increase": "JSON 编号规则数组 [{type:1-4, repeatType:0-4, start, length, format}]。type: 1=序号, 2=固定字符, 3=引用字段, 4=创建时间。repeatType: 0=不重置, 1=每天, 2=每周, 3=每月, 4=每年",
            "usetimezone": "使用时区",
        },
    },
    "TextCombine": {
        "controlType": 32, "name": "文本组合", "category": "basic",
        "doc": "文本公式：多字段文本拼接，支持引用其他字段。",
        "advancedSetting": {
            "sorttype": "zh",
            "analysislink": "1",
        },
    },

    # ── 数值 ──
    "Number": {
        "controlType": 6, "name": "数值", "category": "number",
        "doc": "数字字段，precision=dot。支持千分位、进度条、滑块、计步器。",
        "api_extra": {"dot": 2},
        "advancedSetting": {
            "sorttype": "zh",
            "thousandth": "0",
            "numshow": "0",
            "showtype": "0",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "thousandth": "千分位: 0=否, 1=是",
            "numshow": "百分比显示: 0=否, 1=是",
            "showtype": "输入方式: 0=数值, 2=滑块, 3=计步器",
            "numinterval": "步长值（滑块/计步器）",
            "min": "最小值",
            "max": "最大值",
            "itemcolor": "滑块颜色 JSON {type:1=固定/2=动态, color, colors}",
            "showinput": "滑块模式显示输入框: 1=是",
            "suffix": "单位后缀（替代旧 unit 字段）",
            "datamask": "数据掩码",
            "checkrange": "范围校验: 0=否, 1=是",
        },
    },
    "Money": {
        "controlType": 8, "name": "金额", "category": "number",
        "doc": "货币金额字段，precision=dot, unit=¥。",
        "api_extra": {"dot": 2, "unit": "¥"},
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "currency": "货币配置 JSON {currencycode, symbol}",
            "currencynames": "货币名称 JSON {0-4: 单复数子单位}",
            "showformat": "显示格式: 0=自定义, 1=货币符号, 2=货币代码",
            "suffix": "自定义后缀（showformat=0 时，默认'元'）",
            "prefix": "自定义前缀",
            "roundtype": "进位方式",
        },
    },
    "MoneyCapital": {
        "controlType": 25, "name": "大写金额", "category": "number",
        "doc": "金额转中文大写（如：壹万元整）。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "Formula": {
        "controlType": 31, "name": "公式", "category": "number",
        "doc": "数值计算公式，支持四则运算和字段引用。",
        "advancedSetting": {
            "sorttype": "zh",
            "nullzero": "0",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "nullzero": "空值处理: 0=显示空, 1=显示0",
            "suffix": "单位后缀",
            "roundtype": "进位方式",
        },
    },
    "FormulaDate": {
        "controlType": 38, "name": "公式日期", "category": "number",
        "doc": "日期计算公式（如剩余天数、在职时长）。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },

    # ── 选择 ──
    "SingleSelect": {
        "controlType": 9, "name": "单选", "category": "select",
        "doc": "单选字段（平铺展示），需 option_values(3-8 项)。适合看板分组。",
        "requires_options": True,
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "1",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "showtype": "显示方式: 0=下拉, 1=平铺(默认), 2=进度",
            "allowadd": "允许新增选项: 0=否, 1=是",
            "readonlyshowall": "只读时显示全部",
        },
        "options_format": {
            "key": "选项唯一 ID",
            "value": "选项显示名称（必填）",
            "index": "排序序号（从1开始）",
            "color": "颜色 hex（可选）",
            "score": "分值（默认0.0，服务端自动补）",
            "isDeleted": "是否已删除（服务端自动补 false）",
            "hide": "是否隐藏（服务端自动补 false）",
        },
    },
    "MultipleSelect": {
        "controlType": 10, "name": "多选", "category": "select",
        "doc": "多选字段（标签样式），需 option_values。",
        "requires_options": True,
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "checktype": "显示格式: 0=平铺, 1=下拉",
            "allowadd": "允许新增: 0=否, 1=是",
            "readonlyshowall": "只读时显示全部",
        },
    },
    "Dropdown": {
        "controlType": 11, "name": "下拉框", "category": "select",
        "doc": "下拉选择（下拉展示），用于看板分组、选项较多时。需 option_values。",
        "requires_options": True,
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "0",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "showtype": "显示模式: 0=下拉, 1=平铺, 2=进度",
            "direction": "移动端方向: 0=横向, 1=纵向",
            "otherrequired": "其他选项必填: 0=否, 1=是",
            "readonlyshowall": "只读时显示全部",
        },
    },
    "Checkbox": {
        "controlType": 36, "name": "检查框", "category": "select",
        "doc": "布尔开关（是/否），如'是否完成'。",
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "0",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "showtype": "显示方式: 0=复选框, 1=文字标签, 2=自定义文字",
            "itemnames": "自定义文字标签 JSON [{value}]（showtype=1/2 时）",
            "defsource": "默认值来源配置 JSON",
        },
    },
    "Rating": {
        "controlType": 28, "name": "等级", "category": "select",
        "doc": "星级评分，用于客户评级、重要程度等。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "max": "最高等级数（0=默认5）",
            "itemicon": "图标配置",
            "itemcolor": "颜色 JSON {type:1=固定/2=按等级, color, colors}",
            "showvalue": "显示数值: 1=是",
        },
    },
    "Score": {
        "controlType": 47, "name": "评分", "category": "select",
        "doc": "数值评分字段，用于满意度评分、质量评级等。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },

    # ── 日期时间 ──
    "Date": {
        "controlType": 15, "name": "日期", "category": "date",
        "doc": "日期字段（无时间）。适合甘特图、日历视图。",
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "3",
            "showformat": "0",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "showtype": "格式: 1=年, 2=年月, 3=年月日, 4=时, 5=时分, 6=时分秒",
            "showformat": "时间显示: 0=不显示, 1=显示",
            "timezonetype": "时区: 0=用户时区, 1=应用时区",
            "showtimezone": "显示时区标识: 0=否, 1=是",
            "allowweek": "周显示",
            "allowtime": "时间显示",
            "timeinterval": "分钟间隔",
        },
    },
    "DateTime": {
        "controlType": 16, "name": "日期时间", "category": "date",
        "doc": "日期+时间。适合日历视图。",
        "advancedSetting": {
            "sorttype": "zh",
            "showtype": "1",
            "showformat": "0",
        },
    },
    "Time": {
        "controlType": 46, "name": "时间", "category": "date",
        "doc": "仅时间字段（时:分），不含日期。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },

    # ── 联系方式 ──
    "Phone": {
        "controlType": 3, "name": "电话", "category": "contact",
        "doc": "手机号码字段，自动验证格式，支持拨号。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "datamask": "数据掩码: 0=禁用, 1=启用",
            "commcountries": "常用国家列表 JSON 数组",
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
        "doc": "邮箱地址字段，自动验证格式。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "Link": {
        "controlType": 7, "name": "链接", "category": "contact",
        "doc": "URL 链接字段，支持点击跳转。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },

    # ── 人员组织 ──
    "Collaborator": {
        "controlType": 26, "name": "成员", "category": "people",
        "doc": "成员字段（负责人/参与者），required 强制 false。enumDefault: 0=单选, 1=多选。",
        "force_not_required": True,
        "advancedSetting": {
            "sorttype": "zh",
            "usertype": "1",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "usertype": "成员类型",
            "dynamicsrc": "动态来源",
            "defaultfunc": "默认函数",
            "defsource": "默认值来源",
            "defaulttype": "默认值类型",
            "chooserange": "选择范围",
        },
    },
    "Department": {
        "controlType": 27, "name": "部门", "category": "people",
        "doc": "部门选择字段。enumDefault: 0=单选, 1=多选。",
        "advancedSetting": {
            "sorttype": "zh",
        },
    },
    "OrgRole": {
        "controlType": 48, "name": "组织角色", "category": "people",
        "doc": "组织角色选择字段。",
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
            "showtype": "2",
            "allowlink": "1",
            "searchrange": "0",
            "scanlink": "1",
            "scancontrol": "1",
            "allowdelete": "1",
            "allowexport": "1",
            "allowedit": "1",
            "showquick": "1",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "showtype": "显示模式: 1=弹层, 3=下拉",
            "allowlink": "允许跳转: 0=否, 1=是",
            "covertype": "封面填充: 0=适应, 1=原比例",
            "scanlink": "扫码关联: 0=否, 1=是",
            "scancontrol": "扫码控制: 0=否, 1=是",
            "showtitleid": "标题字段 controlId",
            "choosecoverid": "选择模式封面字段 controlId",
            "choosecovertype": "选择模式封面填充",
            "allowdrag": "允许拖拽排序: 0=否, 1=是",
            "openfastfilters": "快速筛选: 0=否, 1=是",
            "rcsorttype": "排序方式: 1=按时间, 2=自定义, 3=按视图",
            "sorts": "自定义排序 JSON 数组",
            "chooseshowids": "选择模式显示字段 JSON",
            "choosecontrolssorts": "选择模式字段排序 JSON",
            "controlssorts": "正常显示字段排序 JSON",
            "searchrange": "搜索范围: 0=全部",
            "allowdelete": "允许删除: 0=否, 1=是",
            "allowexport": "允许导出: 0=否, 1=是",
            "allowedit": "允许编辑: 0=否, 1=是",
            "showquick": "快速查看: 0=否, 1=是",
            "defsource": "动态默认值 JSON",
            "hidetitle": "隐藏标题: 0=否, 1=是",
            "titlesize": "标题字号",
            "titlestyle": "标题样式",
            "titlecolor": "标题颜色",
            "ddset": "下拉设置标志",
        },
        "api_extra": {
            "dataSource": "<target_worksheetId>",
            "enumDefault": 2,
        },
    },
    "OtherTableField": {
        "controlType": 30, "name": "他表字段", "category": "relation",
        "doc": "引用关联表字段值，需先有关联字段。dataSource=关联字段 controlId。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "api_extra": {
            "dataSource": "<relation_controlId>",
        },
    },
    "SubTable": {
        "controlType": 34, "name": "子表", "category": "relation",
        "doc": "子表（嵌入式关联表），在主记录中展示子记录列表。",
        "advancedSetting": {
            "sorttype": "zh",
            "allowadd": "1",
            "allowcancel": "1",
            "allowedit": "1",
            "allowsingle": "1",
            "allowlink": "1",
            "allowexport": "1",
            "enablelimit": "1",
            "min": "0",
            "max": "200",
            "blankrow": "1",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "allowadd": "允许新增: 0=否, 1=是",
            "allowcancel": "允许取消关联: 0=否, 1=是",
            "allowedit": "允许编辑: 0=否, 1=是",
            "allowsingle": "允许单条操作: 0=否, 1=是",
            "allowlink": "允许跳转: 0=否, 1=是",
            "allowexport": "允许导出: 0=否, 1=是",
            "enablelimit": "启用数量限制: 0=否, 1=是",
            "min": "最少子记录数",
            "max": "最多子记录数",
            "blankrow": "显示空白行: 0=否, 1=是",
            "sorts": "排序 JSON [{controlId, isAsc}]",
            "uniquecontrols": "去重字段 JSON [controlId]",
            "controlssorts": "字段显示排序 JSON [controlId]",
            "showtype": "显示类型",
            "rowheight": "行高",
            "rownum": "每页行数",
            "allowcopy": "允许复制",
            "allowimport": "允许导入",
            "allowbatch": "允许批量",
            "searchrange": "搜索范围",
        },
    },
    "Cascade": {
        "controlType": 35, "name": "级联选择", "category": "relation",
        "doc": "级联多级选择（如省/市/区）。enumDefault=1。",
        "api_extra": {"enumDefault": 1},
        "advancedSetting": {
            "sorttype": "zh",
            "allpath": "0",
            "anylevel": "0",
            "allowlink": "1",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "allpath": "显示完整路径: 0=否, 1=是",
            "anylevel": "允许选任意级别: 0=否(必须到叶节点), 1=是",
            "allowlink": "允许跳转: 0=否, 1=是",
            "showtype": "菜单样式: 3=级联菜单(默认), 4=树形选择",
        },
    },
    "Rollup": {
        "controlType": 37, "name": "汇总", "category": "relation",
        "doc": "汇总关联表数据（求和/计数/平均/最大/最小），需先有关联字段。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "api_extra": {
            "dataSource": "<relation_controlId>",
        },
    },

    # ── 文件 ──
    "Attachment": {
        "controlType": 14, "name": "附件", "category": "file",
        "doc": "文件上传，支持图片、文档、视频等多种格式。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "showtype": "展示格式: 1=缩略图, 2=卡片, 3=列表, 4=海报",
            "covertype": "封面填充: 0=适应容器, 1=保持比例",
            "filetype": "文件类型限制 JSON {type, values}",
            "showfilename": "显示文件名: 0=否, 1=是",
            "watermark": "水印内容",
            "showwatermark": "显示水印: 0=否, 1=是",
            "watermarkinfo": "水印配置",
            "watermarkstyle": "水印样式",
        },
    },
    "Signature": {
        "controlType": 42, "name": "签名", "category": "file",
        "doc": "手写签名字段。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "uselast": "使用上次签名",
            "allowappupload": "允许 App 上传",
        },
    },

    # ── 地理位置 ──
    "Area": {
        "controlType": 24, "name": "地区", "category": "location",
        "doc": "地区选择（省/市/区级联）。enumDefault: 0=指定区域, 1=国际。enumDefault2: 1=省, 2=市, 3=区。",
        "api_extra": {"enumDefault2": 3},
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "chooserange": "国家/地区代码（如 CN）",
            "commcountries": "常用国家列表 JSON 数组",
            "defsource": "默认值来源（国际模式下清空）",
        },
    },
    "Location": {
        "controlType": 40, "name": "定位", "category": "location",
        "doc": "GPS 定位字段，支持地图标记或记录坐标。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "showxy": "显示坐标: 0=否, 1=是（GPS 模式自动设为1）",
            "allowcustom": "允许自定义位置: 0=否, 1=是（GPS 模式禁用）",
            "distance": "范围限制(米): 100/300/500/1000/2000",
        },
    },

    # ── 高级/特殊 ──
    "QRCode": {
        "controlType": 43, "name": "二维码", "category": "advanced",
        "doc": "条形码/二维码。enumDefault: 1=条形码, 2=二维码。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "width": "最大宽度(px)，默认160",
            "faultrate": "容错率(仅二维码): 7%/15%/25%/30%",
        },
    },
    "Embed": {
        "controlType": 45, "name": "嵌入", "category": "advanced",
        "doc": "嵌入外部内容。enumDefault: 1=链接, 2=图表, 3=视图。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "height": "最大高度(px): 100-1000",
            "rownum": "每页行数(max 50，grid 模式)",
            "filters": "过滤条件 JSON（非链接模式）",
            "allowlink": "允许新窗口打开: 0=否, 1=是（链接模式）",
        },
    },

    # ── 布局（不存储数据）──
    "Section": {
        "controlType": 22, "name": "分段", "category": "layout",
        "doc": "表单分段标题。enumDefault2: 0=不折叠, 1=展开, 2=收起。",
        "advancedSetting": {
            "sorttype": "zh",
        },
        "advancedSetting_all_keys": {
            "sorttype": "排序方式",
            "color": "文字颜色 hex，默认 #151515",
            "theme": "线条颜色 hex，默认 #1677ff",
            "icon": "图标配置 JSON",
        },
    },
    "Remark": {
        "controlType": 49, "name": "备注说明", "category": "layout",
        "doc": "表单中的静态文本说明（不存储数据），用于填写提示。",
        "advancedSetting": {
            "sorttype": "zh",
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
