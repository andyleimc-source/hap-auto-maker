# hap_auto

项目目标：自动化完成 HAP 应用从创建到造数的全链路，包括应用创建、工作表规划、字段布局、图标匹配、测试数据生成与一致性修正。

## 1. 目录与分层

1. 入口脚本层（建议直接运行）
- `/Users/andy/Desktop/hap_auto/scripts/`
- 这些脚本通过 `runpy` 转发到实现层，参数接口稳定，适合日常使用。

2. 实现脚本层
- HAP 业务实现：`/Users/andy/Desktop/hap_auto/scripts/hap/`
- Gemini 业务实现：`/Users/andy/Desktop/hap_auto/scripts/gemini/`
- 认证脚本：`/Users/andy/Desktop/hap_auto/scripts/auth/`

3. 数据与结果目录
- `/Users/andy/Desktop/hap_auto/data/outputs/`

## 2. 快速开始

先进入项目目录：

```bash
cd /Users/andy/Desktop/hap_auto
```

### 2.1 一键主流程（需求驱动）

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/agent_collect_requirements.py
```

说明：
- 在终端与 Gemini 对话，输入 `/done` 后生成需求 JSON。
- 默认会调用执行器按需求执行全流程（可通过参数关闭自动执行）。

### 2.2 执行已有需求 JSON

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/execute_requirements.py \
  --spec-json /Users/andy/Desktop/hap_auto/data/outputs/requirement_specs/requirement_spec_latest.json
```

## 3. 标准 Pipeline（按场景拆分）

### 3.1 创建应用流水线

流程：创建应用 -> 获取授权 -> 匹配应用 icon -> 更新应用 icon

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_app.py --name "医院后勤管理系统"
```

### 3.2 工作表流水线

流程：规划工作表 -> 创建工作表 -> 匹配并更新工作表 icon

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheets.py
```

### 3.3 字段布局流水线

流程：选择应用 -> 规划字段布局 -> 应用布局

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheet_layout.py \
  --app-id <你的appId> \
  --requirements "按业务角色优化表单布局"
```

### 3.4 造数流水线（重点）

当前造数流程：
1. 选应用/选表
2. （可选）删除历史记录
3. 拉取字段结构
4. 决定每张表造数数量（`fixed` 或 `auto`）
5. 生成基础记录（非关联字段）
6. 批量写入基础记录
7. 生成关系上下文并规划关联映射
8. 回填关联字段
9. 父子运算一致性修正（可跳过）

交互式运行：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py
```

非交互（自动按表性质分析数量）：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py \
  --app-id <你的appId> \
  --worksheet-ids all \
  --row-count-mode auto \
  --delete-history n
```

非交互（固定每表数量）：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py \
  --app-id <你的appId> \
  --worksheet-ids all \
  --row-count-mode fixed \
  --rows-per-table 3 \
  --delete-history n
```

### 3.5 工作表 icon 流水线

流程：拉清单 -> Gemini 匹配 icon -> 批量更新

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_icon.py \
  --app-auth-json /Users/andy/Desktop/hap_auto/data/outputs/app_authorizations/app_authorize_<你的appId>.json \
  --app-id <你的appId>
