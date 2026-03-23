# HAP Auto Maker — 应用计划规范文档

> 版本：`workflow_requirement_v1` | 更新：2026-03-23

本文档说明 HAP Auto Maker 的**需求收集原则**、**Spec JSON 结构**与**执行流程**，适用于理解、调试或手动编写需求文件。

---

## 一、需求收集原则

入口脚本：`scripts/hap/agent_collect_requirements.py`

### 1.1 对话策略

| 原则 | 说明 |
|------|------|
| **默认优先** | 用户未明确的项目，直接使用默认值，不追问 |
| **单问单答** | 一次只问一个关键缺口，避免一次抛多个问题 |
| **关键缺口** | 只追问三类必要信息：应用名称/行业场景、工作表需求、业务范围 |
| **不输出 JSON** | 对话阶段只做澄清，不生成结构化数据 |

### 1.2 默认值规则

| 字段 | 默认值 | 触发条件 |
|------|--------|----------|
| 导航布局 | 左侧（`pcNaviStyle=1`） | 用户未明确指定 |
| 主题色 | `random`（随机） | 用户未明确指定 |
| 应用目标 | `create_new`（新建） | 未提供现有应用 |
| 工作表 | `enabled: true` | 默认开启 |
| 视图 | `enabled: true` | 默认开启 |
| 视图过滤器 | `enabled: true` | 默认开启 |
| 造数 | `enabled: true` | 默认开启 |
| 机器人 | `enabled: true, auto: true` | 默认开启 |
| 工作流 | `enabled: true` | 默认开启 |
| 统计页 | `enabled: true` | 默认开启 |

### 1.3 触发执行

用户输入**「开始运行」**时：
1. AI 将对话内容结构化为 `workflow_requirement_v1` JSON
2. 保存到 `data/outputs/requirement_specs/` 目录
3. 自动调用 `execute_requirements.py` 启动执行流水线

---

## 二、Spec JSON 结构（`workflow_requirement_v1`）

### 完整 Schema

```json
{
  "schema_version": "workflow_requirement_v1",

  "meta": {
    "created_at": "ISO8601时间戳",
    "source": "terminal_ai_chat",
    "conversation_summary": "100字以内的对话摘要"
  },

  "app": {
    "target_mode": "create_new",
    "name": "应用名称（必须从对话提取，不能保留占位文本）",
    "group_ids": "应用分组ID（逗号分隔，可为空）",
    "icon_mode": "ai_match",
    "color_mode": "random",
    "navi_style": {
      "enabled": true,
      "pcNaviStyle": 1
    }
  },

  "worksheets": {
    "enabled": true,
    "business_context": "1-3句话描述业务场景（必须从对话提取）",
    "requirements": "工作表数量/功能要求，无则留空",
    "icon_update": {
      "enabled": true,
      "refresh_auth": false
    },
    "layout": {
      "enabled": true,
      "requirements": "布局要求，无则留空",
      "refresh_auth": false
    }
  },

  "views": {
    "enabled": true
  },

  "view_filters": {
    "enabled": true
  },

  "roles": {
    "enabled": true,
    "skip_existing": true,
    "video_mode": "skip"
  },

  "mock_data": {
    "enabled": true,
    "dry_run": false,
    "trigger_workflow": false
  },

  "chatbots": {
    "enabled": true,
    "auto": true,
    "dry_run": false
  },

  "workflows": {
    "enabled": true,
    "thinking": "none",
    "no_publish": false,
    "skip_analysis": false
  },

  "delete_default_views": {
    "enabled": true,
    "refresh_auth": false
  },

  "pages": {
    "enabled": true
  },

  "execution": {
    "fail_fast": true,
    "dry_run": false
  }
}
```

### 字段说明

#### `app` — 应用基础配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `target_mode` | string | `create_new`（新建）或 `use_existing`（使用现有应用，需同时提供 `app_id`） |
| `name` | string | 应用名称，AI 必须从对话中提取，不得保留占位文本 |
| `group_ids` | string | 应用分组 ID，多个逗号分隔，可为空 |
| `icon_mode` | string | `ai_match`（AI 匹配）或其他 |
| `color_mode` | string | `random`（随机）或具体颜色值如 `#00bcd4` |
| `navi_style.pcNaviStyle` | int | 导航风格：`1`=左侧，`2`=顶部 |

#### `worksheets` — 工作表规划配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `business_context` | string | 业务场景描述，1-3句，供 AI 规划工作表使用 |
| `requirements` | string | 用户对表数量/功能的具体要求，如"至少20个表" |
| `icon_update.enabled` | bool | 是否启用 AI 匹配工作表 icon |
| `layout.requirements` | string | 字段布局的额外要求，无则留空 |

