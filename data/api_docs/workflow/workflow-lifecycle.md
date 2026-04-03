# 工作流生命周期管理

> 来源：hap-auto-maker 源码分析 + 已有 api-spec 交叉验证（2026-03-31）
> 认证：Web (Cookie + Authorization)，域名 `api2.mingdao.com`（workflow 接口）
> 覆盖蓝图：3j1（获取详情）、3j2（列出工作流）、3j3（启用）、3j4（禁用）

---

## 3j1: 获取工作流详情

**`GET https://api2.mingdao.com/workflow/process/getProcessPublish?processId={processId}`**

获取工作流的已发布信息，核心用途是拿 `startNodeId`（配置触发节点时必须）。

### Response

```json
{
  "status": 1,
  "data": {
    "id": "69c230004aa00636bbbfa2c4",
    "name": "未命名工作流",
    "companyId": "fe288386-3d26-4eab-b5d2-51eeab82a7f9",
    "relationId": "ba498325-8c0b-4684-bda3-cd6c82812a50",
    "startNodeId": "69c230004aa00636bbbfa2c5",
    "publishStatus": 0,
    "enabled": false,
    "startEventAppType": 1
  }
}
```

| 字段 | 说明 |
|------|------|
| startNodeId | 触发节点 ID，saveNode 时必须 |
| publishStatus | 0=未发布, 1=已发布 |
| enabled | 是否启用 |
| startEventAppType | 触发类型（1=工作表事件, 5=循环定时, 6=日期字段）|

---

## 3j2: 列出工作流

**`GET https://api.mingdao.com/workflow/v1/process/listAll?relationId={appId}`**

获取指定应用下所有工作流（分组结构）。

### Response

```json
{
  "status": 1,
  "data": [
    {
      "groupId": "group-uuid",
      "groupName": "默认分组",
      "processList": [
        {
          "id": "69c230004aa00636bbbfa2c4",
          "name": "工作流名称",
          "enabled": true,
          "publishStatus": 1,
          "startEventAppType": 1,
          "createdDate": "2026-03-24 15:00:00"
        }
      ]
    }
  ]
}
```

| 参数 | 说明 |
|------|------|
| relationId | 应用 ID（appId）|

**注意**：返回分组结构，需遍历 `data[].processList` 获取扁平列表。

---

## 3j3: 启用工作流（发布）

**`GET https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={processId}`**

将工作流发布并设为启用状态。同一接口兼做发布预检：响应 `data.isPublish` 为 `true` 才表示真正启用成功。

**前置条件**：工作流必须已配置触发节点（saveNode），否则 `isPublish` 返回 `false`，`errorNodeIds` 不为空。

### Response（启用成功）

```json
{
  "status": 1,
  "data": {
    "isPublish": true,
    "name": "工作流名称",
    "processWarnings": [],
    "errorNodeIds": [],
    "process": { ... }
  }
}
```

### Response（校验失败，触发节点未配置）

```json
{
  "status": 1,
  "data": {
    "isPublish": false,
    "processWarnings": [{ "warningType": 99, "errorCount": 1, "yellow": false }],
    "errorNodeIds": ["69cbbe2426f5606b167fe993"],
    "process": null
  }
}
```

| warningType | 含义 |
|-------------|------|
| 99 | 触发节点未配置（startAppId 为空）|

---

## 3j4: 禁用工作流（取消发布）

**`GET https://api.mingdao.com/workflow/process/publish?isPublish=false&processId={processId}`**

将工作流取消发布，设为停用状态。禁用后工作流不再触发，配置保留。

### Response

```json
{
  "status": 1,
  "data": {
    "isPublish": false,
    "name": "工作流名称",
    "processWarnings": [],
    "errorNodeIds": [],
    "process": null
  }
}
```

---

## 认证说明

工作流接口使用 Web 认证（Cookie + Authorization）。

- `api2.mingdao.com` 域名（workflow 操作接口）：需要 Cookie + AccountId + Authorization 头
- `api.mingdao.com/workflow/v1/` 域名（listAll）：同样使用 Web 认证，与 api2 共享同一认证体系

```python
headers = {
    "Cookie": cookie,
    "AccountId": account_id,
    "Authorization": authorization,
    "Content-Type": "application/json",
    "Origin": "https://www.mingdao.com",
}
```

---

## 完整生命周期示例

```python
# 列出应用下所有工作流
workflows = fetch_workflows(app_id, session)   # 3j2

# 获取某工作流详情
detail = get_workflow_detail(process_id, session)  # 3j1

# 启用
publish_workflow(process_id, session)   # 3j3

# 禁用
unpublish_workflow(process_id, session)  # 3j4
```
