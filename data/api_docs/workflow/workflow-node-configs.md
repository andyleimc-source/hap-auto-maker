# Workflow Node Configuration Schemas — 工作流节点配置结构

> 录制方式：从浏览器 React fiber `workflowDetail.flowNodeMap` 中直接读取节点数据
> + 结合现有 `src/workflow/tools.py` NODE_TYPES 中的 typeId/actionId 信息
> 录制日期：2026-03-27
> 数据来源：processId `69c22ea34aa00636bbbf91e9`

---

## saveNode API

节点配置通过以下接口保存：

- **URL:** `POST https://api2.mingdao.com/workflow/flowNode/saveNode`
- **认证:** Web Cookie + Authorization（通过页面内部 XMLHttpRequest 调用，无法从页面外 fetch，存在 CORS 限制）
- **Request Body:** 节点对象（`processId` + 节点特有字段，见各节分类）

**注意：** `api2.mingdao.com` 接口无法直接从浏览器控制台 fetch（CORS 策略），必须通过 `_api2_post` 函数（服务端 Python 发起请求）调用。

---

## 通用字段（所有节点共有）

| 字段 | 类型 | 说明 |
|------|------|------|
| `processId` | string | 所属工作流 ID（saveNode 时必填） |
| `id` | string | 节点 ID（24位十六进制，add 时由服务端分配） |
| `typeId` | int | 节点类型，见下方类型表 |
| `name` | string | 节点显示名称 |
| `desc` | string | 节点描述（通常为空） |
| `alias` | string | 节点别名（通常为空） |
| `prveId` | string | 上游节点 ID |
| `nextId` | string | 下游节点 ID（`"99"` = 流程结束） |
| `flowIds` | string[] | 分支子流程 ID 列表（仅分支节点有多个） |
| `selectNodeId` | string | 选中的数据来源节点 ID |
| `selectNodeName` | string | 选中的数据来源节点名称 |
| `isException` | bool | 是否开启异常处理分支 |

---

## typeId / actionId 完整映射表

| 节点名称 | typeId | actionId | appType |
|---------|--------|----------|---------|
| 工作表事件触发 | 0 | — | 1 |
| 定时触发 | 0 | — | 3 |
| 按日期字段触发 | 0 | — | 6 |
| 分支网关 | 1 | — | — |
| 分支条件 | 2 | — | — |
| 填写 | 3 | — | — |
| 新增记录 | 6 | `"1"` | 1 |
| 更新记录 | 6 | `"2"` | 1 |
| 删除记录 | 6 | `"3"` | 1 |
| 获取单条数据 | 6 | `"4"` | 1 |
| 获取多条数据 | 6 | `"5"` | 1 |
| 校准单条数据 | 6 | `"6"` | 1 |
| 抄送 | 5 | — | — |
| 数值运算 | 9 | `"100"` | — |
| 从工作表汇总 | 9 | `"107"` | 1 |
| 发送短信 | 10 | — | — |
| 发送邮件 | 11 | `"202"` | 3 |
| 延时一段时间 | 12 | `"301"` | — |
| 延时到指定时间 | 12 | `"302"` | — |
| 延时到字段时间 | 12 | `"303"` | — |
| 人工节点操作明细 | 13 | `"405"` | 101 |
| 调用子流程 | 16 | — | — |
| 界面推送 | 17 | — | — |
| JSON 解析 | 21 | `"510"` | 18 |
| 发送站内通知 | 27 | — | — |
| 中止流程 | 30 | `"2"` | — |
| AI 生成文本 | 31 | `"531"` | 46 |
| AI 生成数据对象 | 31 | `"532"` | 46 |
| AI Agent | 33 | `"533"` | 48 |
| 发起审批 | 26 | — | 10 |
| 循环 | 29 | `"210"` | 45 |

---

## 一、触发器节点（typeId=0）

### 1.1 工作表事件触发（appType=1）

**flowNodeMap 实测结构：**
```json
{
  "id": "69c22ea34aa00636bbbf91ea",
  "typeId": 0,
  "name": "工作表事件触发",
  "desc": "",
  "alias": "",
  "nextId": "下游节点ID",
  "flowIds": [],
  "appType": 1,
  "appTypeName": "工作表",
  "appName": "应用名",
  "appId": "688d6d15f23ab1abd35df839",
  "triggerId": "4",
  "assignFieldNames": ["name", "需求"],
  "assignFieldName": "",
  "selectNodeId": "自身ID",
  "selectNodeName": "工作表事件触发",
  "isException": false
}
```

