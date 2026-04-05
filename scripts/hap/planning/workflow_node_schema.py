"""
明道云工作流节点配置参数 Schema — 完整版

来源：
  - 代码分析（workflow/nodes/*.py、workflow/scripts/*.py）
  - API 实测（通过 flowNode/get 读取 127 个真实工作流节点数据）
  - HAR 分析（action/*.har 抓包记录）

验证状态说明：
  [已验证] — 实测可创建 + saveNode 成功 + publish 成功
  [创建成功] — 可创建 + saveNode 成功，publish 有 warn 但不影响运行
  [待验证] — 根据代码/HAR 推断参数，未实测完整流程

## 关键 API 端点

| 操作               | 方法 | URL                                                       |
|-------------------|------|------------------------------------------------------------|
| 创建工作流进程      | POST | https://api.mingdao.com/workflow/process/add              |
| 注册到应用工作流列表 | POST | https://www.mingdao.com/api/AppManagement/AddWorkflow     |
| 获取工作流发布信息  | GET  | https://api.mingdao.com/workflow/process/getProcessPublish?processId={id} |
| 获取所有节点       | GET  | https://api.mingdao.com/workflow/flowNode/get?processId={id} |
| 获取工作流列表     | GET  | https://api.mingdao.com/workflow/v1/process/listAll?relationId={appId} |
| 添加节点骨架       | POST | https://api.mingdao.com/workflow/flowNode/add             |
| 保存节点配置       | POST | https://api.mingdao.com/workflow/flowNode/saveNode        |
| 发布工作流         | GET  | https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={id} |

## 节点连接方式

节点通过以下字段串联：
  - prveId: 上一个节点 ID（flowNode/add 请求时传入）
  - nextId: 下一个节点 ID（由系统自动设置）
  - flowIds: 分支节点的子分支 ID 列表

动态字段引用格式: "$<nodeId>-<fieldId>$"
  - 在 fieldValue 中使用，引用上游节点产出的字段值
  - 工作流规划时用 {{trigger.FIELD_ID}} 占位，执行时替换为 $startNodeId-FIELD_ID$

## 触发器类型（startEventAppType）

| startEventAppType | 含义       |
|------------------|-----------|
| 1                | 工作表事件 |
| 5                | 定时触发   |
| 6                | 日期字段触发 |
| 8                | 自定义动作（按钮触发，通过 SaveWorksheetBtn 创建）|

## 自定义动作（按钮）触发的特殊流程

自定义动作触发工作流不通过 process/add 创建，而是通过：
1. POST /api/worksheet/SaveWorksheetBtn — 创建按钮，自动生成工作流
2. GET  /workflow/process/getProcessByTriggerId?triggerId={triggerId} — 获取 processId
3. POST /workflow/flowNode/saveNode — 配置触发节点
4. 可选：GET /workflow/process/publish — 发布

"""

from __future__ import annotations

# ─── 节点类型 ID 映射 ────────────────────────────────────────────────────────────

NODE_TYPE_MAP: dict[int, str] = {
    # 系统/特殊节点（不通过 add 创建）
    0:   "触发节点（工作表事件/按钮）",
    100: "本流程参数 / 全局变量（只读）",

    # 流程控制节点（typeId）
    1:   "分支网关（branch）",
    2:   "分支条件（branch_condition）",
    3:   "填写节点（fill）",
    5:   "抄送节点（copy）",
    12:  "延时节点（delay_duration / delay_until / delay_field）",
    16:  "子流程（subprocess）",
    29:  "循环节点（loop）",
    30:  "中止流程（abort）",

    # 数据操作节点（typeId=6，通过 actionId 区分）
    6:   "工作表记录操作（新增/更新/删除/获取）",
    13:  "查询工作表（多条记录）",

    # 通知节点
    10:  "发送短信（sms）",
    11:  "发送邮件（email）",
    17:  "界面推送（push）",
    26:  "审批节点（approval）",
    27:  "发送站内通知（notify）",

    # 运算节点
    9:   "数值运算 / 工作表汇总（calc / aggregate）",

    # 开发者节点
    8:   "发送自定义 API 请求（api_request）",
    14:  "代码块（code_block）",
    21:  "JSON 解析（json_parse）",

    # AI 节点
    31:  "AI 生成文本 / 数据对象（ai_text / ai_object）",
    33:  "AI Agent（ai_agent）",
}


# ─── 完整节点 Schema ──────────────────────────────────────────────────────────────

