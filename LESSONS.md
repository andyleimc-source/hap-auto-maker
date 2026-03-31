# LESSONS.md — HAP Auto Maker 可复用经验

---

## [AI 调用] creation_order 必须在 Prompt 中强制约束

**背景**：AI 规划工作表时反复漏填 creation_order。

**教训**：Prompt 约束必须用编号列表，明确写"creation_order 必须包含所有工作表名，一个不漏"。段落描述约束力不够。

---

## [AI 调用] option_values 禁止模糊词需在 Prompt 中显式声明

**教训**：必须在 Prompt 中写明"option_values 禁止包含模糊词（等、例如、如）"，否则 AI 会在下拉选项中写"其他等"。

---

## [AI 调用] JSON 输出必须声明"不要 markdown，不要注释"

**教训**：不声明的话 AI 会用 ```json 包裹输出，或在 JSON 中加注释，导致 parse 失败。

---

## [Playwright] 造数依赖 creation_order 顺序

**教训**：关联字段数据必须先创建"1端"再创建"N端"，creation_order 决定执行顺序，规划时不能随意排列。

---

## [TEST_CASES] 核心验收用例

手工回归时使用：

| 用例 | 命令 | 验收标准 |
|------|------|---------|
| TC-001 基础全流程 | `python3 scripts/run_app_pipeline.py`，输入"员工考勤管理，3张表" | 14个Step全部✓，明道云出现新应用 |
| TC-002 大规模工作表 | 输入"顺丰物流全流程管理10个表至少" | Step 2 不报 `creation_order 缺少工作表` |
| TC-003 单独测试工作表规划 | `python3 scripts/gemini/plan_app_worksheets_gemini.py --app-name "测试应用" ...` | creation_order 长度 == worksheets 长度 |
| TC-004 认证刷新 | `python3 scripts/auth/refresh_auth.py` 后重跑造数 | 无 401 错误，明道云出现 Mock 数据 |
