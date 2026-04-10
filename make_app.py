#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 应用创建入口（Claude Code 专用）

用法（由 Claude Code 调用，无交互）：
    python3 make_app.py --requirements "需求描述文本"
    python3 make_app.py --requirements "..." --no-execute   # 只生成 spec，不执行
    python3 make_app.py --requirements "..." --dry-run      # 执行器空跑模式
    python3 make_app.py --spec-json path/to/spec.json       # 跳过 AI，直接执行已有 spec
"""

import argparse
import importlib.util
import json
import subprocess
import sys
import sysconfig
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HAP_DIR = BASE_DIR / "scripts" / "hap"
if str(HAP_DIR) not in sys.path:
    sys.path.insert(0, str(HAP_DIR))

from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config, resolve_effective_model_name
from execute_requirements import normalize_spec
from i18n import (
    normalize_language,
    set_runtime_language,
)
from script_locator import resolve_script
from utils import now_iso, now_ts

EXECUTE_SCRIPT = resolve_script("execute_requirements.py")
SPEC_DIR = BASE_DIR / "data" / "outputs" / "requirement_specs"


REQUIRED_RUNTIME_DEPENDENCY_MODULES = [
    ("requests", "requests"),
    ("openai", "openai"),
    ("google-genai", "google.genai"),
    ("playwright", "playwright"),
    # 造数阶段 mock.faker_mapping 会直接 import faker
    ("faker", "faker"),
]

OPTIONAL_RUNTIME_DEPENDENCY_MODULES = [
    # parse_ai_json 缺少该依赖时会退化为严格解析，不应阻断主流程。
    ("json-repair", "json_repair"),
]


def _load_org_group_ids() -> str:
    import warnings
    try:
        from local_config import load_local_group_id
        gid = load_local_group_id()
        if gid:
            return gid
    except ImportError:
        pass  # local_config 不存在是正常情况
    except Exception as e:
        warnings.warn(f"load_local_group_id 失败，回退到 organization_auth.json: {e}")
    org_auth = BASE_DIR / "config" / "credentials" / "organization_auth.json"
    try:
        data = json.loads(org_auth.read_text(encoding="utf-8"))
        return str(data.get("group_ids", "")).strip()
    except FileNotFoundError:
        pass  # 配置文件不存在时返回空字符串是预期行为
    except Exception as e:
        warnings.warn(f"读取 organization_auth.json 失败: {e}")
    return ""


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("AI 返回为空")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"AI 未返回可解析 JSON:\n{text[:500]}")


def save_spec(spec: dict, output=None) -> Path:
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(output).resolve() if output else (SPEC_DIR / f"requirement_spec_{now_ts()}.json").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = (SPEC_DIR / "requirement_spec_latest.json").resolve()
    latest.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def build_spec_prompt(requirements: str, language: str = "zh") -> str:
    lang = normalize_language(language)
    is_en = lang == "en"
    group_ids = _load_org_group_ids()
    app_name_hint = "Extract from requirement, in English" if is_en else "【从需求提取】应用的完整名称，若未明确则根据业务场景推断合理名称"
    biz_hint = "Describe business scenario in English (1-3 sentences)" if is_en else "【从需求提取】用1-3句话描述业务场景"
    req_hint = "Worksheet quantity/functional requirements in English; empty string if not mentioned" if is_en else "【从需求提取】工作表数量/功能要求，若未提及则留空字符串"
    layout_hint = "Layout requirements in English; empty string if not mentioned" if is_en else "【从需求提取】布局要求，若未提及则留空字符串"
    summary_hint = "Summary in English within 100 chars" if is_en else "100字以内总结"
    lang_rule = "All natural-language values must be English." if is_en else "自然语言字段默认中文。"
    rules_block = (
        "1. app.name must be replaced with a real app name.\n"
        "2. worksheets.business_context must be replaced with real business context.\n"
        "3. Replace all placeholder text; if not mentioned, use empty string.\n"
        "4. If navigation is not specified, keep pcNaviStyle=1; if color not specified, keep color_mode=random.\n"
        "5. Output JSON only (no markdown).\n"
        "6. All natural-language fields must be in English."
    ) if is_en else (
        "1. app.name 必须替换为真实应用名称，禁止保留【从需求提取】字样。\n"
        "2. worksheets.business_context 必须替换为真实业务场景描述。\n"
        "3. 其余【从需求提取】占位符同理，无相关信息则填空字符串。\n"
        "4. 若未提及导航布局，固定 pcNaviStyle=1；若未提及主题色，固定 color_mode=random。\n"
        "5. 只输出 JSON，不要 markdown 代码块。"
    )
    intro = (
        "You are a requirements structuring engine. Convert the user requirements into strict JSON. "
        "schema_version must be workflow_requirement_v1."
        if is_en
        else "你是需求结构化引擎。请根据以下用户需求，输出严格 JSON，schema_version 必须为 workflow_requirement_v1。"
    )
    return f"""
{intro}

