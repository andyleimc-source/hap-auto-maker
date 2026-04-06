# 统计图表事件驱动重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将统计图表创建从 Wave 6 大一统模式重构为事件驱动：Pages 提前创建，每个工作表完成后立即触发图表生成。

**Architecture:** Phase 0 在 Wave 2.5 根据工作表名称规划并创建 Pages，Phase 1 在 create_worksheets_from_plan.py 中加工作表完成回调，Phase 2 回调内执行单表图表 AI 规划加创建加追加到 Page。图表创建串行在工作表线程内，通过 gemini_semaphore 控制 AI 并发。

**Tech Stack:** Python 3.12, Google Gemini API (via ai_utils.py), 明道云 Web API (via auth_retry.py)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `scripts/hap/planning/page_planner.py` | Pages 规划 prompt + 校验（仅需工作表名称） |
| Create | `scripts/hap/executors/create_pages_early.py` | 提前创建 Pages + 输出 page_registry.json |
| Create | `scripts/hap/planning/single_ws_chart_planner.py` | 单表图表 AI 规划 prompt + 校验 |
| Create | `scripts/hap/executors/create_single_ws_charts.py` | 单表图表创建 + 追加到 Page |
| Modify | `scripts/hap/pipeline/context.py:47` | 增加 page_registry_json 字段 |
| Modify | `scripts/hap/execute_requirements.py:48-64` | scripts dict 增加新脚本路径 |
| Modify | `scripts/hap/executors/create_worksheets_from_plan.py:670-848` | 新增 --page-registry 参数 + 回调 |
| Modify | `scripts/hap/pipeline/waves.py:247-623` | Wave 2.5 增加 Pages 步骤, 删除 14a/14, 调整 Wave 编号 |

---

### Task 1: planning/page_planner.py — Pages 规划模块

**Files:**
- Create: `scripts/hap/planning/page_planner.py`

- [ ] **Step 1: 创建 page_planner.py**

包含两个核心函数：
- `build_pages_prompt(app_name: str, worksheet_names: list[str]) -> str` — 生成 Pages 规划 prompt，仅需工作表名称列表。根据工作表数量决定 Pages 数量（1-6表=1页，7-15表=2页，16+表=3页）
- `validate_pages_plan(raw: dict, valid_ws_names: set[str]) -> list[dict]` — 校验 AI 输出，过滤无效工作表名、修正非法 icon

常量：
- `ICON_CANDIDATES`: 15 个可用图标及描述（复用 plan_pages_gemini.py 的列表）
- `VALID_ICONS`: 图标名称集合
- `COLOR_POOL`: 10 个 Material Design 颜色

prompt 模板要点：
- 输入仅工作表名称列表（不含字段信息）
- 要求每个 Page 名称 10 字以内、说明 20 字以内
- 所有工作表必须被至少一个 Page 关联
- 输出 worksheetNames（而非 worksheetIds）

参考现有实现: `scripts/hap/planners/plan_pages_gemini.py:251-313`（prompt 结构）和 `:340-378`（validate 逻辑）

- [ ] **Step 2: 验证模块可导入**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "from scripts.hap.planning.page_planner import build_pages_prompt, validate_pages_plan; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/planning/page_planner.py
git commit -m "feat: 新增 page_planner — 仅根据工作表名称规划 Pages"
```

---

### Task 2: executors/create_pages_early.py — 提前创建 Pages

**Files:**
- Create: `scripts/hap/executors/create_pages_early.py`

- [ ] **Step 1: 创建 create_pages_early.py**

命令行工具（被 waves.py 通过 subprocess 调用），负责：
1. 从 worksheet_plan.json 提取工作表名称
2. 获取应用元信息（appSectionId, projectId）— 复用 `planners/plan_pages_gemini.py:145-199` 的 `fetch_app_info` 逻辑
3. 调用 AI 规划 Pages（使用 `page_planner.build_pages_prompt` + `ai_utils.get_ai_client`）
4. 调用 AddWorkSheet API 创建 Pages — 复用 `executors/create_pages_from_plan.py:100-127` 的 `create_page` 逻辑
5. 调用 savePage 初始化 — 复用 `executors/create_pages_from_plan.py:130-162` 的 `initialize_page` 逻辑
6. 输出 page_registry.json

命令行参数: `--app-id`, `--worksheet-plan-json`, `--auth-config`, `--output`, `--dry-run`

page_registry.json 结构:
```json
{
  "appId": "uuid",
  "appName": "应用名",
  "projectId": "xxx",
  "appSectionId": "xxx",
  "pages": [
    {
      "pageId": "actual_id",
      "name": "销售分析",
      "desc": "...",
      "icon": "sys_dashboard",
      "iconColor": "#2196F3",
      "worksheetNames": ["销售订单", "客户信息"],
      "components": [],
      "version": 1
    }
  ]
}
```

输出标记: `RESULT_JSON: {path}` （供 waves.py 解析）

API 端点:
- GET_APP_URL = `https://www.mingdao.com/api/HomeApp/GetApp`
- ADD_WORKSHEET_URL = `https://www.mingdao.com/api/AppManagement/AddWorkSheet`
- SAVE_PAGE_URL = `https://api.mingdao.com/report/custom/savePage`