**triggerId 枚举（工作表事件）：**

| 值 | 说明 |
|----|------|
| `"1"` | 新增记录时 |
| `"2"` | 更新或新增时 |
| `"4"` | 更新记录时 |

**saveNode 关键字段：**

| 字段 | 说明 |
|------|------|
| `appId` | 监听的工作表 ID |
| `appType` | `1` = 工作表 |
| `triggerId` | 触发时机（见上方枚举） |
| `assignFieldNames` | 监听的字段名列表（空数组 = 监听全部字段） |

---

## 二、分支节点（typeId=1 / 2）

### 2.1 分支网关（typeId=1）

```json
{
  "id": "...",
  "typeId": 1,
  "name": "分支",
  "prveId": "...",
  "nextId": "99",
  "flowIds": ["条件分支1-ID", "条件分支2-ID"],
  "selectNodeId": "",
  "selectNodeName": "",
  "gatewayType": 1
}
```

**gatewayType 枚举：**

| 值 | 说明 |
|----|------|
| `1` | 互斥分支（只走首个满足条件的分支） |
| `2` | 并行分支（所有满足条件的分支都走） |

### 2.2 分支条件（typeId=2，每个分支对应一个条件节点）

```json
{
  "id": "...",
  "typeId": 2,
  "name": "",
  "flowIds": [],
  "operateCondition": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": false
}
```

**operateCondition** 为条件规则列表，结构与工作表筛选器一致（`[]` = 所有数据通过）。

---

## 三、记录操作节点（typeId=6）

所有记录操作节点共用 typeId=6，通过 actionId 区分。

### 通用字段

| 字段 | 说明 |
|------|------|
| `appType` | `1` = 工作表 |
| `appId` | 目标工作表 ID |
| `actionId` | 见映射表 |

### 3.1 新增记录（actionId="1"）

