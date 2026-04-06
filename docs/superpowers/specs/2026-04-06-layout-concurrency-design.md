# 布局环节并发优化设计

## 背景

当前布局环节（Step 5）耗时 279s，是主 pipeline 第二大瓶颈。

### 现状拆解

| 子步骤 | 耗时 | 原因 |
|--------|-----:|------|
| Step 1/2 规划（fetch + AI） | 258s | 568 字段塞进单次 AI 调用（~83KB prompt） |
| Step 2/2 应用（Get + Save） | 21s | 40 张表串行 |
| **合计** | **279s** | |

根本问题：**所有工作表的字段全量打包成一次 AI 调用**，prompt 巨大，响应慢约 230s。

### 约束条件

- 模型：gemini-2.5-flash（付费账号）
- 限速：RPD=100K，RPM=2000，TPM=3M
- 并发控制：复用全局 `gemini_semaphore`（默认改为 1000，实际由 Gemini RPM 自然限流）

---

## 设计目标

将布局环节从 **279s → 预计 30-50s**，通过 40 张表并发执行实现。

---

## 方案：新建 `pipeline_worksheet_layout_v2.py`

### 核心变化

1. **合并规划+应用**：每张表在同一线程内串行执行 `fetch_controls → AI规划 → SaveWorksheetControls`，消除第二次 fetch（原来规划和应用各 fetch 一次，共 80 次，现在只需 40 次）
2. **40 张表并发**：用 `ThreadPoolExecutor` 并发处理，受全局 `gemini_semaphore` 控制
3. **全局上下文注入**：每张表的 prompt 包含应用名 + 所有表名列表，保证跨表布局一致性，但 fields 只含当张表字段
4. **旧脚本删除**：`plan_worksheet_layout.py`、`apply_worksheet_layout.py`、`pipeline_worksheet_layout.py` 全部删除

### 执行流程

```
pipeline_worksheet_layout_v2.py
│
├── 1. 拉取应用结构（1次 GET /v3/app）→ 获得 40 张表列表 + 全局上下文
│
├── 2. ThreadPoolExecutor（最大并发 = gemini_semaphore 值）
│    │
│    └── 每张表的 worker（并发执行）：
│         ├── fetch_controls(worksheet_id)         # GET GetWorksheetControls
│         ├── with semaphore: AI规划(当表字段)      # Gemini 调用
│         └── SaveWorksheetControls(new_controls)  # POST 保存
│
├── 3. 汇总结果，写 layout_result_*.json
└── 4. 打印摘要
```

### Prompt 结构

```
应用名：{app_name}
所有工作表：[表1, 表2, ..., 表40]（仅名称，供上下文参考）

当前工作表：{ws_name}
字段数据：[{controlId, controlName, type, current: {size,row,col}}, ...]

请规划每个字段的 size/row/col，输出 JSON。
硬性约束：size ∈ {12,6,4,3}，col 与 size 匹配，row 从 0 开始。
```

### 输出产物

- `data/outputs/worksheet_layout_results/layout_result_{app_id}_{ts}.json`
- `data/outputs/worksheet_layout_results/layout_result_latest.json`

格式：
```json
{
  "app": {"appId": "...", "appName": "..."},
  "worksheetCount": 40,
  "totalFields": 568,
  "totalChanged": 512,
  "worksheets": [
    {
      "workSheetId": "...",
      "workSheetName": "...",
      "fieldsChanged": 13,
      "ok": true,
      "error": null
    }
  ]
}
```

### waves.py 变更

- Step 5 的 `scripts["layout"]` 指向新脚本
- 传参新增 `--gemini-semaphore-value`（从全局 semaphore 读取并发数传入，或直接用环境变量/命令行参数）
- `script_locator.py` 注册新脚本路径

### 删除文件清单

| 文件 | 原职责 |
|------|--------|
| `scripts/hap/planners/plan_worksheet_layout.py` | AI 规划（单次全量） |
| `scripts/hap/executors/apply_worksheet_layout.py` | 串行应用布局 |
| `scripts/hap/pipeline_worksheet_layout.py` | 两步串行流水线入口 |

### 错误处理

- 单张表 worker 失败（fetch/AI/Save 任一步骤）：记录 error，不影响其他表继续执行
- 所有表处理完后，若有失败表，打印警告但不退出（返回码由调用方决定是否 fail_fast）

---

## 预期效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| AI 调用次数 | 1次（568字段） | 40次（每表约14字段） |
| 单次 AI 耗时 | ~230s | ~3-5s |
| fetch_controls 次数 | 80次（串行） | 40次（并发） |
| 总耗时 | ~279s | ~30-50s（受最慢单表限制） |
