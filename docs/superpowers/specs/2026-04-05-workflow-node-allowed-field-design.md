# 工作流节点 `allowed` 字段设计

**日期**: 2026-04-05  
**目标**: 在 NODE_REGISTRY 里给每个节点加 `allowed` 字段，禁止 AI 规划时使用复杂/未就绪的节点类型，并在校验和执行层做相应过滤。

---

## 背景

当前问题：
- 哪些节点可供 AI 使用，散落在 `constraints.py` 的 prompt 文字和 `workflow_planner.py` 的校验里（手动 `discard("branch")`）
- `verified=False` 的节点有些是"测试过没问题但暂不开放"，有些是"完全没验证"，语义混用
- 需要一个独立的开关控制"是否允许 AI 规划时使用"

---

## 设计决策

| 问题 | 决策 |
|---|---|
| 在哪里声明禁用 | 每个节点定义里加 `"allowed": True/False` |
| `verified` 和 `allowed` 的关系 | 独立字段；`verified` 表示"技术上验证过"，`allowed` 表示"允许 AI 规划时使用" |
| 出现禁用节点时 | 从 plan 里过滤掉（不报错） |
| 过滤后 action_nodes 为空 | 跳过整个工作流（不创建） |

---

## 各节点初始 `allowed` 值

| 模块 | 节点 | verified | allowed | 理由 |
|---|---|---|---|---|
| record_ops | `delete_record` | False | False | 风险高，需 filters 配置 |
| record_ops | `get_record` | True | False | 只读查询，AI 无法正确配置 filters |
| record_ops | `get_records` | False | False | 同上 |
| record_ops | `calibrate_record` | False | False | 未验证 |
| notify | `notify` | True | **True** | 主力通知节点，稳定 |
| notify | `sms` | False | False | 需短信签名配置 |
| notify | `email` | False | False | 需邮件服务配置 |
| notify | `push` | False | False | 未验证 |
| timer | `delay_duration` | True | **True** | 稳定，简单延时 |
| timer | `delay_until` | True | False | AI 难以正确配置日期 |
| timer | `delay_field` | True | False | AI 难以正确配置字段引用 |
| approval | `approval` | False | False | publish 报 103，需子流程 |
| human | `fill` | False | False | 未验证 |
| human | `copy` | True | False | 需 selectNodeId，AI 无法正确引用上游节点 |
| flow_control | `branch` | False | False | 复杂，需 operateCondition |
| flow_control | `branch_condition` | False | False | 同上 |
| flow_control | `loop` | False | False | 自动创建子流程，复杂 |
| flow_control | `abort` | False | False | 未验证 |
| flow_control | `subprocess` | False | False | 未验证 |
| compute | `calc` | True | **True** | 稳定，数值运算 |
| compute | `aggregate` | False | False | 未验证 |
| developer | `json_parse` | False | False | 未验证 |
| developer | `code_block` | False | False | 未验证 |
| developer | `api_request` | False | False | 未验证 |
| ai | `ai_text` | False | False | 未验证 |
| ai | `ai_object` | False | False | 未验证 |
| ai | `ai_agent` | False | False | 未验证 |

**初始允许节点**（`allowed=True`）: `notify`, `delay_duration`, `calc`  
加上在 `execute_workflow_plan.py` 中直接处理（不经过 NODE_REGISTRY build）的：`update_record`, `add_record`

---

## 改动范围（4 处）

### 1. 节点定义文件（`workflow/nodes/*.py`）

每个节点的 spec 字典加 `"allowed": True/False`：

```python
# notify.py
"notify": {
    "typeId": 27,
    "name": "发送站内通知",
    "verified": True,
    "allowed": True,   # ← 新增
    "doc": "...",
},
"sms": {
    "typeId": 10,
    "name": "发送短信",
    "verified": False,
    "allowed": False,  # ← 新增
    "doc": "...",
},
```

### 2. `constraints.py` — `get_node_constraints()` 和 `build_node_type_prompt_section()`

`get_node_constraints()` 在返回的 types 字典里加入 `allowed` 字段：

```python
types[nt] = {
    "name": spec["name"],
    "typeId": spec["typeId"],
    "actionId": spec.get("actionId"),
    "verified": spec.get("verified", False),
    "allowed": spec.get("allowed", False),  # ← 新增
    "doc": spec.get("doc", ""),
}
```

`build_node_type_prompt_section()` 只列出 `allowed=True` 的节点（包括 `update_record`/`add_record` 硬编码节点）：

```python
def build_node_type_prompt_section() -> str:
    c = get_node_constraints()
    # 只列出 allowed=True 的节点
    allowed_node_types = {nt for nt, s in c["types"].items() if s.get("allowed")}
    # ...生成 prompt，只描述这些节点
```

### 3. `workflow_planner.py` — 校验函数

`validate_structure_plan()` 和 `validate_workflow_plan()` 从注册中心动态构建 `allowed_types`，不再手动 discard：

```python
def _get_allowed_types() -> set[str]:
    """从 NODE_REGISTRY 读取 allowed=True 的节点类型集合。"""
    constraints = get_node_constraints()
    allowed = {nt for nt, s in constraints["types"].items() if s.get("allowed")}
    allowed.update({"add_record", "update_record"})  # 直接执行层处理，始终允许
    return allowed
```

校验发现禁用节点时，不抛 ValueError，而是从 action_nodes 里过滤掉：

```python
for k, node in enumerate(nodes):
    node_type = node.get("type", "")
    if node_type and node_type not in allowed_types:
        # 过滤掉，记录警告
        filtered_nodes.append(node)  # 收集被过滤的
```

过滤后若 action_nodes 为空，整个工作流（custom_action / worksheet_event / time_trigger）从 plan 里移除。

### 4. 执行层（`execute_workflow_plan.py`）

当前已有 `no_valid_action_nodes` 跳过逻辑（第 699-705 行），过滤后空工作流会命中该逻辑，无需额外改动。

---

## 数据流

```
NODE_REGISTRY (allowed 字段)
    ↓
get_node_constraints()        → 输出 allowed 信息
    ↓
build_node_type_prompt_section() → Prompt 只列 allowed 节点，AI 不会生成禁用类型
    ↓
AI 输出 plan
    ↓
validate_structure_plan()     → 过滤掉禁用节点，空 action_nodes 的工作流从 plan 移除
    ↓
execute_workflow_plan.py      → 现有 no_valid_action_nodes 逻辑兜底
```

---

## 不在本次范围内

- `update_record` / `add_record` 没有在 NODE_REGISTRY 里注册，保持现状（执行层直接处理）
- 不修改 `execute_workflow_plan.py`（现有逻辑已足够）
- 不改变 `verified` 字段的语义
