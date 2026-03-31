#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键串联入口：需求对话 → 应用创建 → 全流程执行

用法：
    python3 run_app_pipeline.py               # 默认：不录屏
    python3 run_app_pipeline.py --add-recording  # 开启 Playwright 录屏
"""

import argparse
import runpy
import sys
from pathlib import Path

HAP_SCRIPT = (Path(__file__).resolve().parent / "scripts" / "hap" / "run_app_to_video.py").resolve()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="一键从需求沟通到应用全流程执行",
        add_help=False,  # 透传 --help 给底层脚本
    )
    parser.add_argument(
        "--add-recording",
        action="store_true",
        default=False,
        help="开启 Playwright 录屏（默认不录屏）",
    )
    known, remaining = parser.parse_known_args()

    # 底层脚本用 --skip-recording 控制，默认跳过；
    # 只有传了 --add-recording 才不加该 flag。
    if not known.add_recording:
        remaining = ["--skip-recording"] + remaining

    # 用 remaining 替换 sys.argv，让底层 argparse 正常解析
    sys.argv = [str(HAP_SCRIPT)] + remaining
    runpy.run_path(str(HAP_SCRIPT), run_name="__main__")


if __name__ == "__main__":
    main()
