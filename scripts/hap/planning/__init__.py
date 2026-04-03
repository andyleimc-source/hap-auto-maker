"""
规划层（Planning Layer）

从注册中心读取元数据，生成高质量的 AI prompt，产出结构化 plan JSON。

模块:
  - constraints.py       — 共用约束生成器（字段校验、类型匹配）
  - worksheet_planner.py — 工作表+字段规划（利用 worksheets/ 注册中心）
  - view_planner.py      — 视图规划+配置（利用 views/ 注册中心）
  - chart_planner.py     — 统计图规划（利用 charts/ 注册中心）
  - workflow_planner.py  — 工作流规划（利用 nodes/ 注册中心）
"""