用户需求：
{requirements}

输出 JSON 结构（只输出 JSON，不要 markdown）：
{{
  "schema_version": "workflow_requirement_v1",
  "meta": {{
    "created_at": "{now_iso()}",
    "source": "claude_code_chat",
    "conversation_summary": "{summary_hint}",
    "language": "{lang}"
  }},
  "app": {{
    "target_mode": "create_new",
    "name": "{app_name_hint}",
    "group_ids": "{group_ids}",
    "icon_mode": "ai_match",
    "color_mode": "random",
    "navi_style": {{
      "enabled": true,
      "pcNaviStyle": 1
    }}
  }},
  "worksheets": {{
    "enabled": true,
    "business_context": "{biz_hint}",
    "requirements": "{req_hint}",
    "icon_update": {{
      "enabled": true,
      "refresh_auth": false
    }},
    "layout": {{
      "enabled": true,
      "requirements": "{layout_hint}",
      "refresh_auth": false
    }}
  }},
  "views": {{
    "enabled": true
  }},
  "view_filters": {{
    "enabled": true
  }},
  "mock_data": {{
    "enabled": true,
    "dry_run": false,
    "trigger_workflow": false
  }},
  "execution": {{
    "fail_fast": true,
    "dry_run": false
  }}
}}

规则：
{rules_block}
额外语言要求：{lang_rule}
""".strip()


def generate_spec(requirements: str, ai_config: dict, language: str = "zh") -> dict:
    client = get_ai_client(ai_config)
    model = ai_config["model"]
    provider = ai_config.get("provider", "")
    effective_model = resolve_effective_model_name(provider, model)
    lang = normalize_language(language)
    prompt = build_spec_prompt(requirements, language=lang)
    if effective_model != model:
        print(f"正在生成需求 spec（配置模型: {model}，实际模型: {effective_model}）...")
    else:
        print(f"正在生成需求 spec（模型: {model}）...")
    resp = client.models.generate_content(
        model=model,
        contents=prompt, 
        config=create_generation_config(
            ai_config,
            response_mime_type="application/json",
            temperature=0.2,
            request_timeout_sec=300,
            stream_idle_timeout_sec=60,
            stream_total_timeout_sec=420,
            stream_fallback_non_stream=True,
        ),
    )
    raw = extract_json(resp.text or "")
    return normalize_spec(raw, default_language=lang)


def _find_missing_runtime_packages(dependencies: list[tuple[str, str]]) -> list[str]:
    missing: list[str] = []
    for package_name, module_name in dependencies:
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)
    return missing


def _in_virtualenv() -> bool:
    return bool(getattr(sys, "real_prefix", None) or (hasattr(sys, "base_prefix") and sys.prefix != sys.base_prefix))


def _is_externally_managed_environment() -> bool:
    try:
        stdlib = Path(sysconfig.get_path("stdlib") or "")
    except Exception:
        return False
    if not stdlib:
        return False
    marker = stdlib / "EXTERNALLY-MANAGED"
    return marker.exists()


def _build_env_fix_hint() -> str:
    return (
        "建议使用虚拟环境：\n"
        "  python3 -m venv .venv\n"
        "  source .venv/bin/activate\n"
        "  pip install -r requirements.txt"
    )


def ensure_runtime_dependencies(auto_install: bool = True, deps_mode: str = "auto") -> None:
    optional_missing = _find_missing_runtime_packages(OPTIONAL_RUNTIME_DEPENDENCY_MODULES)
    if optional_missing:
        print(
            "检测到可选依赖缺失："
            + ", ".join(optional_missing)
            + "（将降级运行，建议在虚拟环境中安装 requirements.txt 以提升 AI JSON 容错能力）"
        )

    missing = _find_missing_runtime_packages(REQUIRED_RUNTIME_DEPENDENCY_MODULES)
    if not missing:
        return

    print(f"检测到缺少运行依赖：{', '.join(missing)}")
    mode = (deps_mode or "auto").strip().lower()
    if mode not in {"auto", "check", "install", "skip"}:
        raise ValueError(f"未知 deps_mode: {deps_mode}")

    if mode == "skip":
        print("已按 --deps-mode=skip 跳过依赖安装检查，后续若报 ImportError 请先安装 requirements.txt")
        return

    if mode == "check":
        raise RuntimeError("缺少运行依赖（check 模式不自动安装）。\n" + _build_env_fix_hint())

    if not auto_install:
        raise RuntimeError("缺少运行依赖，请先安装后重试。")

    if mode == "auto" and (not _in_virtualenv()) and _is_externally_managed_environment():
        raise RuntimeError(
            "当前 Python 环境受 PEP 668 管理（externally-managed），为避免破坏系统环境，已停止自动安装依赖。\n"
            f"当前解释器: {sys.executable}\n"
            + _build_env_fix_hint()
            + "\n如需强制安装，请显式传 --deps-mode install（不推荐）。"
        )

    install_cmd = [sys.executable, "-m", "pip", "install", *missing]
    print(f"正在安装依赖: {' '.join(install_cmd)}")
    proc = subprocess.run(install_cmd, check=False)
    if proc.returncode != 0:
        if _is_externally_managed_environment() and not _in_virtualenv():
            raise RuntimeError(
                f"依赖安装失败，退出码={proc.returncode}。\n"
                "检测到 externally-managed 环境，无法在系统 Python 直接 pip install。\n"
                + _build_env_fix_hint()
            )
        raise RuntimeError(f"依赖安装失败，退出码={proc.returncode}")

    still_missing = _find_missing_runtime_packages(REQUIRED_RUNTIME_DEPENDENCY_MODULES)
    if still_missing:
        raise RuntimeError(f"依赖安装后仍缺失：{', '.join(still_missing)}")
    print("依赖检查完成。")


def main():
    parser = argparse.ArgumentParser(description="HAP 应用创建入口（Claude Code 专用）")
    parser.add_argument("--requirements", default="", help="需求描述文本（由 Claude 整理后传入）")
    parser.add_argument("--no-execute", action="store_true", help="只生成 spec，不执行")
    parser.add_argument("--dry-run", action="store_true", help="执行器空跑模式")
    parser.add_argument("--spec-json", default="", help="跳过 AI 生成，直接执行已有 spec 文件路径")
    parser.add_argument("--output", default="", help="spec 输出路径（默认自动命名）")
    parser.add_argument("--config", default=str(AI_CONFIG_PATH), help="AI 配置 JSON 路径")
    parser.add_argument("--language", default="zh", choices=["zh", "en"], help="应用生成语言（zh/en）")
    parser.add_argument("--deps-mode", default="auto", choices=["auto", "check", "install", "skip"], help="依赖处理策略")
    args = parser.parse_args()
    lang = normalize_language(args.language)
    set_runtime_language(lang)

    # 模式一：直接使用已有 spec 文件
    if args.spec_json:
        spec_path = Path(args.spec_json).expanduser().resolve()
        if not spec_path.exists():
            print(f"错误：spec 文件不存在: {spec_path}", file=sys.stderr)
            sys.exit(1)
        print(f"使用已有 spec: {spec_path}")
    else:
        # 模式二：从 requirements 文本生成 spec
        requirements = args.requirements.strip()
        if not requirements:
            print("错误：请提供 --requirements 需求描述文本，或 --spec-json 已有 spec 路径。", file=sys.stderr)
            sys.exit(1)

        ai_config = load_ai_config(Path(args.config).expanduser().resolve())
        spec = generate_spec(requirements, ai_config, language=lang)
        output_path = Path(args.output).expanduser().resolve() if args.output else None
        spec_path = save_spec(spec, output=output_path)
        print(f"需求 spec 已生成: {spec_path}")
        print(f"应用名称: {spec.get('app', {}).get('name', '未知')}")

    if args.no_execute:
        print("（--no-execute 模式，跳过执行）")
        return

    ensure_runtime_dependencies(auto_install=True, deps_mode=args.deps_mode)

    # 执行
    exec_cmd = [sys.executable, str(EXECUTE_SCRIPT), "--spec-json", str(spec_path)]
    exec_cmd.extend(["--language", lang])
    if args.dry_run:
        exec_cmd.append("--dry-run")
    print(f"\n开始执行需求...")
    proc = subprocess.run(exec_cmd, check=False)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
