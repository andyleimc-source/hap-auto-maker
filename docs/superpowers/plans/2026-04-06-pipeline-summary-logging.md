# Pipeline 实时摘要日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在非 verbose 模式下实时显示各步骤的关键成果摘要（工作表名、字段、视图数、工作流节点等），让用户无需 verbose 也能实时监控 pipeline 进度。

**Architecture:** 在 `utils.py` 中新增 `log_summary()` 工具函数，输出带 `[SUMMARY]` 前缀的行。`step_runner.py` 的 `reader()` 在非 verbose 模式下过滤并透传这些行。各子脚本在关键完成点调用 `log_summary()`。`waves.py` 中内联执行的视图逻辑直接调用 `log_summary()`。

**Tech Stack:** Python 3, 现有 pipeline 框架

---

## File Map

| 文件 | 操作 | 职责 |
|------|------|------|
| `scripts/hap/utils.py` | 修改 | 新增 `log_summary()` 函数 |
| `scripts/hap/pipeline/step_runner.py` | 修改 | `reader()` 增加 `[SUMMARY]` 行过滤透传 |
| `scripts/gemini/plan_app_worksheets_gemini.py` | 修改 | 工作表规划完成后输出摘要 |
| `scripts/hap/executors/create_worksheets_from_plan.py` | 修改 | 每张表创建后输出摘要 |
| `scripts/hap/executors/create_sections_from_plan.py` | 修改 | 每个分组创建后输出摘要 |
| `scripts/hap/pipeline/waves.py` | 修改 | 视图创建完成后输出摘要（内联逻辑） |
| `workflow/scripts/execute_workflow_plan.py` | 修改 | 每条工作流创建后输出摘要 |
| `scripts/hap/executors/create_pages_early.py` | 修改 | Page 创建完成后输出摘要 |
| `scripts/hap/executors/create_single_ws_charts.py` | 修改 | 图表创建完成后输出摘要 |
| `scripts/hap/pipeline_app_roles.py` | 修改 | 角色创建完成后输出摘要 |
| `scripts/hap/create_roles_from_recommendation.py` | 修改 | 角色名称列表摘要 |
| `scripts/hap/pipeline_mock_data.py` | 修改 | 造数完成后输出摘要 |
| `scripts/hap/mock_data_common.py` | 修改 | 每张表写入完成后输出摘要 |
| `scripts/hap/executors/create_chatbots_from_plan.py` | 修改 | 机器人创建后输出摘要 |

---

### Task 1: 核心机制——`log_summary()` + `step_runner` 过滤

**Files:**
- Modify: `scripts/hap/utils.py:54` (文件末尾)
- Modify: `scripts/hap/pipeline/step_runner.py:20-49`

- [ ] **Step 1: 在 `utils.py` 末尾添加 `log_summary()`**

```python
# 在 scripts/hap/utils.py 末尾追加

SUMMARY_PREFIX = "[SUMMARY] "

def log_summary(msg: str) -> None:
    """输出带 [SUMMARY] 前缀的摘要行，供 step_runner 在非 verbose 模式下透传。"""
    print(f"{SUMMARY_PREFIX}{msg}", flush=True)
```

- [ ] **Step 2: 改造 `step_runner.py` 的 `run_cmd()` 函数**

将 `reader()` 从只在 verbose 时打印，改为也在非 verbose 时透传 `[SUMMARY]` 行：

```python
# scripts/hap/pipeline/step_runner.py
# 在文件顶部 import 区域后新增：
from utils import SUMMARY_PREFIX

# 替换 run_cmd() 中的 reader 函数（约第 45-49 行）：
# 旧代码：
#     def reader(pipe, bucket):
#         for line in pipe:
#             bucket.append(line)
#             if verbose:
#                 print(line, end="", flush=True)
# 新代码：
    def reader(pipe, bucket):
        for line in pipe:
            bucket.append(line)
            if verbose:
                print(line, end="", flush=True)
            elif line.startswith(SUMMARY_PREFIX):
                clean = line[len(SUMMARY_PREFIX):]
                print(f"    {clean}", end="", flush=True)
```

