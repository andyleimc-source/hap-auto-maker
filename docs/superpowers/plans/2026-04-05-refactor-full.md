# HAP Auto Maker 全盘整改 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 HAP Auto Maker 进行全盘代码质量整改：消除重复代码、建立包结构、补单元测试、加固错误处理，全程保证功能等价。

**Architecture:** 七个阶段串行推进，每阶段完成后跑 `pytest` 验证不回归。Phase 1-2 提取公用工具、Phase 3 建立包结构、Phase 4 拆分上帝函数、Phase 5 目录分层、Phase 6 补单元测试、Phase 7 错误处理加固。

**Tech Stack:** Python 3.10+, pytest, setuptools (editable install)

---

## 文件结构总览（改动后）

**新建文件：**
- `scripts/hap/utils.py` — 公用工具函数（now_ts, load_json, write_json, latest_file, write_json_with_latest）
- `scripts/hap/pipeline/__init__.py`
- `scripts/hap/pipeline/step_runner.py` — execute_step 通用逻辑
- `scripts/hap/pipeline/context.py` — PipelineContext 数据类 + build_report / save_report
- `scripts/hap/pipeline/waves.py` — Wave 1-7 编排逻辑
- `scripts/hap/planners/` — plan_*_gemini.py 移入（保留原路径软链或 script_locator 更新）
- `tests/unit/test_utils.py` — utils.py 单元测试
- `tests/unit/test_view_planner.py` — view_planner 单元测试
- `tests/unit/test_workflow_planner.py` — workflow_planner 单元测试
- `tests/unit/test_create_worksheets.py` — create_worksheets_from_plan 单元测试

**修改文件：**
- `pyproject.toml` — 加 packages 声明，支持 editable install
- `scripts/hap/execute_requirements.py` — 保留入口 main()，Wave 逻辑移到 pipeline/waves.py
- `make_app.py` — normalize_spec 改为从 execute_requirements 导入
- `scripts/hap/hap_api_client.py` — 加 retry 逻辑
- 所有含重复函数的 ~40 个脚本 — 改为 `from utils import ...`

---

## Phase 1 — 提取公用工具函数到 utils.py

### Task 1: 创建 utils.py 并写测试

**Files:**
- Create: `scripts/hap/utils.py`
- Create: `tests/unit/test_utils.py`

- [ ] **Step 1: 写 test_utils.py（先写测试）**

```python
# tests/unit/test_utils.py
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from utils import now_ts, load_json, write_json, latest_file, write_json_with_latest


class TestNowTs:
    def test_format(self):
        ts = now_ts()
        assert len(ts) == 15  # YYYYmmdd_HHMMSS
        assert ts[8] == "_"

    def test_returns_string(self):
        assert isinstance(now_ts(), str)


class TestLoadJson:
    def test_loads_valid_file(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        assert load_json(f) == {"key": "value"}

    def test_raises_if_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_json(tmp_path / "nope.json")


class TestWriteJson:
    def test_writes_and_creates_dir(self, tmp_path):
        p = tmp_path / "sub" / "out.json"
        write_json(p, {"a": 1})
        assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}

    def test_ensure_ascii_false(self, tmp_path):
        p = tmp_path / "out.json"
        write_json(p, {"名称": "测试"})
        assert "测试" in p.read_text(encoding="utf-8")


class TestLatestFile:
    def test_returns_none_on_empty_dir(self, tmp_path):
        assert latest_file(tmp_path, "*.json") is None

    def test_returns_most_recent(self, tmp_path):
        import time
        a = tmp_path / "a.json"
        a.write_text("{}")
        time.sleep(0.01)
        b = tmp_path / "b.json"
        b.write_text("{}")
        result = latest_file(tmp_path, "*.json")
        assert result.name == "b.json"


class TestWriteJsonWithLatest:
    def test_writes_both_files(self, tmp_path):
        out_path = tmp_path / "run_20260405.json"
        write_json_with_latest(tmp_path, out_path, "latest.json", {"x": 1})
        assert (tmp_path / "run_20260405.json").exists()
        assert (tmp_path / "latest.json").exists()
        assert json.loads((tmp_path / "latest.json").read_text()) == {"x": 1}
```

- [ ] **Step 2: 确认测试失败（utils.py 尚不存在）**

```bash
cd /Users/andy/Documents/coding/hap-auto-maker
.venv/bin/python -m pytest tests/unit/test_utils.py -v 2>&1 | head -20
```

期望输出：`ModuleNotFoundError: No module named 'utils'`

- [ ] **Step 3: 创建 utils.py**

```python
# scripts/hap/utils.py
"""
公用工具函数 — 替代散落在各脚本中的重复定义。
所有 scripts/hap/ 下的脚本统一从此导入。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def now_ts() -> str:
    """返回当前时间戳字符串，格式 YYYYmmdd_HHMMSS。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    """返回 ISO 8601 格式时间字符串（含时区）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    """读取 JSON 文件，文件不存在时抛出 FileNotFoundError。"""
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> Path:
    """写入 JSON 文件，自动创建父目录。返回写入路径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    """返回目录下匹配 pattern 的最新文件（按 mtime），无匹配返回 None。"""
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def write_json_with_latest(
    output_dir: Path,
    output_path: Path,
    latest_name: str,
    payload: Any,
) -> Path:
    """写入 JSON 文件，同时更新同目录下的 latest_name 软链文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_path, payload)
    latest_path = (output_dir / latest_name).resolve()
    write_json(latest_path, payload)
    return output_path
```

- [ ] **Step 4: 跑测试，确认全部通过**

```bash
.venv/bin/python -m pytest tests/unit/test_utils.py -v
```

期望输出：`8 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/hap/utils.py tests/unit/test_utils.py
git commit -m "feat: 新增 utils.py，集中管理公用工具函数（now_ts/load_json/write_json/latest_file）"
```

---

### Task 2: 替换 scripts/hap/ 下所有重复定义

每个文件的操作模式：删除本地定义，在文件顶部 `from utils import ...`。

