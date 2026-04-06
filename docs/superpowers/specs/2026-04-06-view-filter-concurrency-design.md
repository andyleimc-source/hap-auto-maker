# 视图筛选环节并发优化设计

## 背景

当前视图筛选环节（Step 9）耗时 251s，是主 pipeline 第三大瓶颈。

### 现状拆解

| 子步骤 | 耗时 | 原因 |
|--------|-----:|------|
| Step 1/2 规划（fetch + AI） | ~230s | 40张表全量打包成单次 AI 调用（~60-80KB prompt） |
| Step 2/2 应用（SaveWorksheetView × N） | ~20s | 已有 ThreadPoolExecutor(16) 并发 |
| **合计** | **~251s** | |

根本问题：**40张表的所有视图和字段全量打包成一次 Gemini 调用**（`build_batch_filter_prompt`），prompt 巨大，响应慢约 200s。

与布局环节（Step 5）的老问题完全相同。

---

## 设计目标

将视图筛选环节从 **251s → 预计 20-40s**，通过 40 张表并发执行实现。

---

## 方案：新建 `pipeline_tableview_filters_v2.py`

### 核心变化

1. **合并规划+应用**：每张表在同一 worker 内串行执行 `fetch_views → fetch_controls → AI规划 → SaveWorksheetView`，消除中间 plan 文件
2. **40 张表并发**：用 `ThreadPoolExecutor` 并发处理，受全局 `gemini_semaphore` 控制
3. **不输出中间 plan JSON**：只写最终 apply result（简化，调试时看 result 即可）
4. **删除旧脚本**：`pipeline_tableview_filters.py`、`planners/plan_tableview_filters_gemini.py`、`executors/apply_tableview_filters_from_plan.py` 全部删除

### 执行流程

```
pipeline_tableview_filters_v2.py
│
├── 1. fetch_app_structure（1次 GET /v3/app）→ 获得工作表列表
│
├── 2. ThreadPoolExecutor（并发数 = semaphore_value）
│    └── 每张表的 worker（并发执行）：
│         ├── fetch_worksheet_views(ws_id)          # GET 工作表视图列表，注入默认"全部"视图
│         ├── fetch_controls(ws_id)                 # GET GetWorksheetControls
│         ├── with semaphore: AI规划(当表视图+字段)  # Gemini 调用
│         └── SaveWorksheetView × N（并发内层）      # POST 保存各视图
│
└── 3. 汇总结果，写 tableview_filter_result_{app_id}_{ts}.json
```

### Prompt 结构

每张表独立 prompt，使用现有 `build_prompt`（per-worksheet 版本）而非 `build_batch_filter_prompt`：

```
应用：{app_name}
工作表：{worksheet_name}
worksheetId：{worksheet_id}
目标视图：[{viewId, viewName, viewType}, ...]
字段：[{id, name, type, isDropdown, ...}, ...]

请规划每个视图的 navGroup / fastFilters / color / group，输出 JSON。
```

### 输出产物

- `data/outputs/tableview_filter_results/tableview_filter_result_{app_id}_{ts}.json`
- `data/outputs/tableview_filter_results/tableview_filter_result_latest.json`

格式：
```json
{
  "app": {"appId": "...", "appName": "..."},
  "worksheetCount": 40,
  "totalViews": 160,
  "totalSaved": 155,
  "worksheets": [
    {
      "workSheetId": "...",
      "workSheetName": "...",
      "viewCount": 4,
      "savedCount": 4,
      "ok": true,
      "error": null
    }
  ]
}
```

### waves.py / context.py 变更

- `scripts["view_filters"]` 指向新脚本 `pipeline_tableview_filters_v2.py`
- `run_step_9` 新增传参 `--semaphore-value {sem_value}`，传入 `--dry-run`
- `context.py`：移除 `tableview_filter_plan_json`、`tableview_filter_apply_result_json`，新增 `tableview_filter_result_json`
- `waves.py` 中读取 artifact 由两个字段合并为一个

### 删除文件清单

| 文件 | 原职责 |
|------|--------|
| `scripts/hap/pipeline_tableview_filters.py` | 两步串行入口 |
| `scripts/hap/planners/plan_tableview_filters_gemini.py` | AI 批量规划（单次全量） |
| `scripts/hap/executors/apply_tableview_filters_from_plan.py` | 串行读 plan + 并发应用 |

### 错误处理

- 单张表 worker 失败（fetch/AI/Save 任一步骤）：记录 error，不影响其他表继续执行
- 所有表处理完后，若有失败表，打印警告但不退出

---

## 预期效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| AI 调用次数 | 1次（40表全量） | 40次（每表并发） |
| 单次 AI 耗时 | ~200s | ~3-5s |
| fetch_controls 次数 | 40次（串行） | 40次（并发） |
| 总耗时 | ~251s | ~20-40s（受最慢单表限制） |
