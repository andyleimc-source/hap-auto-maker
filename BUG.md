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

## [BUG-011] 所有工作表堆积在仪表盘分组，未被正确分组
- **状态**: resolved
- **现象**: 应用创建后，工作表全部在"仪表盘"分组，其他分组为空，UI 显示无分组
- **根因**: `create_sections_from_plan.py` `run_mode_two` 中 `sourceAppSectionId` 固定取"应用第一个分组"。多次重试后工作表实际分布在各种分组，但 `RemoveWorkSheetAscription` 要求 `sourceAppSectionId` 精确匹配工作表当前所在分组，不匹配时 API 返回 `state=1`（静默成功）但实际不移动
- **修复**:
  - `scripts/hap/executors/create_sections_from_plan.py`：新增 `get_worksheet_to_section_map()` 从 `GetApp` 实时查询每张工作表的真实分组 ID，移动时用工作表实际所在分组作为 `sourceAppSectionId`；已在目标分组则跳过（不重复调用 API）
- **验证**: 手动将 `bede25d2` 应用"仪表盘"中堆积的 44 张工作表（第一批创建）按名称移到对应分组，31/31 移动成功，13 张聊天机器人/分析页正确留在仪表盘
- **关联 commit**: 2c8d843

---

## [BUG-010] add_record 日期字段写入 Invalid date
- **状态**: resolved
- **现象**: 工作流 `add_record` 节点中日期/日期时间字段显示 `Invalid date`，无法正常写入
- **根因**: AI 规划师（Phase 2）输出 `{{NOW}}`/`{{NOW_DATE}}`/`{{NOW_DATE_TIME}}` 等占位符作为日期字段值。执行层 `_build_fields` 只处理 `{{trigger.xxx}}` 格式，对 `NOW` 系列占位符不做任何转换，直接原样写入 HAP API，HAP 无法识别，渲染为 `Invalid date`
- **正确格式（抓包确认）**: 日期字段"当前时间"需用系统节点结构：`{"fieldValueId":"nowTime","nodeId":"5d39140d381d42d20db0c4da","nodeName":"系统","fieldValueName":"当前时间","fieldValueType":<15或16>,"nodeTypeId":100,"appType":100}`
- **修复**:
  - `workflow/scripts/execute_workflow_plan.py`：`_build_fields` 检测 `{{NOW}}`/`{{NOW_DATE}}`/`{{NOW_DATE_TIME}}`/`{{CURRENT_DATE}}` 等，自动转换为 HAP 系统节点"当前时间"格式，`fieldValueType` 跟随字段 type（15 或 16）
  - `workflow/scripts/pipeline_workflows.py`：prompt 明确禁止这些占位符，说明日期字段留空 `""` 即可
- **验证**: 单元测试确认 `{{NOW_DATE}}` → type=15 系统节点、`{{NOW}}` → type=16 系统节点、普通文本和触发器变量格式均不受影响

---

## [BUG-009] date_trigger 工作流无动作节点（仅有触发器）
- **状态**: resolved
- **现象**: 日期字段触发工作流（如"患者生日祝福提醒"）创建后只有触发节点，没有任何动作节点，工作流没有业务含义
- **根因**: `create_date_trigger` 函数只创建了工作流进程、配置了触发节点，但完全缺少调用 `add_action_nodes` 的逻辑。相比之下，`create_worksheet_trigger`、`create_time_trigger`、`create_custom_action` 均已正确调用 `add_action_nodes`，唯独 `create_date_trigger` 遗漏
- **修复**:
  - `workflow/scripts/execute_workflow_plan.py`：`create_date_trigger` 中补充调用 `_sanitize_action_nodes` 和 `add_action_nodes`（与其他触发类型保持一致），返回值加入 `action_nodes` 和 `warnings` 字段
- **验证**: 向现有工作流 `69d2d8351fd8fd2ab3cc2259`（startNodeId: `69d2d8351fd8fd2ab3cc225a`）手动调用 `add_action_nodes` 添加通知节点，`flowNode/add → status=1`、`flowNode/saveNode → status=1`，节点 `69d302e71fd8fd2ab3d0cc16` 成功创建

