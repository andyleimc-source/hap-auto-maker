# hap_auto

项目目标：自动化完成 HAP 应用从创建到配置的全链路，包括应用创建、工作表规划、字段布局、图标匹配、视图与筛选配置，以及现有应用的批量造数与关联回填。

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

### 2.3 一键造数（现有应用）

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_mock_data.py
```

说明：
- 仅支持 `data/outputs/app_authorizations/` 下已有授权的应用。
- 启动后选择应用，后续自动执行：结构快照 -> Gemini 造数规划 -> 写入记录 -> 关联一致性分析 -> 关联修复执行 -> 删除 unresolved 源记录（如有）。
- 默认 `triggerWorkflow=false`，避免触发应用内工作流。
- 结构快照里的造数条数规则：
  - 无关联：每表 5 条记录。
  - 自身 Relation 字段全部为单选端（`subType=1`），且命中 `1-N`：按明细端处理，每表 10 条记录。
  - 聚合端或主表：每表 5 条记录。
- 关联处理规则：
  - `1-1` 关系会处理。
  - `1-N` 关系会处理单选端字段（`subType=1`，即下级记录指向唯一上级记录）。
  - `1-N` 的多选端字段（`subType=2`）不会自动批量回填。
- 如果仍存在无法自动确定的关联，流水线会输出 `unresolved`，并删除对应 unresolved 源记录，避免留下空关联脏数据。

### 2.4 清空应用全部记录

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/clear_app_records.py --dry-run
python3 /Users/andy/Desktop/hap_auto/scripts/clear_app_records.py
```

说明：
- 仅支持 `data/outputs/app_authorizations/` 下已有授权的应用。
- 启动后选择应用，自动遍历该应用下全部工作表并分页删除所有记录。
- 默认逻辑删除；加 `--permanent` 可永久删除。
- 默认 `triggerWorkflow=false`，避免触发应用内工作流。
- 结果文件输出到 `data/outputs/app_record_clear_results/`。

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

### 3.4 工作表 icon 流水线

流程：拉清单 -> Gemini 匹配 icon -> 批量更新

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_icon.py \
  --app-auth-json /Users/andy/Desktop/hap_auto/data/outputs/app_authorizations/app_authorize_<你的appId>.json \
  --app-id <你的appId>
```

### 3.5 视图创建流水线

流程：规划视图 -> 创建视图

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_views.py
```

说明：
- 规划结果输出到 `data/outputs/view_plans/`
- 创建结果输出到 `data/outputs/view_create_results/`

### 3.6 视图筛选配置流水线

流程：选择应用 -> 分析支持的视图 -> 规划筛选列表/快速筛选 -> 应用配置

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_tableview_filters.py
```

### 3.7 造数流水线

流程：选择应用 -> 导出结构快照 -> Gemini 规划造数 -> 写入记录 -> 关联一致性分析 -> 关联修复执行 -> 删除 unresolved 源记录（如有）

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_mock_data.py
```

说明：
- 结构快照会输出工作表、字段、可写字段、跳过字段、关系边、关系对和 worksheet tier。
- tier 规则：
  - 无关联：第一梯队，默认每表 5 条记录。
  - 自身 Relation 字段全部为单选端（`subType=1`），且命中 `1-N`：第二梯队，按明细端处理，默认每表 10 条记录。
  - 存在关联且全部为 `1-1`：第三梯队，默认每表 5 条记录。
  - 聚合端、主表、或 `ambiguous`：按主表处理，默认每表 5 条记录。
- 造数阶段只写常见可写字段：`Text`、`Number`、`Date`、`DateTime`、`SingleSelect`、`MultipleSelect`、`Checkbox`、`Rating`、常见文本类字段。
- 系统字段、公式/汇总、附件、子表、成员/部门/组织角色、Relation 字段会被跳过并记录原因。
- 关联阶段当前支持：
  - `1-1` 关系字段
  - `1-N` 关系中的单选端字段（`subType=1`）
- 关联修复阶段新增两个独立脚本：
  - `analyze_relation_consistency.py`：扫描当前真实写入结果，生成 `updates` 和 `unresolved` 修复计划。
  - `apply_relation_repair_plan.py`：按修复计划批量更新关系字段。