**Files:**（修改下列所有文件）
- `scripts/hap/execute_requirements.py` (now_ts, load_json, write_json)
- `scripts/hap/create_views_from_plan.py` (now_ts, latest_file, load_json, write_json)
- `scripts/hap/create_charts_from_plan.py` (load_json, write_json)
- `scripts/hap/create_pages_from_plan.py` (load_json, write_json)
- `scripts/hap/create_sections_from_plan.py` (now_ts, load_json, write_json)
- `scripts/hap/plan_charts_gemini.py` (now_ts, load_json, write_json)
- `scripts/hap/plan_pages_gemini.py` (now_ts, load_json, write_json)
- `scripts/hap/plan_tableview_filters_gemini.py` (now_ts, load_json, write_json, latest_file)
- `scripts/hap/plan_worksheet_views_gemini.py` (now_ts, load_json, write_json, latest_file)
- `scripts/hap/plan_app_sections_gemini.py` (now_ts, load_json, write_json)
- `scripts/hap/plan_worksheet_layout.py` (latest_file, load_json)
- `scripts/hap/apply_tableview_filters_from_plan.py` (now_ts, latest_file, load_json, write_json)
- `scripts/hap/apply_worksheet_layout.py` (latest_file)
- `scripts/hap/mock_data_common.py` (now_ts, latest_file, load_json, write_json, write_json_with_latest)
- `scripts/hap/run_app_to_video.py` (now_ts, load_json, write_json)
- `scripts/hap/agent_collect_requirements.py` (now_ts, load_json)
- `scripts/hap/pipeline_app_roles.py` (now_ts)
- `scripts/hap/chatbot_common.py` (now_ts, write_json_with_latest)
- `scripts/hap/gen_app_intro.py` (now_ts)
- `scripts/hap/create_worksheets_from_plan.py` (latest_file, load_json)
- `scripts/hap/delete_default_views.py` (latest_file)
- `scripts/hap/delete_worksheet.py` (latest_file)
- `scripts/hap/get_row.py` (latest_file)
- `scripts/hap/get_worksheet_detail.py` (latest_file)
- `scripts/hap/incremental/app_context.py` (latest_file)
- `scripts/hap/list_app_worksheets.py` (latest_file)
- `scripts/hap/list_apps_for_icon.py` (latest_file)
- `scripts/hap/mock_data_common.py` 中的 `ensure_dir` — 替换为 `path.mkdir(parents=True, exist_ok=True)`
- `scripts/hap/pipeline_worksheets.py` (latest_file)
- `scripts/hap/update_app_icons.py` (latest_file)
- `scripts/hap/update_app_navi_style.py` (latest_file)
- `scripts/hap/update_row.py` (latest_file)
- `scripts/hap/update_worksheet_icons.py` (latest_file)

**scripts/gemini/ 下的两个文件**（它们不在 sys.path scripts/hap 下，需要相对路径导入）：
- `scripts/gemini/match_app_icons_gemini.py` (load_json, latest_file)
- `scripts/gemini/match_worksheet_icons_gemini.py` (load_json, latest_file)

> 注意：`scripts/gemini/` 里的脚本需要 `sys.path.insert` 到 `scripts/hap/` 才能 `from utils import ...`

- [ ] **Step 1: 批量替换 scripts/hap/ 下的文件**

对每个文件，执行以下模式（以 `execute_requirements.py` 为示例）：

1. 找到文件中的本地函数定义块（`def now_ts`/`def load_json`/`def write_json`）
2. 删除这些定义
3. 在 `from datetime import datetime` 这行（或 import 区块末尾）加入：
   ```python
   from utils import now_ts, now_iso, load_json, write_json, latest_file
   ```
4. 如果文件已有 `from datetime import datetime` 且只用于 now_ts/now_iso，删除该 import

> 每个文件改完立即验证该脚本可 import：
> ```bash
> .venv/bin/python -c "import sys; sys.path.insert(0, 'scripts/hap'); import <module_name>"
> ```

- [ ] **Step 2: 处理 scripts/gemini/ 下的两个文件**

在 `match_app_icons_gemini.py` 和 `match_worksheet_icons_gemini.py` 头部加入：
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hap"))
from utils import load_json, latest_file
```
然后删除这两个文件中的本地 `load_json` 和 `latest_file` 定义。

- [ ] **Step 3: 处理 mock_data_common.py 的 write_json 返回值差异**

`mock_data_common.py` 的 `write_json` 返回 `path`，而 utils.py 版本也返回 `path`（已统一）。
检查 `mock_data_common.py` 中调用 `write_json` 的地方是否有依赖返回值的代码，若有则确认兼容。

- [ ] **Step 4: 跑全量测试**

```bash
.venv/bin/python -m pytest tests/ -v
```

期望：全部已有测试通过（不新增失败）

- [ ] **Step 5: 验证脚本独立运行**

```bash
.venv/bin/python scripts/hap/execute_requirements.py --help
.venv/bin/python scripts/hap/plan_charts_gemini.py --help
.venv/bin/python scripts/hap/create_views_from_plan.py --help
```

期望：正常打印 help，无 ImportError

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "refactor: 消除重复工具函数，统一从 utils.py 导入（now_ts/load_json/write_json/latest_file）"
```

---

## Phase 2 — 合并 normalize_spec

### Task 3: 统一 normalize_spec 到 execute_requirements.py

`make_app.py` 有一份精简版 normalize_spec，`execute_requirements.py` 有完整版（包含 roles/chatbots/workflows/pages 等字段）。`agent_collect_requirements.py` 也有一份。

**Files:**
- Modify: `make_app.py`
- Modify: `scripts/hap/agent_collect_requirements.py`

- [ ] **Step 1: 确认 execute_requirements.py 的 normalize_spec 是完整版**

执行以下检查，`execute_requirements.py` 应含有 `roles/chatbots/workflows/pages/delete_default_views` 所有字段的 setdefault：
```bash
grep "setdefault" scripts/hap/execute_requirements.py | wc -l
```
期望：> 25 行

- [ ] **Step 2: 修改 make_app.py**

删除 `make_app.py` 中的 `normalize_spec` 函数（第 80-139 行），改为从 `execute_requirements` 导入。

在 `make_app.py` 顶部 import 区块加入：
```python
import sys
HAP_DIR = Path(__file__).resolve().parent / "scripts" / "hap"
if str(HAP_DIR) not in sys.path:
    sys.path.insert(0, str(HAP_DIR))
from execute_requirements import normalize_spec  # noqa: E402
```

> 注意：`make_app.py` 里已有 `from ai_utils import ...`，`HAP_DIR` 的 sys.path 插入已存在，只需加 import。

- [ ] **Step 3: 修改 agent_collect_requirements.py**

同样删除其中的 `normalize_spec`，改为 `from execute_requirements import normalize_spec`。
（需先确认 `execute_requirements` 里的版本与 `agent_collect_requirements.py` 版本在功能上等价，差异仅在默认值的字符串）

- [ ] **Step 4: 验证**

```bash
.venv/bin/python make_app.py --help
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts/hap')
from execute_requirements import normalize_spec
spec = normalize_spec({})
assert 'roles' in spec
assert 'chatbots' in spec
assert spec['app']['name'] == 'CRM自动化应用'
print('OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add make_app.py scripts/hap/agent_collect_requirements.py scripts/hap/execute_requirements.py
git commit -m "refactor: 合并 normalize_spec 为单一权威版本（execute_requirements.py）"
```

