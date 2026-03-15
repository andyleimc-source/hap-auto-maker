# HAP 工作流自动批量创建

## 核心流程（两步完成）

### 第一步：AI 规划工作流

用 Gemini 读取应用结构，自动生成工作流规划 JSON。

```bash
cd /Users/andy/Desktop/hap_auto/workflow

python3 scripts/pipeline_workflows.py \
  --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9'
```

输出：`output/pipeline_workflows_latest.json`

> Gemini Key 从 `config/credentials/gemini_auth.json` 自动读取，无需手动传入。

可选参数：

| 参数 | 含义 | 默认值 |
|---|---|---|
| `--model` | Gemini 模型 | `gemini-2.5-flash` |
| `--thinking` | 推理深度 `none/low/medium/high` | `high` |
| `--skip-analysis` | 跳过业务关系预分析（更快） | 否 |
| `--app-auth-json` | 应用授权 JSON 路径（留空自动匹配） | 自动 |
| `--output` | 自定义输出路径 | `output/pipeline_workflows_latest.json` |

---

### 第二步：批量创建工作流

读取规划 JSON，批量调用 API 创建所有工作流并自动发布（开启状态）。

```bash
cd /Users/andy/Desktop/hap_auto/workflow

python3 scripts/execute_workflow_plan.py
```

> 认证信息从 `config/credentials/auth_config.py` 自动读取，无需额外参数。

可选参数：

| 参数 | 含义 |
|---|---|
| `--no-publish` | 跳过发布，工作流保持关闭状态（调试用） |
| `--skip-existing` | 跳过已存在同名工作流（防重复创建） |
| `--only-worksheet <id>` | 只处理指定工作表（调试用） |
| `--plan-file <path>` | 指定规划 JSON 路径（默认 `output/pipeline_workflows_latest.json`） |

---

## 认证配置

所有脚本按以下优先级读取认证信息：

1. `--cookie` CLI 参数
2. 环境变量 `MINGDAO_COOKIE`
3. `config/credentials/auth_config.py` 中的 `COOKIE` 变量（**推荐**）

`account_id` / `authorization` 同理，从 `MINGDAO_ACCOUNT_ID` / `MINGDAO_AUTHORIZATION` 或 `auth_config.py` 读取。

---

## 目录结构

```
workflow/
├── scripts/
│   ├── pipeline_workflows.py               # 第一步：AI 规划
│   ├── execute_workflow_plan.py            # 第二步：批量创建
│   ├── workflow_io.py                      # 共享 Session / persist 工具
│   ├── delete_workflow.py                  # 交互式删除工作流
│   ├── create_workflow_worksheet_trigger.py # 单独创建-工作表事件触发
│   ├── create_workflow_time_trigger.py      # 单独创建-时间触发
│   └── create_workflow_custom_action_trigger.py # 单独创建-自定义动作
├── output/                                 # 规划 JSON 输出（不入库）
├── logs/                                   # 运行日志（不入库）
├── action/                                 # HAR 原始记录
└── docs/workflow_reference.md              # HAP 工作流节点参考文档
```

---

## 开发规范

- 统一使用 `workflow_io.Session` 发请求（自动注入鉴权 Header）
- 每次运行结果写入 `output/{script}_latest.json`（固定路径，下游可直接引用）
- 运行日志写入 `logs/{script}_{timestamp}.json`（含完整 HTTP 历史）
- `output/`、`logs/`、`__pycache__/` 均已 `.gitignore`，不入库