---

## [BUG-012] 视图重复（同名视图出现两次）
- **状态**: 代码已修复，**未验证**（需重跑 pipeline 确认）
- **现象**: 同一工作表下出现两个完全相同的视图（如"看板视图"出现两次）
- **根因**: `plan_worksheet_views_gemini.py` 的 `fetch_worksheets` 从 GetApp 获取应用所有工作表。当 pipeline 因某步骤失败多次重试时，会产生多批次同名工作表（例如 44+35=79 张）。视图规划对所有 79 张工作表各规划一次，导致同名工作表各生成一套视图，最终在应用中重复出现。
- **修复**:
  - `plan_worksheet_views_gemini.py`：`fetch_worksheets` 末尾按工作表名称去重（保留同名中最后一个，即最新批次），并打印去重日志
- **待验证**: 重跑 pipeline，检查每张工作表的视图是否不再重复

---

## [BUG-013] 对话机器人数量过多
- **状态**: 代码已修复，**未验证**（需重跑 pipeline 确认）
- **现象**: AI 规划生成过多对话机器人（如 5-8 个），超出实际需求
- **根因**: `plan_chatbots_gemini.py` 中 prompt 只要求"至少 1 个"，无上限约束，AI 倾向于为大型应用规划过多机器人
- **修复**:
  - `plan_chatbots_gemini.py`：prompt 改为"1-3 个，根据应用复杂度决定，最多不超过 3 个"；`normalize_proposals` 加入截断逻辑，超过 3 个时取前 3 个

---

## [BUG-014] 层级视图未被创建（AI 忽略自关联字段推荐）
- **状态**: resolved
- **现象**: 工作表有自关联字段（type=29，dataSource==本表ID），`suggest_views` 也推荐了层级视图，但最终创建的视图列表里没有 viewType=2（层级视图）
- **根因**: `suggest_views` 将层级视图作为"推荐视图"文本注入 prompt，AI Phase 2 可以自行决定是否采纳。实测 AI 经常忽略推荐，转而规划其他视图类型（如看板、日历、画廊）。`normalize_views` 后处理阶段也未做强制补全
- **修复**:
  - `plan_worksheet_views_gemini.py`：`normalize_views` 末尾加守卫逻辑：若 `worksheet_id` 非空、检测到自关联字段（`_find_self_relation_field`）、且 AI 输出中无 viewType=2，则自动追加层级视图，并填写 `layersControlId=自关联字段ID`
- **验证**: 手动在「知识库」工作表创建记录，通过 `update_row_relation` 设置父子关系（10条记录，2个根节点），层级知识库视图中正确展示两级层次结构

---

## [BUG-015] mock data 父子关系关联字段格式错误（"已删除"）
- **状态**: resolved
- **现象**: 创建记录时传入关联字段 `value: [{"sid": rowId}]`，关联显示"已删除"；正确格式应为 `value: [rowId字符串]`
- **根因**: 手动测试时混淆了字段写法。`update_row_relation` 函数本身已正确使用 `[target_row_id]` 格式（字符串数组），pipeline 代码（`write_mock_data_from_plan.py`）走 `update_row_relation` 是正确的，不需要修改
- **关键规则**: HAP V3 关联字段写入时 `value` 应为 `["rowId字符串"]`，不是 `[{"sid":"rowId"}]`；不能关联不存在的记录，必须先用 list API 确认目标 rowId 真实存在
- **验证**: 通过 PATCH 先清空损坏关联，再用 `update_row_relation` 重新建立，10条记录全部关联成功，层级视图正确显示两级

---

## [BUG-003] AI 响应超时断连
- **状态**: resolved
- **现象**: Step 2 卡很久后抛出 `ConnectionError` 或 `ReadTimeout`
- **根因**: 大规模工作表（10+ 张）规划时响应体大，non-streaming 连接容易断
- **修复**: 使用 `generate_content_stream` 替换 `generate_content`（commit 8871516）