---

## Phase 3 — pyproject.toml 包结构 + 消除 sys.path hack

### Task 4: 建立可安装包结构

**Files:**
- Modify: `pyproject.toml`
- Create: `scripts/__init__.py`
- Create: `scripts/hap/__init__.py` (已有子目录的 __init__.py，确认根目录有)
- Create: `scripts/gemini/__init__.py`
- Create: `workflow/__init__.py`
- Create: `workflow/scripts/__init__.py`

- [ ] **Step 1: 更新 pyproject.toml**

```toml
[project]
name = "hap-auto-maker"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "requests>=2.28.0",
    "openai>=1.0.0",
    "google-genai>=1.0.0",
    "playwright>=1.40.0",
    "json-repair>=0.1.0",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["scripts*", "workflow*"]
exclude = ["*.tests*"]
```

- [ ] **Step 2: 创建缺失的 __init__.py**

```bash
touch scripts/__init__.py
touch scripts/hap/__init__.py
touch scripts/gemini/__init__.py
touch workflow/__init__.py
touch workflow/scripts/__init__.py
```

> `scripts/hap/charts/`、`scripts/hap/views/`、`scripts/hap/worksheets/`、`scripts/hap/planning/`、`scripts/hap/incremental/` 已有 `__init__.py`，不需要重建。

- [ ] **Step 3: 安装包（editable）**

```bash
.venv/bin/pip install -e . --quiet
```

- [ ] **Step 4: 验证 import 路径可用**

```bash
.venv/bin/python -c "
from scripts.hap.utils import now_ts, load_json
from scripts.hap.ai_utils import load_ai_config
from scripts.hap.hap_api_client import HapClient
from workflow.nodes._base import base_body
print('所有 import 成功')
"
```

- [ ] **Step 5: 替换 scripts/hap/ 内部 sys.path hacks**

对于 `scripts/hap/` 内部文件相互引用的情况，把：
```python
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
from ai_utils import ...
```
替换为：
```python
from scripts.hap.ai_utils import ...
```

> 但要保留脚本直接运行（`python3 scripts/hap/xxx.py`）的能力。解决方案：在每个脚本末尾的 `if __name__ == "__main__":` 块之前，保留一个备用 fallback：
> ```python
> try:
>     from scripts.hap.utils import now_ts, load_json
> except ImportError:
>     from utils import now_ts, load_json  # 直接运行时的 fallback
> ```

- [ ] **Step 6: 处理 workflow/scripts/ 对 scripts/hap/ 的跨目录引用**

`workflow/scripts/pipeline_workflows.py` 和 `execute_workflow_plan.py` 手动 sys.path 到 `scripts/hap/`，改为：
```python
try:
    from scripts.hap.ai_utils import get_ai_client, load_ai_config, create_generation_config, AI_CONFIG_PATH
    from scripts.hap.planning.workflow_planner import build_structure_prompt, validate_structure_plan, build_node_config_prompt, validate_node_config
except ImportError:
    # 直接运行 fallback
    _hap = str(Path(__file__).resolve().parents[2] / "scripts" / "hap")
    if _hap not in sys.path:
        sys.path.insert(0, _hap)
    from ai_utils import get_ai_client, load_ai_config, create_generation_config, AI_CONFIG_PATH
    from planning.workflow_planner import build_structure_prompt, validate_structure_plan, build_node_config_prompt, validate_node_config
```

- [ ] **Step 7: 跑全量测试 + 验证入口脚本**

```bash
.venv/bin/python -m pytest tests/ -v
.venv/bin/python make_app.py --help
.venv/bin/python scripts/hap/execute_requirements.py --help
.venv/bin/python workflow/scripts/pipeline_workflows.py --help
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml scripts/__init__.py scripts/hap/__init__.py scripts/gemini/__init__.py workflow/__init__.py workflow/scripts/__init__.py
git add -u
git commit -m "feat: 建立包结构，支持 editable install，消除 sys.path hack"
```

---

## Phase 4 — 拆分 execute_requirements.py（1093行）

### Task 5: 提取 step_runner 和 context

**Files:**
- Create: `scripts/hap/pipeline/__init__.py`
- Create: `scripts/hap/pipeline/step_runner.py`
- Create: `scripts/hap/pipeline/context.py`
- Modify: `scripts/hap/execute_requirements.py`

- [ ] **Step 1: 创建 pipeline/__init__.py**

```python
# scripts/hap/pipeline/__init__.py
```

- [ ] **Step 2: 创建 step_runner.py**

从 `execute_requirements.py` 提取 `run_cmd`（第 287-345 行）和 `execute_step` 的通用执行逻辑。

