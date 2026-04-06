---
name: Incremental ops feature
description: 增量操作特性进展：对已有应用做局部增删改查的 Skills + 脚本体系
type: project
---

当前已完成 Phase 1 + Phase 2（2026-04-03）。
注：2026-04-07 起工作流模块已下线，以下条目中的工作流脚本仅作历史记录。

**已创建文件：**
- `scripts/hap/incremental/__init__.py`
- `scripts/hap/incremental/app_context.py` — load_app_context() 获取应用完整上下文
- `scripts/hap/incremental/add_workflow.py` — 两阶段规划 + execute_workflow_plan 执行
- `scripts/hap/incremental/add_worksheet.py` — AI 规划字段 + V3 API 创建
- `scripts/hap/incremental/add_field.py` — AI 推荐类型 + SaveWorksheetControls 创建
- `scripts/hap/incremental/add_view.py` — AI 推荐 + SaveWorksheetView 创建
- `.claude/skills/hap-modify.md` — 统一增量入口 Skill

**Phase 3 待实施（todo.md P2）：**
- `incremental/modify_view.py` — 修改视图 advancedSetting
- `incremental/modify_workflow.py` — 增/改/删节点
- `incremental/add_chart.py` — 添加图表到页面
- `delete_view.py` — 从 delete_default_views.py 提取 CLI 封装

**Why:** 让应用创建后可对话式局部调整，不必重走全流程。
**How to apply:** 用户说"给应用加xxx"时，引导用 /hap-modify，调对应增量脚本。
