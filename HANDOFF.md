# HANDOFF — 2026-04-05

## 本次完成

### 1. 自定义页面 icon 匹配（已改代码，未验证）
- **文件**: `scripts/hap/plan_pages_gemini.py`
- 之前所有统计页 icon 硬编码为 `dashboard`，现在 AI 从 15 个业务主题图标中按页面内容选择
- prompt 提供候选列表 + 语义标注，validate 做白名单校验，不在列表的回退 `sys_dashboard`
- `iconUrl` 改为动态拼接：`https://fp1.mingdaoyun.cn/customIcon/{icon}.svg`

### 2. 造数字段缺失（系统性修复，已改代码，未验证）

**根因**: `mock_data_common.py` 的 `SUPPORTED_WRITABLE_FIELD_TYPES` 缺少 4 种可写字段类型，schema 导出阶段就把它们归入 skippedFields，AI 从未为这些字段生成值。

**影响范围**: 跨所有工作表共 23 个业务字段被错误跳过，包括：
- **Dropdown**（下拉单选）: 项目状态、线索状态、付款状态、任务状态、检查结果、在职状态、单位 等
- **Currency**（金额）: 预算金额、合同金额、应付金额、单价、收款金额、支出金额、参考单价 等
- **Region**（地区）: 项目地址
- **RichText**（富文本）: 跟进内容、反馈内容、工作内容、部门职能、文章内容

**改动明细**:

| 文件 | 改动 |
|------|------|
| `scripts/hap/mock_data_common.py` | `SUPPORTED_WRITABLE_FIELD_TYPES` +4 类型（Currency/Dropdown/Region/RichText） |
| 同上 | `KNOWN_COMPLEX_FIELD_TYPES` +4 类型（Rollup/Concatenate/DateFormula/Signature） |
| 同上 | `KNOWN_SYSTEM_FIELD_IDS` +2（wfstatus/wfftime，工作流系统字段不应填值） |
| 同上 | `KNOWN_SYSTEM_FIELD_ALIASES` +2（_processStatus/_remainingTime） |
| 同上 | `to_receive_control_value()` Dropdown 与 SingleSelect 同逻辑序列化 |
| `scripts/hap/plan_mock_data_gemini.py` | prompt v1/v2 新增 Dropdown/Currency/Region/RichText 格式说明 |
| 同上 | 新增强约束"每个 writableField 都必须填值" |
| 同上 | validate 中 SingleSelect 校验扩展为 `{"SingleSelect", "Dropdown"}` |

## 待验证

需要在测试应用上重跑完整 mock data pipeline 来验证：

```bash
# 1. 重新导出 schema（会把之前 skipped 的字段变为 writable）
python3 scripts/hap/export_app_mock_schema.py --app-id b9aec84d-4bbb-4b53-acfd-a14db6b24db5

# 2. 清除现有数据
python3 scripts/hap/clear_mock_data.py --app-id b9aec84d-4bbb-4b53-acfd-a14db6b24db5

# 3. 重跑造数 pipeline
python3 scripts/hap/pipeline_mock_data.py --app-id b9aec84d-4bbb-4b53-acfd-a14db6b24db5

# 4. 重跑统计页（验证 icon 匹配）
python3 scripts/hap/pipeline_pages.py --app-id b9aec84d-4bbb-4b53-acfd-a14db6b24db5
```

验证要点：
- [ ] Dropdown 字段（项目状态、付款状态等）有值且是合法选项
- [ ] Currency 字段（金额类）有数字值
- [ ] Region 字段（项目地址）有地区值
- [ ] RichText 字段（跟进内容等）有文本值
- [ ] 工作流系统字段（流程状态、剩余时间）不出现在造数中
- [ ] 统计页 icon 各不相同，匹配业务主题

## 测试应用

- appId: `b9aec84d-4bbb-4b53-acfd-a14db6b24db5`
- 名称: 室内设计与装修公司管理平台
