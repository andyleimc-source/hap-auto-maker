# HANDOFF — 应用生成质量问题修复

> 生成时间: 2026-04-03
> 测试应用: CRM客户管理系统 (app_id: f11f2128-c4de-46cb-a2be-fe1c62ed1481)
> 应用链接: https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481
> 分支: feat/v2.0

---

## 共性根因（两个系统性缺陷）

所有问题归结为同一类模式的不同表现：

### 缺陷 A：创建了但没配完

很多实体（视图、工作流节点）只调了**创建接口**（`flowNode/add`、`SaveWorksheetView`），没有调**二次保存接口**（`flowNode/saveNode`、带 `editAttrs` 的 `SaveWorksheetView`）下发完整配置。HAP 的设计是"创建"和"配置"分两步，我们只做了第一步。

**受影响:** 甘特图视图、层级视图、工作流分支节点、通知节点、所有工作流 publish 失败

### 缺陷 B：规划了但没校验

AI 规划的 JSON 中引用的字段 ID、工作表 ID 没有在执行前做存在性校验，直接传给 API。字段不存在时 API 不报错但前端渲染失败。

**受影响:** 统计图"无法形成图表"、工作流创建失败（2/71）

---

## 问题清单（8 个）

### 问题 1: "未命名分组"仍然出现

**表现:** 导航栏出现"未命名分组"，里面放着 2 个统计页面和 2 个对话机器人。应该叫"仪表盘"或"数据分析"之类有业务含义的名称。

**根因:** `plan_app_sections_gemini.py` 的分组规划只考虑了工作表（worksheets），没有考虑统计页面（自定义页面）和对话机器人。这些非工作表项创建后被放到了系统默认的未命名分组。

**定位:**
- `scripts/hap/plan_app_sections_gemini.py:49-58` — `build_prompt()` 只遍历 worksheets 数组
- 统计页面在 Wave 6（Step 14）创建，机器人在 Wave 4（Step 10）创建，但分组规划在 Wave 2.5（Step 2c）就完成了，时间上不可能包含这些后创建的项

**修复方向:** 在分组规划时，prompt 中额外要求 AI 预留一个"仪表盘"/"数据分析"分组，供后续统计页面和机器人使用。或者在 Step 14/10 创建完成后，自动将它们移入已有的合适分组。

---

### 问题 2: 统计图显示"无法形成图表"

**表现:** 统计页面中部分图表显示"无法形成图表——构成要素不存在或已删除"。

**根因（缺陷 B）:** AI 规划的图表中 `xaxes.controlId` 引用了工作表中不存在的字段。`validate_plan()` 只校验了 worksheetId 存在性，**没有校验字段 ID 是否在该工作表中真实存在**。

**定位:**
- `scripts/hap/plan_charts_gemini.py:346-378` — `validate_plan()` 无字段级校验
- `scripts/hap/create_charts_from_plan.py` — 直接把未校验的 body 发给 API，无创建后验证
- 工作表的字段信息在 `worksheets_by_id[wsId]["fields"]` 中已有，只是没被用来校验

**修复方向:** 在 `validate_plan()` 中增加：对每个 chart，遍历 `xaxes.controlId` 和 `yaxisList[].controlId`，检查是否存在于对应工作表的字段列表中。`ctime`、`utime`、`record_count` 等系统字段需加白名单。不存在的字段直接 raise 让 AI 重新生成。

---

### 问题 3: 甘特图视图未配置完成

**表现:** 甘特图视图停在配置页面，要求选择"开始"和"结束"日期字段。

**根因（缺陷 A）:** 甘特图（viewType=5）创建后**必须二次保存** `begindate` 和 `enddate`。当前代码只在 plan 中存在 `postCreateUpdates` 时才执行二次保存，但 AI 经常不输出这个字段。

**定位:**
- `scripts/hap/create_views_from_plan.py:330-348` — postCreateUpdates 执行逻辑：只在 plan 中有时才跑
- `data/api_docs/private_view_api.md:173-188` — 甘特图二次保存规范：
  ```
  editAttrs: ["advancedSetting"]
  editAdKeys: ["begindate", "enddate"]
  advancedSetting.begindate: "开始日期字段ID"
  advancedSetting.enddate: "结束日期字段ID"
  ```
- `scripts/hap/plan_worksheet_views_gemini.py` — prompt 提到甘特图但没有**强制**要求输出 postCreateUpdates

