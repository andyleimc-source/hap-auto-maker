# HANDOFF — 四大模块测试与优化

> 更新时间: 2026-04-03
> 测试应用: CRM客户管理系统
> app_id: `f11f2128-c4de-46cb-a2be-fe1c62ed1481`
> 应用链接: https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481
> 分支: feat/v2.0

---

## 架构概览

```
注册中心 (4 个)
├── scripts/hap/worksheets/   38 种字段类型
├── scripts/hap/views/        11 种视图类型
├── scripts/hap/charts/       17 种图表类型
└── workflow/nodes/            27 种工作流节点

规划层 scripts/hap/planning/
├── worksheet_planner.py      工作表+字段规划
├── view_planner.py           视图规划+配置
├── chart_planner.py          统计图规划
├── workflow_planner.py       工作流规划
└── constraints.py            共用约束+字段分类

执行层
├── create_worksheets_from_plan.py
├── create_views_from_plan.py
├── create_charts_from_plan.py
└── execute_workflow_plan.py
```

---

## 一、工作流节点 — 27 种注册，仅 8 种实测通过

### 测试链接
- **全节点展示(6种)**: https://www.mingdao.com/workflowedit/69cf487e9b08efb4c5bb8bca
- **订单发货流程(4种)**: https://www.mingdao.com/workflowedit/69cf46ba8f9e70c865431131

### 问题：注册了 27 种节点，但只实测通过 8 种

当前工作流演示只有 6 种节点（更新记录、获取单条、数值运算、延时、通知、抄送），远未覆盖注册中心的 27 种。需要逐个实测剩余 19 种节点，创建一个真正包含所有可用节点的工作流。

### 27 种节点完整清单

**`workflow/nodes/` 注册中心 — 9 个模块文件**

| # | 节点 | node_type | typeId/actionId | 模块 | 录制 | 实测 | 待办 |
|---|------|-----------|-----------------|------|------|------|------|
| 1 | 更新记录 | update_record | 6/2 | (execute内) | ✅ | ✓ | — |
| 2 | 新增记录(同表) | add_record | 6/1 | (execute内) | ⚠️ | ✓ | — |
| 3 | 新增记录(跨表) | add_record | 6/1 | (execute内) | ⚠️ | ⚠ | 关联字段引用 `$nodeId-fieldId$` 格式不生效，需研究 sourceControlType |
| 4 | 删除记录 | delete_record | 6/3 | record_ops | ⚠️ | ✗ | 需 filters 配置，写测试脚本验证 |
| 5 | 获取单条 | get_record | 6/4 | record_ops | ⚠️ | ✓ | — |
| 6 | 获取多条 | get_records | 13/400 | record_ops | ⚠️ | ✗ | typeId=13 非 6，需验证 add/saveNode 是否不同 |
| 7 | 校准记录 | calibrate_record | 6/6 | record_ops | ✅ | ✗ | 有 fiber 录制，需写测试 |
| 8 | 数值运算 | calc | 9/100 | compute | ✅ | ✓ | — |
| 9 | 汇总 | aggregate | 9/107 | compute | ✅ | ✗ | 有 fiber 录制，需 appId 指向目标表 |
| 10 | 站内通知 | notify | 27 | notify | ⚠️ | ✓ | — |
| 11 | 抄送 | copy | 5 | human | ✅ | ✓ | — |
| 12 | 填写 | fill | 3 | human | ✅ | ✗ | 有 fiber 录制，需 formProperties 配置 |
| 13 | 审批 | approval | 26 | approval | ✅ | ⚠ | 创建成功但 publish 报 103，需研究 processNode 子流程 |
| 14 | 延时(时长) | delay_duration | 12/301 | timer | ✅ | ✓ | — |
| 15 | 延时(日期) | delay_until | 12/302 | timer | ⚠️ | ✗ | 需验证 executeTimeType 等参数 |
| 16 | 延时(字段) | delay_field | 12/303 | timer | ⚠️ | ✗ | 需验证 |
| 17 | 发送短信 | sms | 10 | notify | ⚠️ | ✗ | 用 content 非 sendContent |
| 18 | 发送邮件 | email | 11/202 | notify | ⚠️ | ✗ | 用 content + title |
| 19 | 界面推送 | push | 17 | notify | ⚠️ | ✗ | 用 sendContent |
| 20 | 分支 | branch | 1 | flow_control | ✅ | ✗ | 有 fiber 录制，需 operateCondition 配置 |
| 21 | 分支条件 | branch_condition | 2 | flow_control | ✅ | ✗ | 有 fiber 录制 |
| 22 | 循环 | loop | 29/210 | flow_control | ✅ | ✗ | 有 fiber 录制，自动创建子流程 |
| 23 | 中止流程 | abort | 30/2 | flow_control | ⚠️ | ✗ | 最简节点，应该容易验证 |
| 24 | 子流程 | subprocess | 16 | flow_control | ⚠️ | ✗ | saveNode 跳过 |
| 25 | JSON 解析 | json_parse | 21/510 | developer | ⚠️ | ✗ | 需 jsonContent + controls |
| 26 | 代码块 | code_block | 14/102 | developer | — | ✗ | saveNode 跳过 |
| 27 | API 请求 | api_request | 8 | developer | — | ✗ | saveNode 跳过 |
| 28 | AI 文本 | ai_text | 31/531 | ai | ✅ | ✗ | 有 fiber 录制，需 appId="" |
| 29 | AI 对象 | ai_object | 31/532 | ai | ✅ | ✗ | 有 fiber 录制 |
| 30 | AI Agent | ai_agent | 33/533 | ai | ✅ | ✗ | 有 fiber 录制，需 tools 数组 |

