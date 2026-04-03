# 工作流 - 定时触发 API

> 接口：`POST /api/workflow/flowNode/saveNode`（同工作表事件触发，节点类型不同）
> 来源：浏览器抓包，全部 7 种循环类型均已验证
> 认证：Web (Cookie + Authorization)
> Base URL：`https://{your-org}.mingdao.com`

---

## 与工作表事件触发的区别

| 字段 | 工作表事件触发 | 定时触发 |
|------|--------------|--------|
| `appType` | `1`（工作表） | `5`（循环触发）|
| `name` | `"工作表事件触发"` | `"定时触发"` |
| `triggerId` | `"1"~"4"` | 不传 |
| `repeatType` | 不传 | 必传（循环类型枚举）|
| `frequency` | 不传 | 必传（同 repeatType 对应值）|
| `interval` | 不传 | 必传（固定 `1`）|
| `weekDays` | 不传 | 必传（见各类型说明）|
| `executeTime` | 不传 | 必传（首次执行时间）|
| `executeEndTime` | 不传 | 可选（空字符串=不限）|
| `config` | 不传 | 自定义类型必传，其他传 `null` |
| `controls` | 工作表字段定义 | 固定空数组 `[]` |

---

## Request Body

```json
{
  "appType": 5,
  "assignFieldIds": [],
  "processId": "69c24b444aa00636bbc2fd78",
  "nodeId": "startNodeId",
  "flowNodeType": 0,
  "name": "定时触发",
  "executeTime": "2026-03-13 16:30",
  "executeEndTime": "2026-03-31 16:30",
  "repeatType": 1,
  "frequency": 1,
  "interval": 1,
  "weekDays": [],
  "config": null,
  "controls": [],
  "returns": []
}
```

---

## repeatType 枚举

> ⚠️ **注意**：旧版文档（来自 HAR 文件分析）的枚举映射有误，已于 2026-03-24 浏览器实测推翻重建。
> 以下仅标注已实测确认的值，其余待下次录制补完。

| repeatType | frequency | weekDays | config | UI 显示 | 状态 |
|-----------|-----------|---------|--------|---------|------|
| `1` | `1` | `[]` | `null` | 每天（待确认） | ⚠️ 未重新验证 |
| `2` | `2` | `[]` | `null` | ?（待确认） | ⚠️ 未重新验证 |
| `3` | `3` | `[]` | `null` | ?（待确认） | ⚠️ 未重新验证 |
| `4` | `4` | `[]` | `null` | ?（待确认） | ⚠️ 未重新验证 |
| `5` | `2` | `[1,2,3,4,5]` | `null` | 每个工作日（待确认） | ⚠️ 未重新验证 |
| `6` | `4` | `[]` | 见下方 | 自定义（待确认） | ⚠️ 未重新验证 |
| `7` | `7` | `[]` | `null` | **每小时** | ✅ 2026-03-24 浏览器 UI 实测确认 |

> `weekDays` 数字含义：1=周一，2=周二，3=周三，4=周四，5=周五，6=周六，7=周日

### ⏳ 下次录制任务
进入定时触发节点，依次改为以下频率并保存（不发布）：
每天 → 每周 → 每月 → 每年 → 每个工作日 → 自定义
逐一截图 + 抓包，补全上表。

---

## 自定义（repeatType=6）的 config 结构

```json
{
  "minute": { "type": 3, "values": ["30"] },
  "hour":   { "type": 3, "values": ["16"] },
  "day":    { "type": 1, "values": [] },
  "week":   { "type": 0, "values": [] },
  "month":  { "type": 1, "values": [] }
}
```

| type 值 | 含义 | values |
|---------|------|--------|
| `0` | 不限制（`*`） | `[]` |
| `1` | 每（every） | `[]` |
| `3` | 具体值 | `["16"]`、`["1","15"]` |

---

## 时间参数

| 参数 | 类型 | 说明 |
|------|------|------|
| executeTime | string | 首次执行时间，格式 `"YYYY-MM-DD HH:mm"`，UTC+8 |
| executeEndTime | string | 结束时间，格式同上，传 `""` 表示不限制 |

---

## 备注

- `appType=5` = 帮助文档 `startEventAppType: 5（循环触发）`
- `interval` 目前固定为 `1`
- 时间基于 UTC+8（北京时间），界面有提示
- 每周（repeatType=7）的具体触发星期由 `executeTime` 对应的星期自动决定，`weekDays` 传 `[]`
- 每个工作日（repeatType=5）的 `weekDays=[1,2,3,4,5]` 固定不变，无需用户指定
