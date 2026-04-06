# BUG.md — HAP Auto Maker 问题记录

---

## [BUG-001] creation_order 缺少工作表
- **状态**: resolved
- **现象**: `ValueError: 工作表规划未通过校验: creation_order 缺少工作表: 网点信息, 车辆信息 ...`
- **根因**: AI（fast tier）生成工作表时，`creation_order` 数组只列出有依赖关系的子集，未包含全部工作表名
- **修复**: `scripts/gemini/plan_app_worksheets_gemini.py` 中 `repair_plan()` 自动补全遗漏工作表名；Prompt 约束明确要求"creation_order 必须包含所有工作表名"
- **验证**: 重跑相同需求，Step 2 不再报 `creation_order 缺少工作表`

---

## [BUG-002] Playwright 认证失效
- **状态**: resolved（运维问题，非代码 bug）
- **现象**: 造数步骤失败，日志中有 `401` 或 `登录状态已失效`
- **根因**: 网页端 Cookie/Token 过期（通常 7 天）
- **修复**: `python3 scripts/auth/refresh_auth.py`

---

## [BUG-004] 表格视图行分组配置错误（groupView → groupsetting）
- **状态**: 代码已修复，**未验证**（需重跑 pipeline 确认）
- **现象**: 创建的"按XX分组"表格视图，打开分组面板显示空白，没有实际分组字段配置
- **根因**: 代码用 `advancedSetting.groupView` 配置行分组，但 `groupView` 是 navGroup（左侧导航筛选栏）的配置，与行分组完全无关。HAR 抓包确认真正的行分组字段是 `advancedSetting.groupsetting`，格式为 JSON 字符串数组 `[{"controlId":"...","filterType":11}]`，需配合 `editAdKeys: ["groupsetting","groupsorts","groupcustom","groupshow","groupfilters","groupopen"]` 二次保存
- **修复**:
  - `plan_worksheet_views_gemini.py`：两处 prompt 规则6改为 groupsetting 格式；`normalize_views` 自动补全改为写入 groupsetting
  - `view_config_schema.py`：删除错误的 groupView 行分组说明，新增 `GROUP_SETTING_FORMAT_NOTES`
  - `create_views_from_plan.py`：为 groupView 处理代码加注释说明其真实用途
- **待验证**: 重跑 pipeline，检查生成的分组视图的 `advancedSetting.groupsetting` 是否有值，打开分组面板能看到分组字段

---

## [BUG-005] 默认"全部"视图未被配置快速筛选和筛选列表
- **状态**: 代码已修复，**未验证**（需重跑 pipeline 确认）
- **现象**: 工作表默认视图"全部"没有快速筛选和筛选列表配置
- **根因**: 两个独立原因
  - **原因A**：`find_default_all_view` 用 `v.get("viewId")`/`v.get("viewType")` 读取视图，但 V3 API 实际返回字段名是 `id` 和 `type`，导致 viewId 始终为空，"全部"视图无法注入 targetViews
  - **原因B**：筛选规划 prompt 只说"仅针对 targetViews 中的视图输出"，未强制要求每个视图都必须输出，AI 可能跳过不输出，代码兜底用 `needFastFilters=False`
- **修复**:
  - `plan_tableview_filters_gemini.py`：`find_default_all_view` 兼容 V3 API 字段名（`id`/`type`）；两处 prompt 加入"每个视图必须输出，不得遗漏"强制规则；表格视图默认应配置快速筛选
- **待验证**: 重跑 pipeline，检查每个工作表"全部"视图的 fastFilters 和 navGroup 是否有实际配置

---

## [BUG-006] 视图类型单一（几乎只有表格/看板/甘特图/日历）
- **状态**: 代码已修复，**未验证**（需重跑 pipeline 确认）
- **现象**: 整个应用的视图几乎只有看板和分组表格，没有画廊、层级等类型
- **根因**: 两个独立原因
  - **原因A**：prompt 明文写"保守策略：绝大多数工作表只有1个列表视图就够了"，AI 严格遵守，22张表只生成18个视图
  - **原因B**：`suggest_views` 无画廊视图的自动推荐；画廊条件过严（"仅适合图片是核心内容的表"），医疗类工作表基本不满足
