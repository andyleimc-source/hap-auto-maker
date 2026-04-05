"""
pipeline/waves.py

Wave 1-7 编排逻辑，从 execute_requirements.py 提取。
对外暴露 run_all_waves()。
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

_HAP_DIR = Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_DIR))

from pipeline.step_runner import execute_step, run_cmd
from pipeline.context import PipelineContext
from utils import load_json, now_ts


def _extract_app_id(text: str) -> Optional[str]:
    m = re.search(r'"appId"\s*:\s*"([0-9a-fA-F-]{36})"', text or "")
    if m:
        return m.group(1)
    m2 = re.search(r"appId:\s*([0-9a-fA-F-]{36})", text or "")
    if m2:
        return m2.group(1)
    return None


def _extract_report_path(text: str) -> Optional[str]:
    m = re.search(r"-\s*报告:\s*(.+)", text or "")
    return m.group(1).strip() if m else None


def _extract_saved_path(text: str) -> Optional[str]:
    m = re.search(r"已保存:\s*(.+)", text or "")
    return m.group(1).strip() if m else None


def _extract_labeled_path(text: str, label: str) -> Optional[str]:
    pattern = rf"-\s*{re.escape(label)}:\s*(.+)"
    m = re.search(pattern, text or "")
    return m.group(1).strip() if m else None


def _extract_marker_path(text: str, marker: str) -> Optional[str]:
    for line in reversed((text or "").splitlines()):
        item = line.strip()
        if item.startswith(marker):
            return item.split(":", 1)[1].strip()
    return None


def _find_auth_file_by_app_id(app_id: str, app_auth_dir: Path) -> Optional[Path]:
    files = sorted(
        app_auth_dir.glob("app_authorize_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for f in files:
        try:
            data = load_json(f)
        except (OSError, ValueError):
            continue
        rows = data.get("data")
        if not isinstance(rows, list):
            continue
        for r in rows:
            if isinstance(r, dict) and str(r.get("appId", "")).strip() == app_id:
                return f.resolve()
    return None


def run_all_waves(
    spec: dict,
    spec_path: Path,
    *,
    execution_dry_run: bool,
    fail_fast: bool,
    verbose: bool,
    selected_steps: set,
    gemini_semaphore: threading.Semaphore,
    pipeline_start: float,
    scripts: dict,
    dirs: dict,
) -> PipelineContext:
    """执行全部 Wave，返回填充好的 PipelineContext。"""
    ctx = PipelineContext(
        spec_path=spec_path,
        execution_dry_run=execution_dry_run,
        fail_fast=fail_fast,
        verbose=verbose,
        selected_steps=selected_steps,
        execution_run_dir=dirs["execution_run_dir"],
    )
    steps_report = ctx.steps_report
    steps_lock = ctx.steps_lock

    def _exec(step_id, step_key, title, cmd, uses_gemini=False) -> bool:
        return execute_step(
            step_id, step_key, title, cmd,
            pipeline_start=pipeline_start,
            steps_report=steps_report,
            steps_lock=steps_lock,
            selected_steps=selected_steps,
            execution_dry_run=execution_dry_run,
            verbose=verbose,
            gemini_semaphore=gemini_semaphore if uses_gemini else None,
        )

    def _abort_if_failed() -> bool:
        if fail_fast and ctx.has_failure():
            out = ctx.save_report()
            print(f"\n执行失败并终止，报告: {out}")
            return True
        return False

    app = spec["app"]
    ws = spec["worksheets"]
    roles = spec["roles"]
    views = spec["views"]
    view_filters = spec["view_filters"]
    mock_data = spec["mock_data"]
    chatbots = spec["chatbots"]
    workflows = spec["workflows"]
    delete_default_views_cfg = spec["delete_default_views"]
    pages_cfg = spec["pages"]

    app_auth_dir: Path = dirs["app_auth_dir"]
    workflow_output_dir: Path = dirs["workflow_output_dir"]

    # Wave 1: 创建/使用现有应用
    if app.get("target_mode") == "create_new":
        cmd1 = [
            sys.executable, str(scripts["create_app"]),
            "--name", str(app.get("name", "CRM自动化应用")),
            "--group-ids", str(app.get("group_ids", "")),
        ]
        if str(app.get("icon_mode", "gemini_match")) != "gemini_match":
            cmd1.append("--skip-smart-icon")
        ok = _exec(1, "create_app", "创建应用+授权+应用icon", cmd1, uses_gemini=True)
        if not ok and fail_fast:
            ctx.save_report()
            return ctx
        if ok:
            if execution_dry_run:
                app_id = "DRYRUN_APP_ID"
            else:
                txt = str(steps_report[-1]["result"].get("stdout", ""))
                app_id = _extract_app_id(txt)
                if not app_id:
                    raise RuntimeError("Step1 未能从输出解析 appId")
            ctx.app_id = app_id
            ctx.app_auth_json = str((app_auth_dir / f"app_authorize_{app_id}.json").resolve())
        else:
            return ctx
    else:
        existing_app_id = str(app.get("app_id", "")).strip()
        if not existing_app_id:
            raise ValueError("target_mode=use_existing 时，spec.app.app_id 必填")
        auth_file = _find_auth_file_by_app_id(existing_app_id, app_auth_dir)
        if not auth_file:
            raise FileNotFoundError(
                f"未找到 appId={existing_app_id} 的授权文件（目录: {app_auth_dir}）"
            )
        ctx.app_id = existing_app_id
        ctx.app_auth_json = str(auth_file)
        with steps_lock:
            steps_report.append({
                "step_id": 1, "step_key": "create_app",
                "title": "创建应用+授权+应用icon",
                "skipped": True, "reason": "use_existing", "result": {},
            })

    app_id = str(ctx.app_id or "")
    app_auth_json = str(ctx.app_auth_json or "")
    if not app_id or not app_auth_json:
        raise RuntimeError("未获得 app_id/app_auth_json，无法继续执行")

    # Wave 2: 工作表规划 + 角色（并行）
    print(f"\n-- Wave 2: 工作表规划 / 角色（并行） --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    worksheet_plan_dir: Path = dirs["worksheet_plan_dir"]
    plan_output = (worksheet_plan_dir / f"worksheet_plan_{app_id}_{now_ts()}.json").resolve()

    def run_step_2a() -> bool:
        if not ws.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 2, "step_key": "worksheets_plan", "title": "规划工作表", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd2a = [
            sys.executable, str(scripts["plan_worksheets"]),
            "--app-name", str(app.get("name", "CRM自动化应用")),
            "--business-context", str(ws.get("business_context", "通用企业管理场景")),
            "--requirements", str(ws.get("requirements", "")),
            "--output", str(plan_output),
        ]
        max_ws = int(ws.get("max_worksheets", 0) or 0)
        if max_ws > 0:
            cmd2a.extend(["--max-worksheets", str(max_ws)])
        return _exec(2, "worksheets_plan", "规划工作表", cmd2a, uses_gemini=True)

    def run_step_3() -> bool:
        if not roles.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 3, "step_key": "roles", "title": "规划并创建应用角色", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd3 = [
            sys.executable, str(scripts["roles"]),
            "--app-id", app_id,
            "--video-mode", str(roles.get("video_mode", "skip")),
        ]
        if not bool(roles.get("skip_existing", True)):
            cmd3.append("--no-skip-existing")
        ok3 = _exec(3, "roles", "规划并创建应用角色", cmd3, uses_gemini=True)
        if ok3 and not execution_dry_run:
            role_report = _extract_marker_path(
                str(steps_report[-1]["result"].get("stdout", "")), "RESULT_JSON"
            )
            if role_report:
                ctx.role_pipeline_report_json = role_report
                try:
                    role_data = load_json(Path(role_report))
                    artifacts = role_data.get("artifacts", {}) if isinstance(role_data.get("artifacts"), dict) else {}
                    ctx.role_plan_json = artifacts.get("planJson")
                    ctx.role_create_result_json = artifacts.get("createResultJson")
                except (OSError, ValueError, KeyError):
                    pass  # role report 格式不完整时不影响主流程
        return ok3

    with ThreadPoolExecutor(max_workers=2) as pool:
        ok2a = pool.submit(run_step_2a).result()
        pool.submit(run_step_3).result()

    if _abort_if_failed():
        return ctx

    # Wave 2.5: 分组规划
    print(f"\n-- Wave 2.5: AI 规划工作表分组 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    sections_plan_dir: Path = dirs["sections_plan_dir"]
    sections_create_result_dir: Path = dirs["sections_create_result_dir"]
    sections_plan_output = (sections_plan_dir / f"sections_plan_{app_id}_{now_ts()}.json").resolve()
    sections_create_output = (
        sections_create_result_dir / f"sections_create_{app_id}_{now_ts()}.json"
    ).resolve()
    ok2c = True
    ok2d = True
    sections_create_result_path: Optional[str] = None

    if ws.get("enabled", True) and ok2a:
        ctx.worksheet_plan_json = str(plan_output)
        cmd2c = [
            sys.executable, str(scripts["plan_sections"]),
            "--plan-json", str(plan_output),
            "--output", str(sections_plan_output),
        ]
        ok2c = _exec(2, "sections_plan", "AI 规划工作表分组", cmd2c, uses_gemini=True)
        if ok2c and not execution_dry_run:
            ctx.sections_plan_json = str(sections_plan_output)
        if fail_fast and not ok2c:
            ctx.save_report()
            return ctx

    # 根据分组数动态决定导航样式
    if ok2c and sections_plan_output.exists() and not execution_dry_run:
        try:
            sections_data = json.loads(sections_plan_output.read_text(encoding="utf-8"))
            section_count = len(sections_data.get("sections", []))
            if section_count > 3:
                app["navi_style"]["pcNaviStyle"] = 0
                print(f"  ℹ 分组数={section_count} > 3，自动切换为经典导航（pcNaviStyle=0）", flush=True)
        except Exception as e:
            print(f"  ⚠ 读取分组数失败，使用默认导航样式: {e}", flush=True)

    # Step 8: 导航风格（串行，依赖分组数）
    if not app["navi_style"].get("enabled", True):
        with steps_lock:
            steps_report.append({"step_id": 8, "step_key": "navi", "title": "设置应用导航风格", "skipped": True, "reason": "disabled_by_spec", "result": {}})
    else:
        cmd8 = [
            sys.executable, str(scripts["navi"]),
            "--app-id", app_id,
            "--pc-navi-style", str(int(app["navi_style"].get("pcNaviStyle", 1))),
        ]
        if app["navi_style"].get("refresh_auth", False):
            cmd8.append("--refresh-auth")
        _exec(8, "navi", "设置应用导航风格", cmd8, uses_gemini=False)

    if _abort_if_failed():
        return ctx

    # Wave 3: 创建工作表
    print(f"\n-- Wave 3: 创建工作表 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    if ws.get("enabled", True) and ok2c and not execution_dry_run:
        cmd2d = [
            sys.executable, str(scripts["create_sections"]),
            "--sections-plan-json", str(sections_plan_output),
            "--plan-json", str(plan_output),
            "--app-id", app_id,
            "--app-auth-json", str(app_auth_json),
            "--output", str(sections_create_output),
        ]
        ok2d = _exec(2, "sections_create", "创建工作表分组", cmd2d, uses_gemini=False)
        if ok2d:
            sections_create_result_path = str(sections_create_output)
            ctx.sections_create_result_json = sections_create_result_path
        if fail_fast and not ok2d:
            ctx.save_report()
            return ctx

    worksheet_create_result_path: Optional[str] = None
    if ws.get("enabled", True) and ok2a:
        cmd2b = [
            sys.executable, str(scripts["create_worksheets"]),
            "--plan-json", str(plan_output),
            "--app-auth-json", str(app_auth_json),
        ]
        ok2b = _exec(2, "worksheets_create", "创建工作表", cmd2b, uses_gemini=False)
        if ok2b and not execution_dry_run:
            worksheet_create_result_path = _extract_saved_path(
                str(steps_report[-1]["result"].get("stdout", ""))
            )
            ctx.worksheet_create_result_json = worksheet_create_result_path
        if fail_fast and not ok2b:
            ctx.save_report()
            return ctx

        if ok2b and ok2d and sections_create_result_path and worksheet_create_result_path and not execution_dry_run:
            cmd2d2 = [
                sys.executable, str(scripts["create_sections"]),
                "--sections-plan-json", str(sections_plan_output),
                "--plan-json", str(plan_output),
                "--app-id", app_id,
                "--app-auth-json", str(app_auth_json),
                "--output", str(sections_create_output),
                "--ws-create-result", str(worksheet_create_result_path),
            ]
            _exec(2, "sections_move", "移动工作表到分组", cmd2d2, uses_gemini=False)

    elif not ws.get("enabled", True):
        with steps_lock:
            steps_report.append({"step_id": 2, "step_key": "worksheets_create", "title": "创建工作表", "skipped": True, "reason": "disabled_by_spec", "result": {}})

    if _abort_if_failed():
        return ctx

    # Wave 4: 并行（icon/布局/视图/造数/机器人/工作流规划/图表规划）
    print(
        f"\n-- Wave 4: icon / 布局 / 视图 / 造数 / 机器人 / 工作流规划 / 规划图表页（并行） --- 总计 {time.time()-pipeline_start:.0f}s",
        flush=True,
    )

    view_plan_dir: Path = dirs["view_plan_dir"]
    view_create_result_dir: Path = dirs["view_create_result_dir"]
    tableview_filter_plan_dir: Path = dirs["tableview_filter_plan_dir"]
    tableview_filter_apply_result_dir: Path = dirs["tableview_filter_apply_result_dir"]
    output_root: Path = dirs["output_root"]
    config_web_auth: Path = dirs["config_web_auth"]

    view_plan_output = (view_plan_dir / f"view_plan_{app_id}_{now_ts()}.json").resolve()
    view_create_output = (view_create_result_dir / f"view_create_result_{app_id}_{now_ts()}.json").resolve()
    workflow_plan_output = (workflow_output_dir / f"pipeline_workflows_{app_id}_{now_ts()}.json").resolve()
    page_plan_output = (output_root / "page_plans" / f"page_plan_{app_id}_pipeline.json").resolve()
    ok_14a = False

    def run_step_4() -> bool:
        if not ws["icon_update"].get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 4, "step_key": "worksheet_icon", "title": "更新工作表icon", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd4 = [sys.executable, str(scripts["icon"]), "--app-auth-json", str(app_auth_json), "--app-id", app_id]
        if ws["icon_update"].get("refresh_auth", False):
            cmd4.append("--refresh-auth")
        return _exec(4, "worksheet_icon", "更新工作表icon", cmd4, uses_gemini=True)

    def run_step_5() -> bool:
        if not ws["layout"].get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 5, "step_key": "layout", "title": "规划并应用字段布局", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd5 = [sys.executable, str(scripts["layout"]), "--app-id", app_id]
        layout_req = str(ws["layout"].get("requirements", "")).strip()
        if layout_req:
            cmd5.extend(["--requirements", layout_req])
        if ws["layout"].get("refresh_auth", False):
            cmd5.append("--refresh-auth")
        ok5 = _exec(5, "layout", "规划并应用字段布局", cmd5, uses_gemini=True)
        if ok5 and not execution_dry_run:
            layout_stdout = str(steps_report[-1]["result"].get("stdout", ""))
            ctx.worksheet_layout_plan_json = _extract_labeled_path(layout_stdout, "输出文件")
            ctx.worksheet_layout_apply_result_json = _extract_labeled_path(layout_stdout, "结果文件")
        return ok5

    def run_step_6() -> bool:
        if not views.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 6, "step_key": "views", "title": "规划并创建视图", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd6 = [
            sys.executable, str(scripts["views"]),
            "--app-ids", app_id,
            "--plan-output", str(view_plan_output),
            "--create-output", str(view_create_output),
        ]
        ok6 = _exec(6, "views", "规划并创建视图", cmd6, uses_gemini=True)
        if ok6:
            ctx.view_plan_json = str(view_plan_output)
            ctx.view_create_result_json = str(view_create_output)
        return ok6

    def run_step_9() -> bool:
        if not mock_data.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 9, "step_key": "mock_data", "title": "执行造数流水线", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd9 = [sys.executable, str(scripts["mock_data"]), "--app-id", app_id]
        if execution_dry_run or mock_data.get("dry_run", False):
            cmd9.append("--dry-run")
        if mock_data.get("trigger_workflow", False):
            cmd9.append("--trigger-workflow")
        ok9 = _exec(9, "mock_data", "执行造数流水线", cmd9, uses_gemini=True)
        if ok9 and not execution_dry_run:
            ctx.mock_data_run_json = _extract_report_path(str(steps_report[-1]["result"].get("stdout", "")))
        if not ok9:
            with steps_lock:
                for sr in steps_report:
                    if sr.get("step_id") == 9 and not sr.get("ok", True):
                        sr["non_fatal"] = True
                        break
        return ok9

    def run_step_10() -> bool:
        if not chatbots.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 10, "step_key": "chatbots", "title": "创建对话机器人", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd10 = [sys.executable, str(scripts["chatbots"]), "--app-id", app_id]
        if chatbots.get("auto", True):
            cmd10.append("--auto")
        if chatbots.get("dry_run", False) or execution_dry_run:
            cmd10.append("--dry-run-create")
        ok10 = _exec(10, "chatbots", "创建对话机器人", cmd10, uses_gemini=True)
        if ok10 and not execution_dry_run:
            ctx.chatbot_pipeline_result_json = _extract_labeled_path(
                str(steps_report[-1]["result"].get("stdout", "")), "RESULT_JSON"
            )
        return ok10

    def run_step_11() -> bool:
        if not workflows.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 11, "step_key": "workflows_plan", "title": "规划工作流（AI）", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        workflow_output_dir.mkdir(parents=True, exist_ok=True)
        cmd11 = [
            sys.executable, str(scripts["workflows_plan"]),
            "--relation-id", app_id,
            "--thinking", str(workflows.get("thinking", "none")),
            "--output", str(workflow_plan_output),
        ]
        if workflows.get("skip_analysis", False):
            cmd11.append("--skip-analysis")
        ok11 = _exec(11, "workflows_plan", "规划工作流（AI）", cmd11, uses_gemini=True)
        if ok11:
            ctx.workflow_plan_json = str(workflow_plan_output)
        return ok11

    def run_step_14a() -> bool:
        nonlocal ok_14a
        if not pages_cfg.get("enabled", True):
            ok_14a = False
            return True
        cmd14a = [
            sys.executable, str(scripts["plan_pages"]),
            "--app-id", app_id,
            "--auth-config", str(config_web_auth),
            "--output", str(page_plan_output),
        ]
        elapsed_total = time.time() - pipeline_start
        print(f"  ▶ Step 14a/ 14  规划统计图表页（AI）  [{elapsed_total:.0f}s]", flush=True)
        step_start = time.time()
        with gemini_semaphore:
            result = run_cmd(cmd14a, dry_run=execution_dry_run, verbose=verbose)
        ok_14a = int(result.get("returncode", 1)) == 0
        duration = time.time() - step_start
        elapsed_total = time.time() - pipeline_start
        status = "✓" if ok_14a else "✗"
        print(f"  {status} Step 14a/ 14  规划统计图表页（AI）  ({duration:.0f}s, 总计 {elapsed_total:.0f}s)", flush=True)
        if not ok_14a:
            err = str(result.get("stderr", "") or "").strip()
            if err:
                if len(err) > 900:
                    print(err[:300], flush=True)
                    print("  ...(省略中间内容)...", flush=True)
                    print(err[-600:], flush=True)
                else:
                    print(err, flush=True)
        return ok_14a

    with ThreadPoolExecutor(max_workers=7) as pool:
        f4 = pool.submit(run_step_4)
        f5 = pool.submit(run_step_5)
        f6 = pool.submit(run_step_6)
        f9 = pool.submit(run_step_9)
        f10 = pool.submit(run_step_10)
        f11 = pool.submit(run_step_11)
        f14a = pool.submit(run_step_14a)
        f4.result()
        f5.result()
        ok6 = f6.result()
        f9.result()
        f10.result()
        ok11 = f11.result()
        f14a.result()

    if _abort_if_failed():
        return ctx

    # Wave 5: 视图筛选 + 创建工作流（并行）
    print(f"\n-- Wave 5: 视图筛选 / 创建工作流（并行） --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    filter_plan_output = (
        tableview_filter_plan_dir / f"tableview_filter_plan_{app_id}_{now_ts()}.json"
    ).resolve()
    filter_apply_output = (
        tableview_filter_apply_result_dir / f"tableview_filter_apply_result_{app_id}_{now_ts()}.json"
    ).resolve()

    def run_step_7() -> bool:
        if not view_filters.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 7, "step_key": "view_filters", "title": "规划并应用视图筛选", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd7 = [
            sys.executable, str(scripts["view_filters"]),
            "--app-ids", app_id,
            "--plan-output", str(filter_plan_output),
            "--apply-output", str(filter_apply_output),
            "--app-auth-json", str(app_auth_json),
        ]
        if ok6 and view_create_output.exists():
            cmd7.extend(["--view-create-result", str(view_create_output)])
        if execution_dry_run:
            cmd7.append("--dry-run")
        ok7 = _exec(7, "view_filters", "规划并应用视图筛选", cmd7, uses_gemini=True)
        if ok7:
            ctx.tableview_filter_plan_json = str(filter_plan_output)
            ctx.tableview_filter_apply_result_json = str(filter_apply_output)
        return ok7

    def run_step_12() -> bool:
        if not workflows.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 12, "step_key": "workflows_execute", "title": "创建工作流", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        if not ok11:
            with steps_lock:
                steps_report.append({"step_id": 12, "step_key": "workflows_execute", "title": "创建工作流", "skipped": True, "reason": "step11_failed", "result": {}})
            return True
        workflow_execute_output = (workflow_output_dir / "execute_workflow_plan_latest.json").resolve()
        cmd12 = [sys.executable, str(scripts["workflows_execute"]), "--plan-file", str(workflow_plan_output)]
        if workflows.get("no_publish", False):
            cmd12.append("--no-publish")
        ok12 = _exec(12, "workflows_execute", "创建工作流", cmd12, uses_gemini=False)
        if ok12:
            ctx.workflow_execute_result_json = str(workflow_execute_output)
        return ok12

    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(run_step_7).result()
        pool.submit(run_step_12).result()

    # Wave 6: 统计图表 Pages
    print(f"\n-- Wave 6: 统计图表 Pages --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    if not pages_cfg.get("enabled", True):
        with steps_lock:
            steps_report.append({"step_id": 14, "step_key": "pages", "title": "创建统计图表页", "skipped": True, "reason": "disabled_by_spec", "result": {}})
    else:
        cmd14 = [
            sys.executable, str(scripts["pages"]),
            "--app-id", app_id,
            "--auth-config", str(config_web_auth),
            "--plan-output", str(page_plan_output),
        ]
        if ok_14a:
            cmd14.append("--skip-plan")
        if execution_dry_run:
            cmd14.append("--dry-run")
        title = "创建统计图表页" if ok_14a else "规划并创建统计图表页"
        _exec(14, "pages", title, cmd14, uses_gemini=not ok_14a)

    # Wave 7: 删除默认视图
    print(f"\n-- Wave 7: 删除[全部]默认视图 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    if not delete_default_views_cfg.get("enabled", True):
        with steps_lock:
            steps_report.append({"step_id": 13, "step_key": "delete_default_views", "title": "删除[全部]默认视图", "skipped": True, "reason": "disabled_by_spec", "result": {}})
    else:
        cmd13 = [
            sys.executable, str(scripts["delete_default_views"]),
            "--app-id", app_id,
            "--app-auth-json", str(app_auth_json),
            "--auth-config", str(config_web_auth),
        ]
        if delete_default_views_cfg.get("refresh_auth", True):
            cmd13.extend(["--refresh-auth", "--headless"])
        if execution_dry_run:
            cmd13.append("--dry-run")
        _exec(13, "delete_default_views", "删除[全部]默认视图", cmd13, uses_gemini=False)

    return ctx
