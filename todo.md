# TODO: 增量操作能力 — 增删改查全部局部操作

> 项目最重要的待实现特性之一
> 创建时间: 2026-04-03
> 状态: 待实施（另一个 CC 正在爬完整脚本，接口补全后再开工）

## Context

当前项目只支持"一次性生成完整应用"（`make_app.py` → Wave 1-7 全流程）。需要在应用搭建完成后，还能通过对话对应用做**增删改查**全维度的局部操作。

## 方案：Skills + 轻量编排脚本

用 Skill 做对话引导 + 意图路由，用编排脚本（`scripts/hap/incremental/`）封装需要 AI 规划的复杂操作，简单 CRUD 直接调已有原子脚本或 mingdao MCP。

---

## 操作能力全景（增删改查 × 6 个对象）

### 工作表（Worksheet）

| 操作 | 实现方式 | 已有/新建 |
|------|---------|----------|
| **查** 列出应用所有工作表 | `list_app_worksheets.py` / `mcp__mingdao__get_app_worksheets_list` | 已有 |
| **查** 查看工作表结构（字段列表） | `get_worksheet_detail.py` / `mcp__mingdao__get_worksheet_structure` | 已有 |
| **增** 新增工作表（AI 规划字段） | `incremental/add_worksheet.py` → worksheet_planner + create_worksheets_from_plan | **新建** |
| **改** 修改工作表名称/图标 | `mcp__mingdao__update_worksheet` | 已有 (MCP) |
| **删** 删除工作表 | `delete_worksheet.py` | 已有 |

### 字段（Field）

| 操作 | 实现方式 | 已有/新建 |
|------|---------|----------|
| **查** 查看工作表字段 | `get_worksheet_detail.py` | 已有 |
| **增** 新增字段（AI 推荐配置） | `incremental/add_field.py` → field_config_schema + SaveWorksheetControls | **新建** |
| **改** 修改字段属性 | `update_worksheet_field.py` | 已有 |
| **删** 删除字段 | `delete_worksheet_field.py` | 已有 |

### 视图（View）

| 操作 | 实现方式 | 已有/新建 |
|------|---------|----------|
| **查** 查看工作表视图列表 | `mcp__mingdao__get_worksheet_structure`（含视图信息） | 已有 (MCP) |
| **增** 新增视图（AI 规划配置） | `incremental/add_view.py` → view_planner + pipeline_views | **新建** |
| **改** 修改视图配置（筛选/排序/分组） | `incremental/modify_view.py` → 编辑 advancedSetting | **新建** |
| **删** 删除视图 | `delete_default_views.py`（已有 delete_view 函数可复用） | 已有（需封装 CLI） |

### 工作流（Workflow）

| 操作 | 实现方式 | 已有/新建 |
|------|---------|----------|
| **查** 列出应用工作流 | `mcp__mingdao__get_workflow_list` | 已有 (MCP) |
| **查** 查看工作流详情 | `mcp__mingdao__get_workflow_details` | 已有 (MCP) |
| **增** 新增工作流（AI 规划节点） | `incremental/add_workflow.py` → workflow_planner + execute_workflow_plan | **新建** |
| **改** 修改工作流（加/改/删节点） | `incremental/modify_workflow.py` → workflow node registry + saveNode | **新建** |
| **删** 删除工作流 | `workflow/scripts/delete_workflow.py` | 已有 |

### 图表/页面（Chart/Page）

| 操作 | 实现方式 | 已有/新建 |
|------|---------|----------|
| **查** 查看页面及图表 | `page_get.py` | 已有 |
| **增** 新增图表到页面 | `incremental/add_chart.py` → chart_planner + pipeline_charts | **新建** |
| **增** 新增页面 | `page_create.py` | 已有 |
| **改** 修改页面内容 | `page_save.py` | 已有 |
| **删** 删除页面 | `page_delete.py` | 已有 |

### 数据记录（Record）

| 操作 | 实现方式 | 已有/新建 |
|------|---------|----------|
| **查** 查询记录列表 | `mcp__mingdao__get_record_list` | 已有 (MCP) |
| **查** 查看单条记录 | `get_row.py` / `mcp__mingdao__get_record_details` | 已有 |
| **增** 新增记录 | `mcp__mingdao__create_record` | 已有 (MCP) |
| **改** 更新记录 | `update_row.py` / `mcp__mingdao__update_record` | 已有 |
| **删** 删除记录 | `mcp__mingdao__delete_record` | 已有 (MCP) |