- [ ] **Step 3: 提交**

```bash
git add scripts/hap/utils.py scripts/hap/pipeline/step_runner.py
git commit -m "feat: 新增 log_summary() 摘要机制和 step_runner 过滤透传"
```

---

### Task 2: 工作表规划摘要

**Files:**
- Modify: `scripts/gemini/plan_app_worksheets_gemini.py:652-665`

- [ ] **Step 1: 添加 import 和摘要输出**

在文件顶部的 import 区域（或 `main()` 函数开头），添加 `log_summary` 的导入。由于此脚本在 `scripts/gemini/` 目录而非 `scripts/hap/`，需要确认 `utils.py` 已在 sys.path 中。查看该文件的已有 import，它已经通过 `sys.path` 设置导入了 `scripts/hap/` 下的模块。

在 `main()` 函数中，约第 658 行 `print("规划完成（概览）")` 之前，添加摘要输出：

```python
# scripts/gemini/plan_app_worksheets_gemini.py
# 在文件顶部已有的 from ... import 区域添加：
from utils import log_summary

# 在 main() 中，第 652 行 worksheets = plan.get("worksheets", []) 之后，
# 第 658 行 print("规划完成（概览）") 之前，插入：
    ws_names = [str(w.get("name", "")).strip() for w in worksheets if isinstance(w, dict)]
    log_summary(f"规划完成，共 {len(ws_names)} 张：{'、'.join(ws_names)}")
```

- [ ] **Step 2: 提交**

```bash
git add scripts/gemini/plan_app_worksheets_gemini.py
git commit -m "feat: 工作表规划完成后输出摘要（工作表名称列表）"
```

---

### Task 3: 工作表创建摘要

**Files:**
- Modify: `scripts/hap/executors/create_worksheets_from_plan.py:830-835`

- [ ] **Step 1: 添加 import**

```python
# 在文件顶部 import 区域添加（utils.py 已在 sys.path 中）：
from utils import log_summary
```

- [ ] **Step 2: 在每张表创建成功后输出摘要**

在 `_create_one_ws()` 返回处或在 `as_completed` 循环中（约第 832-835 行），每张表完成后添加摘要。因为是并发创建，在 `as_completed` 循环的 `future.result()` 之后添加：

```python
# scripts/hap/executors/create_worksheets_from_plan.py
# 在约第 833 行 future.result() 解包之后，name_to_id[ws_name] = worksheet_id 之前，插入：

            # 统计字段：normal + relation + deferred
            all_fields = []
            ws_obj = futures[future]
            for f in (ws_obj.get("fields", []) if isinstance(ws_obj.get("fields"), list) else []):
                if isinstance(f, dict):
                    fname = str(f.get("name", "") or f.get("controlName", "")).strip()
                    ftype = str(f.get("type_label", "") or f.get("type", "")).strip()
                    if fname:
                        all_fields.append(f"{fname}({ftype})" if ftype else fname)
            log_summary(f"✓ 工作表「{ws_name}」已创建（{len(all_fields)} 个字段）")
            if all_fields:
                log_summary(f"  {' | '.join(all_fields)}")
```

注意：plan JSON 中字段的 `type` 是字符串（如 "Text", "SingleSelect", "Phone" 等），`type_label` 为空。直接使用 `type` 字段值作为类型显示。

- [ ] **Step 3: 提交**

```bash
git add scripts/hap/executors/create_worksheets_from_plan.py
git commit -m "feat: 每张工作表创建后输出摘要（名称+字段数+字段列表）"
```

---

### Task 4: 分组创建摘要

**Files:**
- Modify: `scripts/hap/executors/create_sections_from_plan.py:92,163,170-174`

