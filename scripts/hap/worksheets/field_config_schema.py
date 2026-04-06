"""
明道云字段类型配置参数 Schema — 完整版（38 种字段类型）

来源：API 实测（GetWorksheetControls） + 代码分析
录制时间：2026-04-03
工作表：全字段演示表（worksheetId=69cf74eef9434db36c6e0816）

## 字段接口说明

### 单字段创建（本项目当前使用）
POST https://www.mingdao.com/api/Worksheet/AddWorksheetControl

### 单字段更新
POST https://www.mingdao.com/api/Worksheet/EditWorksheetControls

### 字段列表读取
POST https://www.mingdao.com/api/Worksheet/GetWorksheetControls
Response: data.data.version（乐观锁版本号）+ data.data.controls（完整字段数组）

### 批量字段管理（乐观锁接口，来源：HAP Ultra 2026-03-26 录制）
POST https://www.mingdao.com/api/Worksheet/SaveWorksheetControls
- 一个接口覆盖新增/修改/删除三种操作（声明式：传入全量字段数组）
- 新增：在 controls 末尾追加 controlId="" 的新字段对象
- 修改：修改 controls 中对应字段对象的属性（controlId 不变）
- 删除：从 controls 中移除该字段对象（不传即删除）
- ⚠️ 乐观锁：version 必须与服务端当前版本一致，否则失败
  先调用 GetWorksheetControls 获取最新 version，再提交
- Request Body: {"version": <int>, "sourceId": "<worksheetId>", "controls": [...]}
- Response: data.data.version（递增后的新版本号）+ data.data.controls（保存后完整字段列表，含新字段的 controlId）

## 通用参数（所有字段类型都有）

- controlName: str   字段名称（必填）
- type: int          字段类型 ID（必填）
- required: 0|1      是否必填，0=否，1=是
- attribute: 0|1     0=普通字段，1=标题字段（每表仅一个）
- row: int           行号（布局用，0 起始，自动分配）
- col: int           列号（布局用，0=第1列, 1=第2列 等，与 size 联动）
- size: int          字段宽度（12=全宽, 6=半宽, 4=1/3宽, 3=1/4宽）
                     ⚠️ SaveWorksheetControls 接口用 12/6/4/3；
                        AddWorksheetControl 接口某些版本用 100/50，需确认
- hint: str          字段说明/提示文字
- desc: str          字段描述
- alias: str         字段别名（用于 API 引用）
- unique: bool       是否唯一值约束
- encryId: str       加密设置 ID（空=不加密）
- showControls: []   关联显示字段列表
- advancedSetting: dict  高级设置

## 字段对象完整结构（来源：HAP Ultra SaveWorksheetControls 实测）

{
    "controlId":         "24位hex或空字符串（新增时为空）",
    "controlName":       "字段名",
    "type":              2,
    "attribute":         0,
    "row":               0,
    "col":               0,
    "hint":              "",
    "default":           "",
    "dot":               0,        # 小数位数（数值/金额字段）
    "unit":              "",       # 单位（数值/金额字段）
    "enumDefault":       0,        # 选项默认值
    "enumDefault2":      0,        # 第二默认值（如地区字段）
    "defaultMen":        [],       # 默认成员列表
    "dataSource":        "",       # 关联数据源工作表 ID
    "sourceControlId":   "",       # 来源字段 ID（他表字段/汇总字段）
    "sourceControlType": 0,        # 来源字段类型
    "showControls":      [],
    "noticeItem":        0,
    "userPermission":    0,
    "options":           [],       # 单选/多选选项列表
    "required":          False,
    "half":              False,
    "relationControls":  [],
    "viewId":            "",
    "unique":            False,
    "coverCid":          "",
    "strDefault":        "",       # 自动编号格式 / 富文本默认值
    "desc":              "",
    "fieldPermission":   "",
    "advancedSetting":   {},
    "alias":             "",
    "size":              0,        # 见 size 说明
    "editAttrs":         [],
    "encryId":           "",
    "sectionId":         "",
    "remark":            "",
    "disabled":          False,
    "checked":           False,
}

## 注意

- advancedSetting.sorttype 控制排序方式："zh"=中文，"en"=英文
- 创建字段时 advancedSetting 可省略大部分键（系统有默认值）
- 关联类字段（29/30/34/35/37）需要 dataSource 或 sourceControlId
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# 完整字段 Schema
# ──────────────────────────────────────────────────────────────────────────────

FIELD_SCHEMA: dict[int, dict] = {

    # ── 文本类 ─────────────────────────────────────────────────────────────────

    2: {
        "name": "文本",
        "type": 2,
        "category": "text",
        "create_params": {
            "type": 2,
            "controlName": "字段名",
            "required": 0,
            "attribute": 0,      # 1 = 标题字段（每表只能一个）
            "advancedSetting": {
                "sorttype": "zh",       # 排序方式：zh=中文, en=英文
                "analysislink": "0",    # 是否解析为链接：0=否, 1=是
                # 以下为表单验证选项（可选）：
                # "regex": "",          # 正则表达式验证
                # "regexmsg": "",       # 验证失败提示
                # "minlen": "0",        # 最小字符数
                # "maxlen": "200",      # 最大字符数
                # "defaulttype": "0",   # 默认值类型：0=无, 1=自定义, 2=当前用户
                # "defsource": "",      # 默认值来源（当 defaulttype=1 时）
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "最基础的单行文本字段，用于名称、标题、描述等。attribute=1 表示标题字段（每表只能有一个），第一个文本字段应设为标题字段。",
        "constraints": {
            "one_per_table_as_title": True,
        },
    },

    3: {
        "name": "手机号",
        "type": 3,
        "category": "contact",
        "create_params": {
            "type": 3,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "手机号码字段，自动验证手机号格式，支持拨号。适用于联系人、客户管理场景。",
    },

    4: {
        "name": "座机",
        "type": 4,
        "category": "contact",
        "create_params": {
            "type": 4,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "座机号码字段，支持带区号的固定电话。",
    },

    5: {
        "name": "邮箱",
        "type": 5,
        "category": "contact",
        "create_params": {
            "type": 5,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "邮箱地址字段，自动验证邮箱格式，支持发送邮件。适用于联系人、用户管理场景。",
    },

    6: {
        "name": "数值",
        "type": 6,
        "category": "number",
        "create_params": {
            "type": 6,
            "controlName": "字段名",
            "required": 0,
            "dot": 2,            # 小数位数：0=整数, 1, 2, 3, 4（默认2）
            "advancedSetting": {
                "sorttype": "zh",
                "thousandth": "0",  # 是否显示千分位：0=否, 1=是
                "numshow": "0",     # 数值显示方式：0=默认, 1=进度条
                "showtype": "0",    # 显示类型：0=数字
                # "unit": "",       # 单位（可选，如 "个", "次"）
                # "unitpos": "0",   # 单位位置：0=后, 1=前
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "数值字段，用于数量、金额、评分等数字型数据。dot 控制小数位数（0=整数）。可设千分位显示和进度条显示。",
    },

    7: {
        "name": "链接",
        "type": 7,
        "category": "contact",
        "create_params": {
            "type": 7,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "defaulttype": "0",  # 默认值类型
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "URL 链接字段，支持点击跳转。适用于网址、文档链接等。",
    },

    8: {
        "name": "金额",
        "type": 8,
        "category": "number",
        "create_params": {
            "type": 8,
            "controlName": "字段名",
            "required": 0,
            "dot": 2,            # 小数位数（通常为2）
            "unit": "¥",         # 货币符号：¥, $, €, £ 等
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "货币金额字段，支持货币符号和千分位显示。unit 设置货币单位（¥/$等），dot 控制小数位。",
    },

    9: {
        "name": "单选",
        "type": 9,
        "category": "select",
        "create_params": {
            "type": 9,
            "controlName": "字段名",
            "required": 0,
            "options": [
                # 选项格式：{"key": "uuid", "value": "选项名", "index": 0, "color": "#2196F3", "score": 0}
                # 创建时 key 可省略（系统自动生成），建议提供 value 和 index
                {"value": "选项1", "index": 0},
                {"value": "选项2", "index": 1},
                {"value": "选项3", "index": 2},
            ],
            "advancedSetting": {
                "sorttype": "zh",
                "showtype": "0",    # 显示方式：0=下拉（收纳，推荐）, 1=平铺, 2=颜色块
            },
        },
        "required_for_create": ["controlName", "type", "options"],
        "ai_notes": "单选字段（平铺展示），用于状态、类型、优先级等只需选一个的场景。需要提供 options 选项列表（3-8项）。适合看板视图分组。",
        "constraints": {
            "min_options": 2,
            "max_options": 10,
            "option_color_palette": ["#2196F3", "#4CAF50", "#F44336", "#FF9800", "#9C27B0", "#00BCD4", "#795548", "#607D8B"],
        },
    },

    10: {
        "name": "多选",
        "type": 10,
        "category": "select",
        "create_params": {
            "type": 10,
            "controlName": "字段名",
            "required": 0,
            "options": [
                {"value": "选项1", "index": 0},
                {"value": "选项2", "index": 1},
                {"value": "选项3", "index": 2},
            ],
            "advancedSetting": {
                "sorttype": "zh",
                "checktype": "1",   # 显示方式：1=下拉（收纳，推荐）, 0=平铺
            },
        },
        "required_for_create": ["controlName", "type", "options"],
        "ai_notes": "多选字段（标签样式），用于标签、技能、分类等可多选的场景。需要提供 options 选项列表（3-8项）。",
        "constraints": {
            "min_options": 2,
            "max_options": 10,
        },
    },

    11: {
        "name": "下拉",
        "type": 11,
        "category": "select",
        "create_params": {
            "type": 11,
            "controlName": "字段名",
            "required": 0,
            "options": [
                {"value": "选项1", "index": 0},
                {"value": "选项2", "index": 1},
                {"value": "选项3", "index": 2},
            ],
            "advancedSetting": {
                "sorttype": "zh",
                "showtype": "0",    # 0=下拉单选（默认）
            },
        },
        "required_for_create": ["controlName", "type", "options"],
        "ai_notes": "下拉选择字段（下拉展示），用于选项较多的单选场景。比 SingleSelect(9) 更紧凑。需要提供 options 选项列表。",
        "constraints": {
            "min_options": 2,
            "max_options": 10,
        },
    },

    14: {
        "name": "附件",
        "type": 14,
        "category": "file",
        "create_params": {
            "type": 14,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "filetypes": "",    # 限制文件类型（如 "image/*"）
                # "filecount": "0",   # 最大文件数（0=不限）
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "附件字段，支持上传图片、文档、视频等文件。用于合同文件、产品图片、凭证上传等场景。",
    },

    15: {
        "name": "日期",
        "type": 15,
        "category": "date",
        "create_params": {
            "type": 15,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                "showtype": "3",      # 日期格式：3=YYYY-MM-DD（推荐）, 5=YYYY/MM/DD, 6=YYYY年MM月DD日
                "showformat": "0",    # 时间显示：0=不显示时间
                # "defaulttype": "0", # 默认值：0=无, 1=录入时间, 2=自定义
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "日期字段（不含时间），用于开始日期、截止日期、生日等。适合甘特图和日历视图。showtype 控制格式（3=YYYY-MM-DD）。",
        "advancedSetting_values": {
            "showtype": {
                "3": "YYYY-MM-DD（推荐）",
                "5": "YYYY/MM/DD",
                "6": "YYYY年MM月DD日",
            },
        },
    },

    16: {
        "name": "日期时间",
        "type": 16,
        "category": "date",
        "create_params": {
            "type": 16,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                "showtype": "1",      # 日期格式：1=YYYY-MM-DD HH:mm, 3=YYYY-MM-DD
                "showformat": "0",    # 0=显示时间（默认）
                # "defaulttype": "0", # 默认值：0=无, 1=录入时间, 2=自定义
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "日期时间字段（含时间），用于会议时间、操作时间等需要精确到时分的场景。适合日历视图。",
    },

    22: {
        "name": "分段",
        "type": 22,
        "category": "layout",
        "create_params": {
            "type": 22,
            "controlName": "分段标题",
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "表单分段标题，仅用于布局分组，不存储任何数据。用于将相关字段分组显示，提升表单可读性。不要给 AI 规划时使用。",
        "constraints": {
            "no_required": True,
            "layout_only": True,
        },
    },

    24: {
        "name": "地区",
        "type": 24,
        "category": "location",
        "create_params": {
            "type": 24,
            "controlName": "字段名",
            "required": 0,
            "enumDefault2": 3,     # 精度级别：1=省, 2=市, 3=区（默认）
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "地区选择字段（省/市/区级联），用于省市区地址选择。enumDefault2 控制精度（1=省, 2=省市, 3=省市区）。",
        "advancedSetting_values": {
            "enumDefault2": {
                "1": "仅省级",
                "2": "省+市",
                "3": "省+市+区（默认）",
            },
        },
    },

    25: {
        "name": "大写金额",
        "type": 25,
        "category": "number",
        "create_params": {
            "type": 25,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "dataSource": "controlId",  # 引用来源字段 ID
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "大写金额字段，将数字金额转换为中文大写（如：壹万元整）。通常关联一个金额字段自动转换。",
    },

    26: {
        "name": "成员",
        "type": 26,
        "category": "people",
        "create_params": {
            "type": 26,
            "controlName": "字段名",
            "required": 0,          # 成员字段禁止设为必填
            "advancedSetting": {
                "sorttype": "zh",
                "usertype": "1",    # 选人类型：0=组织成员, 1=多人选择, 2=单人选择
                # "appointedate": "0",  # 是否允许选非成员
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "成员字段，用于负责人、参与者、审批人等。usertype=1 支持多选成员。注意：required 必须为 0（成员字段不能设必填）。",
        "constraints": {
            "force_required_false": True,
        },
        "advancedSetting_values": {
            "usertype": {
                "0": "组织成员（默认范围）",
                "1": "多人选择（推荐）",
                "2": "单人选择",
            },
        },
    },

    27: {
        "name": "部门",
        "type": 27,
        "category": "people",
        "create_params": {
            "type": 27,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "multiple": "1",   # 是否多选：0=单选, 1=多选
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "部门选择字段，用于所属部门、归属团队等。从组织架构中选取部门。",
    },

    28: {
        "name": "等级",
        "type": 28,
        "category": "select",
        "create_params": {
            "type": 28,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "max": "5",      # 最大等级数（默认5）
                # "style": "0",    # 样式：0=星形, 1=心形, 2=旗帜
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "等级评分字段（星级），用于客户评级、产品评分、重要程度等场景。显示为星形图标（1-5星）。",
    },

    29: {
        "name": "关联记录",
        "type": 29,
        "category": "relation",
        "create_params": {
            "type": 29,
            "controlName": "字段名",
            "required": 0,
            "dataSource": "",       # 目标工作表 ID（必填）
            "enumDefault": 2,       # 关联显示模式：2=卡片式（推荐）
            "advancedSetting": {
                "sorttype": "zh",
                "showtype": "2",      # 显示类型：2=卡片（推荐）
                "allowlink": "1",     # 是否允许点击跳转
                "searchrange": "0",   # 搜索范围：0=全部
                "scanlink": "1",      # 允许扫码关联
                "scancontrol": "1",   # 允许扫码控制
                "allowdelete": "1",   # 允许删除关联
                "allowexport": "1",   # 允许导出
                "allowedit": "1",     # 允许编辑关联记录
                "showquick": "1",     # 显示快速查看
            },
        },
        "required_for_create": ["controlName", "type", "dataSource"],
        "ai_notes": "关联记录字段，用于建立跨表数据关系。dataSource 填目标工作表 ID（第二阶段创建）。1-N 关系通常放在多端表中，指向一端表。",
        "constraints": {
            "requires_dataSource": True,
            "phase": "2",  # 需要在其他表创建后才能创建
        },
    },

    30: {
        "name": "他表字段",
        "type": 30,
        "category": "relation",
        "create_params": {
            "type": 30,
            "controlName": "字段名",
            "required": 0,
            "dataSource": "",        # 关联记录字段的 controlId
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type", "dataSource"],
        "ai_notes": "他表字段（关联查询），引用关联表中某个字段的值，自动显示关联记录的某个字段。dataSource 填关联字段的 controlId。",
        "constraints": {
            "requires_relation_field": True,
            "phase": "3",
        },
    },

    31: {
        "name": "公式",
        "type": 31,
        "category": "formula",
        "create_params": {
            "type": 31,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                "nullzero": "0",    # 空值处理：0=显示空, 1=显示0
                # "formula": "",    # 公式内容（如 "$数量$ * $单价$"）
                # "dot": "2",       # 小数位数
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "数值计算公式字段，支持四则运算和字段引用。公式在 advancedSetting.formula 中定义，用 $字段名$ 引用字段。",
    },

    32: {
        "name": "文本组合",
        "type": 32,
        "category": "text",
        "create_params": {
            "type": 32,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                "analysislink": "1",  # 是否解析为链接
                # "formula": "",      # 文本拼接模式（引用其他字段）
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "文本组合（文本公式）字段，将多个字段拼接为文本。适合自动生成编号、标识符等。",
    },

    33: {
        "name": "自动编号",
        "type": 33,
        "category": "text",
        "create_params": {
            "type": 33,
            "controlName": "字段名",
            "required": 0,
            "strDefault": "increase",  # 编号模式：increase=递增
            "advancedSetting": {
                "sorttype": "zh",
                # "prefix": "NO-",    # 编号前缀
                # "digits": "4",      # 位数（如4=0001起）
                # "start": "1",       # 起始值
                # "step": "1",        # 步长
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "自动编号字段，记录创建时自动分配递增编号。可配置前缀（如 NO-、ORD-）。用于工单号、合同号等场景。",
    },

    34: {
        "name": "子表",
        "type": 34,
        "category": "relation",
        "create_params": {
            "type": 34,
            "controlName": "字段名",
            "required": 0,
            "sourceControlId": "",   # 父表字段 ID（系统关联）
            "advancedSetting": {
                "sorttype": "zh",
                "allowadd": "1",      # 允许新增子记录
                "allowcancel": "1",   # 允许取消关联
                "allowedit": "1",     # 允许编辑子记录
                "allowsingle": "1",   # 允许单条操作
                "allowlink": "1",     # 允许点击跳转
                "allowexport": "1",   # 允许导出
                "enablelimit": "1",   # 启用数量限制
                "min": "0",           # 最少子记录数
                "max": "200",         # 最多子记录数
                "blankrow": "1",      # 显示空白行
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "子表字段，在主记录中嵌入展示关联的子记录列表。常用于订单-明细、项目-任务等主从关系。需要已存在的关联关系。",
        "constraints": {
            "requires_relation": True,
            "phase": "3",
        },
    },

    35: {
        "name": "级联选择",
        "type": 35,
        "category": "relation",
        "create_params": {
            "type": 35,
            "controlName": "字段名",
            "required": 0,
            "enumDefault": 1,         # 1=从根节点开始
            "sourceControlId": "",    # 数据源工作表的 controlId
            "advancedSetting": {
                "sorttype": "zh",
                "allpath": "0",       # 是否显示完整路径：0=否, 1=是
                "anylevel": "0",      # 是否允许选任意级别：0=否, 1=是
                "allowlink": "1",     # 允许跳转
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "级联选择字段，用于多级联动选择（如省/市/区，或产品分类/子分类）。需要配置树形数据源。",
        "constraints": {
            "requires_tree_datasource": True,
        },
    },

    36: {
        "name": "检查框",
        "type": 36,
        "category": "select",
        "create_params": {
            "type": 36,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                "showtype": "0",    # 显示方式：0=方框, 1=开关
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "检查框字段（布尔值），用于是/否标记。如\"是否完成\"、\"是否已审核\"、\"是否优先处理\"等。showtype=1 显示为开关样式。",
        "advancedSetting_values": {
            "showtype": {
                "0": "方形复选框（默认）",
                "1": "开关/拨码样式",
            },
        },
    },

    37: {
        "name": "汇总",
        "type": 37,
        "category": "formula",
        "create_params": {
            "type": 37,
            "controlName": "字段名",
            "required": 0,
            "dataSource": "",       # 关联字段的 controlId
            "advancedSetting": {
                "sorttype": "zh",
                # "aggregateType": "SUM",  # 聚合方式：SUM/COUNT/AVG/MAX/MIN
                # "sourceControlId": "",   # 汇总关联表中的哪个字段
            },
        },
        "required_for_create": ["controlName", "type", "dataSource"],
        "ai_notes": "汇总字段，从关联记录中聚合计算（求和/计数/平均/最大/最小）。需要先有关联字段。dataSource 填关联字段的 controlId。",
        "constraints": {
            "requires_relation_field": True,
            "phase": "3",
        },
    },

    38: {
        "name": "公式（日期）",
        "type": 38,
        "category": "formula",
        "create_params": {
            "type": 38,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "formula": "",         # 日期公式
                # "showtype": "3",       # 结果格式
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "日期计算公式字段，用于计算两个日期之间的差值（天数/工作日）或基于日期的推算。如\"到期天数\"、\"在职时长\"等。",
    },

    40: {
        "name": "定位",
        "type": 40,
        "category": "location",
        "create_params": {
            "type": 40,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "maptype": "0",     # 地图类型：0=百度, 1=高德
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "GPS 定位字段，支持在地图上标记位置或记录当前坐标。适合外勤打卡、门店位置等场景。",
    },

    41: {
        "name": "富文本",
        "type": 41,
        "category": "text",
        "create_params": {
            "type": 41,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "富文本编辑器字段，支持格式化文本、图片、表格等。用于详细描述、备注、正文等需要富格式的场景。",
    },

    42: {
        "name": "签名",
        "type": 42,
        "category": "file",
        "create_params": {
            "type": 42,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "手写签名字段，支持触屏手写签名或鼠标签名。用于合同签署、确认签收等需要手写签名的场景。",
    },

    43: {
        "name": "二维码",
        "type": 43,
        "category": "special",
        "create_params": {
            "type": 43,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "qrtype": "0",        # 二维码类型：0=记录链接, 1=自定义字段值
                # "sourceControlId": "", # 当 qrtype=1 时，引用哪个字段的值
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "二维码字段，自动根据记录 ID 或指定字段值生成二维码图片。扫码可跳转到对应记录。适合资产管理、商品标签等。",
    },

    45: {
        "name": "嵌入",
        "type": 45,
        "category": "special",
        "create_params": {
            "type": 45,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "url": "",          # 嵌入的 URL（可引用字段值）
                # "height": "400",    # 嵌入区域高度
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "嵌入外部网页字段，支持在记录详情中内嵌外部 URL。可动态引用本条记录的字段值拼接 URL。",
    },

    46: {
        "name": "时间",
        "type": 46,
        "category": "date",
        "create_params": {
            "type": 46,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "showtype": "0",    # 格式：0=HH:mm, 1=HH:mm:ss
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "仅时间字段（时:分），不含日期。用于每天的固定时刻，如上班时间、会议时间等。",
    },

    47: {
        "name": "评分",
        "type": 47,
        "category": "select",
        "create_params": {
            "type": 47,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
                # "max": "5",         # 最高分（默认5）
                # "style": "0",       # 样式：0=星形, 1=心形
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "评分字段（数值评分），与等级字段(28)类似但以数字分值展示。用于满意度评分、质量评级等。",
    },

    48: {
        "name": "组织角色",
        "type": 48,
        "category": "people",
        "create_params": {
            "type": 48,
            "controlName": "字段名",
            "required": 0,
            "advancedSetting": {
                "sorttype": "zh",
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "组织角色字段，从系统预定义的组织角色中选择（如管理员、员工等）。适合权限控制和岗位分配场景。",
    },

    49: {
        "name": "备注说明",
        "type": 49,
        "category": "layout",
        "create_params": {
            "type": 49,
            "controlName": "说明文字",
            "advancedSetting": {
                "sorttype": "zh",
                # "remark": "",   # 说明文本内容（富文本）
            },
        },
        "required_for_create": ["controlName", "type"],
        "ai_notes": "表单中的静态说明文本，仅用于布局提示，不存储数据。用于填写说明、注意事项提示等。不要在 AI 规划字段时使用。",
        "constraints": {
            "no_required": True,
            "layout_only": True,
        },
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# 便捷映射
# ──────────────────────────────────────────────────────────────────────────────

# type ID → schema
def get_schema(type_id: int) -> dict:
    """根据字段类型 ID 获取 schema。"""
    return FIELD_SCHEMA.get(type_id, {})


# 所有字段类型 ID 列表
ALL_FIELD_TYPES: list[int] = sorted(FIELD_SCHEMA.keys())

# type ID → 字段名称
TYPE_NAMES: dict[int, str] = {t: s["name"] for t, s in FIELD_SCHEMA.items()}

# type ID → 类别
TYPE_CATEGORIES: dict[int, str] = {t: s["category"] for t, s in FIELD_SCHEMA.items()}

# 按类别分组的 type 列表
TYPES_BY_CATEGORY: dict[str, list[int]] = {}
for _t, _s in FIELD_SCHEMA.items():
    TYPES_BY_CATEGORY.setdefault(_s["category"], []).append(_t)

# 需要 options 的字段类型
OPTION_REQUIRED_TYPES: set[int] = {t for t, s in FIELD_SCHEMA.items() if "options" in s.get("create_params", {})}

# 需要 dataSource 的字段类型
DATASOURCE_REQUIRED_TYPES: set[int] = {
    t for t, s in FIELD_SCHEMA.items()
    if s.get("constraints", {}).get("requires_dataSource")
    or s.get("constraints", {}).get("requires_relation_field")
}

# 需要第二/三阶段才能创建的字段类型
PHASE2_TYPES: set[int] = {t for t, s in FIELD_SCHEMA.items() if s.get("constraints", {}).get("phase") == "2"}
PHASE3_TYPES: set[int] = {t for t, s in FIELD_SCHEMA.items() if s.get("constraints", {}).get("phase") == "3"}

# 不能设为必填的字段类型
FORCE_NOT_REQUIRED_TYPES: set[int] = {t for t, s in FIELD_SCHEMA.items() if s.get("constraints", {}).get("force_required_false")}

# 仅布局用途（不存储数据）的字段类型
LAYOUT_ONLY_TYPES: set[int] = {t for t, s in FIELD_SCHEMA.items() if s.get("constraints", {}).get("layout_only")}

# 可被 AI 规划使用的字段类型（排除布局类型）
PLANNABLE_TYPES: set[int] = {t for t in ALL_FIELD_TYPES if t not in LAYOUT_ONLY_TYPES}


def build_ai_field_type_reference() -> str:
    """生成供 AI prompt 使用的字段类型参考说明。"""
    lines = ["明道云字段类型参考（AI 规划时使用）：", ""]
    for category in ["text", "number", "date", "select", "people", "relation", "file", "formula", "location", "contact", "special"]:
        types_in_cat = TYPES_BY_CATEGORY.get(category, [])
        if not types_in_cat:
            continue
        cat_label = {
            "text": "文本类", "number": "数值类", "date": "日期时间类",
            "select": "选择类", "people": "人员组织类", "relation": "关联类",
            "file": "文件类", "formula": "公式汇总类", "location": "地理位置类",
            "contact": "联系方式类", "special": "特殊功能类",
        }.get(category, category)
        lines.append(f"【{cat_label}】")
        for t in sorted(types_in_cat):
            schema = FIELD_SCHEMA[t]
            if schema.get("constraints", {}).get("layout_only"):
                continue
            notes = schema.get("ai_notes", "")[:80]
            lines.append(f"  type={t:2d} {schema['name']:8s} — {notes}")
        lines.append("")
    return "\n".join(lines)