> 录制状态：✅ = hap-utral-maker 有完整 fiber 实测 saveNode body；⚠️ = 只有 NODE_TYPES 定义
> 实测状态：✓ = 本项目 CRM 应用中创建+配置+publish 成功；⚠ = 创建成功但配置/publish 有问题；✗ = 未测试

### 待办任务（按优先级分组）

**P0：有 fiber 录制但未实测（12 种）— 直接写测试脚本验证**

这些节点在 `hap-utral-maker/api-specs/block1-private/workflow/workflow-node-configs.md` 中有完整的 saveNode body 结构，可以直接照着写测试：

- [ ] 校准记录(6/6) — 有 fiber 录制，需 fields + errorFields
- [ ] 汇总(9/107) — 有 fiber 录制，需 appId
- [ ] 填写(3) — 有 fiber 录制，需 formProperties + accounts
- [ ] 审批(26) — 有 fiber 录制的完整 processNode 结构，是 publish 失败的关键
- [ ] 分支(1) + 条件(2) — 有 fiber 录制，需搞定 operateCondition 配置
- [ ] 循环(29) — 有 fiber 录制，自动创建子流程
- [ ] AI 文本(31/531) — 有 fiber 录制
- [ ] AI 对象(31/532) — 有 fiber 录制
- [ ] AI Agent(33/533) — 有 fiber 录制，需 tools 数组

**P1：只有 NODE_TYPES 定义，需要实测（8 种）**

- [ ] 删除记录(6/3) — 需 filters
- [ ] 获取多条(13/400) — typeId=13
- [ ] 延时到日期(12/302) — 需验证参数格式
- [ ] 延时到字段(12/303) — 需验证参数格式
- [ ] 短信(10) — 用 content
- [ ] 邮件(11/202) — 用 content + title
- [ ] 推送(17) — 用 sendContent
- [ ] 中止(30/2) — 最简节点

**P2：saveNode 跳过的节点（3 种）— 创建即可用**

- [ ] 子流程(16) — 创建后在 UI 中配置
- [ ] 代码块(14/102) — 创建后在 UI 中写代码
- [ ] API 请求(8) — 创建后在 UI 中配置 URL/参数

