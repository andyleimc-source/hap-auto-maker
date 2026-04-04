# TODO: 全量覆盖测试应用 — 验收清单

> 创建时间: 2026-04-04
> 目标：跑一个 20+ 张表的最大最全应用，逐项验收所有功能

## 测试应用：企业综合管理系统

执行命令：`python3 make_app.py --requirements "..."`（见 archive/plan）
执行结果报告：`data/outputs/execution_runs/`（跑完后填入）

---

## 验收结果（2026-04-04 自动执行 + 修复完成）

应用 ID：`bee6bcca-9943-4192-be76-86119476b4b5`
执行报告：`data/outputs/execution_runs/`

---

## 验收清单

### 字段类型（38 种）
- [x] 文本、富文本、自动编号、文本组合（TextCombine type=32 修复后添加）
- [x] 数值、金额（Money type=8 修复后添加）、大写金额（MoneyCapital type=25 修复后添加）、公式、公式日期（FormulaDate type=38 修复后添加）
- [x] 单选、多选、下拉
- [x] 附件、签名、二维码（QRCode type=43 修复后添加）
- [x] 日期、日期时间、时间
- [x] 成员、部门、组织角色
- [x] 关联记录、他表字段、子表、汇总
- [x] 地区（Area type=24 修复后添加）、定位
- [x] 级联选择（Cascade type=35 修复后添加）、等级、检查框、评分（Score type=47 修复后添加）
- [x] 链接（Link type=7 修复后添加）、手机号（Phone type=3 修复后添加）、座机、邮箱
- [x] 嵌入、分段、备注说明
- [x] 公式（数值）

> 注：deferred 字段批量添加原本全部失败（0/28），修复后逐条发送并使用数值类型码，共补充 28 个字段，135/135 全量到位。

### 视图类型（10 种）
- [x] 表格视图（含分组）
- [x] 看板视图
- [x] 层级视图
- [x] 画廊视图
- [x] 日历视图
- [x] 甘特图
- [x] 详情视图（员工档案，修复后添加）
- [x] 地图视图（客户信息，修复后添加）
- [x] 快速视图（任务管理，修复后添加）
- [x] 资源视图（任务管理，修复后添加）

> 共 67 个视图，覆盖全部 10 种类型（类型 0-9）。

### 图表类型（17 种，超出原计划 15 种）
- [x] 柱状图(1)、折线图(2)、条形图(7)、区域图(11，修复后添加)
- [x] 饼图(3)、环形图(4，修复后添加)
- [x] 漏斗图(5)
- [x] 雷达图(6，修复后添加)
- [x] 双轴图(8)
- [x] 散点图(9，修复后添加)
- [x] 数值图(10)
- [x] 进度图(12)
- [x] 透视表(13，修复后添加)
- [x] 词云图(14)、排行图(15)
- [x] 地图图表(16，修复后添加)
- [x] 关系图(17，修复后添加)

> 共 27 个图表，覆盖全部 17 种类型。

### 工作流节点类型
- [x] 工作表事件触发
- [x] 定时触发
- [x] 按日期字段触发
- [x] 新增记录
- [x] 更新记录
- [ ] 删除记录（本次 pipeline 未规划）
- [ ] 获取单条数据（本次 pipeline 未规划）
- [ ] 查询工作表（多条）（本次 pipeline 未规划）
- [x] 发送站内通知
- [x] 抄送节点
- [ ] 发送邮件（本次 pipeline 未规划）
- [ ] 分支网关 + 分支条件（本次 pipeline 未规划）
- [x] 延时（固定时长）
- [x] 延时到日期字段
- [ ] 循环节点（本次 pipeline 未规划）
- [ ] AI 生成文本（本次 pipeline 未规划）

> 共 112/113 个工作流已发布（1 个在创建时 HTTP 500 失败，位于文档库）。
> 触发类型全覆盖，节点类型覆盖 9/16，6 种高级节点类型待补充。

---

## Bug 修复任务（2026-04-04）

> 应用：企业综合管理系统 `bee6bcca-9943-4192-be76-86119476b4b5`
> 入口：https://www.mingdao.com/app/bee6bcca-9943-4192-be76-86119476b4b5

### Bug 列表

