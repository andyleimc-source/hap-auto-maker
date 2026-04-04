# CLAUDE.md — HAP Auto Maker

## 运行

```bash
python3 make_app.py --requirements "完整需求描述"          # 完整执行
python3 make_app.py --requirements "..." --no-execute      # 只生成 spec
python3 make_app.py --spec-json requirement_spec_latest.json  # 跳过 AI 生成
```

入口：`make_app.py` → `execute_requirements.py`（Wave 1-7 并行引擎）

## AI 调用规范

- 统一用 `ai_utils.py`：`load_ai_config`, `get_ai_client`, `parse_ai_json`
- 默认 `fast` tier（gemini-2.5-flash / deepseek-chat），**不要切换到 reasoning**
- 所有 AI 输出须经 `repair_plan()` + `validate_*()` 校验

## API 响应成功标志

- V3 API：`error_code == 1`，数据在 `body["data"]`
- Web API：`state == 1`（部分接口用 `resultCode == 1`）

## 知识沉淀原则

所有通过调试、抓包、测试发现的正确参数和规则，**必须写入代码**（注释、常量、校验逻辑），不能只存在 memory 中。因为 pipeline 运行时不会加载 memory。具体位置：

- API 参数映射 → 对应的 Schema/Registry 文件（如 `chart_config_schema.py`、`view_types.py`）
- 创建/保存规则 → 对应的 build 函数注释和逻辑（如 `_base.py`、`execute_workflow_plan.py`）
- 字段约束 → 对应的 planner prompt 和 validate 函数

## 排障入口

1. 终端 `✗ Step N` → 定位失败步骤
2. `data/outputs/execution_runs/execution_run_*.json` → 完整执行报告
3. `data/outputs/app_runs/{run_id}/tech_log.json` → 技术排障日志