- **修复**:
  - `view_planner.py`：改为积极策略（每表1-4个视图），画廊条件改为"有附件字段(type=14)即可"，`suggest_views` 加入画廊推荐；Phase2 prompt 加入 groupsetting 说明
  - `plan_worksheet_views_gemini.py`：两处 prompt 更新画廊/层级/甘特图适用说明，删除"保守策略"措辞
- **待验证**: 重跑 pipeline，检查是否出现画廊视图（viewType=3），整体视图类型分布是否更多样

---

## [BUG-007] 工作流更新记录节点创建后字段映射为空
- **状态**: resolved
- **现象**: 创建工作流的「更新记录」节点后，HAP 编辑器中「更新字段」区域为空，节点显示「未设置可执行的动作」
- **根因**: 三层缺陷叠加
  1. **规划层校验缺失**：`_validate_single_node_config` 对 `add_record` 要求 ≥2 个字段，但 `update_record` 没有对应的非空检查，AI 输出 `fields:[]` 可通过 Phase 2 验证
  2. **执行层静默跳过**：`_sanitize_action_nodes` 发现 `update_record` 的 `fields` 为空时跳过该节点，但没有反馈机制触发重试，导致 `action_nodes_plan` 为空
  3. **兜底逻辑反效果**：`add_action_nodes` 在 `action_nodes` 为空时自动注入 `fields:[]` 的占位节点，绕过 sanitize 直接发到 HAP API
- **修复**:
  - `scripts/hap/planning/workflow_planner.py`：`_validate_single_node_config` 对 `update_record` 补充 `len(fields) < 1` 校验，Phase 2 验证阶段直接报错迫使 AI 重规划
  - `workflow/scripts/execute_workflow_plan.py`：`add_action_nodes` 中 `action_nodes` 为空时直接 `return []`，移除注入空字段占位节点的兜底逻辑
- **验证**: 在综合医院应用创建测试工作流「测试-更新记录字段验证」，更新患者姓名节点 `fields_count=1`，saveNode 返回 `status=1 msg='成功'`，编辑器中可见字段映射
- **关联**: GitHub Issue #2

---

## [BUG-008] 工作流通知节点变量未被识别（显示红色原始文本）
- **状态**: resolved
- **现象**: 通知节点内容中的变量显示为红色高亮的原始文本 `{{trigger.xxx}}`，未渲染为绿色 pill 标签
- **根因**: 两层缺陷叠加
  1. **变量格式错误**：HAP 通知节点变量格式必须是 `$startNodeId-fieldId$`，但代码直接把 AI 规划师输出的 `{{trigger.FIELD_ID}}` 原样写入 API，HAP 无法识别
  2. **sendContent 被 content 覆盖**：`execute_workflow_plan.py` 第 522 行（原）在注入时重新读 `node_plan.get("content")` 覆盖了 `sendContent`，第一个 bug 掩盖了第二个
- **根因来源**: HAR 抓包（`har/工作流/工作流-通知节点-插入变量.har`），确认前端 saveNode 请求 sendContent 格式为 `$69d3018696aa9cc0d301ad2e-69d2d1b1f93dfe2427d4ca16$`
- **修复**:
  - `workflow/scripts/execute_workflow_plan.py`：注入 `save_body[sendContent]` 前调用 `_resolve_field_value(plan_content, start_node_id)`，与 update_record 字段值处理保持一致
  - `_resolve_field_value` 函数注释更新，明确适用范围包含 sendContent/content
- **验证**: 创建测试工作流「TEST-修复验证-通知变量」（processId: 69d3018696aa9cc0d301ad2d），通知节点 sendContent 写入 `$startNodeId-fieldId$` 格式，HAP 编辑器正确渲染为绿色变量 pill
- **关联 commit**: 0c38d24

---

## [BUG-003] AI 响应超时断连
- **状态**: resolved
- **现象**: Step 2 卡很久后抛出 `ConnectionError` 或 `ReadTimeout`
- **根因**: 大规模工作表（10+ 张）规划时响应体大，non-streaming 连接容易断
- **修复**: 使用 `generate_content_stream` 替换 `generate_content`（commit 8871516）