WORKFLOW_NODE_SCHEMA: dict[str, dict] = {

    # ────────────────────────────────────────────────────────────────────────────
    # 触发节点（Trigger）— typeId=0，通过 saveNode 配置，不通过 flowNode/add 创建
    # ────────────────────────────────────────────────────────────────────────────

    "trigger_worksheet": {
        "type_id": 0,
        "name": "工作表事件触发",
        "category": "trigger",
        "status": "已验证",
        "start_event_app_type": 1,
        "description": "当工作表记录新增、更新或删除时触发",
        "create_api": {
            "url": "https://api.mingdao.com/workflow/process/add",
            "payload": {
                "companyId": "",
                "relationId": "<appId>",
                "relationType": 2,
                "startEventAppType": 1,
                "name": "<workflowName>",
                "explain": "",
            },
        },
        "save_node_payload": {
            "appId": "<worksheetId>",
            "appType": 1,
            "assignFieldIds": [],
            "processId": "<processId>",
            "nodeId": "<startNodeId>",
            "flowNodeType": 0,
            "operateCondition": [],
            "triggerId": "<triggerId>",  # 见 trigger_id_enum
            "name": "工作表事件触发",
            "controls": [],
        },
        "trigger_id_enum": {
            "1": "仅新增记录时",
            "2": "新增或更新记录时（常用默认值）",
            "3": "仅删除记录时",
            "4": "仅更新记录时",
        },
        "api_observed_fields": {
            "typeId": 0,
            "appType": 1,
            "appId": "<worksheetId>",
            "triggerId": "1",
            "appName": "<worksheetName>",
            "assignFieldNames": [],
            "assignFieldName": "",
        },
        "notes": [
            "startNodeId 通过 getProcessPublish 接口获取",
            "triggerId 控制触发时机：1=新增, 2=新增或更新, 3=删除, 4=更新",
            "assignFieldIds 可限定为特定字段变更时才触发",
        ],
    },

    "trigger_custom_action": {
        "type_id": 0,
        "name": "自定义动作（按钮触发）",
        "category": "trigger",
        "status": "已验证",
        "start_event_app_type": 8,
        "description": "工作表按钮点击时触发，工作流通过 SaveWorksheetBtn 自动创建",
        "create_flow": [
            "1. POST /api/worksheet/SaveWorksheetBtn 创建按钮（自动生成工作流）",
            "2. GET  /workflow/process/getProcessByTriggerId?triggerId={triggerId} 获取 processId",
            "3. POST /workflow/flowNode/saveNode 配置触发节点",
            "4. 可选 GET /workflow/process/publish?isPublish=true&processId={id}",
        ],
        "save_worksheet_btn_payload": {
            "worksheetId": "<worksheetId>",
            "appId": "<appId>",
            "name": "<btnName>",
            "confirmMsg": "<confirmMsg>",
            "sureName": "确认",
            "cancelName": "取消",
            "workflowType": 1,  # 1=自定义动作
        },
        "api_observed_fields": {
            "typeId": 0,
            "appType": 8,
            "appId": "<worksheetId>",
            "triggerId": "<triggerId>",
            "triggerName": "<btnName>",
        },
        "notes": [
            "自定义动作不经过 process/add，由 SaveWorksheetBtn 自动创建工作流",
            "通过 getProcessByTriggerId 根据按钮 triggerId 反查 processId",
        ],
    },

    "trigger_time": {
        "type_id": 0,
        "name": "定时触发",
        "category": "trigger",
        "status": "已验证",
        "start_event_app_type": 5,
        "description": "按设定时间周期自动触发",
        "create_api": {
            "url": "https://api.mingdao.com/workflow/process/add",
            "payload": {
                "companyId": "",
                "relationId": "<appId>",
                "relationType": 2,
                "startEventAppType": 5,
                "name": "<workflowName>",
                "explain": "",
            },
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<startNodeId>",
            "flowNodeType": 0,
            "appType": 5,
            "name": "定时触发",
            "executeTime": "<YYYY-MM-DD HH:MM>",     # 首次执行时间
            "executeEndTime": "<YYYY-MM-DD HH:MM>",   # 结束时间（可空）
            "repeatType": "1",                         # 重复类型
            "interval": 1,                             # 间隔数
            "frequency": 7,                            # 频率单位（见枚举）
            "weekDays": [],                            # 按周时的星期列表
        },
        "frequency_enum": {
            1: "分钟",
            2: "小时",
            3: "天",
            4: "周",
            5: "月",
            6: "季",
            7: "天（另一种枚举值）",
        },
        "notes": [
            "定时触发不绑定工作表，动作节点字段值不应包含 {{trigger.xxx}} 引用",
            "executeTime 格式：'YYYY-MM-DD HH:MM'",
        ],
    },

    "trigger_date_field": {
        "type_id": 0,
        "name": "按日期字段触发",
        "category": "trigger",
        "status": "已验证",
        "start_event_app_type": 6,
        "description": "在工作表中特定日期字段的时间点触发",
        "create_api": {
            "url": "https://api.mingdao.com/workflow/process/add",
            "payload": {
                "companyId": "",
                "relationId": "<appId>",
                "relationType": 2,
                "startEventAppType": 6,
                "name": "<workflowName>",
                "explain": "",
            },
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<startNodeId>",
            "flowNodeType": 0,
            "appType": 6,
            "appId": "<worksheetId>",
            "triggerId": "2",                   # 固定为 "2"
            "assignFieldId": "<dateFieldId>",   # 监听的日期字段ID，可用 ctime/mtime
            "name": "按日期字段触发",
            "executeTimeType": 0,               # 触发时机（见枚举）
            "number": 0,                        # 偏移数量
            "unit": 3,                          # 偏移单位（1=分钟, 2=小时, 3=天）
            "endTime": "08:00",                 # 当天执行时刻（executeTimeType=0时）
            "frequency": 1,                     # 重复周期（0=不重复, 1=每年, 2=每月, 3=每周）
        },
        "execute_time_type_enum": {
            0: "当天指定时刻触发（endTime 为执行时刻）",
            1: "日期前 N 单位触发（number 为偏移量）",
            2: "日期后 N 单位触发（number 为偏移量，endTime 为空）",
        },
        "notes": [
            "assignFieldId 可用系统字段 ctime（创建时间）、mtime（更新时间）",
            "只有 type=15/16 的日期字段可以作为 assignFieldId",
        ],
    },

    # ────────────────────────────────────────────────────────────────────────────
    # 数据操作节点（Action — Record）— typeId=6，flowNode/add 时 typeId=6
    # ────────────────────────────────────────────────────────────────────────────

    "add_record": {
        "type_id": 6,
        "action_id": "1",
        "app_type": 1,
        "name": "新增记录",
        "category": "record_ops",
        "status": "已验证",
        "description": "在指定工作表中新增一条记录",
        "add_payload": {
            "processId": "<processId>",
            "actionId": "1",
            "appType": 1,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
            "typeId": 6,
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 6,
            "actionId": "1",
            "name": "<nodeName>",
            "selectNodeId": "<startNodeId>",         # 引用触发节点（重要）
            "selectNodeName": "工作表事件触发",
            "appId": "<targetWorksheetId>",
            "appType": 1,
            "fields": "<fieldsArray>",               # 见 field_item_format
            "filters": [],
            "isException": True,
        },
        "field_item_format": {
            "fieldId": "<fieldId>",
            "type": "<fieldType>",                   # HAP 字段类型值（如 2=文本, 9=单选）
            "enumDefault": 0,
            "fieldValue": "<value>",                 # 固定值 或 $nodeId-fieldId$ 动态引用
            "nodeAppId": "",                         # 跨表引用时填目标工作表ID
            "sourceControlType": 0,                  # 原字段类型（跨表引用时填）
        },
        "api_observed_example": {
            "fieldId": "69ce8327c041365425641f7b",
            "type": 9,
            "enumDefault": 0,
            "fieldValue": "1169bd69-6f4c-4628-88f3-b170cd0fd108",  # 单选用完整UUID key
            "nodeAppType": 0,
            "nodeId": "",
            "nodeAppId": "",
        },
        "notes": [
            "selectNodeId 规则（抓包验证）：",
            "  - 跨表新增（target≠触发表）：selectNodeId='' 空字符串",
            "    若填触发节点ID，前端会变成'基于多条记录逐条新增'并报'节点已删除'",
            "  - 同表新增（target=触发表）：selectNodeId=startNodeId",
            "单选字段(type=9/11) fieldValue 必须是完整 UUID key，截断会被静默丢弃",
            "动态引用格式: $startNodeId-fieldId$",
            "建议包含目标表全部可操作字段",
        ],
    },

    "update_record": {
        "type_id": 6,
        "action_id": "2",
        "app_type": 1,
        "name": "更新记录",
        "category": "record_ops",
        "status": "已验证",
        "description": "更新工作表中已有记录的字段值",
        "add_payload": {
            "processId": "<processId>",
            "actionId": "2",
            "appType": 1,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
            "typeId": 6,
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 6,
            "actionId": "2",
            "name": "<nodeName>",
            "selectNodeId": "<startNodeId>",
            "selectNodeName": "工作表事件触发",
            "appId": "<targetWorksheetId>",
            "appType": 1,
            "fields": "<fieldsArray>",               # 通常只填 1~3 个需要更新的字段
            "filters": [],
            "isException": True,
        },
        "notes": [
            "通常只更新 1~3 个字段，不需要填所有字段",
            "更新触发工作表本身时，appId 填触发工作表 ID",
        ],
    },

    "delete_record": {
        "type_id": 6,
        "action_id": "3",
        "app_type": 1,
        "name": "删除记录",
        "category": "record_ops",
        "status": "待验证",
        "description": "删除工作表中的记录",
        "add_payload": {
            "processId": "<processId>",
            "actionId": "3",
            "appType": 1,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
            "typeId": 6,
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 6,
            "actionId": "3",
            "name": "<nodeName>",
            "selectNodeId": "",                      # 删除不需要 selectNodeId
            "appId": "<targetWorksheetId>",
            "appType": 1,
            "fields": [],                            # 删除不需要字段映射
            "filters": [],
            "isException": True,
        },
        "notes": [
            "fields 为空数组，删除条件通过 filters 设置",
        ],
    },

    "get_record": {
        "type_id": 6,
        "action_id": "4",
        "app_type": 1,
        "name": "获取单条数据",
        "category": "record_ops",
        "status": "已验证",
        "description": "按条件查询工作表中的单条记录",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 6,
            "actionId": "4",
            "name": "<nodeName>",
            "selectNodeId": "",
            "appId": "<targetWorksheetId>",
            "appType": 1,
            "fields": [],
            "filters": [],                           # 查询条件
            "sorts": [],                             # 排序条件
            "isException": True,
        },
    },

    "get_records": {
        "type_id": 13,
        "action_id": "400",
        "name": "查询工作表（多条）",
        "category": "record_ops",
        "status": "待验证",
        "description": "查询工作表中多条记录（与 get_record 使用不同 typeId）",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 13,                            # 注意：不是 6
            "actionId": "400",
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 13,
            "actionId": "400",
            "name": "<nodeName>",
            "appId": "<targetWorksheetId>",
            "filters": [],
            "sorts": [],
            "number": 50,                            # 最大返回记录数
        },
        "notes": [
            "typeId=13（非 6），与其他记录操作节点区别明显",
        ],
    },

    "calibrate_record": {
        "type_id": 6,
        "action_id": "6",
        "app_type": 1,
        "name": "校准单条数据",
        "category": "record_ops",
        "status": "待验证",
        "description": "校准工作表记录的字段值",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 6,
            "actionId": "6",
            "appId": "<targetWorksheetId>",
            "appType": 1,
            "fields": [],
            "errorFields": [],
        },
    },

    # ────────────────────────────────────────────────────────────────────────────
    # 通知节点
    # ────────────────────────────────────────────────────────────────────────────

    "notify": {
        "type_id": 27,
        "name": "发送站内通知",
        "category": "notify",
        "status": "已验证",
        "description": "向指定成员发送站内消息通知",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 27,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 27,
            "name": "<nodeName>",
            "selectNodeId": "",
            "isException": True,
            "accounts": "<accountsArray>",           # 收件人列表（见 account_item_format）
            "sendContent": "<notifyContent>",        # 通知内容（注意不是 content）
        },
        "account_item_format": {
            "type": 6,                               # 6=触发者（常用）
            "roleId": "uaid",                        # uaid=触发者标识
            "entityId": "<startNodeId>",             # 触发节点 ID
            "entityName": "工作表事件触发",
            "controlType": 26,
            "flowNodeType": 0,
            "appType": 1,                            # 触发节点 appType
        },
        "api_observed_example": {
            "typeId": 27,
            "name": "通知销售团队",
            "sendContent": None,                     # 实测时 sendContent 可为 null（前端配置）
            "accounts": [
                {
                    "type": 6,
                    "entityId": "<startNodeId>",
                    "entityName": "工作表事件触发",
                    "roleId": "uaid",
                    "roleName": "触发者",
                    "controlType": 26,
                    "flowNodeType": 0,
                    "appType": 1,
                }
            ],
        },
        "notes": [
            "内容字段是 sendContent，不是 content",
            "accounts 中 type=6, roleId='uaid' 表示发送给触发者",
            "实测 sendContent 可设置文本或包含变量引用的模板",
        ],
    },

    "copy": {
        "type_id": 5,
        "name": "抄送节点",
        "category": "notify",
        "status": "已验证",
        "description": "抄送消息给指定成员",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 5,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 5,
            "name": "<nodeName>",
            "isException": True,
            "accounts": "<accountsArray>",
            "sendContent": "<content>",              # 同 notify，用 sendContent
            "flowIds": [],
        },
        "api_observed_fields": {
            "typeId": 5,
            "name": "抄送给销售主管",
            "accounts": [{"type": 6, "roleId": "uaid"}],
            "prveId": "<prevNodeId>",
        },
        "notes": [
            "抄送节点也使用 sendContent（非 content），与 notify 相同",
        ],
    },

    "email": {
        "type_id": 11,
        "action_id": "202",
        "app_type": 3,
        "name": "发送邮件",
        "category": "notify",
        "status": "待验证",
        "description": "发送邮件给指定成员",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 11,
            "actionId": "202",
            "appType": 3,
            "name": "<nodeName>",
            "accounts": "<accountsArray>",
            "title": "<emailSubject>",
            "content": "<emailBody>",                # 邮件用 content（非 sendContent）
            "isException": True,
        },
        "notes": [
            "邮件节点用 content（非 sendContent），需要邮件服务配置",
        ],
    },

    "sms": {
        "type_id": 10,
        "name": "发送短信",
        "category": "notify",
        "status": "待验证",
        "description": "发送短信给指定手机号",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 10,
            "name": "<nodeName>",
            "accounts": "<accountsArray>",
            "content": "<smsContent>",               # 短信用 content
            "isException": True,
        },
        "notes": [
            "短信用 content（非 sendContent），需要短信签名配置",
        ],
    },

    "push": {
        "type_id": 17,
        "name": "界面推送",
        "category": "notify",
        "status": "待验证",
        "description": "向用户界面推送消息",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 17,
            "name": "<nodeName>",
            "accounts": "<accountsArray>",
            "sendContent": "<content>",              # 同 notify，用 sendContent
            "isException": True,
        },
    },

    # ────────────────────────────────────────────────────────────────────────────
    # 流程控制节点
    # ────────────────────────────────────────────────────────────────────────────

    "branch": {
        "type_id": 1,
        "name": "分支网关",
        "category": "flow_control",
        "status": "待验证",
        "description": "创建条件分支，支持互斥和并行分支",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 1,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 1,
            "name": "<nodeName>",
            "gatewayType": 1,                        # 1=互斥分支, 2=并行分支
            "flowIds": [],                           # 子分支节点 ID 列表（通常空）
            # 注意：不包含 isException
        },
        "api_observed_fields": {
            "typeId": 1,
            "name": "分支判断",
            "prveId": "<prevNodeId>",
            "gatewayType": 1,
        },
        "notes": [
            "分支节点 saveNode 不包含 isException 字段",
            "子分支通过 branch_condition 节点配置条件",
            "当前版本 AI 规划中禁止使用（配置复杂，易出错）",
        ],
    },

    "branch_condition": {
        "type_id": 2,
        "name": "分支条件",
        "category": "flow_control",
        "status": "待验证",
        "description": "分支网关下的条件节点",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 2,
            "name": "<conditionName>",
            "operateCondition": [],                  # 空数组=所有数据通过
            "flowIds": [],
        },
        "api_observed_fields": {
            "typeId": 2,
            "name": "",
            "prveId": "<branchNodeId>",
            "operateCondition": [],
        },
    },

    "delay_duration": {
        "type_id": 12,
        "action_id": "301",
        "name": "延时一段时间",
        "category": "flow_control",
        "status": "已验证",
        "description": "等待指定时长后继续执行",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 12,
            "actionId": "301",
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 12,
            "actionId": "301",
            "name": "<nodeName>",
            "isException": True,
            # 延时值通过以下字段设置（都用 FieldValue 格式）
            "numberFieldValue": {"fieldValue": "<days>", "fieldNodeId": "", "fieldControlId": ""},
            "hourFieldValue": {"fieldValue": "<hours>", "fieldNodeId": "", "fieldControlId": ""},
            "minuteFieldValue": {"fieldValue": "<minutes>", "fieldNodeId": "", "fieldControlId": ""},
            "secondFieldValue": {"fieldValue": "<seconds>", "fieldNodeId": "", "fieldControlId": ""},
        },
        "api_observed_example": {
            "typeId": 12,
            "name": "延时3天",
            "timerNode": {
                "actionId": "301",
                "numberFieldValue": {"fieldValue": "", "fieldNodeId": "", "fieldControlId": ""},
                "hourFieldValue": {"fieldValue": "", "fieldNodeId": "", "fieldControlId": ""},
                "minuteFieldValue": {"fieldValue": "", "fieldNodeId": "", "fieldControlId": ""},
                "secondFieldValue": {"fieldValue": "", "fieldNodeId": "", "fieldControlId": ""},
            },
        },
        "notes": [
            "时间值在 saveNode body 根级别，不是嵌套在 timerNode 下",
            "实际存储时被封装在 timerNode 对象中（GET 返回格式）",
            "fieldValue 填数字字符串（如 '3' 表示 3 天）",
        ],
    },

    "delay_until": {
        "type_id": 12,
        "action_id": "302",
        "name": "延时到指定日期",
        "category": "flow_control",
        "status": "待验证",
        "description": "等到指定日期时间后继续执行",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 12,
            "actionId": "302",
            "name": "<nodeName>",
            "isException": True,
            "executeTimeType": 0,
            "number": 0,
            "unit": 1,
            "time": "08:00",
        },
    },

    "delay_field": {
        "type_id": 12,
        "action_id": "303",
        "name": "延时到字段时间",
        "category": "flow_control",
        "status": "待验证",
        "description": "等到工作表日期字段指定的时间后继续执行",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 12,
            "actionId": "303",
            "name": "<nodeName>",
            "isException": True,
        },
    },

    "loop": {
        "type_id": 29,
        "action_id": "210",
        "app_type": 45,
        "name": "循环节点",
        "category": "flow_control",
        "status": "待验证",
        "description": "满足条件时循环执行，自动创建子流程",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 29,
            "actionId": "210",
            "appType": 45,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 29,
            "name": "<nodeName>",
            "flowIds": [],
            "subProcessId": "",
            "subProcessName": "循环",
        },
        "action_id_enum": {
            "210": "满足条件时循环",
            "211": "遍历列表",
            "212": "遍历查询结果",
        },
    },

    "abort": {
        "type_id": 30,
        "action_id": "2",
        "name": "中止流程",
        "category": "flow_control",
        "status": "待验证",
        "description": "立即终止工作流执行",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 30,
            "actionId": "2",
            "name": "<nodeName>",
            # 注意：不包含 isException
        },
    },

    "subprocess": {
        "type_id": 16,
        "name": "子流程",
        "category": "flow_control",
        "status": "待验证",
        "description": "调用另一个工作流作为子流程",
        "notes": [
            "saveNode 跳过（初始状态无需配置，在 UI 中选择目标工作流）",
        ],
    },

    # ────────────────────────────────────────────────────────────────────────────
    # 人工参与节点
    # ────────────────────────────────────────────────────────────────────────────

    "approval": {
        "type_id": 26,
        "app_type": 10,
        "name": "发起审批",
        "category": "human",
        "status": "创建成功",  # 创建成功但 publish 报 warn 103
        "description": "发起审批流程，等待审批人决定",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 26,
            "appType": 10,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 26,
            "appType": 10,
            "name": "<nodeName>",
            "isException": True,
            "accounts": "<accountsArray>",           # 审批人列表
            "formProperties": [],                    # 审批表单字段配置
            "flowIds": [],
        },
        "api_observed_fields": {
            "typeId": 26,
            "name": "发起金额变更审批",
            "accounts": [{"type": 6, "roleId": "uaid"}],
            "formProperties": [],
            "processNode": None,                     # 子审批流程（高级配置）
            "sourceAppId": "",
        },
        # accounts/formProperties 中 account 对象结构
        "account_item_format": {
            "type":        6,        # 成员类型：1=指定成员, 6=流程节点成员（触发者）
            "entityId":    "<startNodeId>",   # 成员 ID 或节点 ID
            "entityName":  "工作表事件触发",
            "roleId":      "uaid",   # "uaid"=触发者角色（固定）
            "roleTypeId":  0,
            "roleName":    "触发者",
            "avatar":      "",
            "count":       0,
            "controlType": 26,
            "flowNodeType": 0,
            "appType":     1,
        },
        # processNode 结构（审批子流程，系统自动创建）
        "process_node_structure": {
            "id":           "<审批子流程ID>",
            "companyId":    "<组织ID>",
            "startEventId": "<审批触发节点ID>",
            "flowNodeMap": {
                "<审批触发节点ID>": {
                    "typeId":       0,
                    "appType":      9,           # 9=审批触发
                    "appId":        "<worksheetId>",
                    "triggerId":    "<主流程ID>",
                    "triggerNodeId": "<发起审批节点ID>",
                    "accounts":     [],
                },
                "<人工节点ID>": {
                    "typeId":   13,
                    "actionId": "405",
                    "appType":  101,
                    "execute":  False,
                },
            },
        },
        "notes": [
            "publish 时可能报 warn 103（需要在 UI 中完整配置 processNode）",
            "基本可创建，但完整审批流程需要在 UI 中配置",
            "accounts 中 type=6, roleId='uaid' 表示由触发者发起审批",
            "processNode 由系统自动创建，不需要手动传入",
        ],
    },

    "fill": {
        "type_id": 3,
        "name": "填写节点",
        "category": "human",
        "status": "待验证",
        "description": "让指定用户填写工作表中的字段",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 3,
            "name": "<nodeName>",
            "isException": True,
            "accounts": "<accountsArray>",           # 填写人列表
            "formProperties": [],                    # 可填写的字段列表
            "flowIds": [],
        },
        "api_observed_fields": {
            "typeId": 3,
            "name": "填写",
            "flowIds": [],
            "formProperties": [],
            "accounts": [],
        },
    },

    "manual_node_detail": {
        "type_id": 13,
        "action_id": "405",
        "app_type": 101,
        "name": "人工节点操作明细",
        "category": "human",
        "status": "待验证",
        "description": "审批子流程内的人工操作节点，记录审批人的决定",
        "notes": [
            "仅出现在审批（typeId=26）节点自动创建的子流程中",
            "不需要手动添加，由审批节点自动生成",
            "appType=101 是审批子流程特有类型",
        ],
        "api_observed_fields": {
            "typeId": 13,
            "actionId": "405",
            "appType": 101,
            "execute": False,
        },
    },

    # ────────────────────────────────────────────────────────────────────────────
    # 运算节点
    # ────────────────────────────────────────────────────────────────────────────

    "calc": {
        "type_id": 9,
        "action_id": "100",
        "name": "数值运算",
        "category": "compute",
        "status": "已验证",
        "description": "对数值字段进行公式运算",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 9,
            "actionId": "100",
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 9,
            "actionId": "100",
            "name": "<nodeName>",
            "isException": True,
            "formulaMap": {},                        # 变量名 -> 节点引用的映射
            "formulaValue": "<formula>",             # 公式字符串
            "fieldValue": "<outputFieldId>",         # 输出到哪个字段
        },
    },

    "aggregate": {
        "type_id": 9,
        "action_id": "107",
        "app_type": 1,
        "name": "从工作表汇总",
        "category": "compute",
        "status": "待验证",
        "description": "对工作表记录进行汇总统计",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 9,
            "actionId": "107",
            "appType": 1,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 9,
            "actionId": "107",
            "appType": 1,
            "appId": "<targetWorksheetId>",
            "name": "<nodeName>",
            "isException": True,
            "formulaValue": "<aggregateFormula>",
            "fieldValue": "<outputFieldId>",
        },
        "api_observed_fields": {
            "typeId": 9,
            "actionId": "107",
            "appType": 1,
            "name": "汇总活动带来的线索数",
            "appId": "<worksheetId>",
            "formulaValue": "<formula>",
            "fieldValue": "<fieldId>",
            "fields": [],
        },
    },

    # ────────────────────────────────────────────────────────────────────────────
    # 开发者节点
    # ────────────────────────────────────────────────────────────────────────────

    "json_parse": {
        "type_id": 21,
        "action_id": "510",
        "app_type": 18,
        "name": "JSON 解析",
        "category": "developer",
        "status": "待验证",
        "description": "解析 JSON 字符串，提取字段值",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 21,
            "actionId": "510",
            "appType": 18,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 21,
            "actionId": "510",
            "appType": 18,
            "name": "<nodeName>",
            "isException": True,
            "jsonContent": "<jsonString>",           # 输入 JSON 字符串（可含动态引用）
            "controls": [],                          # 输出字段定义列表
        },
    },

    "code_block": {
        "type_id": 14,
        "action_id": "102",
        "name": "代码块",
        "category": "developer",
        "status": "待验证",
        "description": "运行自定义 JS/Python 代码",
        "notes": [
            "saveNode 跳过（初始状态无需配置，代码在 UI 中编写）",
        ],
    },

    "api_request": {
        "type_id": 8,
        "app_type": 7,
        "name": "发送自定义 API 请求",
        "category": "developer",
        "status": "待验证",
        "description": "向外部系统发送 HTTP 请求",
        "notes": [
            "saveNode 跳过（初始状态无需配置，在 UI 中配置请求参数）",
        ],
    },

    # ────────────────────────────────────────────────────────────────────────────
    # AI 节点
    # ────────────────────────────────────────────────────────────────────────────

    "ai_text": {
        "type_id": 31,
        "action_id": "531",
        "app_type": 46,
        "name": "AI 生成文本",
        "category": "ai",
        "status": "待验证",
        "description": "调用 AI 生成文本内容",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 31,
            "actionId": "531",
            "appType": 46,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 31,
            "actionId": "531",
            "appType": 46,
            "appId": "",                             # 固定为空字符串
            "name": "<nodeName>",
            # 注意：不包含 isException
        },
    },

    "ai_object": {
        "type_id": 31,
        "action_id": "532",
        "app_type": 46,
        "name": "AI 生成数据对象",
        "category": "ai",
        "status": "待验证",
        "description": "调用 AI 生成结构化数据对象",
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 31,
            "actionId": "532",
            "appType": 46,
            "name": "<nodeName>",
            # 注意：不包含 isException
        },
    },

    "ai_agent": {
        "type_id": 33,
        "action_id": "533",
        "app_type": 48,
        "name": "AI Agent",
        "category": "ai",
        "status": "待验证",
        "description": "运行 AI Agent 执行多步骤任务",
        "add_payload": {
            "processId": "<processId>",
            "typeId": 33,
            "actionId": "533",
            "appType": 48,
            "name": "<nodeName>",
            "prveId": "<prevNodeId>",
        },
        "save_node_payload": {
            "processId": "<processId>",
            "nodeId": "<nodeId>",
            "flowNodeType": 33,
            "actionId": "533",
            "appType": 48,
            "appId": "",
            "name": "<nodeName>",
            "tools": [],                             # AI 工具列表（见 tool_item_format）
            # 注意：不包含 isException
        },
        "tool_item_format": {
            "type": "<toolType>",  # 1=工作表查询, 2=写入, 3=知识库, 4=其他
        },
    },
}


