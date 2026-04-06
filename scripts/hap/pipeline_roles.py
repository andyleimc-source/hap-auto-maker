#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推荐角色并创建角色的一键流水线。
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
    OUTPUT_ROOT,
    append_log,
    choose_app,
    discover_authorized_apps,
    ensure_dir,
    make_log_path,
    now_iso,
    now_ts,
    write_json,
)
from script_locator import resolve_script
from ai_utils import load_ai_config

BASE_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PLAN = resolve_script("plan_role_recommendations_gemini.py")
SCRIPT_CREATE = resolve_script("create_roles_from_recommendation.py")
ROLE_RUN_DIR = OUTPUT_ROOT / "role_runs"


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
    return {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode}


def extract_marker_path(output: str, marker: str) -> Optional[str]:
    for line in reversed((output or "").splitlines()):
        text = line.strip()
        if text.startswith(marker):
            return text.split(":", 1)[1].strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行推荐角色与角色创建")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="创建时角色已存在则跳过（默认启用）")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false", help="创建时不跳过已有角色")
    args = parser.parse_args()

    ai_config = load_ai_config()
    model_name = ai_config["model"]

    apps = discover_authorized_apps(base_url=args.base_url)
    app = choose_app(apps, app_id=args.app_id, app_index=args.app_index)
    log_path = make_log_path("pipeline_roles", app["appId"])
    append_log(
        log_path,
        "start",
        appId=app["appId"],
        appName=app["appName"],
        model=model_name,
        skipExisting=bool(args.skip_existing),
    )

    context: Dict[str, object] = {
        "app": {"appId": app["appId"], "appName": app["appName"]},
        "artifacts": {},
        "steps": [],
        "logFile": str(log_path),
    }

    try:
        plan_cmd = [
            sys.executable,
            str(SCRIPT_PLAN),
            "--app-id",
            app["appId"],
            "--base-url",
            args.base_url,
        ]
        plan_result = run_step(plan_cmd, "Step 1/2 生成推荐角色", log_path)
        plan_json = extract_marker_path(str(plan_result.get("stdout", "")), "RESULT_JSON")
        if not plan_json:
            raise RuntimeError("Step 1 未输出 RESULT_JSON")
        context["steps"].append({"step": "plan_roles", "ok": True, "planJson": plan_json})
        context["artifacts"]["plan_json"] = plan_json

        create_cmd = [
            sys.executable,
            str(SCRIPT_CREATE),
            "--plan-json",
            plan_json,
            "--app-id",
            app["appId"],
            "--base-url",
            args.base_url,
        ]
        if args.skip_existing:
            create_cmd.append("--skip-existing")
        else:
            create_cmd.append("--no-skip-existing")
        create_result = run_step(create_cmd, "Step 2/2 创建角色", log_path)
        create_json = extract_marker_path(str(create_result.get("stdout", "")), "RESULT_JSON")
        if not create_json:
            raise RuntimeError("Step 2 未输出 RESULT_JSON")
        context["steps"].append({"step": "create_roles", "ok": True, "createResultJson": create_json})
        context["artifacts"]["create_result_json"] = create_json
    except Exception as exc:
        context["ok"] = False
        context["error"] = str(exc)
        append_log(log_path, "pipeline_failed", error=str(exc), artifacts=context["artifacts"])
    else:
        context["ok"] = True
        append_log(log_path, "pipeline_succeeded", artifacts=context["artifacts"])

    report = {
        "schemaVersion": "role_pipeline_run_v1",
        "createdAt": now_iso(),
        **context,
    }
    ensure_dir(ROLE_RUN_DIR)
    report_path = (ROLE_RUN_DIR / f"role_pipeline_run_{app['appId']}_{now_ts()}.json").resolve()
    write_json(report_path, report)
    write_json((ROLE_RUN_DIR / "role_pipeline_run_latest.json").resolve(), report)
    append_log(log_path, "finished", reportFile=str(report_path), ok=bool(report.get("ok")))

    print("\n角色流水线执行结束")
    print(f"- 应用: {app['appName']} ({app['appId']})")
    print(f"- 状态: {'成功' if report.get('ok') else '失败'}")
    print(f"- 日志文件: {log_path}")
    print(f"- 报告文件: {report_path}")
    print(json.dumps(report.get("artifacts", {}), ensure_ascii=False, indent=2))
    if not report.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
