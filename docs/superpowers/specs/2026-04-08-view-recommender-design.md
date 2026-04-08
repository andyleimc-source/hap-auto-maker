# 视图智能推荐系统设计

## 背景

现有视图规划采用"关键词规则 + AI 混合"模式：`suggest_views` 通过字段名关键词匹配（如"状态/阶段"触发看板）生成候选，再由 AI 做最终判断。这种方式的问题：

- 关键词规则覆盖不全，硬编码维护成本高
- AI 缺乏业务上下文（应用背景、工作表间关系），判断不够精准
- 两阶段串行（结构规划 → 配置规划），单表内无并行

## 目标

用 AI 语义推荐完全替代关键词规则。保留字段类型的硬约束（必要条件检查），软判断全部交给 AI（基于应用背景、工作表名称、字段语义）。同时实现工作表间并行、视图间并行，提升执行效率。

## 架构

### 并行模型

```
对每个 worksheet 并行:
  Step 0: 硬约束过滤           (代码)         → 可选视图类型池
  Step 1: recommend           (AI)           → 推荐视图类型+名称+理由
  Step 1.5: validate_recommend (代码)         → 校验推荐结果
  Step 2: configure×N         (AI, 视图间并行) → 每个视图独立生成配置
  Step 2.5: validate_config×N  (代码, 并行)    → 校验每个配置
  Step 3: create×N            (API, 并行)     → 创建视图
```

时序示意：

```
worksheet A: [recommend] → [config v1 | config v2 | config v3] → [create v1 | create v2 | create v3]
worksheet B: [recommend] → [config v1 | config v2]             → [create v1 | create v2]
worksheet C: [recommend] → [config v1 | config v2 | config v3 | config v4] → [create v1 | ...]
↑ 三行同时开始，互不等待
```

### 模块结构

三个独立可运行的模块，每步输出是下一步的输入（JSON 文件）：

| 模块 | 职责 | 可独立运行 |
|------|------|-----------|
| `view_recommender.py` | 硬约束过滤 + AI 推荐 | `python view_recommender.py --app-name "..." --worksheet-name "订单" --fields-json fields.json` |
| `view_configurator.py` | AI 为单个视图生成配置 | `python view_configurator.py --recommendation rec.json --fields-json fields.json` |
| `create_views_from_plan.py` | API 创建视图（已有） | `python create_views_from_plan.py --plan-json config.json` |

## Step 0: 硬约束过滤

纯代码逻辑，输入工作表字段列表，输出该表可创建的视图类型池。

### 约束清单（6 种可选视图）

| 视图类型 | viewType | 必要条件 |
|---------|----------|---------|
| 表格分组 | 0 | 至少一个 type=9/11 单选字段 |
| 看板 | 1 | 至少一个 type=9/11 单选字段 |
| 画廊 | 3 | 至少一个 type=14 附件字段，且字段名/描述与图片/图像/视觉相关（排除文档类、视频类） |
| 日历 | 4 | 至少一个 type=15/16/46 日期字段 |
| 甘特 | 5 | 至少两个 type=15/16/46 日期字段 |
| 资源 | 7 | type=26 成员字段 + 至少两个日期字段 |
| 地图 | 8 | type=40 定位字段 |

已移除：
- ~~详情视图(6)~~：不再创建
- ~~层级视图(2)~~：之前已禁用

### 画廊附件字段判断

附件字段(type=14)需要字段名/描述包含图片相关语义才触发画廊候选：

```python
IMAGE_KEYWORDS = {"图片", "图像", "照片", "头像", "封面", "缩略图", "截图", "logo", "图标", "banner", "image", "photo", "picture", "cover", "thumbnail"}
DOC_VIDEO_EXCLUDE = {"文档", "文件", "视频", "音频", "合同", "附件", "资料"}
```

判断逻辑：字段名命中 IMAGE_KEYWORDS 中任一关键词，且不命中 DOC_VIDEO_EXCLUDE 中任一关键词。

### 数量约束

- 每种视图类型每表最多 **1 个**
- 每表最多 **7 个**视图

## Step 1: recommend（AI 推荐）

### 输入

- `app_name`：应用名称
- `app_background`：从 requirement_spec 提取的业务背景描述
- `worksheet_name`：当前工作表名称
- `fields`：字段列表（名称、类型、选项值）
- `other_worksheet_names`：其他工作表名称列表（业务上下文参考）
- `available_view_types`：Step 0 硬约束过滤后的可选视图类型池

### AI 职责

基于业务语义判断：
- 从可选池中选择哪些视图类型值得创建
- 为每个视图起合适的业务名称
- 说明推荐理由

AI **不需要**判断字段可行性（硬约束已过滤），只需要判断**业务价值**。

### 输出 JSON

```json
{
  "worksheetId": "xxx",
  "worksheetName": "订单",
  "views": [
    {
      "viewType": 1,
      "name": "订单状态看板",
      "reason": "订单有明确的状态流转（待付款→已付款→已发货→已完成），看板视图能直观展示各状态的订单分布",
      "viewControl_hint": "订单状态"
    },
    {
      "viewType": 4,
      "name": "订单日历",
      "reason": "按下单日期浏览订单时间分布，便于发现订单高峰期"
    }
  ]
}
```

注意：`viewControl_hint` 是字段名提示（非 ID），供 Step 2 配置时匹配真实字段 ID。

### validate_recommend 校验

