# 工作流 - 工作表事件触发

> 来源：hap-auto-maker 源码 + 浏览器实际抓包验证（2026-03-24）
> 认证：Web (Cookie + Authorization) + API Key (process/add 用 api2 域名)

---

## 总体流程（3步）

```
Step 1: POST /workflow/process/add          → 创建工作流进程，获取 processId
Step 2: POST /api/AppManagement/AddWorkflow → 注册到应用工作流列表（可见性）
Step 3: GET  /workflow/process/getProcessPublish?processId=xxx → 获取 startNodeId
Step 4: POST /workflow/flowNode/saveNode    → 绑定触发工作表 + 配置触发条件
```

> **为什么需要 Step 2？** 不调用则工作流在应用工作流列表中不可见（无 groupId）
> **为什么需要 Step 3？** saveNode 需要 startNodeId，只能通过 getProcessPublish 获取

---

## Step 1: 创建工作流进程

**`POST https://api2.mingdao.com/workflow/process/add`**

### Request Body

```json
{
  "companyId": "",
  "relationId": "ba498325-8c0b-4684-bda3-cd6c82812a50",
  "relationType": 2,
  "startEventAppType": 1,
  "name": "未命名工作流",
  "explain": "",
  "iconColor": "",
  "iconName": ""
}
```

| 参数 | 类型 | 说明 |
|------|------|------|
| relationId | string | 应用 ID（appId）|
| relationType | integer | 固定 `2`（应用类型）|
| startEventAppType | integer | **`1` = 工作表事件触发**（见全部枚举） |
| name | string | 工作流名称 |
| explain | string | 说明，可空 |

#### startEventAppType 全量枚举

| 值 | 触发类型 |
|----|---------|
| 1 | 工作表事件触发 |
| 5 | 循环定时触发 |
| 6 | 按日期字段触发 |
| （其他） | Webhook / 人员事件 / AI 动作等（待录制） |

### Response

```json
{
  "status": 1,
  "data": {
    "id": "69c230004aa00636bbbfa2c4",
    "companyId": "fe288386-3d26-4eab-b5d2-51eeab82a7f9",
    "name": "未命名工作流",
    "publishStatus": 0,
    "createdDate": "2026-03-24 15:00:00"
  }
}
```

---

## Step 2: 注册到应用工作流列表

**`POST https://www.mingdao.com/api/AppManagement/AddWorkflow`**

### Request Headers

```
Referer: https://www.mingdao.com/workflowedit/{processId}
```

### Request Body

```json
{
  "projectId": "fe288386-3d26-4eab-b5d2-51eeab82a7f9",
  "name": "未命名工作流"
}
```

---

## Step 3: 获取 startNodeId

**`GET https://api2.mingdao.com/workflow/process/getProcessPublish?processId={processId}`**

### Response

```json
{
  "status": 1,
  "data": {
    "startNodeId": "69c230004aa00636bbbfa2c5"
  }
}
```

---

## Step 4: 配置触发节点

**`POST https://api2.mingdao.com/workflow/flowNode/saveNode`**

### Request Body（完整版，含浏览器验证补充字段）

```json
{
  "appId": "689fe97d8a7dfabb2936e228",
  "appType": 1,
  "processId": "69c230004aa00636bbbfa2c4",
  "nodeId": "69c230004aa00636bbbfa2c5",
  "flowNodeType": 0,
  "name": "工作表事件触发",
  "triggerId": "4",
  "assignFieldIds": ["fieldId1", "fieldId2"],
  "operateCondition": [],
  "controls": [],
  "returns": []
}
```

### 参数说明

| 参数 | 类型 | 来源 | 说明 |
|------|------|------|------|
| appId | string | 必填 | 触发工作表的 worksheetId |
| appType | integer | 固定 `1` | 工作表事件触发固定值 |
| processId | string | Step 1 获取 | 工作流进程 ID |
| nodeId | string | Step 3 获取 | 触发节点 ID（startNodeId）|
| flowNodeType | integer | 固定 `0` | 触发节点类型 |
| name | string | 固定 | `"工作表事件触发"` |
| triggerId | string | 必填 | 触发时机（见枚举）|
| assignFieldIds | array | 可选 | 指定字段更新时触发，空数组=任意字段 |
| operateCondition | array | 可选 | 触发条件筛选器，空数组=无条件 |
| controls | array | 推荐 | 工作表字段定义，空数组可创建但UI无法预加载字段 |
| **returns** | **array** | **⚠️ 必须** | **固定空数组 `[]`，源码缺失此字段** |

### triggerId 枚举

| 值 | 触发时机 |
|----|---------|
| "1" | 仅新增记录时 |
| "2" | 新增或更新记录时（默认）|
| "3" | 删除记录时 |
| "4" | 仅更新记录时 |

### operateCondition 结构（触发条件）

`operateCondition` 是一个**二维数组**：外层是 OR 组，内层是同组内 AND 条件。

