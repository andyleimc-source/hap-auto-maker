# HANDOFF — 从 hap-ultra-maker 移植能力增强包

## 背景

`feat/v2.0` 分支已完成分组模块（Step 2c/2d）移植。现在要把 `hap-utral-maker`（注意拼写）中剩余的新能力全部移植到本项目。

**源项目路径：** `/Users/andy/Documents/coding/hap-utral-maker`
**目标项目路径：** `/Users/andy/Documents/coding/hap-auto-maker`（当前在 `feat/v2.0` 分支）

---

## 一、待移植能力清单

### 1. 甘特图视图（viewType=5）

**现状：** 本项目视图规划只允许 `viewType=0,1,3,4`（表格/看板/画廊/日历），**硬编码排除了甘特图（5）和层级视图（2）**。

**需要做的：**
- 修改 `scripts/hap/plan_worksheet_views_gemini.py`：
  - `ALLOWED_VIEW_TYPES` 加入 `"5"`（甘特图）和 `"2"`（层级视图）
  - AI Prompt 中更新说明：`viewType=5` 是甘特图，需含开始/结束日期字段
  - 约 2 处硬编码 `"0|1|3|4"` 需改为 `"0|1|2|3|4|5"`
- 修改 `scripts/hap/create_views_from_plan.py`：
  - `normalize_advanced_setting()` 增加 viewType=5 的处理（与 4 类似，无特殊设置）
- **参考 API spec：** `/Users/andy/Documents/coding/hap-utral-maker/api-specs/block1-private/worksheet/save-worksheet-view.md`（甘特图视图示例在 `viewType=5` 段落）

**影响 Wave：** Wave 4（Step 6 视图规划），不改 execute_requirements.py

---

### 2. 日期字段触发工作流（create_workflow_date_trigger.py）

**现状：** 本项目只有 3 种触发器：
- `create_workflow_worksheet_trigger.py` — 工作表事件触发
- `create_workflow_time_trigger.py` — 定时触发
- `create_workflow_custom_action_trigger.py` — 自定义动作触发

**缺少：** 日期字段触发（按工作表中某个日期字段到期时触发工作流）

**需要做的：**
- 从 ultra 复制 `workflow/scripts/create_workflow_date_trigger.py` 到本项目
- API endpoint: `POST https://api2.mingdao.com/workflow/flowNode/saveNode`，startEventAppType=6
- **参考 API spec：** `/Users/andy/Documents/coding/hap-utral-maker/api-specs/block1-private/workflow/create-workflow-date-trigger.md`
- 修改 `workflow/scripts/execute_workflow_plan.py`：在触发器分发逻辑中增加 `date_trigger` 类型处理
- 修改 `workflow/scripts/generate_workflow_plan.py`（AI Prompt）：告诉 Gemini 可以生成 `date_trigger` 类型

**影响 Wave：** Wave 4（Step 11 工作流规划）+ Wave 5（Step 12 工作流执行）

---

### 3. 更多工作流节点类型

**现状：** 本项目只支持 2 种 action_nodes：`add_record`（新增记录）和 `update_record`（更新记录）

**Ultra 新增节点（已验证 ✅）：**

| 节点 | typeId | actionId | appType | 用途 |
|------|--------|----------|---------|------|
| 分支网关 | 1 | — | — | 按条件分流 |
| 抄送通知 | 5 | — | — | 发站内通知 |
| 删除记录 | 6 | "3" | 1 | 删除数据 |
| 获取单条数据 | 6 | "4" | 1 | 查询数据 |
| 获取多条数据 | 6 | "5" | 1 | 批量查询 |
| 数值运算 | 9 | "100" | — | 计算字段 |
| 从工作表汇总 | 9 | "107" | 1 | 聚合统计 |
| 延时 | 12 | "301" | — | 等待一段时间 |
| 发起审批 | 26 | — | 10 | 审批流 |
| AI 生成文本 | 31 | "531" | 46 | AIGC |

**需要做的：**
- 从 ultra 复制 `workflow/scripts/add_workflow_node.py` — 通用节点添加脚本
- 修改 `workflow/scripts/execute_workflow_plan.py`：
  - `_sanitize_action_nodes()` 扩展 `node_type` 白名单
  - `add_action_nodes()` 中根据 typeId/actionId 分发不同创建逻辑
- 修改 `workflow/scripts/generate_workflow_plan.py`（AI Prompt）：告诉 Gemini 可用的节点类型
- **参考 API spec：** `/Users/andy/Documents/coding/hap-utral-maker/api-specs/block1-private/workflow/workflow-node-types.md` 和 `workflow-node-configs.md`

**影响 Wave：** Wave 4（Step 11）+ Wave 5（Step 12）

---

### 4. 工作流生命周期管理（启用/禁用/列出）

**现状：** 本项目创建工作流后不会自动启用，也无法列出/管理

**Ultra 新增：**
- `workflow/scripts/workflow_lifecycle.py` — 启用/禁用/列出/获取详情
- API endpoints:
  - 列出: `GET https://api.mingdao.com/workflow/v1/process/listAll?relationId={appId}`
  - 启用: `POST https://api2.mingdao.com/workflow/process/publish`
  - 禁用: `POST https://api2.mingdao.com/workflow/process/close`
  - 详情: `GET https://api2.mingdao.com/workflow/process/getProcessPublish?processId={id}`

**需要做的：**
- 复制 `workflow/scripts/workflow_lifecycle.py` 到本项目
- 在 `workflow/scripts/execute_workflow_plan.py` 末尾增加：创建完所有工作流后，批量 publish 启用
- **参考 API spec：** `/Users/andy/Documents/coding/hap-utral-maker/api-specs/block1-private/workflow/workflow-lifecycle.md`

