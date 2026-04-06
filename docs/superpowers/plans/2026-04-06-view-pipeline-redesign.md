# 视图创建流程重新设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 视图创建从"批量规划+批量创建+删除默认视图"改为"单表即时触发+改造默认视图"，每次 AI 调用只为一张表规划视图。

**Architecture:** 新增 `plan_and_create_views_for_ws()` 函数，将 AI 规划 + 默认视图改造 + 新视图创建 + 视图筛选合并为单表原子操作。在 Wave 3 工作表创建完成后，立即提交视图任务到线程池，与其他表并行执行。

**Tech Stack:** Python 3, Gemini Flash API, HAP Web API (SaveWorksheetView), threading.Semaphore

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `scripts/hap/planning/view_planner.py` | 修改 | 新增 `build_single_ws_view_prompt()` — 单表视图规划 prompt（含默认视图改造） |
| `scripts/hap/planners/plan_worksheet_views_gemini.py` | 修改 | 新增 `plan_and_create_views_for_ws()` — 单表规划+创建原子操作 |
| `scripts/hap/pipeline/waves.py` | 修改 | Wave 3 后触发视图任务；移除 Wave 7 删除默认视图 |
| `scripts/hap/executors/create_views_from_plan.py` | 修改 | 新增 `update_default_view()` — 改造默认视图 |

---

### Task 1: 新增单表视图规划 prompt

**Files:**
- Modify: `scripts/hap/planning/view_planner.py`

- [ ] **Step 1: 在 view_planner.py 末尾新增 `build_single_ws_view_prompt()` 函数**

在 `validate_config_plan` 函数之后添加：

