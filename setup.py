#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP Auto 初始化工具 (稳健修复版)
=====================================
主要改进：
1. 修复 f-string 中海象运算符导致的 NameError。
2. 保持 CJK 宽度感知对齐算法。
3. 保持密码实时遮码输入 (*)。
4. 保持账号密码记忆与脱敏显示。
"""

import json
import subprocess
import sys
import os
import re
import argparse
import unicodedata
import tty
import termios
from pathlib import Path

# 路径常量
BASE_DIR = Path(__file__).resolve().parent
CRED_DIR = BASE_DIR / "config" / "credentials"
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))

_PLACEHOLDERS = {
    "YOUR_HAP_APP_KEY", "YOUR_HAP_SECRET_KEY", "YOUR_HAP_PROJECT_ID", "YOUR_HAP_OWNER_ID",
    "YOUR_GEMINI_API_KEY", "YOUR_GEMINI_MODEL", "YOUR_DEEPSEEK_API_KEY", "YOUR_DEEPSEEK_MODEL",
    "your-account@example.com", "your-password", "OPTIONAL_PRECOMPUTED_SIGN", "", None
}

# --- 核心对齐算法 ---

def get_display_width(s):
    width = 0
    for char in s:
        if unicodedata.east_asian_width(char) in ('W', 'F'): width += 2
        else: width += 1
    return width

def ljust_cjk(s, width):
    return s + ' ' * max(0, width - get_display_width(s))

def rjust_cjk(s, width):
    return ' ' * max(0, width - get_display_width(s)) + s

def center_cjk(s, width):
    pad = max(0, width - get_display_width(s))
    left = pad // 2
    return ' ' * left + s + ' ' * (pad - left)

# --- 视觉辅助 ---

def print_box(title: str):
    width = 66
    print("\n┌" + "─" * (width-2) + "┐")
    print(f"│{center_cjk(title, width-2)}│")
    print("└" + "─" * (width-2) + "┘")

def show_banner():
    print("\n" + "═" * 66)
    print(center_cjk("🚀 HAP Auto 自动化环境配置中心", 66))
    print("═" * 66)
    print("\n💡 指令速查 (Command Cheat Sheet):")
    cmds = [
        ("python3 setup.py",        "引导式全量安装 (向导模式)"),
        ("python3 setup.py --menu", "管理模式 (查看状态 & 增量修改)"),
        ("python3 setup.py --init", "彻底重置 (清空配置并从头开始)")
    ]
    for cmd, desc in cmds:
        print(f"   {ljust_cjk(cmd, 25)} ->  {desc}")
    print("-" * 66)

def show_footer():
    width = 66
    print("\n" + "╔" + "═" * (width-2) + "╗")
    print("║" + center_cjk("✨ 配置引导已圆满完成！", width-2) + "║")
    print("╠" + "═" * (width-2) + "╣")
    print(f"║ {ljust_cjk('💡 修改或检查:  python3 setup.py --menu', width-4)} ║")
    print(f"║ {ljust_cjk('🔥 彻底清空重置: python3 setup.py --init', width-4)} ║")
    print(f"║ {ljust_cjk('🚀 启动主流程:   python3 scripts/run_app_pipeline.py', width-4)} ║")
    print("╚" + "═" * (width-2) + "╝\n")

# --- 工具函数 ---

def _mask(val: str, show: int = 4) -> str:
    s = str(val or "").strip()
    if not s or s in _PLACEHOLDERS or "YOUR_" in s: return "未填写"
    return s[:show] + "****" if len(s) > show else s

def _truncate(val: str, max_len: int = 20) -> str:
    s = str(val or "").strip()
    if not s or s in _PLACEHOLDERS or "YOUR_" in s: return ""
    return s[:max_len-3] + "..." if len(s) > max_len else s

def _is_valid(val: str) -> bool:
    s = str(val or "").strip()
    return bool(s) and s not in _PLACEHOLDERS and "YOUR_" not in s

def _load_json(path: Path) -> dict:
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except: return {}

def get_password_masked(prompt):
    """实时遮码输入 (*)"""
    print(prompt, end='', flush=True)
    password = ""
    while True:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        
        if ch in ('\r', '\n'):
            print()
            break
        elif ch == '\x7f':  # Backspace
            if len(password) > 0:
                password = password[:-1]
                sys.stdout.write('\b \b')
                sys.stdout.flush()
        elif ch == '\x03': # Ctrl+C
            raise KeyboardInterrupt
        else:
            password += ch
            sys.stdout.write('*')
            sys.stdout.flush()
    return password

def ask(label: str, default: str = "", required: bool = False, hint: str = "", is_pwd: bool = False, choices: list = None) -> str:
    prefix = "[必填]" if required else "[可选]"
    clean_def = str(default).strip()
    is_placeholder = clean_def in _PLACEHOLDERS or "YOUR_" in clean_def
    
    # 确定显示值
    display_hint = hint if hint else (_mask(clean_def) if (len(clean_def) > 15 or required) else clean_def)
    hint_str = f"(当前: {display_hint})" if (display_hint and not is_placeholder) else ""
    
    # 修复对齐：先计算再组合
    p_prefix = ljust_cjk(prefix, 8)
    p_label  = ljust_cjk(label, 32)
    p_hint   = rjust_cjk(hint_str, 22)
    prompt_str = f"   {p_prefix}{p_label}{p_hint} : "
    
    while True:
        if is_pwd:
            val = get_password_masked(prompt_str).strip()
        else:
            val = input(prompt_str).strip()
            val = val.strip("\"'").strip("\u200b\u200c\u200d\ufeff")
            
        final = val if val else (default if not is_placeholder else "")
        
        if required and not _is_valid(final):
            print(f"      {ljust_cjk('', 40)} ⚠️  错误：此项必填。")
            continue
            
        if choices and final not in choices:
            print(f"      {ljust_cjk('', 40)} ⚠️  错误：无效输入，请从 {choices} 中选择。")
            continue
            
        return final

# --- 状态检测 ---

def get_existing_login():
    path = CRED_DIR / "login_credentials.py"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        acc = re.search(r'^LOGIN_ACCOUNT\s*=\s*"(.+?)"', text, re.M)
        pwd = re.search(r'^LOGIN_PASSWORD\s*=\s*"(.+?)"', text, re.M)
        return (acc.group(1) if acc else "", pwd.group(1) if pwd else "")
    return ("", "")

def get_status_ai():
    try:
        from ai_utils import AI_CONFIG_PATH
        conf = _load_json(AI_CONFIG_PATH)
        if _is_valid(conf.get("api_key")):
            return f"✅ 已配置 ({conf.get('provider','').title()}: {_truncate(conf.get('model',''), 15)})"
    except: pass
    return "❌ 待配置"

def get_status_hap():
    conf = _load_json(CRED_DIR / "organization_auth.json")
    ak, sk = _is_valid(conf.get("app_key")), _is_valid(conf.get("secret_key"))
    if ak and sk: return f"✅ 已配置 (Key: {_mask(conf.get('app_key'))})"
    if ak or sk: return "⚠️ 部分配置"
    return "❌ 待配置"

def get_status_login():
    acc, pwd = get_existing_login()
    if _is_valid(acc) and _is_valid(pwd): return f"✅ 已配置 ({_truncate(acc)})"
    return "❌ 待配置"

def get_status_group():
    conf = _load_json(CRED_DIR / "organization_auth.json")
    gid = conf.get("group_ids")
    if _is_valid(gid): return f"✅ 已选中 (ID: {_mask(gid, 5)})"
    return "❌ 未选择"

# --- 步骤执行 ---

def step_ai(force=True):
    from ai_utils import AI_CONFIG_PATH, DEFAULT_DEEPSEEK_BASE_URL, load_ai_config
    existing = {}
    try: existing = load_ai_config()
    except: pass
    print_box("第 1 步：配置 AI 平台 (AI Provider)")
    old_p = existing.get("provider", "gemini")
    p_choice = ask("AI 平台 (1=Gemini, 2=DeepSeek)", default="2" if old_p=="deepseek" else "1", required=True, hint="DeepSeek" if old_p=="deepseek" else "Gemini", choices=["1", "2"])
    provider = "deepseek" if p_choice == "2" else "gemini"
    key = ask(f"{provider.title()} API Key", default=existing.get("api_key", ""), required=True)
    opts = {"gemini": {"1": ("gemini-2.0-flash", "响应极快"), "2": ("gemini-2.0-pro-exp-02-05", "逻辑顶尖")},
            "deepseek": {"1": ("deepseek-chat", "通用对话"), "2": ("deepseek-reasoner", "深度推理")}}[provider]
    print("\n   可用模型清单:")
    for k, v in opts.items(): print(f"      {k}. {ljust_cjk(v[0], 25)} -> {v[1]}")
    m_choice = ask("请选择模型序号", default="1", required=True, hint=existing.get("model", "") if provider==old_p else "", choices=list(opts.keys()))
    model = opts.get(m_choice, opts["1"])[0]
    data = {"provider": provider, "api_key": key, "model": model, "base_url": DEFAULT_DEEPSEEK_BASE_URL if provider=="deepseek" else ""}
    AI_CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if provider == "gemini": (CRED_DIR / "gemini_auth.json").write_text(json.dumps({"api_key": key, "model": model}, indent=2), encoding="utf-8")
    print("\n   ✔ AI 平台配置已保存。")

def step_org_auth(force=True):
    dst = CRED_DIR / "organization_auth.json"
    existing = _load_json(dst)
    print_box("第 2 步：配置 HAP 组织密钥 (HAP API)")
    res = {}
    res["app_key"] = ask("App Key", default=existing.get("app_key",""), required=True)
    res["secret_key"] = ask("Secret Key", default=existing.get("secret_key",""), required=True)
    res["project_id"] = ask("组织 Project ID (编号)", default=existing.get("project_id",""), required=True)
    res["owner_id"] = ask("用户 Owner ID (个人编号)", default=existing.get("owner_id",""), required=True)
    res["group_ids"] = existing.get("group_ids", "")
    dst.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\n   ✔ HAP 组织密钥已同步。")

def step_login_and_auth(force=True):
    login_dst = CRED_DIR / "login_credentials.py"
    existing_acc, existing_pwd = get_existing_login()
    print_box("第 3 步：配置登录账号 (Login Account)")
    acc = ask("登录邮箱或手机号", default=existing_acc, required=True)
    pwd = ask("登录密码 (明道云密码)", default=existing_pwd, required=True, is_pwd=True)
    content = f'# -*- coding: utf-8 -*-\nLOGIN_ACCOUNT = "{acc}"\nLOGIN_PASSWORD = "{pwd}"\nLOGIN_URL = "https://www.mingdao.com/login"\n'
    login_dst.write_text(content, encoding="utf-8")
    print("\n   ✔ 登录凭据已保存。")
    print("   🔄 正在启动自动登录并同步浏览器 Session...")
    try:
        subprocess.call([sys.executable, str(BASE_DIR / "scripts" / "auth" / "refresh_auth.py"), "--headless"])
        print("   ✔ Session 认证同步完成。")
    except Exception as e: print(f"   ⚠️  同步异常: {e}")

def step_group_init():
    print_box("第 4 步：选择应用工作分组 (App Group)")
    if "✅" not in get_status_hap():
        print("   ⚠️  错误：请先完成第 2 步。")
        return
    try:
        from list_groups import get_groups
        from local_config import save_local_group_id, load_local_group_id
        from create_group import create_group
        groups = get_groups()
        if not groups:
            print("\n   ⚠️  未发现应用分组。")
            if ask("是否现在创建一个新分组？(y/N)", default="y", required=True) == "y":
                name = ask("请输入新分组名称", default="AutoHAP_Test", required=True)
                gid = create_group(name)
                return
            return
        curr_gid = load_local_group_id()
        curr_gname = next((g['name'] for g in groups if g['groupId'] == curr_gid), "")
        print("\n   现有工作分组清单:")
        for i, g in enumerate(groups, 1): print(f"      {i}. {ljust_cjk(g['name'], 30)}")
        print(f"      n. {ljust_cjk('[新建应用分组]', 30)}")
        
        valid_indices = [str(i) for i in range(1, len(groups) + 1)]
        choice_list = valid_indices + ["n", "N"]
        idx_str = ask("请输入分组序号 (n 新建)", default="1", required=True, hint=curr_gname, choices=choice_list)
        
        if idx_str.lower() == 'n':
            name = ask("请输入新分组名称", default="AutoHAP_New", required=True)
            gid = create_group(name)
            return
        idx = int(idx_str) - 1
        if 0 <= idx < len(groups):
            gid = groups[idx]['groupId']
            save_local_group_id(gid)
            print(f"\n   ✔ 已选中分组: {groups[idx]['name']}")
    except Exception as e: print(f"   ❌ 分组操作失败: {e}")

# --- 主逻辑 ---

def wizard():
    show_banner()
    step_ai(force=True)
    step_org_auth(force=True)
    step_login_and_auth(force=True)
    step_group_init()
    show_footer()

def main():
    parser = argparse.ArgumentParser(description="HAP Auto 初始化工具")
    parser.add_argument("--menu", action="store_true", help="管理模式")
    parser.add_argument("--init", action="store_true", help="清空重置")
    args = parser.parse_args()

    if args.init:
        if input("\n🚨 警告：这会彻底清空所有配置。确认吗？(y/N): ").lower() == 'y':
            for f in [CRED_DIR / "ai_auth.json", CRED_DIR / "organization_auth.json", CRED_DIR / "login_credentials.py", 
                      CRED_DIR / "gemini_auth.json", CRED_DIR / "auth_config.py"]:
                if f.exists(): f.unlink()
            print("   ✔ 已清理。")
            wizard()
            return

    if args.menu:
        show_banner()
        while True:
            print("\n" + "╔" + "═" * 64 + "╗")
            print("║" + center_cjk("⚙️  HAP Auto 配置管理中心 (Management)", 64) + "║")
            print("╚" + "═" * 64 + "╝")
            print(f"  1. 修改 AI 平台配置    ->  {get_status_ai()}")
            print(f"  2. 修改 HAP 组织密钥    ->  {get_status_hap()}")
            print(f"  3. 修改明道云登录账号    ->  {get_status_login()}")
            print(f"  4. 重新选择/新建分组    ->  {get_status_group()}")
            print("  q. 保存并退出管理模式")
            c = input("\n请选择序号: ").strip().lower()
            if c == '1': step_ai()
            elif c == '2': step_org_auth()
            elif c == '3': step_login_and_auth()
            elif c == '4': step_group_init()
            elif c == 'q': break
        return

    wizard()

if __name__ == "__main__":
    try:
        try: import requests
        except: subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "requests", "openai", "playwright"])
        main()
    except KeyboardInterrupt: print("\n👋 配置流程已中断。")
