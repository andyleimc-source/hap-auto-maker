# 工作流 HAR 采集模板

用途：后续你继续抓“触发器”或“动作节点”的 HAR 时，统一按这个模板补资料。  
当前基线 HAR：`/Users/andy/Desktop/hap_auto/record/action/创建工作流.har`

## 1. 采集目标
每次只抓一种“新增能力”，不要一次混很多变量。建议拆成以下粒度：
- 一个新触发器
  - 例如：定时触发、按日期字段触发、Webhook 触发
- 一个新动作节点
  - 例如：更新记录、发送站内通知、发送邮件、查询记录
- 一个新配置能力
  - 例如：触发条件、触发字段、执行方式、流程参数

## 2. 抓包前的最小场景
每份 HAR 最好只做一个最小闭环：
1. 新建工作流
2. 只配置一个触发器
3. 只配置一个动作节点
4. 只填写 1-2 个必要字段
5. 发布

这样后面容易识别“哪一个请求对应哪一步”。

## 3. 建议命名
HAR 文件名建议固定成：

```text
工作流_<触发器>_<动作节点>_<关键特性>.har
```

示例：
- `工作流_工作表触发_新增记录_字段映射.har`
- `工作流_定时触发_发送通知_固定内容.har`
- `工作流_工作表触发_更新记录_引用触发字段.har`

## 4. 每份 HAR 必填元信息
请在同目录补一个同名 `.md` 或直接把下面内容发我：

```md
# HAR 说明

- HAR 路径：
- 触发器类型：
- 动作节点类型：
- 操作页面：
- 场景说明：
- 源工作表：
- 目标工作表：
- 关键字段映射：
  - 源字段A -> 目标字段B
  - 固定值 -> 目标字段C
- 是否发布：
- 是否启用：
```

## 5. 我后续最需要你提供的请求信息
看到这些请求时，优先告诉我对应的是哪一步：

### A. 创建流程骨架
- `workflow/process/add`
- `AppManagement/AddWorkflow`

### B. 保存触发器
- `workflow/flowNode/saveNode`
- 如果是触发器，请额外说明：
  - `flowNodeType`
  - `triggerId`
  - 是否带 `assignFieldIds`
  - 是否带 `operateCondition`

### C. 新增动作节点
- `workflow/flowNode/add`
- 请额外说明：
  - `typeId`
  - `actionId`
  - `prveId`

### D. 保存动作节点
- `workflow/flowNode/saveNode`
- 如果是动作节点，请额外说明：
  - `flowNodeType`
  - `appId`
  - `fields / findFields / sendContent / formulaNode / specialNode`
  - 哪些字段是必填
  - 哪些字段是动态引用格式

### E. 拉取辅助元数据
- `workflow/flowNode/get`
- `workflow/flowNode/getNodeDetail`
- `workflow/flowNode/getAppTemplateControls`
- `workflow/flowNode/getFlowNodeAppDtos`

### F. 发布
- `workflow/process/update`
- `workflow/process/publish`

## 6. 需要你额外确认的字段
每抓一种新能力，尽量补齐这些观察：

```md
- 触发器 / 动作的中文名称：
- 对应 request URL：
- Method：
- Referer：
- 关键 query 参数：
- 最小请求体：
- 哪些字段改动后请求仍成功：
- 哪些字段缺失后请求失败：
- 成功响应中哪个字段代表 processId / nodeId / publishedProcessId：
- 是否依赖前置 GET 请求结果：
```

## 7. 动态值格式记录规范
如果你看到字段值不是固定文本，而是这种“节点变量”：

```text
$<nodeId>-<fieldId>$
```

请单独记下来：
- 来源节点类型
- 来源节点名称
- 来源字段 id
- 目标字段 id

这是后面把 plan 转成真实请求最关键的一层。

## 8. 当前代码已接入的能力
- 触发器：
  - `worksheet:create`
  - `worksheet:update`（代码已接入，仍建议补 HAR 二次确认）
- 动作节点：
  - `create_record`

## 9. 当前最优先补抓的 HAR
建议按这个顺序继续补：
1. `定时触发 + 新增记录`
2. `工作表事件触发 + 更新记录`
3. `工作表事件触发 + 发送站内通知`
4. `工作表事件触发 + 触发条件`
5. `工作表事件触发 + 指定触发字段`

补齐这些后，现有 pipeline 的可执行面会明显扩大。
