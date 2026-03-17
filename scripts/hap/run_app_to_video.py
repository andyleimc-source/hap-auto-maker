#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键串联：需求对话 → 应用创建 → 全流程执行，并将关键产物归档到单次运行目录。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from script_locator import resolve_script

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_RUNS_DIR = OUTPUT_ROOT / "app_runs"
REQUIREMENT_SPEC_LATEST = OUTPUT_ROOT / "requirement_specs" / "requirement_spec_latest.json"
EXECUTION_RUN_LATEST = OUTPUT_ROOT / "execution_runs" / "execution_run_latest.json"
AGENT_COLLECT_SCRIPT = resolve_script("agent_collect_requirements.py")


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def assert_recent(path: Path, not_before_epoch: float, label: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{label} 不存在: {path}")
    if path.stat().st_mtime < (not_before_epoch - 1):
        raise RuntimeError(f"{label} 不是本次运行新产物，疑似仍在使用旧文件: {path}")
    return path.resolve()


def run_command(
    cmd: List[str],
    cwd: Path,
    interactive: bool = False,
    stdin_text: str = "",
) -> Dict[str, Any]:
    started_at = now_iso()
    started_epoch = time.time()
    if interactive:
        proc = subprocess.run(cmd, cwd=str(cwd), check=False, input=stdin_text or None, text=bool(stdin_text))
        return {
            "cmd": cmd,
            "cwd": str(cwd),
            "interactive": True,
            "started_at": started_at,
            "ended_at": now_iso(),
            "duration_seconds": round(time.time() - started_epoch, 3),
            "returncode": proc.returncode,
            "stdout": "",
            "stderr": "",
        }

    proc = subprocess.run(
        cmd, cwd=str(cwd), check=False, capture_output=True, text=True, input=stdin_text or None,
    )
    return {
        "cmd": cmd,
        "cwd": str(cwd),
        "interactive": False,
        "started_at": started_at,
        "ended_at": now_iso(),
        "duration_seconds": round(time.time() - started_epoch, 3),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def safe_copy(src: Optional[str | Path], dst: Path) -> Optional[str]:
    if not src:
        return None
    source = Path(src).expanduser().resolve()
    if not source.exists():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dst)
    return str(dst.resolve())


def collect_artifact_sources(execution_report: dict) -> Dict[str, str]:
    context = execution_report.get("context") if isinstance(execution_report.get("context"), dict) else {}
    keys = [
        "app_auth_json",
        "worksheet_plan_json",
        "worksheet_create_result_json",
        "worksheet_layout_plan_json",
        "worksheet_layout_apply_result_json",
        "view_plan_json",
        "view_create_result_json",
        "tableview_filter_plan_json",
        "tableview_filter_apply_result_json",
        "mock_data_run_json",
        "chatbot_pipeline_result_json",
        "workflow_plan_json",
        "workflow_execute_result_json",
    ]
    out: Dict[str, str] = {}
    for key in keys:
        value = str(context.get(key, "")).strip()
        if value:
            out[key] = value
    return out


def count_fields_from_layout_plan(layout_plan: dict) -> int:
    total = 0
    for worksheet in layout_plan.get("worksheets", []) if isinstance(layout_plan.get("worksheets"), list) else []:
        if not isinstance(worksheet, dict):
            continue
        fields = worksheet.get("fields")
        if not isinstance(fields, list):
            fields = worksheet.get("controls")
        if isinstance(fields, list):
            total += len(fields)
    return total


def get_worksheet_names(layout_plan: Optional[dict], worksheet_create_result: Optional[dict]) -> List[str]:
    names: List[str] = []
    if isinstance(layout_plan, dict):
        for ws in layout_plan.get("worksheets", []) if isinstance(layout_plan.get("worksheets"), list) else []:
            if isinstance(ws, dict):
                name = str(ws.get("workSheetName", "") or ws.get("worksheetName", "")).strip()
                if name:
                    names.append(name)
    if names:
        return names
    if isinstance(worksheet_create_result, dict):
        for ws in worksheet_create_result.get("created_worksheets", []) if isinstance(worksheet_create_result.get("created_worksheets"), list) else []:
            if isinstance(ws, dict):
                name = str(ws.get("name", "")).strip()
                if name:
                    names.append(name)
    return names


def format_seconds(seconds: Optional[float]) -> str:
    if seconds is None:
        return "未知"
    return f"{seconds:.3f} 秒"


def build_summary_md(
    app_id: str,
    app_name: str,
    conversation_summary: str,
    app_entry_url: str,
    worksheet_names: List[str],
    stats: Dict[str, Any],
    artifact_paths: Dict[str, Any],
) -> str:
    lines = [
        "# 本次运行摘要",
        "",
        "## 1. 入口",
        f"- 应用入口: {app_entry_url}",
        "",
        "## 2. 应用信息",
        f"- 应用名称: {app_name}",
        f"- 应用 ID: {app_id}",
        f"- 功能摘要: {conversation_summary or '无'}",
        f"- 工作表清单: {', '.join(worksheet_names) if worksheet_names else '无'}",
        f"- 已创建视图数: {stats.get('created_view_count', 0)}",
        f"- 是否执行造数: {'是' if stats.get('mock_data_enabled') else '否'}",
        "",
        "## 3. 运行日志",
        f"- 总运行时长: {format_seconds(stats.get('total_duration_seconds'))}",
        f"- 工作表数量: {stats.get('worksheet_count', 0)}",
        f"- 字段数量: {stats.get('field_count', 0)}",
        f"- 视图数量: {stats.get('created_view_count', 0)} / 规划视图数量: {stats.get('planned_view_count', 0)}",
        f"- 造数结果: {stats.get('mock_data_summary', '未执行')}",
        "- 关键产物路径:",
    ]
    for key, value in artifact_paths.items():
        lines.append(f"  - {key}: {value}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="一键从需求沟通到应用全流程执行")
    parser.add_argument("--requirements-text", default="", help="可选，非交互模式下直接提供需求文本")
    parser.add_argument("--resume-latest", action="store_true", help="跳过需求采集，直接从最新成功的 execution report 继续")
    parser.add_argument("--skip-recording", action="store_true", default=False, help="跳过 Playwright 录屏（由 run_app_pipeline.py 默认传入）")
    args = parser.parse_args()

    started_at = now_iso()
    started_epoch = time.time()
    run_stamp = now_ts()
    pending_dir = (APP_RUNS_DIR / f"{run_stamp}_pending").resolve()
    pending_dir.mkdir(parents=True, exist_ok=True)
    run_dir = pending_dir

    tech_log: Dict[str, Any] = {
        "run_metadata": {
            "started_at": started_at,
            "cwd": str(BASE_DIR.resolve()),
            "python": sys.executable,
            "run_dir": str(run_dir),
            "script": str(Path(__file__).resolve()),
        },
        "app_metadata": {},
        "requirement_metadata": {},
        "pipeline_artifacts": {},
        "aggregate_stats": {},
        "commands": [],
        "error_context": None,
    }

    spec_data: Optional[dict] = None
    execution_data: Optional[dict] = None
    app_id = ""
    app_name = ""
    app_entry_url = ""
    summary_md = ""
    try:
        if args.resume_latest:
            spec_path = REQUIREMENT_SPEC_LATEST.resolve()
            execution_path = EXECUTION_RUN_LATEST.resolve()
        else:
            step1_started = time.time()
            cmd1 = [sys.executable, str(AGENT_COLLECT_SCRIPT.resolve())]
            stdin_text = ""
            if str(args.requirements_text).strip():
                stdin_text = args.requirements_text.strip() + "\n/done\n"
            result1 = run_command(cmd1, cwd=BASE_DIR, interactive=True, stdin_text=stdin_text)
            result1["name"] = "agent_collect_requirements"
            tech_log["commands"].append(result1)
            if result1["returncode"] != 0:
                raise RuntimeError("步骤1失败：需求采集或自动执行未成功完成。")

            spec_path = assert_recent(REQUIREMENT_SPEC_LATEST, step1_started, "requirement_spec_latest.json")
            execution_path = assert_recent(EXECUTION_RUN_LATEST, step1_started, "execution_run_latest.json")

        spec_data = load_json(spec_path)
        execution_data = load_json(execution_path)
        failed_steps = int(execution_data.get("summary", {}).get("failed", 0) or 0)
        if failed_steps > 0:
            raise RuntimeError(
                f"需求执行阶段失败，execution report 显示 failed={failed_steps}。"
            )

        context = execution_data.get("context") if isinstance(execution_data.get("context"), dict) else {}
        app_id = str(context.get("app_id", "")).strip()
        if not app_id:
            raise RuntimeError("execution_run_latest.json 缺少 context.app_id。")
        app_name = str(spec_data.get("app", {}).get("name", "")).strip() or app_id
        app_entry_url = f"https://www.mingdao.com/app/{app_id}"

        final_dir = (APP_RUNS_DIR / f"{run_stamp}_{app_id}").resolve()
        if run_dir != final_dir:
            if final_dir.exists():
                raise FileExistsError(f"目标运行目录已存在: {final_dir}")
            run_dir.rename(final_dir)
            run_dir = final_dir
            tech_log["run_metadata"]["run_dir"] = str(run_dir)

        copied_spec = safe_copy(spec_path, run_dir / "requirement_spec.json")
        copied_execution = safe_copy(execution_path, run_dir / "execution_run.json")

        tech_log["app_metadata"] = {
            "appId": app_id,
            "appName": app_name,
            "appEntryUrl": app_entry_url,
        }
        tech_log["requirement_metadata"] = {
            "spec_path": copied_spec or str(spec_path),
            "execution_run_path": copied_execution or str(execution_path),
            "conversation_summary": str(spec_data.get("meta", {}).get("conversation_summary", "")).strip(),
            "execution_mode": str(spec_data.get("app", {}).get("target_mode", "")).strip() or "create_new",
        }

        # Archive pipeline artifacts
        artifact_sources = collect_artifact_sources(execution_data)
        copied_artifacts: Dict[str, str] = {}
        for key, value in artifact_sources.items():
            copied = safe_copy(value, run_dir / "artifacts" / Path(value).name)
            if copied:
                copied_artifacts[key] = copied

        layout_plan = load_json(Path(artifact_sources["worksheet_layout_plan_json"])) if artifact_sources.get("worksheet_layout_plan_json") else {}
        worksheet_create_result = load_json(Path(artifact_sources["worksheet_create_result_json"])) if artifact_sources.get("worksheet_create_result_json") else {}
        view_create_result = load_json(Path(artifact_sources["view_create_result_json"])) if artifact_sources.get("view_create_result_json") else {}
        mock_data_run = load_json(Path(artifact_sources["mock_data_run_json"])) if artifact_sources.get("mock_data_run_json") else {}

        worksheet_names = get_worksheet_names(layout_plan, worksheet_create_result)
        worksheet_count = len(worksheet_names)
        if not worksheet_count:
            worksheet_count = len(layout_plan.get("worksheets", []) if isinstance(layout_plan.get("worksheets"), list) else [])
        if not worksheet_count and isinstance(worksheet_create_result, dict):
            worksheet_count = len(worksheet_create_result.get("created_worksheets", []) if isinstance(worksheet_create_result.get("created_worksheets"), list) else [])

        field_count = count_fields_from_layout_plan(layout_plan)
        view_summary = view_create_result.get("summary") if isinstance(view_create_result.get("summary"), dict) else {}
        planned_view_count = int(view_summary.get("plannedViewCount", 0) or 0)
        created_view_count = int(view_summary.get("createdViewCount", 0) or 0)

        # 工作流数量
        workflow_count = 0
        if artifact_sources.get("workflow_execute_result_json"):
            try:
                wf_result = load_json(Path(artifact_sources["workflow_execute_result_json"]))
                workflow_count = (
                    len(wf_result.get("workflows", []))
                    or len(wf_result.get("results", []))
                    or int(wf_result.get("total", 0) or 0)
                )
            except Exception:
                pass

        mock_data_enabled = bool(artifact_sources.get("mock_data_run_json"))
        if mock_data_enabled and isinstance(mock_data_run, dict):
            mock_data_summary = (
                f"ok={mock_data_run.get('ok')} "
                f"partial={mock_data_run.get('partial')} "
                f"deletedUnresolvedCount={mock_data_run.get('deletedUnresolvedCount', 0)}"
            )
        else:
            mock_data_summary = "未执行"

        total_duration_seconds = round(time.time() - started_epoch, 3)
        tech_log["pipeline_artifacts"] = {
            "requirement_spec_json": copied_spec,
            "execution_run_json": copied_execution,
            **copied_artifacts,
        }
        tech_log["aggregate_stats"] = {
            "worksheet_count": worksheet_count,
            "field_count": field_count,
            "planned_view_count": planned_view_count,
            "created_view_count": created_view_count,
            "total_duration_seconds": total_duration_seconds,
            "mock_data_enabled": mock_data_enabled,
            "mock_data_summary": mock_data_summary,
        }

        summary_artifact_paths: Dict[str, Any] = {
            "requirement_spec": copied_spec,
            "execution_run": copied_execution,
            **copied_artifacts,
        }
        summary_md = build_summary_md(
            app_id=app_id,
            app_name=app_name,
            conversation_summary=tech_log["requirement_metadata"]["conversation_summary"],
            app_entry_url=app_entry_url,
            worksheet_names=worksheet_names,
            stats={
                **tech_log["aggregate_stats"],
                "mock_data_enabled": mock_data_enabled,
            },
            artifact_paths=summary_artifact_paths,
        )
        write_text(run_dir / "summary.md", summary_md)

    except Exception as exc:
        tech_log["error_context"] = {
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        raise
    finally:
        tech_log["run_metadata"]["ended_at"] = now_iso()
        tech_log["run_metadata"]["total_duration_seconds"] = round(time.time() - started_epoch, 3)
        if app_id:
            tech_log["app_metadata"].setdefault("appId", app_id)
            tech_log["app_metadata"].setdefault("appName", app_name or app_id)
            tech_log["app_metadata"].setdefault("appEntryUrl", app_entry_url)

        write_json(run_dir / "tech_log.json", tech_log)
        if summary_md:
            stats = tech_log.get("aggregate_stats", {})
            dur = int(stats.get("total_duration_seconds", 0))
            mins, secs = divmod(dur, 60)
            dur_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            w = 52
            def row(label, value):
                content = f"  {label:<10}{value}"
                return f"│{content:<{w}}│"
            print("\n┌" + "─" * w + "┐")
            title = f"  ✓ 运行完成  {app_name}"
            print(f"│{title:<{w}}│")
            print("├" + "─" * w + "┤")
            print(row("应用地址", app_entry_url))
            print(row("工作表", f"{stats.get('worksheet_count', 0)} 张"))
            print(row("视图", f"{stats.get('created_view_count', 0)} 个"))
            print(row("工作流", f"{workflow_count} 个"))
            print(row("总耗时", dur_str))
            print("└" + "─" * w + "┘")
        elif tech_log.get("error_context"):
            print(f"\n✗ 运行失败，排障日志: {run_dir / 'tech_log.json'}")


if __name__ == "__main__":
    main()
