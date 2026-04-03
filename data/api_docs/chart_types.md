# 统计图类型（Chart Types）

- 录制日期: 2026-04-01（React Fiber 批量点击 + XHR 拦截器）
- 接口: `POST https://api.mingdao.com/report/reportConfig/saveReportConfig`
- 接口: `POST https://api.mingdao.com/report/custom/savePage`（布局到页面）

## reportType 枚举（全部 17 种，已验证 ✅）

| reportType | 图表名称 | 备注 |
|------------|---------|------|
| `1` | 柱状图 | 默认图表类型 |
| `2` | 折线图 | |
| `3` | 饼图 | showPercent 建议设为 true |
| `4` | 环形图 | showPercent 建议设为 true |
| `5` | 漏斗图 | |
| `6` | 雷达图 | |
| `7` | 条形图 | 横向柱状图 |
| `8` | 双轴图 | 需同时设置 yaxisList 和 yreportType |
| `9` | 散点图 | |
| `10` | 数值图（数字卡片）| 通常只设 yaxisList，不设 xaxes |
| `11` | 区域图 | 类似折线图，面积填充 |
| `12` | 进度图 | 单值进度条 |
| `13` | 透视表（数据透视）| pivotTable，需 xaxes + yaxisList |
| `14` | 词云图 | 文本分析 |
| `15` | 排行图 | 横向排名条形图 |
| `16` | 地图 | 需地理字段（省市）|
| `17` | 关系图 | 层级关系可视化 |

---

## saveReportConfig 请求体

**POST** `https://api.mingdao.com/report/reportConfig/saveReportConfig`

### 最小可用示例（柱状图，按记录数量汇总）

```json
{
  "splitId": "",
  "split": {},
  "displaySetup": {
    "isPerPile": false,
    "isPile": false,
    "isAccumulate": false,
    "accumulatePerPile": null,
    "isToday": false,
    "isLifecycle": false,
    "lifecycleValue": 0,
    "contrastType": 0,
    "fontStyle": 1,
    "showTotal": false,
    "showTitle": true,
    "showLegend": true,
    "legendType": 1,
    "showDimension": true,
    "showNumber": true,
    "showPercent": false,
    "showXAxisCount": 0,
    "showChartType": 1,
    "showPileTotal": true,
    "hideOverlapText": false,
    "showRowList": true,
    "showControlIds": [],
    "auxiliaryLines": [],
    "showOptionIds": [],
    "contrast": false,
    "colorRules": [],
    "percent": {
      "enable": false,
      "type": 2,
      "dot": "2",
      "dotFormat": "1",
      "roundType": 2
    },
    "mergeCell": true,
    "previewUrl": null,
    "imageUrl": null,
    "xdisplay": {
      "showDial": true,
      "showTitle": false,
      "title": "",
      "minValue": null,
      "maxValue": null
    },
    "xaxisEmpty": false,
    "ydisplay": {
      "showDial": true,
      "showTitle": false,
      "title": "记录数量",
      "minValue": null,
      "maxValue": null,
      "lineStyle": 1,
      "showNumber": null
    }
  },
  "name": "未命名图表",
  "desc": "",
  "reportType": 1,
  "filter": {
    "filterRangeId": "ctime",
    "filterRangeName": "创建时间",
    "rangeType": 0,
    "rangeValue": 0,
    "today": false
  },
  "sorts": [],
  "yaxisList": [
    {
      "controlId": "record_count",
      "controlName": "记录数量",
      "controlType": 10000000,
      "magnitude": 0,
      "roundType": 2,
      "dotFormat": "1",
      "suffix": "",
      "ydot": 2,
      "fixType": 0,
      "showNumber": true,
      "hide": false,
      "percent": {
        "enable": false,
        "type": 2,
        "dot": "2",
        "dotFormat": "1",
        "roundType": 2
      },
      "normType": 5,
      "emptyShowType": 0,
      "dot": 0,
      "rename": "",
      "advancedSetting": {}
    }
  ],
  "xaxes": {
    "controlId": null,
    "sortType": 0,
    "particleSizeType": 0,
    "rename": "",
    "emptyType": 0,
    "fields": null,
    "subTotal": false,
    "subTotalName": null,
    "showFormat": "0",
    "displayMode": "text",
    "controlName": "",
    "controlType": 16,
    "dataSource": null,
    "options": [],
    "advancedSetting": null,
    "relationControl": null,
    "cid": "null-1",
    "cname": "",
    "xaxisEmptyType": 0,
    "xaxisEmpty": false,
    "c_Id": "null-1"
  },
  "appId": "<worksheetId>",
  "appType": 1,
  "sourceType": 1,
  "isPublic": true,
  "id": "",
  "version": "6.5"
}
```

Response:
```json
{
  "status": 1,
  "data": { "reportId": "<reportId>" }
}
```

---

## filter.rangeType 枚举

| rangeType | 含义 |
|-----------|------|
| 0 | 不限时间 |
| 1 | 今天 |
| 2 | 昨天 |
| 3 | 本周 |
| 4 | 上周 |
| 5 | 本月 |
| 6 | 上月 |
| 7 | 本季度 |
| 8 | 上季度 |
| 9 | 本年 |
| 18 | 过去N天（rangeValue=天数，today=true 含今天）|

---

## 特殊图表注意事项

### 饼图/环形图（reportType=3/4）
- `displaySetup.showPercent = true` 建议开启

### 双轴图（reportType=8）
- `yreportType` 指定第二轴类型（通常为 2=折线）
- `yaxisList` 至少两个指标

### 数值图（reportType=10）
- `xaxes.controlId = null`，不需要维度字段
- `yaxisList` 只放一个指标

### 透视表（reportType=13）
- 需要 `xaxes`（行维度）+ `yaxisList`（值）
- 可选设置列维度

---

## getData 接口（图表数据查询）

**POST** `https://api.mingdao.com/report/report/getData`

```json
{
  "reportId": "<reportId>",
  "pageId": "<pageId>",
  "filters": [],
  "isPersonal": false,
  "reload": false
}
```

Response: `{ "status": 1, "data": { "xaxes": [...], "yaxisList": [...] } }`

---

## 将图表添加到自定义页面（savePage component type=1）

创建图表后，需通过 savePage 将其布局到页面：

```json
{
  "appId": "<pageId>",
  "version": 1,
  "components": [
    {
      "id": "<24位hex>",
      "type": 1,
      "value": "<reportId>",
      "valueExtend": "<reportId>",
      "config": { "objectId": "<uuid>" },
      "worksheetId": "<worksheetId>",
      "name": "图表名称",
      "reportType": 1,
      "showChartType": 1,
      "titleVisible": false,
      "needUpdate": true,
      "web": {
        "title": "",
        "titleVisible": false,
        "visible": true,
        "layout": { "x": 0, "y": 0, "w": 24, "h": 12, "minW": 2, "minH": 4 }
      },
      "mobile": { "title": "", "titleVisible": false, "visible": true, "layout": null }
    }
  ],
  "adjustScreen": false,
  "urlParams": [],
  "config": { "pageStyleType": "light", "pageBgColor": "#f5f6f7", "webNewCols": 48 }
}
```
