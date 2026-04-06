# Pipeline 实时摘要日志设计

## 背景

当前 pipeline 日志只有两档：verbose（子进程全部输出）和非 verbose（只有步骤开始/结束标记 + 30 秒心跳点）。缺少"摘要级"中间态，用户无法在运行时了解各步骤的具体成果。

## 目标

在非 verbose 模式下，实时显示每个步骤的关键成果摘要，包括工作表名称、字段信息、视图数量、工作流节点等。verbose 模式行为不变。

## 方案

采用「统一 summary 工具函数 + `[SUMMARY]` 前缀标记 + step_runner 过滤透传」方案。

## 核心机制

### 1. `utils.py` 新增 `log_summary()`

```python
def log_summary(msg: str) -> None:
    print(f"[SUMMARY] {msg}", flush=True)
```

所有子脚本通过 `from utils import log_summary` 调用，不再用裸 `print` 输出摘要信息。

### 2. `step_runner.py` 的 `reader()` 改造

当前行为：verbose 时透传所有 stdout，非 verbose 时全部吞掉。

改为：非 verbose 时，只透传 `[SUMMARY]` 开头的行，去掉前缀后加 4 空格缩进显示。

```python
SUMMARY_PREFIX = "[SUMMARY] "

def reader(pipe, bucket):
    for line in pipe:
        bucket.append(line)
        if verbose:
            print(line, end="", flush=True)
        elif line.startswith(SUMMARY_PREFIX):
            clean = line[len(SUMMARY_PREFIX):]
            print(f"    {clean}", end="", flush=True)
```

- `[SUMMARY]` 行用 4 空格缩进，和 `▶ Step` 的 2 空格缩进区分层级
- 多行摘要由子进程输出多条 `[SUMMARY]`，各自独立透传
- 30 秒心跳点 `.` 保持不变
- verbose 模式完全不受影响

### 3. 输出效果示例

```
  ▶ Step  2 / 14  规划工作表  [12s]
    规划完成，共 5 张：客户管理、订单记录、产品目录、供应商、库存
  ✓ Step  2 / 14  规划工作表  (8s, 总计 20s)
  ▶ Step  2 / 14  创建工作表  [20s]
    ✓ 工作表「客户管理」已创建（5 个字段）
      客户名称(文本) | 联系电话(电话) | 负责人(成员) | 创建时间(日期) | 状态(单选)
    ✓ 工作表「订单记录」已创建（3 个字段）
      订单号(自动编号) | 金额(金额) | 客户(关联)
  ✓ Step  2 / 14  创建工作表  (15s, 总计 35s)
```

## 各模块摘要规格

### 工作表规划 (`plan_app_worksheets_gemini.py`)

- 时机：AI 返回规划结果解析后
- 格式：`规划完成，共 5 张：客户管理、订单记录、产品目录、供应商、库存`

### 工作表创建 (`create_worksheets_from_plan.py`)

- 时机：每张表创建成功后
- 格式（两条 log_summary）：
  - `✓ 工作表「客户管理」已创建（5 个字段）`
  - `  客户名称(文本) | 联系电话(电话) | 负责人(成员) | 创建时间(日期) | 状态(单选)`

### 分组 (`create_sections_from_plan.py`)

- 时机：每个分组创建成功后
- 格式：`✓ 分组「销售管理」已创建（3 张表：客户管理、订单记录、产品目录）`

### 视图 (`waves.py` 中的 `_do_views_for_ws`)

- 时机：每张表的视图创建完成后
- 格式：`✓「客户管理」→ 3 个视图已创建`
- 注意：视图逻辑在 `waves.py` 中内联执行（Wave 3.5），不经过子进程。直接在 `_do_views_for_ws` ��调用 `log_summary()` 输出到主进程 stdout，无需 step_runner 过滤。

### 工作流 (`workflow/scripts/execute_workflow_plan.py`)

- 时机：每条工作流创建完成后
- 格式（两条 log_summary）：
  - `✓ 工作流「新客户通知」→ 客户管理 / 新增记录时触发 / 3 个节点`
  - `  发送通知 | 更新记录 | 审批`

### 统计图/Pages (`pipeline_pages.py` 或对应创建脚本)

- 时机：每个 Page 创建完成后
- 格式：`✓ Page「销售仪表盘」已创建（4 个图表：月度趋势、客户分布、销售排行、转化漏斗）`

### 角色 (`pipeline_app_roles.py`)

- 时机：角色创建完成后
- 格式：`✓ 角色已创建：管理员、销售经理、客服`

### 造数 (`pipeline_mock_data.py`)

- 时机：每张表造数完成后
- 格式：`✓「客户管理」已写入 10 条记录`

### 机器人 (`pipeline_chatbots.py`)

- 时机：机器人创建完成后
- 格式：`✓ 机器人「智能客服助手」已创建`

### 布局 / 视图筛选 / Icon / 导航风格

- 无需额外摘要，保持现有的 `✓ Step N` 即可

## 不改动的部分

- 现有所有子脚本的 debug 级 print/stderr 输出不做删减
- verbose 模式行为完全不变
- 执行报告 JSON 结构不变
- `PipelineContext` 和 `waves.py` 的编排逻辑不变
