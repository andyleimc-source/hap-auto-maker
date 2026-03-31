# DECISIONS.md — HAP Auto Maker 决策日志

---

## [核心] Plan-Execute 分离架构

**决策**：每个功能分为 `plan_*`（AI 输出 JSON）和 `create_*`（执行 JSON）两个脚本，不混在一起。

**理由**：
- 可以单独重跑执行步骤而不重新调用 AI（省时省钱）
- JSON 可以手动修改调试
- 失败时容易定位是 AI 规划问题还是 API 执行问题

---

## [AI Tier] 固定使用 fast tier

**决策**：所有规划步骤用 `fast` tier（gemini-2.5-flash / deepseek-chat），不使用 `reasoning` tier。

**理由**：推理档位慢 3-5 倍，质量提升不明显（commit f22778d 已切回 fast）。

---

## [Streaming] 大规模规划使用 streaming

**决策**：plan 脚本使用 `generate_content_stream` 而非 `generate_content`。

**理由**：大规模工作表（10+ 张）规划时，non-streaming 连接在长响应时有断连风险。

---

## [校验] repair_plan 自动修复优先于重试

**决策**：AI 输出先经过 `repair_plan()` 自动修复，再 `validate_*()` 校验，不直接重试。

**理由**：重试一次需要 2-6 分钟，且 AI 可能重复犯同一错误（如漏填 creation_order）。自动修复可确定性解决问题。

**边界**：`repair_plan` 只修复可确定正确的问题，不猜测 AI 意图。