```

## 4. 全流程脚本顺序与作用（完整）

说明：`/scripts/*.py` 基本都是稳定入口（代理转发），真实实现在 `/scripts/hap/`、`/scripts/gemini/`、`/scripts/auth/`。

### 4.1 入口代理脚本（出现顺序按目录）

1. `scripts/agent_collect_requirements.py` -> 转发到 `scripts/hap/agent_collect_requirements.py`（需求对话）
2. `scripts/apply_worksheet_layout.py` -> `scripts/hap/apply_worksheet_layout.py`（应用布局）
3. `scripts/create_app.py` -> `scripts/hap/create_app.py`（创建应用）
4. `scripts/create_worksheets_from_plan.py` -> `scripts/hap/create_worksheets_from_plan.py`（按规划建表）
5. `scripts/delete_app.py` -> `scripts/hap/delete_app.py`（删除应用）
6. `scripts/enforce_parent_child_consistency.py` -> `scripts/hap/enforce_parent_child_consistency.py`（父子一致性修正）
7. `scripts/execute_requirements.py` -> `scripts/hap/execute_requirements.py`（需求执行器）
8. `scripts/get_app_authorize.py` -> `scripts/hap/get_app_authorize.py`（获取授权）
9. `scripts/list_app_worksheets.py` -> `scripts/hap/list_app_worksheets.py`（工作表清单）
10. `scripts/list_apps_for_icon.py` -> `scripts/hap/list_apps_for_icon.py`（应用清单）
11. `scripts/list_gemini_models.py` -> `scripts/gemini/list_gemini_models.py`（模型列表）
12. `scripts/match_app_icons_gemini.py` -> `scripts/gemini/match_app_icons_gemini.py`（应用 icon 匹配）
13. `scripts/match_worksheet_icons_gemini.py` -> `scripts/gemini/match_worksheet_icons_gemini.py`（工作表 icon 匹配）
14. `scripts/pipeline_create_app.py` -> `scripts/hap/pipeline_create_app.py`（创建应用流水线）
15. `scripts/pipeline_create_rows.py` -> `scripts/hap/pipeline_create_rows.py`（造数流水线）
16. `scripts/pipeline_icon.py` -> `scripts/hap/pipeline_icon.py`（工作表 icon 流水线）
17. `scripts/pipeline_worksheet_layout.py` -> `scripts/hap/pipeline_worksheet_layout.py`（布局流水线）
18. `scripts/pipeline_worksheets.py` -> `scripts/hap/pipeline_worksheets.py`（工作表流水线）
19. `scripts/plan_app_worksheets_gemini.py` -> `scripts/gemini/plan_app_worksheets_gemini.py`（工作表规划）
20. `scripts/plan_parent_child_constraints_gemini.py` -> `scripts/gemini/plan_parent_child_constraints_gemini.py`（父子约束规划）
21. `scripts/plan_row_relation_links_gemini.py` -> `scripts/gemini/plan_row_relation_links_gemini.py`（关系映射规划）
22. `scripts/plan_row_seed_counts_gemini.py` -> `scripts/gemini/plan_row_seed_counts_gemini.py`（造数数量规划）
23. `scripts/plan_worksheet_layout.py` -> `scripts/hap/plan_worksheet_layout.py`（布局规划）
24. `scripts/refresh_auth.py` -> `scripts/auth/refresh_auth.py`（刷新网页登录认证）
25. `scripts/update_app_icons.py` -> `scripts/hap/update_app_icons.py`（更新应用 icon）
26. `scripts/update_app_navi_style.py` -> `scripts/hap/update_app_navi_style.py`（更新导航风格）
27. `scripts/update_worksheet_icons.py` -> `scripts/hap/update_worksheet_icons.py`（更新工作表 icon）

### 4.2 需求驱动总编排顺序（`execute_requirements.py`）

1. `pipeline_create_app.py`：创建应用 + 授权 + 应用 icon
2. `pipeline_worksheets.py`：工作表规划/建表/icon
3. （可选）`update_worksheet_icons.py`：工作表 icon 更新（编排内第3步）
4. `pipeline_worksheet_layout.py`：字段布局规划与应用
5. `update_app_navi_style.py`：应用导航风格
6. `pipeline_create_rows.py`：造数、关联回填、父子一致性修正

### 4.3 各流水线内部顺序与作用

1. `pipeline_create_app.py`
- Step 1/5 `create_app.py`：创建应用
- Step 2/5 `get_app_authorize.py`：保存应用授权文件
- Step 3/5 `list_apps_for_icon.py`：生成应用名称清单
- Step 4/5 `match_app_icons_gemini.py`：Gemini 生成 icon 匹配方案
- Step 5/5 `update_app_icons.py`：落地更新 icon

2. `pipeline_worksheets.py`
- Step 1/3 `plan_app_worksheets_gemini.py`：生成工作表规划 JSON
- Step 2/3 `create_worksheets_from_plan.py`：创建工作表与关系字段
- Step 3/3 `pipeline_icon.py`：对工作表执行 icon 流程

3. `pipeline_icon.py`
- Step 1/3 `list_app_worksheets.py`：拉工作表清单
- Step 2/3 `match_worksheet_icons_gemini.py`：生成工作表 icon 匹配方案
- Step 3/3 `update_worksheet_icons.py`：批量更新工作表 icon

4. `pipeline_worksheet_layout.py`
- Step 1/2 `plan_worksheet_layout.py`：布局规划
- Step 2/2 `apply_worksheet_layout.py`：布局应用

5. `pipeline_create_rows.py`
- Step 1-2：选应用/选表 + 可选删除历史记录
- Step 3：读取工作表字段结构并拆分基础字段/关联字段
- Step 4：数量决策  
  `fixed`：直接用 `rows-per-table`  
  `auto`：`plan_row_seed_counts_gemini.py` 规划，失败则本地 fallback
- Step 5：Gemini 生成基础记录（不含关联字段）
- Step 6A：按依赖拓扑批量写入基础记录
- Step 6B：构建 rowId 池（新建 + 现有）
- Step 6C：`plan_row_relation_links_gemini.py` 规划关联映射（失败回退索引策略）
- Step 6D：批量 patch 回填关联字段
- Step 6E：`enforce_parent_child_consistency.py` 执行父子运算一致性修正（可 `--skip-consistency`）

### 4.4 底层实现脚本（按职责）

1. 应用：`create_app.py`、`get_app_authorize.py`、`list_apps_for_icon.py`、`update_app_icons.py`、`update_app_navi_style.py`、`delete_app.py`
2. 工作表：`plan_app_worksheets_gemini.py`、`create_worksheets_from_plan.py`、`list_app_worksheets.py`、`update_worksheet_icons.py`
3. 布局：`plan_worksheet_layout.py`、`apply_worksheet_layout.py`
4. 造数：`pipeline_create_rows.py`、`plan_row_seed_counts_gemini.py`、`plan_row_relation_links_gemini.py`
5. 一致性：`plan_parent_child_constraints_gemini.py`、`enforce_parent_child_consistency.py`
6. 认证与辅助：`auth/refresh_auth.py`、`gemini/list_gemini_models.py`

## 5. 造数参数说明（pipeline_create_rows）

脚本：`/Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py`

关键参数：
- `--row-count-mode auto|fixed`：造数数量模式，默认 `auto`
- `--rows-per-table`：固定模式下每表数量（正整数）
- `--seed-count-plan-json`：外部传入数量规划 JSON（`auto` 可用）
- `--relation-plan-json`：外部传入关联映射规划 JSON
- `--consistency-plan-json`：外部传入父子一致性约束 JSON
- `--skip-consistency`：跳过父子一致性修正
- `--delete-history y|n`：是否先清空所选表历史记录
- `--dry-run`：只规划不写入

模式说明：
- `auto`：基于工作表结构和关系由 Gemini 分析每表数量，并支持本地 fallback 规则。
- `fixed`：所有选中工作表统一使用 `--rows-per-table`。

## 6. 关键脚本清单

### 6.1 应用管理
- `create_app.py`：创建应用
- `get_app_authorize.py`：获取应用授权并落盘
- `list_apps_for_icon.py`：拉取应用清单（供 icon 匹配）
- `update_app_icons.py`：批量更新应用 icon
- `update_app_navi_style.py`：修改应用导航风格
- `delete_app.py`：删除应用（支持全删/按序号删）

### 6.2 工作表管理
- `plan_app_worksheets_gemini.py`：规划工作表
- `create_worksheets_from_plan.py`：按规划建表
- `list_app_worksheets.py`：获取工作表列表
- `update_worksheet_icons.py`：批量更新工作表 icon

### 6.3 字段布局
- `plan_worksheet_layout.py`：规划字段布局
- `apply_worksheet_layout.py`：应用字段布局

### 6.4 造数与关系
- `pipeline_create_rows.py`：造数总入口
- `plan_row_seed_counts_gemini.py`：按表性质分析造数数量
- `plan_row_relation_links_gemini.py`：规划记录间关联映射
- `plan_parent_child_constraints_gemini.py`：规划父子运算一致性约束
- `enforce_parent_child_consistency.py`：执行一致性校验与修正

### 6.5 需求对话与执行
- `agent_collect_requirements.py`：需求对话，输出 `workflow_requirement_v1`
- `execute_requirements.py`：按需求 JSON 编排执行

## 7. 输出文件目录

### 7.1 应用与授权
- `/Users/andy/Desktop/hap_auto/data/outputs/app_authorizations/`

### 7.2 工作表规划与建表
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_create_results/`

### 7.3 字段布局
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_layout_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_layout_apply_results/`

### 7.4 图标
- `/Users/andy/Desktop/hap_auto/data/outputs/app_icon_match_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/app_icon_updates/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_icon_match_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_icon_updates/`

### 7.5 造数与关系
- `/Users/andy/Desktop/hap_auto/data/outputs/row_seed_schemas/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_seed_count_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_seed_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_seed_results/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_relation_contexts/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_relation_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_consistency_contexts/`
- `/Users/andy/Desktop/hap_auto/data/outputs/parent_child_constraint_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/parent_child_consistency_results/`

### 7.6 需求与执行报告
- `/Users/andy/Desktop/hap_auto/data/outputs/requirement_specs/`
- `/Users/andy/Desktop/hap_auto/data/outputs/execution_runs/`

## 8. 常见问题

1. 提交时报 `index.lock`：
- 原因：仓库存在未释放锁文件 `.git/index.lock`。
- 处理：结束占用 Git 的进程后删除锁文件，再重试提交。

2. 造数数量和预期不一致：
- 先确认 `row-count-mode` 是否为 `auto`。
- 检查 `row_seed_count_plan_latest.json` 是否为最新分析结果。
- 若需固定值，改用 `--row-count-mode fixed --rows-per-table N`。
