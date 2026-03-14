#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流一键流水线：
1. 选择应用并导出 schema
2. 用 Gemini 生成 3 个工作流规划
3. 根据 plan 生成工作流请求或实际创建
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from workflow_common import (
    GEMINI_CONFIG_PATH,
    WORKFLOW_CREATE_DIR,
    WORKFLOW_PIPELINE_DIR,
    WORKFLOW_PLAN_DIR,
    WORKFLOW_SCHEMA_DIR,
    append_log,
    ensure_workflow_dirs,
    extract_result_json,
    make_workflow_log_path,
    make_workflow_output_path,
    now_iso,
    write_json_with_latest,
)

BASE_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = BASE_DIR / "scripts"
SCRIPT_EXPORT = SCRIPTS_DIR / "export_workflow_schema.py"
SCRIPT_PLAN = SCRIPTS_DIR / "plan_workflows_gemini.py"
SCRIPT_CREATE = SCRIPTS_DIR / "create_workflows_from_plan.py"


def run_step_capture(cmd: List[str], title: str, log_path: Path) -> str:
    print(f"\n== {title} ==")
    print("命令:", " ".join(cmd))
    append_log(log_path, "step_start", title=title, cmd=cmd)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr.strip():
            print(proc.stderr.strip())
        append_log(
            log_path,
            "step_failed",
            title=title,
            cmd=cmd,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
        raise RuntimeError(f"{title} 失败，退出码: {proc.returncode}")
    append_log(log_path, "step_finished", title=title, cmd=cmd, returncode=proc.returncode)
    return proc.stdout


def run_step_interactive(cmd: List[str], title: str, log_path: Path) -> None:
    print(f"\n== {title} ==")
    print("命令:", " ".join(cmd))
    append_log(log_path, "step_start", title=title, cmd=cmd)
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        append_log(log_path, "step_failed", title=title, cmd=cmd, returncode=proc.returncode)
        raise RuntimeError(f"{title} 失败，退出码: {proc.returncode}")
    append_log(log_path, "step_finished", title=title, cmd=cmd, returncode=proc.returncode)


def print_plan_summary(plan_path: Path) -> None:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:
        print(f"- 规划文件: {plan_path}")
        return
    print("\n规划摘要：")
    print(f"- 应用: {plan.get('app', {}).get('appName', '')} ({plan.get('app', {}).get('appId', '')})")
    for workflow in plan.get("workflows", []) or []:
        if not isinstance(workflow, dict):
            continue
        trigger = workflow.get("trigger", {}) if isinstance(workflow.get("trigger"), dict) else {}
        print(
            f"- {workflow.get('key', '')}: {workflow.get('name', '')} | "
            f"trigger={trigger.get('type', '')}/{trigger.get('event', '')} | "
            f"worksheet={trigger.get('worksheetName', '')}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行工作流 schema 导出、Gemini 规划、创建")
    parser.add_argument("--app-id", default="", help="指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="指定应用序号")
    parser.add_argument("--schema-json", default="", help="跳过导出，直接使用现有 schema JSON")
    parser.add_argument("--plan-json", default="", help="跳过规划，直接使用现有 plan JSON")
    parser.add_argument("--model", default="gemini-2.5-pro", help="Gemini 模型名")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--base-url", default="https://api.mingdao.com", help="API 基础地址")
    parser.add_argument("--stop-after-plan", action="store_true", help="规划完成后停止，不进入创建")
    parser.add_argument("--dry-run", action="store_true", help="创建阶段仅生成请求草稿")
    parser.add_argument("--schema-output", default="", help="schema 输出路径")
    parser.add_argument("--plan-output", default="", help="plan 输出路径")
    parser.add_argument("--create-output", default="", help="create 输出路径")
    args = parser.parse_args()

    ensure_workflow_dirs()
    pipeline_log = make_workflow_log_path("workflow_pipeline", args.app_id)
    append_log(
        pipeline_log,
        "start",
        appId=args.app_id,
        appIndex=args.app_index,
        schemaJson=args.schema_json,
        planJson=args.plan_json,
        model=args.model,
        dryRun=bool(args.dry_run),
        stopAfterPlan=bool(args.stop_after_plan),
    )

    schema_output = Path(args.schema_output).expanduser().resolve() if args.schema_output else (WORKFLOW_SCHEMA_DIR / "workflow_schema_snapshot_pipeline.json").resolve()
    plan_output = Path(args.plan_output).expanduser().resolve() if args.plan_output else (WORKFLOW_PLAN_DIR / "workflow_plan_pipeline.json").resolve()
    create_output = Path(args.create_output).expanduser().resolve() if args.create_output else (WORKFLOW_CREATE_DIR / "workflow_create_result_pipeline.json").resolve()

    schema_json = str(Path(args.schema_json).expanduser().resolve()) if args.schema_json else ""
    plan_json = str(Path(args.plan_json).expanduser().resolve()) if args.plan_json else ""
    create_json = ""
    ok = False
    error = ""

    try:
        if plan_json:
            append_log(
                pipeline_log,
                "step_skipped",
                title="Step 1/3 导出工作流 schema",
                reason="使用 --plan-json，直接跳过 schema 导出",
            )
        elif not schema_json:
            step1_cmd = [
                sys.executable,
                str(SCRIPT_EXPORT),
                "--base-url",
                args.base_url,
                "--output",
                str(schema_output),
            ]
            if args.app_id:
                step1_cmd.extend(["--app-id", args.app_id])
            if args.app_index:
                step1_cmd.extend(["--app-index", str(args.app_index)])
            run_step_interactive(step1_cmd, "Step 1/3 导出工作流 schema", pipeline_log)
            schema_json = str(schema_output)
        else:
            append_log(pipeline_log, "step_skipped", title="Step 1/3 导出工作流 schema", reason="使用 --schema-json")

        if not plan_json:
            step2_cmd = [
                sys.executable,
                str(SCRIPT_PLAN),
                "--schema-json",
                schema_json,
                "--model",
                args.model,
                "--config",
                str(Path(args.config).expanduser().resolve()),
                "--output",
                str(plan_output),
            ]
            plan_stdout = run_step_capture(step2_cmd, "Step 2/3 Gemini 规划工作流", pipeline_log)
            plan_json = extract_result_json(plan_stdout) or str(plan_output)
        else:
            append_log(pipeline_log, "step_skipped", title="Step 2/3 Gemini 规划工作流", reason="使用 --plan-json")

        print_plan_summary(Path(plan_json))
        if args.stop_after_plan:
            ok = True
            append_log(pipeline_log, "pipeline_stopped_after_plan", planJson=plan_json)
        else:
            step3_cmd = [
                sys.executable,
                str(SCRIPT_CREATE),
                "--plan-json",
                plan_json,
                "--output",
                str(create_output),
            ]
            if args.dry_run:
                step3_cmd.append("--dry-run")
            create_stdout = run_step_capture(step3_cmd, "Step 3/3 创建工作流", pipeline_log)
            create_json = extract_result_json(create_stdout) or str(create_output)
            ok = True
    except Exception as exc:
        error = str(exc)
        ok = False
        append_log(pipeline_log, "pipeline_failed", error=error, schemaJson=schema_json, planJson=plan_json, createJson=create_json)

    report = {
        "schemaVersion": "workflow_pipeline_run_v1",
        "createdAt": now_iso(),
        "ok": ok,
        "error": error,
        "artifacts": {
            "schemaJson": schema_json,
            "planJson": plan_json,
            "createResultJson": create_json,
        },
        "stopAfterPlan": bool(args.stop_after_plan),
        "dryRun": bool(args.dry_run),
        "logFile": str(pipeline_log),
    }
    report_path = make_workflow_output_path(WORKFLOW_PIPELINE_DIR, "workflow_pipeline_run", args.app_id or "general")
    write_json_with_latest(WORKFLOW_PIPELINE_DIR, report_path, "workflow_pipeline_run_latest.json", report)
    append_log(pipeline_log, "finished", output=str(report_path), ok=ok)

    print("\n工作流流水线结束")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n结果文件: {report_path}")
    print(f"日志文件: {pipeline_log}")
    print(f"RESULT_JSON: {report_path}")
    print(f"LOG_FILE: {pipeline_log}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
