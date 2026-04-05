#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统计图流水线：
  Step 1/2  plan_charts_gemini.py   — 调用 Gemini 规划 3 个业务图表
  Step 2/2  create_charts_from_plan.py — 调用 saveReportConfig 创建图表
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
CURRENT_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
CHART_PLAN_DIR = OUTPUT_ROOT / "chart_plans"
CHART_CREATE_DIR = OUTPUT_ROOT / "chart_create_results"

DEFAULT_AUTH_CONFIG = BASE_DIR / "config" / "credentials" / "auth_config.py"


def run_cmd(cmd: list[str], title: str) -> None:
    print(f"\n{'='*60}")
    print(f"[{title}]")
    print(" ".join(cmd))
    print("=" * 60)
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{title} 失败，退出码={proc.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行：规划图表 -> 创建图表")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--auth-config", default=str(DEFAULT_AUTH_CONFIG), help="auth_config.py 路径")
    parser.add_argument("--worksheet-ids", default="", help="工作表 ID 列表，逗号分隔（从应用 URL 获取）")
    parser.add_argument("--app-name", default="", help="应用名称（可选）")
    parser.add_argument("--views-json", default="", help="视图数组 JSON 字符串（从已有图表 curl 的 views 字段复制）")
    parser.add_argument("--plan-output", default="", help="规划 JSON 输出路径（可选）")
    parser.add_argument("--create-output", default="", help="创建结果 JSON 输出路径（可选）")
    parser.add_argument("--page-id", default="", help="统计图 Page ID（应用 URL 最后一段），创建后自动 savePage")
    parser.add_argument("--dry-run", action="store_true", help="仅演练规划，不实际调用创建接口")
    parser.add_argument("--skip-plan", action="store_true", help="跳过规划步骤，直接用已有最新规划文件创建")
    args = parser.parse_args()

    plan_output = args.plan_output.strip()
    if not plan_output:
        plan_output = str((CHART_PLAN_DIR / f"chart_plan_{args.app_id}_pipeline.json").resolve())

    create_output = args.create_output.strip()
    if not create_output:
        create_output = str((CHART_CREATE_DIR / f"chart_create_{args.app_id}_pipeline.json").resolve())

    auth_config = str(Path(args.auth_config).expanduser().resolve())

    if str(CURRENT_DIR) not in sys.path:
        sys.path.insert(0, str(CURRENT_DIR))
    from script_locator import resolve_script
    plan_script = resolve_script("plan_charts_gemini.py")
    create_script = resolve_script("create_charts_from_plan.py")

    print("统计图流水线启动")
    print(f"  应用 ID  : {args.app_id}")
    print(f"  dry-run  : {args.dry_run}")

    if not args.skip_plan:
        cmd_plan = [
            sys.executable, str(plan_script),
            "--app-id", args.app_id,
            "--auth-config", auth_config,
            "--output", plan_output,
        ]
        if args.worksheet_ids.strip():
            cmd_plan.extend(["--worksheet-ids", args.worksheet_ids.strip()])
        if args.app_name.strip():
            cmd_plan.extend(["--app-name", args.app_name.strip()])
        if args.views_json.strip():
            cmd_plan.extend(["--views-json", args.views_json.strip()])
        run_cmd(cmd_plan, "Step 1/2 规划图表（AI）")
    else:
        print("\n[跳过 Step 1/2]：使用已有规划文件")

    cmd_create = [
        sys.executable, str(create_script),
        "--plan-json", plan_output,
        "--auth-config", auth_config,
        "--output", create_output,
    ]
    if args.page_id.strip():
        cmd_create.extend(["--page-id", args.page_id.strip()])
    if args.dry_run:
        cmd_create.append("--dry-run")

    run_cmd(cmd_create, "Step 2/2 创建图表（saveReportConfig）")

    print("\n流水线完成")
    print(f"  规划文件 : {plan_output}")
    print(f"  结果文件 : {create_output}")


if __name__ == "__main__":
    main()