```python
# ─── 单表视图规划（一次 AI 调用，含默认视图改造）─────────────────────────


def build_single_ws_view_prompt(
    app_name: str,
    ws_name: str,
    ws_id: str,
    fields: list[dict],
    default_view_id: str,
) -> str:
    """为单张工作表生成视图规划 prompt，含默认视图改造方案。

    Args:
        app_name: 应用名称
        ws_name: 工作表名称
        ws_id: 真实 worksheetId
        fields: 该表的字段列表（simplify_field 格式）
        default_view_id: 系统默认"全部"视图的 viewId
    """
    import json as _json

    view_type_section = build_view_type_prompt_section()
    classified = classify_fields(fields)
    suggestions = suggest_views(classified, ws_id)

    # 字段摘要
    field_lines = []
    for f in fields:
        if bool(f.get("isSystem", False)):
            continue
        opts_str = ""
        if f.get("options"):
            opts_str = " 选项: " + ", ".join(o.get("value", "") for o in f["options"][:6])
        field_lines.append(f"  {f['id']}  type={f['type']}  {f['name']}{opts_str}")
    field_section = "\n".join(field_lines)

    # 推荐视图
    suggestion_lines = []
    for sg in suggestions:
        suggestion_lines.append(
            f"  - viewType={sg['viewType']} {sg['name']}（{sg.get('reason', '')}）"
        )
    suggestion_text = "推荐视图：\n" + "\n".join(suggestion_lines) if suggestion_lines else ""

    return f"""你是明道云视图配置专家。请为工作表「{ws_name}」规划视图。

应用名：{app_name}
工作表：{ws_name}（ID: {ws_id}）

## 字段列表
{field_section}

{view_type_section}

{suggestion_text}

## 任务

1. **改造默认视图**：系统已有一个名为"全部"的默认表格视图（viewId: {default_view_id}），请将它改造成有业务含义的视图——改名并加配置（如分组、显示字段等）
2. **规划新视图**：额外规划 1-3 个有业务价值的视图（看板/日历/甘特图/画廊等）

## 输出格式（严格 JSON）

{{
  "default_view_update": {{
    "name": "改造后的视图名（如'按状态分组'）",
    "viewType": 0,
    "displayControls": ["字段ID1", "字段ID2", ...],
    "advancedSetting": {{
      "groupsetting": "[...]"
    }},
    "postCreateUpdates": []
  }},
  "new_views": [
    {{
      "name": "视图名",
      "viewType": 1,
      "displayControls": ["字段ID1", ...],
      "viewControl": "看板分组字段ID",
      "coverCid": "",
      "advancedSetting": {{}},
      "postCreateUpdates": [...]
    }}
  ]
}}

## 规则

1) 默认视图改造必须有实际业务含义——至少改名 + 设 displayControls，如有单选字段(type=9/11)则加 groupsetting 分组
2) displayControls 选 5-8 个最重要的字段 ID
3) 看板(viewType=1)：必须有单选字段(type=9/11)作为 viewControl
4) 日历(viewType=4)：postCreateUpdates 中设 calendarcids
5) 甘特图(viewType=5)：需要开始+结束两个日期字段
6) 层级(viewType=2)：需要自关联字段(type=29)
7) 画廊(viewType=3)：有附件字段(type=14)时推荐，设 coverCid
8) 所有 advancedSetting 中的 JSON 字符串值必须是紧凑格式（无空格）
9) 不要创建与默认视图改造后功能重复的视图"""


def validate_single_ws_view_plan(
    plan: dict,
    field_ids: set[str],
) -> list[str]:
    """校验单表视图规划输出。"""
    errors = []

    # 校验 default_view_update
    dv = plan.get("default_view_update")
    if not isinstance(dv, dict):
        errors.append("缺少 default_view_update")
    else:
        name = str(dv.get("name", "")).strip()
        if not name or name == "全部":
            errors.append("default_view_update.name 未改造（仍为'全部'或为空）")
        dc = dv.get("displayControls", [])
        if isinstance(dc, list):
            for cid in dc:
                if str(cid).strip() and str(cid).strip() not in field_ids:
                    errors.append(f"default_view_update.displayControls 引用了不存在的字段: {cid}")

    # 校验 new_views
    new_views = plan.get("new_views", [])
    if not isinstance(new_views, list):
        errors.append("new_views 不是数组")
    else:
        for i, v in enumerate(new_views):
            if not isinstance(v, dict):
                continue
            vt = str(v.get("viewType", "")).strip()
            if vt not in ("0", "1", "2", "3", "4", "5", "6", "7", "8"):
                errors.append(f"new_views[{i}] viewType 非法: {vt}")
            dc = v.get("displayControls", [])
            if isinstance(dc, list):
                for cid in dc:
                    if str(cid).strip() and str(cid).strip() not in field_ids:
                        errors.append(f"new_views[{i}].displayControls 引用不存在的字段: {cid}")

    return errors
```

- [ ] **Step 2: 验证新函数可导入**

Run:
```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
from planning.view_planner import build_single_ws_view_prompt, validate_single_ws_view_plan
p = build_single_ws_view_prompt('测试', '客户', 'ws123', [{'id':'f1','name':'名称','type':'2','isSystem':False}], 'v001')
print(f'prompt length: {len(p)}')
errors = validate_single_ws_view_plan({'default_view_update':{'name':'按状态','displayControls':['f1']},'new_views':[]}, {'f1'})
print(f'validation errors: {errors}')
"
```
Expected: prompt length < 1500, validation errors = []

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/planning/view_planner.py
git commit -m "feat: 新增单表视图规划 prompt（含默认视图改造）"
```

---

### Task 2: 新增默认视图改造函数

**Files:**
- Modify: `scripts/hap/executors/create_views_from_plan.py`

- [ ] **Step 1: 在 `save_view()` 函数之后新增 `update_default_view()`**

```python
def update_default_view(
    app_id: str,
    worksheet_id: str,
    view_id: str,
    update_plan: dict,
    auth_config_path: Path,
    dry_run: bool = False,
) -> dict:
    """改造默认视图：改名 + 修改 displayControls + 加配置。

    Args:
        app_id: 应用 ID
        worksheet_id: 工作表 ID
        view_id: 默认视图的 viewId
        update_plan: AI 输出的 default_view_update dict
        auth_config_path: 认证配置路径
        dry_run: 是否仅演练

    Returns:
        API 响应 dict
    """
    view_type = str(update_plan.get("viewType", "0")).strip()
    payload = {
        "viewId": view_id,
        "appId": app_id,
        "worksheetId": worksheet_id,
        "name": str(update_plan.get("name", "")).strip() or "数据总览",
        "editAttrs": ["name", "displayControls", "advancedSetting"],
    }

    display_controls = update_plan.get("displayControls")
    if isinstance(display_controls, list):
        payload["displayControls"] = [str(x).strip() for x in display_controls if str(x).strip()]

    adv = update_plan.get("advancedSetting")
    if isinstance(adv, dict):
        payload["advancedSetting"] = normalize_advanced_setting(view_type, adv)

    if dry_run:
        return {"dry_run": True, "payload": payload}

    return post_web_api(SAVE_VIEW_URL, payload, auth_config_path, app_id=app_id, worksheet_id=worksheet_id, view_id=view_id)
