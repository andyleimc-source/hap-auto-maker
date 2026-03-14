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

## 脚本开发规范

所有节点脚本必须遵守以下规范，保证风格统一、方便串联。

### 1. 使用共享 Session（`workflow_io.py`）

不要在脚本里直接用 `urllib` 或裸 `requests`，统一用 `workflow_io.Session`：

```python
from workflow_io import Session, persist

session = Session(cookie, account_id, authorization, origin)
resp = session.post(url, payload)
resp = session.get(url)
```

`Session` 会自动注入所有必要的鉴权 Header，并记录每次请求的 method / url / status / 耗时。

### 2. 输出落盘（固定文件名）

每个脚本在结束时调用 `persist()`，将结果写到 `output/{script}_latest.json`：

- 文件名固定（`_latest`），下游脚本可直接硬编码路径引用，无需知道时间戳
- 不保留带时间戳的历史 output（日志已覆盖历史）

```python
persist(
    script     = Path(__file__).stem,  # 脚本名，无后缀
    output     = result,               # 任意可序列化对象
    args       = vars(args),
    error      = None,                 # 有异常时传 str(e)
    started_at = started_at,           # time.time() 记录的开始时间
    session    = session,
)
```

### 3. 运行日志（带时间戳）

`persist()` 同时写 `logs/{script}_{timestamp}.json`，内容包含：

- 运行参数、完整 HTTP 请求历史（含状态码和耗时）、输出结果、错误信息、总耗时

排查问题直接看 `logs/`，不需要翻 output 历史。

### 4. 目录不入库

`output/`、`logs/`、`.claude/`、`__pycache__/` 均已加入 `.gitignore`，不提交到 Git。
产物只在本地留存，Git 仓库只保存脚本本身。

### 5. 鉴权优先级

所有脚本统一按以下顺序读取认证信息：

1. `--cookie` CLI 参数
2. 环境变量 `MINGDAO_COOKIE`
3. `config/credentials/auth_config.py` 中的 `COOKIE` 变量

`account_id` / `authorization` 同理，从 `MINGDAO_ACCOUNT_ID` / `MINGDAO_AUTHORIZATION` 或 `auth_config.py` 中加载。

### 6. 脚本间数据传递

上游脚本通过 `output/{script}_latest.json` 输出，下游脚本直接读取该文件。
不使用进程参数或标准输出传递结构化数据。

```python
# 下游脚本读取上游结果示例
import json
from pathlib import Path

plan = json.loads((Path(__file__).parents[1] / "output" / "workflow_plan_latest.json").read_text())
```

---

## 操作节点清单（持续补充）

| 节点ID | 节点名称 | 目标页面/模块 | HAR文件 | 状态 | 备注 |
|---|---|---|---|---|---|
| N001 | 创建工作流-工作表事件触发 | 工作流编辑页 | `action/创建工作流.har` | 已完成首版脚本 | 需传 `--worksheet-id` 才能出现在列表 |
| N002 | 添加新增记录节点 | 工作流编辑页 | `action/创建新增记录节点.har` | 已完成首版脚本 | 支持字段映射 + 一键发布 |
| N003 | 创建工作流-时间触发 | 工作流编辑页 | `action/创建工作流-时间触发.har` | 已完成首版脚本 | 传 `--execute-time` 自动配置定时触发节点 |
| N004 | 创建工作流-自定义动作触发 | 工作表设置页 | `action/创建工作流-自定义动作触发.har` | 已完成首版脚本 | 无 process/add；工作流由 SaveWorksheetBtn 自动创建 |

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

## 脚本清单

| 脚本名 | 对应节点ID | 输入 | 输出 | 依赖 | 状态 |
|---|---|---|---|---|---|
| `scripts/create_workflow_worksheet_trigger.py` | N001 | `relation_id`、`worksheet_id`、`name`、Cookie | `process_id`、`publish_status` | Python3 | 可运行 |
| `scripts/create_workflow_time_trigger.py` | N003 | `relation_id`、`execute_time`、`name`、Cookie | `process_id`、`publish_status` | Python3 | 可运行 |
| `scripts/create_workflow_custom_action_trigger.py` | N004 | `worksheet_id`、`app_id`、`name`、Cookie | `btn_id`、`process_id`、`start_event_id` | Python3 | 可运行 |
| `scripts/delete_workflow.py` | — | `relation_id`、Cookie | 交互式删除 | Python3 | 可运行 |
| `scripts/generate_workflow_plan.py` | — | 应用结构 JSON + Gemini Key | `output/workflow_plan_latest.json` | Python3、google-generativeai | 可运行 |
| `scripts/execute_workflow_plan.py` | — | `output/workflow_plan_latest.json`、Cookie | 批量创建结果 JSON | Python3 | 可运行 |

### N001 运行方式（工作表事件触发）

```bash
cd /Users/andy/Desktop/hap_auto/workflow
python3 scripts/create_workflow_worksheet_trigger.py \
  --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \
  --worksheet-id '69aead6f952cd046bb57e3f2' \
  --name '未命名工作流'
```

认证读取优先级：

1. `--cookie`
2. 环境变量 `MINGDAO_COOKIE`
3. `/Users/andy/Desktop/hap_auto/config/credentials/auth_config.py` 的 `COOKIE`

