#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图流水线：
1) 规划视图（Gemini）
2) 创建视图（执行规划 JSON）
"""

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
PLAN_SCRIPT = BASE_DIR / "scripts" / "plan_worksheet_views_gemini.py"
CREATE_SCRIPT = BASE_DIR / "scripts" / "create_views_from_plan.py"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
VIEW_PLAN_DIR = OUTPUT_ROOT / "view_plans"
VIEW_CREATE_RESULT_DIR = OUTPUT_ROOT / "view_create_results"
DEFAULT_MODEL = "gemini-2.5-pro"
DEFAULT_GEMINI_CONFIG = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
DEFAULT_AUTH_CONFIG = BASE_DIR / "config" / "credentials" / "auth_config.py"


def run_cmd(cmd: list[str], title: str) -> None:
    print(f"\n[{title}]")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{title} 失败，退出码={proc.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行：规划视图 -> 创建视图")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(DEFAULT_GEMINI_CONFIG), help="Gemini 配置 JSON 路径")
    parser.add_argument("--auth-config", default=str(DEFAULT_AUTH_CONFIG), help="auth_config.py 路径")
    parser.add_argument("--app-ids", default="", help="可选，仅执行指定 appId（逗号分隔）")
    parser.add_argument("--worksheet-ids", default="", help="可选，仅执行指定 worksheetId（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际调用创建接口")
    parser.add_argument("--plan-output", default="", help="规划 JSON 输出路径")
    parser.add_argument("--create-output", default="", help="创建结果 JSON 输出路径")
    args = parser.parse_args()

    plan_output = args.plan_output.strip()
    if not plan_output:
        plan_output = str((VIEW_PLAN_DIR / "view_plan_pipeline_latest.json").resolve())

    create_output = args.create_output.strip()
    if not create_output:
        create_output = str((VIEW_CREATE_RESULT_DIR / "view_create_result_pipeline_latest.json").resolve())

    cmd_plan = [
        sys.executable,
        str(PLAN_SCRIPT),
        "--model",
        args.model,
        "--config",
        str(Path(args.config).expanduser().resolve()),
        "--auth-config",
        str(Path(args.auth_config).expanduser().resolve()),
        "--output",
        str(Path(plan_output).expanduser().resolve()),
    ]
    if args.app_ids.strip():
        cmd_plan.extend(["--app-ids", args.app_ids.strip()])

    cmd_create = [
        sys.executable,
        str(CREATE_SCRIPT),
        "--plan-json",
        str(Path(plan_output).expanduser().resolve()),
        "--auth-config",
        str(Path(args.auth_config).expanduser().resolve()),
        "--output",
        str(Path(create_output).expanduser().resolve()),
    ]
    if args.app_ids.strip():
        cmd_create.extend(["--app-ids", args.app_ids.strip()])
    if args.worksheet_ids.strip():
        cmd_create.extend(["--worksheet-ids", args.worksheet_ids.strip()])
    if args.dry_run:
        cmd_create.append("--dry-run")

    print("开始执行视图流水线")
    run_cmd(cmd_plan, "Step 1/2 规划视图")
    run_cmd(cmd_create, "Step 2/2 创建视图")

    print("\n流水线完成")
    print(f"- 规划文件: {Path(plan_output).expanduser().resolve()}")
    print(f"- 创建结果: {Path(create_output).expanduser().resolve()}")


if __name__ == "__main__":
    main()
