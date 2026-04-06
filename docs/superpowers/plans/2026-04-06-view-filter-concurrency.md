# 视图筛选并发优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将视图筛选环节（Step 7）从串行单次 AI 调用（~251s）改为 per-worksheet 并发 AI 调用，预计降至 20-40s。

**Architecture:** 新建 `pipeline_tableview_filters_v2.py`，合并规划+应用两步为一个脚本，每张表在独立线程内串行执行 fetch_views → fetch_controls → AI规划 → SaveWorksheetView，用 ThreadPoolExecutor + 全局 gemini_semaphore 并发控制。删除旧三个脚本，更新 context.py / waves.py / execute_requirements.py / run_app_to_video.py。

**Tech Stack:** Python 3.11+, `concurrent.futures.ThreadPoolExecutor`, `threading.Semaphore`, Gemini 2.5 Flash, `auth_retry.hap_web_post`

---

## 文件结构

| 文件 | 动作 | 说明 |
|------|------|------|
| `scripts/hap/pipeline_tableview_filters_v2.py` | 新建 | 并发主脚本 |
| `scripts/hap/pipeline/context.py` | 修改 | 移除两个旧字段，新增 tableview_filter_result_json |
| `scripts/hap/pipeline/waves.py` | 修改 | run_step_7 使用新脚本，传参调整，读取新 artifact |
| `scripts/hap/execute_requirements.py` | 修改 | _dirs() 新增 tableview_filter_result_dir，移除两个旧 dir |
| `scripts/hap/run_app_to_video.py` | 修改 | artifact 字段名更新 |
| `scripts/hap/pipeline_tableview_filters.py` | 删除 | 旧两步入口 |
| `scripts/hap/planners/plan_tableview_filters_gemini.py` | 删除 | 旧批量 AI 规划 |
| `scripts/hap/executors/apply_tableview_filters_from_plan.py` | 删除 | 旧 plan→apply |

---

### Task 1: 新建并发主脚本 pipeline_tableview_filters_v2.py

**Files:**
- Create: `scripts/hap/pipeline_tableview_filters_v2.py`

这是核心任务。脚本结构参照 `scripts/hap/pipeline_worksheet_layout_v2.py`，但处理视图筛选。
关键函数：fetch_app_structure, fetch_app_auth, fetch_worksheet_views, find_default_all_view,
fetch_controls, simplify_field, build_prompt, extract_json, generate_with_retry,
pick_best_dropdown_field, normalize_view_plan, to_adv_str_dict, save_view, process_worksheet, main

- [ ] **Step 1: 创建脚本文件（内容见下方）**

写入 `scripts/hap/pipeline_tableview_filters_v2.py`，参照规范：