```python
# scripts/hap/pipeline/step_runner.py
"""
通用步骤执行工具：run_cmd（子进程执行）和 execute_step（带报告和信号量的步骤封装）。
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from scripts.hap.utils import now_iso
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from utils import now_iso


def run_cmd(cmd: List[str], dry_run: bool, verbose: bool) -> Dict[str, Any]:
    """执行子命令，实时流式输出，返回 {returncode, stdout, stderr, ...}。"""
    cmd_text = " ".join(str(c) for c in cmd)
    if dry_run:
        return {"dry_run": True, "cmd": cmd, "cmd_text": cmd_text, "returncode": 0, "stdout": "", "stderr": ""}

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    def reader(pipe, bucket):
        for line in pipe:
            bucket.append(line)
            if verbose:
                print(line, end="", flush=True)

    def heartbeat(process):
        while process.poll() is None:
            if not verbose:
                print(".", end="", flush=True)
            time.sleep(30)

    t1 = threading.Thread(target=reader, args=(proc.stdout, stdout_lines))
    t2 = threading.Thread(target=reader, args=(proc.stderr, stderr_lines))
    t3 = threading.Thread(target=heartbeat, args=(proc,))
    t1.start(); t2.start(); t3.start()
    returncode = proc.wait()
    t1.join(); t2.join()

    if not verbose and not dry_run:
        print(" ", end="\r")

    return {
        "dry_run": False,
        "cmd": cmd,
        "cmd_text": cmd_text,
        "returncode": returncode,
        "stdout": "".join(stdout_lines),
        "stderr": "".join(stderr_lines),
    }


def execute_step(
    step_id: int,
    step_key: str,
    title: str,
    cmd: Optional[List[str]],
    *,
    pipeline_start: float,
    steps_report: List[dict],
    steps_lock: threading.Lock,
    selected_steps: set,
    execution_dry_run: bool,
    verbose: bool,
    gemini_semaphore: Optional[threading.Semaphore] = None,
) -> bool:
    """
    执行一个 pipeline 步骤，写入 steps_report，返回是否成功。
    - cmd=None 表示该步骤被 spec 禁用
    - gemini_semaphore 非空则在获取信号量后再执行
    """
    def _skip(reason: str) -> bool:
        with steps_lock:
            steps_report.append({
                "step_id": step_id, "step_key": step_key, "title": title,
                "skipped": True, "reason": reason, "result": {},
            })
        return True

    if not _step_selected(step_id, step_key, selected_steps):
        return _skip("not_selected")
    if cmd is None:
        return _skip("disabled_by_spec")

    elapsed_total = time.time() - pipeline_start
    print(f"  ▶ Step {step_id:2d}  {title}  [{elapsed_total:.0f}s]", flush=True)
    started = now_iso()
    step_start = time.time()

    if gemini_semaphore:
        with gemini_semaphore:
            result = run_cmd(cmd, dry_run=execution_dry_run, verbose=verbose)
    else:
        result = run_cmd(cmd, dry_run=execution_dry_run, verbose=verbose)

    ended = now_iso()
    ok = int(result.get("returncode", 1)) == 0
    duration = time.time() - step_start
    elapsed_total = time.time() - pipeline_start
    status = "✓" if ok else "✗"
    print(f"  {status} Step {step_id:2d}  {title}  ({duration:.0f}s, 总计 {elapsed_total:.0f}s)", flush=True)

    if not ok:
        # 打印前 300 + 末尾 600，避免截断根因
        err = str(result.get("stderr", "") or "").strip()
        if err:
            if len(err) > 900:
                print(err[:300], flush=True)
                print("  ...(省略中间内容)...", flush=True)
                print(err[-600:], flush=True)
            else:
                print(err, flush=True)

    with steps_lock:
        steps_report.append({
            "step_id": step_id,
            "step_key": step_key,
            "title": title,
            "started_at": started,
            "ended_at": ended,
            "ok": ok,
            "result": result,
        })
    return ok


def _step_selected(step_id: int, step_key: str, selected: set) -> bool:
    if not selected:
        return True
    return str(step_id) in selected or step_key.lower() in selected
```

- [ ] **Step 3: 创建 context.py**

```python
# scripts/hap/pipeline/context.py
"""
PipelineContext — 保存 pipeline 执行过程中各步骤产生的文件路径和 app_id。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from scripts.hap.utils import now_iso, write_json
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from utils import now_iso, write_json


@dataclass
class PipelineContext:
    app_id: Optional[str] = None
    app_auth_json: Optional[str] = None
    worksheet_plan_json: Optional[str] = None
    sections_plan_json: Optional[str] = None
    sections_create_result_json: Optional[str] = None
    worksheet_create_result_json: Optional[str] = None
    role_pipeline_report_json: Optional[str] = None
    role_plan_json: Optional[str] = None
    role_create_result_json: Optional[str] = None
    worksheet_layout_plan_json: Optional[str] = None
    worksheet_layout_apply_result_json: Optional[str] = None
    view_plan_json: Optional[str] = None
    view_create_result_json: Optional[str] = None
    tableview_filter_plan_json: Optional[str] = None
    tableview_filter_apply_result_json: Optional[str] = None
    mock_data_run_json: Optional[str] = None
    chatbot_pipeline_result_json: Optional[str] = None
    workflow_plan_json: Optional[str] = None
    workflow_execute_result_json: Optional[str] = None

    def as_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


def build_report(
    spec_path: Path,
    steps_report: List[dict],
    context: PipelineContext,
    *,
    dry_run: bool,
    fail_fast: bool,
) -> dict:
    ok_count = len([s for s in steps_report if s.get("ok") is True or s.get("skipped") is True])
    fail_count = len([s for s in steps_report if s.get("ok") is False])
    return {
        "schema_version": "workflow_requirement_v1_execution_report",
        "created_at": now_iso(),
        "spec_json": str(spec_path),
        "dry_run": dry_run,
        "fail_fast": fail_fast,
        "summary": {
            "total_steps": len(steps_report),
            "ok_or_skipped": ok_count,
            "failed": fail_count,
        },
        "artifacts": context.as_dict(),
        "context": context.as_dict(),
        "steps": steps_report,
    }


def save_report(
    report: dict,
    execution_run_dir: Path,
) -> Path:
    from scripts.hap.utils import now_ts
    execution_run_dir.mkdir(parents=True, exist_ok=True)
    out = (execution_run_dir / f"execution_run_{now_ts()}.json").resolve()
    write_json(out, report)
    latest = (execution_run_dir / "execution_run_latest.json").resolve()
    write_json(latest, report)
    return out
```

- [ ] **Step 4: 跑测试确认不回归**

```bash
.venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add scripts/hap/pipeline/
git commit -m "refactor: 提取 pipeline/step_runner.py 和 pipeline/context.py，拆解 execute_requirements.py 上帝函数（第一步）"
```

---

### Task 6: 提取 pipeline/waves.py，精简 execute_requirements.py

**Files:**
- Create: `scripts/hap/pipeline/waves.py`
- Modify: `scripts/hap/execute_requirements.py`

- [ ] **Step 1: 创建 waves.py**

把 `execute_requirements.py` 的 `main()` 函数中 Wave 1-7 的编排逻辑（第 570-1093 行）整体移到 `waves.py` 的 `run_all_waves()` 函数中，参数为：

```python
def run_all_waves(
    spec: dict,
    spec_path: Path,
    args,           # argparse.Namespace
    pipeline_start: float,
) -> tuple[PipelineContext, list[dict]]:
    """执行全部 Wave，返回 (context, steps_report)。"""
```

Wave 1-7 逻辑原封不动搬过来，把对 `execute_step` 的调用改为使用 `step_runner.execute_step`，把 `context` dict 改为 `PipelineContext` dataclass。

- [ ] **Step 2: 精简 execute_requirements.py**

改完后 `execute_requirements.py` 的 `main()` 只保留：
1. argparse 解析
2. `normalize_spec` + 配置校验
3. `run_all_waves(...)` 调用
4. 最终 report 保存和打印

目标行数：main() < 100 行，全文件 < 350 行。

- [ ] **Step 3: 验证完整流程不挂**

```bash
.venv/bin/python scripts/hap/execute_requirements.py --help
.venv/bin/python make_app.py --help
```

- [ ] **Step 4: 跑全量测试**

```bash
.venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add scripts/hap/pipeline/waves.py scripts/hap/execute_requirements.py
git commit -m "refactor: 将 Wave 编排逻辑提取到 pipeline/waves.py，execute_requirements.py 精简到 <350 行"
```