AI 调用: `load_ai_config(tier="fast")` + `get_ai_client()` + `create_generation_config(response_mime_type="application/json", temperature=0.3)` + `parse_ai_json()`

- [ ] **Step 2: 验证语法**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "import ast; ast.parse(open('scripts/hap/executors/create_pages_early.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/executors/create_pages_early.py
git commit -m "feat: 新增 create_pages_early — 提前创建统计分析 Pages"
```

---

### Task 3: planning/single_ws_chart_planner.py — 单表图表规划模块

**Files:**
- Create: `scripts/hap/planning/single_ws_chart_planner.py`

- [ ] **Step 1: 创建 single_ws_chart_planner.py**

包含两个核心函数：
- `build_single_ws_chart_prompt(ws_name: str, fields: list[dict], page_name: str = "") -> str`
  - 输入: 工作表名称 + 字段列表（controlId, controlName, controlType, options）
  - 包含图表类型指南（通过 `charts.chart_config_schema.get_ai_prompt_section()` 或 `constraints.build_chart_type_prompt_section()`）
  - 字段列表格式: `{controlId}  {controlName}  (type={controlType})  选项: val1, val2`
  - 要求 AI 同时判断 suitable + 输出 1-3 个不重复类型的图表配置
  - 约束: 数值图(10) xaxes 为空字符串、饼图(3) xaxes 用单选/下拉、折线图(2) xaxes 用日期
  - 输出 JSON: `{"suitable": true/false, "reason": "...", "charts": [...]}`

- `validate_single_ws_chart_plan(raw: dict, valid_field_ids: set[str]) -> list[dict]`
  - suitable=false 时返回空列表
  - 校验 reportType > 0 且不重复
  - 校验 xaxes.controlId 在 valid_field_ids 或系统字段（ctime/utime/record_count/""）中
  - 校验 yaxisList 至少 1 项且 controlId 有效，无效时兜底为 record_count
  - 兜底 filter 为 `{"filterRangeId": "ctime", "filterRangeName": "创建时间", "rangeType": 0, "rangeValue": 0, "today": false}`
  - 最多返回 3 个图表

参考现有实现:
- prompt 结构: `scripts/hap/planning/chart_planner.py:55-167`（`build_enhanced_prompt`）
- 字段分类: `scripts/hap/planning/constraints.py:48-66`（`build_chart_type_prompt_section`）
- 图表 schema: `scripts/hap/charts/chart_config_schema.py`（`get_ai_prompt_section`）

- [ ] **Step 2: 验证模块可导入**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "from scripts.hap.planning.single_ws_chart_planner import build_single_ws_chart_prompt, validate_single_ws_chart_plan; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/planning/single_ws_chart_planner.py
git commit -m "feat: 新增 single_ws_chart_planner — 单表图表 AI 规划"
```

---

### Task 4: executors/create_single_ws_charts.py — 单表图表创建+追加到 Page

**Files:**
- Create: `scripts/hap/executors/create_single_ws_charts.py`

- [ ] **Step 1: 创建 create_single_ws_charts.py**

该模块作为库被 create_worksheets_from_plan.py 的回调调用（非独立命令行工具）。

核心函数: `plan_and_create_charts(worksheet_id, worksheet_name, fields, page_entry, app_id, auth_config_path, ai_config, gemini_semaphore=None) -> dict`

流程:
1. 调用 `single_ws_chart_planner.build_single_ws_chart_prompt()` 生成 prompt
2. 通过 `ai_utils.get_ai_client()` + `create_generation_config(response_mime_type="application/json", temperature=0.3)` 调用 AI
3. 用 `gemini_semaphore.acquire/release` 控制并发
4. 调用 `validate_single_ws_chart_plan()` 校验
5. 对每个有效图表: 设置 worksheetId -> `charts.build_report_body()` -> POST `saveReportConfig`
6. 收集成功的 reportId -> `_append_charts_to_page()` 追加到 Page

