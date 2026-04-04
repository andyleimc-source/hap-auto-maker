# HANDOFF — 2026-04-05 四大待修问题

测试应用：**室内设计与装修公司管理平台**（app_id: b9aec84d-4bbb-4b53-acfd-a14db6b24db5）
分支：`feat/v2.0`

---

## 问题 1：分组命名问题

### 现象

分组名称正确（「客户营销」「项目管理」「施工交付」「财务核算」「基础设置」），
但有一个分组「数据分析」被规划出来却**没有任何工作表**（0张），实际上是空的。

```
[客户营销] 5张
[项目管理] 8张
[施工交付] 5张
[财务核算] 2张
[基础设置] 6张
[数据分析] 0张  ← 空分组，被创建出来但无内容
```

### 根因

`sections_plan` AI 规划时把「数据分析」列为分组，但没给它分配任何工作表。
创建空分组后，应用导航里会出现一个空的标签页，影响用户体验。

### 修复方向

- **方案 A**：sections 创建后自动跳过/删除空分组（`create_worksheets_from_plan.py`）
- **方案 B**：sections planner prompt 加规则：「禁止规划没有工作表的分组」
- 推荐 B + A 双保险

### 相关文件

- `scripts/hap/create_worksheets_from_plan.py`（sections 创建逻辑）
- `data/outputs/sections_plans/sections_plan_b9aec84d-4bbb-4b53-acfd-a14db6b24db5_20260404_222853.json`

---

## 问题 2：视图数量和类型问题

### 现象

本次 26 张工作表共 50 个视图，分布：

```
viewType 1 (表格): 16
viewType 2 (看板): 17
viewType 3 (层级): 1
viewType 4 (画廊): 5
viewType 5 (日历): 11
viewType 6 (甘特): 0  ← 装修公司有大量项目/工期，应该有甘特图
```

具体问题：

1. **每张表只有 1-2 个视图**，几乎全是「看板+表格」或「日历+表格」两件套，模式固化
2. **甘特图(6)完全没有**：项目、施工任务、合同等都有开始/结束日期，天然适合甘特
3. **表格视图无差异化**：多个表格视图仅名字不同，没有用 displayControls 展示不同字段集
4. **明细类表缺「按父记录分组」视图**：报价明细、施工日志等只有 1 个视图

### 根因

Phase 1 prompt（类型决策）已改为按业务语义判断，但对甘特图的触发条件描述不够强：
只说「需要开始+结束日期字段」，没有指出项目/计划/合同类表**应当主动考虑**甘特图。

### 修复方向

- Phase 1 prompt 补充：含「项目/施工/合同/计划/排期」语义且有两个日期字段的表，优先推荐甘特图
- Phase 2 prompt 补充：明细类表（名称含「明细/记录/日志」且有关联字段）应规划「按父记录分组」的表格视图
- 核心业务表视图数量建议 ≥ 3

### 相关文件

- `scripts/hap/planning/view_planner.py`（Phase 1 prompt 约 151 行，Phase 2 prompt 约 410 行）
- `data/outputs/view_plans/view_plan_b9aec84d-4bbb-4b53-acfd-a14db6b24db5_20260404_223027.json`

---

## 问题 3：工作流问题

### 现象

execute_workflow_plan 报告：**成功 30 / 31，失败 1**

失败的 1 个是 time_trigger：
```
TT: 每日晨会数据提醒 — invalid literal for int() with base 10: 'daily'
```

另外规划出的 worksheets 只有 11 张（实际 26 张），说明**15 张工作表完全没有工作流**。

### 根因

1. **time_trigger frequency 字段类型错误**：AI 输出了字符串 `"daily"`，
   但执行脚本期望整数（分钟数，如 `1440`），直接 `int("daily")` crash
2. **工作流覆盖不完整**：封顶截断后只保留了 11 张有 CA/EV 的表，另外 15 张完全没有 worksheet_event

### 修复方向

- `workflow/scripts/execute_workflow_plan.py`：对 `frequency` 做容错映射
  （`"daily"` → `1440`，`"hourly"` → `60`，`"weekly"` → `10080`；搜索关键词 `frequency`）
- `workflow/scripts/pipeline_workflows.py`：prompt 中要求所有工作表都必须有至少 1 个 worksheet_event，
  而不是只给部分表分配（目前的 `num_ca_ws` 只控制 CA 的覆盖面，EV 没有覆盖面约束）

### 相关文件

- `workflow/scripts/execute_workflow_plan.py`（搜索 `frequency` 或 `int(`）
- `workflow/scripts/pipeline_workflows.py`（`build_prompt()` 约 510 行）
- `workflow/logs/execute_workflow_plan_20260404_230818.json`

---

## 问题 4：统计图表问题

### 现象

本次统计图表成功了（上次 xaxes 修复的效果），但遗留两个问题：

1. **只创建了 2 个 Page**：26 张工作表只有「营销销售看板」和「项目经营看板」，
   财务/施工/质检/人员等业务模块没有统计页面
2. **跳过逻辑后遗症**：上次将校验失败的图表改为 warn+skip，
   可能导致某些 Page 里只剩 1-2 个图表，但 Page 仍被创建（当前没有最小图表数检查）

### 根因

Page 数量在 `pipeline_pages.py` 中固定规划为 2 个，没有按应用规模动态扩展。

### 修复方向

- `scripts/hap/pipeline_pages.py`：Page 数量按分组数动态计算
  （例：分组数 ≤ 3 时 2 个 Page，4-6 组时 3-4 个 Page，涵盖主要业务模块）
- `scripts/hap/create_pages_from_plan.py`：Page 最终图表数 < 3 时打印 warning
- `scripts/hap/plan_charts_gemini.py`：`validate_plan()` 中跳过图表后，
  如果剩余图表数 < 3，整体 raise 要求重试（而不是接受一个几乎空的 Page）

### 相关文件

- `scripts/hap/pipeline_pages.py`（`main()` 函数，Page 数量规划逻辑）
- `scripts/hap/plan_charts_gemini.py`（`validate_plan()`，约 347 行）
- `data/outputs/page_create_results/page_create_b9aec84d-4bbb-4b53-acfd-a14db6b24db5_pipeline.json`

---

## 本次对话已完成 ✅

- viewType=0 bug 修复（字符串→整数，验证函数拒绝 0）
- 视图类型 prompt 改为按业务语义判断（不再强制数量多样化）
- 工作流 AI 返回后硬性截断（上限 25，不含 date_triggers）
- 统计图校验失败改为 warn+skip（不再整体 raise）

## 当前分支状态

```
feat/v2.0  领先 main 33 个 commit
最新 commit: 34a9ebb  fix: 视图规划改为按业务语义选类型
```