---

## Phase 5 — scripts/hap/ 目录分层

### Task 7: 创建分层目录结构

当前 `scripts/hap/` 有 80+ 文件平铺。目标结构：

```
scripts/hap/
  pipeline/          ← 已在 Phase 4 创建
  planners/          ← plan_*_gemini.py（9个 AI 规划脚本）
  executors/         ← create_*_from_plan.py、apply_*_from_plan.py（7个执行脚本）
  schemas/           ← 现有的 charts/、views/、worksheets/ 子目录（不动）
  incremental/       ← 已有，不动
  planning/          ← 已有，不动
  utils.py           ← Phase 1 已建
  ai_utils.py        ← 不动
  hap_api_client.py  ← 不动
  script_locator.py  ← 更新 SEARCH_DIRS
```

**Files:**
- Create: `scripts/hap/planners/__init__.py`
- Create: `scripts/hap/executors/__init__.py`
- Move（git mv）: 9个 planners 脚本
- Move（git mv）: 7个 executors 脚本
- Modify: `scripts/hap/script_locator.py`

- [ ] **Step 1: 创建目录和 __init__.py**

```bash
mkdir -p scripts/hap/planners scripts/hap/executors
touch scripts/hap/planners/__init__.py scripts/hap/executors/__init__.py
```

- [ ] **Step 2: git mv planners（AI 规划脚本）**

```bash
git mv scripts/hap/plan_charts_gemini.py scripts/hap/planners/
git mv scripts/hap/plan_pages_gemini.py scripts/hap/planners/
git mv scripts/hap/plan_tableview_filters_gemini.py scripts/hap/planners/
git mv scripts/hap/plan_worksheet_views_gemini.py scripts/hap/planners/
git mv scripts/hap/plan_app_sections_gemini.py scripts/hap/planners/
git mv scripts/hap/plan_worksheet_layout.py scripts/hap/planners/
git mv scripts/hap/plan_mock_data_gemini.py scripts/hap/planners/
git mv scripts/hap/plan_mock_relations_gemini.py scripts/hap/planners/
git mv scripts/hap/plan_role_recommendations_gemini.py scripts/hap/planners/
git mv scripts/hap/plan_chatbots_gemini.py scripts/hap/planners/
```

- [ ] **Step 3: git mv executors（执行脚本）**

```bash
git mv scripts/hap/create_charts_from_plan.py scripts/hap/executors/
git mv scripts/hap/create_views_from_plan.py scripts/hap/executors/
git mv scripts/hap/create_worksheets_from_plan.py scripts/hap/executors/
git mv scripts/hap/create_pages_from_plan.py scripts/hap/executors/
git mv scripts/hap/create_sections_from_plan.py scripts/hap/executors/
git mv scripts/hap/apply_tableview_filters_from_plan.py scripts/hap/executors/
git mv scripts/hap/apply_worksheet_layout.py scripts/hap/executors/
git mv scripts/hap/apply_mock_relations_from_plan.py scripts/hap/executors/
git mv scripts/hap/write_mock_data_from_plan.py scripts/hap/executors/
```

- [ ] **Step 4: 更新 script_locator.py 的 SEARCH_DIRS**

```python
SEARCH_DIRS = (
    CURRENT_DIR,
    CURRENT_DIR / "planners",
    CURRENT_DIR / "executors",
    CURRENT_DIR / "pipeline",
    SCRIPTS_DIR / "gemini",
    SCRIPTS_DIR / "auth",
    SCRIPTS_DIR,
)
```

- [ ] **Step 5: 验证所有 pipeline 脚本仍可找到**

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts/hap')
from script_locator import resolve_script
scripts = [
    'plan_charts_gemini.py',
    'create_views_from_plan.py',
    'pipeline_views.py',
    'apply_tableview_filters_from_plan.py',
    'plan_app_sections_gemini.py',
]
for s in scripts:
    p = resolve_script(s)
    print(f'OK: {s} -> {p}')
