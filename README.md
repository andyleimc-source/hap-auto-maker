# HAP Workflow Automation

本项目用于沉淀 HAP 工作流自动化能力，按“先记录操作节点 -> 提炼接口 -> 编写节点脚本 -> 串联整套流程”推进。

## 目录结构

```text
workflow/
├── README.md               # 项目说明、节点/接口/脚本索引
└── action/                 # 网页操作 HAR 文件（按节点分文件）
└── scripts/                # 节点脚本
```

## 当前阶段规划

1. 保存主要操作节点的 HAR（放在 `action/`）。
2. 根据 HAR 整理每个节点对应的接口信息（请求/响应/鉴权/参数）。
3. 为每个节点编写独立脚本（可单独运行和调试）。
4. 将节点脚本串联成完整流程（含重试、日志、异常处理）。

## HAR 存储规范

- 文件命名建议：`{序号}_{节点名}_{YYYYMMDD}.har`
- 示例：`01_login_20260314.har`
- 每个 HAR 尽量只覆盖一个核心节点，避免噪音请求过多。

## 操作节点清单（持续补充）

| 节点ID | 节点名称 | 目标页面/模块 | HAR文件 | 状态 | 备注 |
|---|---|---|---|---|---|
| N001 | 创建工作流 | 工作流编辑页 | `action/创建工作流.har` | 已完成首版脚本 | 需传 `--worksheet-id` 才能出现在列表 |
| N002 | 添加新增记录节点 | 工作流编辑页 | `action/创建新增记录节点.har` | 已完成首版脚本 | 支持字段映射 + 一键发布 |

## 已提炼接口（N001）

### 接口：创建流程（未发布）
- 节点ID：N001
- 场景：新建工作流（进入编辑态，未发布）
- Method：POST
- URL：`https://api.mingdao.com/workflow/process/add`
- Headers：`Content-Type: application/json`、`X-Requested-With: XMLHttpRequest`、`Cookie`
- Query Params：无
- Body：
  - `companyId`: `""`
  - `relationId`: App ID（来自 HAR）
  - `relationType`: `2`
  - `startEventAppType`: `1`
  - `name`: 工作流名称
  - `explain`: `""`
- 鉴权方式：Cookie（浏览器登录态）
- 成功响应：`status=1`，`data.id` 为新建 `processId`，`data.publishStatus=0`
- 失败码/异常：HTTP 4xx/5xx 或业务 `status != 1`
- 幂等性：否（每次调用会创建新流程）
- 备注：该接口本身创建的是未发布流程，符合“创建但未保存/未发布”阶段目标。

## 接口信息模板（从 HAR 提炼）

每个节点建议整理为如下结构：

```md
### 接口：{接口名称}
- 节点ID：{N001}
- 场景：{例如：登录/查询/提交审批}
- Method：GET/POST/PUT/DELETE
- URL：{完整路径}
- Headers：{关键请求头，脱敏}
- Query Params：{参数说明}
- Body：{请求体结构}
- 鉴权方式：{Cookie / Token / Signature}
- 成功响应：{关键字段}
- 失败码/异常：{常见错误码和含义}
- 幂等性：{是/否}
- 备注：{重放注意事项}
```

## 脚本清单（后续补充）

| 脚本名 | 对应节点ID | 输入 | 输出 | 依赖 | 状态 |
|---|---|---|---|---|---|
| `scripts/create_workflow.py` | N001 | `relation_id`、`name`、Cookie | `process_id`、`publish_status` | Python3 | 可运行 |

### N001 运行方式

```bash
cd /Users/andy/Desktop/hap_auto/workflow
python3 scripts/create_workflow.py \
  --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \
  --name '未命名工作流'
```

认证读取优先级：

1. `--cookie`
2. 环境变量 `MINGDAO_COOKIE`
3. `/Users/andy/Desktop/hap_auto/config/credentials/auth_config.py` 的 `COOKIE`

如果你希望脚本自动刷新并回写最新登录态（复用旧项目方法）：

```bash
python3 scripts/create_workflow.py \
  --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \
  --name '未命名工作流' \
  --refresh-auth \
  --refresh-on-fail
```

`--refresh-auth` 会调用 `/Users/andy/Desktop/hap_auto/scripts/refresh_auth.py`，自动获取并设置最新 Cookie 到 `auth_config.py`。

成功后会输出 JSON，关键字段：

- `process_id`：新建流程 ID
- `publish_status`：理论应为 `0`（未发布）

## 已提炼接口（N002）

### 接口一：添加节点骨架
- 节点ID：N002
- Method：POST
- URL：`https://api.mingdao.com/workflow/flowNode/add`
- Body：`processId` / `actionId="1"` / `appType=1` / `name` / `prveId`（上一节点ID） / `typeId=6`
- 成功响应：`status=1`，`data.addFlowNodes[0].id` 为新节点 ID

### 接口二：保存节点配置
- 节点ID：N002
- Method：POST
- URL：`https://api.mingdao.com/workflow/flowNode/saveNode`
- Body：`processId` / `nodeId` / `flowNodeType=6` / `actionId="1"` / `appId`（目标工作表） / `fields`（字段映射数组）
- 字段值格式：静态值直接写字符串；引用上游节点用 `"$<nodeId>-<fieldId>$"`

### 接口三：发布工作流（可选）
- 节点ID：N002
- Method：GET
- URL：`https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={processId}`
- 成功响应：`data.isPublish=true`，`data.errorNodeIds=[]`

### N002 运行方式

```bash
cd /Users/andy/Desktop/hap_auto/workflow

# 基础用法（字段留空，在 UI 里手动配置）
python3 scripts/add_new_record_node.py \
  --process-id  '69b4b92f9c92de5d02cd921f' \
  --prev-node-id '69b4b9309c92de5d02cd9220' \
  --worksheet-id '69aead6f952cd046bb57e3f2'

# 带字段映射 + 发布
python3 scripts/add_new_record_node.py \
  --process-id   '69b4b92f9c92de5d02cd921f' \
  --prev-node-id '69b4b9309c92de5d02cd9220' \
  --worksheet-id '69aead6f952cd046bb57e3f2' \
  --fields '[{"fieldId":"69aead70c55060e1d97c80c6","type":2,"enumDefault":0,"fieldValue":"$69b4b9309c92de5d02cd9220-69aead70c55060e1d97c80c6$","nodeAppId":""}]' \
  --publish
```

`--fields` 也可以传 JSON 文件路径：`--fields fields.json`

## 串联流程草案

```text
[节点1] -> [节点2] -> [节点3] -> ... -> [完成]
```

后续建议在串联脚本中统一实现：

- 全局配置（环境、账号、超时、重试次数）
- 统一日志（请求摘要、响应状态、错误信息）
- 失败中断与重试策略
- 关键结果落盘（JSON/CSV）

## 下一步

你把第一批核心节点的 HAR 放到 `action/` 后，我可以按文件逐个整理出：

1. 节点接口清单
2. 每个节点的脚本骨架
3. 一键串联执行脚本（初版）
