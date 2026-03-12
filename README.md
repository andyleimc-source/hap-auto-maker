# hap_auto

HAP 应用自动化工具仓库。目标是把“需求收集 -> 创建应用 -> 建表 -> 布局 -> 视图 -> 筛选 -> 造数 -> 浏览器录制”尽量串成可复跑、可审计、可分步调试的流水线。

当前仓库已经不是单一脚本，而是 3 套能力共同工作：
- HAP 应用搭建与配置自动化
- HAP 现有应用批量造数与关系修复
- `record/` 浏览器操作录制与视频归档

## 1. 当前阶段结论

近期开发已经把主链路基本打通，当前最值得关注的是：
- 已具备“从需求对话到录制归档”的一键链路：`scripts/run_app_to_video.py`
- 已具备“从需求 JSON 到完整执行”的编排器：`scripts/execute_requirements.py`
- 已具备“现有应用批量造数 + 关系修复 + unresolved 清理”的闭环：`scripts/pipeline_mock_data.py`
- 已把 `record/` 从独立实验目录提升为主流程的一部分，支持 `task_template.txt -> task.txt -> run_agent.py`
- 大多数关键阶段都会落盘 JSON，并维护 `*_latest.json`，方便接续和排障

当前仍然要接受的边界：
- LLM 规划默认依赖 Gemini
- HAP 调用同时依赖组织 API 凭据和网页登录态
- Relation 自动修复目前重点支持 `1-1` 和 `1-N` 的单选端，`1-N` 多选端不保证自动回填
- 不是所有脚本都幂等，重复执行前要确认目标应用当前状态

## 2. 近期开发进展

### 2026-03-09
- 新增一键串联脚本 `scripts/run_app_to_video.py`，打通“需求收集 -> 建应用 -> 生成 task -> 浏览器录制 -> 归档”
- 新增 `scripts/fill_task_placeholders.py`，支持纯本地填充 `record/task_template.txt`
- 录制产物归档目录统一到 `data/outputs/app_video_runs/<timestamp>_<appId>/`
- 新增 `summary.md`、`tech_log.json`、`tech_log.md` 等运行摘要，便于回放和复盘
- 主流程相关 JSON 产物可自动复制进单次录制归档目录，便于把“业务配置结果”和“操作视频”对齐

### 2026-03-08
- `record/run_agent.py` 完成结构拆分，核心能力下沉到 `record/core/`
- 录制链路稳定支持 `wait_seconds`，解决长等待时 CDP 无新帧导致“视频跳过”的问题
- 增加浏览器 repaint hack，保证静态等待段仍保留可见停留
- 默认网页缩放通过原生 Chrome `Preferences` 固定到 `125%`，替代模糊的 DPR 方案
- 录制过程中的黑屏 logo / 空白帧问题已做底层规避

### 2026-03-07
- `record/task.json` 迁移为 `record/task.txt`
- 支持 `solo`、`no`、`#`、`//` 等更适合人工编辑的任务控制方式
- 明道云 iframe 场景下的元素定位稳定性提升
- `storage/`、`runs/`、`venv/` 等录制运行态目录已明确隔离

## 3. 当前目标

短期目标：
- 把 README、脚本入口、产物目录、排障方式统一成一份开发说明
- 提高主流程复跑稳定性，减少“上一步成功、下一步接不上”的人工干预
- 继续补齐录制链路的任务模板和可复用素材

中期目标：
- 让 `execute_requirements.py` 的阶段边界更稳定，失败时更容易断点续跑
- 让 mock data、view、filter、layout 这些阶段的输入输出约定进一步统一
- 把“新建应用”和“已有应用维护”两条路径彻底分离清楚

## 4. 仓库结构

```text
hap_auto/
├── config/                  # 本地凭据与策略
├── data/
│   ├── assets/icons/        # icon 素材
│   ├── api_docs/            # 接口资料与抓取结果
│   └── outputs/             # 所有阶段性 JSON / 运行结果
├── record/                  # 浏览器录制子系统
├── scripts/                 # 稳定入口层
│   ├── hap/                 # HAP 业务实现
│   ├── gemini/              # Gemini 规划/匹配实现
│   └── auth/                # 登录态刷新
└── view/                    # 抓包/接口行为样本
```

