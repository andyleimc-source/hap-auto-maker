# HAP 接口录制任务清单

> 目标：用 Chrome 录制功能重新扒取所有接口，获取更完整的参数，同时补录新功能接口。
>
> 录制方法：Chrome DevTools → Network 面板 → 过滤目标请求 → 右键 Copy as cURL / Copy as fetch
> 或使用 Chrome 的 Recorder 面板录制完整操作流程。

---

## 一、已有接口（需重新录制，补全参数）

### 1. 应用管理

| 优先级 | 接口 | 当前文件 | 重录目标 |
|--------|------|---------|---------|
| 🔴 高 | `POST /api/HomeApp/EditAppInfo` | `update_app_navi_style.py` | 补全所有可编辑的导航风格参数（pcNaviStyle 以外的字段）|
| 🟡 中 | `POST /v1/open/app/edit` | `update_app_icons.py` | 确认 icon/颜色参数的完整枚举 |
| 🟢 低 | `GET /api/HomeApp/GetApp` | `update_app_navi_style.py` | 了解完整的应用结构返回字段 |

### 2. 工作表管理

| 优先级 | 接口 | 当前文件 | 重录目标 |
|--------|------|---------|---------|
| 🔴 高 | `POST /api/AppManagement/EditWorkSheetInfoForApp` | `update_worksheet_icons.py` | 除 icon 以外还有哪些字段可编辑（颜色、描述、顺序等）|
| 🔴 高 | `POST /v3/app/worksheets` | `create_worksheets_from_plan.py` | 补全字段类型参数，尤其是复杂字段（公式、子表等）|
| 🟡 中 | `POST /api/Worksheet/DeleteWorksheetView` | `delete_default_views.py` | 确认批量删除参数 |
| 🟡 中 | `GET/POST /api/Worksheet/SaveWorksheetView` | 工作流脚本 | 补全视图配置参数（过滤、排序、分组的完整结构）|

### 3. 数据写入

| 优先级 | 接口 | 当前文件 | 重录目标 |
|--------|------|---------|---------|
| 🔴 高 | `POST /v3/app/worksheets/{id}/rows` | `mock_data_common.py` | 补全所有字段类型的 payload 格式（附件、子表、成员等）|
| 🔴 高 | `POST /api/Worksheet/AddWorksheetRow` | `mock_data_common.py` | 与 v3 接口的差异对比，web 版支持哪些额外字段 |
| 🟡 中 | `PATCH /v3/app/worksheets/{id}/rows/{rowId}` | `mock_data_common.py` | 确认关联字段更新的完整格式 |
| 🟡 中 | `DELETE /v3/app/worksheets/{id}/rows/batch` | `mock_data_common.py` | 确认批量删除上限（一次最多几条）|

### 4. 工作流

| 优先级 | 接口 | 当前文件 | 重录目标 |
|--------|------|---------|---------|
| 🔴 高 | `POST /workflow/flowNode/saveNode` | 多个工作流脚本 | 各节点类型的完整 payload（当前只覆盖了部分节点）|
| 🟡 中 | `POST /workflow/process/add` | 多个触发器脚本 | 触发器配置的完整参数 |
| 🟡 中 | `POST /api/Worksheet/SaveWorksheetBtn` | `execute_workflow_plan.py` | 自定义动作的完整配置字段 |

---

## 二、待录制的新功能接口

### A. 工作表分组（App Navigation Groups）

> HAP 应用左侧导航可以对工作表进行分组，目前未实现。

- [ ] **创建分组**：在应用导航中新建一个分组节点
- [ ] **重命名分组**：修改分组名称
- [ ] **移动工作表进分组**：将已有工作表拖入某个分组
- [ ] **删除分组**：删除分组（工作表是否随之移动？）
- [ ] **折叠/展开分组**：确认是前端行为还是有接口

录制操作路径：应用编辑模式 → 左侧导航 → 新建分组

---

### B. 统计图（Charts / 统计视图）

> 工作表可以创建"统计"视图，展示各类图表。目前未实现。

- [ ] **创建统计视图**：新建一个图表类型的视图
- [ ] **配置图表类型**：柱状图、折线图、饼图等的参数结构
- [ ] **配置 X/Y 轴字段**：字段绑定的 payload 结构
- [ ] **配置分组/汇总方式**：sum、count、avg 等聚合参数
- [ ] **配置过滤条件**：统计视图专属的过滤参数
- [ ] **修改图表样式**：颜色、标题等样式参数
- [ ] **删除统计视图**

录制操作路径：工作表 → 新建视图 → 选择"统计"

---

### C. 工作流更多节点类型

> 当前只实现了少数几种节点，需补录其他常用节点。

#### 已实现的节点
- [x] 新增记录（add_update_record_node）
- [x] 更新记录
- [x] 触发器（工作表事件、定时、自定义动作）

#### 待录制的节点

- [ ] **发送通知**（notification）：站内通知/邮件参数结构
- [ ] **发送消息**：企业微信/钉钉消息节点参数
- [ ] **查找记录**（filter node）：条件查询的 payload 结构
- [ ] **分支判断**（branch/condition node）：多分支条件配置
- [ ] **子流程**（sub-process）：调用另一个工作流的参数
- [ ] **API 请求节点**：调用外部 HTTP 接口的参数结构
- [ ] **代码节点**（code/script）：自定义代码执行的参数
- [ ] **延迟节点**（delay）：等待 N 分钟/小时的配置

录制操作路径：工作流编辑器 → 添加节点 → 逐一录制每种类型

---

### D. 工作表视图（Views）补全

> 当前只实现了基础列表视图，其他视图类型未覆盖。

- [ ] **看板视图**（Kanban）：分组字段、泳道配置
- [ ] **日历视图**（Calendar）：日期字段绑定参数
- [ ] **甘特图视图**（Gantt）：开始/结束日期字段参数
- [ ] **画廊视图**（Gallery）：封面字段配置
- [ ] **层级视图**（Hierarchy）：父子关联字段配置

---

### E. 其他待探索的功能

- [ ] **字段权限设置**：对某个视图/角色限制字段的读写权限
- [ ] **记录权限设置**：行级权限（哪些人能看哪些记录）
- [ ] **应用分享/发布**：将应用发布给外部用户的接口
- [ ] **工作表导入**：批量导入 Excel/CSV 的接口（如有 API）
- [ ] **工作表导出**：导出数据的接口
- [ ] **消息/提醒配置**：字段变更时触发提醒的参数

---

## 三、录制规范

录制时请注意保存以下信息：

```
接口名称：
URL：
Method：
Request Headers：（重点标注认证相关字段）
Request Body：（完整 JSON，包含所有参数）
Response Body：（关键字段说明）
认证方式：v3 AppKey/Sign | Web Cookie/Authorization
备注：（特殊参数说明、枚举值、已知限制）
```

录制结果保存到：`docs/api_recordings/` 目录（待创建），每个功能一个文件。

---

## 四、执行顺序建议

1. **第一批（核心改造）**：工作表分组 + 统计图 → 对应用完整度影响最大
2. **第二批（工作流扩展）**：更多节点类型 → 让工作流更实用
3. **第三批（视图补全）**：看板/日历/甘特图 → 丰富数据展示
4. **第四批（已有接口重录）**：系统性补全参数，提升现有功能质量
