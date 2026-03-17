#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP Auto 一键初始化脚本
=======================
首次克隆后只需运行此脚本，按提示填写即可完成全部配置。

用法：
    python3 setup.py            # 首次初始化（已有配置自动跳过）
    python3 setup.py --force    # 强制重新初始化（显示当前值，回车保留，输入新值覆盖）
"""

import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CRED_DIR = BASE_DIR / "config" / "credentials"

# 占位符列表，匹配到这些值视为"未填写"
_PLACEHOLDERS = {
    "YOUR_HAP_APP_KEY",
    "YOUR_HAP_SECRET_KEY",
    "YOUR_HAP_PROJECT_ID",
    "YOUR_HAP_OWNER_ID",
    "YOUR_GEMINI_API_KEY",
    "your-account@example.com",
    "your-password",
    "OPTIONAL_PRECOMPUTED_SIGN",
}


def _mask(val: str, show: int = 4) -> str:
    """对敏感值做脱敏显示：前 show 位明文 + ****"""
    if not val or val in _PLACEHOLDERS:
        return "(未填写)"
    if len(val) <= show:
        return val
    return val[:show] + "****"


def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    val = input(f"{prompt}{hint}: ").strip()
    # 清理 copy-paste 常见的多余字符：引号、零宽空格等
    val = val.strip("\"'""''").strip("\u200b\u200c\u200d\ufeff").strip()
    return val or default


def _load_json_safe(path: Path) -> dict:
    """安全读取 JSON，文件不存在或格式错误返回空 dict"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _display_val(val: str, sensitive: bool = False) -> str:
    """用于展示当前值：敏感字段脱敏，占位符显示为 (未填写)"""
    if not val or val in _PLACEHOLDERS:
        return "(未填写)"
    return _mask(val) if sensitive else val


