# HANDOFF — 四大规划师集成与验证

> 更新时间: 2026-04-03（今日 36/36 全部测试通过）
> 测试应用: CRM客户管理系统
> app_id: `f11f2128-c4de-46cb-a2be-fe1c62ed1481`
> 应用链接: https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481
> 分支: feat/v2.0

---

## 四个验证链接（目视确认用）

| 类型 | 链接 | 状态 |
|------|------|------|
| (a) 全节点工作流 | https://www.mingdao.com/workflowedit/69cf8883ff333071d406dfa2 | 21种节点 ✓ |
| (b) 全视图工作表 | https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481/69ce832640691821042c6e79/69cf74eef9434db36c6e0816 | 11种视图 ✓ |
| (c) 全字段工作表 | https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481/69ce832640691821042c6e79/69cf74eef9434db36c6e0816 | 38种字段 ✓ |
| (d) 全图表页面 | https://www.mingdao.com/app/f11f2128-c4de-46cb-a2be-fe1c62ed1481/69ce825c4e5c3d9aa799d979/69cf23ea0a5c9f9c3bdf1f16 | 17种图表 ✓ |

---

## 架构概览

```
注册中心 (4 个)
├── scripts/hap/worksheets/   38 种字段类型（全部实测 ✓）
├── scripts/hap/views/        11 种视图类型（全部实测 ✓）
├── scripts/hap/charts/       17 种图表类型（全部实测 ✓）
└── workflow/nodes/            30 种工作流节点（全部实测 ✓）

规划层 scripts/hap/planning/   ← 核心重构目标（四大规划师）
├── worksheet_planner.py      已实现，待集成 pipeline
├── view_planner.py           已实现，待集成 pipeline
├── chart_planner.py          已实现，待集成 pipeline
└── workflow_planner.py       已实现，待集成 pipeline

执行层（已稳定）
├── create_worksheets_from_plan.py
├── create_views_from_plan.py
├── create_charts_from_plan.py
└── execute_workflow_plan.py
```

---

## 一、工作流节点 — 30 种全部实测通过 ✓

### 关键修正记录（今日发现）

1. **API 字段名纠错**：saveNode 用 `nodeId`/`flowNodeType`，文档里写的 `id`/`typeId` 是错的
2. **timer.py 结构 BUG**：延时到日期(302)/字段(303) 需嵌套在 `timerNode` 对象内，而非平坦结构（301 才用平坦）
   ```json
   "timerNode": { "actionId": "302", "executeTimeType": 0, "number": 0, "unit": 1, "time": "08:00" }
   ```
3. **界面推送 pushType 必填**：typeId=17 必须传 `pushType=2` 或 `3`，传 0/1 返回 HTTP 500
4. **中止流程返回空 body**：typeId=30 saveNode 返回 HTTP 200 + 空 body，这是成功标志（非错误）
5. **分支网关自动创建 3 节点**：add typeId=1 服务端自动返回网关+2条件，不需要单独 add typeId=2
6. **`sendContent` vs `content`**：通知(27)/推送(17) 用 `sendContent`；短信(10)/邮件(11) 用 `content`

### 待办（仅代码修复，API 已验证）

- [x] **timer.py 修复**：`workflow/nodes/timer.py` 中 actionId=302/303 的 build() 已改为 timerNode 嵌套结构（2026-04-03）
- [ ] **新增跨表记录节点**：新增记录(跨表)的 `$nodeId-fieldId$` 引用格式待研究

---

## 二、字段类型 — 38 种全部创建成功 ✓

### 待优化（非阻塞）

- [ ] 部分字段缺少 `advancedSetting` 详细配置（公式表达式、级联数据源）
- [ ] SubTable(34) 创建后需配置子表字段
- [ ] OtherTableField(30) 和 Rollup(37) 需关联字段存在才有意义

---

## 三、视图类型 — 11 种全部实测通过 ✓

### 关键修正记录（今日发现）

1. **二次保存必须带 `editAttrs` + `editAdKeys`**，否则高级配置不生效
2. **`calendarcids` 须为 JSON 字符串**（非对象）：`[{"begin":"fieldId","end":"fieldId"}]`
3. **资源视图配置**：`resourceId`/`startdate`/`enddate` 均为字段 controlId 字符串
4. **地图视图**：`advancedSetting.latlng = controlId`（定位字段）

### 待优化（非阻塞）

- [ ] `normalize_views()` 扩展支持 viewType 6-9 的自动补全

---

## 四、统计图表 — 17 种全部实测通过 ✓

### 关键修正记录

1. **Referer 必须包含 pageId**：`saveReportConfig` 的 Referer 需 `app/{appId}/{pageId}`
2. **数值图 xaxes.controlId=null**：不需要维度字段
3. **双轴图需 yreportType**：默认第二轴为折线(2)

---

## 五、四大规划师 — 集成进度（见 PLAN.md）

| 规划师 | 集成状态 | 说明 |
|--------|---------|------|
| worksheet_planner.py | ✅ 已集成 | `plan_app_worksheets_gemini.py` 改用 `build_enhanced_prompt` + `validate_worksheet_plan`，含 log |
| view_planner.py | 🔶 部分集成 | `plan_worksheet_views_gemini.py` `build_prompt` 内注入注册中心类型+字段推荐（兜底降级） |
| chart_planner.py | ✅ 已集成 | `plan_charts_gemini.py` 非 system_fields_only 路径改用 `build_enhanced_prompt` |
| workflow_planner.py | ❌ 待集成 | `pipeline_workflows.py` build_prompt 改造量大，暂未替换 |

详细集成计划见 PLAN.md「四大规划师重构」章节。

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| `scripts/hap/planning/` | 四大规划师（核心重构目标） |
| `workflow/nodes/` | 30 种节点注册中心 |
| `scripts/hap/worksheets/field_types.py` | 38 种字段注册中心 |
| `scripts/hap/views/view_types.py` | 11 种视图注册中心 |
| `scripts/hap/charts/` | 17 种图表注册中心 |
| `scripts/test_wf_p0.py` | 工作流 P0 验证脚本（9种） |
| `scripts/test_wf_p1p2.py` | 工作流 P1+P2 验证脚本（11种） |
| `scripts/test_views_advanced.py` | 视图高级配置验证脚本 |
| `scripts/test_charts_all.py` | 图表全类型验证脚本（12种） |
| `data/api_docs/workflow/workflow-node-configs.md` | saveNode body 录制文档 |