**修复方向:** 在 `normalize_views()` 中（`plan_worksheet_views_gemini.py`），当 viewType=5 时，如果缺少 begindate/enddate 的 postCreateUpdates，自动从字段列表中找 type=15 或 type=16 的日期字段补全。参考已实现的分组视图自动补全模式。

---

### 问题 4: 层级视图（组织架构图）未配置完成

**表现:** 层级视图显示空白配置页面，未选择关联字段。

**根因（缺陷 A）:** 与问题 3 同理。层级视图（viewType=2）创建后**必须二次保存** `childType` 和 `layersControlId`。

**定位:**
- `data/api_docs/private_view_api.md:148-160` — 层级视图二次保存规范：
  ```
  editAttrs: ["childType", "layersControlId"]
  childType: 0
  layersControlId: "本表关联字段ID"（Relation 类型，dataSource = 本工作表 ID）
  ```
- 同样在 `plan_worksheet_views_gemini.py` 的 `normalize_views()` 中没有自动补全逻辑

**修复方向:** 在 `normalize_views()` 中，当 viewType=2 时，自动从字段中找 Relation 类型且 dataSource 等于本工作表 ID 的自关联字段，生成 postCreateUpdates。

---

### 问题 5: 工作表排序不对（订单明细不在订单旁边）

**表现:** "交易管理"分组下，左侧导航中订单和订单明细没有相邻排列。期望：主表（订单）在上，子表（订单明细）紧跟其后。

**根因:** `create_sections_from_plan.py` 模式二（移动工作表到分组）只关心"移到哪个分组"，不关心分组内的顺序。虽然 `sections_plan.json` 中 worksheets 数组有顺序，但移动时这个顺序丢失了。

**定位:**
- `scripts/hap/create_sections_from_plan.py:252-292` — 模式二移动逻辑，按 dict 迭代顺序而非 plan 中的顺序
- `sections_plan.json` 中的 `worksheets` 数组本身就有 AI 规划的顺序（通常是合理的），但代码没有保持

**修复方向:**
1. `plan_app_sections_gemini.py` prompt 中要求 AI 按业务逻辑排序（主表在前、明细/子表在后）
2. `create_sections_from_plan.py` 模式二移动时，按 `sections_plan` 中 worksheets 数组的顺序逐个移动
3. 如有排序 API（`UpdateSectionChildSort` 之类），移动后额外调一次

---

### 问题 6: 几乎所有工作流都是关闭状态（72/72 publish 失败）

**表现:** 82 个工作流全部显示"关闭"。日志: `[publish-verify] 补发布完成：成功 0，失败 72`。

**根因（缺陷 A 的连锁反应）:** `publish_process()` 调用 `process/publish` API 时返回 `errorNodeIds` 非空，HAP 拒绝发布含有配置错误节点的工作流。这与问题 7 是同一个根因——**节点配置不完整导致 publish 必然失败**。

**定位:**
- `workflow/scripts/execute_workflow_plan.py:116-142` — `publish_process()` 收到 errorNodeIds
- 日志: `errorNodes=['69ce899a9e34966050847bb8', '69ce899a599498a551bf3887']`
- 这些 ID 对应的是分支节点（空 operateCondition）和记录操作节点（空 fields）

**修复方向:** 这个问题的根本解决依赖于问题 7——只有节点配置完整了，publish 才能成功。当前的 retry/verify 补发布逻辑是治标不治本。

---

### 问题 7: 工作流节点太少且无配置参数

**表现:**
- 节点数量只有 2-3 个（prompt 要求 3-5 个）
- 分支节点显示"所有数据可进入该分支"— `operateCondition` 为空
- 记录操作节点没有可见的字段映射
- 通知节点没有内容

**根因（缺陷 A，多个子问题）:**

**(A) 分支节点条件为空:**
- `workflow/scripts/add_workflow_node.py:146-150` — 分支网关(typeId=1) saveNode 时 `flowIds: []`
- 分支条件(typeId=2) `operateCondition: []`（空数组）
- HAP 要求分支条件至少有一个有效 condition 对象，否则视为"配置不完整"

**(B) 非记录节点配置为空壳:**
- `add_workflow_node.py:237-240` — 通知节点: `content: ""`、`accounts: []`
- 虽然 `execute_workflow_plan.py` 中加了自动注入 accounts（触发者）和 content 的逻辑，但 content 来自 `node_plan.get("content")`，而 AI 规划中通常不输出 content 字段

**(C) 部分节点类型被跳过:**
- `execute_workflow_plan.py:388-391` — 如果 `NODE_CONFIGS` 中没有该类型，直接跳过不创建

