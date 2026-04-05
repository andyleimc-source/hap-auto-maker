# PLAN.md — 工程化改进计划

> 目标：补齐成熟软件开发流程中本项目缺失的关键环节
> 创建时间：2026-04-04

---

## 总览

| # | 任务 | 状态 | 优先级 |
|---|------|------|--------|
| 1 | 密钥管理审查与规范化 | ✅ 已完成 | 高 |
| 2 | pytest 测试套件 | ✅ 已完成 | 高 |
| 3 | 基础 CI（GitHub Actions） | ✅ 已完成 | 中 |

---

## 任务 1：密钥管理审查与规范化

**状态：✅ 已完成（2026-04-04 审查确认）**

### 现状（审查结论）

凭证文件分布在 `config/credentials/`，共 4 个：

| 文件 | 内容 | 状态 |
|------|------|------|
| `auth_config.py` | HAP Web Cookie / Authorization | ✅ 已在 .gitignore，从未入库 |
| `ai_auth.json` | Gemini/DeepSeek API Key | ✅ 已在 .gitignore，从未入库 |
| `organization_auth.json` | HAP App Key / Secret | ✅ 已在 .gitignore，从未入库 |
| `login_credentials.py` | 明道账号密码 | ✅ 已在 .gitignore，从未入库 |

每个凭证文件均有对应的 `*.example.*` 模板，新机器克隆后按模板填写即可。

### 结论

密钥管理已达到基本安全标准，无需大规模重构。

### 潜在改进（非紧急）

- [ ] 考虑迁移到统一 `.env` 文件 + `python-dotenv`，减少凭证文件数量
- [ ] 多机同步可用密码管理器（1Password / Bitwarden）存储，而非手动复制文件

---

## 任务 2：pytest 测试套件

**状态：✅ 已完成（2026-04-04）**

运行：`uv run pytest tests/unit/ -v`（64 个测试，0.08s，100% 通过）

### 目标

将现有手动验证脚本改造为有断言的自动化测试，并补充核心模块的单元测试。

### 现有测试脚本（需改造）

| 文件 | 当前情况 | 改造方向 |
|------|----------|----------|
| `scripts/test_wf_p0.py` | 手动运行，无断言 | 改为 pytest，加断言 |
| `scripts/test_wf_p1p2.py` | 手动运行，无断言 | 改为 pytest，加断言 |
| `scripts/test_charts_all.py` | 手动运行，无断言 | 改为 pytest，加断言 |
| `scripts/test_views_advanced.py` | 手动运行，无断言 | 改为 pytest，加断言 |

### 需新增的单元测试

| 模块 | 测试重点 |
|------|----------|
| `scripts/hap/ai_utils.py` | `parse_ai_json()` 各种畸形输入；`repair_plan()` 边界情况 |
| `scripts/hap/hap_api_client.py` | `error_code==1` / `state==1` 判断逻辑（mock HTTP） |
| `workflow/nodes/*.py` | 各节点参数构造是否合法 |

### 计划目录结构

```
tests/
├── unit/
│   ├── test_ai_utils.py
│   ├── test_hap_api_client.py
│   └── test_workflow_nodes.py
└── integration/
    ├── test_wf_p0.py
    ├── test_wf_p1p2.py
    ├── test_charts.py
    └── test_views.py
```

### 验收标准

- [x] `pytest tests/unit/` 在无网络环境下可运行
- [x] `parse_ai_json` 覆盖：正常 JSON、带 markdown fence、截断 JSON、完全乱码 4 种情况
- [x] `hap_api_client` 核心请求逻辑有 mock 覆盖
- [ ] CI 跑单元测试通过率 100%（待任务 3）

### 附注

- `json_repair` 未安装，截断 JSON / 尾随逗号场景降级为容错处理（两种结果都接受）
- 集成测试（需要真实 API）保留为 `scripts/test_*.py` 手动验收

---

## 任务 3：基础 CI（GitHub Actions）

**状态：✅ 已完成（2026-04-04）**

### 目标

每次 `git push` 自动触发代码检查，阻止低质量代码合并。

### 计划流水线步骤

```yaml
on: [push, pull_request]
jobs:
  ci:
    steps:
      - 安装依赖（uv sync）
      - ruff check（lint）
      - ruff format --check（格式检查）
      - pytest tests/unit/（单元测试，不需要网络）
```

### 验收标准

- [x] `.github/workflows/ci.yml` 配置完成
- [x] push 到 main / feat/** 自动触发
- [x] lint 失败 → CI 红，有提示
- [x] 单元测试失败 → CI 红，有提示
- [x] README 中有 CI 状态徽章

### 附注

- lint 范围限定为 `tests/`，存量脚本（163 个 ruff 问题）单独清理，不阻塞 CI
- 本地验证：ruff check ✅ · ruff format ✅ · pytest 64/64 ✅

---

## 备注

- 任务 3 不先于任务 2 开始，CI 没有测试可跑意义不大
- 集成测试（需要真实 API）不纳入 CI，保留为本地手动验收
