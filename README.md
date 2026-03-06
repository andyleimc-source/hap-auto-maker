# hap_auto

项目目标：自动化完成 HAP 应用从创建到配置的全链路，包括应用创建、工作表规划、字段布局、图标匹配、视图与筛选配置。

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

## 4. 全流程脚本顺序与作用

说明：`/scripts/*.py` 基本都是稳定入口（代理转发），真实实现在 `/scripts/hap/`、`/scripts/gemini/`、`/scripts/auth/`。

### 4.1 需求驱动总编排顺序（`execute_requirements.py`）

1. `pipeline_create_app.py`：创建应用 + 授权 + 应用 icon
2. `plan_app_worksheets_gemini.py` + `create_worksheets_from_plan.py`：工作表规划与建表
3. （可选）`pipeline_icon.py`：工作表 icon 更新
4. `pipeline_worksheet_layout.py`：字段布局规划与应用
5. `update_app_navi_style.py`：应用导航风格

### 4.2 底层实现脚本（按职责）

1. 应用：`create_app.py`、`get_app_authorize.py`、`list_apps_for_icon.py`、`update_app_icons.py`、`update_app_navi_style.py`、`delete_app.py`
2. 工作表：`plan_app_worksheets_gemini.py`、`create_worksheets_from_plan.py`、`list_app_worksheets.py`、`update_worksheet_icons.py`
3. 布局：`plan_worksheet_layout.py`、`apply_worksheet_layout.py`
4. 视图与筛选：`plan_worksheet_views_gemini.py`、`create_views_from_plan.py`、`pipeline_views.py`、`plan_tableview_filters_gemini.py`、`apply_tableview_filters_from_plan.py`、`pipeline_tableview_filters.py`
5. 认证与辅助：`auth/refresh_auth.py`、`gemini/list_gemini_models.py`

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
