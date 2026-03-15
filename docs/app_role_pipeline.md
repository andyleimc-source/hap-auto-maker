# 应用角色流水线

## 目标

按“应用名 + 工作表名”调用 Gemini 规划角色，再把规划 JSON 写回应用，并为每一步保留排障产物与运行日志。

## 入口脚本

- 规划脚本: `scripts/plan_role_recommendations_gemini.py`
- 角色写入脚本: `scripts/create_roles_from_recommendation.py`
- 一键流水线: `scripts/pipeline_app_roles.py`

## 流水线步骤

1. 解析目标应用与工作表范围
2. 生成工作表清单、Gemini prompt、Gemini 原始响应、角色规划 JSON
3. 根据角色规划 JSON 写入应用角色
4. 可选调用 `run_app_to_video.py` 做应用校验

## 运行产物

每次运行会在 `data/outputs/app_role_runs/app_role_run_<appId>_<timestamp>/` 下生成：

- `pipeline_report.json`: 总报告
- `pipeline.jsonl`: 流水线事件日志
- `artifacts/01_scope.json`: 应用与工作表范围
- `artifacts/02_worksheet_inventory.json`: 工作表清单
- `artifacts/02_role_prompt.txt`: 发给 Gemini 的 prompt
- `artifacts/02_gemini_raw_response.txt`: Gemini 原始响应
- `artifacts/02_role_plan.json`: 角色规划 JSON
- `artifacts/03_role_create_result.json`: 角色写入结果
- `artifacts/04_video_request.json`: 视频校验请求说明
- `artifacts/04_video_result.json`: 视频校验结果
- `logs/*.stdout.log` / `logs/*.stderr.log`: 每个子命令的标准输出/错误输出

## 视频步骤说明

`run_app_to_video.py` 当前只能通过 `--resume-latest` 接到最近一次应用执行结果上，因此只有在 `data/outputs/execution_runs/execution_run_latest.json` 中的 `context.app_id` 与当前目标应用一致时，流水线才会真正执行视频步骤；否则会把跳过原因写入 `04_video_result.json`。

## 示例

```bash
python3 scripts/pipeline_app_roles.py \
  --app-name "客户管理" \
  --worksheet-name "客户列表" \
  --worksheet-name "销售机会" \
  --video-mode skip
```
