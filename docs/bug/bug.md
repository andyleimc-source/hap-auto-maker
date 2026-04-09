# Bug Trace Log

## 2026-04-09 快速筛选配置回退导致加载异常

- 症状：
  - 自动创建的快速筛选缺少“允许选择数量 / 显示方式”等关键配置。
  - 视图加载时可能异常，或 UI 配置回退到不完整状态。
- 根因：
  - [pipeline_tableview_filters_v2.py](/Users/andy/Documents/coding/hap-auto-maker/scripts/hap/pipeline_tableview_filters_v2.py) 曾把 `fastFilters` 收敛成仅保留 `controlId` 的最小结构。
  - 这样虽然避免了直接透传 AI 噪声，但也丢掉了单选/多选字段必须具备的稳定 UI 配置。
- 固化规则：
  - 单选/下拉字段（type `9/11`）生成：
    - `filterType=2`
    - `advancedSetting={"direction":"2","allowitem":"1"}`
  - 多选字段（type `10`）生成：
    - `filterType=2`
    - `advancedSetting={"direction":"2","allowitem":"2"}`
  - 只要存在 `fastFilters`，必须同时写入：
    - `fastAdvancedSetting.enablebtn = "1"`
    - `fastEditAdKeys` 包含 `enablebtn`
- 约束：
  - 不再直接透传 AI 原始 `fastFilters.advancedSetting`，而是由代码按字段类型生成稳定默认值。
  - 该规则属于基础稳定性规则，后续禁止回退为“只写 controlId”的最小结构。

## 2026-04-09 英文应用视图名回落为中文

- 症状：
  - `--language en` 生成英文应用时，视图名仍为中文。
- 根因：
  - [view_recommender.py](/Users/andy/Documents/coding/hap-auto-maker/scripts/hap/planners/view_recommender.py) 的推荐 prompt 仍是中文模板，直接要求输出中文视图名称和理由。
- 固化规则：
  - 视图推荐必须读取运行时语言。
  - `language=en` 时，推荐 prompt 必须要求：
    - 视图名称为英文
    - 推荐理由为英文
  - 视图推荐链路不得依赖默认中文 prompt。