- [x] **Bug 1**：考勤记录 - 「每日工时甘特图」视图未设置开始/结束日期字段 → 已修复：`create_views_from_plan.py` 加入 `auto_complete_post_updates`，甘特图自动从 view 字段提取 begindate/enddate 二次保存
- [x] **Bug 2**：考勤记录 - 「按是否迟到看板」布尔字段不适合看板 → 已修复：`view_planner.py` 限制看板只推荐 type=9/11 的单选字段，排除 type=36（检查框）；prompt 规则也已更新
- [x] **Bug 3**：统计图页面 - 多个图表无法正常渲染 → **根因：reportType 映射大面积错误**（代码中 12 个 reportType 与 HAP 实际不一致）。通过浏览器抓包校正全部 15 种图表映射，重写 `chart_config_schema.py` 及所有图表模块（`basic/pie/funnel/dual_axis/scatter/number/table/radar/special.py`），修复 `_base.py` 通用参数（showFormat/dataSource/advancedSetting/filter），更新 `chart_planner.py` 和 `constraints.py` 中的旧引用。创建「全类型图表验证」页面（15 种图表全部渲染正常）
- [x] **Bug 4**：层级视图 - ① layersControlId 未二次保存 → 已修复：`auto_complete_post_updates` 自动补全；② prompt/规划中已加 latlng/layersControlId 说明
- [x] **Bug 5**：地图视图 - 未配置定位字段 → 已修复：`view_planner.py` 的 `suggest_views` 自动推荐地图视图并传 latlng；`build_create_payload` 将 latlng 写入 advancedSetting
- [x] **Bug 6**：资源视图 - 报错/配置不完整 → 已修复：`auto_complete_post_updates` 自动补全 resourceId/startdate/enddate 二次保存；prompt 中加入说明
- [x] **Bug 7**：「数据分析」分组为空 → 已修复：`plan_pages_gemini.py` 原来总取第一个分组（AI助手），现在优先匹配名含「数据/分析」的分组，确保统计页面放入数据分析分组
- [x] **Bug 8**：字段选项缺失 - `Dropdown` 类型未写入 options → 已修复：`create_worksheets_from_plan.py` 的 `build_field_payload` 将 `Dropdown` 加入 options 处理分支（原来只有 SingleSelect/MultipleSelect）
- [x] **Bug 9**：字段高级配置缺失 - 进度字段显示 `50.00` 而非 `50%` → 已修复：`create_worksheets_from_plan.py` 的 `build_field_payload` 现在读取 plan 里的 `unit`/`dot` 并写入 advancedSetting；`worksheet_planner.py` prompt 要求 AI 填写这两个字段

---

### 整体验收
- [x] 应用创建成功（无报错）
- [x] 20 张以上工作表均可打开（共 20 张）
- [x] 所有视图正常渲染（67 个视图，10 种类型）
- [x] 图表页面正常展示（27 个图表，15 种类型，reportType 映射已全部校正）
- [x] 全类型图表验证页面（15 种图表全部渲染正常，含造数验证）
- [x] 工作流已发布（112/113，1 个创建失败已知）
- [x] 关联关系正确建立（14 处关联，含子表和汇总）

### 导航结构
- [x] 7 个分组：AI助手、人事中心、项目协作、客户销售、行政后勤、知识与流程、数据分析
- [x] 4 个 AI 对话机器人（AI助手分组）
- [x] 2 个统计页面（人力资源洞察、销售业绩分析）
- [x] 1 个验证页面（全类型图表验证，15 种 reportType 全覆盖）
- [x] 视图注册表完善（9 种视图 HAR 抓包，advancedSetting 键从 5-6 个增至 13-30 个）
- [x] 全类型视图验证表（9 种视图全部创建成功，含造数验证）

## 工作流规划师质量提升（进行中）

> 目标：让工作流规划师生成的工作流具有**实际业务意义**且**节点参数完整正确**

### 问题 1：工作流缺乏业务意义
- [ ] 研究当前规划师 prompt（`planning/workflow_planner.py`）的输出质量
- [ ] 对比"好的工作流"应该长什么样（触发条件合理、节点链路有业务逻辑、字段映射正确）
- [ ] 优化 prompt，让 AI 规划出真正有用的工作流（而不是为了创建而创建）

### 问题 2：节点参数配置不完整
- [ ] 当前 record_ops.py 对 typeId=6 返回 None（跳过 saveNode），导致新增/更新记录节点无字段映射
- [ ] 触发节点必须传完整 controls 数组（已发现并记录）
- [ ] 新增/更新记录的 fields 需要有实际的 fieldValue（静态值或引用 `$nodeId-fieldId$`）
- [ ] 通知类节点需要有实际的 sendContent/accounts
- [ ] 延时节点需要有合理的时间配置
- [ ] 分支节点需要有实际的 operateCondition

### 验证方法
- [ ] 用规划师为"企业综合管理系统"重新生成工作流
- [ ] 逐个打开工作流编辑器检查节点配置
- [ ] 尝试发布（publish）验证配置完整性
- [ ] 在应用中触发工作流，验证实际执行效果