#### `execution` — 执行控制

| 字段 | 类型 | 说明 |
|------|------|------|
| `fail_fast` | bool | `true`=遇到步骤失败立即终止，`false`=继续执行后续步骤 |
| `dry_run` | bool | `true`=预览模式，仅输出计划不实际调用 API |

---

## 三、执行流程（14 步 + 6 波次）

入口脚本：`scripts/hap/execute_requirements.py`

### 波次总览

```
Wave 1  ──  Step 1：创建应用（串行，后续步骤依赖 appId）
Wave 2  ──  Step 2a + Step 3 + Step 8（并行）
Wave 3  ──  Step 2b：创建工作表（依赖 Wave 2 的 Step 2a）
Wave 4  ──  Step 4/5/6/9/10/11/13/14a（并行，Gemini 限制最大 3 并发）
Wave 5  ──  Step 7（依赖 Step 6）、Step 12（依赖 Step 11）
Wave 6  ──  Step 14b：创建统计图表页（依赖 Wave 4/5）
```

### 步骤详情

| Step | Key | 标题 | 依赖 | 使用 Gemini |
|------|-----|------|------|-------------|
| 1 | `create_app` | 创建应用 + 授权 + 应用 icon | — | ✓ |
| 2a | `worksheets_plan` | 规划工作表（AI） | Step 1 | ✓ |
| 2b | `worksheets_create` | 创建工作表 | Step 2a | — |
| 3 | `roles` | 规划并创建应用角色 | Step 1 | ✓ |
| 4 | `worksheet_icon` | 更新工作表 icon（AI 匹配） | Step 2b | ✓ |
| 5 | `layout` | 规划并应用字段布局 | Step 2b | ✓ |
| 6 | `views` | 规划并创建视图 | Step 2b | ✓ |
| 7 | `view_filters` | 规划并应用视图过滤器 | Step 6 | ✓ |
| 8 | `navi` | 设置应用导航风格 | Step 1 | — |
| 9 | `mock_data` | 执行造数流水线 | Step 2b | ✓ |
| 10 | `chatbots` | 创建对话机器人 | Step 2b | ✓ |
| 11 | `workflows_plan` | 规划工作流（AI） | Step 2b | ✓ |
| 12 | `workflows_execute` | 执行工作流创建 | Step 11 | — |
| 13 | `delete_default_views` | 删除默认视图 | Step 2b | — |
| 14 | `pages` | 规划并创建统计图表页 | Wave 4/5 | ✓ |

### Gemini 并发控制

- 默认最多 **3 个步骤**同时调用 Gemini API
- 可通过 `--gemini-concurrency N` 参数调整
- 目的：避免 API 限流，保证输出质量

---

## 四、输出产物

执行完成后，产物分布在 `data/outputs/` 下：

| 产物目录 | 内容 |
|---------|------|
| `requirement_specs/` | 需求 JSON（`workflow_requirement_v1`） |
| `app_authorizations/` | 应用授权信息（appKey / sign） |
| `worksheet_plans/` | 工作表规划 JSON |
| `worksheet_create_results/` | 工作表创建结果 |
| `view_plans/` | 视图规划 JSON |
| `view_create_results/` | 视图创建结果 |
| `tableview_filter_plans/` | 视图过滤器规划 JSON |
| `worksheet_layout_plans/` | 字段布局规划 JSON |
| `mock_data_plans/` | 造数计划 JSON |
| `chatbot/plans/` | 机器人规划 JSON |
| `page_plans/` | 统计页规划 JSON |
| `execution_runs/` | 完整执行报告（含每步耗时与状态） |

最新一次执行报告始终同步到 `execution_runs/execution_run_latest.json`。

---

## 五、常用执行命令

### 对话式启动（推荐）

```bash
python3 scripts/run_app_pipeline.py
```

### 直接执行已有需求文件

```bash
python3 scripts/hap/execute_requirements.py \
  --spec-json data/outputs/requirement_specs/requirement_spec_latest.json
```

### 预览模式（不调用 API）

```bash
python3 scripts/hap/execute_requirements.py \
  --spec-json <path>.json \
  --dry-run
```

### 仅执行指定步骤

```bash
# 按编号
python3 scripts/hap/execute_requirements.py --spec-json <path>.json --only-steps 1,2,3

# 按名称
python3 scripts/hap/execute_requirements.py --spec-json <path>.json --only-steps mock_data,chatbots
```

### 遇错继续（不 fail-fast）

```bash
python3 scripts/hap/execute_requirements.py \
  --spec-json <path>.json \
  --continue-on-error
```
