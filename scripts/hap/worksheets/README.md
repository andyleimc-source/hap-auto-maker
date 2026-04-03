# 工作表字段类型注册中心

## 目录结构

```
scripts/hap/worksheets/
├── __init__.py        # 导出 FIELD_REGISTRY, FIELD_TYPE_MAP
├── field_types.py     # 15 种字段类型定义
└── README.md
```

## 字段类型清单 (15 种)

| AI 枚举名 | controlType | 中文 | 注意事项 |
|-----------|-------------|------|---------|
| Text | 2 | 文本 | 第一个自动设为标题 |
| Number | 6 | 数字 | precision=2 |
| Money | 8 | 金额 | precision=2, unit=¥ |
| SingleSelect | 9 | 单选 | 需 option_values |
| MultipleSelect | 10 | 多选 | 需 option_values |
| Dropdown | 11 | 下拉框 | 用于看板分组 |
| Date | 15 | 日期 | 适合甘特图/日历 |
| DateTime | 16 | 日期时间 | 适合日历视图 |
| Collaborator | 26 | 成员 | required 强制 false |
| Relation | 29 | 关联 | 需 relation_target |
| Attachment | 14 | 附件 | |
| RichText | 41 | 富文本 | |
| Phone | 3 | 电话 | |
| Email | 5 | 邮箱 | |
| Area | 24 | 地区 | 适合地图图表 |

> 注: AI 规划时使用英文枚举名（如 `Text`），API 创建时使用 controlType 数字（如 `2`）。
> `plan_app_worksheets_gemini.py` 原支持 9 种，现扩展到 15 种。
