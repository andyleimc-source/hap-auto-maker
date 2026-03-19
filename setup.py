#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP Auto 一键初始化脚本
=======================
首次克隆后只需运行此脚本，按提示填写即可完成全部配置。

用法：
    python3 setup.py            # 首次初始化（已有配置自动跳过）
    python3 setup.py --force    # 强制重新初始化（显示当前值，回车保留，输入新值覆盖）
    python3 setup.py --show     # 查看当前配置，并可按提示修改 AI 配置
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CRED_DIR = BASE_DIR / "config" / "credentials"
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))

from ai_utils import (
    AI_CONFIG_PATH,
    DEFAULT_DEEPSEEK_BASE_URL,
    default_model_for_provider,
    load_ai_config,
    mask_secret,
)

# 占位符列表，匹配到这些值视为"未填写"
_PLACEHOLDERS = {
    "YOUR_HAP_APP_KEY",
    "YOUR_HAP_SECRET_KEY",
    "YOUR_HAP_PROJECT_ID",
    "YOUR_HAP_OWNER_ID",
    "YOUR_GEMINI_API_KEY",
    "YOUR_GEMINI_MODEL",
    "YOUR_DEEPSEEK_API_KEY",
    "YOUR_DEEPSEEK_MODEL",
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
    
    # 特殊规则：输入 '-' 表示清除该项内容（设为空字符串）
    if val == "-":
        return ""
    
    return val if val else default


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


def _looks_like_prompt_artifact(val: str) -> bool:
    """识别误写入配置文件的交互提示文本，避免作为默认值继续回显。"""
    text = str(val or "").strip()
    if not text:
        return False
    markers = (
        "请选择 AI 平台",
        "Deepseek API Key",
        "Gemini API Key",
        "获取地址:",
        "1. Gemini",
        "2. DeepSeek",
        "[2]: 2",
    )
    return any(marker in text for marker in markers)


def _ask_with_validator(prompt: str, default: str = "", validator=None, error_message: str = "输入无效，请重试。") -> str:
    """带校验的输入；校验失败时提示并重新输入。"""
    while True:
        val = ask(prompt, default=default)
        if validator is None or validator(val):
            return val
        print(f"   ⚠ {error_message}")


def _is_non_artifact_text(val: str) -> bool:
    text = str(val or "").strip()
    return bool(text) and not _looks_like_prompt_artifact(text)


def _is_valid_ai_key(provider: str, val: str) -> bool:
    text = str(val or "").strip()
    if not text or _looks_like_prompt_artifact(text):
        return False
    if provider == "deepseek":
        return text.startswith("sk-")
    return len(text) >= 16


def _is_valid_ai_model_choice(choice: str, model_options: dict) -> bool:
    return str(choice or "").strip() in model_options


def step_install_deps():
    """安装 Python 依赖 + Playwright 浏览器"""
    print("\n📦 [1/4] 安装 Python 依赖...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
                           "requests", "google-genai", "openai", "playwright", "prompt-toolkit"])
    print("🌐 安装 Playwright Chromium...")
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def _write_ai_config(data: dict) -> None:
    AI_CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if data.get("provider") == "gemini":
        legacy = {
            "api_key": data.get("api_key", ""),
            "model": data.get("model", default_model_for_provider("gemini")),
        }
        (CRED_DIR / "gemini_auth.json").write_text(
            json.dumps(legacy, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _load_existing_ai_config() -> dict:
    try:
        return load_ai_config()
    except Exception:
        return {}


def step_ai(force=False):
    """配置统一 AI 平台"""
    dst = AI_CONFIG_PATH
    existing = _load_existing_ai_config()
    if dst.exists() and not force:
        return

    old_provider = existing.get("provider", "gemini")
    old_key = existing.get("api_key", "")
    old_model = existing.get("model", default_model_for_provider(old_provider))
    old_base_url = existing.get("base_url", "")

    print("\n🔑 [2/4] 配置 AI 平台")
    print("   1. Gemini")
    print("      获取地址: https://aistudio.google.com/apikey")
    print("   2. DeepSeek")
    print("      获取地址: https://platform.deepseek.com/api_keys")

    provider_default = "1" if old_provider == "gemini" else "2"
    provider_choice = _ask_with_validator(
        "   请选择 AI 平台（1=Gemini, 2=DeepSeek）",
        default=provider_default,
        validator=lambda x: x in {"1", "2"},
        error_message="请输入 1 或 2。",
    )
    provider = "deepseek" if provider_choice == "2" else "gemini"
    default_model = old_model if provider == old_provider and old_model else default_model_for_provider(provider)

    if old_key and old_key not in _PLACEHOLDERS and provider == old_provider:
        key = _ask_with_validator(
            f"   {provider.title()} API Key [{_mask(old_key)}]",
            validator=lambda x: _is_valid_ai_key(provider, x) or (x == "" and _is_valid_ai_key(provider, old_key)),
            error_message="API Key 格式不正确，或输入内容看起来像提示文本。",
        ) or old_key
    else:
        key = _ask_with_validator(
            f"   请输入 {provider.title()} API Key",
            validator=lambda x: _is_valid_ai_key(provider, x),
            error_message="API Key 格式不正确，或输入内容看起来像提示文本。",
        )

    if provider == "gemini":
        model_options = {
            "1": ("gemini-2.5-flash", "响应更快，适合日常生成"),
            "2": ("gemini-2.5-pro", "能力更强，适合复杂任务"),
        }
        base_url = ""
    else:
        model_options = {
            "1": ("deepseek-chat", "通用对话模型，速度更快，适合大多数场景"),
            "2": ("deepseek-reasoner", "推理模型，适合复杂分析、多步推导"),
        }
        base_url = old_base_url or DEFAULT_DEEPSEEK_BASE_URL

    print("   请选择模型:")
    for option, (model_name, description) in model_options.items():
        print(f"      {option}. {model_name}：{description}")

    default_model_choice = next(
        (option for option, (model_name, _) in model_options.items() if model_name == default_model),
        "1",
    )
    model_choice = _ask_with_validator(
        "   请输入模型序号",
        default=default_model_choice,
        validator=lambda x: _is_valid_ai_model_choice(x, model_options),
        error_message="请输入上面列出的模型序号。",
    )
    model = model_options[model_choice][0]
    data = {
        "provider": provider,
        "api_key": key or ("YOUR_GEMINI_API_KEY" if provider == "gemini" else "YOUR_DEEPSEEK_API_KEY"),
        "model": model or default_model_for_provider(provider),
        "base_url": base_url,
    }
    _write_ai_config(data)
    print(f"   ✔ 已写入 {dst.name}")


def step_org_auth(force=False):
    """配置 HAP 组织级密钥"""
    dst = CRED_DIR / "organization_auth.json"
    existing = _load_json_safe(dst)

    if dst.exists() and not force:
        return

    print("\n🏢 [3/4] 配置 HAP 组织级密钥")
    print("   获取路径: 组织管理 → 集成 → 其他 → 开放接口 → 查看密钥")
    print("   快捷地址: https://www.mingdao.com/admin/integrationothers/<你的组织ID>")

    # 定义字段：(json_key, 显示名, 提示文字, 是否敏感, 是否必填)
    # group_ids 不在此处询问，由 step_group_init() 通过下拉选择写入
    fields = [
        ("app_key",    "app_key",    None, True,  True),
        ("secret_key", "secret_key", None, True,  True),
        ("project_id", "project_id", "获取 project_id: 组织管理 → 组织 → 组织信息 → 编号（ID）", False, True),
        ("owner_id",   "owner_id",   "获取 owner_id: 点击群聊中个人头像，地址栏中 https://www.mingdao.com/user_xxx 的 xxx 部分", False, True),
    ]

    # 如果已有配置，先展示当前值
    valid_existing = {
        key: ("" if _looks_like_prompt_artifact(existing.get(key, "")) else existing.get(key, ""))
        for key, *_ in fields
    }

    if valid_existing and any(valid_existing.get(f[0], "") not in ("", *_PLACEHOLDERS) for f in fields):
        print("\n   📋 当前配置：")
        for key, name, _, sensitive, _ in fields:
            val = valid_existing.get(key, "")
            print(f"      {name:12s} = {_display_val(val, sensitive)}")
        print("   （直接回车保留当前值，输入新值则覆盖）\n")

    results = {}
    for key, name, hint, sensitive, required in fields:
        if hint:
            print(f"\n   {hint}")
        old_val = valid_existing.get(key, "")
        # 占位符不作为默认值展示
        default = old_val if old_val and old_val not in _PLACEHOLDERS else ""
        if default and sensitive:
            # 敏感字段显示脱敏值作为提示
            raw_input = _ask_with_validator(
                f"   {name} [{_mask(default)}]",
                validator=lambda x: x == "" or _is_non_artifact_text(x),
                error_message="输入内容看起来像提示文本，请重新输入真实值；直接回车可保留当前值。",
            )
            # 同 show_config: 空字符串回车保留，'-' 清空
            if raw_input == "" and old_val and old_val not in _PLACEHOLDERS:
                results[key] = old_val
            else:
                results[key] = raw_input
        else:
            results[key] = _ask_with_validator(
                f"   {name}",
                default=default,
                validator=lambda x: (bool(str(x or "").strip()) and not _looks_like_prompt_artifact(x)) or (default and x == default),
                error_message="输入内容看起来像提示文本，或为空，请重新输入真实值。",
            )

    # 写入（group_ids 保留已有值，由 step_group_init 下拉选择后覆盖）
    data = {}
    data["app_key"] = results["app_key"] or "YOUR_HAP_APP_KEY"
    data["secret_key"] = results["secret_key"] or "YOUR_HAP_SECRET_KEY"
    data["project_id"] = results["project_id"] or "YOUR_HAP_PROJECT_ID"
    data["owner_id"] = results["owner_id"] or "YOUR_HAP_OWNER_ID"
    data["group_ids"] = existing.get("group_ids", "")
    dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"   ✔ 已写入 {dst.name}")


def step_login_and_auth(force=False):
    """配置登录凭据 → 自动刷新 auth_config.py"""
    login_dst = CRED_DIR / "login_credentials.py"
    auth_dst = CRED_DIR / "auth_config.py"

    if login_dst.exists() and auth_dst.exists() and not force:
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
                [sys.executable, str(BASE_DIR / "scripts" / "auth" / "refresh_auth.py"), "--headless"],
                cwd=str(BASE_DIR),
            )
        except subprocess.CalledProcessError:
            print("   ⚠️  自动登录失败，请稍后手动运行: python3 scripts/auth/refresh_auth.py")
    else:
        print("   ⚠️  未填写账号密码，跳过自动认证。稍后手动运行: python3 scripts/auth/refresh_auth.py")


