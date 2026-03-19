#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 认证自动刷新工具
====================
使用 Playwright 驱动 Chromium 浏览器自动登录明道云，
登录成功后提取最新的 Cookie 和 Authorization，
并自动回写到 auth_config.py。

用法：
    python3 refresh_auth.py            # 有头模式（可以看到浏览器窗口）
    python3 refresh_auth.py --headless # 无头模式（后台静默运行）
"""

import re
import sys
import argparse
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = BASE_DIR / "config" / "credentials"
sys.path.insert(0, str(CONFIG_DIR))

# 导入登录凭据
try:
    from login_credentials import LOGIN_ACCOUNT, LOGIN_PASSWORD, LOGIN_URL
except ImportError:
    print("❌ 找不到 login_credentials.py，请先创建并填写账号信息")
    sys.exit(1)

AUTH_CONFIG_PATH = CONFIG_DIR / "auth_config.py"

# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def format_cookie_string(cookies: list[dict]) -> str:
    """把 Playwright 返回的 cookie 列表拼成 HTTP Cookie 字符串"""
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def extract_authorization(headers_log: list[dict]) -> str:
    """从捕获的请求头日志中提取 Authorization 值"""
    for entry in reversed(headers_log):
        auth = entry.get("authorization", "")
        if auth.startswith("md_pss_id"):
            return auth
    return ""


def update_auth_config(account_id: str, authorization: str, cookie: str) -> None:
    """将新的认证信息回写到 auth_config.py"""
    if not AUTH_CONFIG_PATH.exists():
        content = (
            "# -*- coding: utf-8 -*-\n"
            "ACCOUNT_ID = \"\"\n"
            "AUTHORIZATION = \"\"\n"
            "COOKIE = (\n"
            "    \"\"\n"
            ")\n"
        )
    else:
        content = AUTH_CONFIG_PATH.read_text(encoding="utf-8")

    # 替换 ACCOUNT_ID
    content = re.sub(
        r'^ACCOUNT_ID\s*=\s*"[^"]*"',
        f'ACCOUNT_ID = "{account_id}"',
        content,
        flags=re.MULTILINE,
    )

    # 替换 AUTHORIZATION
    content = re.sub(
        r'^AUTHORIZATION\s*=\s*"[^"]*"',
        f'AUTHORIZATION = "{authorization}"',
        content,
        flags=re.MULTILINE,
    )

    # 替换 COOKIE（整个多行括号块替换为单行字符串）
    content = re.sub(
        r'^COOKIE\s*=\s*\(.*?\)',
        f'COOKIE = (\n    "{cookie}"\n)',
        content,
        flags=re.MULTILINE | re.DOTALL,
    )

    AUTH_CONFIG_PATH.write_text(content, encoding="utf-8")
    print(f"✅ auth_config.py 已更新")


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def refresh(headless: bool = False) -> None:
    print("=" * 60)
    print("🔄 HAP 认证自动刷新")
    print(f"   登录账号: {LOGIN_ACCOUNT}")
    print(f"   无头模式: {headless}")
    print("=" * 60)

    headers_log: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # 监听所有请求，捕获带 Authorization 的头部
        def on_request(request):
            headers = request.headers
            if "authorization" in headers and headers["authorization"].startswith("md_pss_id"):
                headers_log.append(headers)

        page.on("request", on_request)

        # ── Step 1: 打开登录页 ──────────────────────────────────
        print("\n🌐 打开登录页...")
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=30_000)

        # ── Step 2: 填写账号密码 ────────────────────────────────
        print("✏️  填写账号密码...")
        try:
            # 明道云登录页真实 selector（SPA 动态渲染，无 <form> 标签）
            # 账号输入框 id="txtMobilePhone"，密码框 class="passwordIcon"
            page.wait_for_selector('#txtMobilePhone', timeout=15_000)

            # 填写账号
            page.click('#txtMobilePhone')
            page.fill('#txtMobilePhone', LOGIN_ACCOUNT)
            print(f"   ✔ 账号已填写: {LOGIN_ACCOUNT}")

            # 填写密码
            page.click('.passwordIcon')
            page.fill('.passwordIcon', LOGIN_PASSWORD)
            print("   ✔ 密码已填写")

        except PlaywrightTimeout:
            print("❌ 找不到登录表单，请检查 LOGIN_URL 是否正确，或页面渲染超时")
            browser.close()
            sys.exit(1)

        # ── Step 3: 点击登录按钮 ────────────────────────────────
        # 明道云登录按钮是 <span class="btnForLogin Hand">登 录</span>，不是 <button>
        print("🖱️  点击登录...")
        try:
            page.click('.btnForLogin')
        except Exception:
            page.keyboard.press("Enter")

        # ── Step 4: 等待登录完成（跳转到应用页） ────────────────
        print("⏳ 等待登录完成...")
        try:
            # 等待 URL 不再包含 /login
            page.wait_for_url(lambda url: "/login" not in url, timeout=30_000)
        except PlaywrightTimeout:
            print("❌ 登录超时，可能账号密码有误或需要验证码")
            if not headless:
                print("   已切换到有头模式，请在浏览器窗口中手动完成登录后按回车继续...")
                input("   按回车键继续...")
            else:
                browser.close()
                sys.exit(1)

        # 再等待 2 秒确保认证请求都发完
        time.sleep(2)
        page.wait_for_load_state("networkidle")

        # ── Step 5: 提取认证信息 ─────────────────────────────────
        print("\n📦 提取认证信息...")
        cookies = context.cookies()
        cookie_str = format_cookie_string(cookies)

        # AccountId：从 cookie 里找，或从请求头找
        account_id = ""
        for c in cookies:
            if c["name"].lower() in ("accountid", "account_id"):
                account_id = c["value"]
                break

        if not account_id:
            for h in reversed(headers_log):
                if "accountid" in h:
                    account_id = h["accountid"]
                    break

        authorization = extract_authorization(headers_log)

        # 如果 headers_log 没捕获到，尝试从 localStorage 取
        if not authorization:
            try:
                auth_from_storage = page.evaluate(
                    "() => localStorage.getItem('Authorization') || localStorage.getItem('md_pss_id') || ''"
                )
                if auth_from_storage:
                    authorization = auth_from_storage
            except Exception:
                pass

        # 从 auth_config.py 读取当前 ACCOUNT_ID 作为兜底
        if not account_id:
            try:
                from auth_config import ACCOUNT_ID
                account_id = ACCOUNT_ID
                print(f"   AccountId 使用已存储值: {account_id}")
            except Exception:
                pass

        # 同理 Authorization 兜底
        if not authorization:
            try:
                from auth_config import AUTHORIZATION
                authorization = AUTHORIZATION
                print(f"   Authorization 使用已存储值（未能自动捕获）")
            except Exception:
                pass

        print(f"   AccountId     : {account_id}")
        print(f"   Authorization : {authorization[:30]}...")
        print(f"   Cookie 长度   : {len(cookie_str)} 字符，共 {len(cookies)} 条")

        browser.close()

    # ── Step 6: 回写 auth_config.py ──────────────────────────────
    print("\n💾 回写 auth_config.py ...")
    update_auth_config(account_id, authorization, cookie_str)

    print("\n🎉 认证刷新完成！现在可以正常调用需要认证的 HAP 脚本了")
    print("=" * 60)


# ------------------------------------------------------------------
# 命令行入口
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HAP 明道云认证自动刷新工具")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式运行（不显示浏览器窗口，适合定时任务）",
    )
    args = parser.parse_args()
    refresh(headless=args.headless)


if __name__ == "__main__":
    main()
