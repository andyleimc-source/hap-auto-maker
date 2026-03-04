#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键执行工作表布局流程：
1) 规划字段布局（Gemini）
2) 应用字段布局（SaveWorksheetControls）
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
LAYOUT_PLAN_DIR = OUTPUT_ROOT / "worksheet_layout_plans"

PLAN_SCRIPT = BASE_DIR / "scripts" / "hap" / "plan_worksheet_layout.py"
APPLY_SCRIPT = BASE_DIR / "scripts" / "hap" / "apply_worksheet_layout.py"


def run_step(cmd: list[str], title: str) -> None:
    print(f"\n== {title} ==")
    print("命令:", " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"{title} 失败，退出码: {proc.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行：规划工作表布局 + 应用工作表布局")
    parser.add_argument("--app-index", type=int, default=0, help="可选，应用序号（免交互）")
    parser.add_argument("--requirements", default="", help="额外布局要求")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="Gemini 模型名")
    parser.add_argument("--refresh-auth", action="store_true", help="应用布局前先刷新网页登录认证")
    parser.add_argument("--headless", action="store_true", help="配合 --refresh-auth 无头刷新")
    parser.add_argument("--dry-run", action="store_true", help="仅预览应用布局，不实际保存")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    plan_output = (LAYOUT_PLAN_DIR / f"worksheet_layout_plan_pipeline_{ts}.json").resolve()
    plan_output.parent.mkdir(parents=True, exist_ok=True)

    cmd1 = [sys.executable, str(PLAN_SCRIPT), "--output", str(plan_output), "--model", args.model]
    if args.app_index > 0:
        cmd1.extend(["--app-index", str(args.app_index)])
    if args.requirements:
        cmd1.extend(["--requirements", args.requirements])
    run_step(cmd1, "Step 1/2 规划字段布局")

    cmd2 = [sys.executable, str(APPLY_SCRIPT), "--plan-json", str(plan_output)]
    if args.refresh_auth:
        cmd2.append("--refresh-auth")
    if args.headless:
        cmd2.append("--headless")
    if args.dry_run:
        cmd2.append("--dry-run")
    run_step(cmd2, "Step 2/2 应用字段布局")

    print("\n流水线执行完成")
    print(f"- 规划文件: {plan_output}")


if __name__ == "__main__":
    main()