- [ ] **Step 1: 添加 import 和摘要输出**

```python
# 文件顶部添加：
from utils import log_summary
```

在 `run_mode_one()` 中，每个分组创建/复用完成后（约第 163 行和第 92 行），输出摘要。分组的工作表名列表在 `sec.get("worksheets", [])`：

```python
# 在 run_mode_one() 的 for 循环中，每次 name_to_section_id[name] = section_id 之后（约第 169 行），
# result_sections.append(...) 之后（约第 174 行），插入：
        ws_list = sec.get("worksheets", [])
        ws_names_str = "、".join(str(w).strip() for w in ws_list) if ws_list else "无"
        log_summary(f"✓ 分组「{name}」已创建（{len(ws_list)} 张表：{ws_names_str}）")
```

- [ ] **Step 2: 提交**

```bash
git add scripts/hap/executors/create_sections_from_plan.py
git commit -m "feat: 分组创建后输出摘要（分组名+工作表列表）"
```

---

### Task 5: 视图创建摘要（waves.py 内联）

**Files:**
- Modify: `scripts/hap/pipeline/waves.py:429-431`

- [ ] **Step 1: 添加 import 和摘要输出**

```python
# 在 waves.py 顶部 import 区域添加：
from utils import log_summary
```

在 `_do_views_for_ws()` 函数中（约第 429 行），每张表视图创建完成后输出摘要。在 `_view_results_all.append(r)` 之前添加：

```python
# waves.py 中 _do_views_for_ws 函数内，约第 429 行 with _view_lock: 之前插入：
            new_count = len(r.get("new_views_results", []))
            default_ok = 1 if isinstance(r.get("default_view_result"), dict) and r["default_view_result"].get("success") else 0
            total_views = new_count + default_ok
            log_summary(f"✓「{ws_name}」→ {total_views} 个视图已创建")
```

- [ ] **Step 2: 提交**

```bash
git add scripts/hap/pipeline/waves.py
git commit -m "feat: 视图创建完成后输出摘要（工作表名+视图数）"
```

---

### Task 6: 工作流创建摘要

**Files:**
- Modify: `workflow/scripts/execute_workflow_plan.py:1088,1104,1121,1157`

- [ ] **Step 1: 添加 import**

`execute_workflow_plan.py` 在 `workflow/scripts/` 目录，已有 `sys.path.insert(0, str(Path(__file__).parent))` 指向自身目录。需要额外添加 `scripts/hap/` 路径以导入 `utils.py`：

```python
# 在文件顶部已有的 sys.path.insert 之后（约第 33 行后），添加：
_HAP_DIR = str(Path(__file__).resolve().parents[2] / "scripts" / "hap")
if _HAP_DIR not in sys.path:
    sys.path.insert(0, _HAP_DIR)
from utils import log_summary
```

- [ ] **Step 2: 在每条工作流创建完成后输出摘要**

在 `execute_worksheet_plan()` 函数中，每个工作流（自定义动作/工作表事件/日期触发）创建完后，在 `results.append(r)` 之后添加摘要。

工作流有三种类型，分别在约第 1088、1104、1121 行。对每个位置，在 `results.append(r)` 之后添加：

```python
        # 自定义动作（约第 1088 行后）：
        if r.get("ok") and not r.get("skipped"):
            trigger_desc = "自定义动作"
            node_names = [str(n.get("name", "")).strip() for n in r.get("action_nodes", []) if isinstance(n, dict) and n.get("name")]
            node_count = len(r.get("action_nodes", []))
            log_summary(f"✓ 工作流「{name}」→ {ws_name} / {trigger_desc} / {node_count} 个节点")
            if node_names:
                log_summary(f"  {' | '.join(node_names)}")
```

