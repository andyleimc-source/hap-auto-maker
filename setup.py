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
            # 用 print 显示提示符，再用 sys.stdin.readline() 读取输入。
            # 不能用 input(prompt_str)：readline 用字节数计算 CJK 光标位置，导致错位乱码。
            # 不能用 print()+input()：input() 无参数仍调用 readline，方向键/Ctrl+Z 会产生
            # 转义序列 ^[[B / ^Z 回显到输入行。
            # sys.stdin.readline() 完全绕过 readline，使用终端 cooked mode 读取，无上述问题。
            print(prompt_str, end='', flush=True)
            val = sys.stdin.readline().rstrip('\n')
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

# --- 交互式列表选择 ---

def _select_interactive(items: list, title: str = "", current_idx: int = 0) -> int:
    """
    用上/下方向键浏览列表，Enter 确认，数字键直接跳转。
    返回 0-based 索引。items 为字符串列表。
    """
    import tty
    import termios

    idx = max(0, min(current_idx, len(items) - 1))
    n = len(items)

    def _render(first=False):
        if not first:
            # 上移 n 行，回到行首，清空到屏幕底部
            # raw 模式下 \n 只是 LF（不含 CR），必须加 \r 才能回到列 0
            sys.stdout.write(f"\x1b[{n}A\r\x1b[0J")
        for i, item in enumerate(items):
            marker = "▶" if i == idx else " "
            num = str(i + 1)
            line = f"      {marker} {num}. {item}"
            # raw 模式下必须用 \r\n，否则下一行从当前列开始，导致排版错乱
            sys.stdout.write(line + "\r\n")
        sys.stdout.flush()

    if title:
        print(f"\n   {title}")
    _render(first=True)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                # 读取完整转义序列（最多再读 2 个字符）
                seq = sys.stdin.read(1)
                if seq == '[':
                    direction = sys.stdin.read(1)
                    if direction == 'A':  # 上箭头
                        idx = (idx - 1) % n
                    elif direction == 'B':  # 下箭头
                        idx = (idx + 1) % n
                # 其他转义序列忽略
            elif ch in ('\r', '\n'):
                break
            elif ch == '\x03':  # Ctrl+C
                raise KeyboardInterrupt
            elif ch.isdigit() and ch != '0':
                d = int(ch) - 1
                if 0 <= d < n:
                    idx = d
            _render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    # 确认选中：擦除列表，只显示选中结果
    sys.stdout.write(f"\x1b[{n}A\r\x1b[0J")
    sys.stdout.write(f"   ✔ {idx + 1}. {items[idx]}\r\n")
    sys.stdout.flush()
    return idx


# --- 步骤执行 ---

def step_ai(force=True):
    from ai_utils import (AI_CONFIG_PATH,
                          load_ai_config, list_models,
                          default_base_url_for_provider)
    existing = {}
    try:
        existing = load_ai_config()
    except Exception:
        pass

    print_box("第 1 步：配置 AI 平台 (AI Provider)")

    # 供应商菜单
    PROVIDERS = [
        ("gemini",   "Gemini (Google)"),
        ("deepseek", "DeepSeek"),
        ("minimax",  "MiniMax"),
        ("kimi",     "Kimi (Moonshot)"),
        ("zhipu",    "智谱 GLM"),
        ("doubao",   "豆包 (Doubao/Volcengine)"),
        ("qwen",     "千问 (Qwen/Alibaba)"),
    ]
    old_p = existing.get("provider", "")
    provider_labels = [label for _, label in PROVIDERS]
    default_provider_idx = next(
        (i for i, (key, _) in enumerate(PROVIDERS) if key == old_p),
        0
    )
    p_idx = _select_interactive(provider_labels, title="选择 AI 供应商（↑↓ 移动，Enter 确认，数字键跳转）：", current_idx=default_provider_idx)
    provider, provider_label = PROVIDERS[p_idx]
    provider_changed = provider != old_p

    # API Key
    existing_key = existing.get("api_key", "")
    # 仅对 Gemini/DeepSeek 做 key 格式校验
    key_mismatch = (
        (provider == "gemini" and existing_key.startswith("sk-")) or
        (provider == "deepseek" and existing_key.startswith("AIza"))
    )
    key = ask(
        f"{provider_label} API Key",
        default="" if (provider_changed or key_mismatch) else existing_key,
        required=True,
    )

    # 确定 base_url
    base_url = default_base_url_for_provider(provider)

    # 拉取可用模型列表
    print(f"\n   正在从 {provider_label} API 拉取可用模型列表...")
    models = list_models(provider, key, base_url)

    if models:
        # DeepSeek：交互页仅展示推理模型，避免误选 deepseek-chat。
        if provider == "deepseek":
            models = [m for m in models if m == "deepseek-reasoner"]
            if not models:
                models = ["deepseek-reasoner"]
        old_model = existing.get("model", "") if not provider_changed else ""
        default_model_idx = next((i for i, m in enumerate(models) if m == old_model), 0)
        print(f"\n   可用模型（共 {len(models)} 个）：")
        m_idx = _select_interactive(models, current_idx=default_model_idx)
        selected_model = models[m_idx]
    else:
        print("   ⚠️  无法拉取模型列表，请手动输入模型名称。")
        old_model = existing.get("model", "") if not provider_changed else ""
        selected_model = ask("模型名称", default=old_model, required=True)

    data = {
        "provider": provider,
        "api_key": key,
        "model": selected_model,
        "base_url": base_url,
    }

    AI_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # 向后兼容：Gemini 同步写入 gemini_auth.json
    if provider == "gemini":
        (CRED_DIR / "gemini_auth.json").write_text(
            json.dumps({"api_key": key, "model": selected_model}, indent=2),
            encoding="utf-8",
        )
    print(f"\n   ✔ AI 平台配置已完成 (供应商: {provider_label}, 模型: {selected_model})。")

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
        subprocess.call([sys.executable, str(BASE_DIR / "scripts" / "auth" / "refresh_auth.py")])
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
        try:
            import openai  # noqa: F401
        except ImportError:
            print("  📦 正在安装缺少的依赖 openai...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                                   "--break-system-packages", "openai"])
        main()
    except KeyboardInterrupt: print("\n👋 配置流程已中断。")