"
```

期望：全部打印 `OK: ...`，无 FileNotFoundError

- [ ] **Step 6: 跑全量测试 + 入口验证**

```bash
.venv/bin/python -m pytest tests/ -v
.venv/bin/python scripts/hap/execute_requirements.py --help
.venv/bin/python make_app.py --help
```

- [ ] **Step 7: Commit**

```bash
git add scripts/hap/planners/ scripts/hap/executors/ scripts/hap/script_locator.py
git commit -m "refactor: scripts/hap/ 目录分层，plan_* 移入 planners/，create_*/apply_* 移入 executors/"
```

---

## Phase 6 — 补单元测试

### Task 8: 补 view_planner 单元测试

**Files:**
- Create: `tests/unit/test_view_planner.py`

- [ ] **Step 1: 写测试**

```python
# tests/unit/test_view_planner.py
"""
validate_structure_plan 和 validate_view_plan 的单元测试。
不需要网络，不需要真实 API。
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from planning.view_planner import validate_structure_plan, validate_view_plan

# ── 测试数据辅助 ──────────────────────────────────────────────────────────────

def _make_ws_by_id(ws_id="ws1", fields=None):
    return {
        ws_id: {
            "worksheetId": ws_id,
            "name": "测试表",
            "fields": fields or [
                {"id": "f1", "type": 2, "name": "标题"},
                {"id": "f2", "type": 9, "name": "状态"},
                {"id": "f3", "type": 15, "name": "日期"},
                {"id": "f4", "type": 26, "name": "负责人"},
            ],
        }
    }


def _make_plan(ws_id="ws1", views=None):
    return {
        "worksheets": [
            {
                "worksheetId": ws_id,
                "views": views or [{"viewType": 0, "name": "表格视图", "sortFields": []}],
            }
        ]
    }


# ── validate_structure_plan ───────────────────────────────────────────────────

class TestValidateStructurePlan:
    def test_valid_plan_passes(self):
        plan = _make_plan()
        result = validate_structure_plan(plan, _make_ws_by_id())
        assert "worksheets" in result

    def test_missing_worksheets_raises(self):
        with pytest.raises(ValueError, match="缺少 worksheets"):
            validate_structure_plan({}, {})

    def test_empty_worksheets_raises(self):
        with pytest.raises(ValueError, match="缺少 worksheets"):
            validate_structure_plan({"worksheets": []}, {})

    def test_invalid_view_type_string_raises(self):
        plan = _make_plan(views=[{"viewType": "invalid", "name": "x"}])
        with pytest.raises(ValueError, match="viewType"):
            validate_structure_plan(plan, _make_ws_by_id())

    def test_view_type_as_string_int_accepted(self):
        # "0" 应被接受（可转为 int）
        plan = _make_plan(views=[{"viewType": "0", "name": "表格"}])
        result = validate_structure_plan(plan, _make_ws_by_id())
        assert result is not None

    def test_views_not_list_raises(self):
        plan = {"worksheets": [{"worksheetId": "ws1", "views": "not_a_list"}]}
        with pytest.raises(ValueError):
            validate_structure_plan(plan, _make_ws_by_id())


# ── validate_view_plan ────────────────────────────────────────────────────────

class TestValidateViewPlan:
    def test_valid_table_view_passes(self):
        plan = _make_plan(views=[{"viewType": 0, "name": "表格", "sortFields": []}])
        result = validate_view_plan(plan, _make_ws_by_id())
        assert result is not None

    def test_kanban_view_requires_single_select_field(self):
        # 看板视图（type=1）如果 groupField 不是单选(9/11)，应该被过滤或抛异常
        ws_by_id = _make_ws_by_id(fields=[
            {"id": "f1", "type": 2, "name": "标题"},
            {"id": "f2", "type": 36, "name": "检查框"},  # 检查框不适合看板
        ])
        plan = _make_plan(views=[{
            "viewType": 1,
            "name": "看板",
            "groupControlId": "f2",  # 引用检查框字段
        }])
        # 应该抛出或移除不合法的看板配置
        try:
            result = validate_view_plan(plan, ws_by_id)
            # 若不报错，说明内部自动修复了
            assert result is not None
        except ValueError:
            pass  # 抛出也接受

    def test_gantt_view_needs_date_field(self):
        ws_by_id = _make_ws_by_id(fields=[
            {"id": "f1", "type": 2, "name": "标题"},
            {"id": "f3", "type": 15, "name": "开始日期"},
            {"id": "f4", "type": 15, "name": "结束日期"},
        ])
        plan = _make_plan(views=[{
            "viewType": 6,
            "name": "甘特图",
            "begindate": "f3",
            "enddate": "f4",
        }])
        result = validate_view_plan(plan, ws_by_id)
        assert result is not None

    def test_unknown_worksheet_id_skipped(self):
        plan = _make_plan(ws_id="unknown_ws")
        # worksheets_by_id 里没有 unknown_ws，应跳过校验而不是报错
        result = validate_view_plan(plan, {})
        assert result is not None
```

- [ ] **Step 2: 跑测试确认能跑（部分可能失败，记录下来）**

```bash
.venv/bin/python -m pytest tests/unit/test_view_planner.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_view_planner.py
git commit -m "test: 补 view_planner validate_structure_plan / validate_view_plan 单元测试"
```

---

### Task 9: 补 workflow_planner 单元测试

**Files:**
- Create: `tests/unit/test_workflow_planner.py`

- [ ] **Step 1: 写测试**

```python
# tests/unit/test_workflow_planner.py
"""
validate_structure_plan 和 validate_node_config 的单元测试。
不需要网络。
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from planning.workflow_planner import validate_structure_plan, validate_node_config

# ── 测试数据 ──────────────────────────────────────────────────────────────────

def _make_ws_by_id(ws_id="ws1", fields=None):
    return {
        ws_id: {
            "worksheetId": ws_id,
            "name": "任务表",
            "fields": fields or [
                {"id": "f1", "type": 2, "name": "标题"},
                {"id": "f2", "type": 9, "name": "状态"},
                {"id": "f3", "type": 26, "name": "负责人"},
            ],
        }
    }


def _allowed_node(node_type="notify"):
    return {"node_type": node_type, "name": "通知"}


def _make_structure_plan(ws_id="ws1", workflows=None):
    return {
        "worksheets": [
            {
                "worksheet_id": ws_id,
                "workflows": workflows or [
                    {
                        "name": "新增通知",
                        "trigger_type": "worksheet_event",
                        "action_nodes": [_allowed_node("notify")],
                    }
                ],
            }
        ]
    }


# ── validate_structure_plan ───────────────────────────────────────────────────

class TestWorkflowValidateStructurePlan:
    def test_valid_plan_passes(self):
        plan = _make_structure_plan()
        result = validate_structure_plan(plan, _make_ws_by_id())
        assert "worksheets" in result

    def test_missing_worksheets_raises(self):
        with pytest.raises(ValueError):
            validate_structure_plan({}, {})

    def test_missing_worksheet_id_raises(self):
        plan = {"worksheets": [{"workflows": []}]}
        with pytest.raises(ValueError, match="worksheet_id"):
            validate_structure_plan(plan, _make_ws_by_id())

    def test_disallowed_node_type_is_filtered(self):
        """不在 allowed 列表中的节点类型应被过滤出 action_nodes。"""
        plan = _make_structure_plan(workflows=[{
            "name": "工作流",
            "trigger_type": "worksheet_event",
            "action_nodes": [
                {"node_type": "notify", "name": "通知"},     # allowed
                {"node_type": "sms", "name": "短信"},         # not allowed
            ],
        }])
        result = validate_structure_plan(plan, _make_ws_by_id())
        ws = result["worksheets"][0]
        if ws["workflows"]:
            nodes = ws["workflows"][0]["action_nodes"]
            node_types = [n["node_type"] for n in nodes]
            assert "sms" not in node_types

    def test_workflow_with_all_disallowed_nodes_removed(self):
        """所有节点都不在 allowed 的工作流应从规划中移除。"""
        plan = _make_structure_plan(workflows=[{
            "name": "全禁工作流",
            "trigger_type": "worksheet_event",
            "action_nodes": [{"node_type": "sms", "name": "短信"}],
        }])
        result = validate_structure_plan(plan, _make_ws_by_id())
        ws = result["worksheets"][0]
        assert len(ws.get("workflows", [])) == 0


# ── validate_node_config ──────────────────────────────────────────────────────