def _read_all_config() -> dict:
    """读取所有配置文件，返回统一的 dict"""
    import re as _re
    result = {}

    ai = _load_existing_ai_config()
    result["ai_provider"] = ai.get("provider", "gemini")
    result["ai_api_key"] = ai.get("api_key", "")
    result["ai_model"] = ai.get("model", default_model_for_provider(result["ai_provider"]))
    result["ai_base_url"] = ai.get("base_url", "")

    # 组织密钥
    org = _load_json_safe(CRED_DIR / "organization_auth.json")
    for k in ("app_key", "secret_key", "project_id", "owner_id", "group_ids"):
        result[k] = org.get(k, "")

    # 登录凭据
    login_dst = CRED_DIR / "login_credentials.py"
    if login_dst.exists():
        try:
            text = login_dst.read_text(encoding="utf-8")
            m = _re.search(r'LOGIN_ACCOUNT\s*=\s*"(.+?)"', text)
            result["account"] = m.group(1) if m else ""
            m = _re.search(r'LOGIN_PASSWORD\s*=\s*"(.+?)"', text)
            result["password"] = m.group(1) if m else ""
        except Exception:
            result["account"] = ""
            result["password"] = ""
    else:
        result["account"] = ""
        result["password"] = ""

    return result


def _sync_group_id_to_org_auth(group_id: str) -> None:
    """将选中的分组 ID 同步写入 organization_auth.json 的 group_ids 字段。"""
    org_dst = CRED_DIR / "organization_auth.json"
    data = _load_json_safe(org_dst)
    data["group_ids"] = group_id
    org_dst.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def step_group_init(force=False):
    """应用分组初始化引导：选择或新建"""
    # 导入本地配置处理
    sys.path.append(str(BASE_DIR / "scripts" / "hap"))
    try:
        from local_config import load_local_group_id, save_local_group_id
        from list_groups import get_groups
    except ImportError:
        print("   ⚠️  无法加载 HAP 基础模块，跳过分组初始化。")
        return

    # 如果已经有选中分组且不是强制模式，跳过
    current_group_id = load_local_group_id()
    if current_group_id and not force:
        return

    print("\n📁 [Extra] 初始化应用工作分组")
    groups = get_groups()
    if not groups:
        print("   ⚠️  未能获取到分组列表，请检查网络或授权。")
        return

    print("   请选择一个应用分组：")
    for i, g in enumerate(groups, 1):
        mark = " (当前)" if g["groupId"] == current_group_id else ""
        print(f"      {i}. {g['name']}{mark}")
    print(f"      n. 新建分组")

    choice = ask("   请输入序号", default="1")
    if choice.lower() == "n":
        new_name = ask("   请输入新分组名称")
        if new_name:
            try:
                from create_group import create_group
                new_group = create_group(new_name)
                selected_group_id = new_group["groupId"]
                save_local_group_id(selected_group_id)
                _sync_group_id_to_org_auth(selected_group_id)
                print(f"   ✔ 分组已创建并选中: {new_name}")
            except Exception as e:
                print(f"   ❌ 创建分组失败: {e}")
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(groups):
                selected_group_id = groups[idx]["groupId"]
                save_local_group_id(selected_group_id)
                _sync_group_id_to_org_auth(selected_group_id)
                print(f"   ✔ 已选中分组: {groups[idx]['name']}")
        except (ValueError, IndexError):
            print("   ⚠️  无效选择。")


