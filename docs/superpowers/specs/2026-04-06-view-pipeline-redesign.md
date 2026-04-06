# 视图创建流程重新设计

## 问题

当前视图创建流程存在 4 个问题：

1. **prompt 太大**：Phase 1 一次传所有表的字段摘要给 AI，表越多 prompt 越长，AI 注意力分散
2. **等待浪费**：视图在 Wave 4，必须等 Wave 3 所有工作表字段创建完才开始。单表字段就绪后闲置等待
3. **删除默认视图不合理**：系统自动创建的"全部"视图被直接删除（Wave 7），浪费了一个可以改造利用的视图位
4. **批量规划+批量创建**：所有表的视图全部规划完才开始创建，不是"规划一个创建一个"

## 设计

### 核心理念：单表完成字段后立即处理该表视图

每张工作表字段创建完成后，立即触发该表的视图任务，不等其他表。

### 单表视图任务流程

```
对每张工作表（字段创建完成后立即触发）：
  1. 拉取该表真实字段（GetWorksheetControls API）
  2. AI 规划该表的视图列表（1 次 AI 调用，只含这一张表）
     - 输出包含：默认视图改造方案 + 新建视图列表
  3. 改造默认"全部"视图（SaveWorksheetView API，传入已有 viewId）
     - 改名为有业务含义的名称（如"按状态分组"）
     - 设置 displayControls、groupsetting 等配置
  4. 逐个创建额外视图（看板/日历/甘特图等）
     - 每创建一个，立刻做 postCreateUpdates（二次保存高级配置）
  5. 视图筛选（对表格视图加筛选条件）
```

### AI Prompt 设计

每次 AI 调用只为一张表规划视图，prompt 包含：
- 工作表名称 + 用途
- 该表的真实字段列表（controlId、type、options）
- 该表已有的默认视图信息（名称"全部"、viewId）
- 视图类型规则（从 VIEW_REGISTRY 自动生成）
- `suggest_views()` 的推荐结果（根据字段类型预判适合的视图）

AI 输出格式：
```json
{
  "default_view_update": {
    "name": "按状态分组",
    "displayControls": ["字段ID1", "字段ID2"],
    "advancedSetting": {"groupsetting": "[...]"}
  },
  "new_views": [
    {
      "name": "销售看板",
      "viewType": 1,
      "viewControl": "单选字段ID",
      "displayControls": ["..."],
      "postCreateUpdates": [...]
    }
  ]
}
```

预计 prompt < 1000 token/表。不分 Phase1/Phase2，单次调用直接输出完整配置。

### Pipeline 集成

改造前：
```
Wave 3: 创建所有工作表（等全部完成）
Wave 4: Step 6 视图规划+创建（等全部完成）
Wave 5: Step 7 视图筛选
Wave 7: Step 13 删除默认视图
```

改造后：
```
Wave 3: 创建工作表 + 追加字段（逐表）
  ↓ 每张表字段完成后，立即提交该表的视图任务到线程池

视图任务（与其他表的字段创建并行执行）：
  1. 拉取真实字段
  2. AI 规划视图（单表单次调用）
  3. 改造默认视图
  4. 创建新视图 + postCreateUpdates
  5. 视图筛选

Wave 7: 移除（不再需要删除默认视图）
```

并发控制：
- 多张表的视图任务并行，用 `gemini_semaphore` 控制 AI 调用并发
- 同一张表内的多个视图串行创建

### 错误处理

- 某张表的视图 AI 规划失败 → 记录错误，跳过该表视图，其他表继续
- 某个视图创建 API 失败 → 记录错误，继续创建该表的下一个视图
- 默认视图改造失败 → 降级为保留原"全部"视图不动，继续创建新视图
- AI 调用：复用现有 `generate_with_retry`（3 次网络重试）+ 校验失败重试 2 次
- 输出仍汇总到 `view_create_result_*.json`，格式兼容，下游不受影响

## 关键文件

- `scripts/hap/planning/view_planner.py` — 新增单表视图规划 prompt（含默认视图改造）
- `scripts/hap/planners/plan_worksheet_views_gemini.py` — 新增 `plan_and_create_views_for_ws()` 单表规划+创建函数
- `scripts/hap/executors/create_views_from_plan.py` — 新增默认视图改造逻辑（update 而非 delete+create）
- `scripts/hap/pipeline/waves.py` — Wave 3 触发视图任务、移除 Wave 7
- `scripts/hap/delete_default_views.py` — 不再被 pipeline 调用（保留文件但不执行）

## 复用的现有代码

- `view_planner.suggest_views()` — 字段类型→视图推荐
- `view_planner.build_view_type_prompt_section()` — 视图类型规则生成
- `planning/constraints.classify_fields()` — 字段分类
- `create_views_from_plan.auto_complete_post_updates()` — 自动补全 postCreateUpdates
- `create_views_from_plan.merge_post_updates()` — 合并 AI 和自动补全的配置
- `create_views_from_plan.build_create_payload()` — 构建创建请求
- `create_views_from_plan.build_update_payload()` — 构建更新请求
- `create_views_from_plan.normalize_advanced_setting()` — 规范化 advancedSetting
- `plan_worksheet_views_gemini.normalize_views()` — 视图后处理（字段校验、自动补全）

## 验证

1. 对一个应用运行新流程，检查：
   - 默认视图被成功改造（名称有业务含义、有配置）
   - 新视图创建成功（看板/日历/甘特图等，取决于字段类型）
   - postCreateUpdates 正确执行
2. 检查 `view_create_result_*.json` 格式与现有兼容
3. 确认 Wave 3 中单表完成字段后视图任务确实立即启动（不等其他表）
4. 确认失败的表不影响其他表的视图创建
