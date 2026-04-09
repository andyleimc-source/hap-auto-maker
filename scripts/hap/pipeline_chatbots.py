#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对话机器人一键流水线：
1. 选择应用并导出结构
2. Gemini 交互式生成 3 个机器人方案
3. 根据确认方案创建机器人
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

from chatbot_common import (
    CHATBOT_CREATE_DIR,
    CHATBOT_PIPELINE_DIR,
    CHATBOT_PLAN_DIR,
    CHATBOT_SCHEMA_DIR,
    append_log,
    ensure_chatbot_dirs,
    make_chatbot_log_path,
    now_iso,
    write_json_with_latest,
)
from i18n import get_runtime_language, normalize_language
from script_locator import resolve_script

SCRIPT_SCHEMA = resolve_script("select_chatbot_app_schema.py")
SCRIPT_PLAN = resolve_script("plan_chatbots_gemini.py")
SCRIPT_CREATE = resolve_script("create_chatbots_from_plan.py")


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


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行对话机器人生成流水线")
    parser.add_argument("--app-id", default="", help="可选，指定 appId")
    parser.add_argument("--app-index", type=int, default=0, help="可选，指定应用序号")
    parser.add_argument("--section-id", default="", help="可选，指定分组 appSectionId")
    parser.add_argument("--section-index", type=int, default=0, help="可选，指定分组序号")
    parser.add_argument("--upload-permission", default="11", help="上传权限，默认 11")
    parser.add_argument("--dry-run-create", action="store_true", help="创建阶段仅 dry-run")
    parser.add_argument("--auto", action="store_true", help="自动确认机器人规划方案，不等待人工审核（用于自动化流水线）")
    parser.add_argument("--language", default="", help="规划语言（zh/en，默认读取 HAP_LANGUAGE）")
    args = parser.parse_args()
    lang = normalize_language(args.language or get_runtime_language())

    ensure_chatbot_dirs()
    pipeline_log = make_chatbot_log_path("chatbot_pipeline")
    append_log(
        pipeline_log,
        "start",
        appId=args.app_id,
        appIndex=args.app_index,
        sectionId=args.section_id,
        sectionIndex=args.section_index,
    )

    schema_output = (CHATBOT_SCHEMA_DIR / "chatbot_app_schema_pipeline.json").resolve()
    plan_output = (CHATBOT_PLAN_DIR / "chatbot_plan_pipeline.json").resolve()
    create_output = (CHATBOT_CREATE_DIR / "chatbot_create_result_pipeline.json").resolve()

    try:
        step1_cmd = [sys.executable, str(SCRIPT_SCHEMA), "--output", str(schema_output)]
        if args.app_id:
            step1_cmd.extend(["--app-id", args.app_id])
        if args.app_index:
            step1_cmd.extend(["--app-index", str(args.app_index)])
        if args.section_id:
            step1_cmd.extend(["--section-id", args.section_id])
        if args.section_index:
            step1_cmd.extend(["--section-index", str(args.section_index)])
        run_step_interactive(step1_cmd, "Step 1/3 导出应用结构", pipeline_log)

        step2_cmd = [
            sys.executable,
            str(SCRIPT_PLAN),
            "--schema-json",
            str(schema_output),
            "--output",
            str(plan_output),
            "--language",
            lang,
        ]
        if args.auto:
            step2_cmd.append("--auto")
            run_step_capture(step2_cmd, "Step 2/3 Gemini 规划机器人（auto）", pipeline_log)
        else:
            run_step_interactive(step2_cmd, "Step 2/3 Gemini 交互式规划机器人", pipeline_log)

        step3_cmd = [
            sys.executable,
            str(SCRIPT_CREATE),
            "--plan-json",
            str(plan_output),
            "--upload-permission",
            args.upload_permission,
            "--output",
            str(create_output),
            "--language",
            lang,
        ]
        if args.dry_run_create:
            step3_cmd.append("--dry-run")
        run_step_capture(step3_cmd, "Step 3/3 创建对话机器人", pipeline_log)

        result = {
            "schemaVersion": "chatbot_pipeline_result_v1",
            "generatedAt": now_iso(),
            "ok": True,
            "artifacts": {
                "schemaJson": str(schema_output),
                "planJson": str(plan_output),
                "createResultJson": str(create_output),
            },
            "pipelineLog": str(pipeline_log),
        }
    except Exception as exc:
        append_log(pipeline_log, "pipeline_failed", error=str(exc))
        result = {
            "schemaVersion": "chatbot_pipeline_result_v1",
            "generatedAt": now_iso(),
            "ok": False,
            "error": str(exc),
            "artifacts": {
                "schemaJson": str(schema_output),
                "planJson": str(plan_output),
                "createResultJson": str(create_output),
            },
            "pipelineLog": str(pipeline_log),
        }

    output_path = (CHATBOT_PIPELINE_DIR / "chatbot_pipeline_result.json").resolve()
    write_json_with_latest(
        CHATBOT_PIPELINE_DIR,
        output_path,
        "chatbot_pipeline_result_latest.json",
        result,
    )

    print("\n流水线执行结束")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n结果文件: {output_path}")
    print(f"日志文件: {pipeline_log}")
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {pipeline_log}")
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
