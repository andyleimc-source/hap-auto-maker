# 工作流私有接口文档（基于 `创建工作流.har`）

更新时间：2026-03-13  
用途：记录工作流创建、发布、启停相关私有接口，供 `old_workflow/scripts/hap/create_workflows_from_plan.py` 落地真实请求。  
当前状态：已接入 `old_workflow/record/action/创建工作流.har` 中验证过的最小可用链路，可真实创建：
- 工作表事件触发
- 新增记录动作节点
- 流程名称更新
- 发布流程

暂未接入：
- 定时触发 / 按日期字段触发 / Webhook 触发
- 更新记录、通知、审批、子流程等其他动作节点

## 1. 当前脚本约定
- 创建脚本已经支持：
  - 读取 `workflow_plan_v1`
  - 基于 HAR 执行 `process/add -> flowNode/saveNode -> flowNode/add/saveNode -> process/update -> process/publish`
  - dry-run 落盘
  - JSONL 日志
- 非 dry-run 模式要求提供私有接口配置文件：
  - `/Users/andy/Desktop/hap_auto/old_workflow/data/api_docs/workflow/private_workflow_api.json`

## 2. 当前已验证接口链
1. `POST https://api.mingdao.com/workflow/process/add`
   - 用途：创建草稿流程壳子
   - 关键入参：
     - `relationId`: 应用 `appId`
     - `relationType`: 固定 `2`
     - `startEventAppType`: 固定 `1`
     - `name`
     - `explain`
   - 关键响应：
     - `data.id`: 草稿 `processId`
     - `data.companyId`

2. `POST https://www.mingdao.com/api/AppManagement/AddWorkflow`
   - 用途：同步应用管理侧的工作流列表
   - 当前脚本按 HAR 保留调用，但不依赖其返回结构做后续拼装

3. `GET https://api.mingdao.com/workflow/flowNode/get`
   - 用途：拿到 `startEventId`
   - 关键入参：
     - `processId`
     - `count=200`

4. `POST https://api.mingdao.com/workflow/flowNode/saveNode`
   - 用途：保存触发器节点
   - 当前已验证的 `flowNodeType=0`
   - 当前已验证的触发器：
     - `triggerId=2`: 仅新增记录时触发
     - `triggerId=3`: 代码里按“仅更新记录时触发”接入，尚未由 HAR 二次验证
   - 关键字段：
     - `appId`
     - `appType=1`
     - `assignFieldIds`
     - `operateCondition`
     - `controls`

5. `POST https://api.mingdao.com/workflow/flowNode/add`
   - 用途：在流程图中新增动作节点
   - 当前已验证的动作：
     - `typeId=6`
     - `actionId=1`
     - 含义：新增记录

6. `GET https://api.mingdao.com/workflow/flowNode/getAppTemplateControls`
   - 用途：拉取目标工作表控件清单，用于组装新增记录节点字段

7. `GET https://api.mingdao.com/workflow/flowNode/getFlowNodeAppDtos`
   - 用途：拉取前置节点可引用字段，当前主要用于校验 `trigger_field`

8. `POST https://api.mingdao.com/workflow/flowNode/saveNode`
   - 用途：保存新增记录节点
   - 当前已验证的 `flowNodeType=6`
   - 关键字段：
     - `appId`: 目标工作表
     - `fields`: 目标字段赋值
   - 动态引用格式：
     - `"$<triggerNodeId>-<sourceFieldId>$"`

9. `POST https://api.mingdao.com/workflow/process/update`
   - 用途：更新工作流名称、说明、图标颜色

10. `GET https://api.mingdao.com/workflow/process/publish?isPublish=true&processId=...`
   - 用途：发布流程
   - 关键响应：
     - `data.process.id`: 发布版流程 id

## 3. 当前 plan 字段格式
`create_record` 节点当前使用以下结构：

```json
{
  "nodeType": "create_record",
  "name": "新增记录",
  "config": {
    "targetWorksheetId": "目标表ID",
    "targetWorksheetName": "目标表名称",
    "fieldValues": [
      {
        "fieldId": "目标字段ID",
        "valueType": "static",
        "value": "固定值"
      },
      {
        "fieldId": "目标字段ID",
        "valueType": "trigger_field",
        "sourceFieldId": "触发记录字段ID"
      }
    ]
  }
}
```

说明：
- `valueType=static` 时写固定值，脚本会转成字符串或 JSON 字符串。
- `valueType=trigger_field` 时会被拼成 `"$<triggerNodeId>-<sourceFieldId>$"`。
- `scheduled_trigger` 因无触发记录，当前只允许 `static`。

## 4. JSON 配置格式
`private_workflow_api.json` 当前建议如下：

```json
{
  "schemaVersion": "workflow_private_api_v1",
  "enabled": true,
  "processAddUrl": "https://api.mingdao.com/workflow/process/add",
  "processGetUrl": "https://api.mingdao.com/workflow/flowNode/get",
  "processUpdateUrl": "https://api.mingdao.com/workflow/process/update",
  "processPublishUrl": "https://api.mingdao.com/workflow/process/publish",
  "appManagementAddWorkflowUrl": "https://www.mingdao.com/api/AppManagement/AddWorkflow",
  "flowNodeAddUrl": "https://api.mingdao.com/workflow/flowNode/add",
  "flowNodeSaveUrl": "https://api.mingdao.com/workflow/flowNode/saveNode"
}
```

说明：
- `enabled=true` 时，`create_workflows_from_plan.py` 才会真正发起非 dry-run 请求。
- 未提供该 JSON 时，脚本会明确报错并提示先补抓包资料。
- 未被当前 HAR 覆盖的触发器 / 动作节点，脚本会在结果中标记 `skipped=true`。