def show_config():
    """查看当前所有配置内容"""
    conf = _read_all_config()
    print("\n" + "=" * 60)
    print("📋 HAP Auto 当前完整配置")
    print("=" * 60)

    print("\n[AI]")
    print(f"   Provider:  {conf['ai_provider']}")
    print(f"   API Key:   {mask_secret(conf['ai_api_key'])}")
    print(f"   Model:     {conf['ai_model']}")
    print(f"   Base URL:  {conf['ai_base_url'] or '(默认)'}")

    print("\n[HAP Organization]")
    print(f"   AppKey:    {_mask(conf['app_key'])}")
    print(f"   SecretKey: {_mask(conf['secret_key'])}")
    print(f"   ProjectID: {conf['project_id']}")
    print(f"   OwnerID:   {conf['owner_id']}")
    print(f"   GroupIDs:  {conf['group_ids'] or '(未指定)'}")

    print("\n[Login Credentials]")
    print(f"   Account:   {conf['account']}")
    print(f"   Password:  {_mask(conf['password'])}")

    print("\n" + "=" * 60)
    print("提示：可运行 python3 setup.py --force 重新初始化全部配置")
    print("=" * 60 + "\n")

    if sys.stdin.isatty():
        choice = ask("是否立即修改 AI 配置？(y/N)", default="N").strip().lower()
        if choice in {"y", "yes"}:
            step_ai(force=True)
            print("\nAI 配置已更新，最新结果如下：")
            refreshed = _read_all_config()
            print(f"   Provider:  {refreshed['ai_provider']}")
            print(f"   API Key:   {mask_secret(refreshed['ai_api_key'])}")
            print(f"   Model:     {refreshed['ai_model']}")
            print(f"   Base URL:  {refreshed['ai_base_url'] or '(默认)'}")


def main():
    parser = argparse.ArgumentParser(description="HAP Auto 初始化与配置工具")
    parser.add_argument("--force", action="store_true", help="强制重跑初始化步骤")
    parser.add_argument("--show", action="store_true", help="查看当前配置，并可修改 AI 配置")
    args = parser.parse_args()

    if args.show:
        show_config()
        return

    print("\n" + "🚀" * 20)
    print("  HAP Auto 自动化环境初始化")
    print("🚀" * 20)

    try:
        step_install_deps()
        step_ai(args.force)
        step_org_auth(args.force)
        step_login_and_auth(args.force)
        step_group_init(args.force)

        print("\n" + "✨" * 20)
        print("  所有配置已完成！")
        print("  现在你可以运行主流程：python3 scripts/run_app_pipeline.py")
        print("✨" * 20 + "\n")

    except KeyboardInterrupt:
        print("\n\n👋 已由用户取消。")
    except Exception as e:
        print(f"\n\n❌ 初始化过程中发生错误: {e}")


if __name__ == "__main__":
    main()
