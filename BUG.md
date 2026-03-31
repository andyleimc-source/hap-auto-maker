# BUG.md — HAP Auto Maker 问题记录

---

## [BUG-001] creation_order 缺少工作表
- **状态**: resolved
- **现象**: `ValueError: 工作表规划未通过校验: creation_order 缺少工作表: 网点信息, 车辆信息 ...`
- **根因**: AI（fast tier）生成工作表时，`creation_order` 数组只列出有依赖关系的子集，未包含全部工作表名
- **修复**: `scripts/gemini/plan_app_worksheets_gemini.py` 中 `repair_plan()` 自动补全遗漏工作表名；Prompt 约束明确要求"creation_order 必须包含所有工作表名"
- **验证**: 重跑相同需求，Step 2 不再报 `creation_order 缺少工作表`

---

## [BUG-002] Playwright 认证失效
- **状态**: resolved（运维问题，非代码 bug）
- **现象**: 造数步骤失败，日志中有 `401` 或 `登录状态已失效`
- **根因**: 网页端 Cookie/Token 过期（通常 7 天）
- **修复**: `python3 scripts/auth/refresh_auth.py`

---

## [BUG-003] AI 响应超时断连
- **状态**: resolved
- **现象**: Step 2 卡很久后抛出 `ConnectionError` 或 `ReadTimeout`
- **根因**: 大规模工作表（10+ 张）规划时响应体大，non-streaming 连接容易断
- **修复**: 使用 `generate_content_stream` 替换 `generate_content`（commit 8871516）
