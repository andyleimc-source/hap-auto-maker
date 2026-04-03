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

## 一、工作流节点

### 测试链接
- **全节点展示**: https://www.mingdao.com/workflowedit/69cf487e9b08efb4c5bb8bca
- **订单发货流程**: https://www.mingdao.com/workflowedit/69cf46ba8f9e70c865431131

### 实测通过的节点 (8 种)

| 节点 | typeId | 创建 | 配置完整 | Publish | 关键发现 |
|------|--------|------|----------|---------|----------|
| 更新记录 | 6/2 | ✓ | ✓ | ✓ | 单选字段需完整 UUID key |
| 新增记录(同表) | 6/1 | ✓ | ✓ | ✓ | |
| 获取单条数据 | 6/4 | ✓ | ✓ | ✓ | |
| 数值运算 | 9/100 | ✓ | ✓ | ✓ | |
| 延时 | 12/301 | ✓ | ✓ | ✓ | 值在根级别非 timerNode |
| 站内通知 | 27 | ✓ | ✓ | ✓ | **用 sendContent 非 content** |
| 抄送 | 5 | ✓ | ✓ | ✓ | **用 sendContent 非 content** |
| 审批 | 26 | ✓ | ⚠ | ✗ | 创建成功但 publish 报 103 |

### 待验证的节点 (19 种)

| 节点 | 注册中心文件 | 状态 |
|------|-------------|------|
| 新增记录(跨表) | record_ops.py | 关联字段引用格式未解决 |
| 删除记录 | record_ops.py | 需要 filters |
| 查询工作表 | record_ops.py | typeId=13 |
| 校准记录 | record_ops.py | 需要 errorFields |
| 填写 | human.py | 需要 formProperties |
| 短信/邮件/推送 | notify.py | |
| 延时到日期/字段 | timer.py | actionId=302/303 |
| 汇总 | compute.py | 需要 appId |
| 分支 | flow_control.py | 需 operateCondition |
| 循环/中止/子流程 | flow_control.py | |
| JSON解析/代码块/API | developer.py | |
| AI文本/对象/Agent | ai.py | |

### 关键修复记录

1. **`sendContent` 非 `content`** — 通知(27)和推送(17)的内容字段是 `sendContent`，短信(10)和邮件(11)用 `content`
2. **延时值在根级别** — `numberFieldValue` 等直接放 saveNode body，不嵌套 `timerNode`
3. **单选字段需完整 UUID** — 截断 key 被 HAP 静默丢弃，必须传完整 UUID
4. **审批节点 publish 失败** — 需研究 processNode 子流程配置

### 关键文件

| 文件 | 职责 |
|------|------|
| `workflow/nodes/` | 27 种节点注册中心（9 个模块） |
| `workflow/scripts/add_workflow_node.py` | 兼容层，代理到 nodes/ |
| `workflow/scripts/execute_workflow_plan.py` | 节点创建+publish |
| `scripts/create_demo_workflow_v2.py` | 验证脚本（订单流程） |
| `scripts/create_demo_workflow_full.py` | 验证脚本（全节点） |

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
