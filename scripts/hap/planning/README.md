# 规划层（Planning Layer）

## 设计理念

规划层是连接「注册中心」和「AI 规划」的桥梁：

```
注册中心                    规划层                        AI
worksheets/FIELD_REGISTRY → worksheet_planner.py → prompt → Gemini → validate → plan.json
views/VIEW_REGISTRY       → view_planner.py      → prompt → Gemini → validate → plan.json
charts/CHART_REGISTRY     → chart_planner.py      → prompt → Gemini → validate → plan.json
```

核心能力：
1. **从注册中心读取元数据** — 自动生成 AI prompt 中的类型说明
2. **字段分类** — 按类型(text/number/date/select)分组，推荐适合的图表/视图类型
3. **增强校验** — 不仅检查存在性，还检查类型兼容性

## 目录结构

```
scripts/hap/planning/
├── __init__.py              # 包入口
├── constraints.py           # 共用约束生成器（字段分类+类型推荐）
├── worksheet_planner.py     # 工作表+字段规划器
├── view_planner.py          # 视图规划+配置器
├── chart_planner.py         # 图表规划器
└── README.md
```

## 三个规划器

### 1. worksheet_planner.py — 工作表+字段规划

规划表名、字段、关联关系、创建顺序。利用 `worksheets/FIELD_REGISTRY`（15 种字段类型）。

| 函数 | 用途 |
|------|------|
| `build_enhanced_prompt()` | 从注册中心生成字段类型枚举 |
| `validate_worksheet_plan()` | 检查字段类型合法性、选项完整性、关联目标存在性 |

### 2. view_planner.py — 视图规划+配置

规划每个表的视图类型和名称，同时生成二次保存配置。利用 `views/VIEW_REGISTRY`（6 种视图）。

| 函数 | 用途 |
|------|------|
| `build_enhanced_prompt()` | 从注册中心+字段分类推荐视图类型 |
| `suggest_views()` | 根据字段自动推荐（有日期→甘特/日历，有单选→看板） |
| `validate_view_plan()` | 检查字段引用和类型约束 |

### 3. chart_planner.py — 图表规划

利用 `charts/CHART_REGISTRY`（17 种图表）。

| 函数 | 用途 |
|------|------|
| `build_enhanced_prompt()` | 包含类型约束+字段推荐 |
| `validate_enhanced_plan()` | 字段存在性+类型兼容性 |

## constraints.py — 共用约束生成器

| 函数 | 用途 |
|------|------|
| `get_chart_constraints()` | 17 种图表类型约束 |
| `classify_fields(controls)` | 将字段按 text/number/date/select 分类 |
| `suggest_chart_types(classified)` | 根据字段推荐图表 |
| `build_chart_type_prompt_section()` | 生成 prompt 段落 |

## 与现有代码的关系

| 现有文件 | 规划层对应 | 状态 |
|----------|-----------|------|
| `scripts/gemini/plan_app_worksheets_gemini.py` | `worksheet_planner.py` | 可迁移 |
| `scripts/hap/plan_worksheet_views_gemini.py` | `view_planner.py` | 可迁移 |
| `scripts/hap/plan_charts_gemini.py` | `chart_planner.py` | 可迁移 |
