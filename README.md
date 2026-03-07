# hap_auto

项目目标：自动化完成 HAP 应用从创建到配置的全链路，包括应用创建、工作表规划、字段布局、图标匹配、视图与筛选配置，以及现有应用的批量造数与关联回填。

## 0. 背景、边界与工作方式

这个仓库不是单一脚本，而是一组围绕 HAP 应用生命周期的自动化流水线。核心思路是：
- 用稳定入口脚本串联 HAP OpenAPI、页面接口和 Gemini 规划能力。
- 把每一步中间结果都落盘为 JSON，方便复跑、审计和人工修正。
- 优先把“规划”和“执行”拆开，避免直接把大模型输出无检查地写入真实应用。

适用场景：
- 新建一个业务应用，并自动补齐工作表、布局、图标、视图与筛选配置。
- 对已有应用做批量造数、关联补齐、清空记录等运维动作。
- 反复调试某一阶段时，只执行单个 pipeline 或底层脚本。

当前边界：
- LLM 规划默认依赖 Gemini。
- HAP 接口调用同时依赖组织级 API 凭据与网页登录态。
- Relation 自动修复目前重点覆盖 `1-1` 和 `1-N` 的单选端；`1-N` 多选端不会自动批量回填。
- 大部分脚本假设输出目录可写，并默认把最新结果额外写一份 `*_latest.json`。

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

补充说明：
- `scripts/*.py` 基本是稳定入口；如果你只是执行任务，优先用这一层。
- `scripts/hap/*.py` 是 HAP 业务实现；调试逻辑时再读这一层。
- `scripts/gemini/*.py` 主要负责规划、匹配、生成方案，不直接写业务数据。
- `view/*.har` 是视图相关抓包样本，主要用于接口行为核对，不是运行时必需输入。

## 2. 环境准备与配置

### 2.1 Python 与依赖

建议使用 Python 3.11+。仓库当前未维护统一的 `requirements.txt`，从脚本实际 import 看，至少需要：
- `requests`
- `google-genai`
- `playwright`
- `prompt-toolkit`（可选，用于更好的终端输入体验）

如果要使用自动刷新认证，还需要先安装 Playwright 浏览器：

```bash
python3 -m pip install requests google-genai playwright prompt-toolkit
python3 -m playwright install chromium
```

### 2.2 凭据与本地配置

运行前至少要检查以下文件：
- `/Users/andy/Desktop/hap_auto/config/credentials/gemini_auth.json`
- `/Users/andy/Desktop/hap_auto/config/credentials/organization_auth.json`
- `/Users/andy/Desktop/hap_auto/config/credentials/auth_config.py`
- `/Users/andy/Desktop/hap_auto/config/credentials/login_credentials.py`

它们分别承担的作用：
- `gemini_auth.json`：提供 Gemini `api_key`，用于需求收集、建模规划、图标匹配、造数规划等。
- `organization_auth.json`：提供 HAP 组织级 API 调用所需信息，供 OpenAPI 脚本使用。
- `auth_config.py`：提供网页接口调用所需的 `ACCOUNT_ID`、`AUTHORIZATION`、`COOKIE`。
- `login_credentials.py`：供 `refresh_auth.py` 用 Playwright 自动登录并刷新 `auth_config.py`。

安全约定：
- 这些文件都属于本地敏感配置，不应提交到公开仓库。
- `AUTHORIZATION` 和 `COOKIE` 有时效，失效时需要刷新。

### 2.3 认证刷新方法

如果网页登录态失效，优先用下面的脚本刷新：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/refresh_auth.py
```

无头模式：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/refresh_auth.py --headless
```

这个脚本会：
- 打开明道云登录页。
- 使用 `login_credentials.py` 中的账号密码登录。
- 捕获最新 Cookie / Authorization。
- 自动回写 `/Users/andy/Desktop/hap_auto/config/credentials/auth_config.py`。

## 3. 快速开始

先进入项目目录：

```bash
cd /Users/andy/Desktop/hap_auto
```

### 3.1 一键主流程（需求驱动）

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/agent_collect_requirements.py
```

说明：
- 在终端与 Gemini 对话，输入 `/done` 后生成需求 JSON。
- 默认会调用执行器按需求执行全流程（可通过参数关闭自动执行）。

### 3.2 执行已有需求 JSON

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/execute_requirements.py \
  --spec-json /Users/andy/Desktop/hap_auto/data/outputs/requirement_specs/requirement_spec_latest.json
```