**影响 Wave：** Wave 5（Step 12 末尾追加启用）

---

### 5. 页面组件底层脚本（page_create / page_get / page_save / page_delete）

**现状：** 本项目有 `pipeline_pages.py`（高级编排）和 `create_pages_from_plan.py`（创建页面），但缺少底层原子操作脚本

**Ultra 新增：**
- `scripts/hap/page_create.py` — 创建空白页面（POST /api/AppManagement/AddWorkSheet, type=1）
- `scripts/hap/page_get.py` — 获取页面内容（POST https://api.mingdao.com/report/custom/getPage）
- `scripts/hap/page_save.py` — 保存页面布局和组件（POST https://api.mingdao.com/report/custom/savePage）
- `scripts/hap/page_delete.py` — 删除页面（POST /api/AppManagement/RemoveWorkSheetForApp）

**需要做的：**
- 直接复制这 4 个文件到本项目 `scripts/hap/`
- 这些是工具脚本，不需要改 execute_requirements.py
- 后续 pipeline_pages.py 可以调用这些底层脚本实现更精细的页面管理

**影响 Wave：** 无（工具脚本，不改流水线）

---

### 6. 工作表/字段底层操作脚本

**Ultra 新增：**
- `scripts/hap/get_row.py` — 获取单条记录
- `scripts/hap/update_row.py` — 更新单条记录
- `scripts/hap/get_worksheet_detail.py` — 获取工作表详情
- `scripts/hap/delete_worksheet.py` — 删除工作表
- `scripts/hap/delete_worksheet_field.py` — 删除单个字段
- `scripts/hap/update_worksheet_field.py` — 更新字段属性

**需要做的：**
- 直接复制到本项目 `scripts/hap/`
- 工具脚本，不改流水线

---

## 二、HTML 流程图更新

`docs/pipeline-visual.html` 需要更新：
- Step 6（视图规划）的描述：加入甘特图、层级视图
- Step 11（工作流规划）的描述：加入日期触发器、新节点类型
- Step 12（工作流执行）的描述：加入自动启用
- badge 不变（阶段数和步骤数没增加，只是增强已有步骤）

---

## 三、测试方案

### 测试 1：甘特图视图

用和之前一样的模拟测试方式，传入「汽车生产管理应用」的 worksheet_plan，调用 `plan_worksheet_views_gemini.py` 的 AI 规划函数，验证输出中有 viewType=5（甘特图）分配给含日期字段的工作表。

### 测试 2：工作流规划增强

同样用模拟方式，调用 `generate_workflow_plan.py` 的 AI 规划函数，验证输出中有：
- `date_trigger` 类型的工作流
- 超过 `add_record/update_record` 的节点类型（如 delete_record、分支、通知）

### 测试 3：脚本语法检查

对所有新增/修改的 .py 文件跑 `ast.parse()` 确认无语法错误。

### 测试报告

输出每个能力的移植结果（成功/失败），附带 AI 规划的关键输出片段。

---

## 四、实施顺序

1. 复制底层工具脚本（page_*.py、get_row.py 等 6 个文件）— 纯复制，零风险
2. 甘特图视图 — 改 2 个文件（plan_views + create_views）
3. 日期触发器 — 复制 1 个 + 改 2 个文件（execute_workflow_plan + generate_workflow_plan）
4. 更多工作流节点 — 复制 1 个 + 改 2 个文件
5. 工作流生命周期 — 复制 1 个 + 改 1 个文件
6. 更新 HTML — 改 1 个文件
7. 跑测试 + 出报告

---

## 五、关键文件路径速查

### Ultra（源）

| 文件 | 路径 |
|------|------|
| 甘特图 API spec | `/Users/andy/Documents/coding/hap-utral-maker/api-specs/block1-private/worksheet/save-worksheet-view.md` |
| 日期触发器 | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/workflow/scripts/create_workflow_date_trigger.py` |
| 日期触发器 API spec | `/Users/andy/Documents/coding/hap-utral-maker/api-specs/block1-private/workflow/create-workflow-date-trigger.md` |
| 通用节点添加 | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/workflow/scripts/add_workflow_node.py` |
| 节点类型枚举 | `/Users/andy/Documents/coding/hap-utral-maker/api-specs/block1-private/workflow/workflow-node-types.md` |
| 节点配置结构 | `/Users/andy/Documents/coding/hap-utral-maker/api-specs/block1-private/workflow/workflow-node-configs.md` |
| 工作流生命周期 | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/workflow/scripts/workflow_lifecycle.py` |
| page_create.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/page_create.py` |
| page_get.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/page_get.py` |
| page_save.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/page_save.py` |
| page_delete.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/page_delete.py` |
| get_row.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/get_row.py` |
| update_row.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/update_row.py` |
| get_worksheet_detail.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/get_worksheet_detail.py` |
| delete_worksheet.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/delete_worksheet.py` |
| delete_worksheet_field.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/delete_worksheet_field.py` |
| update_worksheet_field.py | `/Users/andy/Documents/coding/hap-utral-maker/hap-auto-maker/scripts/hap/update_worksheet_field.py` |

### Auto（目标，需修改）

| 文件 | 改动 |
|------|------|
| `scripts/hap/plan_worksheet_views_gemini.py` | 加入 viewType 2/5 |
| `scripts/hap/create_views_from_plan.py` | 加入 viewType 2/5 处理 |
| `workflow/scripts/execute_workflow_plan.py` | 加入 date_trigger + 更多 node types + auto publish |
| `workflow/scripts/generate_workflow_plan.py` | AI Prompt 加入日期触发器 + 新节点类型 |
| `docs/pipeline-visual.html` | 更新 Step 6/11/12 描述 |
