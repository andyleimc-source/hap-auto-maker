# 统计图表注册中心

## 目录结构

```
scripts/hap/charts/
├── __init__.py      # 注册中心: CHART_REGISTRY + build_report_body()
├── _base.py         # 通用构建: displaySetup/xaxes/yaxis/body
├── basic.py         # 柱状图(1), 折线图(2), 条形图(7), 区域图(11)
├── pie.py           # 饼图(3), 环形图(4)
├── funnel.py        # 漏斗图(5)
├── radar.py         # 雷达图(6)
├── dual_axis.py     # 双轴图(8)
├── scatter.py       # 散点图(9)
├── number.py        # 数值图(10), 进度图(12)
├── table.py         # 透视表(13)
└── special.py       # 词云图(14), 排行图(15), 地图(16), 关系图(17)
```

## 图表清单 (17 种)

| reportType | 名称 | 模块 | 验证 | 注意事项 |
|-----------|------|------|------|---------|
| 1 | 柱状图 | basic | ✓ | 默认图表类型 |
| 2 | 折线图 | basic | ✓ | xaxes 通常为日期字段 |
| 3 | 饼图 | pie | ✓ | showPercent=True |
| 4 | 环形图 | pie | - | 同饼图 |
| 5 | 漏斗图 | funnel | ✓ | showPercent=True |
| 6 | 雷达图 | radar | - | 多维度对比 |
| 7 | 条形图 | basic | - | 横向柱状图 |
| 8 | 双轴图 | dual_axis | - | 需 yreportType |
| 9 | 散点图 | scatter | - | 二维数值分布 |
| 10 | 数值图 | number | ✓ | xaxes.controlId=null |
| 11 | 区域图 | basic | - | 面积填充折线 |
| 12 | 进度图 | number | - | 同数值图 |
| 13 | 透视表 | table | - | mergeCell=True |
| 14 | 词云图 | special | - | 文本分析 |
| 15 | 排行图 | special | - | 横向排名 |
| 16 | 地图 | special | - | 需地理字段 |
| 17 | 关系图 | special | - | 层级可视化 |

## 关键发现

1. **Referer 必须包含 pageId** — `saveReportConfig` 的 HTTP Referer 需要 `app/{appId}/{pageId}`，否则图表创建成功但前端报"不存在"
2. **数值图 xaxes.controlId=null** — 不需要维度字段
3. **双轴图需 yreportType** — 第二轴图表类型 (1=柱状, 2=折线)
4. **饼图/环形图/漏斗图** — showPercent=True

## 用法

```python
from scripts.hap.charts import CHART_REGISTRY, build_report_body, REPORT_TYPE_NAMES

# 构建 saveReportConfig body
body = build_report_body({"reportType": 3, "name": "饼图", "worksheetId": "...", ...}, app_id)
```