分层约定：
- 日常执行优先用 `scripts/*.py`
- 调试实现细节再看 `scripts/hap/*.py`、`scripts/gemini/*.py`
- 录制相关逻辑集中在 `record/`
- 所有中间产物默认写到 `data/outputs/`

## 5. 环境与依赖

建议：
- Python 3.11+
- macOS 本地运行
- 可用的 Gemini API Key
- 可用的 HAP 组织级凭据
- 可用的明道云网页登录账号

主仓库常用依赖：

```bash
python3 -m pip install requests google-genai playwright prompt-toolkit
python3 -m playwright install chromium
```

`record/` 子系统额外依赖见 [record/requirements.txt](/Users/andy/Desktop/hap_auto/record/requirements.txt)：

```bash
cd /Users/andy/Desktop/hap_auto/record
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium
```

### 5.1 GitHub 协作模式（密钥不入库）

本仓库采用“代码入库、密钥本地配置”的方式：
- 可以把仓库公开/共享到 GitHub
- 同事只需克隆代码并在本地填写自己的密钥文件
- 真实密钥文件已在 `.gitignore` 中忽略，不应提交

同事首次克隆后可按以下步骤配置：

```bash
cd /Users/andy/Desktop/hap_auto
cp config/credentials/gemini_auth.example.json config/credentials/gemini_auth.json
cp config/credentials/organization_auth.example.json config/credentials/organization_auth.json
cp config/credentials/auth_config.example.py config/credentials/auth_config.py
cp config/credentials/login_credentials.example.py config/credentials/login_credentials.py
```

然后把上面 4 个目标文件中的占位值替换成自己的真实配置。

## 6. 必备本地配置

运行前至少确认以下文件存在且可用：
- [config/credentials/gemini_auth.json](/Users/andy/Desktop/hap_auto/config/credentials/gemini_auth.json)
- [config/credentials/organization_auth.json](/Users/andy/Desktop/hap_auto/config/credentials/organization_auth.json)
- [config/credentials/auth_config.py](/Users/andy/Desktop/hap_auto/config/credentials/auth_config.py)
- [config/credentials/login_credentials.py](/Users/andy/Desktop/hap_auto/config/credentials/login_credentials.py)

作用说明：
- `gemini_auth.json`：Gemini 规划、匹配、需求收集
- `organization_auth.json`：HAP OpenAPI 调用
- `auth_config.py`：网页接口 Cookie / Authorization
- `login_credentials.py`：自动登录刷新网页认证

注意：
- 这些都是本地敏感文件，不应提交
- `auth_config.py` 中的 `COOKIE`、`AUTHORIZATION` 会过期

## 7. 认证刷新

网页登录态失效时，优先执行：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/refresh_auth.py
```

无头模式：

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/refresh_auth.py --headless
```

该脚本会自动回写 [config/credentials/auth_config.py](/Users/andy/Desktop/hap_auto/config/credentials/auth_config.py)。

## 8. 快速开始

先进入项目目录：

```bash
cd /Users/andy/Desktop/hap_auto
```

### 8.1 新应用：从需求对话开始

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/agent_collect_requirements.py
```

说明：
- 终端与 Gemini 多轮对话
- 输入 `/done` 后生成 requirement spec
- 默认自动接着执行 `execute_requirements.py`

### 8.2 新应用：直接执行已有需求 JSON

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/execute_requirements.py \
  --spec-json /Users/andy/Desktop/hap_auto/data/outputs/requirement_specs/requirement_spec_latest.json
```

