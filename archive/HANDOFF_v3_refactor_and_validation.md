# HANDOFF — 全盘工程重构 + 双应用验证

> 更新时间: 2026-04-06
> 分支: feat/v2.0（已同步 main）
> 验证应用 1: 综合医院（行业应用，generate_industry_app.py）
> app_id: `d137922d-44b9-44ca-aeec-3ad6a803bc74`
> 验证应用 2: 供应链管理系统（make_app.py 直接生成，28 工作表）
> app_id: `bede25d2-2072-4e4e-8c6b-52fcc16c3eef`

---

## 本次完成内容（7 Phase 重构 + 8 Bug 修复）

### Phase 1-3：基础设施
- **utils.py**：消除全仓库 ~40 处重复的 `now_ts/load_json/write_json/latest_file`
- **pyproject.toml + `__init__.py`**：建立 `scripts.hap.*` 标准包结构
- **normalize_spec**：合并为单一权威版本（`execute_requirements.py`），`make_app.py` 和 `agent_collect_requirements.py` 改为导入

### Phase 4：拆分上帝函数
- `execute_requirements.py`：1076 行 → 285 行
- 新增 `scripts/hap/pipeline/` 包：
  - `context.py`：`PipelineContext` dataclass，持有所有 artifact 路径 + steps_report
  - `step_runner.py`：`run_cmd()`（流式输出 + 心跳）、`execute_step()`、`step_selected()`
  - `waves.py`：Wave 1-7 全部并行逻辑（621 行），`run_all_waves()` 作为唯一入口

### Phase 5：目录分层
- 新建 `scripts/hap/planners/`（10 个 AI 规划脚本）
- 新建 `scripts/hap/executors/`（10 个执行脚本）
- `script_locator.py` 搜索路径扩展至 planners/ 和 executors/

### Phase 6：单元测试
新增 44 个测试（6 个测试文件）：
- `test_hap_api_client.py`：15 个（签名、重试、GET/POST、超时）
- `test_utils.py`：11 个（now_ts/now_iso/load_json/write_json/latest_file）
- `test_ai_utils.py`：AI 配置加载、修复模式
- `test_view_planner.py`：视图规划校验（displayControls 剪枝等）
- `test_workflow_planner.py`：工作流结构校验
- `test_create_worksheets.py`：字段 payload 构建、split_fields

### Phase 7：错误处理加固
- `hap_api_client.py`：`max_retries=2`，5/10s 退避，`timeout=30s`
- `waves.py`：宽泛的 `except Exception` 收窄为具体类型
- `make_app.py` / `execute_requirements.py`：`_load_org_group_ids` 分离 ImportError vs 其他异常

---

## 验证结果

### 供应链管理系统（28 工作表）
- 总步骤：18 步全部成功，0 失败
- 耗时：~93 分钟（含 AI 规划 + 造数 + 工作流）
- 报告：`data/outputs/execution_runs/execution_run_20260406_051117.json`

### 综合医院（行业应用）
- 总步骤：18 步（1 skip 建应用，17 成功），0 失败
- 耗时：~40 分钟
- 报告：`data/outputs/execution_runs/execution_run_20260406_055227.json`

---

## 重构后遗留 Bug（已全部修复）

| # | 问题 | 影响文件数 | 修复 commit |
|---|------|-----------|------------|
| 1 | `pipeline_app_roles/charts/pages.py` 硬编码 `CURRENT_DIR/"plan_*.py"`，脚本移位后 FileNotFoundError | 3 | d5df8e4 |
| 2 | `planners/` 和 `executors/` 所有脚本 `sys.path.insert` 在 import 之后，运行时 ModuleNotFoundError | 20 | d5df8e4 |
| 3 | `planners/` 和 `executors/` 内 `BASE_DIR = parents[2]` 层数错误（应为 `parents[3]`） | 14 | 0b9e786 |
| 4 | `Department` 字段类型 API 不支持 CreateWorksheet | create_worksheets_from_plan.py | 0b9e786 |
| 5 | 双向 Relation 未声明时抛异常阻断流程 | create_worksheets_from_plan.py | 0b9e786 |
| 6 | `create_views_from_plan.py` 缺少 `from datetime import datetime` | 1 | 0b9e786 |
| 7 | 工作表 > 20 张时 Gemini 单次响应超长截断，造数失败 | plan_mock_data_gemini.py | 0b9e786 |
| 8 | 分组工作表上限 8 张，大型应用不够用 | plan_app_sections_gemini.py | 0b9e786 |
| 9 | `create_pages_from_plan.py` 用 `CURRENT_DIR`（executors/）找 `pipeline_charts.py` | 1 | a24cb09 |

