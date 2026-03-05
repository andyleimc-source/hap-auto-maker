项目目标：
创建并自动化管理 HAP 应用、工作表、字段布局、图标与测试数据。


一、脚本分层说明

1. 入口脚本层（推荐直接运行）
- 目录：`/Users/andy/Desktop/hap_auto/scripts/`
- 说明：这些脚本是稳定入口，内部通过 `runpy` 转发到 `scripts/hap/` 或 `scripts/gemini/`。

2. 业务实现层
- HAP 业务实现：`/Users/andy/Desktop/hap_auto/scripts/hap/`
- Gemini 业务实现：`/Users/andy/Desktop/hap_auto/scripts/gemini/`

3. 认证脚本层
- 目录：`/Users/andy/Desktop/hap_auto/scripts/auth/`
- 说明：负责刷新网页登录态（Cookie/Authorization）。


二、主要 Pipeline（推荐）

1. 创建应用流水线（创建应用 -> 获取授权 -> 匹配应用 icon -> 更新应用 icon）
- 入口脚本：`/Users/andy/Desktop/hap_auto/scripts/pipeline_create_app.py`
- 典型命令：
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_app.py --name "应用名"
```

2. 工作表流水线（规划工作表 -> 创建工作表 -> 匹配并更新工作表 icon）
- 入口脚本：`/Users/andy/Desktop/hap_auto/scripts/pipeline_worksheets.py`
- 典型命令：
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheets.py
```

3. 字段布局流水线（选择应用 -> 规划字段布局 -> 应用布局）
- 入口脚本：`/Users/andy/Desktop/hap_auto/scripts/pipeline_worksheet_layout.py`
- 典型命令：
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheet_layout.py
```

4. 造数流水线（选应用/选表 -> 数量策略分析 -> Gemini 造数 -> 语义关系规划 -> 批量写入 -> 关联回填 -> 父子运算一致性修正）
- 入口脚本：`/Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py`
- 典型命令：
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py
```

5. 工作表 icon 流水线（拉清单 -> 匹配 icon -> 批量更新）
- 入口脚本：`/Users/andy/Desktop/hap_auto/scripts/pipeline_icon.py`
- 典型命令：
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_icon.py
```

6. 需求驱动执行（先对话整理需求 -> 再按需求一键执行）
- 需求对话脚本：`/Users/andy/Desktop/hap_auto/scripts/agent_collect_requirements.py`
- 需求执行脚本：`/Users/andy/Desktop/hap_auto/scripts/execute_requirements.py`
- 典型命令：
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/agent_collect_requirements.py
python3 /Users/andy/Desktop/hap_auto/scripts/execute_requirements.py --spec-json /Users/andy/Desktop/hap_auto/data/outputs/requirement_specs/requirement_spec_latest.json
```


二点五、命令速查（可直接复制）

先进入项目目录：
```bash
cd /Users/andy/Desktop/hap_auto
```

1) 需求对话 + /done 自动执行全流程
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/agent_collect_requirements.py
```

2) 只执行已有需求 JSON（不走对话）
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/execute_requirements.py \
  --spec-json /Users/andy/Desktop/hap_auto/data/outputs/requirement_specs/requirement_spec_latest.json
```

3) 创建应用（含授权和应用 icon）
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_app.py \
  --name "医院后勤管理系统"
```

4) 工作表规划 + 建表 + 工作表 icon
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheets.py
```

5) 字段布局规划 + 应用布局
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_worksheet_layout.py \
  --app-id <你的appId> \
  --requirements "按业务角色优化表单布局"
```

6) 造数（交互式）
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py
```

7) 造数（非交互，自动按表性质分析数量）
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py \
  --app-id <你的appId> \
  --worksheet-ids all \
  --row-count-mode auto \
  --delete-history n
```

8) 造数（非交互，固定数量覆盖）
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_create_rows.py \
  --app-id <你的appId> \
  --worksheet-ids all \
  --row-count-mode fixed \
  --rows-per-table 3 \
  --delete-history n
```

9) 删除应用

批量删除（先列出应用，再输入 Y 全删 或 1,2,3 按序号删）：
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/delete_app.py --delete-all
```


10) 工作表 icon 重新匹配并更新
```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_icon.py \
  --app-auth-json /Users/andy/Desktop/hap_auto/data/outputs/app_authorizations/app_authorize_<你的appId>.json \
  --app-id <你的appId>
