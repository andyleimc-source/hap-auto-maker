# 工作流节点注册中心

## 目录结构

```
workflow/nodes/
├── __init__.py        # 注册中心: NODE_REGISTRY, build_save_body()
├── _base.py           # 通用 base body 构建
├── record_ops.py      # 记录操作: 删除/获取/查询/校准
├── notify.py          # 通知: 站内通知/短信/邮件/推送
├── timer.py           # 延时: 时长/日期/字段时间
├── approval.py        # 审批
├── human.py           # 人工: 填写/抄送
├── flow_control.py    # 流程控制: 分支/条件/循环/中止/子流程
├── compute.py         # 运算: 数值运算/汇总
├── developer.py       # 开发者: JSON解析/代码块/API请求
└── ai.py              # AI: 文本/数据对象/Agent
```

## 节点清单 (27 种)

| 节点名 | node_type | typeId | actionId | 模块 | 验证 | 关键注意事项 |
|--------|-----------|--------|----------|------|------|-------------|
| 删除记录 | delete_record | 6 | 3 | record_ops | - | 需要 filters |
| 获取单条数据 | get_record | 6 | 4 | record_ops | ✓ | 需要 filters+sorts |
| 查询工作表 | get_records | 13 | 400 | record_ops | - | typeId=13 非 6 |
| 校准单条数据 | calibrate_record | 6 | 6 | record_ops | - | 需要 fields+errorFields |
| 发送站内通知 | notify | 27 | — | notify | ✓ | **用 sendContent 非 content** |
| 发送短信 | sms | 10 | — | notify | - | 用 content |
| 发送邮件 | email | 11 | 202 | notify | - | 用 content+title |
| 界面推送 | push | 17 | — | notify | - | **用 sendContent 非 content** |
| 延时一段时间 | delay_duration | 12 | 301 | timer | ✓ | **值在根级别非 timerNode** |
| 延时到指定日期 | delay_until | 12 | 302 | timer | - | |
| 延时到字段时间 | delay_field | 12 | 303 | timer | - | |
| 发起审批 | approval | 26 | — | approval | ⚠ | 创建成功但 publish 需 processNode |
| 填写 | fill | 3 | — | human | - | 需要 formProperties |
| 抄送 | copy | 5 | — | human | ✓ | **用 sendContent 非 content** |
| 分支 | branch | 1 | — | flow_control | - | 需 operateCondition 才能 publish |
| 分支条件 | branch_condition | 2 | — | flow_control | - | |
| 循环 | loop | 29 | 210 | flow_control | - | 自动创建子流程 |
| 中止流程 | abort | 30 | 2 | flow_control | - | 无需 isException |
| 子流程 | subprocess | 16 | — | flow_control | - | saveNode 跳过 |
| 数值运算 | calc | 9 | 100 | compute | ✓ | |
| 从工作表汇总 | aggregate | 9 | 107 | compute | - | 需要 appId |
| JSON 解析 | json_parse | 21 | 510 | developer | - | |
| 代码块 | code_block | 14 | 102 | developer | - | saveNode 跳过 |
| API 请求 | api_request | 8 | — | developer | - | saveNode 跳过 |
| AI 生成文本 | ai_text | 31 | 531 | ai | - | 需要 appId="" |
| AI 生成数据对象 | ai_object | 31 | 532 | ai | - | |
| AI Agent | ai_agent | 33 | 533 | ai | - | 需要 tools 数组 |

> 注: 新增记录(6/1)和更新记录(6/2)在 `execute_workflow_plan.py` 的 `add_action_nodes()` 中直接处理，不经过此注册中心。均已实测通过。

## 关键发现

1. **单选字段值必须完整 UUID** — 截断 key 被 HAP 静默丢弃
2. **通知/推送用 `sendContent`** — 非 `content`，短信/邮件用 `content`
3. **延时节点值在根级别** — `numberFieldValue` 等直接放 saveNode body，不嵌套 `timerNode`

## 用法

```python
from workflow.nodes import NODE_REGISTRY, build_save_body

# 查看所有节点
for name, spec in NODE_REGISTRY.items():
    print(f"{name}: typeId={spec['typeId']} verified={spec.get('verified')}")

# 构建 saveNode body
body = build_save_body("notify", process_id, node_id, worksheet_id, "通知", {
    "content": "hello",
    "accounts": [...]
})
```