### 3.3 一键造数（现有应用）

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

### 3.4 清空应用全部记录

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

## 4. 方法与标准 Pipeline（按场景拆分）

方法约定：
- 先规划，后执行。凡是涉及 LLM 的能力，通常先生成 plan，再由应用脚本消费。
- 先落盘，后串联。每个阶段都尽量输出独立 JSON，便于单步回放。
- 入口脚本可重复执行；是否幂等取决于下游接口语义，重复执行前最好确认输出和目标应用状态。
- 对真实应用写入的脚本，能用 `--dry-run` 时优先先跑一遍。

### 4.1 创建应用流水线

流程：创建应用 -> 获取授权 -> 匹配应用 icon -> 更新应用 icon

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_app.py --name "医院后勤管理系统"
```

### 4.2 工作表流水线

流程：规划工作表 -> 创建工作表 -> 匹配并更新工作表 icon

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheets.py
```

### 4.3 字段布局流水线

流程：选择应用 -> 规划字段布局 -> 应用布局

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheet_layout.py \
  --app-id <你的appId> \
  --requirements "按业务角色优化表单布局"
```

### 4.4 工作表 icon 流水线

流程：拉清单 -> Gemini 匹配 icon -> 批量更新

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_icon.py \
  --app-auth-json /Users/andy/Desktop/hap_auto/data/outputs/app_authorizations/app_authorize_<你的appId>.json \
  --app-id <你的appId>
```

### 4.5 视图创建流水线

流程：规划视图 -> 创建视图

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_views.py
```

说明：
- 规划结果输出到 `data/outputs/view_plans/`
- 创建结果输出到 `data/outputs/view_create_results/`

### 4.6 视图筛选配置流水线

流程：选择应用 -> 分析支持的视图 -> 规划筛选列表/快速筛选 -> 应用配置

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_tableview_filters.py
```

### 4.7 造数流水线

流程：选择应用 -> 导出结构快照 -> Gemini 规划造数 -> 写入记录 -> 关联一致性分析 -> 关联修复执行 -> 删除 unresolved 源记录（如有）

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_mock_data.py
```

说明：
- 结构快照会输出工作表、字段、可写字段、跳过字段、关系边、关系对和 worksheet tier。
- tier 规则：
  - 无关联：第一梯队，默认每表 5 条记录。
  - 存在关联且全部为 `1-1`：第二梯队，默认每表 5 条记录。
  - 自身 Relation 字段全部为单选端（`subType=1`），且命中 `1-N`：第三梯队，按明细端处理，默认每表 10 条记录。
  - 聚合端、主表、或 `ambiguous`：按主表处理，默认每表 5 条记录。
- 造数阶段只写常见可写字段：`Text`、`Number`、`Date`、`DateTime`、`SingleSelect`、`MultipleSelect`、`Checkbox`、`Rating`、常见文本类字段。
- 系统字段、公式/汇总、附件、子表、成员/部门/组织角色、Relation 字段会被跳过并记录原因。
- 关联阶段当前支持：
  - `1-1` 关系字段
  - `1-N` 关系中的单选端字段（`subType=1`）
- Relation 修复顺序与造数 tier 保持一致：
  - `tier 1`（无关联 / 聚合端 / 主表 / ambiguous）优先
  - `tier 2`（纯 `1-1`）其次
  - `tier 3`（明细单选端）最后
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

### 4.8 删除应用脚本（补充）

单个应用删除（按 `appId`）：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/delete_app.py \
  --app-id "<APP_ID>"
```

批量删除（从 `data/outputs/app_authorizations/` 读取已记录应用，交互选择）：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/delete_app.py --delete-all
```

只看请求体不真正删除（排查参数时推荐先跑）：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/delete_app.py \
  --app-id "<APP_ID>" \
  --dry-run
```

说明：
- `--delete-all` 模式会提示输入：`Y` 全删，或输入序号（如 `1,2,3`）部分删除。
- 在非 `--dry-run` 下，脚本会按模式清理对应的本地 `data/outputs` JSON 文件记录。
- `project_id`、`owner_id` 默认从 `/Users/andy/Desktop/hap_auto/config/credentials/organization_auth.json` 读取；必要时可显式传 `--project-id`、`--operator-id`。

## 5. 全流程脚本顺序与作用

