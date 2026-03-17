#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP Auto 一键初始化脚本
=======================
首次克隆后只需运行此脚本，按提示填写即可完成全部配置。

用法：
    python3 setup.py
"""

import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CRED_DIR = BASE_DIR / "config" / "credentials"


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    val = input(f"{prompt}{hint}: ").strip()
    return val or default


def step_install_deps():
    """安装 Python 依赖 + Playwright 浏览器"""
    print("\n📦 [1/4] 安装 Python 依赖...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                           "requests", "google-genai", "playwright", "prompt-toolkit"])
    print("🌐 安装 Playwright Chromium...")
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def step_gemini():
    """配置 Gemini API Key"""
    dst = CRED_DIR / "gemini_auth.json"
    if dst.exists():
        print(f"\n✅ {dst.name} 已存在，跳过")
        return
    print("\n🔑 [2/4] 配置 Gemini API Key")
    print("   获取地址: https://aistudio.google.com/apikey")
    key = ask("   请输入你的 Gemini API Key")
    if not key:
        print("   ⚠️  未填写，稍后可手动编辑 config/credentials/gemini_auth.json")
        key = "YOUR_GEMINI_API_KEY"
    dst.write_text(json.dumps({"api_key": key}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"   ✔ 已写入 {dst.name}")


def step_org_auth():
    """配置 HAP 组织级密钥"""
    dst = CRED_DIR / "organization_auth.json"
    if dst.exists():
        print(f"\n✅ {dst.name} 已存在，跳过")
        return
    print("\n🏢 [3/4] 配置 HAP 组织级密钥")
    print("   获取路径: 组织管理 → 集成 → 其他 → 开放接口 → 查看密钥")
    print("   快捷地址: https://www.mingdao.com/admin/integrationothers/<你的组织ID>")
    app_key = ask("   app_key")
    secret_key = ask("   secret_key")
    # 读取 example 模板获取完整结构
    example = CRED_DIR / "organization_auth.example.json"
    if example.exists():
        data = json.loads(example.read_text(encoding="utf-8"))
    else:
        data = {}
    data["app_key"] = app_key or "YOUR_HAP_APP_KEY"
    data["secret_key"] = secret_key or "YOUR_HAP_SECRET_KEY"
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"   ✔ 已写入 {dst.name}")


def step_login_and_auth():
    """配置登录凭据 → 自动刷新 auth_config.py"""
    login_dst = CRED_DIR / "login_credentials.py"
    auth_dst = CRED_DIR / "auth_config.py"

    if login_dst.exists() and auth_dst.exists():
        print(f"\n✅ login_credentials.py & auth_config.py 已存在，跳过")
        return

    print("\n🔐 [4/4] 配置明道云登录账号")
    account = ask("   登录邮箱/手机号")
    password = ask("   登录密码")

    # 写入 login_credentials.py
    login_dst.write_text(
        '# -*- coding: utf-8 -*-\n'
        '"""\n本地登录账号配置（自动生成，请勿提交到 Git）。\n"""\n\n'
        f'LOGIN_ACCOUNT = "{account or "your-account@example.com"}"\n'
        f'LOGIN_PASSWORD = "{password or "your-password"}"\n'
        f'LOGIN_URL = "https://www.mingdao.com/login"\n',
        encoding="utf-8",
    )
    print(f"   ✔ 已写入 login_credentials.py")

    # 先从模板复制 auth_config.py（refresh_auth 需要文件已存在才能正则替换）
    if not auth_dst.exists():
        example = CRED_DIR / "auth_config.example.py"
        if example.exists():
            auth_dst.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    # 自动刷新认证
    if account and password:
        print("\n🔄 自动登录并获取认证信息...")
        try:
            subprocess.check_call(
                [sys.executable, str(BASE_DIR / "scripts" / "refresh_auth.py"), "--headless"],
                cwd=str(BASE_DIR),
            )
        except subprocess.CalledProcessError:
            print("   ⚠️  自动登录失败，请稍后手动运行: python3 scripts/refresh_auth.py")
    else:
        print("   ⚠️  未填写账号密码，跳过自动认证。稍后手动运行: python3 scripts/refresh_auth.py")


def main():
    print("=" * 60)
    print("  HAP Auto — 一键初始化")
    print("=" * 60)

    step_install_deps()
    step_gemini()
    step_org_auth()
    step_login_and_auth()

    print("\n" + "=" * 60)
    print("🎉 初始化完成！现在可以运行：")
    print()
    print("   # 对话式创建应用（推荐）")
    print("   python3 scripts/hap/agent_collect_requirements.py")
    print()
    print("   # 一键全流程")
    print("   python3 scripts/hap/run_app_to_video.py --skip-recording")
    print("=" * 60)


if __name__ == "__main__":
    main()
