#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
终端需求对话 Agent（AI）：
1) 多轮对话收集需求
2) 输入"开始运行"触发需求冻结、生成 JSON 并自动执行
3) 支持 /show 查看摘要、/exit 退出
"""

import argparse
import itertools
import json
import os
import subprocess
import sys
import textwrap
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ai_utils import create_generation_config, get_ai_client, load_ai_config

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from script_locator import resolve_script

# 启用终端行编辑（方向键左右移动等）
try:
    import readline  # noqa: F401
except Exception:
    readline = None
try:
    from prompt_toolkit import prompt as pt_prompt
except Exception:
    pt_prompt = None

class Spinner:
    """终端转圈动画，用于等待 Gemini 响应时防止用户二次输入"""
    _FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, message: str = "思考中"):
        self._message = message
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "Spinner":
        if not (sys.stdout.isatty()):
            return self
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
            self._thread = None
        # 清除转圈行
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _spin(self) -> None:
        for frame in itertools.cycle(self._FRAMES):
            if self._stop_event.is_set():
                break
            sys.stdout.write(f"\r{frame} {self._message}...")
            sys.stdout.flush()
            self._stop_event.wait(0.1)

    def __enter__(self) -> "Spinner":
        return self.start()

    def __exit__(self, *_) -> None:
        self.stop()


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
SPEC_DIR = OUTPUT_ROOT / "requirement_specs"
# 加载全局配置
try:
    AI_CONFIG = load_ai_config()
    GEN_API_KEY = AI_CONFIG.get("api_key", "")
    GEN_MODEL = AI_CONFIG.get("model", "gemini-2.5-flash")
except Exception:
    AI_CONFIG = {"provider": "gemini", "api_key": "", "model": "gemini-2.5-flash", "base_url": ""}
    GEN_API_KEY, GEN_MODEL = "", "gemini-2.5-flash"

# 用户指定优先模型；若不可用则自动回退到已验证可用模型
DEFAULT_MODEL = GEN_MODEL
FALLBACK_MODELS = (GEN_MODEL, "gemini-2.0-flash", "gemini-1.5-pro")
EXECUTE_REQUIREMENTS_SCRIPT = resolve_script("execute_requirements.py")
ORG_AUTH_PATH = BASE_DIR / "config" / "credentials" / "organization_auth.json"


def _load_org_group_ids() -> str:
    """获取 group_ids，优先级：.env.local > organization_auth.json"""
    # 1. 尝试从 .env.local (local_config.py) 加载
    try:
        from local_config import load_local_group_id
        local_gid = load_local_group_id()
        if local_gid:
            return local_gid
    except Exception:
        pass

    # 2. 回退到 organization_auth.json
    try:
        data = load_json(ORG_AUTH_PATH)
        return str(data.get("group_ids", "")).strip()
    except Exception:
        return ""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_api_key(config_path: Path) -> str:
    # 优先使用已加载的全局 Key
    if GEN_API_KEY:
        return GEN_API_KEY
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


def make_config(response_mime_type: str, temperature: float, seed: Optional[int]):
    return create_generation_config(
        AI_CONFIG,
        response_mime_type=response_mime_type,
        temperature=temperature,
        seed=seed,
    )


def read_user_input(prompt_text: str) -> str:
    term = (os.environ.get("TERM") or "").strip().lower()
    use_prompt_toolkit = (
        pt_prompt is not None
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and term not in ("", "dumb")
    )
    if use_prompt_toolkit:
        return pt_prompt(prompt_text)
    return input(prompt_text)


def clean_terminal_text(text: str) -> str:
    if not text:
        return ""
    # 去除 ANSI 控制序列，避免终端显示错位/截断感
    import re

    text = re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text)
    return text.replace("\r", "")


def print_wrapped(prefix: str, text: str) -> None:
    if sys.stdout.isatty():
        try:
            cols = os.get_terminal_size().columns
        except OSError:
            cols = 100
    else:
        cols = 100
    cols = max(40, cols)
    body_width = max(20, cols - len(prefix))
    lines = []
    for part in clean_terminal_text(text).splitlines() or [""]:
        if not part.strip():
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                part,
                width=body_width,
                break_long_words=False,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=False,
            )
        )
    if not lines:
        lines = [""]
    print(f"{prefix}{lines[0]}")
    align = " " * len(prefix)
    for ln in lines[1:]:
        print(f"{align}{ln}")


def create_chat_with_fallback(client, model: str, temperature: float, seed: Optional[int]):
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


def generate_with_fallback(client, model: str, contents: str, config):
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


def send_chat_with_fallback(
    client: genai.Client,
    chat,
    current_model: str,
    prompt: str,
    temperature: float,
    seed: Optional[int],
) -> Tuple[object, object, str]:
    """
    发送聊天消息；若当前模型在 send_message 阶段失败（常见 404/NOT_FOUND），
    自动回退到候选模型并重试一次。
    返回: (response, chat_obj, model_name)
    """
    try:
        resp = chat.send_message(prompt)
        return resp, chat, current_model
    except Exception as exc:
        msg = str(exc)
        recoverable = (
            "NOT_FOUND" in msg
            or "is not found" in msg
            or "not supported for generateContent" in msg
        )
        if not recoverable:
            raise

        tried = [current_model] + [m for m in FALLBACK_MODELS if m != current_model]
        for m in tried[1:]:
            print(f"聊天模型 {current_model} 不可用，自动回退到 {m} ...")
            try:
                chat_config = make_config(response_mime_type="text/plain", temperature=temperature, seed=seed)
                new_chat = client.chats.create(model=m, config=chat_config)
                resp = new_chat.send_message(prompt)
                return resp, new_chat, m
            except Exception:
                continue
        raise


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
2) 采用“默认优先”策略：以下项若用户未明确指定，不要追问，直接使用默认值。
   - 导航布局: 左侧（pcNaviStyle=1）
   - 主题色: random
3) 如果信息不完整，只追问关键缺口（应用名称/行业场景、是否需要工作表规划、业务范围）。
4) 避免一次提太多问题，优先单问单答。
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
    "group_ids": "{_load_org_group_ids()}",
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
    "model": "{DEFAULT_MODEL}",
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
  "views": {{
    "enabled": true,
    "model": "{DEFAULT_MODEL}"
  }},
  "view_filters": {{
    "enabled": true,
    "model": "{DEFAULT_MODEL}"
  }},
  "mock_data": {{
    "enabled": true,
    "model": "{DEFAULT_MODEL}",
    "dry_run": false,
    "trigger_workflow": false
  }},

  "execution": {{
    "fail_fast": true,
    "dry_run": false
  }}
}}

规则：
1) 缺失项按上述默认值补齐。
2) app.name 若未明确，给出合理占位名：CRM自动化应用。
3) 不要新增未定义顶层字段。
4) 若对话中未明确提到导航布局，固定 app.navi_style.pcNaviStyle=1。
5) 若对话中未明确提到主题色，固定 app.color_mode=random。
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
    app.setdefault("name", "智能自动化应用")
    app.setdefault("group_ids", _load_org_group_ids())
    app.setdefault("icon_mode", "gemini_match")
    app.setdefault("color_mode", "random")
    # 默认主题色策略：未明确时强制 random
    if not str(app.get("color_mode", "")).strip():
        app["color_mode"] = "random"
    navi = app.get("navi_style") if isinstance(app.get("navi_style"), dict) else {}
    navi.setdefault("enabled", True)
    navi.setdefault("pcNaviStyle", 1)
    try:
        navi["pcNaviStyle"] = int(navi.get("pcNaviStyle", 1))
    except Exception:
        navi["pcNaviStyle"] = 1
    # 默认导航布局：左侧
    navi["pcNaviStyle"] = 1 if not isinstance(navi.get("pcNaviStyle"), int) else navi["pcNaviStyle"]
    app["navi_style"] = navi
    spec["app"] = app

    ws = spec.get("worksheets") if isinstance(spec.get("worksheets"), dict) else {}
    ws.setdefault("enabled", True)
    ws.setdefault("business_context", "通用企业管理场景")
    ws.setdefault("requirements", "")
    ws.setdefault("model", DEFAULT_MODEL)
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
    
    views = spec.get("views") if isinstance(spec.get("views"), dict) else {}
    views.setdefault("enabled", True)
    views.setdefault("model", ws.get("model", DEFAULT_MODEL))
    spec["views"] = views
    
    view_filters = spec.get("view_filters") if isinstance(spec.get("view_filters"), dict) else {}
    view_filters.setdefault("enabled", True)
    view_filters.setdefault("model", ws.get("model", DEFAULT_MODEL))
    spec["view_filters"] = view_filters

    mock_data = spec.get("mock_data") if isinstance(spec.get("mock_data"), dict) else {}
    mock_data.setdefault("enabled", True)
    mock_data.setdefault("model", ws.get("model", DEFAULT_MODEL))
    mock_data.setdefault("dry_run", False)
    mock_data.setdefault("trigger_workflow", False)
    spec["mock_data"] = mock_data

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
    parser = argparse.ArgumentParser(description="终端需求对话 Agent（AI）")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="AI 模型名")
    parser.add_argument("--output", default="", help="输出 JSON 路径（默认自动命名）")
    parser.add_argument("--max-turns", type=int, default=0, help="最大对话轮数（0 表示不限制）")
    parser.add_argument("--temperature", type=float, default=0.2, help="AI 温度")
    parser.add_argument("--seed", type=int, default=None, help="可选随机种子")
    parser.add_argument("--no-auto-execute", action="store_true", help="「开始运行」后不自动执行 execute_requirements.py")
    parser.add_argument("--execute-dry-run", action="store_true", help="「开始运行」自动执行时，以 dry-run 模式运行")
    parser.add_argument("--execute-verbose", action="store_true", help="「开始运行」自动执行时打印执行器详细输出")
    parser.add_argument("--continue-on-error", action="store_true", help="「开始运行」自动执行时，执行器遇错继续")
    args = parser.parse_args()

    client = get_ai_client(AI_CONFIG)
    output_path = Path(args.output).expanduser().resolve() if args.output else None
    chat, actual_model = create_chat_with_fallback(client, args.model, args.temperature, args.seed)
    if readline is not None:
        try:
            readline.parse_and_bind("set editing-mode emacs")
            readline.parse_and_bind("set enable-keypad on")
            readline.parse_and_bind("set keymap emacs")
        except Exception:
            pass

    transcript: List[Dict[str, str]] = []
    _hint = '\u300c\u5f00\u59cb\u8fd0\u884c\u300d'  # 「开始运行」
    print(f"需求对话已启动（模型: {actual_model}）。描述你的需求，输入{_hint}并回车开始执行；/show 查看摘要；/exit 退出。")

    turns = 0
    while True:
        if args.max_turns > 0 and turns >= args.max_turns:
            print("达到 max-turns，自动执行 \u300c\u5f00\u59cb\u8fd0\u884c\u300d。")
            cmd = "开始运行"
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
        if cmd == "开始运行":
            if not transcript:
                print("当前没有对话内容，请先输入你的需求。")
                continue
            prompt = build_spec_prompt(transcript)
            spinner = Spinner("正在生成需求 JSON").start()
            try:
                resp, _ = generate_with_fallback(
                    client=client,
                    model=actual_model,
                    contents=prompt,
                    config=make_config(response_mime_type="application/json", temperature=args.temperature, seed=args.seed),
                )
            finally:
                spinner.stop()
            spec = normalize_spec(extract_json(resp.text or ""))
            out = save_spec(spec, output=output_path)
            print(f"需求 JSON 已保存: {out}")
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
        transcript.append({"role": "user", "text": cmd})
        turns += 1
        prompt = build_chat_prompt(transcript, latest_user_input=cmd)
        spinner = Spinner("思考中").start()
        try:
            resp, chat, actual_model = send_chat_with_fallback(
                client=client,
                chat=chat,
                current_model=actual_model,
                prompt=prompt,
                temperature=args.temperature,
                seed=args.seed,
            )
        finally:
            spinner.stop()
        reply = (resp.text or "").strip() or "请继续补充你的需求，我会整理成可执行 JSON。"
        transcript.append({"role": "assistant", "text": reply})
        print()
        print_wrapped("Agent: ", reply)


if __name__ == "__main__":
    main()