```

- [ ] **Step 2: 验证函数可导入**

Run:
```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
from executors.create_views_from_plan import update_default_view
print('import OK')
"
```
Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/executors/create_views_from_plan.py
git commit -m "feat: 新增 update_default_view() 改造默认视图"
```

---

### Task 3: 新增单表视图规划+创建原子函数

**Files:**
- Modify: `scripts/hap/planners/plan_worksheet_views_gemini.py`

- [ ] **Step 1: 在文件末尾（`main()` 之前）新增 `plan_and_create_views_for_ws()`**

```python
def plan_and_create_views_for_ws(
    client,
    model: str,
    app_id: str,
    app_name: str,
    worksheet_id: str,
    worksheet_name: str,
    default_view_id: str,
    auth_config_path: Path,
    dry_run: bool = False,
) -> dict:
    """单表视图原子操作：AI 规划 → 改造默认视图 → 创建新视图 → postCreateUpdates。

    Args:
        client: AI 客户端
        model: 模型名
        app_id: 应用 ID
        app_name: 应用名称
        worksheet_id: 工作表 ID
        worksheet_name: 工作表名称
        default_view_id: 默认"全部"视图的 viewId
        auth_config_path: auth_config.py 路径
        dry_run: 是否仅演练

    Returns:
        {"worksheetId": ..., "worksheetName": ..., "default_view_result": ..., "new_views_results": [...]}
    """
    from planning.view_planner import (
        build_single_ws_view_prompt,
        validate_single_ws_view_plan,
    )
    from executors.create_views_from_plan import (
        update_default_view,
        build_create_payload,
        build_update_payload,
        save_view,
        auto_complete_post_updates,
        merge_post_updates,
    )

    result = {
        "worksheetId": worksheet_id,
        "worksheetName": worksheet_name,
        "default_view_result": None,
        "new_views_results": [],
        "error": None,
    }

    # 1. 拉取真实字段
    try:
        schema = fetch_controls(worksheet_id, auth_config_path)
    except Exception as exc:
        result["error"] = f"拉取字段失败: {exc}"
        print(f"  ✗ [{worksheet_name}] 拉取字段失败: {exc}", file=_sys.stderr)
        return result

    raw_fields = schema.get("fields", [])
    fields = [simplify_field(f) for f in raw_fields if isinstance(f, dict)]
    field_ids = {str(f.get("id", "")).strip() for f in fields if str(f.get("id", "")).strip()}

    # 2. AI 规划
    prompt = build_single_ws_view_prompt(
        app_name=app_name,
        ws_name=worksheet_name,
        ws_id=worksheet_id,
        fields=fields,
        default_view_id=default_view_id,
    )

    plan = None
    validation_errors: list[str] = []
    for attempt in range(1, 3):
        current_prompt = prompt
        if validation_errors:
            current_prompt = (
                prompt + "\n\n上次输出校验失败，请修正：\n"
                + "\n".join(f"- {e}" for e in validation_errors)
            )
        try:
            raw_text = _call_ai_with_retry(client, model, current_prompt, label=f"view:{worksheet_name}")
            plan = _parse_ai_json(raw_text)
            validation_errors = validate_single_ws_view_plan(plan, field_ids)
            if not validation_errors:
                break
        except Exception as exc:
            validation_errors = [str(exc)]
        if attempt >= 2:
            print(f"  ⚠ [{worksheet_name}] 视图规划校验仍有错误: {validation_errors}", file=_sys.stderr)

    if plan is None:
        result["error"] = f"AI 规划失败: {validation_errors}"
        return result

    # 3. 改造默认视图
    dv_plan = plan.get("default_view_update")
    if isinstance(dv_plan, dict) and default_view_id:
        try:
            dv_resp = update_default_view(
                app_id, worksheet_id, default_view_id, dv_plan, auth_config_path, dry_run
            )
            result["default_view_result"] = {
                "viewId": default_view_id,
                "name": str(dv_plan.get("name", "")).strip(),
                "response": dv_resp,
                "success": dry_run or (isinstance(dv_resp, dict) and int(dv_resp.get("state", 0) or 0) == 1),
            }
            # postCreateUpdates for default view
            post_updates = dv_plan.get("postCreateUpdates", [])
            if isinstance(post_updates, list):
                for upd in post_updates:
                    if not isinstance(upd, dict):
                        continue
                    upd_payload = build_update_payload(app_id, worksheet_id, default_view_id, upd)
                    skip_reason = str(upd_payload.pop("_skip_reason", "")).strip()
                    if skip_reason:
                        continue
                    save_view(upd_payload, auth_config_path, app_id, worksheet_id, dry_run)
            print(f"  ✓ [{worksheet_name}] 默认视图改造: {dv_plan.get('name', '')}", file=_sys.stderr)
        except Exception as exc:
            result["default_view_result"] = {"error": str(exc)}
            print(f"  ⚠ [{worksheet_name}] 默认视图改造失败: {exc}", file=_sys.stderr)

    # 4. 逐个创建新视图
    new_views = plan.get("new_views", [])
    if not isinstance(new_views, list):
        new_views = []
    # normalize
    new_views = normalize_views(new_views, fields, worksheet_id)

    for view in new_views:
        view_name = str(view.get("name", "")).strip()
        try:
            create_payload = build_create_payload(app_id, worksheet_id, view)
            create_resp = save_view(create_payload, auth_config_path, app_id, worksheet_id, dry_run)

            created_view_id = ""
            if dry_run:
                created_view_id = "__DRY_RUN__"
            elif isinstance(create_resp, dict) and int(create_resp.get("state", 0) or 0) == 1:
                created_view_id = str((create_resp.get("data") or {}).get("viewId", "")).strip()

            view_result = {
                "name": view_name,
                "viewType": view.get("viewType"),
                "createdViewId": created_view_id,
                "success": bool(created_view_id),
                "updates": [],
            }

            # postCreateUpdates
            if created_view_id and created_view_id != "__DRY_RUN__":
                view_type_int = int(str(view.get("viewType", "0")).strip() or "0")
                ai_updates = view.get("postCreateUpdates", [])
                if not isinstance(ai_updates, list):
                    ai_updates = []
                view_with_ws = dict(view)
                view_with_ws["_worksheetId"] = worksheet_id
                auto_updates = auto_complete_post_updates(view_with_ws, raw_fields)
                post_updates = merge_post_updates(ai_updates, auto_updates, view_type_int)
                for upd in post_updates:
                    if not isinstance(upd, dict):
                        continue
                    upd_payload = build_update_payload(app_id, worksheet_id, created_view_id, upd)
                    skip_reason = str(upd_payload.pop("_skip_reason", "")).strip()
                    if skip_reason:
                        view_result["updates"].append({"skipped": True, "reason": skip_reason})
                        continue
                    upd_resp = save_view(upd_payload, auth_config_path, app_id, worksheet_id, dry_run)
                    view_result["updates"].append({"response": upd_resp})

            result["new_views_results"].append(view_result)
            status = "✓" if view_result["success"] else "✗"
            print(f"  {status} [{worksheet_name}] 新视图: {view_name} (viewType={view.get('viewType')})", file=_sys.stderr)
        except Exception as exc:
            result["new_views_results"].append({"name": view_name, "error": str(exc), "success": False})
            print(f"  ✗ [{worksheet_name}] 新视图创建失败 {view_name}: {exc}", file=_sys.stderr)

    return result
```