如果你希望脚本自动刷新并回写最新登录态：

```bash
python3 scripts/create_workflow_worksheet_trigger.py \
  --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \
  --worksheet-id '69aead6f952cd046bb57e3f2' \
  --name '未命名工作流' \
  --refresh-auth \
  --refresh-on-fail
```

成功后会输出 JSON，关键字段：

- `process_id`：新建流程 ID
- `publish_status`：理论应为 `0`（未发布）

### N003 运行方式（时间触发）

```bash
cd /Users/andy/Desktop/hap_auto/workflow
python3 scripts/create_workflow_time_trigger.py \
  --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \
  --name '定时工作流' \
  --execute-time '2026-03-14 18:25' \
  --execute-end-time '2026-03-31 18:25'
```

`--execute-time` 不传则只创建工作流，不调用 saveNode（触发节点留空，可在 UI 手动配置）。

可选时间参数：

| 参数 | 含义 | 默认值 |
|---|---|---|
| `--execute-time` | 首次执行时间 `YYYY-MM-DD HH:MM` | 空（不调用 saveNode） |
| `--execute-end-time` | 结束执行时间 `YYYY-MM-DD HH:MM` | `""` |
| `--repeat-type` | 重复类型 | `1` |
| `--interval` | 间隔数值 | `1` |
| `--frequency` | 频率单位 | `1` |
| `--week-days` | 按周重复的星期数组（JSON） | `[]` |

成功后会输出 JSON，关键字段：

- `process_id`：新建流程 ID
- `trigger_type`：`"time"`
- `execute_time`：配置的首次执行时间

### N004 运行方式（自定义动作触发）

```bash
cd /Users/andy/Desktop/hap_auto/workflow
python3 scripts/create_workflow_custom_action_trigger.py \
  --worksheet-id '69aead6fd777aea8806b9302' \
  --app-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \
  --name '开发票'
```

加 `--publish` 立即发布：

```bash
python3 scripts/create_workflow_custom_action_trigger.py \
  --worksheet-id '69aead6fd777aea8806b9302' \
  --app-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \
  --name '开发票' \
  --publish
```

可选参数：

| 参数 | 含义 | 默认值 |
|---|---|---|
| `--confirm-msg` | 确认弹窗提示语 | `你确认执行此操作吗？` |
| `--sure-name` | 确认按钮文案 | `确认` |
| `--cancel-name` | 取消按钮文案 | `取消` |
| `--publish` | 创建后立即发布 | 否 |

成功后输出 JSON，关键字段：

- `btn_id`：自定义动作按钮 ID
- `process_id`：工作流 ID
- `start_event_id`：触发节点 ID（串联下游节点时的 `prev-node-id`）

## 已提炼接口（N004）

### 接口一：创建按钮并自动生成工作流
- 节点ID：N004
- Method：POST
- URL：`https://www.mingdao.com/api/Worksheet/SaveWorksheetBtn`
- Body（首次创建，`btnId` 和 `workflowId` 均为空）：
  - `name`：按钮名称（同时作为工作流名称）
  - `worksheetId`：目标工作表 ID
  - `appId`：应用 ID
  - `workflowType`：`1`（触发工作流类型）
  - `clickType`：`1`，`showType`：`1`
  - `confirmMsg` / `sureName` / `cancelName`：确认弹窗文案
- 成功响应：`state=1`，`data` 为新建 `btnId`（同时作为 `triggerId`）

### 接口二：获取自动创建的工作流 ID
- 节点ID：N004
- Method：GET
- URL：`https://api.mingdao.com/workflow/process/getProcessByTriggerId?appId={worksheetId}&triggerId={btnId}`
- 成功响应：`status=1`，`data[0].id` 为 `processId`，`data[0].startEventId` 为触发节点 ID

### 接口三：回填 workflowId 绑定按钮与工作流
- 节点ID：N004
- Method：POST
- URL：同接口一
- Body：同首次创建，但 `btnId` 和 `workflowId` 填入实际值
- 成功响应：`state=1`

---

## 已提炼接口（N003）

### 接口：创建定时触发流程
- 节点ID：N003
- 场景：新建时间触发工作流（进入编辑态，未发布）
- Method：POST
- URL：`https://api.mingdao.com/workflow/process/add`
- Body：与 N001 相同，但 `startEventAppType: 5`（N001 为 1）
- 成功响应：`status=1`，`data.id` 为新建 `processId`

### 接口：配置定时触发节点
- 节点ID：N003
- Method：POST
- URL：`https://api.mingdao.com/workflow/flowNode/saveNode`
- Body：
  - `appType`: `5`（时间触发；工作表事件为 1）
  - `flowNodeType`: `0`（触发节点）
  - `name`: `"定时触发"`
  - `executeTime`: 首次执行时间（`"YYYY-MM-DD HH:MM"`）
  - `executeEndTime`: 结束执行时间
  - `repeatType`: 重复类型
  - `interval`: 间隔数值
  - `frequency`: 频率单位
  - `weekDays`: 按周重复的星期数组
  - 无 `appId`、`triggerId`、`operateCondition`（仅工作表事件触发才有）
- 成功响应：`status=1`

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