```json
{
  "typeId": 6,
  "actionId": "1",
  "appType": 1,
  "appId": "工作表ID",
  "fields": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 3.2 更新记录（actionId="2"）

```json
{
  "typeId": 6,
  "actionId": "2",
  "appType": 1,
  "appId": "工作表ID",
  "fields": [],
  "filters": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 3.3 删除记录（actionId="3"）

```json
{
  "typeId": 6,
  "actionId": "3",
  "appType": 1,
  "appId": "工作表ID",
  "filters": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 3.4 获取单条数据（actionId="4"）

```json
{
  "typeId": 6,
  "actionId": "4",
  "appType": 1,
  "appId": "工作表ID",
  "filters": [],
  "sorts": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 3.5 获取多条数据（actionId="5"）

```json
{
  "typeId": 6,
  "actionId": "5",
  "appType": 1,
  "appId": "工作表ID",
  "filters": [],
  "sorts": [],
  "number": 50,
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 3.6 校准单条数据（actionId="6"）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 6,
  "actionId": "6",
  "appType": 1,
  "appTypeName": "工作表",
  "appName": "工作表名称",
  "fields": [],
  "errorFields": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

**特有字段：** `errorFields`（校准失败时的字段映射）

---

## 四、人工参与节点

### 4.1 抄送（typeId=5）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 5,
  "name": "抄送",
  "flowIds": [],
  "accounts": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 4.2 填写（typeId=3）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 3,
  "name": "填写",
  "flowIds": [],
  "formProperties": [],
  "accounts": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 4.3 发起审批（typeId=26，appType=10）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 26,
  "name": "未命名审批流程",
  "flowIds": [],
  "formProperties": [],
  "accounts": [
    {
      "type": 6,
      "entityId": "触发节点ID",
      "entityName": "工作表事件触发",
      "roleId": "uaid",
      "roleTypeId": 0,
      "roleName": "触发者",
      "avatar": "",
      "count": 0,
      "controlType": 26,
      "flowNodeType": 0,
      "appType": 1
    }
  ],
  "sourceAppId": "工作表ID",
  "processNode": {
    "id": "审批子流程ID",
    "companyId": "组织ID",
    "startEventId": "审批触发节点ID",
    "flowNodeMap": {
      "审批触发节点ID": {
        "typeId": 0,
        "appType": 9,
        "appId": "工作表ID",
        "triggerId": "主流程ID",
        "triggerName": "主流程名称",
        "triggerNodeId": "发起审批节点ID",
        "accounts": [...]
      },
      "人工节点ID": {
        "typeId": 13,
        "actionId": "405",
        "appType": 101,
        "execute": false
      }
    }
  },
  "isException": true
}
```

**Account 对象结构（accounts/formProperties 共用）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | int | 成员类型：1=指定成员, 6=流程节点成员 |
| `entityId` | string | 成员 ID 或节点 ID |
| `entityName` | string | 显示名称 |
| `roleId` | string | 角色 ID（`"uaid"` = 触发者） |
| `roleTypeId` | int | 角色类型 |
| `roleName` | string | 角色名称 |

---

## 五、运算节点

### 5.1 数值运算（typeId=9，actionId="100"）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 9,
  "actionId": "100",
  "name": "数值运算",
  "formulaMap": {},
  "formulaValue": "",
  "fieldValue": "",
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 5.2 从工作表汇总（typeId=9，actionId="107"）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 9,
  "actionId": "107",
  "name": "从工作表汇总",
  "appId": "",
  "formulaValue": "",
  "fieldValue": "",
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

---

## 六、延时节点（typeId=12）

### 6.1 延时一段时间（actionId="301"）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 12,
  "name": "延时一段时间",
  "timerNode": {
    "name": "延时一段时间",
    "desc": "",
    "actionId": "301",
    "numberFieldValue": {
      "fieldValue": "",
      "fieldNodeId": "",
      "fieldNodeType": null,
      "fieldNodeName": null,
      "fieldAppType": null,
      "fieldActionId": null,
      "fieldControlId": "",
      "fieldControlName": null,
      "fieldControlType": null,
      "sourceType": null
    },
    "hourFieldValue": { "fieldValue": "", "fieldNodeId": "", ... },
    "minuteFieldValue": { "fieldValue": "", "fieldNodeId": "", ... },
    "secondFieldValue": { "fieldValue": "", "fieldNodeId": "", ... }
  },
  "isException": true
}
```

**timerNode.actionId 枚举：**

| 值 | 说明 |
|----|------|
| `"301"` | 延时一段时间（指定天/小时/分/秒） |
| `"302"` | 延时到指定日期时间 |
| `"303"` | 延时到字段指定时间 |

**FieldValue 通用结构：**

```json
{
  "fieldValue": "静态值（直接填数字或字符串）",
  "fieldNodeId": "引用其他节点的ID",
  "fieldControlId": "引用字段的控件ID",
  "fieldNodeType": null,
  "fieldNodeName": null,
  "fieldAppType": null,
  "fieldActionId": null,
  "fieldControlName": null,
  "fieldControlType": null,
  "sourceType": null
}
```

---

## 七、循环节点（typeId=29，actionId="210"，appType=45）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 29,
  "actionId": "210",
  "name": "满足条件时循环",
  "flowIds": [],
  "subProcessId": "循环子流程ID",
  "subProcessName": "循环",
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

**actionId 枚举：**

| 值 | 说明 |
|----|------|
| `"210"` | 满足条件时循环 |
| `"211"` | 遍历列表字段循环 |
| `"212"` | 遍历查询结果循环 |

循环节点会自动创建一个子流程（`subProcessId`），在该子流程中添加循环体节点。

---

## 八、通知节点

### 8.1 发送站内通知（typeId=27）

```json
{
  "typeId": 27,
  "name": "发送站内通知",
  "accounts": [],
  "content": "",
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 8.2 发送邮件（typeId=11，actionId="202"，appType=3）

```json
{
  "typeId": 11,
  "actionId": "202",
  "appType": 3,
  "name": "发送邮件",
  "accounts": [],
  "title": "",
  "content": "",
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 8.3 发送短信（typeId=10）

```json
{
  "typeId": 10,
  "name": "发送短信",
  "accounts": [],
  "content": "",
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 8.4 界面推送（typeId=17）

```json
{
  "typeId": 17,
  "name": "界面推送",
  "accounts": [],
  "content": "",
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

---

## 九、开发者节点

### 9.1 JSON 解析（typeId=21，actionId="510"，appType=18）

```json
{
  "typeId": 21,
  "actionId": "510",
  "appType": 18,
  "name": "JSON 解析",
  "jsonContent": "",
  "controls": [],
  "selectNodeId": "",
  "selectNodeName": "",
  "isException": true
}
```

### 9.2 中止流程（typeId=30，actionId="2"）

```json
{
  "typeId": 30,
  "actionId": "2",
  "name": "中止流程",
  "selectNodeId": "",
  "selectNodeName": ""
}
```

---

## 十、AI 节点

### 10.1 AI 生成文本（typeId=31，actionId="531"，appType=46）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 31,
  "actionId": "531",
  "appType": 46,
  "name": "AI 生成文本",
  "appId": "",
  "selectNodeId": "",
  "selectNodeName": ""
}
```

### 10.2 AI 生成数据对象（typeId=31，actionId="532"，appType=46）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 31,
  "actionId": "532",
  "appType": 46,
  "name": "AI 生成数据对象",
  "appId": "",
  "selectNodeId": "",
  "selectNodeName": ""
}
```

### 10.3 AI Agent（typeId=33，actionId="533"，appType=48）

**flowNodeMap 实测结构：**
```json
{
  "typeId": 33,
  "actionId": "533",
  "appType": 48,
  "name": "AI Agent",
  "appId": "",
  "tools": [
    {"toolId": "节点ID_1", "type": 3, "configs": []},
    {"toolId": "节点ID_2", "type": 1, "configs": []},
    {"toolId": "节点ID_3", "type": 2, "configs": []},
    {"toolId": "节点ID_4", "type": 4, "configs": []}
  ],
  "selectNodeId": "",
  "selectNodeName": ""
}
```

**tools[].type 枚举：**

| 值 | 说明 |
|----|------|
| `1` | 工作表查询工具 |
| `2` | 工作表写入工具 |
| `3` | 知识库检索工具 |
| `4` | 其他工具 |

---

## 十一、flowNode/add 接口（新建节点）

新建节点（在编辑器中拖入时）调用：
- **URL:** `POST https://api2.mingdao.com/workflow/flowNode/add`
- **Body:**
```json
{
  "processId": "流程ID",
  "prveId": "上游节点ID",
  "name": "节点名称",
  "typeId": 数字,
  "actionId": "字符串（如有）",
  "appType": 数字（如有）,
  "appId": "工作表ID（如有）"
}
```
- **Response:** `{"status": 1, "data": "新节点ID"}`

新建后**必须立即调用 saveNode** 保存节点，否则节点不会出现在流程列表中（缺少 groupId）。

---

## 十二、数据录制状态

| 节点 | typeId | actionId | 配置来源 | 状态 |
|------|--------|----------|---------|------|
| 工作表事件触发 | 0 | — | fiber 实测 | ✅ |
| 定时触发 | 0 | — | tools.py saveNode | ✅ |
| 按日期字段触发 | 0 | — | tools.py saveNode | ✅ |
| 分支 | 1 | — | fiber 实测 | ✅ |
| 分支条件 | 2 | — | fiber 实测 | ✅ |
| 填写 | 3 | — | fiber 实测 | ✅ |
| 抄送 | 5 | — | fiber 实测 | ✅ |
| 新增记录 | 6 | 1 | NODE_TYPES | ⚠️ 待完整验证 |
| 更新记录 | 6 | 2 | NODE_TYPES | ⚠️ 待完整验证 |
| 删除记录 | 6 | 3 | NODE_TYPES | ⚠️ 待完整验证 |
| 获取单条 | 6 | 4 | NODE_TYPES | ⚠️ 待完整验证 |
| 获取多条 | 6 | 5 | NODE_TYPES | ⚠️ 待完整验证 |
| 校准单条 | 6 | 6 | fiber 实测 | ✅ |
| 数值运算 | 9 | 100 | fiber 实测 | ✅ |
| 从工作表汇总 | 9 | 107 | fiber 实测 | ✅ |
| 发送短信 | 10 | — | NODE_TYPES | ⚠️ 待完整验证 |
| 发送邮件 | 11 | 202 | NODE_TYPES | ⚠️ 待完整验证 |
| 延时一段时间 | 12 | 301 | fiber 实测 | ✅ |
| 延时到指定时间 | 12 | 302 | NODE_TYPES | ⚠️ 待完整验证 |
| 人工节点操作明细 | 13 | 405 | fiber 实测 | ✅ |
| 调用子流程 | 16 | — | NODE_TYPES | ⚠️ 待完整验证 |
| 界面推送 | 17 | — | NODE_TYPES | ⚠️ 待完整验证 |
| JSON 解析 | 21 | 510 | NODE_TYPES | ⚠️ 待完整验证 |
| 发起审批 | 26 | — | fiber 实测 | ✅ |
| 发送站内通知 | 27 | — | NODE_TYPES | ⚠️ 待完整验证 |
| 循环 | 29 | 210 | fiber 实测 | ✅ |
| 中止流程 | 30 | 2 | NODE_TYPES | ⚠️ 待完整验证 |
| AI 生成文本 | 31 | 531 | fiber 实测 | ✅ |
| AI 生成数据对象 | 31 | 532 | fiber 实测 | ✅ |
| AI Agent | 33 | 533 | fiber 实测 | ✅ |
