#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端需求对话 Agent（Gemini）：
1) 多轮对话收集需求
2) 输入 /done 冻结需求并生成标准 JSON（workflow_requirement_v1）
3) 支持 /save 手动保存当前版本、/show 查看摘要、/exit 退出
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from google import genai
from google.genai import types

# 启用终端行编辑（方向键左右移动等）
try:
    import readline  # noqa: F401
except Exception:
    readline = None
try:
    from prompt_toolkit import prompt as pt_prompt
except Exception:
    pt_prompt = None

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
SPEC_DIR = OUTPUT_ROOT / "requirement_specs"
GEMINI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
# 用户指定优先模型；若不可用则自动回退到官方稳定 Pro
DEFAULT_MODEL = "gemini-3.1-pro"
FALLBACK_MODELS = ("gemini-2.5-pro",)
EXECUTE_REQUIREMENTS_SCRIPT = BASE_DIR / "scripts" / "execute_requirements.py"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_api_key(config_path: Path) -> str:
    data = load_json(config_path)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"Gemini 配置缺少 api_key: {config_path}")
    return api_key


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Gemini 返回为空")
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
    raise ValueError(f"Gemini 未返回可解析 JSON:\n{text}")


def make_config(response_mime_type: str, temperature: float, seed: Optional[int]) -> types.GenerateContentConfig:
    kwargs = {"response_mime_type": response_mime_type, "temperature": temperature}
    if seed is not None:
        kwargs["seed"] = seed
    try:
        return types.GenerateContentConfig(**kwargs)
    except TypeError:
        kwargs.pop("seed", None)
        return types.GenerateContentConfig(**kwargs)


def read_user_input(prompt_text: str) -> str:
    if pt_prompt is not None and sys.stdin.isatty() and sys.stdout.isatty():
        return pt_prompt(prompt_text)
    return input(prompt_text)


def create_chat_with_fallback(client: genai.Client, model: str, temperature: float, seed: Optional[int]):
    tried = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_exc: Optional[Exception] = None
    for idx, m in enumerate(tried):
        try:
            chat_config = make_config(response_mime_type="text/plain", temperature=temperature, seed=seed)
            # 官方推荐：多轮聊天使用 chats.create + send_message
            chat = client.chats.create(model=m, config=chat_config)
            return chat, m
        except Exception as exc:
            last_exc = exc
            if idx < len(tried) - 1:
                print(f"模型 {m} 不可用，回退到 {tried[idx + 1]} ...")
    if last_exc:
        raise last_exc
    raise RuntimeError("无法创建 Gemini Chat 会话")


def generate_with_fallback(
    client: genai.Client,
    model: str,
    contents: str,
    config: types.GenerateContentConfig,
):
    tried = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_exc: Optional[Exception] = None
    for idx, m in enumerate(tried):
        try:
            return client.models.generate_content(model=m, contents=contents, config=config), m
        except Exception as exc:
            last_exc = exc
            if idx < len(tried) - 1:
                print(f"模型 {m} 不可用，回退到 {tried[idx + 1]} ...")
    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini 生成失败")


def build_chat_prompt(transcript: List[Dict[str, str]], latest_user_input: str) -> str:
    lines = []
    for turn in transcript[-30:]:
        role = turn.get("role", "user")
        text = turn.get("text", "")
        lines.append(f"{role.upper()}: {text}")
    transcript_text = "\n".join(lines).strip()
    return f"""
你是 HAP 自动化实施顾问。请继续和用户澄清需求，目标是最终可执行。

当前对话上下文：
{transcript_text}

用户最新输入：
{latest_user_input}

要求：
1) 用中文回复，简洁直接。
2) 如果信息不完整，优先追问关键缺口（应用目标、是否新建、工作表规划要求、icon、布局、导航、造数数量）。
3) 不输出 JSON；这是聊天阶段。
""".strip()