### 录制文档位置

完整的 saveNode body 结构见：
`hap-utral-maker/api-specs/block1-private/workflow/workflow-node-configs.md`
（已同步到本项目 `data/api_docs/workflow/workflow-node-configs.md`）

### 关键修复记录

1. **`sendContent` 非 `content`** — 通知(27)和推送(17)用 `sendContent`，短信(10)和邮件(11)用 `content`
2. **延时值在根级别** — `numberFieldValue` 等直接放 saveNode body，不嵌套 `timerNode`
3. **单选字段需完整 UUID** — 截断 key 被 HAP 静默丢弃
4. **审批 publish 失败** — 需配置 processNode 子流程，录制文档中有完整结构

### 关键文件

| 文件 | 职责 |
|------|------|
| `workflow/nodes/` | 27 种节点注册中心（9 个模块） |
| `workflow/scripts/add_workflow_node.py` | 兼容层，代理到 nodes/ |
| `workflow/scripts/execute_workflow_plan.py` | 节点创建+publish |
| `data/api_docs/workflow/workflow-node-configs.md` | 完整 saveNode body 录制文档 |
| `scripts/create_demo_workflow_full.py` | 验证脚本（当前 6 种，需扩展） |

---

## 二、字段类型

### 测试链接
- **全字段演示表**: https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481/69ce832640691821042c6e79/69cf74eef9434db36c6e0816

### 实测结果: 38 种字段类型，全部创建成功

| 分类 | 数量 | 类型 |
|------|------|------|
| basic | 4 | Text, RichText, AutoNumber, TextCombine |
| number | 5 | Number, Money, MoneyCapital, Formula, FormulaDate |
| select | 6 | SingleSelect, MultipleSelect, Dropdown, Checkbox, Rating, Score |
| date | 3 | Date, DateTime, Time |
| contact | 4 | Phone, Landline, Email, Link |
| people | 3 | Collaborator, Department, OrgRole |
| relation | 5 | Relation, OtherTableField, SubTable, Cascade, Rollup |
| file | 2 | Attachment, Signature |
| location | 2 | Area, Location |
| advanced | 2 | QRCode, Embed |
| layout | 2 | Section, Remark |

### 待优化

- [ ] 部分字段缺少 `advancedSetting` 详细配置（如公式表达式、级联数据源）
- [ ] SubTable(34) 创建后需要配置子表字段
- [ ] OtherTableField(30) 和 Rollup(37) 需要关联字段存在才有意义
- [ ] 各字段的 `size/row/col` 布局参数未精细设置

### 关键文件

| 文件 | 职责 |
|------|------|
| `scripts/hap/worksheets/field_types.py` | 38 种字段注册中心 |
| `scripts/hap/planning/worksheet_planner.py` | 工作表+字段规划器 |
| `scripts/demo_all_field_types.py` | 验证脚本 |
| `scripts/record_field_types.py` | type 1-54 录制脚本 |

---

## 三、视图类型

### 测试链接
- **全视图演示**（同全字段表）: https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481/69ce832640691821042c6e79/69cf74eef9434db36c6e0816

### 实测结果: 11 种视图类型

| viewType | 名称 | 创建 | 二次保存 | 状态 |
|----------|------|------|---------|------|
| 0 | 表格 | ✓ | — | ✓ |
| 0 | 分组表格 | ✓ | groupView | ✓ |
| 1 | 看板 | ✓ | viewControl | ✓ |
| 2 | 层级 | ✓ | childType+layersControlId | ✓（需自关联字段） |
| 3 | 画廊 | ✓ | — | ✓ |
| 4 | 日历 | ✓ | calendarcids | ✓ |
| 5 | 甘特图 | ✓ | begindate+enddate | ✓ |
| 6 | 详情 | ✓ | — | ✓ |
| 7 | 地图 | ✓ | — | ✓ 待配置地理字段 |
| 8 | 快速 | ✓ | — | ✓ |
| 9 | 资源 | ✓ | — | ✓ 待配置成员+日期 |
| 10 | 自定义 | ✓ | — | ✓ 需插件 |

