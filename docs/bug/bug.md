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

## 2026-04-09 英文应用仍残留中文 page / 分组 / chatbot / 默认视图

- 症状：
  - 英文应用中页面名仍出现中文，如 `发票业务全景`。
  - 应用分组仍出现 `仪表盘`、`全部`。
  - 对话机器人名称、简介、欢迎语仍可能回落为中文。
  - 工作表仍残留系统默认视图 `全部`。
- 根因：
  - `page`、`section`、`chatbot` 三条规划链路未完整透传 `language`，prompt 仍使用中文模板或中文固定默认值。
  - `GenerateChatRobotInfo`/fallback greeting 流程没有按语言兜底，导致平台生成内容可能继续偏中文。
  - 默认视图清理逻辑和注释分叉，只清理 `视图`/空名，没有稳定覆盖 `全部`/`All`。
- 固化规则：
  - `--language en` 必须贯穿 `pages`、`sections`、`chatbots`、`views` 规划与创建链路。
  - 英文应用默认命名固定为：
    - dashboard section: `Dashboard`
    - small-app catch-all section: `All Worksheets`
  - 默认系统视图识别集合固定为：
    - `全部`
    - `All`
    - `视图`
    - `View`
    - 空名
  - 只有当某工作表已经存在至少一个非系统视图时，才允许删除系统默认视图；否则保留，避免工作表无视图。

## 2026-04-09 视图配置校验误删 postCreateUpdates，导致日历 / 甘特 / 资源视图未完成初始化

- 症状：
  - 自动创建出的日历、甘特图、资源视图只生成了视图壳子，打开后仍弹出“选择开始/结束/资源字段”的初始化面板。
  - 同一问题在不同英文应用里重复出现，尤其是任务类工作表的 Calendar / Gantt / Resource 视图。
- HAR 证据：
  - [har/视图/日历视图.har](/Users/andy/Documents/coding/hap-auto-maker/har/视图/日历视图.har)
  - [har/视图/甘特图配置.har](/Users/andy/Documents/coding/hap-auto-maker/har/视图/甘特图配置.har)
  - [har/视图/资源视图.har](/Users/andy/Documents/coding/hap-auto-maker/har/视图/资源视图.har)
- 根因：
  - [view_configurator.py](/Users/andy/Documents/coding/hap-auto-maker/scripts/hap/planners/view_configurator.py) 的 `validate_view_config()` 曾把 `postCreateUpdates.advancedSetting` 中的所有字符串都当作“字段 ID 引用”检查。
  - 这会把资源视图里合法的普通配置值，例如：
    - `navshow = "0"`
    - `navfilters = "[]"`
    - `calendarType = "1"`
  - 误判为非法字段引用，并直接删除整条 `postCreateUpdates`。
  - 结果就是：
    - 资源视图丢失 `viewControl + navshow/navfilters`
    - 日历/甘特/资源视图的关键二次保存链被破坏
- 固化规则：
  - `postCreateUpdates` 校验只允许检查“真正应该是字段 ID”的键。
  - 普通枚举/开关/布局值不得再按字段 ID 校验。
  - 当前已识别的字段引用键包括：
    - 顶层：`viewControl`、`coverCid`、`layersControlId`、`resourceId`
    - `advancedSetting`：`begindate`、`enddate`、`startdate`、`resourceId`、`colorid`、`abstract`、`navtitle`、`milepost`、`latlng`
    - 特殊包装字段：`viewtitle`（`$fieldId$`）
  - 明确不是字段引用的键，例如：
    - `navshow`
    - `navfilters`
    - `calendarType`
    - `weekbegin`
    - `showall`
    - `hour24`
  - 这些值必须原样保留，禁止再触发整条更新删除。

## 2026-04-10 视图创建后又被后续步骤覆盖，导致日历 / 甘特 / 资源视图再次失效

- 症状：
  - 视图创建阶段显示成功，但最终打开应用时：
    - 日历视图再次弹出日期字段选择面板；
    - 甘特图再次弹出开始/结束字段选择面板；
    - 资源视图再次弹出资源/时间字段选择面板；
    - 个别表格自定义视图名称被冲成空串，最终只剩系统默认视图 `全部`。
- 根因：
  - [pipeline_tableview_filters_v2.py](/Users/andy/Documents/coding/hap-auto-maker/scripts/hap/pipeline_tableview_filters_v2.py) 会在视图创建后再次调用 `SaveWorksheetView`。
  - `SaveWorksheetView` 对 `advancedSetting` 不是字段级 merge；若后续仅写入快筛/颜色等局部配置，可能覆盖掉创建阶段已经写入的关键字段。
  - 尤其是日历视图若在该阶段再写 `fastFilters + enablebtn`，会把 `calendarcids / begindate / enddate` 覆盖掉。
  - 同时，个别自定义表格视图会在后续保存后出现“名称变空串”的副作用，导致默认视图删除逻辑误判为“当前还没有非系统视图”。
- 固化规则：
  - `view_filters` 阶段禁止再对日历视图(type `4`) 写入快速筛选。
  - 流水线必须增加“创建后完整性补修”步骤：
    - 日历视图缺 `calendarcids` 时自动回填；
    - 甘特图缺 `begindate/enddate` 时自动回填；
    - 资源视图缺 `viewControl/begindate/enddate` 时自动回填；
    - 自定义视图若名称为空，按视图创建结果中的计划名称回写。
  - 英文应用只要某张表存在非系统视图，就必须删除残留系统默认视图：
    - `全部`
    - `All`
    - `视图`
    - `View`
    - 空名