def step_install_deps():
    """安装 Python 依赖 + Playwright 浏览器"""
    print("\n📦 [1/4] 安装 Python 依赖...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                           "requests", "google-genai", "playwright", "prompt-toolkit"])
    print("🌐 安装 Playwright Chromium...")
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def step_gemini(force=False):
    """配置 Gemini API Key"""
    dst = CRED_DIR / "gemini_auth.json"
    existing = _load_json_safe(dst)
    old_key = existing.get("api_key", "")

    if dst.exists() and not force:
        print(f"\n✅ {dst.name} 已存在，跳过（需重新配置请加上 --force）")
        return

    print("\n🔑 [2/4] 配置 Gemini API Key")
    print("   获取地址: https://aistudio.google.com/apikey")

    if old_key and old_key not in _PLACEHOLDERS:
        print(f"   当前值: {_mask(old_key)}")
        print("   （直接回车保留当前值，输入新值则覆盖）")
        key = ask("   Gemini API Key", default=old_key)
    else:
        key = ask("   请输入你的 Gemini API Key")

    if not key:
        print("   ⚠️  未填写，稍后可手动编辑 config/credentials/gemini_auth.json")
        key = "YOUR_GEMINI_API_KEY"
    dst.write_text(json.dumps({"api_key": key}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"   ✔ 已写入 {dst.name}")


def step_org_auth(force=False):
    """配置 HAP 组织级密钥"""
    dst = CRED_DIR / "organization_auth.json"
    existing = _load_json_safe(dst)

    if dst.exists() and not force:
        print(f"\n✅ {dst.name} 已存在，跳过（需重新配置请加上 --force）")
        return

    print("\n🏢 [3/4] 配置 HAP 组织级密钥")
    print("   获取路径: 组织管理 → 集成 → 其他 → 开放接口 → 查看密钥")
    print("   快捷地址: https://www.mingdao.com/admin/integrationothers/<你的组织ID>")

    # 定义字段：(json_key, 显示名, 提示文字, 是否敏感, 是否必填)
    fields = [
        ("app_key",    "app_key",    None, True,  True),
        ("secret_key", "secret_key", None, True,  True),
        ("project_id", "project_id", "获取 project_id: 组织管理 → 组织 → 组织信息 → 编号（ID）", False, True),
        ("owner_id",   "owner_id",   "获取 owner_id: 点击群聊中个人头像，地址栏中 https://www.mingdao.com/user_xxx 的 xxx 部分", False, True),
        ("group_ids",  "group_ids",  "获取 group_ids: 在明道云中点击某个应用分组，地址栏中 groupId=xxx 的 xxx 部分（可选，留空不指定分组）", False, False),
    ]

    # 如果已有配置，先展示当前值
    if existing and any(existing.get(f[0], "") not in ("", *_PLACEHOLDERS) for f in fields):
        print("\n   📋 当前配置：")
        for key, name, _, sensitive, _ in fields:
            val = existing.get(key, "")
            print(f"      {name:12s} = {_display_val(val, sensitive)}")
        print("   （直接回车保留当前值，输入新值则覆盖）\n")

    results = {}
    for key, name, hint, sensitive, required in fields:
        if hint:
            print(f"\n   {hint}")
        old_val = existing.get(key, "")
        # 占位符不作为默认值展示
        default = old_val if old_val and old_val not in _PLACEHOLDERS else ""
        if default and sensitive:
            # 敏感字段显示脱敏值作为提示
            results[key] = ask(f"   {name} [{_mask(default)}]") or default
        else:
            results[key] = ask(f"   {name}", default=default)

    # 写入
    data = {}
    data["app_key"] = results["app_key"] or "YOUR_HAP_APP_KEY"
    data["secret_key"] = results["secret_key"] or "YOUR_HAP_SECRET_KEY"
    data["project_id"] = results["project_id"] or "YOUR_HAP_PROJECT_ID"
    data["owner_id"] = results["owner_id"] or "YOUR_HAP_OWNER_ID"
    data["group_ids"] = results["group_ids"] or ""
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"   ✔ 已写入 {dst.name}")


def step_login_and_auth(force=False):
    """配置登录凭据 → 自动刷新 auth_config.py"""
    login_dst = CRED_DIR / "login_credentials.py"
    auth_dst = CRED_DIR / "auth_config.py"

    if login_dst.exists() and auth_dst.exists() and not force:
        print(f"\n✅ login_credentials.py & auth_config.py 已存在，跳过（需重新配置请加上 --force）")
        return

    print("\n🔐 [4/4] 配置明道云登录账号")

    # 尝试读取已有账号
    old_account = ""
    old_password = ""
    if login_dst.exists():
        try:
            text = login_dst.read_text(encoding="utf-8")
            import re
            m = re.search(r'LOGIN_ACCOUNT\s*=\s*"(.+?)"', text)
            if m:
                old_account = m.group(1)
            m = re.search(r'LOGIN_PASSWORD\s*=\s*"(.+?)"', text)
            if m:
                old_password = m.group(1)
        except Exception:
            pass

    if old_account and old_account not in _PLACEHOLDERS:
        print(f"   当前账号: {old_account}")
        print(f"   当前密码: {_mask(old_password)}")
        print("   （直接回车保留当前值，输入新值则覆盖）")
        account = ask("   登录邮箱/手机号", default=old_account)
        password = ask(f"   登录密码 [{_mask(old_password)}]") or old_password
    else:
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
    import argparse
    parser = argparse.ArgumentParser(description="HAP Auto 一键初始化脚本")
    parser.add_argument("--force", action="store_true", help="强制重新初始化（保留已有值，回车跳过，输入新值覆盖）")
    args = parser.parse_args()

    print("=" * 60)
    print("  HAP Auto — 一键初始化")
    if args.force:
        print("  （--force 模式：显示当前配置，直接回车保留，输入新值覆盖）")
    print("=" * 60)

    step_install_deps()
    step_gemini(force=args.force)
    step_org_auth(force=args.force)
    step_login_and_auth(force=args.force)

    print("\n" + "=" * 60)
    print("🎉 初始化完成！现在可以运行：")
    print()
    print("   # 对话式创建应用（推荐）")
    print("   python3 scripts/hap/agent_collect_requirements.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
