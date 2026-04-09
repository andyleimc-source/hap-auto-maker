"""
pipeline/waves.py

Wave 1-6 编排逻辑，从 execute_requirements.py 提取。
对外暴露 run_all_waves()。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

_HAP_DIR = Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_DIR))

from pipeline.step_runner import execute_step
from pipeline.context import PipelineContext
from utils import load_json, write_json, now_ts, log_summary


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


def _load_checkpoint(path: Path, validator_fn=None) -> Optional[dict]:
    """若 checkpoint 文件存在且合法，返回其内容；否则返回 None。"""
    if not path.exists():
        return None
    try:
        data = load_json(path)
        if validator_fn and not validator_fn(data):
            return None
        return data
    except Exception:
        return None


def _sync_latest_output(source_path: Path, latest_path: Path) -> None:
    """将本次输出同步到稳定 latest 文件。"""
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(latest_path, load_json(source_path))


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
    force_replan: bool = False,
    rollback_on_failure: bool = False,
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
            if (
                rollback_on_failure
                and not execution_dry_run
                and app.get("target_mode") == "create_new"
                and ctx.app_id
            ):
                try:
                    cmd = [
                        sys.executable,
                        str(scripts["delete_app"]),
                        "--app-id",
                        str(ctx.app_id),
                    ]
                    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
                    if proc.returncode == 0:
                        print(f"  ↩ 回滚成功：已删除应用 {ctx.app_id}")
                    else:
                        print(f"  ⚠ 回滚失败（exit={proc.returncode}）: {proc.stderr.strip() or proc.stdout.strip()}")
                except Exception as exc:
                    print(f"  ⚠ 回滚异常: {exc}")
            return True
        return False

    app = spec["app"]
    ws = spec["worksheets"]
    roles = spec["roles"]
    views = spec["views"]
    view_filters = spec["view_filters"]
    mock_data = spec["mock_data"]
    chatbots = spec["chatbots"]
    delete_default_views_cfg = spec["delete_default_views"]
    pages_cfg = spec["pages"]

    app_auth_dir: Path = dirs["app_auth_dir"]
    output_root: Path = dirs["output_root"]
    config_web_auth: Path = dirs["config_web_auth"]

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
    plan_output_ts = (worksheet_plan_dir / f"worksheet_plan_{app_id}_{now_ts()}.json").resolve()
    plan_output_latest = (worksheet_plan_dir / f"worksheet_plan_{app_id}_latest.json").resolve()
    plan_output = plan_output_ts

    def run_step_2a() -> bool:
        nonlocal plan_output
        if not ws.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 2, "step_key": "worksheets_plan", "title": "规划工作表", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        if not force_replan:
            checkpoint = _load_checkpoint(
                plan_output_latest,
                lambda d: isinstance(d.get("worksheets"), list) and len(d.get("worksheets", [])) > 0,
            )
            if checkpoint is not None:
                print(f"  [checkpoint] 使用已有工作表规划: {plan_output_latest}", flush=True)
                plan_output = plan_output_latest
                ctx.worksheet_plan_json = str(plan_output_latest)
                with steps_lock:
                    steps_report.append({
                        "step_id": 2, "step_key": "worksheets_plan", "title": "规划工作表",
                        "skipped": True, "reason": "checkpoint", "result": {"checkpoint": str(plan_output_latest)},
                    })
                return True
        cmd2a = [
            sys.executable, str(scripts["plan_worksheets"]),
            "--app-name", str(app.get("name", "CRM自动化应用")),
            "--business-context", str(ws.get("business_context", "通用企业管理场景")),
            "--requirements", str(ws.get("requirements", "")),
            "--output", str(plan_output_ts),
        ]
        max_ws = int(ws.get("max_worksheets", 0) or 0)
        if max_ws > 0:
            cmd2a.extend(["--max-worksheets", str(max_ws)])
        sem_value = getattr(gemini_semaphore, '_value', 1000)
        cmd2a.extend(["--concurrency", str(sem_value)])
        ok = _exec(2, "worksheets_plan", "规划工作表", cmd2a, uses_gemini=True)
        if ok and not execution_dry_run and plan_output_ts.exists():
            _sync_latest_output(plan_output_ts, plan_output_latest)
            plan_output = plan_output_latest
            ctx.worksheet_plan_json = str(plan_output_latest)
        return ok

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
    sections_plan_output_ts = (sections_plan_dir / f"sections_plan_{app_id}_{now_ts()}.json").resolve()
    sections_plan_output_latest = (sections_plan_dir / f"sections_plan_{app_id}_latest.json").resolve()
    sections_plan_output = sections_plan_output_ts
    sections_create_output = (
        sections_create_result_dir / f"sections_create_{app_id}_{now_ts()}.json"
    ).resolve()
    ok2c = True
    ok2d = True
    sections_create_result_path: Optional[str] = None

    if ws.get("enabled", True) and ok2a:
        ctx.worksheet_plan_json = str(plan_output)
        if not force_replan:
            checkpoint = _load_checkpoint(
                sections_plan_output_latest,
                lambda d: isinstance(d.get("sections"), list) and len(d.get("sections", [])) > 0,
            )
            if checkpoint is not None:
                print(f"  [checkpoint] 使用已有分组规划: {sections_plan_output_latest}", flush=True)
                sections_plan_output = sections_plan_output_latest
                ctx.sections_plan_json = str(sections_plan_output_latest)
                with steps_lock:
                    steps_report.append({
                        "step_id": 2, "step_key": "sections_plan", "title": "AI 规划工作表分组",
                        "skipped": True, "reason": "checkpoint", "result": {"checkpoint": str(sections_plan_output_latest)},
                    })
                ok2c = True
            else:
                cmd2c = [
                    sys.executable, str(scripts["plan_sections"]),
                    "--plan-json", str(plan_output),
                    "--output", str(sections_plan_output_ts),
                ]
                ok2c = _exec(2, "sections_plan", "AI 规划工作表分组", cmd2c, uses_gemini=True)
                if ok2c and not execution_dry_run and sections_plan_output_ts.exists():
                    _sync_latest_output(sections_plan_output_ts, sections_plan_output_latest)
                    sections_plan_output = sections_plan_output_latest
                    ctx.sections_plan_json = str(sections_plan_output_latest)
        else:
            cmd2c = [
                sys.executable, str(scripts["plan_sections"]),
                "--plan-json", str(plan_output),
                "--output", str(sections_plan_output_ts),
            ]
            ok2c = _exec(2, "sections_plan", "AI 规划工作表分组", cmd2c, uses_gemini=True)
            if ok2c and not execution_dry_run and sections_plan_output_ts.exists():
                _sync_latest_output(sections_plan_output_ts, sections_plan_output_latest)
                sections_plan_output = sections_plan_output_latest
                ctx.sections_plan_json = str(sections_plan_output_latest)
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

    # Wave 2.5b: 提前创建统计分析 Pages
    page_registry_output: Optional[str] = None
    if pages_cfg.get("enabled", True) and ok2a:
        page_registry_path_ts = (output_root / "page_registries" / f"page_registry_{app_id}_{now_ts()}.json").resolve()
        page_registry_path_latest = (output_root / "page_registries" / f"page_registry_{app_id}_latest.json").resolve()
        checkpoint_hit = False
        if not force_replan:
            checkpoint = _load_checkpoint(
                page_registry_path_latest,
                lambda d: isinstance(d.get("pages"), list) and len(d.get("pages", [])) > 0,
            )
            if checkpoint is not None:
                print(f"  [checkpoint] 使用已有 Pages 注册表: {page_registry_path_latest}", flush=True)
                page_registry_output = str(page_registry_path_latest)
                ctx.page_registry_json = page_registry_output
                checkpoint_hit = True
                with steps_lock:
                    steps_report.append({
                        "step_id": 14, "step_key": "pages_early", "title": "提前创建统计分析 Pages",
                        "skipped": True, "reason": "checkpoint", "result": {"checkpoint": str(page_registry_path_latest)},
                    })
        if not checkpoint_hit:
            cmd_pages_early = [
                sys.executable, str(scripts["create_pages_early"]),
                "--app-id", app_id,
                "--worksheet-plan-json", str(plan_output),
                "--auth-config", str(config_web_auth),
                "--output", str(page_registry_path_ts),
            ]
            if bool(pages_cfg.get("skip_existing", True)):
                cmd_pages_early.append("--skip-existing")
            else:
                cmd_pages_early.append("--no-skip-existing")
            if execution_dry_run:
                cmd_pages_early.append("--dry-run")
            ok_pages_early = _exec(14, "pages_early", "提前创建统计分析 Pages", cmd_pages_early, uses_gemini=True)
            if ok_pages_early and not execution_dry_run and page_registry_path_ts.exists():
                _sync_latest_output(page_registry_path_ts, page_registry_path_latest)
                page_registry_output = str(page_registry_path_latest)
                ctx.page_registry_json = page_registry_output

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
        _sem_value_2b = getattr(gemini_semaphore, '_value', 1000)
        cmd2b = [
            sys.executable, str(scripts["create_worksheets"]),
            "--plan-json", str(plan_output),
            "--app-auth-json", str(app_auth_json),
            "--semaphore-value", str(_sem_value_2b),
        ]
        if bool(ws.get("skip_existing", True)):
            cmd2b.append("--skip-existing")
        else:
            cmd2b.append("--no-skip-existing")
        if page_registry_output:
            cmd2b.extend(["--page-registry", page_registry_output])
        import os
        if page_registry_output:
            os.environ["AUTH_CONFIG_PATH"] = str(config_web_auth)
        ok2b = _exec(2, "worksheets_create", "创建工作表", cmd2b, uses_gemini=False)
        if not execution_dry_run:
            # 即使 ok2b=False（crash），也尝试提取结果路径——
            # 工作表可能已全部创建完毕，crash 发生在最后的校验阶段
            worksheet_create_result_path = _extract_saved_path(
                str(steps_report[-1]["result"].get("stdout", ""))
            )
            ctx.worksheet_create_result_json = worksheet_create_result_path
        if fail_fast and not ok2b:
            ctx.save_report()
            return ctx

        if ok2d and sections_create_result_path and worksheet_create_result_path and not execution_dry_run:
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

    # 提前初始化 Wave 3.5 和 Wave 4 共用的目录变量
    view_create_result_dir: Path = dirs["view_create_result_dir"]

    # Wave 3.5: 单表视图创建（使用新推荐+配置+创建流水线，逐表并行）
    if views.get("enabled", True) and worksheet_create_result_path and not execution_dry_run:
        from planners.view_recommender import recommend_views
        from planners.view_configurator import configure_single_view
        from planners.plan_worksheet_views_gemini import fetch_controls, simplify_field
        from executors.create_views_from_plan import create_single_view_from_config
        from ai_utils import load_ai_config as _view_load_ai

        print(f"\n-- Wave 3.5: 逐表创建视图 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

        ws_create_data = load_json(Path(worksheet_create_result_path))
        _name_to_id = ws_create_data.get("name_to_worksheet_id", {})

        _app_name_for_views = str(app.get("name", "")).strip()
        _app_background = str(spec.get("worksheets", {}).get("business_context", "通用企业管理场景"))
        _view_ai_config = _view_load_ai()
        _all_ws_names = list(_name_to_id.keys())

        _view_results_all = []
        _view_lock = threading.Lock()

        def _do_views_for_ws(ws_name: str, ws_id: str):
            """单表视图创建：推荐 → 配置 → 创建。"""
            # 1. 拉取字段
            try:
                schema = fetch_controls(ws_id, config_web_auth)
            except Exception as exc:
                print(f"  ✗ [{ws_name}] 拉取字段失败: {exc}", file=sys.stderr)
                return

            raw_fields = schema.get("fields", [])
            fields = [simplify_field(f) for f in raw_fields if isinstance(f, dict)]
            field_ids = {str(f.get("id", "")).strip() for f in fields if str(f.get("id", "")).strip()}
            other_names = [n for n in _all_ws_names if n != ws_name]

            # 2. AI 推荐（受 Gemini 信号量限制）
            with gemini_semaphore:
                rec = recommend_views(
                    app_name=_app_name_for_views,
                    app_background=_app_background,
                    worksheet_name=ws_name,
                    worksheet_id=ws_id,
                    fields=fields,
                    other_worksheet_names=other_names,
                    ai_config=_view_ai_config,
                )

            rec_views = rec.get("views", [])
            if not rec_views:
                log_summary(f"  [{ws_name}] 无推荐视图，跳过")
                with _view_lock:
                    _view_results_all.append({
                        "worksheetId": ws_id, "worksheetName": ws_name,
                        "new_views_results": [],
                    })
                return

            # 3. 并行配置每个视图（受 Gemini 信号量限制）
            configs = []
            def _configure_one(v):
                with gemini_semaphore:
                    return configure_single_view(v, ws_name, fields, field_ids, _view_ai_config)

            with ThreadPoolExecutor(max_workers=min(len(rec_views), 5)) as cfg_pool:
                cfg_futures = {cfg_pool.submit(_configure_one, v): v for v in rec_views}
                for fut in cfg_futures:
                    v = cfg_futures[fut]
                    try:
                        cfg = fut.result()
                        if cfg:
                            configs.append(cfg)
                        else:
                            print(f"  ✗ [{ws_name}] 配置失败: {v.get('name', '')}", file=sys.stderr)
                    except Exception as exc:
                        print(f"  ✗ [{ws_name}] 配置异常 {v.get('name', '')}: {exc}", file=sys.stderr)

            if not configs:
                log_summary(f"  [{ws_name}] 所有视图配置失败，跳过创建")
                with _view_lock:
                    _view_results_all.append({
                        "worksheetId": ws_id, "worksheetName": ws_name,
                        "new_views_results": [],
                    })
                return

            # 4. 并行创建每个视图
            new_views_results = []
            def _create_one(cfg):
                view_data = {
                    "name": cfg.get("name", ""),
                    "viewType": str(cfg.get("viewType", "0")),
                    "displayControls": cfg.get("displayControls", []),
                    "viewControl": cfg.get("viewControl", ""),
                    "coverCid": cfg.get("coverCid", ""),
                    "advancedSetting": cfg.get("advancedSetting", {}),
                    "postCreateUpdates": cfg.get("postCreateUpdates", []),
                }
                return create_single_view_from_config(
                    worksheet_id=ws_id,
                    app_id=app_id,
                    view_config=view_data,
                    auth_config_path=config_web_auth,
                    ws_fields=raw_fields,
                    dry_run=execution_dry_run,
                )

            with ThreadPoolExecutor(max_workers=min(len(configs), 10)) as create_pool:
                create_futures = {create_pool.submit(_create_one, c): c for c in configs}
                for fut in create_futures:
                    c = create_futures[fut]
                    try:
                        cr = fut.result()
                        new_views_results.append(cr)
                        status = "✓" if cr.get("success") else "✗"
                        print(f"  {status} [{ws_name}] {c.get('name', '')} (viewType={c.get('viewType', '')})", file=sys.stderr)
                    except Exception as exc:
                        new_views_results.append({"name": c.get("name", ""), "success": False, "error": str(exc)})
                        print(f"  ✗ [{ws_name}] 创建异常 {c.get('name', '')}: {exc}", file=sys.stderr)

            ok_count = sum(1 for r in new_views_results if r.get("success"))
            log_summary(f"✓「{ws_name}」→ {ok_count}/{len(new_views_results)} 个视图已创建")
            with _view_lock:
                _view_results_all.append({
                    "worksheetId": ws_id,
                    "worksheetName": ws_name,
                    "new_views_results": new_views_results,
                })

        with ThreadPoolExecutor(max_workers=max(1, len(_name_to_id))) as pool:
            futures = [pool.submit(_do_views_for_ws, wn, wi) for wn, wi in _name_to_id.items()]
            for f in futures:
                try:
                    f.result()
                except Exception as exc:
                    print(f"  ✗ 视图任务异常: {exc}", file=sys.stderr)

        view_create_result_dir.mkdir(parents=True, exist_ok=True)
        _view_result_path = view_create_result_dir / f"view_create_result_{app_id}_{now_ts()}.json"
        # 转换为兼容格式（下游 load_view_targets 期望 worksheets[].views[].createdViewId）
        _compat_worksheets = []
        for _vr in _view_results_all:
            _compat_views = []
            for _nvr in _vr.get("new_views_results", []):
                if isinstance(_nvr, dict):
                    _compat_views.append({
                        "name": str(_nvr.get("name", "")).strip(),
                        "viewType": str(_nvr.get("viewType", "")).strip(),
                        "createdViewId": str(_nvr.get("viewId", "")).strip(),
                        "success": bool(_nvr.get("success")),
                    })
            _compat_worksheets.append({
                "worksheetId": str(_vr.get("worksheetId", "")).strip(),
                "worksheetName": str(_vr.get("worksheetName", "")).strip(),
                "views": _compat_views,
            })
        write_json(_view_result_path, {
            "apps": [{
                "appId": app_id,
                "appName": _app_name_for_views,
                "worksheets": _compat_worksheets,
            }],
        })
        ctx.view_create_result_json = str(_view_result_path)
        print(f"  视图创建完成: {_view_result_path}", flush=True)

        with steps_lock:
            steps_report.append({
                "step_id": 6, "step_key": "views",
                "title": "逐表创建视图",
                "skipped": False,
                "result": {"success": True, "output": str(_view_result_path)},
            })

    if _abort_if_failed():
        return ctx

    # ── Wave 3.5b: 逐表造数 + 关联字段填写（Two-Phase）──────────────────────────────
    if mock_data.get("enabled", True) and worksheet_create_result_path and not execution_dry_run:
        from planners.mock_data_inline import plan_and_write_mock_data_for_ws, apply_relation_phase
        from mock_data_common import build_schema_snapshot, DEFAULT_BASE_URL
        from ai_utils import AI_CONFIG_PATH as _MD_AI_CFG, load_ai_config as _md_load_ai, get_ai_client as _md_get_client

        print(f"\n-- Wave 3.5b Phase 1: 逐表造数 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

        # 从 app_auth_json 取 appKey/sign
        _auth_data = load_json(Path(app_auth_json))
        _auth_rows = _auth_data.get("data", [])
        _auth_row = next(
            (r for r in _auth_rows if isinstance(r, dict) and r.get("appId") == app_id),
            _auth_rows[0] if _auth_rows else {},
        )
        _md_app_key = str(_auth_row.get("appKey", "")).strip()
        _md_sign = str(_auth_row.get("sign", "")).strip()

        # 构建结构快照（含 relationPairs, relationEdges）
        _md_snapshot = build_schema_snapshot(
            DEFAULT_BASE_URL,
            {
                "appId": app_id,
                "appName": str(app.get("name", "")).strip(),
                "appKey": _md_app_key,
                "sign": _md_sign,
                "authPath": app_auth_json,
                "authFile": "",
            },
        )
        _md_relation_pairs = _md_snapshot.get("relationPairs", [])
        _md_relation_edges = _md_snapshot.get("relationEdges", [])
        _md_ws_schemas_by_id = {wss["worksheetId"]: wss for wss in _md_snapshot.get("worksheets", [])}

        # 业务背景
        _md_business_context = str(ws.get("business_context", "")).strip()
        _md_app_name = str(app.get("name", "")).strip()

        # AI client
        _md_ai_config = _md_load_ai(_MD_AI_CFG)
        _md_client = _md_get_client(_md_ai_config)
        _md_model = _md_ai_config["model"]

        # Phase 1: 并发逐表造数
        _md_all_row_ids: dict = {}
        _md_results: list = []
        _md_lock = threading.Lock()

        def _do_mock_for_ws(ws_name: str, ws_id: str):
            wss_schema = _md_ws_schemas_by_id.get(ws_id)
            if not wss_schema:
                print(f"  ⚠ [{ws_name}] 未找到结构快照，跳过造数", flush=True)
                return
            with gemini_semaphore:
                result = plan_and_write_mock_data_for_ws(
                    client=_md_client,
                    model=_md_model,
                    ai_config=_md_ai_config,
                    app_id=app_id,
                    app_name=_md_app_name,
                    business_context=_md_business_context,
                    app_key=_md_app_key,
                    sign=_md_sign,
                    base_url=DEFAULT_BASE_URL,
                    worksheet_id=ws_id,
                    worksheet_name=ws_name,
                    ws_schema=wss_schema,
                    relation_pairs=_md_relation_pairs,
                    relation_edges=_md_relation_edges,
                    dry_run=mock_data.get("dry_run", False),
                )
            with _md_lock:
                _md_results.append(result)
                if result.get("rowIds"):
                    _md_all_row_ids[ws_id] = result["rowIds"]

        _md_ws_create_data = load_json(Path(worksheet_create_result_path))
        _md_name_to_id = _md_ws_create_data.get("name_to_worksheet_id", {})

        with ThreadPoolExecutor(max_workers=max(1, len(_md_name_to_id))) as pool:
            futures = [pool.submit(_do_mock_for_ws, wn, wi) for wn, wi in _md_name_to_id.items()]
            for f in futures:
                try:
                    f.result()
                except Exception as exc:
                    print(f"  ✗ 造数任务异常: {exc}", file=sys.stderr)

        print(f"  造数完成: {len(_md_all_row_ids)}/{len(_md_name_to_id)} 张表写入成功", flush=True)

        # 保存 Phase 1 结果
        _md_result_dir = Path(app_auth_json).parent.parent / "mock_data_inline_results"
        _md_result_dir.mkdir(parents=True, exist_ok=True)
        _md_result_path = _md_result_dir / f"mock_data_inline_{app_id}_{now_ts()}.json"
        write_json(_md_result_path, {
            "appId": app_id,
            "appName": _md_app_name,
            "worksheets": _md_results,
            "rowIdMap": _md_all_row_ids,
        })
        ctx.mock_data_inline_result_json = str(_md_result_path)

        # Phase 2: 按 tier 并发填关联
        if mock_data.get("relation_enabled", True) and _md_all_row_ids and _md_relation_pairs:
            print(f"\n-- Wave 3.5b Phase 2: 关联字段填写 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)
            _md_rel_result = apply_relation_phase(
                app_id=app_id,
                app_key=_md_app_key,
                sign=_md_sign,
                base_url=DEFAULT_BASE_URL,
                relation_pairs=_md_relation_pairs,
                relation_edges=_md_relation_edges,
                all_row_ids=_md_all_row_ids,
                worksheet_schemas=list(_md_ws_schemas_by_id.values()),
                dry_run=mock_data.get("dry_run", False),
            )
            _md_rel_result_path = _md_result_dir / f"mock_relation_{app_id}_{now_ts()}.json"
            write_json(_md_rel_result_path, _md_rel_result)
            ctx.mock_relation_apply_result_json = str(_md_rel_result_path)
            print(f"  关联处理完成: {_md_rel_result_path}", flush=True)

        with steps_lock:
            steps_report.append({
                "step_id": 9, "step_key": "mock_data_inline",
                "title": "Wave 3.5b 造数+关联",
                "skipped": False,
                "ok": True,
                "result": {
                    "inline_result": str(ctx.mock_data_inline_result_json),
                    "worksheets_written": len(_md_all_row_ids),
                },
            })

    # Wave 4: 并行（icon/布局/造数/机器人/图表规划）
    print(
        f"\n-- Wave 4: icon / 布局 / 造数 / 机器人 / 图表规划（并行） --- 总计 {time.time()-pipeline_start:.0f}s",
        flush=True,
    )

    tableview_filter_result_dir: Path = dirs["tableview_filter_result_dir"]

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
        sem_value = getattr(gemini_semaphore, '_value', 1000)
        cmd5 = [
            sys.executable, str(scripts["layout"]),
            "--app-id", app_id,
            "--semaphore-value", str(sem_value),
        ]
        layout_req = str(ws["layout"].get("requirements", "")).strip()
        if layout_req:
            cmd5.extend(["--requirements", layout_req])
        if execution_dry_run:
            cmd5.append("--dry-run")
        ok5 = _exec(5, "layout", "规划并应用字段布局", cmd5, uses_gemini=True)
        if ok5 and not execution_dry_run:
            layout_stdout = str(steps_report[-1]["result"].get("stdout", ""))
            ctx.worksheet_layout_result_json = _extract_labeled_path(layout_stdout, "结果文件")
        return ok5


    def run_step_9() -> bool:
        # Wave 3.5b 已完成造数，跳过旧流水线
        if ctx.mock_data_inline_result_json:
            with steps_lock:
                steps_report.append({
                    "step_id": 9, "step_key": "mock_data",
                    "title": "执行造数流水线",
                    "skipped": True,
                    "reason": "already_done_in_wave_3.5b",
                    "result": {},
                })
            return True
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

    with ThreadPoolExecutor(max_workers=4) as pool:
        f4 = pool.submit(run_step_4)
        f5 = pool.submit(run_step_5)
        f9 = pool.submit(run_step_9)
        f10 = pool.submit(run_step_10)
        f4.result()
        f5.result()
        f9.result()
        f10.result()

    if _abort_if_failed():
        return ctx

    # Wave 5: 视图筛选
    print(f"\n-- Wave 5: 视图筛选 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)

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
            latest = tableview_filter_result_dir / "tableview_filter_result_latest.json"
            if latest.exists():
                ctx.tableview_filter_result_json = str(latest)
        return ok7

    run_step_7()

    # Wave 6: 清理空名称视图（SaveWorksheetView postCreateUpdates 有时会产生空名称视图作为副作用）
    if not execution_dry_run and delete_default_views_cfg.get("enabled", True):
        print(f"\n-- Wave 6: 清理空名称视图 --- 总计 {time.time()-pipeline_start:.0f}s", flush=True)
        try:
            from delete_default_views import (
                fetch_worksheets as _ddv_fetch_worksheets,
                fetch_views as _ddv_fetch_views,
                delete_view as _ddv_delete_view,
            )
            # 取 appKey/sign
            _ddv_auth = load_json(Path(app_auth_json))
            _ddv_rows = _ddv_auth.get("data", [])
            _ddv_row = next((r for r in _ddv_rows if isinstance(r, dict) and r.get("appId") == app_id), _ddv_rows[0] if _ddv_rows else {})
            _ddv_key = str(_ddv_row.get("appKey", "")).strip()
            _ddv_sign = str(_ddv_row.get("sign", "")).strip()

            _ddv_worksheets = _ddv_fetch_worksheets(_ddv_key, _ddv_sign)
            _ddv_deleted = 0
            for _ddv_ws in _ddv_worksheets:
                _ddv_views = _ddv_fetch_views(_ddv_ws["worksheetId"], _ddv_key, _ddv_sign)
                for _ddv_v in _ddv_views:
                    _ddv_name = str(_ddv_v.get("name", "")).strip()
                    if _ddv_name in ("视图", ""):
                        _ddv_vid = str(_ddv_v.get("viewId", "") or _ddv_v.get("id", "")).strip()
                        if _ddv_vid:
                            ok = _ddv_delete_view(app_id, _ddv_ws["worksheetId"], _ddv_vid, config_web_auth)
                            if ok:
                                _ddv_deleted += 1
                                print(f"  ✓ 清理空名称视图：{_ddv_ws['worksheetName']} → {_ddv_vid}", flush=True)
            print(f"  Wave 6 完成：共清理 {_ddv_deleted} 个空名称视图", flush=True)
        except Exception as _ddv_exc:
            print(f"  ⚠ Wave 6 清理空名称视图失败（非致命）: {_ddv_exc}", flush=True)

    return ctx
