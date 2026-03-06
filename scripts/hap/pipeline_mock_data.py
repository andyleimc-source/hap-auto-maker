#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 造数总流水线。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import (
    DEFAULT_BASE_URL,
    DEFAULT_GEMINI_MODEL,
    MOCK_BUNDLE_DIR,
    MOCK_PLAN_DIR,
    MOCK_RELATION_REPAIR_APPLY_DIR,
    MOCK_RELATION_REPAIR_PLAN_DIR,
    MOCK_RUN_DIR,
    MOCK_SCHEMA_DIR,
    MOCK_UNRESOLVED_DELETE_DIR,
    MOCK_WRITE_RESULT_DIR,
    append_log,
    choose_app,
    discover_authorized_apps,
    load_json,
    make_log_path,
    make_output_path,
    now_iso,
    now_ts,
    write_json,
)

BASE_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = BASE_DIR / "scripts"
SCRIPT_EXPORT_SCHEMA = SCRIPTS_DIR / "export_app_mock_schema.py"
SCRIPT_PLAN_DATA = SCRIPTS_DIR / "plan_mock_data_gemini.py"
SCRIPT_WRITE_DATA = SCRIPTS_DIR / "write_mock_data_from_plan.py"
SCRIPT_ANALYZE_REL = SCRIPTS_DIR / "analyze_relation_consistency.py"
SCRIPT_APPLY_REL = SCRIPTS_DIR / "apply_relation_repair_plan.py"
SCRIPT_DELETE_UNRESOLVED = SCRIPTS_DIR / "delete_unresolved_records.py"