def build_spec_prompt(transcript: List[Dict[str, str]]) -> str:
    lines = []
    for t in transcript:
        lines.append(f"{t.get('role','user').upper()}: {t.get('text','')}")
    transcript_text = "\n".join(lines).strip()
    return f"""
你是需求结构化引擎。请根据以下终端对话，输出严格 JSON，schema_version 必须为 workflow_requirement_v1。

对话记录：
{transcript_text}

输出 JSON 结构（只输出 JSON，不要 markdown）：
{{
  "schema_version": "workflow_requirement_v1",
  "meta": {{
    "created_at": "{now_iso()}",
    "source": "terminal_gemini_chat",
    "conversation_summary": "100字以内总结"
  }},
  "app": {{
    "target_mode": "create_new",
    "name": "应用名称",
    "group_ids": "69a794589860d96373beeb4d",
    "icon_mode": "gemini_match",
    "color_mode": "random",
    "navi_style": {{
      "enabled": true,
      "pcNaviStyle": 1
    }}
  }},
  "worksheets": {{
    "enabled": true,
    "business_context": "业务背景",
    "requirements": "工作表规划要求",
    "model": "gemini-2.5-pro",
    "icon_update": {{
      "enabled": true,
      "refresh_auth": false
    }},
    "layout": {{
      "enabled": true,
      "requirements": "布局要求",
      "refresh_auth": false
    }}
  }},
  "seed_data": {{
    "enabled": true,
    "rows_per_table": 3,
    "delete_history_before_seed": false,
    "model": "gemini-2.5-pro"
  }},
  "execution": {{
    "fail_fast": true,
    "dry_run": false
  }}
}}

规则：
1) 缺失项按上述默认值补齐。
2) app.name 若未明确，给出合理占位名：CRM自动化应用。
3) rows_per_table 必须是正整数。
4) 不要新增未定义顶层字段。
""".strip()


def normalize_spec(raw: dict) -> dict:
    spec = dict(raw) if isinstance(raw, dict) else {}
    spec["schema_version"] = "workflow_requirement_v1"

    meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
    meta.setdefault("created_at", now_iso())
    meta.setdefault("source", "terminal_gemini_chat")
    meta.setdefault("conversation_summary", "")
    spec["meta"] = meta

    app = spec.get("app") if isinstance(spec.get("app"), dict) else {}
    app.setdefault("target_mode", "create_new")
    app.setdefault("name", "CRM自动化应用")
    app.setdefault("group_ids", "69a794589860d96373beeb4d")
    app.setdefault("icon_mode", "gemini_match")
    app.setdefault("color_mode", "random")
    navi = app.get("navi_style") if isinstance(app.get("navi_style"), dict) else {}
    navi.setdefault("enabled", True)
    navi.setdefault("pcNaviStyle", 1)
    try:
        navi["pcNaviStyle"] = int(navi.get("pcNaviStyle", 1))
    except Exception:
        navi["pcNaviStyle"] = 1
    app["navi_style"] = navi
    spec["app"] = app

    ws = spec.get("worksheets") if isinstance(spec.get("worksheets"), dict) else {}
    ws.setdefault("enabled", True)
    ws.setdefault("business_context", "通用企业管理场景")
    ws.setdefault("requirements", "")
    ws.setdefault("model", "gemini-2.5-pro")
    icon_update = ws.get("icon_update") if isinstance(ws.get("icon_update"), dict) else {}
    icon_update.setdefault("enabled", True)
    icon_update.setdefault("refresh_auth", False)
    ws["icon_update"] = icon_update
    layout = ws.get("layout") if isinstance(ws.get("layout"), dict) else {}
    layout.setdefault("enabled", True)
    layout.setdefault("requirements", "")
    layout.setdefault("refresh_auth", False)
    ws["layout"] = layout
    spec["worksheets"] = ws

    seed = spec.get("seed_data") if isinstance(spec.get("seed_data"), dict) else {}
    seed.setdefault("enabled", True)
    seed.setdefault("rows_per_table", 3)
    try:
        seed["rows_per_table"] = max(1, int(seed.get("rows_per_table", 3)))
    except Exception:
        seed["rows_per_table"] = 3
    seed.setdefault("delete_history_before_seed", False)
    seed.setdefault("model", "gemini-2.5-pro")
    spec["seed_data"] = seed

    execution = spec.get("execution") if isinstance(spec.get("execution"), dict) else {}
    execution.setdefault("fail_fast", True)
    execution.setdefault("dry_run", False)
    spec["execution"] = execution
    return spec