---

## 当前架构（重构后）

```
make_app.py                          ← 入口（AI 生成 spec → 调 execute_requirements）
scripts/hap/
├── execute_requirements.py          ← 285 行，校验 + 调 run_all_waves()
├── pipeline/
│   ├── context.py                   ← PipelineContext dataclass
│   ├── step_runner.py               ← run_cmd / execute_step
│   └── waves.py                     ← Wave 1-7 全部并行逻辑
├── planners/                        ← 10 个 AI 规划脚本（plan_*.py）
├── executors/                       ← 10 个执行脚本（create_*/apply_*/write_*.py）
├── planning/                        ← 四大规划师注册中心
│   ├── view_planner.py
│   ├── workflow_planner.py
│   ├── constraints.py
│   └── ...
├── worksheets/field_types.py        ← 38 种字段注册中心
├── views/view_types.py              ← 11 种视图注册中心
├── charts/                          ← 17 种图表注册中心
├── utils.py                         ← 公共工具函数
├── ai_utils.py                      ← AI 客户端统一封装
├── hap_api_client.py                ← HAP 组织 API（重试+超时）
└── script_locator.py                ← 脚本路径解析（搜索 planners/executors）
workflow/
├── scripts/pipeline_workflows.py    ← 工作流规划入口
└── nodes/                           ← 30 种节点注册中心
tests/
└── unit/                            ← 44 个单元测试
```

---

## 执行参数参考

```bash
# 完整跑（AI 生成 spec + 执行）
python3 make_app.py --requirements "需求描述"

# 行业应用（需要 industry-app-generator）
cd /Users/andy/Documents/coding/industry-app-generator
python generate_industry_app.py --industry comprehensive-hospital
python generate_industry_app.py --list   # 查看全部 152 个行业

# 跳过 AI 生成，直接执行已有 spec
python3 make_app.py --spec-json data/outputs/requirement_specs/requirement_spec_latest.json

# 跳过建应用，用已有 app_id 续跑
python scripts/hap/execute_requirements.py \
  --spec-json path/to/spec.json \
  --app-id YOUR_APP_ID

# 只跑指定步骤
python scripts/hap/execute_requirements.py \
  --spec-json path/to/spec.json \
  --only-steps "views,view_filters"
```

---

## 待办（下次继续）

- [ ] **workflow_planner 集成**：`planning/workflow_planner.py` 已实现，但 `pipeline_workflows.py` 的 `build_prompt` 尚未替换成 `build_enhanced_prompt`（见 HANDOFF_v2）
- [ ] **pytest 环境**：当前 python3.14 未安装 pytest，CI（.github/workflows/ci.yml）需要验证能否正常跑
- [ ] **增量操作功能**：`scripts/hap/incremental/` 下已有 `add_chart.py`/`modify_view.py`/`modify_workflow.py` 雏形，待接入 Skills（见 archive/TODO_v1_incremental_ops.md）
- [ ] **SubTable/OtherTableField/Rollup** 高级字段配置（见 HANDOFF_v2 三、字段类型）
- [ ] **Department 字段**：已从 CreateWorksheet 白名单移除，deferred addFields 路径需端到端验证

---

## 关键文件索引（增量，完整见 HANDOFF_v2）

| 文件 | 职责 |
|------|------|
| `scripts/hap/pipeline/waves.py` | Wave 1-7 全部并行调度逻辑 |
| `scripts/hap/pipeline/context.py` | PipelineContext，持有所有 artifact 路径 |
| `scripts/hap/pipeline/step_runner.py` | 子进程执行 + 流式输出 |
| `scripts/hap/utils.py` | 公共工具：now_ts/load_json/write_json/latest_file |
| `scripts/hap/planners/` | 10 个 AI 规划脚本（已修复 sys.path） |
| `scripts/hap/executors/` | 10 个执行脚本（已修复 sys.path + BASE_DIR） |
| `tests/unit/` | 44 个单元测试 |
| `data/outputs/execution_runs/` | 执行报告（排障入口） |