- viewType 是否在 Step 0 输出的可选池内 → 不在则丢弃
- 同一 viewType 是否重复 → 只保留第一个
- 总数是否超过 7 → 截断
- views 数组是否为空 → 接受，该表不创建视图

## Step 2: configure（AI 配置，每视图独立并行）

### 输入（单个视图）

- 该视图的推荐结果（viewType、name、reason、hint）
- 工作表字段详情
- `view_types.py` 中该 viewType 的 advancedSetting_keys 定义
- `view_config_schema.py` 中的配置模板

### AI 职责

为该视图生成完整的配置参数：
- `viewControl`（看板/资源/地图：选哪个字段）
- `advancedSetting`（视图特定设置）
- `postCreateUpdates`（二次保存参数）

### 输出 JSON（单个视图）

```json
{
  "viewType": 1,
  "name": "订单状态看板",
  "viewControl": "actual_field_id",
  "advancedSetting": {
    "enablerules": "1",
    "coverstyle": "{\"position\":\"1\",\"style\":3}"
  },
  "postCreateUpdates": {
    "editAttrs": ["viewControl"],
    "fields": {
      "viewControl": "actual_field_id"
    }
  }
}
```

### validate_config 校验

- 引用的字段 ID 是否存在于工作表字段列表中 → 不存在则尝试按字段名匹配修正，修正失败则丢弃该视图
- advancedSetting key 是否在注册中心定义中 → 未知 key 静默移除
- advancedSetting value 格式是否正确（如 JSON 字符串是否合法）→ 格式错误则移除该 key
- postCreateUpdates 结构是否完整 → 不完整则降级（创建视图但不做二次保存）

## Step 3: create（API 执行）

复用现有 `create_views_from_plan.py` 逻辑。输入为 Step 2 校验后的配置 JSON，格式兼容。

## 错误处理

### 核心原则

1. **隔离性**：单个视图失败不影响同表其他视图，单个工作表失败不影响其他工作表
2. **不让脏数据往下走**：每步校验不通过的数据就地丢弃，不传递给下一步
3. **降级优先**：能降级就降级（丢弃有问题的 key/视图），不轻易重试整个流程

### 各步错误策略

| 步骤 | 错误类型 | 处理方式 |
|------|---------|---------|
| Step 0 | 可选池为空 | 该表跳过，日志记录 |
| Step 1 | AI 返回非法 JSON | `parse_ai_json` 修复重试，最多 2 次 |
| Step 1 | AI 推荐了不允许的视图类型 | validate 静默丢弃，不重试 |
| Step 1 | AI 返回空列表 | 接受，该表不创建视图 |
| Step 1 | AI 调用超时/API 报错 | 重试 1 次，仍失败则该表标记失败 |
| Step 2 | AI 返回非法 JSON | `parse_ai_json` 修复重试，最多 2 次 |
| Step 2 | 字段 ID 不存在 | 尝试按字段名匹配修正，失败则丢弃该视图 |
| Step 2 | advancedSetting 格式错误 | 移除该 key，降级创建 |
| Step 2 | AI 调用失败 | 重试 1 次，失败则丢弃该视图 |
| Step 3 | API error_code != 1 | 重试 1 次，失败则记录错误 |
| Step 3 | 二次保存失败 | 视图已创建但配置不完整，记录 warning |

### 结果示例

```
worksheet A:
  recommend ✓ → [config v1 ✓ | config v2 ✗重试✓ | config v3 ✗丢弃]
                → [create v1 ✓ | create v2 ✓]
  结果: 3个推荐，2个成功创建，1个配置失败丢弃

worksheet B:
  recommend ✗重试✗ → 整表跳过
  结果: 标记失败，日志记录原因
```

## 改动范围

### 新增

- `scripts/hap/planners/view_recommender.py` — Step 0 硬约束 + Step 1 AI 推荐 + validate
- `scripts/hap/planners/view_configurator.py` — Step 2 AI 配置 + validate

### 修改

- `scripts/hap/pipeline_views.py` — 调用链改为并行 recommender → 并行 configurator → 并行 create
- `scripts/hap/views/view_types.py` — 移除 viewType=6（详情视图），更新画廊约束条件

### 移除

- `scripts/hap/planning/view_planner.py` 中的 `suggest_views`（关键词规则）、`build_structure_prompt`（Phase 1 prompt）、`build_config_prompt`（Phase 2 prompt）
- `scripts/hap/planners/plan_worksheet_views_gemini.py` 中的旧规划逻辑（被新模块替代）

### 保留

- `scripts/hap/planning/constraints.py` 中的 `classify_fields`
- `scripts/hap/views/view_config_schema.py`
- `scripts/hap/views/view_types.py`（VIEW_REGISTRY 结构保留，内容更新）
- `scripts/hap/executors/create_views_from_plan.py`（创建逻辑不变）

## 独立运行示例

```bash
# 测试推荐（从 requirement_spec 提取背景）
python view_recommender.py \
  --spec-json requirement_spec.json \
  --worksheet-name "订单" \
  --output recommendations.json

# 测试推荐（手动指定参数）
python view_recommender.py \
  --app-name "订单管理系统" \
  --background "电商订单全流程管理，覆盖下单、支付、发货、退换货全流程" \
  --worksheet-name "订单" \
  --fields-json fields.json \
  --other-worksheets "客户,商品,物流" \
  --output recommendations.json

# 测试配置（单个视图）
python view_configurator.py \
  --recommendation recommendation_single.json \
  --fields-json fields.json \
  --output config.json

# 测试创建（已有）
python create_views_from_plan.py --plan-json config.json
```
