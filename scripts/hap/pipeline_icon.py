#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作表 icon 一键流水线：
1) 拉取应用下工作表列表
2) 调用 Gemini 生成 icon 匹配方案
3) 批量更新工作表 icon
"""

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
WORKSHEET_INVENTORY_DIR = OUTPUT_ROOT / "worksheet_inventory"
ICON_MATCH_DIR = OUTPUT_ROOT / "worksheet_icon_match_plans"

LIST_SCRIPT = BASE_DIR / "scripts" / "hap" / "list_app_worksheets.py"
MATCH_SCRIPT = BASE_DIR / "scripts" / "gemini" / "match_worksheet_icons_gemini.py"
UPDATE_SCRIPT = BASE_DIR / "scripts" / "hap" / "update_worksheet_icons.py"


def run_step(cmd: list[str], title: str) -> None:
    print(f"\n== {title} ==")
    print("命令:", " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"{title} 失败，退出码: {proc.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="一键执行工作表 icon 匹配与批量更新")
    parser.add_argument("--app-auth-json", default="", help="应用授权 JSON 文件名或路径")
    parser.add_argument("--app-id", default="", help="可选，授权文件有多个 app 时可指定")
    parser.add_argument("--model", default="gemini-2.5-pro", help="Gemini 模型名")
    parser.add_argument(
        "--inventory-json",
        default=str((WORKSHEET_INVENTORY_DIR / "worksheet_inventory_latest.json").resolve()),
        help="第1步工作表清单输出路径",
    )
    parser.add_argument(
        "--match-json",
        default=str((ICON_MATCH_DIR / "worksheet_icon_match_plan_latest.json").resolve()),
        help="第2步 icon 匹配输出路径",
    )
    parser.add_argument("--refresh-auth", action="store_true", help="第3步执行前先刷新网页认证")
    parser.add_argument("--headless", action="store_true", help="配合 --refresh-auth 无头刷新")
    parser.add_argument("--dry-run", action="store_true", help="第3步仅预览，不实际更新")
    args = parser.parse_args()

    # Step 1: 列工作表
    inventory_path = Path(args.inventory_json).expanduser().resolve()
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    cmd1 = [sys.executable, str(LIST_SCRIPT), "--output", str(inventory_path)]
    if args.app_auth_json:
        cmd1.extend(["--app-auth-json", args.app_auth_json])
    if args.app_id:
        cmd1.extend(["--app-id", args.app_id])
    run_step(cmd1, "Step 1/3 获取工作表清单")

    # Step 2: Gemini 匹配
    match_path = Path(args.match_json).expanduser().resolve()
    match_path.parent.mkdir(parents=True, exist_ok=True)
    cmd2 = [
        sys.executable,
        str(MATCH_SCRIPT),
        "--worksheet-json",
        str(inventory_path),
        "--model",
        args.model,
        "--output",
        str(match_path),
    ]
    run_step(cmd2, "Step 2/3 生成 icon 匹配方案")

    # Step 3: 批量更新 icon
    cmd3 = [sys.executable, str(UPDATE_SCRIPT), "--mapping-json", str(match_path)]
    if args.refresh_auth:
        cmd3.append("--refresh-auth")
    if args.headless:
        cmd3.append("--headless")
    if args.dry_run:
        cmd3.append("--dry-run")
    run_step(cmd3, "Step 3/3 批量更新工作表 icon")

    print("\n流水线执行完成")
    print(f"- 工作表清单: {inventory_path}")
    print(f"- 匹配方案: {match_path}")


if __name__ == "__main__":
    main()
