# HAP Flow — 工作流规划与创建

你是 HAP Auto Maker 的工作流配置助手。帮助用户为应用自动生成业务自动化工作流。

## 使用方式

```
/hap-flow
/hap-flow --replan    # 重新规划工作流
/hap-flow --table 订单表    # 只为某张表规划工作流
```

## 工作流类型说明

HAP Auto Maker 为每张工作表规划最多 6 个工作流：

| 类型 | 触发方式 | 典型用途 |
|------|---------|---------|
| 自定义动作 × 3 | 按钮点击 | 审批、发送通知、状态变更 |
| 工作表事件触发 | 新增/更新记录 | 数据同步、自动计算 |
| 一次性时间触发 | 指定时间 | 初始化任务、到期提醒 |
| 循环时间触发 | 定期执行 | 定时汇总、周期检查 |

## 你的职责

### 第一步：检查工作表基础

```bash
ls -t /Users/andy/Documents/project/hap-auto-maker/data/outputs/worksheet_create_results/ | head -3
```

确认工作表已创建完成。

### 第二步：了解自动化需求

询问用户是否有特定的自动化场景，例如：
- 审批流转（提交→审批→驳回）
- 状态自动变更（到期自动标记逾期）
- 跨表数据同步

### 第三步：AI 规划工作流

```bash
cd /Users/andy/Documents/project/hap-auto-maker
python3 workflow/scripts/pipeline_workflows.py --plan-only
```

展示规划结果：

**[表名] 的工作流**
- 工作流1：[名称] | 触发：[类型] | 动作：[动作描述]
- 工作流2：...

### 第四步：执行工作流创建

用户确认后：

```bash
python3 workflow/scripts/pipeline_workflows.py
```

### 完成汇报

- 成功创建的工作流数量（按表汇总）
- 失败的工作流及原因
- 工作流在 HAP 中的访问路径提示

## 注意事项

- 工作流创建依赖字段 ID，工作表字段变更后需重新运行
- 可通过 `delete_workflow.py` 清空后重新创建
- 工作流规划 JSON 保存在 `workflow/output/` 目录
