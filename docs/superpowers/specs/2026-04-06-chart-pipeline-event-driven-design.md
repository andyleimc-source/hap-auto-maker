# 统计图表创建流程重构 — 事件驱动方案

## Context

当前统计图表创建是"大一统"模式：Wave 4 一次 AI 调用规划所有 Pages → Wave 6 逐 Page 再调 AI 规划 8-12 个图表 → 批量创建。

**问题**：
- AI 调用多且 prompt 重（每个 Page 一次图表规划调用，prompt 含多张工作表全量字段）
- 必须等到 Wave 6 才开始做图表，Wave 3-5 的时间浪费了
- Pages 规划依赖所有工作表的字段信息，增加了前置数据拉取量

**目标**：改为事件驱动模式 — 每个工作表字段创建完成后，立即判断是否适合做图表并生成。减少 AI 调用次数、精简每次 prompt、图表创建与工作表创建流水线并行。

## 整体架构

```
Wave 2:    工作表规划 + 角色（不变）
Wave 2.5:  分组规划 + ★ Pages 规划与创建（新）
Wave 3:    创建工作表 → 每个工作表完成后 ★ 触发单表图表回调
Wave 4:    icon / 布局 / 视图 / 造数 / 机器人 / 工作流（去掉 step_14a）
Wave 5:    视图筛选 / 创建工作流（不变）
Wave 6:    删除默认视图（原 Wave 7，编号前移）
```

**AI 调用**：1 次（Pages 规划）+ N 次（每个工作表 1 次图表判断+规划，N=工作表数量）

## Phase 0：Pages 规划与创建

**时机**：Wave 2.5（分组规划之后、工作表创建之前）

**输入**：仅工作表名称列表（从 `worksheet_plan.json` 提取）

**流程**：
1. 从 worksheet plan 提取所有工作表名称
2. 一次 AI 调用 → 规划 Pages：每个 Page 的名称、说明、icon、颜色、关联的工作表名称
3. 调用 `AddWorkSheet` API 创建所有 Page
4. 调用 `savePage` 初始化每个 Page（version=0, components=[]）
5. 输出 `page_registry.json`

**关键文件**：
- 新建 `scripts/hap/planning/page_planner.py`
- 新建 `scripts/hap/executors/create_pages_early.py`
- 修改 `scripts/hap/pipeline/waves.py`
- 修改 `scripts/hap/pipeline/context.py`

**page_registry.json 结构**：
```json
{
  "appId": "xxx",
  "pages": [
    {
      "pageId": "actual_page_id_from_api",
      "name": "销售分析",
      "desc": "销售业绩与趋势分析",
      "worksheetNames": ["销售订单", "客户信息"],
      "components": [],
      "version": 0
    }
  ]
}
```

## Phase 1：工作表完成回调

**时机**：`create_worksheets_from_plan.py` 中每个工作表的非 Relation 字段全部创建成功后

**回调签名**：
```python
def on_worksheet_ready(
    worksheet_id: str,
    worksheet_name: str,
    fields: list[dict],
    page_registry: dict,
    auth_config_path: Path,
    gemini_semaphore: Semaphore,
) -> dict | None:
```

**关键文件**：
- 修改 `scripts/hap/executors/create_worksheets_from_plan.py`（新增 `--page-registry` 参数，创建完字段后调用回调）

## Phase 2：单表图表规划+创建

**触发**：由 Phase 1 回调触发，在工作表创建线程内串行执行

**流程**：
1. 查 `page_registry`，按工作表名称找到目标 Page
2. 若未匹配 → 跳过
3. 一次 AI 调用（轻量 prompt）→ 判断适配性 + 输出 1-3 个图表配置
4. 若不适合 → 跳过
5. 调用 `build_report_body()` → `saveReportConfig` 创建图表
6. 追加到目标 Page → `savePage` 更新

**savePage 并发控制**：
- `page_registry` 中维护每个 Page 的 `components` 数组和 `version`
- 使用线程锁保护同一个 Page 的并发写入

**关键文件**：
- 新建 `scripts/hap/planning/single_ws_chart_planner.py`
- 新建 `scripts/hap/executors/create_single_ws_charts.py`

**复用**：
- `charts/__init__.py` 的 `CHART_REGISTRY`, `build_report_body()`
- `charts/_base.py` 的 `base_display_setup()`, `build_xaxes()`
- `planning/constraints.py` 的 `classify_fields()`, `build_chart_type_prompt_section()`
- `charts/chart_config_schema.py` 的 `get_ai_prompt_section()`

**单表 prompt 模板**：
```
你是数据分析师。判断下面的工作表是否适合制作统计图表。

工作表: {worksheet_name}
字段列表:
{fields_json}

{chart_type_guide}

要求:
1. 如果该表不适合做统计图（如纯配置表、关联表等），返回 suitable=false
2. 如果适合，输出 1-3 个图表配置，类型(reportType)不重复
3. 每个图表需指定: reportType, name, xaxes(维度字段), yaxisList(指标字段)

输出 JSON:
{"suitable": true/false, "reason": "简短原因", "charts": [...]}
```

## waves.py 改动

- **删除** `run_step_14a()` 和 Wave 6 Step 14
- **新增** Wave 2.5 中 Pages 创建步骤
- **修改** `create_worksheets_from_plan.py` 命令行参数

## 可删除的旧文件

- `scripts/hap/planners/plan_pages_gemini.py`
- `scripts/hap/planners/plan_charts_gemini.py`
- `scripts/hap/executors/create_pages_from_plan.py`
- `scripts/hap/executors/create_charts_from_plan.py`
- `scripts/hap/pipeline_charts.py`
- `scripts/hap/pipeline_pages.py`

## 验证方案

1. 对 `page_planner.py` 和 `single_ws_chart_planner.py` 的 validate 函数编写单元测试
2. `python3 make_app.py --requirements "..." --no-execute` 确认 spec 生成正常
3. 端到端测试：Pages 在 Wave 2.5 创建、图表回调触发、图表追加到 Page、不适合的表被跳过
4. 对比验证：同一需求跑新旧 pipeline，对比图表数量和质量