`_append_charts_to_page(page_id, page_entry, charts, app_id, auth_config_path)`:
- 使用 `_page_lock = threading.Lock()` 保护并发写入
- 计算 max_y（现有组件的最大 y+h）
- 两列布局: W=24, H=12, x=(idx%2)*W, y=max_y+(idx//2)*H
- 组件结构复用 `executors/create_charts_from_plan.py:322-362` 的 `build_page_components` 逻辑
- savePage body 复用 `executors/create_charts_from_plan.py:365-394` 的 `save_page` 逻辑
- 成功后原地更新 page_entry["components"] 和 page_entry["version"]

API 端点:
- SAVE_REPORT_URL = `https://api.mingdao.com/report/reportConfig/saveReportConfig`
- SAVE_PAGE_URL = `https://api.mingdao.com/report/custom/savePage`

返回值: `{"worksheet": str, "suitable": bool, "reason": str, "charts_created": int, "details": list}`

- [ ] **Step 2: 验证语法**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "import ast; ast.parse(open('scripts/hap/executors/create_single_ws_charts.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/executors/create_single_ws_charts.py
git commit -m "feat: 新增 create_single_ws_charts — 单表图表创建+追加到 Page"
```

---

### Task 5: 修改 pipeline/context.py — 增加 page_registry 字段

**Files:**
- Modify: `scripts/hap/pipeline/context.py:47`

- [ ] **Step 1: 添加 page_registry_json 字段**

在 PipelineContext dataclass 中，`workflow_execute_result_json` 之后添加:
```python
    page_registry_json: Optional[str] = None
```

在 `as_artifacts_dict()` 中添加:
```python
            "page_registry_json": self.page_registry_json,
```

- [ ] **Step 2: 验证**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
from pipeline.context import PipelineContext
print('page_registry_json' in PipelineContext.__dataclass_fields__)
"`
Expected: True

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/pipeline/context.py
git commit -m "feat: PipelineContext 增加 page_registry_json 字段"
```

---

### Task 6: 修改 execute_requirements.py — 注册新脚本

**Files:**
- Modify: `scripts/hap/execute_requirements.py:48-64`

- [ ] **Step 1: 在 scripts dict 中添加新脚本**

在 `_resolve_scripts()` 返回的 dict 中，`"plan_pages"` 行之后添加:
```python
        "create_pages_early": resolve_script("create_pages_early.py"),
```

- [ ] **Step 2: 验证**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
# 简单验证语法
import ast; ast.parse(open('scripts/hap/execute_requirements.py').read()); print('OK')
"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/execute_requirements.py
git commit -m "feat: execute_requirements 注册 create_pages_early 脚本"
```

---

### Task 7: 修改 create_worksheets_from_plan.py — 增加图表回调

**Files:**
- Modify: `scripts/hap/executors/create_worksheets_from_plan.py:670-848`

- [ ] **Step 1: 添加辅助函数**

在 `main()` 函数之前添加:

`_TYPE_NAME_MAP` dict: 类型名称到 int 的映射（Text->2, Number->6, SingleSelect->9, 等）
`_type_name_to_int(type_name: str) -> int`: 查表返回类型 int
`_fetch_real_fields(base_url, headers, worksheet_id) -> list[dict]`: 通过 v3 API 获取工作表字段（用 `GET_WS_ENDPOINT`），返回 `[{controlId, controlName, controlType}]`，跳过 Relation/SubTable/Rollup

- [ ] **Step 2: 添加 --page-registry 参数**

在 `main()` 的 argparse 中添加:
```python
    parser.add_argument("--page-registry", default="", help="page_registry.json 路径")
```

- [ ] **Step 3: 加载 page_registry 和 AI 配置**

在 `args = parser.parse_args()` 之后，添加 page_registry 加载逻辑:
- 如果 `args.page_registry` 非空且文件存在 -> 用 `load_json()` 加载
- 从 `ai_utils.load_ai_config(tier="fast")` 获取 AI 配置
- 打印 Page 数量

- [ ] **Step 4: 在 Phase 1.5 之后添加图表回调（Phase 1.6）**

位置: Phase 1.5 deferred 字段处理完毕后、Phase 2 relation 之前

逻辑:
1. 构建 ws_name -> page_entry 映射（遍历 page_registry.pages）
2. 遍历 relations_todo（每个已创建的工作表）
3. 对每个工作表: 查找匹配的 page_entry -> 调用 `_fetch_real_fields()` 获取真实字段 -> 调用 `create_single_ws_charts.plan_and_create_charts()`
4. 使用 `threading.Semaphore(2)` 限制 AI 并发
5. 从环境变量 AUTH_CONFIG_PATH 获取 auth_config.py 路径
6. 打印汇总: N/M 个工作表生成了 X 个图表

- [ ] **Step 5: 验证语法**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "import ast; ast.parse(open('scripts/hap/executors/create_worksheets_from_plan.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 6: Commit**

```bash
git add scripts/hap/executors/create_worksheets_from_plan.py
git commit -m "feat: create_worksheets 增加 --page-registry 参数和图表回调"
```

---

### Task 8: 修改 pipeline/waves.py — 重编排 Wave

**Files:**
- Modify: `scripts/hap/pipeline/waves.py:247-623`

- [ ] **Step 1: 在 Wave 2.5 中添加 Pages 创建步骤**

位置: 分组规划（ok2c）处理完毕后、Step 8（导航风格）之前

添加:
- `page_registry_output: Optional[str] = None` 变量
- 构建 `cmd_pages_early` 命令（调用 create_pages_early.py）
- 参数: `--app-id`, `--worksheet-plan-json`(=plan_output), `--auth-config`(=config_web_auth), `--output`
- 如果 execution_dry_run: 添加 `--dry-run`
- 调用 `_exec(14, "pages_early", "提前创建统计分析 Pages", ...)`
- 成功后设置 `ctx.page_registry_json`

- [ ] **Step 2: 修改 Wave 3 创建工作表命令**

在 cmd2b 构建后，添加:
```python
        if page_registry_output:
            cmd2b.extend(["--page-registry", page_registry_output])
```

同时在调用前设置环境变量:
```python
        import os
        if page_registry_output:
            os.environ["AUTH_CONFIG_PATH"] = str(config_web_auth)
```

- [ ] **Step 3: 删除 Wave 4 中的 run_step_14a**

删除:
- `ok_14a = False`（约 line 375）
- 整个 `def run_step_14a():` 函数（约 line 479-509）
- `f14a = pool.submit(run_step_14a)`（约 line 518）
- `f14a.result()`（约 line 525）

将 ThreadPoolExecutor 的 max_workers 从 7 改为 6。

- [ ] **Step 4: 删除 Wave 6（原图表 Pages 步骤）**

删除从 `# Wave 6: 统计图表 Pages` 到 `_exec(14, "pages", title, cmd14, ...)` 的整个代码块（约 line 584-602）。

- [ ] **Step 5: 将 Wave 7 改为 Wave 6**

将 `"-- Wave 7: 删除[全部]默认视图"` 改为 `"-- Wave 6: 删除[全部]默认视图"`

- [ ] **Step 6: 验证语法**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "import ast; ast.parse(open('scripts/hap/pipeline/waves.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 7: Commit**

```bash
git add scripts/hap/pipeline/waves.py
git commit -m "feat: waves 重编排 — Pages 提前到 Wave 2.5, 删除旧 Wave 6"
```

---

### Task 9: 端到端验证

- [ ] **Step 1: dry-run 测试**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 make_app.py --requirements "一个简单的客户管理系统，包含客户信息表和销售订单表" --no-execute`

验证 spec 生成正常，pages 配置存在。

- [ ] **Step 2: 检查 page_planner prompt 输出**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
from planning.page_planner import build_pages_prompt
prompt = build_pages_prompt('客户管理系统', ['客户信息', '销售订单', '产品目录'])
print(prompt[:500])
print('...')
print(f'Prompt length: {len(prompt)} chars')
"`

验证 prompt 精简、仅含工作表名称。

- [ ] **Step 3: 检查 single_ws_chart_planner prompt 输出**

Run: `cd /Users/andy/Documents/coding/hap-auto-maker && python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
from planning.single_ws_chart_planner import build_single_ws_chart_prompt
fields = [
    {'controlId': 'f1', 'controlName': '客户名称', 'controlType': 2},
    {'controlId': 'f2', 'controlName': '签约金额', 'controlType': 8},
    {'controlId': 'f3', 'controlName': '客户来源', 'controlType': 9, 'options': [{'value': '线上'}, {'value': '线下'}]},
]
prompt = build_single_ws_chart_prompt('销售订单', fields, '销售分析')
print(prompt[:500])
print('...')
print(f'Prompt length: {len(prompt)} chars')
"`

验证 prompt 精简、包含字段和图表类型指南。

- [ ] **Step 4: 最终 Commit**

```bash
git add -A && git commit -m "chore: 统计图表事件驱动重构 — 全部代码完成"
```
