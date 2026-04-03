# 视图类型注册中心

## 目录结构

```
scripts/hap/views/
├── __init__.py       # 导出 VIEW_REGISTRY, ALLOWED_VIEW_TYPES
├── view_types.py     # 6 种视图类型定义
└── README.md
```

## 视图类型清单 (6 种)

| viewType | 名称 | 验证 | 字段约束 | 二次保存 | 自动补全 |
|----------|------|------|---------|---------|---------|
| 0 | 表格视图 | ✓ | — | — | 分组: groupView |
| 1 | 看板视图 | ✓ | type=11 单选 | — | viewControl |
| 2 | 层级视图 | ✓ | type=29 自关联 | childType + layersControlId | hierarchy |
| 3 | 画廊视图 | - | — | — | — |
| 4 | 日历视图 | - | type=15/16 日期 | calendarcids | calendar |
| 5 | 甘特图 | ✓ | type=15/16 x2 | begindate + enddate | gantt |

## 关键规则

1. **看板(1)** — `viewControl` 必须是单选字段(type=11)，没有则不创建
2. **层级(2)** — 需要自关联字段(type=29, dataSource=本表)，创建后二次保存
3. **日历(4)** — 需要日期字段，二次保存 calendarcids JSON
4. **甘特图(5)** — 需要两个日期字段（开始+结束），二次保存 begindate/enddate
5. **分组表格(0)** — 视图名含"分组"/"分类"时自动生成 groupView 配置