文件头和常量：
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图筛选流水线 v2：按工作表并发执行 fetch_views -> fetch_controls -> AI规划 -> SaveWorksheetView。
每张表独立线程，受全局 gemini_semaphore 限流（通过 --semaphore-value 传入，默认 1000）。
Gemini 2.5 Flash 付费第一层级：RPD=10K，RPM=1000，TPM=1M。
"""

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parent
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import auth_retry
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config
from utils import now_ts, latest_file

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
RESULT_DIR = OUTPUT_ROOT / "tableview_filter_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
WORKSHEET_INFO_URL = "https://api.mingdao.com/v3/app/worksheets/{worksheet_id}"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"

SUPPORTED_VIEW_TYPES = {"0", "1", "3", "4"}
NAV_SUPPORTED_VIEW_TYPES = {"0", "3"}
FAST_SUPPORTED_VIEW_TYPES = {"0", "1", "3"}
VIEW_TYPE_LABELS = {"0": "表格视图", "1": "看板视图", "3": "画廊视图", "4": "日历视图"}
```

fetch_app_structure（与 layout_v2 相同）：
```python
def fetch_app_structure(app_key: str, sign: str) -> Tuple[str, List[dict]]:
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json"}
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app_data = data.get("data", {})
    app_name = str(app_data.get("name", "")).strip()
    worksheets: List[dict] = []
    def walk(section: dict):
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append({"workSheetId": str(item.get("id", "")), "workSheetName": str(item.get("name", ""))})
        for child in section.get("childSections", []) or []:
            walk(child)
    for sec in app_data.get("sections", []) or []:
        walk(sec)
    return app_name, worksheets
```

fetch_app_auth（从 APP_AUTH_DIR 按 appId 读取）：
```python
def fetch_app_auth(app_id: str) -> Tuple[str, str]:
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for row in (data.get("data") or []):
            if isinstance(row, dict) and str(row.get("appId", "")).strip() == app_id:
                return str(row.get("appKey", "")).strip(), str(row.get("sign", "")).strip()
    raise FileNotFoundError(f"未找到 appId={app_id} 的授权信息（目录: {APP_AUTH_DIR}）")
```

fetch_worksheet_views + find_default_all_view：
```python
def fetch_worksheet_views(worksheet_id: str, app_key: str, sign: str) -> List[dict]:
    url = WORKSHEET_INFO_URL.format(worksheet_id=worksheet_id)
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        return []
    views = data.get("data", {}).get("views") or []
    return views if isinstance(views, list) else []

def find_default_all_view(views: List[dict]) -> Optional[dict]:
    for v in views:
        if not isinstance(v, dict):
            continue
        vtype = v.get("viewType") if v.get("viewType") is not None else v.get("type")
        if isinstance(vtype, str):
            try:
                vtype = int(vtype)
            except ValueError:
                continue
        if vtype == 0 and str(v.get("name", "")).strip() == "全部":
            view_id = str(v.get("viewId") or v.get("id") or "").strip()
            if view_id:
                return {"viewId": view_id, "viewName": "全部", "viewType": "0"}
    return None
```

fetch_controls + simplify_field（与旧 plan 脚本相同）：
```python
def fetch_controls(worksheet_id: str, auth_config_path: Path) -> List[dict]:
    resp = auth_retry.hap_web_post(
        GET_CONTROLS_URL, auth_config_path,
        referer=f"https://www.mingdao.com/worksheet/field/edit?sourceId={worksheet_id}",
        json={"worksheetId": worksheet_id}, timeout=30,
    )
    data = resp.json()
    wrapped = data.get("data", {})
    if isinstance(wrapped, dict) and isinstance(wrapped.get("data"), dict):
        if int(wrapped.get("code", 0) or 0) != 1:
            raise RuntimeError(f"获取工作表控件失败: {worksheet_id}")
        payload = wrapped["data"]
    else:
        payload = data.get("data", {})
        if not isinstance(payload, dict):
            raise RuntimeError(f"工作表控件格式错误: {worksheet_id}")
    controls = payload.get("controls", [])
    return controls if isinstance(controls, list) else []

def simplify_field(field: dict) -> dict:
    ftype = field.get("type")
    subtype = field.get("subType")
    options = field.get("options")
    field_id = str(field.get("id", "") or field.get("controlId", "")).strip()
    field_name = str(field.get("name", "") or field.get("controlName", "")).strip()
    is_system = bool(field.get("isSystemControl", False))
    if not is_system:
        try:
            is_system = int(field.get("attribute", 0) or 0) == 1
        except Exception:
            is_system = False
    is_dropdown = False
    if isinstance(ftype, str):
        is_dropdown = ftype in ("SingleSelect", "MultipleSelect")
    elif isinstance(ftype, int):
        is_dropdown = ftype in (9, 10, 11)
    if isinstance(subtype, int) and subtype in (10, 11):
        is_dropdown = True
    return {
        "id": field_id, "name": field_name, "type": ftype, "subType": subtype,
        "isTitle": bool(field.get("isTitle", False)), "required": bool(field.get("required", False)),
        "isSystem": is_system, "optionCount": len(options) if isinstance(options, list) else 0,
        "isDropdown": is_dropdown,
    }
```

build_prompt（per-worksheet，与旧 build_prompt 函数相同，从旧 plan 脚本第 318-380 行复制）：
```python
def build_prompt(app_name: str, worksheet_name: str, worksheet_id: str,
                 target_views: List[dict], fields: List[dict]) -> str:
    # 与旧 plan_tableview_filters_gemini.py 中 build_prompt 函数完全相同
    # 包含完整的规则 1-11，prompt 结构不变
    ...  # （按旧脚本第 319-380 行实现）
```

extract_json + generate_with_retry（标准模式）：
```python
def extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("AI 返回为空")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"AI 未返回可解析 JSON:\n{text[:500]}")

def generate_with_retry(client, model: str, prompt: str, ai_config: dict, retries: int = 4) -> str:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=create_generation_config(ai_config, response_mime_type="application/json", temperature=0.2),
            )
            return resp.text or ""
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            wait = min(8, 2 ** (attempt - 1))
            print(f"  AI 调用失败（第{attempt}次），{wait}s 后重试：{exc}")
            time.sleep(wait)
    raise last_exc
```

pick_best_dropdown_field + normalize_view_plan（从旧脚本 472-676 行完整复制，改 `id` 字段访问）：
```python
def pick_best_dropdown_field(fields: List[dict]) -> str:
    # 从旧脚本 planners/plan_tableview_filters_gemini.py 第 472-504 行复制
    ...

def normalize_view_plan(item, field_map, fields, views_by_id) -> Optional[dict]:
    # 从旧脚本第 507-676 行复制，逻辑不变
    ...
```

to_adv_str_dict + save_view：
```python
def to_adv_str_dict(value: dict) -> dict:
    # 从旧 apply 脚本 executors/apply_tableview_filters_from_plan.py 第 50-63 行复制
    ...

def save_view(app_id: str, worksheet_id: str, view_id: str, plan: dict,
              auth_config_path: Path, dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "view_id": view_id}
    payload: dict = {"viewId": view_id}
    # 按 plan 内容填充 navGroup, fastFilters, advancedSetting, colorControlId, groupControlId
    # 参照旧 apply 脚本的 save_view_from_plan 逻辑
    referer = f"https://www.mingdao.com/app/{app_id}/{worksheet_id}/{view_id}"
    resp = auth_retry.hap_web_post(SAVE_VIEW_URL, auth_config_path, referer=referer, json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}
```

process_worksheet（核心 worker，每张表的完整流程）：
```python
def process_worksheet(ws, app_id, app_name, app_key, sign, view_create_targets,
                      semaphore, client, model, ai_config, auth_config_path, dry_run) -> dict:
    ws_id = ws["workSheetId"]
    ws_name = ws["workSheetName"]
    result = {"workSheetId": ws_id, "workSheetName": ws_name, "viewCount": 0, "savedCount": 0, "ok": False, "error": None}
    try:
        # 1. 获取视图列表，注入默认"全部"视图
        raw_views = fetch_worksheet_views(ws_id, app_key, sign)
        default_view = find_default_all_view(raw_views)
        existing_ids = {t["viewId"] for t in view_create_targets}
        targets = list(view_create_targets)
        if default_view and default_view["viewId"] not in existing_ids:
            targets.insert(0, default_view)
        if not targets:
            result["ok"] = True
            result["error"] = "no_target_views"
            return result
        # 2. 获取字段
        raw_controls = fetch_controls(ws_id, auth_config_path)
        fields = [simplify_field(f) for f in raw_controls if isinstance(f, dict)]
        field_map = {str(f.get("id", "")).strip(): f for f in fields if str(f.get("id", "")).strip()}
        views_by_id = {str(v.get("viewId", "")).strip(): v for v in targets}
        # 3. AI 规划（受 semaphore 限流）
        prompt = build_prompt(app_name, ws_name, ws_id, targets, fields)
        with semaphore:
            raw_text = generate_with_retry(client, model, prompt, ai_config)
        parsed = extract_json(raw_text)
        view_plans_raw = parsed.get("viewPlans", [])
        # 4. 归一化
        view_plans = []
        for item in view_plans_raw:
            norm = normalize_view_plan(item, field_map, fields, views_by_id)
            if norm:
                view_plans.append(norm)
        covered_ids = {p["viewId"] for p in view_plans}
        for vid, v in views_by_id.items():
            if vid not in covered_ids:
                view_plans.append({
                    "viewId": vid, "viewName": v.get("viewName", ""), "viewType": v.get("viewType", ""),
                    "needNavGroup": False, "navGroup": [], "navAdvancedSetting": {}, "navEditAdKeys": [],
                    "needFastFilters": False, "fastFilters": [], "fastAdvancedSetting": {"enablebtn": "0"},
                    "fastEditAdKeys": ["enablebtn"], "needColor": False, "colorControlId": "",
                    "needGroup": False, "groupControlId": "", "reason": "AI未返回，默认不配置",
                })
        result["viewCount"] = len(view_plans)
        # 5. 保存视图（内层并发）
        needs_save = [p for p in view_plans if p.get("needNavGroup") or p.get("needFastFilters") or p.get("needColor") or p.get("needGroup")]
        saved = 0
        if needs_save and not dry_run:
            with ThreadPoolExecutor(max_workers=min(8, len(needs_save))) as inner:
                futs = {inner.submit(save_view, app_id, ws_id, p["viewId"], p, auth_config_path, dry_run): p for p in needs_save}
                for fut in as_completed(futs):
                    try:
                        fut.result()
                        saved += 1
                    except Exception as e:
                        print(f"    ⚠ SaveWorksheetView 失败 ({futs[fut]['viewId']}): {e}")
        elif dry_run:
            saved = len(needs_save)
        result["savedCount"] = saved
        result["ok"] = True
        print(f"  ✓ {ws_name}：{len(view_plans)} 个视图，保存 {saved} 个", flush=True)
    except Exception as exc:
        result["error"] = str(exc)
        print(f"  ✗ {ws_name}：{exc}", flush=True)
    return result
```

main（入口，解析参数、读取授权、并发分发、写结果）：
```python
def main() -> None:
    parser = argparse.ArgumentParser(description="视图筛选流水线 v2（per-worksheet 并发）")
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--semaphore-value", type=int, default=1000)
    parser.add_argument("--view-create-result", default="")
    parser.add_argument("--app-auth-json", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    semaphore = threading.Semaphore(args.semaphore_value)
    ai_config = load_ai_config(AI_CONFIG_PATH)
    client = get_ai_client(ai_config)
    model = ai_config["model"]

    # 读授权（优先 --app-auth-json，否则从 APP_AUTH_DIR 读）
    if args.app_auth_json.strip():
        auth_data = json.loads(Path(args.app_auth_json).read_text(encoding="utf-8"))
        row = next((r for r in (auth_data.get("data") or []) if str(r.get("appId","")).strip() == args.app_id), None)
        if not row:
            raise ValueError(f"--app-auth-json 中未找到 appId={args.app_id}")
        app_key, sign = str(row.get("appKey","")).strip(), str(row.get("sign","")).strip()
    else:
        app_key, sign = fetch_app_auth(args.app_id)

    app_name, worksheets = fetch_app_structure(app_key, sign)
    print(f"应用：{app_name}，工作表数：{len(worksheets)}", flush=True)

    # 读视图创建结果（尝试 --view-create-result，失败则自动找最新）
    view_create_targets_by_ws: Dict[str, List[dict]] = {}
    vcr_str = args.view_create_result.strip()
    vcr_path = None
    if vcr_str:
        p = Path(vcr_str).expanduser().resolve()
        if p.exists():
            vcr_path = p
    if not vcr_path:
        vcr_path = latest_file(OUTPUT_ROOT / "view_create_results", "view_create_result_*.json")
    if vcr_path:
        try:
            vcr_data = json.loads(vcr_path.read_text(encoding="utf-8"))
            for app_item in (vcr_data.get("apps") or []):
                if str(app_item.get("appId","")).strip() != args.app_id:
                    continue
                for ws_item in (app_item.get("worksheets") or []):
                    ws_id = str(ws_item.get("worksheetId","")).strip()
                    targets = []
                    for view in (ws_item.get("views") or []):
                        view_id = str(view.get("createdViewId","")).strip()
                        view_type = str(view.get("viewType","")).strip()
                        if not view_id or view_type not in SUPPORTED_VIEW_TYPES:
                            continue
                        view_name = str(view.get("name","")).strip()
                        if not view_name and isinstance(view.get("createPayload"), dict):
                            view_name = str(view["createPayload"].get("name","")).strip()
                        targets.append({"viewId": view_id, "viewName": view_name, "viewType": view_type})
                    if targets:
                        view_create_targets_by_ws[ws_id] = targets
        except Exception as e:
            print(f"⚠ 读取视图创建结果失败，仅处理默认视图：{e}", flush=True)

    t0 = time.time()
    ws_results = []
    max_workers = min(args.semaphore_value, len(worksheets)) if worksheets else 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {
            pool.submit(process_worksheet, ws, args.app_id, app_name, app_key, sign,
                        view_create_targets_by_ws.get(ws["workSheetId"], []),
                        semaphore, client, model, ai_config, AUTH_CONFIG_PATH, args.dry_run): ws
            for ws in worksheets
        }
        for fut in as_completed(futs):
            try:
                ws_results.append(fut.result())
            except Exception as e:
                ws = futs[fut]
                ws_results.append({"workSheetId": ws["workSheetId"], "workSheetName": ws["workSheetName"],
                                   "viewCount": 0, "savedCount": 0, "ok": False, "error": str(e)})

    elapsed = time.time() - t0
    total_views = sum(r["viewCount"] for r in ws_results)
    total_saved = sum(r["savedCount"] for r in ws_results)
    failed = [r for r in ws_results if not r["ok"] and r.get("error") != "no_target_views"]

    payload = {
        "app": {"appId": args.app_id, "appName": app_name},
        "worksheetCount": len(worksheets), "totalViews": total_views,
        "totalSaved": total_saved, "elapsedSeconds": round(elapsed, 1),
        "dryRun": args.dry_run, "worksheets": ws_results,
    }
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = now_ts()
    out_path = (RESULT_DIR / f"tableview_filter_result_{args.app_id}_{ts}.json").resolve()
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULT_DIR / "tableview_filter_result_latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n视图筛选完成  工作表={len(worksheets)}  视图={total_views}  保存={total_saved}  耗时={elapsed:.0f}s", flush=True)
    if failed:
        print(f"⚠ 失败 {len(failed)} 张表：{[r['workSheetName'] for r in failed]}", flush=True)
        sys.exit(1)
    print(f"结果：{out_path}", flush=True)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证脚本语法正确**

```bash
python3 -c "import ast; ast.parse(open('scripts/hap/pipeline_tableview_filters_v2.py').read()); print('syntax OK')"
```

期望输出：`syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/pipeline_tableview_filters_v2.py
git commit -m "feat: 新建 pipeline_tableview_filters_v2.py（per-worksheet 并发 AI 调用）"
```

---

### Task 2: 更新 context.py

**Files:**
- Modify: `scripts/hap/pipeline/context.py`

- [ ] **Step 1: 修改 context.py**

将第 44-45 行：
```python
    tableview_filter_plan_json: Optional[str] = None
    tableview_filter_apply_result_json: Optional[str] = None
```
替换为：
```python
    tableview_filter_result_json: Optional[str] = None
```

将第 74-75 行：
```python
            "tableview_filter_plan_json": self.tableview_filter_plan_json,
            "tableview_filter_apply_result_json": self.tableview_filter_apply_result_json,
```
替换为：
```python
            "tableview_filter_result_json": self.tableview_filter_result_json,
```

- [ ] **Step 2: 验证语法**

```bash
python3 -c "import sys; sys.path.insert(0, 'scripts/hap'); from pipeline.context import PipelineContext; print('OK')"
```

期望输出：`OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/pipeline/context.py
git commit -m "refactor: context.py 视图筛选字段更新为 tableview_filter_result_json"
```

---

### Task 3: 更新 waves.py

**Files:**
- Modify: `scripts/hap/pipeline/waves.py`

- [ ] **Step 1: 修改 waves.py**

**改动 1**：删除约第 637-638 行的两个 dir 变量读取：
```python
# 删除这两行
    tableview_filter_plan_dir: Path = dirs["tableview_filter_plan_dir"]
    tableview_filter_apply_result_dir: Path = dirs["tableview_filter_apply_result_dir"]
```

**改动 2**：删除 Wave 5 顶部约第 765-770 行的两个路径变量：
```python
# 删除这些行
    filter_plan_output = (
        tableview_filter_plan_dir / f"tableview_filter_plan_{app_id}_{now_ts()}.json"
    ).resolve()
    filter_apply_output = (
        tableview_filter_apply_result_dir / f"tableview_filter_apply_result_{app_id}_{now_ts()}.json"
    ).resolve()
```

**改动 3**：将 `run_step_7` 函数体（约第 772-792 行）替换为：
```python
    def run_step_7() -> bool:
        if not view_filters.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 7, "step_key": "view_filters", "title": "规划并应用视图筛选", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        sem_value = getattr(gemini_semaphore, '_value', 1000)
        cmd7 = [
            sys.executable, str(scripts["view_filters"]),
            "--app-id", app_id,
            "--semaphore-value", str(sem_value),
            "--app-auth-json", str(app_auth_json),
        ]
        if ctx.view_create_result_json and Path(ctx.view_create_result_json).exists():
            cmd7.extend(["--view-create-result", ctx.view_create_result_json])
        if execution_dry_run:
            cmd7.append("--dry-run")
        ok7 = _exec(7, "view_filters", "规划并应用视图筛选", cmd7, uses_gemini=True)
        if ok7:
            latest = output_root / "tableview_filter_results" / "tableview_filter_result_latest.json"
            if latest.exists():
                ctx.tableview_filter_result_json = str(latest)
        return ok7
```

- [ ] **Step 2: 验证语法**

```bash
python3 -c "import sys; sys.path.insert(0, 'scripts/hap'); from pipeline import waves; print('OK')"
```

期望输出：`OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/pipeline/waves.py
git commit -m "refactor: waves.py 视图筛选步骤改用 v2 脚本，移除旧参数"
```

---

### Task 4: 更新 execute_requirements.py

**Files:**
- Modify: `scripts/hap/execute_requirements.py`

- [ ] **Step 1: 修改 execute_requirements.py**

**改动 1**：`_scripts()` 中将：
```python
        "view_filters":        resolve_script("pipeline_tableview_filters.py"),
```
改为：
```python
        "view_filters":        resolve_script("pipeline_tableview_filters_v2.py"),
```

**改动 2**：`_dirs()` 中将：
```python
        "tableview_filter_plan_dir":      OUTPUT_ROOT / "tableview_filter_plans",
        "tableview_filter_apply_result_dir": OUTPUT_ROOT / "tableview_filter_apply_results",
```
替换为：
```python
        "tableview_filter_result_dir":    OUTPUT_ROOT / "tableview_filter_results",
```

- [ ] **Step 2: 验证语法**

```bash
python3 -c "import sys; sys.path.insert(0,'scripts/hap'); import execute_requirements; print('OK')"
```

期望输出：`OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/execute_requirements.py
git commit -m "refactor: execute_requirements 视图筛选脚本和目录更新为 v2"
```

---

### Task 5: 更新 run_app_to_video.py

**Files:**
- Modify: `scripts/hap/run_app_to_video.py`

- [ ] **Step 1: 修改 run_app_to_video.py**

将约第 105-106 行：
```python
        "tableview_filter_plan_json",
        "tableview_filter_apply_result_json",
```
替换为：
```python
        "tableview_filter_result_json",
```

- [ ] **Step 2: 验证语法**

```bash
python3 -c "import ast; ast.parse(open('scripts/hap/run_app_to_video.py').read()); print('syntax OK')"
```

期望输出：`syntax OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/run_app_to_video.py
git commit -m "refactor: run_app_to_video artifact 字段更新"
```

---

### Task 6: 删除旧脚本

**Files:**
- Delete: `scripts/hap/pipeline_tableview_filters.py`
- Delete: `scripts/hap/planners/plan_tableview_filters_gemini.py`
- Delete: `scripts/hap/executors/apply_tableview_filters_from_plan.py`

- [ ] **Step 1: 删除旧脚本**

```bash
git rm scripts/hap/pipeline_tableview_filters.py
git rm scripts/hap/planners/plan_tableview_filters_gemini.py
git rm scripts/hap/executors/apply_tableview_filters_from_plan.py
```

- [ ] **Step 2: 确认无残留引用**

```bash
grep -r "pipeline_tableview_filters\b\|plan_tableview_filters_gemini\|apply_tableview_filters_from_plan" \
  scripts/ tests/ --include="*.py" | grep -v "_v2"
```

期望：无输出

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: 删除视图筛选旧脚本（plan/apply 分离版）"
```

---

### Task 7: 运行测试验证

- [ ] **Step 1: 运行全量测试**

```bash
python3 -m pytest tests/ -v 2>&1 | tail -30
```

期望：138 tests pass，5 tests fail（`test_mock_data_inline.py::TestComputeNewRecordCount` 为已知 pre-existing，不计入本次范围）

- [ ] **Step 2: 验证新脚本可启动（语法+导入）**

```bash
python3 -c "
import sys
sys.path.insert(0, 'scripts/hap')
import pipeline_tableview_filters_v2
print('import OK')
print('RESULT_DIR:', pipeline_tableview_filters_v2.RESULT_DIR)
"
```

期望：
```
import OK
RESULT_DIR: /path/to/hap-auto-maker/data/outputs/tableview_filter_results
```

- [ ] **Step 3: Commit 修复（如有）**

若测试发现问题，修复后：
```bash
git add -p
git commit -m "fix: 修复视图筛选 v2 测试发现的问题"
```
