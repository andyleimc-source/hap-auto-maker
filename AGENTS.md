# AGENTS.md — HAP Auto Maker

## Agent 快速上手（必须先读）

当 Claude Code / Codex 首次进入仓库时，按以下顺序读取，禁止先全仓扫描：

1. `AGENTS.md`（本文件）
2. `README-QUICKSTART.md`（3 分钟启动）
3. `RUNBOOK.md`（失败排障）

## 运行

```bash
python3 make_app.py --requirements "完整需求描述"          # 完整执行
python3 make_app.py --requirements "..." --no-execute      # 只生成 spec
python3 make_app.py --spec-json requirement_spec_latest.json  # 跳过 AI 生成
```

入口：`make_app.py` → `execute_requirements.py`（Wave 1-7 并行引擎）

## AI 调用规范

- 统一用 `ai_utils.py`：`load_ai_config`, `get_ai_client`, `parse_ai_json`
- 默认 fast 模式；DeepSeek 在运行时会强制使用 `deepseek-reasoner`（由 `ai_utils.py` 统一处理）
- 所有 AI 输出须经 `repair_plan()` + `validate_*()` 校验

## API 响应成功标志

- V3 API：`error_code == 1`，数据在 `body["data"]`
- Web API：`state == 1`（部分接口用 `resultCode == 1`）

## 知识沉淀原则

所有通过调试、抓包、测试发现的正确参数和规则，**必须写入代码**（注释、常量、校验逻辑），不能只存在 memory 中。因为 pipeline 运行时不会加载 memory。具体位置：

- API 参数映射 → 对应的 Schema/Registry 文件（如 `chart_config_schema.py`、`view_types.py`）
- 创建/保存规则 → 对应的 build 函数注释和逻辑（如 `_base.py`、`execute_workflow_plan.py`）
- 字段约束 → 对应的 planner prompt 和 validate 函数

## Bug 处理原则

处理任何 bug 时，**必须先使用 `superpowers:systematic-debugging` skill**，不得直接跳到修复。skill 会系统地引导根因定位、修复验证流程，确保不遗漏关键步骤。

## Git 提交原则

当完成重要成果时（如修复一批 Bug、完成模块校正、新功能可用），**主动 commit**，不需要等用户要求。commit message 用中文，概括改了什么、为什么改。

## 排障入口

1. 终端 `✗ Step N` → 定位失败步骤
2. `data/outputs/execution_runs/execution_run_*.json` → 完整执行报告
3. `data/outputs/app_runs/{run_id}/tech_log.json` → 技术排障日志