```


三、主要单功能脚本（可用于后续合并/串联）

3.1 应用管理
1. `create_app.py`：创建应用
2. `get_app_authorize.py`：获取应用授权并落盘
3. `delete_app.py`：删除应用（支持全删/按序号删）
4. `update_app_icons.py`：批量更新应用 icon
5. `update_app_navi_style.py`：修改应用导航风格 `pcNaviStyle`
6. `list_apps_for_icon.py`：拉取应用清单（供 icon 匹配）

3.2 工作表管理
1. `plan_app_worksheets_gemini.py`：Gemini 规划工作表结构
2. `create_worksheets_from_plan.py`：根据规划创建工作表（1对N 双向显示：N端单选、1端多选，并校验避免异常 N-N）
3. `list_app_worksheets.py`：拉取某应用下工作表清单
4. `update_worksheet_icons.py`：批量更新工作表 icon

3.3 字段布局
1. `plan_worksheet_layout.py`：规划每个字段在表单中的布局
2. `apply_worksheet_layout.py`：应用字段布局（调用网页端接口）

3.4 造数与记录
1. `pipeline_create_rows.py`：交互式造数总入口
2. 关键能力：按依赖顺序创建记录、关联字段二阶段回填、人员字段默认写固定账号 ID、可选清理历史记录后再造数、按表性质自动分析造数数量、按语义规划关联映射（避免随机关联）
3. 非交互参数：支持 `--app-id --worksheet-ids --row-count-mode --rows-per-table --seed-count-plan-json --relation-plan-json --consistency-plan-json --skip-consistency --delete-history`

3.5 Gemini 相关
1. `list_gemini_models.py`：列出可用模型
2. `match_app_icons_gemini.py`：应用名匹配 icon
3. `match_worksheet_icons_gemini.py`：工作表名匹配 icon
4. `plan_app_worksheets_gemini.py`：工作表规划
5. `plan_row_seed_counts_gemini.py`：按工作表性质分析造数层级与数量（输出 row_seed_count_plan JSON）
6. `plan_row_relation_links_gemini.py`：按源记录语义规划关联字段映射（输出 row_relation_plan JSON）
7. `plan_parent_child_constraints_gemini.py`：规划父子表运算一致性约束（输出 parent_child_constraint_plan JSON）

3.6 父子一致性修正
1. `enforce_parent_child_consistency.py`：执行父子表数量/金额等运算一致性校验与修正

3.7 认证相关
1. `refresh_auth.py`：刷新网页登录态并更新 `auth_config.py`

3.8 需求 Agent 与执行器
1. `agent_collect_requirements.py`：终端与 Gemini 多轮对话，输入 `/done` 生成 `workflow_requirement_v1` JSON
2. `execute_requirements.py`：读取需求 JSON，编排执行应用创建、工作表、icon、布局、导航、造数
3. `seed_data` 推荐结构（动态数量默认）：
```json
{
  "seed_data": {
    "enabled": true,
    "row_count_mode": "auto",
    "rows_per_table": 0,
    "delete_history_before_seed": false,
    "model": "gemini-3.1-pro-preview"
  }
}
```


四、数据与结果目录（关键）

1. 授权文件
- `/Users/andy/Desktop/hap_auto/data/outputs/app_authorizations/`

2. 工作表规划与创建结果
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_create_results/`

3. 字段布局规划与执行结果
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_layout_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_layout_apply_results/`

4. icon 匹配与更新结果
- `/Users/andy/Desktop/hap_auto/data/outputs/app_icon_match_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/app_icon_updates/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_icon_match_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/worksheet_icon_updates/`

5. 造数结果
- `/Users/andy/Desktop/hap_auto/data/outputs/row_seed_schemas/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_seed_count_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_relation_contexts/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_relation_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_consistency_contexts/`
- `/Users/andy/Desktop/hap_auto/data/outputs/parent_child_constraint_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/parent_child_consistency_results/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_seed_plans/`
- `/Users/andy/Desktop/hap_auto/data/outputs/row_seed_results/`

6. 需求与执行报告
- `/Users/andy/Desktop/hap_auto/data/outputs/requirement_specs/`
- `/Users/andy/Desktop/hap_auto/data/outputs/execution_runs/`


五、当前开发任务状态

1. 创建应用流水线：已完成
2. 工作表流水线：已完成
3. 删除应用（全删/按序号删）：已完成
4. 字段布局流水线：已完成
5. 造数流水线：已完成
6. 关联字段回填与顺序控制：已完成
7. 造数前历史记录清理：已完成
8. 人员字段默认固定账号：已完成
9. 应用导航风格修改：已完成
10. 需求对话 Agent（生成标准需求 JSON）：已完成
11. 需求执行引擎（按 JSON 编排全流程）：已完成