### 8.3 已有应用：一键造数

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/pipeline_mock_data.py
```

### 8.4 已有应用：清空记录

```bash
python3 /Users/andy/Desktop/hap_auto/scripts/clear_app_records.py --dry-run
python3 /Users/andy/Desktop/hap_auto/scripts/clear_app_records.py
```

## 9. 功能与主流程

### 9.1 需求驱动总编排

入口：
- [scripts/agent_collect_requirements.py](/Users/andy/Desktop/hap_auto/scripts/agent_collect_requirements.py)
- [scripts/execute_requirements.py](/Users/andy/Desktop/hap_auto/scripts/execute_requirements.py)

主流程：
1. 创建应用
2. 获取应用授权
3. 规划工作表并建表
4. 匹配并更新应用 / 工作表图标
5. 规划并应用工作表布局
6. 规划并创建视图
7. 规划并应用表格视图筛选
8. 更新应用导航风格
9. 对应用执行 mock data 流程

### 9.2 造数与关系修复

入口：
- [scripts/pipeline_mock_data.py](/Users/andy/Desktop/hap_auto/scripts/pipeline_mock_data.py)

流程：
1. 选择已授权应用
2. 导出结构快照
3. Gemini 生成造数 plan / bundle
4. 写入记录
5. 分析 Relation 一致性
6. 应用修复计划
7. 如仍 unresolved，则删除源记录，避免留下脏数据

当前支持情况：
- 支持 `1-1`
- 支持 `1-N` 的单选端字段
- 不保证自动回填 `1-N` 的多选端字段

### 9.3 录制子系统（可选）

入口：
- [record/run_agent.py](/Users/andy/Desktop/hap_auto/record/run_agent.py)

核心能力：
- 自然语言任务解析
- `wait_seconds` 可见等待
- repaint hack，避免静止阶段丢帧
- 原生 Chrome 缩放注入
- 登录态复用
- 运行日志、视频、GIF 自动落盘

## 10. 关键脚本清单

### 10.1 推荐直接使用的入口脚本

- `scripts/agent_collect_requirements.py`：对话式收集需求，默认自动执行
- `scripts/execute_requirements.py`：执行需求 JSON
- `scripts/run_app_to_video.py`：从策划直接到录制归档
- `scripts/pipeline_create_app.py`：创建应用并处理应用 icon
- `scripts/pipeline_worksheets.py`：工作表规划、建表、工作表 icon
- `scripts/pipeline_worksheet_layout.py`：布局规划与应用
- `scripts/pipeline_views.py`：视图规划与创建
- `scripts/pipeline_tableview_filters.py`：筛选规划与应用
- `scripts/pipeline_mock_data.py`：造数总流程
- `scripts/clear_app_records.py`：清空应用记录
- `scripts/fill_task_placeholders.py`：生成 `record/task.txt`
- `scripts/refresh_auth.py`：刷新网页登录态
- `scripts/gemini/list_gemini_models.py`：查询并导出当前 API Key 可用的 Gemini 模型列表

### 10.2 造数排障常用脚本

- `scripts/analyze_relation_consistency.py`
- `scripts/apply_relation_repair_plan.py`
- `scripts/delete_unresolved_records.py`
- `scripts/export_app_mock_schema.py`
- `scripts/plan_mock_data_gemini.py`
- `scripts/write_mock_data_from_plan.py`

### 10.3 删除类脚本

- `scripts/delete_app.py`
- `scripts/clear_app_records.py`

删除类脚本建议默认先 `--dry-run`。

## 11. 产物目录说明

最常用的输出目录：

- `data/outputs/requirement_specs/`：需求规格
- `data/outputs/execution_runs/`：需求执行报告
- `data/outputs/app_authorizations/`：应用授权信息
- `data/outputs/worksheet_plans/`：工作表规划
- `data/outputs/worksheet_create_results/`：建表结果
- `data/outputs/worksheet_layout_plans/`：布局规划
- `data/outputs/worksheet_layout_apply_results/`：布局应用结果
- `data/outputs/view_plans/`：视图规划
- `data/outputs/view_create_results/`：视图创建结果
- `data/outputs/tableview_filter_plans/`：筛选规划
- `data/outputs/tableview_filter_apply_results/`：筛选应用结果
- `data/outputs/mock_data_schema_snapshots/`：造数前结构快照
- `data/outputs/mock_data_plans/`：造数规划
- `data/outputs/mock_data_write_results/`：写入结果
- `data/outputs/mock_relation_repair_plans/`：关系修复计划
- `data/outputs/mock_relation_repair_apply_results/`：关系修复执行结果
- `data/outputs/mock_unresolved_delete_results/`：删除 unresolved 结果
- `data/outputs/app_video_runs/`：一键录制归档

产物约定：
- 多数目录会维护一份 `*_latest.json`
- 选择应用类脚本通常依赖 `app_authorize_<appId>.json`
- 排障时先看对应 JSON 和日志，不要只盯终端输出

## 12. 开发中的必要说明

### 12.1 推荐工作方式

- 先跑入口脚本，不要一上来改实现层
- 先看 `data/outputs/` 的最新产物，再决定是否重跑
- 涉及写真实应用时，优先使用 `--dry-run`
- 规划和执行尽量分开看，不要把 LLM 输出直接当成可靠执行输入

### 12.2 关于 `scripts/` 与 `scripts/hap/`

- `scripts/*.py` 多数只是稳定转发入口
- 真正逻辑通常在 `scripts/hap/` 或 `scripts/gemini/`
- 日常执行不要直接依赖 `scripts/hap/` 的内部文件路径，避免后续重构成本高

### 12.3 关于 `record/`

- `record/` 现在不是附属 demo，而是主流程的一部分
- `record/task.txt` 是运行态文件，`record/task_template.txt` 才是模板
- `record/storage/`、`record/runs/`、`record/venv/` 都属于本地运行态，不要作为稳定输入依赖

## 13. 避坑与排障

### 13.1 Gemini 调用失败

- 先检查 [config/credentials/gemini_auth.json](/Users/andy/Desktop/hap_auto/config/credentials/gemini_auth.json)
- 再检查模型名是否可用，当前脚本里常见默认值是 `gemini-2.5-pro` 或 `gemini-2.5-flash`
  - 可以使用以下命令查询并确认当前 API Key 下所有可用的模型：
    ```bash
    python3 /Users/andy/Desktop/hap_auto/scripts/gemini/list_gemini_models.py
    ```
    *(执行后将输出 JSON 到终端，并在 `data/outputs/gemini_models/` 生成结果文件)*
- `record/` 录制链路还要额外检查 [record/.env](/Users/andy/Desktop/hap_auto/record/.env)

### 13.2 页面接口 401 / 403

- 基本就是 [config/credentials/auth_config.py](/Users/andy/Desktop/hap_auto/config/credentials/auth_config.py) 过期
- 直接重新跑 `scripts/refresh_auth.py`

### 13.3 OpenAPI 调用失败

- 检查 [config/credentials/organization_auth.json](/Users/andy/Desktop/hap_auto/config/credentials/organization_auth.json)
- 确认 `base_url` 与当前环境一致

### 13.4 选择不到应用

- 一般是 `data/outputs/app_authorizations/` 没有对应 `app_authorize_<appId>.json`
- 先跑创建应用流程，或单独补授权文件

### 13.5 造数后还有空关联

- 先看 `mock_relation_repair_plan` 和 `mock_relation_repair_apply_result`
- 若 unresolved 仍存在，先确认是不是当前未覆盖的关系类型

### 13.6 录制里“等待几秒”但视频看起来没停留

- 不要直接删 `record/run_agent.py` 里的等待与 repaint 相关逻辑
- `browser-use` + CDP 录制在静止页面下可能不自然产帧，这部分已经做了补帧处理

### 13.7 录制里点击不稳定

- 明道云弹层和侧栏常有淡出动画，下一步太快会点在遮罩层上
- 指令里要明确“等待侧栏完全消失”或“等待 1-2 秒”

### 13.8 网页缩放不要乱改

- 当前稳定方案是原生 `Preferences` 注入
- 不要改回 `force-device-scale-factor`、CSS `zoom`、快捷键模拟缩放

## 14. 已知限制

- 不是所有脚本都支持断点续跑
- 不是所有阶段都提供统一 CLI 参数风格
- 录制链路对本地环境依赖比较重，尤其是 `record/venv`、浏览器、登录态
- 一些目录下已有大量历史产物，默认“取最新”时要注意是否误用了旧结果

## 15. 建议的日常使用顺序

### 新应用

1. `scripts/agent_collect_requirements.py`
2. `scripts/execute_requirements.py`
3. 需要演示视频时再跑 `scripts/run_app_to_video.py`

### 已有应用维护

1. `scripts/pipeline_mock_data.py`
2. 必要时 `scripts/analyze_relation_consistency.py`
3. 必要时 `scripts/apply_relation_repair_plan.py`
4. 需要清场时 `scripts/clear_app_records.py`

### 只处理录制

1. `scripts/fill_task_placeholders.py`
2. `record/run_agent.py`

## 16. 补充文档

- [record/README.md](/Users/andy/Desktop/hap_auto/record/README.md)
- [record/HAP_Automation_Best_Practices.md](/Users/andy/Desktop/hap_auto/record/HAP_Automation_Best_Practices.md)

如果只看一份文档，优先看本 README；如果只调录制，再看 `record/README.md`。
