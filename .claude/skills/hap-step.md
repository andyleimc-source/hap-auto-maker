# HAP Run Step — 单步执行与重跑

你是 HAP Auto Maker 的步骤执行助手。支持单独执行或重跑任意一个流程步骤，无需重跑整个流水线。

## 使用方式

```
/hap-step [步骤名]
/hap-step mock-data
/hap-step views
```

不带参数时，列出所有可用步骤供选择。

## 可用步骤列表

| 步骤名 | 说明 | 对应脚本 |
|--------|------|---------|
| `create-app` | 创建应用实例 | `pipeline_create_app.py` |
| `worksheets` | 创建工作表和字段 | `pipeline_worksheets.py` |
| `views` | 创建视图配置 | `pipeline_views.py` |
| `mock-data` | 生成测试数据 | `pipeline_mock_data.py` |
| `charts` | 创建统计图表页 | `create_pages_from_plan.py` |
| `roles` | 配置角色权限 | `pipeline_app_roles.py` |
| `chatbots` | 创建智能机器人 | `pipeline_chatbots.py` |
| `icons` | 匹配应用图标 | `pipeline_icon.py` |
| `repair-relations` | 修复关联字段一致性 | `apply_relation_repair_plan.py` |

## 执行流程

### 第一步：确认上下文

检查是否有可用的 requirement spec 和 app_id：

```bash
ls -t /Users/andy/Documents/project/hap-auto-maker/data/outputs/requirement_specs/ | head -3
ls -t /Users/andy/Documents/project/hap-auto-maker/data/outputs/app_authorizations/ | head -3
```

### 第二步：确认执行意图

告知用户：
- 即将执行的步骤
- 使用的 requirement spec（文件名 + 时间戳）
- 目标 app_id
- 是否会覆盖已有数据（造数步骤会追加数据）

等待用户确认后再执行。

### 第三步：执行步骤

```bash
cd /Users/andy/Documents/project/hap-auto-maker
python3 scripts/hap/[对应脚本] [参数]
```

实时汇报输出中的关键信息（成功/警告/错误行）。

### 第四步：结果确认

执行完成后：
- 展示成功/失败摘要
- 如有错误，自动触发 `/hap-fix` 分析原因
- 建议后续步骤

## 依赖关系提示

某些步骤有前置依赖，执行前自动检查：

- `views` 依赖 `worksheets` 完成
- `mock-data` 依赖 `worksheets` 完成
- `charts` 依赖 `worksheets` + `mock-data` 完成（可选）
- `repair-relations` 依赖 `mock-data` 完成