# ─── 工作流创建 API 摘要 ─────────────────────────────────────────────────────────

WORKFLOW_CREATE_API = {
    "process_add": {
        "url": "https://api.mingdao.com/workflow/process/add",
        "method": "POST",
        "description": "创建工作流进程",
        "payload": {
            "companyId": "",
            "relationId": "<appId>",
            "relationType": 2,
            "startEventAppType": "<1|5|6>",  # 1=工作表事件, 5=定时, 6=日期字段
            "name": "<workflowName>",
            "explain": "",
        },
        "response": {
            "status": 1,
            "data": {
                "id": "<processId>",
                "companyId": "<companyId>",
                "name": "<workflowName>",
                "publishStatus": 0,
            },
        },
    },
    "app_management_add_workflow": {
        "url": "https://www.mingdao.com/api/AppManagement/AddWorkflow",
        "method": "POST",
        "description": "注册工作流到应用工作流列表（让工作流在应用中可见）",
        "referer": "https://www.mingdao.com/workflowedit/<processId>",
        "payload": {
            "projectId": "<companyId>",
            "name": "<workflowName>",
        },
    },
    "get_process_publish": {
        "url": "https://api.mingdao.com/workflow/process/getProcessPublish",
        "method": "GET",
        "params": {"processId": "<processId>"},
        "description": "获取工作流发布信息，含 startNodeId",
        "response_data_keys": [
            "id", "startNodeId", "startAppId", "startAppType", "startTriggerId",
        ],
    },
    "flow_node_add": {
        "url": "https://api.mingdao.com/workflow/flowNode/add",
        "method": "POST",
        "description": "添加节点骨架（返回新节点 ID）",
        "payload": {
            "processId": "<processId>",
            "prveId": "<prevNodeId>",
            "name": "<nodeName>",
            "typeId": "<typeId>",
            "actionId": "<actionId>",
            "appType": "<appType>",
        },
        "response_data": {
            "addFlowNodes": [{"id": "<newNodeId>"}],
        },
    },
    "flow_node_save_node": {
        "url": "https://api.mingdao.com/workflow/flowNode/saveNode",
        "method": "POST",
        "description": "保存节点配置（各节点参数见上方 WORKFLOW_NODE_SCHEMA）",
    },
    "flow_node_get": {
        "url": "https://api.mingdao.com/workflow/flowNode/get",
        "method": "GET",
        "params": {"processId": "<processId>"},
        "description": "获取工作流所有节点配置",
        "response_data_keys": [
            "id", "companyId", "startEventId", "flowNodeMap",
        ],
        "flow_node_map_format": "{ nodeId: { typeId, actionId, appType, appId, name, nextId, prveId, ...nodeSpecificFields } }",
    },
    "process_publish": {
        "url": "https://api.mingdao.com/workflow/process/publish",
        "method": "GET",
        "params": {"isPublish": "true", "processId": "<processId>"},
        "description": "发布（启用）工作流",
        "response_data_keys": ["isPublish", "errorNodeIds", "processWarnings"],
    },
    "list_all": {
        "url": "https://api.mingdao.com/workflow/v1/process/listAll",
        "method": "GET",
        "params": {"relationId": "<appId>"},
        "description": "获取应用的所有工作流列表",
        "response_data": "list of {processListType, groupId, groupName, processList: [{id, name, ...}]}",
    },
}


