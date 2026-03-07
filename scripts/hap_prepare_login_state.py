#!/usr/bin/env python3
"""
One-time login state preparation for HAP/Mingdao.

Usage:
    python3 scripts/hap_prepare_login_state.py --url "https://www.mingdao.com/app/xxx"
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright


DEFAULT_STATE_PATH = Path("config/credentials/mingdao_storage_state.json")


def run(url: str, state_path: Path, headless: bool = False) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded")

        if "/login" in page.url:
            if headless:
                context.close()
                browser.close()
                raise RuntimeError("Headless 模式无法手动登录，请去掉 --headless 后重试。")

            print("检测到登录页。请在打开的浏览器中完成登录，然后回到终端按回车。")
            input("完成登录后按回车继续...")
            try:
                page.wait_for_url(lambda u: "/login" not in u, timeout=180_000)
            except PlaywrightTimeout as exc:
                context.close()
                browser.close()
                raise RuntimeError("登录未完成或超时（180秒）。") from exc
        else:
            print("当前已是登录态，直接保存会话。")

        context.storage_state(path=str(state_path))
        print(f"已保存登录态: {state_path.resolve()}")
        context.close()
        browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare login storage state for HAP scripts.")
    parser.add_argument("--url", required=True, help="HAP app URL (or a page that requires login).")
    parser.add_argument(
        "--state-path",
        default=str(DEFAULT_STATE_PATH),
        help="Storage state file path.",
    )
    parser.add_argument("--headless", action="store_true", help="Run headless (not recommended for first login).")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(url=args.url, state_path=Path(args.state_path), headless=args.headless)
