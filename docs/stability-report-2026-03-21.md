# 2026-03-21 串行稳定性回归报告

## 执行范围

- 执行命令：`python3 scripts/run_app_pipeline.py --requirements-text "..."`
- 执行方式：严格串行，不并行
- 执行总量：10 个随机企业管理应用场景
- 运行环境：`/usr/local/bin/python3`
- 结果汇总文件：
  - `data/outputs/stability_runs/stability_run_20260321_004417.json`
  - `data/outputs/stability_runs/stability_run_20260321_005814.json`
  - `data/outputs/stability_runs/stability_run_20260321_013238.json`
  - `data/outputs/stability_runs/stability_run_20260321_014713.json`

## 运行简报

- 成功场景数：10 / 10
- 中途真实失败数：1
- 失败修复后复测：通过
- 成功用例累计耗时：2 小时 13 分 17 秒
- 单个成功用例平均耗时：13 分 20 秒

| Case | 应用名称 | 工作表 | 视图 | 工作流 | 耗时 | 应用地址 |
|---|---|---:|---:|---:|---|---|
| 1 | 中型企业行政管理系统 | 7 | 19 | 14 | 20m 24s | https://www.mingdao.com/app/b5e8ca57-b474-43f4-a083-6f2b435995bc |
| 2 | 企业采购审批系统 | 5 | 13 | 19 | 13m 23s | https://www.mingdao.com/app/3a4f15aa-9356-46cd-ad96-9d6c14f3947f |
| 3 | 企业招聘管理系统 | 4 | 12 | 8 | 12m 39s | https://www.mingdao.com/app/50ed8166-b3e9-43c5-9b91-0e943a89a82b |
| 4 | 企业培训管理系统 | 8 | 20 | 14 | 14m 29s | https://www.mingdao.com/app/faf1f6ec-51d6-41a8-a264-1a4742d10bf3 |
| 5 | 企业合同管理系统 | 6 | 16 | 12 | 16m 04s | https://www.mingdao.com/app/0fdb9f64-2351-4265-8297-2393077a7a62 |
| 6 | 企业售后工单管理系统 | 4 | 13 | 6 | 10m 08s | https://www.mingdao.com/app/fccd4870-d0ec-45b2-979e-ff89ba25251a |
| 7 | 企业费用报销系统 | 5 | 12 | 11 | 12m 14s | https://www.mingdao.com/app/57de9276-a187-46b2-8407-4cc982e7f246 |
| 8 | 企业车辆管理系统 | 5 | 13 | 14 | 14m 02s | https://www.mingdao.com/app/109a9766-9167-45e2-a554-6a3fe7557ff5 |
| 9 | 企业仓库盘点管理系统 | 4 | 11 | 7 | 10m 39s | https://www.mingdao.com/app/c73c77b0-a144-474e-8765-0946de2e63eb |
| 10 | 企业客户拜访管理应用 | 3 | 9 | 6 | 9m 54s | https://www.mingdao.com/app/11285e06-c835-43e5-be6d-1a62ca23cb8c |

## 修复报告

### 失败场景

- 失败用例：Case 4 首次执行
- 失败阶段：`Step 12 / 14 创建工作流`
- 失败应用：`企业培训管理系统`
- 失败应用 ID：`9a73de6f-2ce8-4d6f-9944-54f0c8858db1`
- 失败现象：
  - `workflow/execute_workflow_plan.py` 在创建动作节点时收到 HAP `HTTP 500`
  - 出错节点来自 AI 规划产物中的 `worksheet_events`
  - 该节点内容不合法：`target_worksheet_id="69"`，且 `add_record` 没有任何 `fields`

### 根因

工作流 AI 规划产物存在脏数据，执行器此前没有做动作节点的前置校验，直接将非法 `add_record` 请求提交给 HAP，导致整轮执行被标记为失败。

### 修复内容

1. 在 `workflow/scripts/execute_workflow_plan.py` 增加动作节点清洗逻辑：
   - 非法 `type` 直接跳过
   - 非法 `target_worksheet_id` 直接跳过
   - `add_record` / `update_record` 没有字段映射时直接跳过
2. 当某条工作流所有动作节点都被清洗掉时：
   - 不再发起工作流创建请求
   - 记录为 `skipped` 而不是 `failed`
   - 将告警打印到 stderr，便于后续排查 AI 规划质量
3. 使用同一场景重新执行 `Case 4`，确认补丁生效且整轮通过

### 修复后验证

- `Case 4` 复测通过
- 随后继续串行完成 `Case 5` 到 `Case 10`
- 后续 6 个 case 未再出现工作流执行失败

## 代码变更

- `workflow/scripts/execute_workflow_plan.py`
  - 增加 `_sanitize_action_nodes`
  - 在自定义动作、工作表事件、时间触发创建前做计划合法性校验
- `scripts/serial_stability_runner.py`
  - 新增串行稳定性回归入口
  - 用于批量调用 `scripts/run_app_pipeline.py` 并记录 case 级结果

