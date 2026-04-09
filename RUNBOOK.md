# RUNBOOK — 运行与排障手册

## 标准运行路径

1. 配置：`python3 setup.py`
2. 生成+执行：`python3 make_app.py --requirements "..."`
3. 仅执行：`python3 make_app.py --spec-json requirement_spec_latest.json`

## 常见失败定位顺序

1. 看终端：定位 `✗ Step N`
2. 看执行报告：`data/outputs/execution_runs/execution_run_*.json`
3. 看技术日志：`data/outputs/app_runs/{run_id}/tech_log.json`

## 高频问题与处理

### 1. 末尾崩溃但业务已执行完

现象：主流程看似成功，最后统计阶段报错。  
处理：优先确认 `execution_run_*.json` 中各步骤状态，再决定是否重跑。

### 2. 某个视图创建失败

现象：单个视图 `success=false`。  
处理：

1. 打开 `view_create_result_*.json` 看该视图 `createResponse` 和 `updates.response`
2. 核对 `viewType` 与 `advancedSetting/editAdKeys` 是否符合抓包规则
3. 必要时用 HAR 对照修复并把规则固化到代码（Schema/Registry/validate）

### 3. 模型配置疑问（DeepSeek）

`setup.py` 选择后写入 `ai_auth.json`；运行时由 `ai_utils.py` 统一读取。  
DeepSeek 会在运行时按项目策略处理模型选择，请以运行日志中的实际请求行为为准。

## 对 Agent 的约束

- 先读：`AGENTS.md` → `README-QUICKSTART.md` → `RUNBOOK.md`
- 优先走最小可运行命令，不要一上来扫完整仓库
- 抓包/调试得到的规则必须写回代码，不允许只写在 memory