说明：`/scripts/*.py` 基本都是稳定入口（代理转发），真实实现在 `/scripts/hap/`、`/scripts/gemini/`、`/scripts/auth/`。

### 5.1 需求驱动总编排顺序（`execute_requirements.py`）

1. `pipeline_create_app.py`：创建应用 + 授权 + 应用 icon
2. `plan_app_worksheets_gemini.py` + `create_worksheets_from_plan.py`：工作表规划与建表
3. （可选）`pipeline_icon.py`：工作表 icon 更新
4. `pipeline_worksheet_layout.py`：字段布局规划与应用
5. `pipeline_views.py`：规划并创建视图
6. `pipeline_tableview_filters.py`：规划并应用视图筛选
7. `update_app_navi_style.py`：应用导航风格
8. `pipeline_mock_data.py`：执行一键造数流水线（最后一步）

### 5.2 底层实现脚本（按职责）

1. 应用：`create_app.py`、`get_app_authorize.py`、`list_apps_for_icon.py`、`update_app_icons.py`、`update_app_navi_style.py`、`delete_app.py`
2. 工作表：`plan_app_worksheets_gemini.py`、`create_worksheets_from_plan.py`、`list_app_worksheets.py`、`update_worksheet_icons.py`
3. 布局：`plan_worksheet_layout.py`、`apply_worksheet_layout.py`
4. 视图与筛选：`plan_worksheet_views_gemini.py`、`create_views_from_plan.py`、`pipeline_views.py`、`plan_tableview_filters_gemini.py`、`apply_tableview_filters_from_plan.py`、`pipeline_tableview_filters.py`
5. 造数：`list_apps_for_mock_data.py`、`export_app_mock_schema.py`、`plan_mock_data_gemini.py`、`write_mock_data_from_plan.py`、`analyze_relation_consistency.py`、`apply_relation_repair_plan.py`、`pipeline_mock_data.py`
6. 认证与辅助：`auth/refresh_auth.py`、`gemini/list_gemini_models.py`

## 6. 输出文件目录

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

## 7. 常见输入输出约定

1. 多数脚本支持显式 `--output`，不传时会写到 `data/outputs/` 的约定目录。
2. 很多结果目录同时会维护一个 `*_latest.json`，方便下游脚本直接接续。
3. 应用级脚本常通过 `app_authorize_<appId>.json` 找授权信息；如果这类文件缺失，很多“选择应用”型脚本无法运行。
4. 需要用户选择应用的脚本，本质上是扫描 `data/outputs/app_authorizations/` 下最近的授权文件。
5. `pipeline_mock_data.py`、`clear_app_records.py` 这类脚本会把运行日志额外写入 `jsonl`，排障时优先看日志而不是只看终端输出。

## 8. 常见排障

1. Gemini 调用失败
- 先检查 `/Users/andy/Desktop/hap_auto/config/credentials/gemini_auth.json` 是否存在有效 `api_key`。
- 再确认默认模型 `gemini-2.5-pro` 当前可用。

2. HAP OpenAPI 调用失败
- 检查 `organization_auth.json` 是否仍有效。
- 核对 `base_url` 是否与当前环境一致，默认是 `https://api.mingdao.com`。

3. 页面接口调用失败或 401/403
- 通常是 `auth_config.py` 里的 `COOKIE` / `AUTHORIZATION` 过期。
- 直接运行 `python3 /Users/andy/Desktop/hap_auto/scripts/refresh_auth.py` 刷新。

4. 选择不到应用
- 说明 `data/outputs/app_authorizations/` 下没有对应应用的授权 JSON。
- 先跑一次创建应用流水线，或单独执行授权拉取脚本生成 `app_authorize_<appId>.json`。

5. 造数后仍有脏数据或空关联
- 先看 `mock_relation_repair_plan` 与 `mock_relation_repair_apply_result`。
- 如果仍有 unresolved，确认是否属于当前不支持自动修复的关系类型。

## 9. 推荐使用方式

1. 新应用从 `agent_collect_requirements.py` 或 `execute_requirements.py` 开始。
2. 已有应用补数据，从 `pipeline_mock_data.py` 开始。
3. 只改某一块配置时，不走总流程，直接跑对应 pipeline。
4. 调试问题时，优先使用 `scripts/` 入口脚本；只有在需要看内部实现时再进入 `scripts/hap/` 或 `scripts/gemini/`。