```
operateCondition = [
  [condA, condB],    // OR 第1组（组内 condA AND condB）
  [condC],           // OR 第2组
]
```

#### 类型1：静态值条件（字符串/数字等）

```json
{
  "nodeId": "triggerNodeId",
  "nodeName": "工作表事件触发",
  "nodeType": 0,
  "appType": 1,
  "actionId": "",
  "filedId": "689fe9bc8979c0ca28dc48eb",
  "filedValue": "应用创作AI",
  "sourceType": 0,
  "advancedSetting": {
    "analysislink": "1",
    "min": "",
    "sorttype": "en",
    "max": "",
    "custom_event": ""
  },
  "filedTypeId": 2,
  "enumDefault": 2,
  "conditionId": "1",
  "value": null,
  "conditionValues": [
    {
      "nodeId": "",
      "nodeName": "",
      "nodeType": null,
      "appType": null,
      "actionId": "",
      "controlId": "",
      "controlName": "",
      "sourceType": null,
      "value": "222",
      "type": null
    }
  ],
  "ignoreEmpty": null,
  "ignoreValueEmpty": null,
  "fromValue": null,
  "toValue": null
}
```

#### 类型2：引用其他字段条件（日期/关联等）

```json
{
  "nodeId": "triggerNodeId",
  "nodeName": "工作表事件触发",
  "nodeType": 0,
  "appType": 1,
  "actionId": "",
  "filedId": "wfcotime",
  "filedValue": "完成时间",
  "sourceType": 0,
  "advancedSetting": null,
  "filedTypeId": 16,
  "enumDefault": 0,
  "conditionId": "9",
  "value": null,
  "conditionValues": [
    {
      "nodeId": "triggerNodeId",
      "nodeName": "工作表事件触发",
      "nodeType": 0,
      "appType": 1,
      "actionId": "",
      "controlId": "wfdtime",
      "controlName": "剩余时间",
      "sourceType": 0,
      "value": null,
      "type": null
    }
  ],
  "ignoreEmpty": null,
  "ignoreValueEmpty": null,
  "fromValue": null,
  "toValue": null
}
```

**两种类型的区别：**

| 字段 | 静态值 | 引用字段 |
|------|--------|---------|
| `conditionValues[0].value` | `"比较值"` | `null` |
| `conditionValues[0].controlId` | `""` | 被引用字段的 ID |
| `conditionValues[0].controlName` | `""` | 被引用字段的名称 |
| `conditionValues[0].sourceType` | `null` | `0`（当前触发节点）|
| `advancedSetting` | 对象 | `null` |

**条件字段说明：**

| 字段 | 说明 |
|------|------|
| filedId | 字段 ID（来自工作表结构，系统字段如 `wfcotime`）|
| filedValue | 字段显示名称 |
| filedTypeId | 字段类型（2=文本, 6=数字, 16=日期, 等）|
| conditionId | 比较运算符（"1"=包含, "2"=不包含, "9"=等于日期引用 等）|

### Response

```json
{
  "status": 1,
  "msg": "成功",
  "data": {}
}
```

---

## 源码 vs 实际差异汇总

| 字段 | hap-auto-maker 源码 | 实际浏览器行为 | 影响 |
|------|---------------------|----------------|------|
| `returns` | ❌ 缺失 | `[]` 必须传 | 可能导致接口报错 |
| `controls` | `[]` 空 | 完整字段定义（~20+项）| 工作流 UI 无法预加载字段显示 |
| `assignFieldIds` | 只能 `[]` | 支持传字段 ID 数组 | 无法指定特定字段触发 |
| `operateCondition` | 只能 `[]` | 支持完整条件结构 | 无法程序化设置触发条件 |

---

## 使用示例（最简版）

```python
# Step 1: 创建工作流
resp = api2.post('/workflow/process/add', {
    'companyId': '',
    'relationId': app_id,
    'relationType': 2,
    'startEventAppType': 1,
    'name': name,
    'explain': '',
})
process_id = resp['data']['id']
company_id = resp['data']['companyId']

# Step 2: 注册可见性
web.post('/api/AppManagement/AddWorkflow',
    {'projectId': company_id, 'name': name},
    headers={'Referer': f'https://www.mingdao.com/workflowedit/{process_id}'}
)

# Step 3: 获取 startNodeId
pub = api2.get(f'/workflow/process/getProcessPublish?processId={process_id}')
start_node_id = pub['data']['startNodeId']

# Step 4: 绑定触发工作表
api2.post('/workflow/flowNode/saveNode', {
    'appId': worksheet_id,
    'appType': 1,
    'processId': process_id,
    'nodeId': start_node_id,
    'flowNodeType': 0,
    'name': '工作表事件触发',
    'triggerId': '2',          # 2=新增或更新
    'assignFieldIds': [],       # 空=任意字段
    'operateCondition': [],     # 空=无条件
    'controls': [],
    'returns': [],              # ⚠️ 必须传，否则可能报错
})
```
