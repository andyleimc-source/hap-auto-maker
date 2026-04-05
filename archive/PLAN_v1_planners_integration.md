# PLAN.md — HAP Auto Maker 项目计划

> 本文件为本地开发文档，不提交到 git。

---

## 四大规划师重构

> 这是项目当前最核心的任务。目标：用注册中心驱动的规划师替换现有的手写 prompt 脚本，提升规划质量和可维护性。

### 现状

| 规划师 | 模块文件 | 状态 | 待替换的旧脚本 |
|--------|---------|------|--------------|
| worksheet_planner | `scripts/hap/planning/worksheet_planner.py` | ✅ 模块已实现 | `plan_app_worksheets_gemini.py`（Wave 2） |
| view_planner | `scripts/hap/planning/view_planner.py` | ✅ 模块已实现 | `plan_worksheet_views_gemini.py`（Wave 4C） |
| chart_planner | `scripts/hap/planning/chart_planner.py` | ✅ 模块已实现 | `plan_charts_gemini.py`（Wave 6） |
| workflow_planner | `scripts/hap/planning/workflow_planner.py` | ✅ 模块已实现 | `pipeline_workflows.py` 的 `build_prompt` 部分（Wave 4F） |

所有四个规划师**模块已写完，但尚未集成到 pipeline**。

### 每个规划师的能力（vs 旧脚本）

**worksheet_planner**
- 字段类型从 `FIELD_REGISTRY` 自动生成（旧：手写 9 种枚举）
- 校验增加：关联目标存在性、option_values 完整性
- 自动修复：creation_order 补全（旧脚本也有，但逻辑分散）

**view_planner**
- 视图类型约束从 `VIEW_REGISTRY` 自动生成
- 根据字段分类智能推荐（有日期→日历/甘特图，有单选→看板）
- 配置生成集中管理（二次保存参数自动补全）

**chart_planner**
- 从 `CHART_REGISTRY` 元数据指导 AI 选型
- 字段分类后给 AI 更精准推荐
- 校验增加字段类型兼容性检查

**workflow_planner**
- 节点类型从 `NODE_REGISTRY` 自动生成（只推荐已验证节点）
- 内置约束：禁止未验证节点、强制正确参数格式
- 校验：节点类型合法性、字段引用、跨表检查

### 集成步骤（按优先级）

**P0：worksheet_planner 集成（影响最大）**
- [x] 在 `scripts/gemini/plan_app_worksheets_gemini.py` 中 import `worksheet_planner`，替换手写 prompt 构建逻辑（改用 `build_enhanced_prompt`）
- [x] 用 `worksheet_planner.validate_worksheet_plan()` 替换现有 validate_plan()
- [x] 加 log：prompt 长度+前200字、AI 原始 JSON 写文件、validate errors 列表
- [ ] 跑一次 pipeline 验证输出 JSON 结构不变

**P1：workflow_planner 集成**
- [x] 修复 `workflow/nodes/timer.py`：actionId=302/303 改为 timerNode 嵌套结构（已完成）
- [x] 在 `pipeline_workflows.py` 中替换 `build_prompt()` 函数（改用 workflow_planner 两阶段）
- [x] 确保输出 JSON 格式兼容 `execute_workflow_plan.py` 输入
- [x] 加 log：prompt 长度+前200字、AI 原始 JSON 写文件、validate errors 列表

**P2：view_planner + chart_planner 集成**
- [x] `plan_worksheet_views_gemini.py`：在 `build_prompt()` 内注入 `view_planner` 的注册中心类型说明 + 字段分类推荐（兜底降级）
- [x] `plan_charts_gemini.py`：非 system_fields_only 路径改用 `chart_planner.build_enhanced_prompt()`，加 log
- [x] 加 log：prompt 长度+前200字（view 侧已加）
- [x] view_planner 两阶段完整集成（plan_views_two_phase 已实现）

### 验收标准

- 跑完整 `python3 run_app_pipeline.py` 一次，输出工作表数/视图数/图表数/工作流数与改造前持平或更优
- 规划 JSON 中不再出现未注册的字段类型/节点类型
- timer.py 修复后，延时到日期/字段节点可正常 publish

---

## 已知风险.

| 风险 | 说明 | 缓解 |
|------|------|------|
| AI 输出结构不稳定 | 大工作表数量时 AI 容易漏字段或漏 creation_order | repair_plan + 重试机制 |
| HAP 前端接口变动 | 部分功能依赖浏览器内部接口 | 定期回归测试 |
| Playwright 登录失效 | Cookie 过期导致造数失败 | `auth/refresh_auth.py` 刷新 |
| 并发限制 | `Semaphore(3)` 控制并行数，超出可能被 API 限流 | 调整 semaphore 值 |