---

## 架构设计

```
用户对话 → Claude Code
  ├── /hap-build           (全量创建，已有)
  └── /hap-modify          (增量操作，新增)
        │
        ├── 【查询类】直接调已有脚本或 mingdao MCP
        │
        ├── 【AI 规划创建】调 incremental 编排脚本
        │    ├── 加工作表 → incremental/add_worksheet.py
        │    ├── 加字段   → incremental/add_field.py
        │    ├── 加视图   → incremental/add_view.py
        │    ├── 加工作流 → incremental/add_workflow.py
        │    └── 加图表   → incremental/add_chart.py
        │
        ├── 【修改类】
        │    ├── 改字段属性 → update_worksheet_field.py（已有）
        │    ├── 改工作表   → MCP update_worksheet（已有）
        │    ├── 改视图配置 → incremental/modify_view.py（新建）
        │    ├── 改工作流   → incremental/modify_workflow.py（新建）
        │    ├── 改记录     → update_row.py / MCP（已有）
        │    └── 改页面     → page_save.py（已有）
        │
        └── 【删除类】直接调已有脚本
             ├── 删工作表 → delete_worksheet.py
             ├── 删字段   → delete_worksheet_field.py
             ├── 删视图   → delete_view.py（需从 delete_default_views.py 提取）
             ├── 删工作流 → delete_workflow.py
             ├── 删页面   → page_delete.py
             └── 删记录   → MCP delete_record
```

---

## 需要新建的文件清单

### 共享模块（1 个）
- [x] `scripts/hap/incremental/__init__.py`
- [x] `scripts/hap/incremental/app_context.py` — 根据 app_id 获取完整应用上下文

### AI 规划创建脚本（5 个）
- [x] `scripts/hap/incremental/add_workflow.py` — 复用 workflow_planner + execute_workflow_plan
- [x] `scripts/hap/incremental/add_worksheet.py` — 复用 worksheet_planner + create_worksheets_from_plan
- [x] `scripts/hap/incremental/add_field.py` — 复用 field_config_schema（38 种字段注册中心）
- [x] `scripts/hap/incremental/add_view.py` — 复用 view_planner + pipeline_views
- [ ] `scripts/hap/incremental/add_chart.py` — 复用 chart_planner + pipeline_charts

### 修改编排脚本（2 个）
- [ ] `scripts/hap/incremental/modify_view.py` — 修改视图 advancedSetting
- [ ] `scripts/hap/incremental/modify_workflow.py` — 增/改/删节点，复用 30 种 node registry

### 删除视图 CLI 封装（1 个）
- [ ] `scripts/hap/delete_view.py` — 从 delete_default_views.py 提取 delete_view() 封装

### Skill 文件（1 个）
- [x] `.claude/skills/hap-modify.md` — 统一增量操作入口（增删改查全覆盖）

---

## 实施顺序

| 阶段 | 内容 | 新建文件 | 优先级 | 状态 |
|------|------|---------|--------|------|
| **Phase 1** | `app_context.py` + `add_workflow.py` + `hap-modify.md` skill | 3 | P0 | ✅ 完成 |
| **Phase 2** | `add_worksheet.py` + `add_field.py` + `add_view.py` | 3 | P1 | ✅ 完成 |
| **Phase 3** | `modify_view.py` + `modify_workflow.py` + `add_chart.py` + `delete_view.py` | 4 | P2 | 待实施 |

---

## 验证清单

对一个已创建的应用逐一测试：
- [ ] "这个应用有哪些表？" → 查询成功
- [ ] "加一个请假表" → 工作表 + 字段创建成功
- [ ] "给请假表加一个'审批人'字段" → 字段创建成功
- [ ] "把天数字段改成必填" → 修改成功
- [ ] "删掉测试字段" → 删除成功
- [ ] "加一个按状态分组的看板视图" → 视图创建成功
- [ ] "修改看板视图的筛选条件" → 修改成功
- [ ] "给请假表加一个审批工作流" → 工作流创建成功
- [ ] 全量 `/hap-build` 仍然正常工作（无冲突）
