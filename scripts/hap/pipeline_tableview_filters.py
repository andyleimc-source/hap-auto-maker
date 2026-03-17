#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键流水线：
1) 规划视图筛选配置
2) 应用筛选配置
"""

import argparse
import subprocess
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from script_locator import resolve_script
from gemini_utils import load_gemini_config

BASE_DIR = Path(__file__).resolve().parents[2]
PLAN_SCRIPT = resolve_script("plan_tableview_filters_gemini.py")
APPLY_SCRIPT = resolve_script("apply_tableview_filters_from_plan.py")
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
PLAN_DIR = OUTPUT_ROOT / "tableview_filter_plans"
APPLY_RESULT_DIR = OUTPUT_ROOT / "tableview_filter_apply_results"
# 加载全局配置
try:
    _, GEN_MODEL = load_gemini_config()
except Exception:
    GEN_MODEL = "gemini-2.5-pro"

DEFAULT_MODEL = GEN_MODEL
DEFAULT_GEMINI_CONFIG = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
DEFAULT_AUTH_CONFIG = BASE_DIR / "config" / "credentials" / "auth_config.py"


def run_cmd(cmd: list[str], title: str) -> None:
    print(f"\n[{title}]")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{title} 失败，退出码={proc.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行：规划视图筛选配置 -> 应用配置")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(DEFAULT_GEMINI_CONFIG), help="Gemini 配置 JSON 路径")
    parser.add_argument("--auth-config", default=str(DEFAULT_AUTH_CONFIG), help="auth_config.py 路径")
    parser.add_argument("--view-create-result", default="", help="视图创建结果 JSON 路径")
    parser.add_argument("--app-ids", default="", help="可选，仅执行指定 appId（逗号分隔）")
    parser.add_argument("--worksheet-ids", default="", help="可选，仅执行指定 worksheetId（逗号分隔）")
    parser.add_argument("--view-ids", default="", help="可选，仅执行指定 viewId（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际调用接口")
    parser.add_argument("--plan-output", default="", help="规划 JSON 输出路径")
    parser.add_argument("--apply-output", default="", help="应用结果 JSON 输出路径")
    args = parser.parse_args()

    plan_output = args.plan_output.strip() or str((PLAN_DIR / "tableview_filter_plan_pipeline_latest.json").resolve())
    apply_output = args.apply_output.strip() or str(
        (APPLY_RESULT_DIR / "tableview_filter_apply_result_pipeline_latest.json").resolve()
    )

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
    if args.view_create_result.strip():
        cmd_plan.extend(["--view-create-result", str(Path(args.view_create_result).expanduser().resolve())])

    cmd_apply = [
        sys.executable,
        str(APPLY_SCRIPT),
        "--plan-json",
        str(Path(plan_output).expanduser().resolve()),
        "--auth-config",
        str(Path(args.auth_config).expanduser().resolve()),
        "--output",
        str(Path(apply_output).expanduser().resolve()),
    ]
    if args.app_ids.strip():
        cmd_apply.extend(["--app-ids", args.app_ids.strip()])
    if args.worksheet_ids.strip():
        cmd_apply.extend(["--worksheet-ids", args.worksheet_ids.strip()])
    if args.view_ids.strip():
        cmd_apply.extend(["--view-ids", args.view_ids.strip()])
    if args.dry_run:
        cmd_apply.append("--dry-run")

    print("开始执行视图筛选配置流水线")
    run_cmd(cmd_plan, "Step 1/2 规划筛选配置")
    run_cmd(cmd_apply, "Step 2/2 应用筛选配置")
    print("\n流水线完成")
    print(f"- 规划文件: {Path(plan_output).expanduser().resolve()}")
    print(f"- 应用结果: {Path(apply_output).expanduser().resolve()}")


if __name__ == "__main__":
    main()
