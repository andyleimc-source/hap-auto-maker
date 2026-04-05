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
import json
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HAP_DIR = BASE_DIR / "scripts" / "hap"
if str(HAP_DIR) not in sys.path:
    sys.path.insert(0, str(HAP_DIR))

from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config
from execute_requirements import normalize_spec
from script_locator import resolve_script
from utils import now_iso, now_ts

EXECUTE_SCRIPT = resolve_script("execute_requirements.py")
SPEC_DIR = BASE_DIR / "data" / "outputs" / "requirement_specs"


def _load_org_group_ids() -> str:
    try:
        from local_config import load_local_group_id
        gid = load_local_group_id()
        if gid:
            return gid
    except Exception:
        pass
    org_auth = BASE_DIR / "config" / "credentials" / "organization_auth.json"
    try:
        data = json.loads(org_auth.read_text(encoding="utf-8"))
        return str(data.get("group_ids", "")).strip()
    except Exception:
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


def build_spec_prompt(requirements: str) -> str:
    group_ids = _load_org_group_ids()
    return f"""
你是需求结构化引擎。请根据以下用户需求，输出严格 JSON，schema_version 必须为 workflow_requirement_v1。

用户需求：
{requirements}

输出 JSON 结构（只输出 JSON，不要 markdown）：
{{
  "schema_version": "workflow_requirement_v1",
  "meta": {{
    "created_at": "{now_iso()}",
    "source": "claude_code_chat",
    "conversation_summary": "100字以内总结"
  }},
  "app": {{
    "target_mode": "create_new",
    "name": "【从需求提取】应用的完整名称，若未明确则根据业务场景推断合理名称",
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
    "business_context": "【从需求提取】用1-3句话描述业务场景",
    "requirements": "【从需求提取】工作表数量/功能要求，若未提及则留空字符串",
    "icon_update": {{
      "enabled": true,
      "refresh_auth": false
    }},
    "layout": {{
      "enabled": true,
      "requirements": "【从需求提取】布局要求，若未提及则留空字符串",
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
1. app.name 必须替换为真实应用名称，禁止保留【从需求提取】字样。
2. worksheets.business_context 必须替换为真实业务场景描述。
3. 其余【从需求提取】占位符同理，无相关信息则填空字符串。
4. 若未提及导航布局，固定 pcNaviStyle=1；若未提及主题色，固定 color_mode=random。
5. 只输出 JSON，不要 markdown 代码块。
""".strip()


def generate_spec(requirements: str, ai_config: dict) -> dict:
    client = get_ai_client(ai_config)
    model = ai_config["model"]
    prompt = build_spec_prompt(requirements)
    print(f"正在生成需求 spec（模型: {model}）...")
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=create_generation_config(ai_config, response_mime_type="application/json", temperature=0.2),
    )
    raw = extract_json(resp.text or "")
    return normalize_spec(raw)


def main():
    parser = argparse.ArgumentParser(description="HAP 应用创建入口（Claude Code 专用）")
    parser.add_argument("--requirements", default="", help="需求描述文本（由 Claude 整理后传入）")
    parser.add_argument("--no-execute", action="store_true", help="只生成 spec，不执行")
    parser.add_argument("--dry-run", action="store_true", help="执行器空跑模式")
    parser.add_argument("--spec-json", default="", help="跳过 AI 生成，直接执行已有 spec 文件路径")
    parser.add_argument("--output", default="", help="spec 输出路径（默认自动命名）")
    parser.add_argument("--config", default=str(AI_CONFIG_PATH), help="AI 配置 JSON 路径")
    args = parser.parse_args()

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

        ai_config = load_ai_config(Path(args.config).expanduser().resolve(), tier="fast")
        spec = generate_spec(requirements, ai_config)
        output_path = Path(args.output).expanduser().resolve() if args.output else None
        spec_path = save_spec(spec, output=output_path)
        print(f"需求 spec 已生成: {spec_path}")
        print(f"应用名称: {spec.get('app', {}).get('name', '未知')}")

    if args.no_execute:
        print("（--no-execute 模式，跳过执行）")
        return

    # 执行
    exec_cmd = [sys.executable, str(EXECUTE_SCRIPT), "--spec-json", str(spec_path)]
    if args.dry_run:
        exec_cmd.append("--dry-run")
    print(f"\n开始执行需求...")
    proc = subprocess.run(exec_cmd, check=False)
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