- [ ] **Step 2: 验证函数可导入**

Run:
```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
from planners.plan_worksheet_views_gemini import plan_and_create_views_for_ws
print('import OK')
"
```
Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/planners/plan_worksheet_views_gemini.py
git commit -m "feat: 新增 plan_and_create_views_for_ws() 单表视图原子操作"
```

---

### Task 4: 改造 Pipeline — Wave 3 后触发视图 + 移除 Wave 7

**Files:**
- Modify: `scripts/hap/pipeline/waves.py`

- [ ] **Step 1: 在 Wave 3 代码块后新增视图触发逻辑**

在 `waves.py` 中找到 Wave 3 结束位置（约 L355 `if _abort_if_failed(): return ctx`），在它之前插入视图触发逻辑。

同时需要修改 Wave 4 中移除 Step 6（视图规划+创建），因为视图改为在 Wave 3 后立即执行。

具体改动：

**1a. 在 Wave 3 的 `_abort_if_failed()` 之前，添加视图任务触发：**

在 `if _abort_if_failed(): return ctx`（Wave 3 末尾，约 L355）之前插入：

```python
    # Wave 3.5: 单表视图创建（每张表字段完成后立即触发）
    if views.get("enabled", True) and worksheet_create_result_path and not execution_dry_run:
        from planners.plan_worksheet_views_gemini import plan_and_create_views_for_ws
        from delete_default_views import fetch_views

        print(f"\n-- Wave 3.5: 逐表创建视图 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

        # 读取工作表创建结果，获取 name_to_id 映射
        ws_create_data = load_json(Path(worksheet_create_result_path))
        name_to_id = ws_create_data.get("name_to_worksheet_id", {})

        # 获取 app 授权信息用于 V3 API
        app_auth_data = load_json(Path(app_auth_json))
        auth_rows = app_auth_data.get("data", [])
        auth_row = next((r for r in auth_rows if isinstance(r, dict) and r.get("appId") == app_id), auth_rows[0] if auth_rows else {})
        app_key = str(auth_row.get("appKey", "")).strip()
        app_sign = str(auth_row.get("sign", "")).strip()
        app_name_for_views = str(app.get("name", "")).strip()

        view_results_all = []
        view_results_lock = threading.Lock()

        def _do_views_for_ws(ws_name: str, ws_id: str):
            # 获取默认视图 ID
            try:
                ws_views = fetch_views(ws_id, app_key, app_sign)
            except Exception:
                ws_views = []
            default_view_id = ""
            for v in ws_views:
                if str(v.get("name", "")).strip() in ("全部", "视图", ""):
                    default_view_id = str(v.get("viewId", "") or v.get("id", "")).strip()
                    break

            with gemini_semaphore:
                result = plan_and_create_views_for_ws(
                    client=None,  # 需要在此处初始化
                    model="",
                    app_id=app_id,
                    app_name=app_name_for_views,
                    worksheet_id=ws_id,
                    worksheet_name=ws_name,
                    default_view_id=default_view_id,
                    auth_config_path=config_web_auth,
                    dry_run=execution_dry_run,
                )
            with view_results_lock:
                view_results_all.append(result)

        # 初始化 AI 客户端
        from ai_utils import AI_CONFIG_PATH, load_ai_config, get_ai_client
        view_ai_config = load_ai_config(AI_CONFIG_PATH, tier="fast")
        view_client = get_ai_client(view_ai_config)
        view_model = view_ai_config["model"]

        def _do_views_for_ws_with_client(ws_name: str, ws_id: str):
            try:
                ws_views = fetch_views(ws_id, app_key, app_sign)
            except Exception:
                ws_views = []
            default_view_id = ""
            for v in ws_views:
                v_name = str(v.get("name", "")).strip()
                if v_name in ("全部", "视图", ""):
                    default_view_id = str(v.get("viewId", "") or v.get("id", "")).strip()
                    break

            with gemini_semaphore:
                result = plan_and_create_views_for_ws(
                    client=view_client,
                    model=view_model,
                    app_id=app_id,
                    app_name=app_name_for_views,
                    worksheet_id=ws_id,
                    worksheet_name=ws_name,
                    default_view_id=default_view_id,
                    auth_config_path=config_web_auth,
                    dry_run=execution_dry_run,
                )
            with view_results_lock:
                view_results_all.append(result)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = []
            for ws_name, ws_id in name_to_id.items():
                futures.append(pool.submit(_do_views_for_ws_with_client, ws_name, ws_id))
            for f in futures:
                try:
                    f.result()
                except Exception as exc:
                    print(f"  ✗ 视图任务异常: {exc}", file=_sys.stderr)

        # 保存视图创建结果
        view_plan_dir.mkdir(parents=True, exist_ok=True)
        view_create_result_dir.mkdir(parents=True, exist_ok=True)
        view_result_output = view_create_result_dir / f"view_create_result_{app_id}_{now_ts()}.json"
        write_json(view_result_output, {"worksheets": view_results_all})
        ctx.view_create_result_json = str(view_result_output)
        print(f"  视图创建完成: {view_result_output}", file=_sys.stderr)

        with steps_lock:
            steps_report.append({
                "step_id": 6, "step_key": "views",
                "title": "逐表创建视图",
                "skipped": False,
                "result": {"success": True, "output": str(view_result_output)},
            })
```

**1b. 在 Wave 4 的 ThreadPoolExecutor 中移除 `run_step_6`：**

将 `f6 = pool.submit(run_step_6)` 和 `ok6 = f6.result()` 注释掉或删除。把 `max_workers=7` 改为 `max_workers=6`。

**1c. 移除 Wave 7（删除默认视图）：**

将 Wave 7 整个代码块替换为注释：

```python
    # Wave 7: 已移除（默认视图改为改造而非删除）
```

**1d. Wave 5 中 Step 7（视图筛选）的 `ok6` 依赖需要调整：**

将 `if ok6 and view_create_output.exists()` 改为检查 Wave 3.5 的结果：

```python
        if ctx.view_create_result_json and Path(ctx.view_create_result_json).exists():
            cmd7.extend(["--view-create-result", ctx.view_create_result_json])
```

- [ ] **Step 2: 验证 pipeline 代码无语法错误**

Run:
```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
from pipeline.waves import run_all_waves
print('import OK')
"
```
Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/pipeline/waves.py
git commit -m "feat: 视图改为 Wave 3.5 逐表创建，移除 Wave 7 删除默认视图"
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 用 --no-execute 测试 spec 生成**

Run:
```bash
python3 make_app.py --requirements "一个简单的项目管理系统，包含项目、任务、团队成员三个模块" --no-execute
```
Expected: spec 生成成功，无报错

- [ ] **Step 2: 实际执行一次小型应用**

Run:
```bash
python3 make_app.py --requirements "一个简单的客户管理系统，包含客户信息和联系记录"
```

检查项：
- 默认视图被改造（名称不再是"全部"，有 displayControls 和分组配置）
- 新视图创建成功（看板/日历等）
- postCreateUpdates 执行成功
- 无 Wave 7 删除步骤
- `view_create_result_*.json` 格式正确

- [ ] **Step 3: Commit 最终状态**

```bash
git add -A
git commit -m "feat: 视图创建流程重新设计完成 — 单表即时触发+改造默认视图"
```