### 待优化

- [ ] 日历视图(4)的 calendarcids 配置需更精细（多日期字段场景）
- [ ] 地图视图(7)需配置 advancedSetting 指定地理字段
- [ ] 资源视图(9)需配置成员字段和日期字段映射
- [ ] 详情视图(6)的表单布局配置
- [ ] normalize_views() 需扩展支持 viewType 6-9 的自动补全

### 关键文件

| 文件 | 职责 |
|------|------|
| `scripts/hap/views/view_types.py` | 11 种视图注册中心 |
| `scripts/hap/planning/view_planner.py` | 视图规划器 |
| `scripts/hap/plan_worksheet_views_gemini.py` | 现有视图规划（待迁移到 planning/） |
| `scripts/hap/create_views_from_plan.py` | 视图创建执行层 |
| `scripts/demo_all_view_types.py` | 验证脚本 |

---

## 四、统计图表

### 测试链接
- **CRM 数据总览**（10 个图表）: https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481/69ce825c4e5c3d9aa799d979/69cf23ea0a5c9f9c3bdf1f16

### 实测通过的图表 (5 种)

| reportType | 名称 | 状态 |
|-----------|------|------|
| 1 | 柱状图 | ✓ |
| 2 | 折线图 | ✓ |
| 3 | 饼图 | ✓ |
| 5 | 漏斗图 | ✓ |
| 10 | 数值图 | ✓ |

### 待验证的图表 (12 种)

| reportType | 名称 | 注册中心文件 |
|-----------|------|-------------|
| 4 | 环形图 | pie.py |
| 6 | 雷达图 | radar.py |
| 7 | 条形图 | basic.py |
| 8 | 双轴图 | dual_axis.py |
| 9 | 散点图 | scatter.py |
| 11 | 区域图 | basic.py |
| 12 | 进度图 | number.py |
| 13 | 透视表 | table.py |
| 14 | 词云图 | special.py |
| 15 | 排行图 | special.py |
| 16 | 地图 | special.py |
| 17 | 关系图 | special.py |

### 关键修复记录

1. **Referer 必须包含 pageId** — `saveReportConfig` 的 Referer 需要 `app/{appId}/{pageId}`，否则图表不可渲染
2. **数值图 xaxes.controlId=null** — 不需要维度字段
3. **双轴图需 yreportType** — 默认第二轴为折线(2)

### 关键文件

| 文件 | 职责 |
|------|------|
| `scripts/hap/charts/` | 17 种图表注册中心（9 个模块） |
| `scripts/hap/planning/chart_planner.py` | 图表规划器 |
| `scripts/hap/create_charts_from_plan.py` | 图表创建执行层（已改为代理层） |
| `scripts/create_demo_charts.py` | 验证脚本 |

---

## 五、下一步优化方向

### P0：提高实测覆盖率
- [ ] 工作流：逐个验证剩余 19 种节点类型
- [ ] 图表：逐个验证剩余 12 种图表类型
- [ ] 字段：补全 advancedSetting 配置（公式、级联、子表）

### P1：规划层集成
- [ ] 将 planning/ 规划器集成到现有 pipeline（替换手写 prompt）
- [ ] worksheet_planner 替换 plan_app_worksheets_gemini.py
- [ ] view_planner 替换 plan_worksheet_views_gemini.py
- [ ] chart_planner 替换 plan_charts_gemini.py
- [ ] workflow_planner 替换 pipeline_workflows.py 的 build_prompt

### P2：端到端测试
- [ ] 跑一次完整 pipeline（run_app_pipeline.py）验证所有改动协同工作
- [ ] 对比改造前后的生成质量（节点数/配置完整度/publish 成功率）
