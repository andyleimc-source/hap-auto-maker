#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义页面 + 统计图一键流水线：

  Step 1/2  plan_pages_gemini.py    — Gemini 规划应用需要哪些分析页及各页聚焦的工作表
  Step 2/2  create_pages_from_plan.py — 逐一创建 Page，并在每个 Page 中生成统计图

运行后产物：
  data/outputs/page_plans/       page_plan_<appId>_<ts>.json  （Page 规划）
  data/outputs/page_create_results/ page_create_<appId>_<ts>.json （创建结果汇总）
  data/outputs/chart_plans/      chart_plan_<appId>_page_<pageId>.json（各 Page 图表规划）
  data/outputs/page_create_results/ chart_create_<appId>_page_<pageId>.json（各 Page 图表结果）
  data/logs/                     plan_pages_<appId>_<ts>.log
                                 create_pages_<appId>_<ts>.log
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
CURRENT_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
PAGE_PLAN_DIR = OUTPUT_ROOT / "page_plans"
PAGE_CREATE_DIR = OUTPUT_ROOT / "page_create_results"

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
    parser = argparse.ArgumentParser(
        description="一键执行：规划分析页 -> 创建 Page -> 在每个 Page 中创建统计图",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 最简调用（自动读取 auth_config.py 中的默认配置）
  python pipeline_pages.py --app-id YOUR_APP_ID

  # 跳过规划（使用已有最新规划文件直接创建）
  python pipeline_pages.py --app-id YOUR_APP_ID --skip-plan

  # 仅演练（不实际创建）
  python pipeline_pages.py --app-id YOUR_APP_ID --dry-run
        """,
    )
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--auth-config", default=str(DEFAULT_AUTH_CONFIG), help="auth_config.py 路径")
    parser.add_argument("--plan-output", default="", help="Page 规划 JSON 输出路径（可选）")
    parser.add_argument("--create-output", default="", help="创建结果 JSON 输出路径（可选）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际创建 Page 和图表")
    parser.add_argument("--skip-plan", action="store_true", help="跳过规划步骤，使用已有最新规划文件")
    args = parser.parse_args()

    app_id = args.app_id.strip()
    auth_config = str(Path(args.auth_config).expanduser().resolve())

    plan_output = args.plan_output.strip()
    if not plan_output:
        plan_output = str((PAGE_PLAN_DIR / f"page_plan_{app_id}_pipeline.json").resolve())

    create_output = args.create_output.strip()
    if not create_output:
        create_output = str((PAGE_CREATE_DIR / f"page_create_{app_id}_pipeline.json").resolve())

    plan_script = CURRENT_DIR / "plan_pages_gemini.py"
    create_script = CURRENT_DIR / "create_pages_from_plan.py"

    print("自定义页面 + 统计图流水线启动")
    print(f"  应用 ID  : {app_id}")
    print(f"  dry-run  : {args.dry_run}")
    print(f"  skip-plan: {args.skip_plan}")

    # Step 1: 规划 Pages
    if not args.skip_plan:
        cmd_plan = [
            sys.executable, str(plan_script),
            "--app-id", app_id,
            "--auth-config", auth_config,
            "--output", plan_output,
        ]
        run_cmd(cmd_plan, "Step 1/2 规划自定义分析页（AI）")
    else:
        print("\n[跳过 Step 1/2]：使用已有规划文件")

    # Step 2: 创建 Pages + 图表
    # --skip-plan 时若 pipeline 专属文件不存在，传空让 create 脚本自动找最新规划
    plan_json_arg = plan_output if (not args.skip_plan or Path(plan_output).exists()) else ""
    cmd_create = [
        sys.executable, str(create_script),
        "--plan-json", plan_json_arg,
        "--auth-config", auth_config,
        "--output", create_output,
    ]
    if args.dry_run:
        cmd_create.append("--dry-run")
    run_cmd(cmd_create, "Step 2/2 创建 Page + 统计图")

    print("\n流水线完成")
    print(f"  规划文件 : {plan_output}")
    print(f"  结果文件 : {create_output}")
    print(f"  日志目录 : {BASE_DIR / 'data' / 'logs'}")


if __name__ == "__main__":
    main()