# ─── AI 规划用：节点类型快速参考 ──────────────────────────────────────────────────

AI_PLANNING_NODE_TYPES = {
    # 数据操作（最常用）
    "add_record": {
        "description": "新增记录到目标工作表",
        "required": ["target_worksheet_id", "fields"],
        "fields_note": "建议包含目标表全部可操作字段",
        "verified": True,
    },
    "update_record": {
        "description": "更新已有记录的字段值",
        "required": ["target_worksheet_id", "fields"],
        "fields_note": "通常只填 1~3 个需更新的字段",
        "verified": True,
    },
    "delete_record": {
        "description": "删除工作表记录",
        "required": ["target_worksheet_id"],
        "fields_note": "fields 为空，通过 filters 指定删除条件",
        "verified": False,
    },
    "get_record": {
        "description": "查询单条记录",
        "required": ["target_worksheet_id"],
        "verified": True,
    },

    # 通知
    "notify": {
        "description": "发送站内消息通知",
        "required": ["content"],
        "content_field": "sendContent",
        "verified": True,
    },
    "copy": {
        "description": "抄送消息",
        "required": ["content"],
        "content_field": "sendContent",
        "verified": True,
    },

    # 流程控制
    "delay_duration": {
        "description": "延时等待",
        "required": [],
        "verified": True,
    },
    "approval": {
        "description": "发起审批流程",
        "required": [],
        "verified": False,
        "warning": "publish 可能报 warn，建议配合 UI 完整配置",
    },

    # 运算
    "calc": {
        "description": "数值公式运算",
        "required": ["formulaValue", "fieldValue"],
        "verified": True,
    },
    "aggregate": {
        "description": "工作表数据汇总统计",
        "required": ["target_worksheet_id"],
        "verified": False,
    },

    # 禁用
    "branch": {
        "description": "条件分支",
        "verified": False,
        "disabled": True,
        "disabled_reason": "配置复杂，AI 规划禁止使用",
    },
}


# ─── 字段值格式说明 ───────────────────────────────────────────────────────────────

FIELD_VALUE_FORMATS = {
    "static_text": {
        "example": "固定文本内容",
        "description": "直接填字符串",
    },
    "static_number": {
        "example": "100",
        "description": "数字填字符串形式",
    },
    "static_select": {
        "example": "1169bd69-6f4c-4628-88f3-b170cd0fd108",
        "description": "单选必须用完整 UUID key（从工作表结构的 options 中获取），不能截断",
    },
    "dynamic_trigger_field": {
        "example": "$startNodeId-fieldId$",
        "planning_placeholder": "{{trigger.fieldId}}",
        "description": "引用触发记录的字段值，规划时用占位符，执行时自动替换",
    },
    "dynamic_upstream_field": {
        "example": "$upstreamNodeId-fieldId$",
        "description": "引用上游节点（如查询节点）输出的字段值",
    },
    "empty": {
        "example": "",
        "description": "清空/不填",
    },
}