def run_step(cmd: List[str], title: str, log_path: Path) -> Dict[str, object]:
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
    append_log(
        log_path,
        "step_finished",
        title=title,
        cmd=cmd,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
    return {"cmd": cmd, "stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}


def extract_file_path(output: str) -> Optional[str]:
    for line in reversed((output or "").splitlines()):
        line = line.strip()
        if "日志文件:" in line:
            continue
        if "结果文件:" in line or "文件:" in line:
            return line.split(":", 1)[1].strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行 HAP 造数总流程")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--model", default=DEFAULT_GEMINI_MODEL, help="Gemini 模型名")
    parser.add_argument("--dry-run", action="store_true", help="写入与更新步骤使用 dry-run")
    parser.add_argument("--trigger-workflow", action="store_true", help="写入与更新时触发工作流")
    args = parser.parse_args()

    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id, app_index=args.app_index)
    log_path = make_log_path("pipeline_mock_data", app["appId"])
    append_log(
        log_path,
        "start",
        appId=app["appId"],
        appName=app["appName"],
        dryRun=bool(args.dry_run),
        triggerWorkflow=bool(args.trigger_workflow),
        model=args.model,
    )
    context: Dict[str, object] = {
        "app": {"appId": app["appId"], "appName": app["appName"]},
        "artifacts": {},
        "steps": [],
        "logFile": str(log_path),
    }
    unresolved_count = 0
    delete_count = 0

    try:
        schema_json = str(make_output_path(MOCK_SCHEMA_DIR, "mock_schema_snapshot", app["appId"]))
        export_cmd = [
            sys.executable,
            str(SCRIPT_EXPORT_SCHEMA),
            "--app-id",
            app["appId"],
            "--base-url",
            args.base_url,
            "--output",
            schema_json,
        ]
        export_result = run_step(export_cmd, "Step 1/6 导出结构快照", log_path)
        context["steps"].append({"step": "export_schema", "ok": True, "schemaJson": schema_json})
        context["artifacts"]["schema_json"] = schema_json

        plan_json = str(make_output_path(MOCK_PLAN_DIR, "mock_data_plan", app["appId"]))
        bundle_json = str(make_output_path(MOCK_BUNDLE_DIR, "mock_data_bundle", app["appId"]))
        plan_cmd = [
            sys.executable,
            str(SCRIPT_PLAN_DATA),
            "--schema-json",
            str(schema_json),
            "--model",
            args.model,
            "--plan-output",
            plan_json,
            "--bundle-output",
            bundle_json,
        ]
        plan_result = run_step(plan_cmd, "Step 2/6 规划造数", log_path)
        context["steps"].append({"step": "plan_mock_data", "ok": True, "plan_json": plan_json, "bundle_json": bundle_json})
        context["artifacts"].update({"plan_json": plan_json, "bundle_json": bundle_json})

        write_json_path = str(make_output_path(MOCK_WRITE_RESULT_DIR, "mock_data_write_result", app["appId"]))
        write_cmd = [
            sys.executable,
            str(SCRIPT_WRITE_DATA),
            "--bundle-json",
            bundle_json,
            "--app-id",
            app["appId"],
            "--base-url",
            args.base_url,
            "--output",
            write_json_path,
        ]
        if args.dry_run:
            write_cmd.append("--dry-run")
        if args.trigger_workflow:
            write_cmd.append("--trigger-workflow")
        write_result = run_step(write_cmd, "Step 3/6 写入造数", log_path)
        context["steps"].append({"step": "write_mock_data", "ok": True, "write_result_json": write_json_path})
        context["artifacts"]["write_result_json"] = write_json_path

        relation_plan_json = str(make_output_path(MOCK_RELATION_REPAIR_PLAN_DIR, "mock_relation_repair_plan", app["appId"]))
        relation_plan_cmd = [
            sys.executable,
            str(SCRIPT_ANALYZE_REL),
            "--schema-json",
            str(schema_json),
            "--write-result-json",
            str(write_json_path),
            "--app-id",
            app["appId"],
            "--base-url",
            args.base_url,
            "--model",
            args.model,
            "--output",
            relation_plan_json,
        ]
        relation_plan_result = run_step(relation_plan_cmd, "Step 4/6 分析关联一致性", log_path)
        context["steps"].append({"step": "analyze_relation_consistency", "ok": True, "repair_plan_json": relation_plan_json})
        context["artifacts"]["repair_plan_json"] = relation_plan_json
        repair_plan = load_json(Path(relation_plan_json))
        unresolved_count = int(repair_plan.get("summary", {}).get("unresolvedCount", 0) or 0)
        append_log(log_path, "repair_plan_summary", summary=repair_plan.get("summary", {}))

        relation_apply_json = str(make_output_path(MOCK_RELATION_REPAIR_APPLY_DIR, "mock_relation_repair_apply_result", app["appId"]))
        apply_cmd = [
            sys.executable,
            str(SCRIPT_APPLY_REL),
            "--repair-plan-json",
            str(relation_plan_json),
            "--app-id",
            app["appId"],
            "--base-url",
            args.base_url,
            "--output",
            relation_apply_json,
        ]
        if args.dry_run:
            apply_cmd.append("--dry-run")
        if args.trigger_workflow:
            apply_cmd.append("--trigger-workflow")
        apply_result = run_step(apply_cmd, "Step 5/6 应用关联修复", log_path)
        context["steps"].append({"step": "apply_relation_repair", "ok": True, "relation_apply_json": relation_apply_json})
        context["artifacts"]["relation_apply_json"] = relation_apply_json
        apply_result_data = load_json(Path(relation_apply_json))
        unresolved_count = int(apply_result_data.get("summary", {}).get("unresolvedCount", 0) or 0)
        if unresolved_count > 0:
            delete_result_json = str(make_output_path(MOCK_UNRESOLVED_DELETE_DIR, "mock_unresolved_delete_result", app["appId"]))
            delete_cmd = [
                sys.executable,
                str(SCRIPT_DELETE_UNRESOLVED),
                "--repair-apply-result-json",
                relation_apply_json,
                "--app-id",
                app["appId"],
                "--base-url",
                args.base_url,
                "--output",
                delete_result_json,
            ]
            if args.dry_run:
                delete_cmd.append("--dry-run")
            delete_result = run_step(delete_cmd, "Step 6/6 删除 unresolved 记录", log_path)
            context["steps"].append({"step": "delete_unresolved_records", "ok": True, "delete_result_json": delete_result_json})
            context["artifacts"]["delete_result_json"] = delete_result_json
            delete_result_data = load_json(Path(delete_result_json))
            delete_count = int(delete_result_data.get("summary", {}).get("deleteSuccessCount", 0) or 0)
            append_log(log_path, "delete_unresolved_summary", summary=delete_result_data.get("summary", {}))
        else:
            context["steps"].append({"step": "delete_unresolved_records", "ok": True, "skipped": True, "reason": "no_unresolved"})
    except Exception as exc:
        context["error"] = str(exc)
        context["ok"] = False
        append_log(log_path, "pipeline_failed", error=str(exc), artifacts=context["artifacts"])
    else:
        context["ok"] = True
        context["deletedUnresolvedCount"] = delete_count
        context["partial"] = False
        if unresolved_count > 0:
            context["warning"] = f"已执行可修复关联，并删除 unresolved 源记录 {delete_count} 条"
            append_log(
                log_path,
                "pipeline_cleanup",
                unresolvedCount=unresolved_count,
                deletedUnresolvedCount=delete_count,
                artifacts=context["artifacts"],
            )
        else:
            append_log(log_path, "pipeline_succeeded", artifacts=context["artifacts"])

    report = {
        "schemaVersion": "mock_data_run_v1",
        "createdAt": now_iso(),
        "dryRun": bool(args.dry_run),
        "triggerWorkflow": bool(args.trigger_workflow),
        **context,
    }
    MOCK_RUN_DIR.mkdir(parents=True, exist_ok=True)
    report_path = (MOCK_RUN_DIR / f"mock_data_run_{app['appId']}_{now_ts()}.json").resolve()
    write_json(report_path, report)
    write_json((MOCK_RUN_DIR / "mock_data_run_latest.json").resolve(), report)
    append_log(log_path, "finished", reportFile=str(report_path), ok=report["ok"])

    print("\n总流程结束")
    print(f"- 应用: {app['appName']} ({app['appId']})")
    if report.get("ok") and report.get("partial"):
        print("- 状态: 部分成功")
    else:
        print(f"- 状态: {'成功' if report['ok'] else '失败'}")
    print(f"- 日志文件: {log_path}")
    print(f"- 报告: {report_path}")
    print(json.dumps(report["artifacts"], ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
