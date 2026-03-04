项目目标：
创建并自动化管理 HAP 应用及其工作表。


Pipeline 用法：

1. 创建应用流水线（创建应用 -> 获取授权 -> 智能匹配应用 icon -> 更新应用 icon）

- 脚本：`scripts/pipeline_create_app.py`

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_app.py --name "应用名"
```

2. 工作表流水线（规划工作表 -> 创建工作表 -> 匹配并更新工作表 icon）

- 脚本：`scripts/pipeline_worksheets.py`

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheets.py
```

3. 删除应用

- 脚本：`scripts/delete_app.py`

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/delete_app.py --delete-all
```

4. 字段布局流水线（选择应用 -> 规划字段布局 -> 应用字段布局）

- 脚本：`scripts/pipeline_worksheet_layout.py`

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheet_layout.py
```
