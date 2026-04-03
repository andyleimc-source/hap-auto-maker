# 规划层（Planning Layer）

## 设计理念

规划层是连接「注册中心」和「AI 规划」的桥梁：

```
注册中心                 规划层                     AI
charts/CHART_REGISTRY → constraints.py → prompt → Gemini → validate → plan.json
nodes/NODE_REGISTRY   → constraints.py → prompt → Gemini → validate → plan.json
```

核心能力：
1. **从注册中心读取元数据** — 自动生成 AI prompt 中的类型说明
2. **字段分类** — 按类型(text/number/date/select)分组，推荐适合的图表/节点类型
3. **增强校验** — 不仅检查存在性，还检查类型兼容性

## 目录结构

```
scripts/hap/planning/
├── __init__.py            # 包入口
├── constraints.py         # 共用约束生成器（图表+工作流+字段分类）
├── chart_planner.py       # 图表规划器
├── workflow_planner.py    # 工作流规划器
└── README.md
```

## 模块说明

### constraints.py — 约束生成器

从 `charts/` 和 `nodes/` 注册中心提取元数据，生成约束信息供 prompt 和校验使用。

| 函数 | 用途 |
|------|------|
| `get_chart_constraints()` | 返回 17 种图表类型的约束 dict |
| `get_node_constraints()` | 返回 27 种节点类型的约束 dict |
| `build_chart_type_prompt_section()` | 生成 AI prompt 的图表类型说明段落 |
| `build_node_type_prompt_section()` | 生成 AI prompt 的节点类型说明段落 |
| `classify_fields(controls)` | 将字段按 text/number/date/select 等分类 |
| `suggest_chart_types(classified)` | 根据字段分类推荐图表类型 |

### chart_planner.py — 图表规划器

| 函数 | 用途 |
|------|------|
| `build_enhanced_prompt(app_name, worksheets_info, target_count)` | 生成增强版图表规划 prompt |
| `validate_enhanced_plan(raw, worksheets_by_id)` | 校验 plan（字段存在性+类型兼容性） |

### workflow_planner.py — 工作流规划器

| 函数 | 用途 |
|------|------|
| `build_enhanced_prompt(app_name, worksheets_info, ca_per_ws, ev_per_ws, num_tt)` | 生成增强版工作流规划 prompt |
| `validate_workflow_plan(raw, worksheets_by_id)` | 校验 plan（节点类型合法性+跨表检查） |

## 与现有代码的关系

| 现有文件 | 规划层对应 | 关系 |
|----------|-----------|------|
| `plan_charts_gemini.py` | `chart_planner.py` | 现有代码可逐步迁移到使用增强 prompt/validate |
| `pipeline_workflows.py` | `workflow_planner.py` | 同上 |
| `plan_worksheet_views_gemini.py` | (待建) | 未来可添加 view_planner.py |
| `plan_app_sections_gemini.py` | (待建) | 未来可添加 section_planner.py |

## 用法示例

```python
from planning.chart_planner import build_enhanced_prompt, validate_enhanced_plan
from planning.constraints import classify_fields

# 1. 准备数据
worksheets_info = [{"worksheetId": "...", "worksheetName": "客户", "fields": [...]}]

# 2. 生成 prompt
prompt = build_enhanced_prompt("CRM系统", worksheets_info, target_count=10)

# 3. 调用 AI
response = gemini.generate(prompt)

# 4. 校验
validated_charts = validate_enhanced_plan(response, worksheets_by_id)
```
