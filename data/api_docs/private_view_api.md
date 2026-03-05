# 私有接口文档（工作表视图创建）

更新时间：2026-03-05  
来源：
- `/Users/andy/Desktop/hap_auto/view/表格视图.har`
- `/Users/andy/Desktop/hap_auto/view/看板视图.har`
- `/Users/andy/Desktop/hap_auto/view/画廊视图.har`
- `/Users/andy/Desktop/hap_auto/view/日历视图.har`

## 1. 核心接口：创建/保存工作表视图

- 接口名称：创建/保存工作表视图（所有视图类型共用）
- 方法：`POST`
- 路径：`/api/Worksheet/SaveWorksheetView`
- 完整 URL：`https://www.mingdao.com/api/Worksheet/SaveWorksheetView`

### 鉴权与请求头

- 必需头（已确认）：
  - `accountid: <account_uuid>`
  - `content-type: application/json`
  - `x-requested-with: XMLHttpRequest`
- 常见头（建议透传）：
  - `origin: https://www.mingdao.com`
  - `referer: https://www.mingdao.com/app/...`
- 说明：
  - 本 HAR 中未捕获到 `Authorization` / `Cookie` 字段，但该接口在真实环境通常依赖登录态。
  - 后续脚本建议复用现有认证模块（`auth_config.py`）统一注入鉴权信息。

### 请求体（JSON）

```json
{
  "viewId": "",
  "appId": "888a8ad4-f056-402a-814a-8ca0fbd1e69a",
  "viewType": "0",
  "displayControls": [
    "69a943fee4311077e074bc45",
    "69a943fee4311077e074bc46"
  ],
  "name": "表格1",
  "sortType": 0,
  "coverType": 0,
  "worksheetId": "69a943fe296f91d9c3c86bf3",
  "controls": [],
  "filters": [],
  "sortCid": "",
  "showControlName": true,
  "advancedSetting": {
    "enablerules": "1",
    "coverstyle": "{\"position\":\"1\",\"style\":3}"
  }
}
```

### 字段说明（当前样本可确认）

- `viewId`：新建时为空字符串；更新时传已有视图 ID。
- `appId`：应用 ID。
- `worksheetId`：工作表 ID。
- `name`：视图名称。
- `viewType`：视图类型（见下方映射表）。
- `displayControls`：列表页展示的字段 ID 数组。
- `controls`：控件配置（样本为空数组）。
- `filters`：筛选条件（样本为空数组）。
- `sortType`：排序类型，样本为 `0`。
- `sortCid`：排序字段 ID，样本为空字符串。
- `coverType`：封面类型，样本为 `0`。
- `showControlName`：是否显示字段名，样本为 `true`。
- `advancedSetting`：扩展设置对象，包含字符串化子配置。

### `viewType` 映射（基于 HAR 实测）

- `"0"`：表格视图
- `"1"`：看板视图
- `"3"`：画廊视图
- `"4"`：日历视图

### 成功响应（样本）

- HTTP：`200`
- Body 结构：
  - `state`：`1` 表示成功
  - `data.viewId`：新创建的视图 ID
  - `data.*`：返回完整视图配置（名称、字段显示、筛选、排序、advancedSetting 等）

```json
{
  "data": {
    "viewId": "69a98423ed7657adee283e57",
    "name": "表格1",
    "worksheetId": "69a943fe296f91d9c3c86bf3",
    "viewType": 0,
    "displayControls": [
      "69a943fee4311077e074bc45",
      "69a943fee4311077e074bc46"
    ],
    "showControlName": true,
    "advancedSetting": {
      "enablerules": "1",
      "coverstyle": "{\"position\":\"1\",\"style\":3}",
      "navempty": "1",
      "detailbtns": "[]",
      "listbtns": "[]"
    }
  },
  "state": 1
}
```

## 2. 各视图创建样本（请求关键差异）

### 2.1 表格视图（`viewType: "0"`）

- HAR：`表格视图.har`
- 关键参数：
  - `viewId: ""`
  - `viewType: "0"`
  - `name: "表格1"`
  - `displayControls`: 字段 ID 数组
  - `advancedSetting.enablerules: "1"`
  - `advancedSetting.coverstyle: "{\"position\":\"1\",\"style\":3}"`

### 2.2 看板视图（`viewType: "1"`）

- HAR：`看板视图.har`
- 创建请求关键参数：
  - `viewId: ""`
  - `viewType: "1"`
  - `name: "看板"`
- 创建后出现二次保存（同接口）：
  - `viewId: "<刚创建的viewId>"`
  - `editAttrs`: 大字段列表
  - `viewControl`: 分组字段 ID（看板关键配置）

### 2.3 画廊视图（`viewType: "3"`）

- HAR：`画廊视图.har`
- 关键参数：
  - `viewId: ""`
  - `viewType: "3"`
  - `name: "画廊"`
  - `coverCid`: 图片字段 ID
  - `advancedSetting.coverstyle: "{\"position\":\"2\"}"`

### 2.4 日历视图（`viewType: "4"`）

- HAR：`日历视图.har`
- 创建请求关键参数：
  - `viewId: ""`
  - `viewType: "4"`
  - `name: "日历"`
  - `coverCid`: 日期字段 ID（初始请求里存在）
- 创建后出现二次保存（同接口）：
  - `viewId: "<刚创建的viewId>"`
  - `editAttrs: ["advancedSetting"]`
  - `advancedSetting.calendarcids`: `[{begin,end}]` 的字符串化 JSON
  - `editAdKeys: ["calendarcids"]`

## 3. 创建与更新的调用规律（重要）

- `SaveWorksheetView` 同时承担“创建”和“更新”。
- 判定方式：
  - `viewId = ""` => 创建
  - `viewId != ""` 且带 `editAttrs`（或完整字段）=> 更新
- 部分视图需要“两步”：
  1. 先创建基础视图拿到 `viewId`
  2. 再调用一次同接口补关键配置（如看板 `viewControl`、日历 `calendarcids`）

### 失败响应（待补）

- 当前 HAR 未包含失败样本（如重名、参数缺失、鉴权失效）。
- 后续需补充：
  - 常见错误码
  - 错误消息字段（例如 `error_code` / `error_msg` / `state != 1`）

## 4. 调用链路（基于 HAR）

1. 调用 `SaveWorksheetView` 创建视图。
2. 必要时再次调用 `SaveWorksheetView` 补充视图特有配置。
3. 调用 `GetFilterRows` / `GetFilterRowsTotalNum` 拉取视图数据与总数。
4. 调用 `GetWorksheetBtns` 获取按钮配置。
5. 看板场景还会调用 `GetNavGroup`、`GetWorksheetBaseInfo`、`GetWorksheetInfo`。

## 5. 待补项（后续 HAR 可继续追加）

- 其他视图类型 `viewType` 取值（如甘特等）。
- 更新视图、删除视图、复制视图、重命名视图接口。
- 完整鉴权要求（是否必须 `Authorization`、`Cookie`、`accountid` 组合）。
- 错误响应样本。
