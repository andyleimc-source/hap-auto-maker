# CLAUDE.md — HAP Auto Maker

## 项目概述

通过 AI（Gemini/DeepSeek）驱动，全自动将自然语言需求转化为完整明道云 HAP 应用，包含工作表、字段、视图、图表、角色权限、工作流、机器人、Mock 数据。

## 运行

```bash
cd hap-auto-maker
python3 run_app_pipeline.py
```

## 架构

```
用户需求 (自然语言)
    ↓
agent_collect_requirements.py  ← 多轮对话，产出 requirement_spec.json
    ↓
execute_requirements.py        ← 多 Wave 并行编排引擎（Wave 1-7）
```

## AI 调用规范

- 统一使用 `ai_utils.py`：`load_ai_config`, `get_ai_client`, `parse_ai_json`
- 默认用 `fast` tier（gemini-2.5-flash / deepseek-chat），**不要擅自切换到 reasoning**
- 所有 AI 输出必须经过 `repair_plan()` + `validate_*()` 校验后才能使用

## API 响应成功标志

- V3 API：`error_code == 1`，数据在 `body["data"]`
- Web API：`state == 1`（部分接口用 `resultCode == 1`）

## 排障入口

1. 终端 `✗ Step N` → 定位失败步骤
2. `data/outputs/execution_runs/execution_run_*.json` → 完整执行报告
3. `data/outputs/app_runs/{run_id}/tech_log.json` → 技术排障日志
