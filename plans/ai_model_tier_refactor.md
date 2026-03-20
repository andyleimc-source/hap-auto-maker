# Plan: AI 模型档位自动适配改造计划

> 目标：将模型选择从用户端剥离，改为基于任务档位（Reasoning / Fast）的自动适配。支持 DeepSeek 和 Gemini 2.5 系列。

## 1. 核心架构决策

### 1.1 任务档位 (Task Tier) 定义
不再由脚本直接请求具体的模型名称，而是请求以下两种能力等级之一：

| 档位名称 | 适用场景 | DeepSeek 映射 | Gemini 映射 |
| :--- | :--- | :--- | :--- |
| **REASONING** (推理档) | 工作表规划、工作流逻辑生成、业务分析、复杂布局 | `deepseek-reasoner` | `gemini-2.5-pro` |
| **FAST** (极速档) | 图标匹配、Mock 数据生成、视图/筛选器创建、简单翻译 | `deepseek-chat` | `gemini-2.5-flash` |

### 1.2 简化配置层
`ai_auth.json` 仅保留 `provider`、`api_key` 和 `base_url`。不再要求用户配置具体的 `model`。

---

## 2. 实施阶段

### 第一阶段：核心工具类改造 (`scripts/hap/ai_utils.py`)
- **定义档位映射表**：在 `ai_utils.py` 中内置 `TIER_MODELS` 常量。
- **新增接口**：实现 `get_model_by_tier(tier: str) -> str`，根据配置的 `provider` 返回对应的物理模型名。
- **兼容层优化**：更新 `load_ai_config`，使其支持返回 `tier` 对应的模型信息。

### 第二阶段：子脚本“去参数化”重构
对所有涉及 AI 调用的脚本进行重构，移除 `--model` 命令行参数（或标记为弃用且不生效），改为内部显式声明任务档位。

#### 需改造为 `REASONING` 档位的脚本：
- `scripts/hap/plan_app_worksheets_gemini.py` (工作表规划)
- `scripts/hap/plan_workflow_gemini.py` (工作流逻辑)
- `scripts/hap/plan_pages_gemini.py` (页面与统计分析)
- `scripts/hap/plan_role_recommendations_gemini.py` (角色权限推荐)
- `scripts/hap/plan_worksheet_layout.py` (字段布局规划)

#### 需改造为 `FAST` 档位的脚本：
- `scripts/gemini/match_app_icons_gemini.py` (应用图标匹配)
- `scripts/gemini/match_worksheet_icons_gemini.py` (工作表图标匹配)
- `scripts/hap/plan_mock_data_gemini.py` (Mock 数据内容生成)
- `scripts/hap/plan_worksheet_views_gemini.py` (基础视图规划)
- `scripts/hap/plan_tableview_filters_gemini.py` (筛选器规则生成)

### 第三阶段：全流程引擎适配
- **`agent_collect_requirements.py`**: 需求对话阶段默认使用 `FAST` 档位（追求响应速度）。
- **`execute_requirements.py`**: 确保在并行执行波次中，每个子脚本都能正确继承档位逻辑。

### 第四阶段：实战验证（双厂商线跑通）
在完成核心逻辑改造和子脚本重构后，需进行以下两项全流程实战验证：

1. **DeepSeek 厂商线验证**：
   - 配置 `ai_auth.json` 为 `provider: deepseek`。
   - 运行全流程：`python3 scripts/run_app_pipeline.py --requirements-text "建立一套标准的 CRM 系统"`。
   - **验证点**：检查 `worksheet_plans` 是否由 `deepseek-reasoner` 生成，`mock_data` 是否由 `deepseek-chat` 生成。
2. **Gemini 厂商线验证**：
   - 配置 `ai_auth.json` 为 `provider: gemini`。
   - 运行全流程：`python3 scripts/run_app_pipeline.py --requirements-text "建立一套简单的员工入职管理系统"`。
   - **验证点**：检查规划环节是否正确调用了 `gemini-2.5-pro`，其他环节是否调用了 `gemini-2.5-flash`。

---

## 3. 验收标准
- [ ] 运行 `python scripts/hap/plan_app_worksheets_gemini.py` 不再需要传 `--model`。
- [ ] 修改 `ai_auth.json` 的 `provider` 后，全流程自动切换到该厂商的 Pro/Flash 或 Reasoner/Chat 组合。
- [ ] 验证 DeepSeek Reasoner 的 Thinking 过程在核心规划环节正常触发。
- [ ] 验证 Gemini 2.5 Pro 和 Flash 在各自档位下的调用正确。
- [ ] **DeepSeek 全流程实战跑通：成功创建一个功能完整的 CRM 应用。**
- [ ] **Gemini 全流程实战跑通：成功创建一个功能完整的 HR 应用。**

---

## 4. 风险点
- **成本控制**：`gemini-2.5-pro` 和 `deepseek-reasoner` 成本较高，需确保仅在核心规划环节使用。
- **Gemini API 兼容性**：需确认 `google-genai` 库对 `gemini-2.5` 系列模型 ID 的完全支持。