def save_spec(spec: dict, output: Optional[Path]) -> Path:
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    out = output.resolve() if output else (SPEC_DIR / f"requirement_spec_{now_ts()}.json").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = (SPEC_DIR / "requirement_spec_latest.json").resolve()
    latest.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def print_transcript_summary(transcript: List[Dict[str, str]]) -> None:
    user_count = len([t for t in transcript if t.get("role") == "user"])
    assistant_count = len([t for t in transcript if t.get("role") == "assistant"])
    print("会话摘要")
    print(f"- 用户消息数: {user_count}")
    print(f"- 助手消息数: {assistant_count}")
    if transcript:
        print(f"- 最近一条: {transcript[-1].get('role')} -> {transcript[-1].get('text','')[:120]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="终端需求对话 Agent（Gemini）")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--output", default="", help="输出 JSON 路径（默认自动命名）")
    parser.add_argument("--max-turns", type=int, default=0, help="最大对话轮数（0 表示不限制）")
    parser.add_argument("--temperature", type=float, default=0.2, help="Gemini 温度")
    parser.add_argument("--seed", type=int, default=None, help="可选随机种子")
    parser.add_argument("--no-auto-execute", action="store_true", help="/done 后不自动执行 execute_requirements.py")
    parser.add_argument("--execute-dry-run", action="store_true", help="/done 自动执行时，以 dry-run 模式运行")
    parser.add_argument("--execute-verbose", action="store_true", help="/done 自动执行时打印执行器详细输出")
    parser.add_argument("--continue-on-error", action="store_true", help="/done 自动执行时，执行器遇错继续")
    args = parser.parse_args()

    api_key = load_api_key(GEMINI_CONFIG_PATH)
    client = genai.Client(api_key=api_key)
    output_path = Path(args.output).expanduser().resolve() if args.output else None
    chat, actual_model = create_chat_with_fallback(client, args.model, args.temperature, args.seed)

    transcript: List[Dict[str, str]] = []
    print(f"需求对话已启动（模型: {actual_model}）。输入 /done 生成并执行；/save 立即保存；/show 查看摘要；/exit 退出。")

    turns = 0
    while True:
        if args.max_turns > 0 and turns >= args.max_turns:
            print("达到 max-turns，自动执行 /done。")
            cmd = "/done"
        else:
            cmd = read_user_input("\n你: ").strip()

        if not cmd:
            continue

        if cmd == "/exit":
            print("已退出，不保存。")
            return
        if cmd == "/show":
            print_transcript_summary(transcript)
            continue
        if cmd in ("/save", "/done"):
            if not transcript:
                print("当前没有对话内容，无法生成需求 JSON。")
                if cmd == "/done":
                    return
                continue
            prompt = build_spec_prompt(transcript)
            resp, _ = generate_with_fallback(
                client=client,
                model=actual_model,
                contents=prompt,
                config=make_config(response_mime_type="application/json", temperature=args.temperature, seed=args.seed),
            )
            spec = normalize_spec(extract_json(resp.text or ""))
            out = save_spec(spec, output=output_path)
            print(f"需求 JSON 已保存: {out}")
            if cmd == "/done":
                if not args.no_auto_execute:
                    exec_cmd = [sys.executable, str(EXECUTE_REQUIREMENTS_SCRIPT), "--spec-json", str(out)]
                    if args.execute_dry_run:
                        exec_cmd.append("--dry-run")
                    if args.execute_verbose:
                        exec_cmd.append("--verbose")
                    if args.continue_on_error:
                        exec_cmd.append("--continue-on-error")
                    print("\n开始自动执行需求 ...")
                    proc = subprocess.run(exec_cmd, check=False)
                    if proc.returncode != 0:
                        raise SystemExit(proc.returncode)
                return
            continue

        transcript.append({"role": "user", "text": cmd})
        turns += 1
        prompt = build_chat_prompt(transcript, latest_user_input=cmd)
        resp = chat.send_message(prompt)
        reply = (resp.text or "").strip() or "请继续补充你的需求，我会整理成可执行 JSON。"
        transcript.append({"role": "assistant", "text": reply})
        print(f"\nAgent: {reply}")


if __name__ == "__main__":
    main()