```python
        # 工作表事件触发（约第 1104 行后）：
        if r.get("ok") and not r.get("skipped"):
            trigger_id = r.get("trigger_id", "")
            trigger_map = {"1": "新增记录时", "2": "编辑记录时", "3": "删除记录时"}
            trigger_desc = trigger_map.get(str(trigger_id), f"事件触发(id={trigger_id})")
            node_names = [str(n.get("name", "")).strip() for n in r.get("action_nodes", []) if isinstance(n, dict) and n.get("name")]
            node_count = len(r.get("action_nodes", []))
            log_summary(f"✓ 工作流「{ev_name}」→ {ws_name} / {trigger_desc} / {node_count} 个节点")
            if node_names:
                log_summary(f"  {' | '.join(node_names)}")
```

```python
        # 日期字段触发（约第 1121 行后）：
        if r.get("ok") and not r.get("skipped"):
            node_names = [str(n.get("name", "")).strip() for n in r.get("action_nodes", []) if isinstance(n, dict) and n.get("name")]
            node_count = len(r.get("action_nodes", []))
            log_summary(f"✓ 工作流「{dt_name}」→ {ws_name} / 按日期字段触发 / {node_count} 个节点")
            if node_names:
                log_summary(f"  {' | '.join(node_names)}")
```

同样，对全局时间触发（约第 1157 行后），在 `results.append(r)` 之后：

```python
        if r.get("ok") and not r.get("skipped"):
            node_names = [str(n.get("name", "")).strip() for n in r.get("action_nodes", []) if isinstance(n, dict) and n.get("name")]
            node_count = len(r.get("action_nodes", []))
            log_summary(f"✓ 工作流「{name}」→ 全局 / 定时触发 / {node_count} 个节点")
            if node_names:
                log_summary(f"  {' | '.join(node_names)}")
```

- [ ] **Step 3: 提交**

```bash
git add workflow/scripts/execute_workflow_plan.py
git commit -m "feat: 每条工作流创建后输出摘要（名称+触发方式+节点列表）"
```

---

### Task 7: Pages 和图表摘要

**Files:**
- Modify: `scripts/hap/executors/create_pages_early.py:369-375`
- Modify: `scripts/hap/executors/create_single_ws_charts.py:329-345`

- [ ] **Step 1: `create_pages_early.py` 添加 Page 创建摘要**

```python
# 文件顶部添加：
from utils import log_summary
```

在每个 Page 创建成功后（约第 375 行 `print(f"    ✓ pageId={page_id}")` 之后），添加：

```python
            log_summary(f"✓ Page「{page_name}」已创建")
```

注意：Pages 在此阶段是空的（图表后续创建），所以只输出 Page 名称。

- [ ] **Step 2: `create_single_ws_charts.py` 添加图表摘要**

```python
# 文件顶部添加：
from utils import log_summary
```

在 `plan_and_create_charts()` 函数中，图表创建并追加到页面成功后（约第 345 行 `print(f"  ✅ {worksheet_name}: ...")` 处），输出摘要：

```python
    # 在成功追加图表到页面后（约第 345 行），添加：
    chart_names = [str(c.get("chartName", "")).strip() for c in created_charts if isinstance(c, dict)]
    chart_names_str = "、".join(n for n in chart_names if n) or "无"
    log_summary(f"✓ Page「{page_name}」图表已创建（{len(created_charts)} 个：{chart_names_str}）")
```

需要确认 `page_name` 变量在该作用域内可用。从函数签名看，`page_entry` 被传入，`page_name` 可通过 `page_entry.get("name", "")` 获取。

- [ ] **Step 3: 提交**

```bash
git add scripts/hap/executors/create_pages_early.py scripts/hap/executors/create_single_ws_charts.py
git commit -m "feat: Page 创建和图表创建完成后输出摘要"
```

---

### Task 8: 角色创建摘要

**Files:**
- Modify: `scripts/hap/create_roles_from_recommendation.py:228-234`

- [ ] **Step 1: 添加 import 和摘要输出**

```python
# 文件顶部添加：
from utils import log_summary
```