- 如果 `apply_relation_repair_plan.py` 执行后仍有 unresolved，流水线会继续调用 `delete_unresolved_records.py` 删除对应源记录，并在 run report 中记录删除数量。
- 运行日志会落到 `data/outputs/mock_data_logs/`，用于排查结构识别、Gemini 返回、写入批次、关联修复覆盖率等问题。

常用单步命令：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/analyze_relation_consistency.py \
  --schema-json /Users/andy/Desktop/hap_auto/data/outputs/mock_data_schema_snapshots/mock_schema_snapshot_latest.json \
  --write-result-json /Users/andy/Desktop/hap_auto/data/outputs/mock_data_write_results/mock_data_write_result_latest.json
```

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/apply_relation_repair_plan.py \
  --repair-plan-json /Users/andy/Desktop/hap_auto/data/outputs/mock_relation_repair_plans/mock_relation_repair_plan_latest.json
```

## 4. 全流程脚本顺序与作用

说明：`/scripts/*.py` 基本都是稳定入口（代理转发），真实实现在 `/scripts/hap/`、`/scripts/gemini/`、`/scripts/auth/`。

### 4.1 需求驱动总编排顺序（`execute_requirements.py`）

1. `pipeline_create_app.py`：创建应用 + 授权 + 应用 icon
2. `plan_app_worksheets_gemini.py` + `create_worksheets_from_plan.py`：工作表规划与建表
3. （可选）`pipeline_icon.py`：工作表 icon 更新
4. `pipeline_worksheet_layout.py`：字段布局规划与应用
5. `pipeline_views.py`：规划并创建视图
6. `pipeline_tableview_filters.py`：规划并应用视图筛选
7. `update_app_navi_style.py`：应用导航风格
8. `pipeline_mock_data.py`：执行一键造数流水线（最后一步）

### 4.2 底层实现脚本（按职责）

1. 应用：`create_app.py`、`get_app_authorize.py`、`list_apps_for_icon.py`、`update_app_icons.py`、`update_app_navi_style.py`、`delete_app.py`
2. 工作表：`plan_app_worksheets_gemini.py`、`create_worksheets_from_plan.py`、`list_app_worksheets.py`、`update_worksheet_icons.py`
3. 布局：`plan_worksheet_layout.py`、`apply_worksheet_layout.py`
4. 视图与筛选：`plan_worksheet_views_gemini.py`、`create_views_from_plan.py`、`pipeline_views.py`、`plan_tableview_filters_gemini.py`、`apply_tableview_filters_from_plan.py`、`pipeline_tableview_filters.py`
5. 造数：`list_apps_for_mock_data.py`、`export_app_mock_schema.py`、`plan_mock_data_gemini.py`、`write_mock_data_from_plan.py`、`analyze_relation_consistency.py`、`apply_relation_repair_plan.py`、`pipeline_mock_data.py`
6. 认证与辅助：`auth/refresh_auth.py`、`gemini/list_gemini_models.py`

## 5. 输出文件目录

1. 应用与授权
- `/Users/andy/Desktop/hap_auto/data/outputs/app_authorizations/`

2. 工作表规划与建表
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_create_results/`

3. 字段布局
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_layout_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_layout_apply_results/`

4. 图标
- `/Users/andy/Desktop/hap_auto/data/outputs/app_icon_match_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/app_icon_updates/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_icon_match_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_icon_updates/`

5. 需求与执行报告
- `/Users/andy/Desktop/hap_auto/data/outputs/requirement_specs/`
- `/Users/andy/Desktop/hap_auto/data/outputs/execution_runs/`

6. 视图与筛选配置
- `/Users/andy/Desktop/hap_auto/data/outputs/view_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/view_create_results/`
- `/Users/andy/Desktop/hap_auto/data/outputs/tableview_filter_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/tableview_filter_apply_results/`

7. 造数与关联回填
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_data_app_inventory/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_data_schema_snapshots/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_data_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_data_bundles/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_data_write_results/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_relation_repair_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_relation_repair_apply_results/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_relation_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_relation_apply_results/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_data_runs/`
- `/Users/andy/Desktop/hap_auto/data/outputs/mock_data_logs/`