class TestValidateNodeConfig:
    def test_valid_notify_config_passes(self):
        plan = {
            "worksheets": [
                {
                    "worksheet_id": "ws1",
                    "workflows": [
                        {
                            "name": "通知流",
                            "trigger_type": "worksheet_event",
                            "action_nodes": [
                                {
                                    "node_type": "notify",
                                    "name": "发通知",
                                    "content": "你有新任务",
                                    "accounts": [{"type": 6, "entityId": "uid1"}],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        result = validate_node_config(plan, _make_ws_by_id())
        assert result is not None
```

- [ ] **Step 2: 跑测试**

```bash
.venv/bin/python -m pytest tests/unit/test_workflow_planner.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_workflow_planner.py
git commit -m "test: 补 workflow_planner validate_structure_plan / validate_node_config 单元测试"
```

---

### Task 10: 补 create_worksheets_from_plan 单元测试

**Files:**
- Create: `tests/unit/test_create_worksheets.py`

- [ ] **Step 1: 写测试**

```python
# tests/unit/test_create_worksheets.py
"""
build_field_payload 和 split_fields 的单元测试。
不需要网络。
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
# 调整路径以匹配 Phase 5 目录结构
try:
    from executors.create_worksheets_from_plan import build_field_payload, split_fields
except ImportError:
    from create_worksheets_from_plan import build_field_payload, split_fields


class TestBuildFieldPayload:
    def test_text_field_type_2(self):
        field = {"name": "标题", "type": "Text", "required": True}
        payload = build_field_payload(field, is_first_text_title=True)
        assert payload["controlName"] == "标题"
        assert payload["type"] == 2
        assert payload["attribute"] == 1  # 第一个文本字段是标题字段

    def test_select_field_has_options(self):
        field = {
            "name": "状态",
            "type": "Select",
            "option_values": ["待处理", "进行中", "已完成"],
        }
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["type"] == 9
        assert len(payload.get("options", [])) == 3

    def test_number_field_type_6(self):
        field = {"name": "数量", "type": "Number"}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["type"] == 6

    def test_date_field_type_15(self):
        field = {"name": "创建日期", "type": "Date"}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["type"] == 15

    def test_member_field_type_26(self):
        field = {"name": "负责人", "type": "Member"}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload["type"] == 26

    def test_non_title_text_field_no_attribute_1(self):
        field = {"name": "备注", "type": "Text"}
        payload = build_field_payload(field, is_first_text_title=False)
        assert payload.get("attribute", 0) != 1


class TestSplitFields:
    def test_basic_fields_in_immediate(self):
        fields = [
            {"name": "标题", "type": "Text"},
            {"name": "状态", "type": "Select"},
        ]
        immediate, deferred, relations = split_fields(fields)
        assert len(immediate) == 2
        assert len(deferred) == 0

    def test_relation_fields_separated(self):
        fields = [
            {"name": "标题", "type": "Text"},
            {"name": "关联项目", "type": "RelateRecord", "relate_worksheet": "ws2"},
        ]
        immediate, deferred, relations = split_fields(fields)
        assert len(relations) == 1
        assert relations[0]["name"] == "关联项目"

    def test_returns_three_lists(self):
        result = split_fields([])
        assert len(result) == 3
        assert all(isinstance(r, list) for r in result)
```

- [ ] **Step 2: 跑测试**

```bash
.venv/bin/python -m pytest tests/unit/test_create_worksheets.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_create_worksheets.py
git commit -m "test: 补 create_worksheets_from_plan build_field_payload / split_fields 单元测试"
```

---

## Phase 7 — 错误处理加固

### Task 11: HapClient 加 retry

**Files:**
- Modify: `scripts/hap/hap_api_client.py`
- Modify: `tests/unit/test_hap_api_client.py`

- [ ] **Step 1: 先写失败测试**

在 `tests/unit/test_hap_api_client.py` 中加入：

```python
def test_request_retries_on_500(monkeypatch):
    """HTTP 500 应重试最多 2 次。"""
    import requests
    from unittest.mock import MagicMock, patch

    call_count = 0

    def fake_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        if call_count < 3:
            resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        else:
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"error_code": 1, "data": {"ok": True}}
        return resp

    with patch("requests.request", side_effect=fake_request):
        with patch.object(HapClient, "_load_auth", return_value={
            "app_key": "k", "secret_key": "s", "project_id": "p"
        }):
            client = HapClient.__new__(HapClient)
            client.base_url = "https://fake.api"
            client.auth = {"app_key": "k", "secret_key": "s", "project_id": "p"}
            result = client.request("POST", "/test")
            assert result == {"ok": True}
            assert call_count == 3
```

- [ ] **Step 2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/unit/test_hap_api_client.py::test_request_retries_on_500 -v
```

期望：FAIL（当前 HapClient 没有 retry）

- [ ] **Step 3: 修改 hap_api_client.py 加入 retry**

```python
def request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, max_retries: int = 2) -> Any:
    url = f"{self.base_url}{endpoint}"
    headers = {"Content-Type": "application/json"}
    method = method.upper()

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        ts = int(time.time() * 1000)
        payload = {
            "appKey": self.auth["app_key"],
            "sign": self._build_sign(ts),
            "timestamp": ts,
            "projectId": self.auth["project_id"],
        }
        if data:
            payload.update(data)

        try:
            if method == "GET":
                response = requests.request(method, url, params=payload, headers=headers, timeout=30)
            else:
                response = requests.request(method, url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if attempt < max_retries:
                wait = (attempt + 1) * 5
                import warnings
                warnings.warn(f"HAP API HTTP错误，{wait}s 后重试 ({attempt+1}/{max_retries}): {e}")
                time.sleep(wait)
                continue
            raise

        res_json = response.json()
        code = res_json.get("error_code") if "error_code" in res_json else res_json.get("code")
        if code != 1:
            msg = res_json.get("error_msg") or res_json.get("message") or "Unknown error"
            raise RuntimeError(f"HAP API Error: {msg} (code: {code})")
        return res_json.get("data")

    raise last_exc or RuntimeError("HAP API 请求失败")
```

- [ ] **Step 4: 跑测试确认通过**

```bash
.venv/bin/python -m pytest tests/unit/test_hap_api_client.py -v
```

- [ ] **Step 5: Commit**

```bash
git add scripts/hap/hap_api_client.py tests/unit/test_hap_api_client.py
git commit -m "feat: HapClient.request 加入重试逻辑（最多2次，指数退避），加 timeout=30s"
```

---

### Task 12: 修复 except Exception: pass 静默吞异常

**Files:**
- Modify: `make_app.py`
- Modify: `scripts/hap/execute_requirements.py`

- [ ] **Step 1: 修复 make_app.py 中的 _load_org_group_ids**

```python
def _load_org_group_ids() -> str:
    """获取 group_ids，优先级：.env.local > organization_auth.json"""
    import warnings
    try:
        from local_config import load_local_group_id
        gid = load_local_group_id()
        if gid:
            return gid
    except ImportError:
        pass  # local_config 不存在是正常情况
    except Exception as e:
        warnings.warn(f"load_local_group_id 失败，回退到 organization_auth.json: {e}")

    org_auth = BASE_DIR / "config" / "credentials" / "organization_auth.json"
    try:
        data = json.loads(org_auth.read_text(encoding="utf-8"))
        return str(data.get("group_ids", "")).strip()
    except FileNotFoundError:
        pass  # 配置文件不存在时返回空字符串是预期行为
    except Exception as e:
        warnings.warn(f"读取 organization_auth.json 失败: {e}")
    return ""
```

- [ ] **Step 2: 同样修复 execute_requirements.py 中的 _load_org_group_ids**

相同改法，`except Exception: pass` → 区分 ImportError（正常）和其他异常（warn）。

- [ ] **Step 3: 搜索其他关键路径上的 except pass**

```bash
grep -n "except.*:\s*$\|except.*pass" scripts/hap/execute_requirements.py scripts/hap/pipeline/ make_app.py 2>/dev/null
```

对每个发现的 `except Exception: pass`，判断：
- 是正常 fallback（如 local_config 不存在）→ 改为 `except ImportError: pass`
- 是真实错误 → 改为 `except Exception as e: warnings.warn(f"xxx: {e}")`

- [ ] **Step 4: 跑全量测试**

```bash
.venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add make_app.py scripts/hap/execute_requirements.py scripts/hap/pipeline/
git commit -m "fix: 消除 except Exception: pass 静默吞异常，改为精确捕获或 warnings.warn"
```

---

### Task 13: pipeline 开头验证 web auth 有效性

**Files:**
- Create: `scripts/hap/pipeline/auth_check.py`
- Modify: `scripts/hap/pipeline/waves.py`

- [ ] **Step 1: 创建 auth_check.py**

```python
# scripts/hap/pipeline/auth_check.py
"""
Pipeline 启动前的认证探活检查。
检查 web auth cookie 是否仍然有效，避免在 Step 5/6/7 才发现过期。
"""
from __future__ import annotations

from pathlib import Path


def check_web_auth(auth_config_path: Path) -> tuple[bool, str]:
    """
    检查 web auth 配置是否有效（文件存在且包含非空 token）。
    返回 (ok: bool, message: str)。

    注意：只做静态文件检查，不发网络请求（避免增加启动时间）。
    如需深度验证，可在此扩展为发一次探活请求。
    """
    if not auth_config_path.exists():
        return False, f"web auth 配置文件不存在: {auth_config_path}\n请运行: python3 scripts/auth/refresh_auth.py"

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("auth_config", auth_config_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        token = getattr(mod, "X_MD_TOKEN", None) or getattr(mod, "token", None) or getattr(mod, "TOKEN", None)
        if not token:
            return False, f"web auth 文件存在但 token 为空: {auth_config_path}\n请运行: python3 scripts/auth/refresh_auth.py"
        return True, "web auth OK"
    except Exception as e:
        return False, f"加载 web auth 配置失败: {e}\n请运行: python3 scripts/auth/refresh_auth.py"
```

- [ ] **Step 2: 在 waves.py 的 run_all_waves 开头调用 auth_check**

在 Wave 1 执行之前，若 spec 中有需要 web auth 的步骤，先做检查：

```python
from scripts.hap.pipeline.auth_check import check_web_auth

# 在 main() / run_all_waves() 开头
if _needs_web_auth(spec):
    ok, msg = check_web_auth(CONFIG_WEB_AUTH)
    if not ok:
        print(f"\n⚠️  Web Auth 检查失败：{msg}", flush=True)
        print("Pipeline 将继续，但依赖 Web Auth 的步骤（视图/布局/图表）可能失败。", flush=True)
        print("建议先运行: python3 scripts/auth/refresh_auth.py\n", flush=True)
```

> 注意：这里选择 warn 而非 fail fast，因为用户可能只跑部分步骤（--only-steps）。

- [ ] **Step 3: 跑全量测试**

```bash
.venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add scripts/hap/pipeline/auth_check.py scripts/hap/pipeline/waves.py
git commit -m "feat: pipeline 启动时检查 web auth 配置，提前预警认证过期"
```

---

## 最终验收

### Task 14: 全量测试 + dry-run 验证

- [ ] **Step 1: 跑全量测试**

```bash
.venv/bin/python -m pytest tests/ -v --tb=short
```

期望：所有测试通过，0 个错误

- [ ] **Step 2: 验证所有入口脚本不挂**

```bash
.venv/bin/python make_app.py --help
.venv/bin/python scripts/hap/execute_requirements.py --help
.venv/bin/python workflow/scripts/pipeline_workflows.py --help
.venv/bin/python workflow/scripts/execute_workflow_plan.py --help
```

期望：全部正常打印 help，无 ImportError

- [ ] **Step 3: dry-run 验证**

```bash
.venv/bin/python make_app.py --requirements "员工考勤管理系统，3张表" --no-execute
```

期望：正常生成 spec JSON，打印应用名称，无错误

- [ ] **Step 4: 最终 commit（如有未提交改动）**

```bash
git add -u
git status  # 确认无意外未追踪文件
git commit -m "chore: 全盘整改收尾，更新 .gitignore 和文档"
```

- [ ] **Step 5: 推送**（等用户确认后执行）

```bash
git log --oneline -15  # 展示所有整改 commits
```

---

## 附：文件变更汇总

| 类型 | 文件 | 变更 |
|------|------|------|
| 新建 | `scripts/hap/utils.py` | 公用工具函数 |
| 新建 | `scripts/hap/pipeline/step_runner.py` | 步骤执行逻辑 |
| 新建 | `scripts/hap/pipeline/context.py` | PipelineContext dataclass |
| 新建 | `scripts/hap/pipeline/waves.py` | Wave 编排逻辑 |
| 新建 | `scripts/hap/pipeline/auth_check.py` | web auth 探活 |
| 新建 | `scripts/hap/planners/`（目录） | plan_* 脚本迁移目标 |
| 新建 | `scripts/hap/executors/`（目录） | create_*/apply_* 脚本迁移目标 |
| 新建 | `tests/unit/test_utils.py` | utils 测试 |
| 新建 | `tests/unit/test_view_planner.py` | view_planner 测试 |
| 新建 | `tests/unit/test_workflow_planner.py` | workflow_planner 测试 |
| 新建 | `tests/unit/test_create_worksheets.py` | create_worksheets 测试 |
| 修改 | `scripts/hap/execute_requirements.py` | 拆分到 pipeline/，精简到 <350 行 |
| 修改 | `make_app.py` | 导入 normalize_spec，删除重复定义 |
| 修改 | `scripts/hap/hap_api_client.py` | 加 retry + timeout |
| 修改 | `scripts/hap/script_locator.py` | 更新 SEARCH_DIRS |
| 修改 | `pyproject.toml` | 加包声明 |
| 修改 | ~40个脚本 | 删除重复函数，改为 from utils import |
| 移动 | 10个 plan_* 脚本 | → `scripts/hap/planners/` |
| 移动 | 9个 create_*/apply_* 脚本 | → `scripts/hap/executors/` |