**(D) AI 规划的节点缺少具体配置:**
- `pipeline_workflows.py` prompt 要求了 3-5 个节点，但没有要求 AI 为 branch 节点输出分支条件、为 notify 节点输出通知内容

**定位:**
- `workflow/scripts/add_workflow_node.py:96-250` — `build_save_node_body()` 各节点类型配置
- `workflow/scripts/execute_workflow_plan.py:283-440` — `add_action_nodes()` 节点创建流程
- `workflow/scripts/pipeline_workflows.py:480-540` — AI prompt 中的节点规则

**修复方向:**
1. **prompt 改造:** 要求 AI 为 branch 节点输出分支条件（哪个字段、什么值走哪个分支）；notify 节点输出 content
2. **saveNode 改造:** 分支条件不能为空——如果 AI 没给条件，应该不创建分支节点，或基于触发表字段生成默认条件
3. **空壳检测:** 创建节点后检查关键配置是否为空，空则 warn 或 fallback

---

### 问题 8: 工作流执行失败（2/71）

**表现:** 日志 "工作流成功：69 / 71，失败数：2"。

**根因（缺陷 B）:** 个别工作流的 AI 规划中引用了不存在的字段 ID 或工作表 ID，API 调用失败。

**修复方向:** 执行前增加字段/工作表 ID 存在性校验，过滤无效引用。

---

## 修复优先级

| 优先级 | 问题 | 原因 | 难度 |
|--------|------|------|------|
| **P0** | 6+7（工作流节点配置 → publish 失败） | 所有工作流不可用，影响面最大 | 高 |
| **P1** | 3+4（甘特图/层级视图二次保存） | 视图不可用 | 中（参考分组视图自动补全模式） |
| **P1** | 2（统计图字段校验） | 图表不可用 | 中 |
| **P2** | 1（未命名分组） | 体验问题 | 低 |
| **P2** | 5（工作表排序） | 体验问题 | 低 |

---

## 关键文件索引

| 文件 | 职责 | 涉及问题 |
|------|------|----------|
| `scripts/hap/plan_app_sections_gemini.py` | AI 规划应用分组 | 1, 5 |
| `scripts/hap/create_sections_from_plan.py` | 创建分组 + 移动工作表 | 1, 5 |
| `scripts/hap/plan_worksheet_views_gemini.py` | AI 规划视图 + normalize_views() | 3, 4 |
| `scripts/hap/create_views_from_plan.py` | 创建视图 + postCreateUpdates | 3, 4 |
| `scripts/hap/plan_charts_gemini.py` | AI 规划统计图 + validate_plan() | 2 |
| `scripts/hap/create_charts_from_plan.py` | 创建统计图 | 2 |
| `workflow/scripts/pipeline_workflows.py` | AI 规划工作流（prompt 定义） | 7 |
| `workflow/scripts/execute_workflow_plan.py` | 创建工作流 + 节点 + publish | 6, 7, 8 |
| `workflow/scripts/add_workflow_node.py` | 节点类型定义 + build_save_node_body() | 6, 7 |
| `data/api_docs/private_view_api.md` | 视图 API 文档（甘特图/层级视图二次保存规范） | 3, 4 |
| `data/api_docs/workflow/workflow-node-configs.md` | 工作流节点完整配置 schema（含 saveNode 请求体） | 6, 7 |
| `data/api_docs/chart_types.md` | 统计图 17 种类型定义 | 2 |

---

## 已有的相关修复（本轮之前已提交但未完全生效）

以下改动已在代码中但测试验证未通过，新会话修复时需注意这些代码已存在：

1. `create_sections_from_plan.py` — 创建时已改为传真实名称 + 改名重试 3 次（但问题 1 的根因不在这里）
2. `execute_workflow_plan.py` — 已加 publish-verify 验证步骤（但因问题 7 导致全部失败）
3. `plan_worksheet_views_gemini.py` — 已加看板视图 viewControl 自动补全 + 分组视图 groupView 自动补全（但甘特图/层级视图的补全还没加）
4. `plan_charts_gemini.py` — 已改为 8-12 个图表 + 17 种类型（但缺少字段校验）
5. `create_charts_from_plan.py` — 已扩展 REPORT_TYPE_NAMES 到 17 种 + 数值图/双轴图特殊处理
6. `pipeline_workflows.py` — prompt 已改为 3-5 个节点 + 通知节点要求 content（但 AI 不一定遵守）
7. `add_workflow_node.py` — typeId=17（界面推送）不再跳过 saveNode