在角色全部创建完后（约第 228 行 `write_json(output_path, result)` 之后，第 232 行 `print("角色创建执行完成")` 之前），添加：

```python
    created_names = [str(c.get("name", "")).strip() for c in created if isinstance(c, dict)]
    if created_names:
        log_summary(f"✓ 角色已创建：{'、'.join(created_names)}")
```

- [ ] **Step 2: 提交**

```bash
git add scripts/hap/create_roles_from_recommendation.py
git commit -m "feat: 角色创建完成后输出摘要（角色名列表）"
```

---

### Task 9: 造数摘要

**Files:**
- Modify: `scripts/hap/mock_data_common.py:1242-1246`

- [ ] **Step 1: 添加 per-worksheet 摘要**

```python
# 文件顶部添加：
from utils import log_summary
```

在 `summarize_write_result()` 函数中（约第 1242 行），或者在造数的核心写入逻辑中，每张表写入完成后输出摘要。

查看造数写入逻辑，实际写入在 `mock_data_common.py` 的某个函数中按工作表遍历。需要找到每张表写入完成的位置。

更实际的做法：在 `pipeline_mock_data.py` 中，造数完成后读取 write_result JSON，遍历输出每张表的摘要。在 `pipeline_mock_data.py` 约第 201 行（Step 3 写入造数完成后）：

```python
# pipeline_mock_data.py 中添加 import：
from utils import log_summary

# 约第 201 行，造数 step 完成后，读取 write_result 输出摘要：
        try:
            wr = load_json(Path(write_json_path))
            for ws_item in wr.get("worksheets", []):
                if isinstance(ws_item, dict):
                    ws_n = str(ws_item.get("worksheetName", "")).strip()
                    ok_c = int(ws_item.get("successCount", 0) or 0)
                    log_summary(f"✓「{ws_n}」已写入 {ok_c} 条记录")
        except Exception:
            pass
```

- [ ] **Step 2: 提交**

```bash
git add scripts/hap/pipeline_mock_data.py
git commit -m "feat: 造数完成后输出摘要（每张表的写入记录数）"
```

---

### Task 10: 机器人创建摘要

**Files:**
- Modify: `scripts/hap/executors/create_chatbots_from_plan.py:228-229`

- [ ] **Step 1: 添加 import 和摘要输出**

```python
# 文件顶部添加：
from utils import log_summary
```

在每个机器人创建成功后（约第 228 行 `ok_count += 1` 之后，`append_log(...)` 之后），添加：

```python
            log_summary(f"✓ 机器人「{proposal['name']}」已创建")
```

- [ ] **Step 2: 提交**

```bash
git add scripts/hap/executors/create_chatbots_from_plan.py
git commit -m "feat: 机器人创建后输出摘要"
```

---

### Task 11: 端到端验证

- [ ] **Step 1: 检查所有修改文件的 import 正确性**

运行每个修改过的文件的 import 检查，确保 `from utils import log_summary` 能正确解析：

```bash
cd /Users/andy/Documents/coding/hap-auto-maker
python3 -c "import sys; sys.path.insert(0, 'scripts/hap'); from utils import log_summary, SUMMARY_PREFIX; print('OK:', SUMMARY_PREFIX)"
```

- [ ] **Step 2: 检查 step_runner 的过滤逻辑**

创建一个简单的测试脚本验证 `[SUMMARY]` 行在子进程中能被正确捕获：

```bash
python3 -c "
from scripts.hap.pipeline.step_runner import run_cmd
result = run_cmd(['python3', '-c', 'print(\"[SUMMARY] test line\"); print(\"debug line\")'], dry_run=False, verbose=False)
print('stdout captured:', repr(result['stdout']))
assert '[SUMMARY] test line' in result['stdout']
print('OK')
"
```

- [ ] **Step 3: 最终提交**

```bash
git add -A
git commit -m "feat: pipeline 实时摘要日志系统完成"
```
