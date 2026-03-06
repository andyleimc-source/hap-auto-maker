#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
需求执行引擎：
读取 workflow_requirement_v1 JSON，并编排现有脚本执行全流程。
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = BASE_DIR / "scripts"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
EXECUTION_RUN_DIR = OUTPUT_ROOT / "execution_runs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"

CONFIG_GEMINI = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
CONFIG_ORG = BASE_DIR / "config" / "credentials" / "organization_auth.json"
CONFIG_WEB_AUTH = BASE_DIR / "config" / "credentials" / "auth_config.py"

SCRIPT_PIPELINE_CREATE_APP = SCRIPTS_DIR / "pipeline_create_app.py"
SCRIPT_PLAN_WORKSHEETS = SCRIPTS_DIR / "plan_app_worksheets_gemini.py"
SCRIPT_CREATE_WORKSHEETS = SCRIPTS_DIR / "create_worksheets_from_plan.py"
SCRIPT_PIPELINE_ICON = SCRIPTS_DIR / "pipeline_icon.py"
SCRIPT_PIPELINE_LAYOUT = SCRIPTS_DIR / "pipeline_worksheet_layout.py"
SCRIPT_UPDATE_NAVI = SCRIPTS_DIR / "update_app_navi_style.py"


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    navi.setdefault("refresh_auth", False)
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
    ws.setdefault("model", "gemini-3.1-pro-preview")
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

    execution = spec.get("execution") if isinstance(spec.get("execution"), dict) else {}
    execution.setdefault("fail_fast", True)
    execution.setdefault("dry_run", False)
    spec["execution"] = execution
    return spec


def ensure_scripts_exist() -> None:
    required = [
        SCRIPT_PIPELINE_CREATE_APP,
        SCRIPT_PLAN_WORKSHEETS,
        SCRIPT_CREATE_WORKSHEETS,
        SCRIPT_PIPELINE_ICON,
        SCRIPT_PIPELINE_LAYOUT,
        SCRIPT_UPDATE_NAVI,
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("缺少脚本:\n" + "\n".join(missing))


def find_auth_file_by_app_id(app_id: str) -> Optional[Path]:
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            data = load_json(f)
        except Exception:
            continue
        rows = data.get("data")
        if not isinstance(rows, list):
            continue
        for r in rows:
            if isinstance(r, dict) and str(r.get("appId", "")).strip() == app_id:
                return f.resolve()
    return None


def extract_app_id_from_text(text: str) -> Optional[str]:
    m = re.search(r'"appId"\s*:\s*"([0-9a-fA-F-]{36})"', text or "")
    if m:
        return m.group(1)
    m2 = re.search(r"appId:\s*([0-9a-fA-F-]{36})", text or "")
    if m2:
        return m2.group(1)
    return None


def run_cmd(cmd: List[str], dry_run: bool, verbose: bool) -> Dict[str, object]:
    cmd_text = " ".join(cmd)
    if dry_run:
        return {"dry_run": True, "cmd": cmd, "cmd_text": cmd_text, "returncode": 0, "stdout": "", "stderr": ""}

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if verbose and proc.stdout.strip():
        print(proc.stdout.strip())
    if verbose and proc.stderr.strip():
        print(proc.stderr.strip())
    return {
        "dry_run": False,
        "cmd": cmd,
        "cmd_text": cmd_text,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def parse_only_steps(value: str) -> set:
    if not value.strip():
        return set()
    out = set()
    for x in value.split(","):
        t = x.strip().lower()
        if t:
            out.add(t)
    return out


def step_selected(step_id: int, step_key: str, selected: set) -> bool:
    if not selected:
        return True
    return str(step_id) in selected or step_key.lower() in selected


def required_configs(spec: dict) -> List[Tuple[Path, str]]:
    out = [(CONFIG_GEMINI, "Gemini 配置"), (CONFIG_ORG, "组织认证配置")]
    ws = spec["worksheets"]
    navi = spec["app"]["navi_style"]
    need_web_auth = False
    if ws["icon_update"]["enabled"] and not ws["icon_update"].get("refresh_auth", False):
        need_web_auth = True
    if ws["layout"]["enabled"] and not ws["layout"].get("refresh_auth", False):
        need_web_auth = True
    if navi["enabled"] and not navi.get("refresh_auth", False):
        need_web_auth = True
    if need_web_auth:
        out.append((CONFIG_WEB_AUTH, "网页认证配置"))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="执行 workflow_requirement_v1 需求 JSON")
    parser.add_argument("--spec-json", required=True, help="需求 JSON 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅输出执行计划，不实际调用")
    parser.add_argument("--continue-on-error", action="store_true", help="遇错继续执行后续步骤")
    parser.add_argument("--only-steps", default="", help="仅执行指定步骤（逗号分隔：1,2,3 或 create_app,worksheets,...）")
    parser.add_argument("--verbose", action="store_true", help="打印子脚本完整输出")
    args = parser.parse_args()

    ensure_scripts_exist()
    spec_path = Path(args.spec_json).expanduser().resolve()
    spec = normalize_spec(load_json(spec_path))
    if spec.get("schema_version") != "workflow_requirement_v1":
        raise ValueError("schema_version 必须是 workflow_requirement_v1")

    for cfg, name in required_configs(spec):
        if not cfg.exists():
            raise FileNotFoundError(f"缺少{name}: {cfg}")

    selected_steps = parse_only_steps(args.only_steps)
    execution_dry_run = bool(args.dry_run or spec["execution"].get("dry_run", False))
    fail_fast = bool(spec["execution"].get("fail_fast", True)) and (not args.continue_on_error)

    context: Dict[str, object] = {
        "app_id": None,
        "app_auth_json": None,
        "worksheet_plan_json": None,
        "worksheet_create_result_json": None,
    }
    steps_report: List[dict] = []

    def build_report() -> dict:
        ok_count = len([s for s in steps_report if s.get("ok") is True or s.get("skipped") is True])
        fail_count = len([s for s in steps_report if s.get("ok") is False])
        return {
            "schema_version": "workflow_requirement_v1_execution_report",
            "created_at": now_iso(),
            "spec_json": str(spec_path),
            "dry_run": execution_dry_run,
            "fail_fast": fail_fast,
            "summary": {
                "total_steps": len(steps_report),
                "ok_or_skipped": ok_count,
                "failed": fail_count,
            },
            "artifacts": {
                "app_auth_json": context.get("app_auth_json"),
                "worksheet_plan_json": context.get("worksheet_plan_json"),
            },
            "context": context,
            "steps": steps_report,
        }

    def save_report() -> Path:
        report = build_report()
        EXECUTION_RUN_DIR.mkdir(parents=True, exist_ok=True)
        out = (EXECUTION_RUN_DIR / f"execution_run_{now_ts()}.json").resolve()
        write_json(out, report)
        write_json((EXECUTION_RUN_DIR / "execution_run_latest.json").resolve(), report)
        return out

    def execute_step(step_id: int, step_key: str, title: str, cmd: Optional[List[str]]) -> bool:
        if not step_selected(step_id, step_key, selected_steps):
            steps_report.append({"step_id": step_id, "step_key": step_key, "title": title, "skipped": True, "reason": "not_selected"})
            return True
        if cmd is None:
            steps_report.append({"step_id": step_id, "step_key": step_key, "title": title, "skipped": True, "reason": "disabled_by_spec"})
            return True

        print(f"\n== Step {step_id}: {title} ==")
        print("命令:", " ".join(cmd))
        started = now_iso()
        result = run_cmd(cmd, dry_run=execution_dry_run, verbose=args.verbose)
        ended = now_iso()
        ok = int(result.get("returncode", 1)) == 0
        step_item = {
            "step_id": step_id,
            "step_key": step_key,
            "title": title,
            "started_at": started,
            "ended_at": ended,
            "ok": ok,
            "result": result,
        }
        if (not execution_dry_run) and (not args.verbose):
            out = str(result.get("stdout", "") or "").strip()
            err = str(result.get("stderr", "") or "").strip()
            if out:
                print(out[-1200:])
            if err:
                print(err[-800:])
        steps_report.append(step_item)
        return ok

    app = spec["app"]
    ws = spec["worksheets"]

    # Step 1: 创建应用（默认新建）
    if app.get("target_mode") == "create_new":
        cmd1 = [
            sys.executable,
            str(SCRIPT_PIPELINE_CREATE_APP),
            "--name",
            str(app.get("name", "CRM自动化应用")),
            "--group-ids",
            str(app.get("group_ids", "69a794589860d96373beeb4d")),
            "--gemini-model",
            str(ws.get("model", "gemini-3.1-pro-preview")),
        ]
        if str(app.get("icon_mode", "gemini_match")) != "gemini_match":
            cmd1.append("--skip-smart-icon")
        ok = execute_step(1, "create_app", "创建应用+授权+应用icon", cmd1)
        if not ok and fail_fast:
            pass
        if ok:
            if execution_dry_run:
                app_id = "DRYRUN_APP_ID"
                context["app_id"] = app_id
                context["app_auth_json"] = str((APP_AUTH_DIR / f"app_authorize_{app_id}.json").resolve())
            else:
                txt = str(steps_report[-1]["result"].get("stdout", ""))
                app_id = extract_app_id_from_text(txt)
                if not app_id:
                    raise RuntimeError("Step1 未能从输出解析 appId")
                context["app_id"] = app_id
                auth_path = (APP_AUTH_DIR / f"app_authorize_{app_id}.json").resolve()
                context["app_auth_json"] = str(auth_path)
    else:
        # use_existing 模式：要求提供 app_id
        existing_app_id = str(app.get("app_id", "")).strip()
        if not existing_app_id:
            raise ValueError("target_mode=use_existing 时，spec.app.app_id 必填")
        auth_file = find_auth_file_by_app_id(existing_app_id)
        if not auth_file:
            raise FileNotFoundError(f"未找到 appId={existing_app_id} 的授权文件（目录: {APP_AUTH_DIR}）")
        context["app_id"] = existing_app_id
        context["app_auth_json"] = str(auth_file)
        steps_report.append({"step_id": 1, "step_key": "create_app", "title": "创建应用+授权+应用icon", "skipped": True, "reason": "use_existing"})

    # fail-fast
    if fail_fast and any((x.get("ok") is False) for x in steps_report):
        out = save_report()
        print(f"\n执行失败并终止，报告: {out}")
        return

    app_id = str(context.get("app_id") or "")
    app_auth_json = str(context.get("app_auth_json") or "")
    if (not app_id) or (not app_auth_json):
        raise RuntimeError("未获得 app_id/app_auth_json，无法继续执行")

    # Step 2: 工作表规划 + 创建
    if ws.get("enabled", True):
        plan_output = (WORKSHEET_PLAN_DIR / f"worksheet_plan_{app_id}_{now_ts()}.json").resolve()
        cmd2a = [
            sys.executable,
            str(SCRIPT_PLAN_WORKSHEETS),
            "--app-name",
            str(app.get("name", "CRM自动化应用")),
            "--business-context",
            str(ws.get("business_context", "通用企业管理场景")),
            "--requirements",
            str(ws.get("requirements", "")),
            "--model",
            str(ws.get("model", "gemini-3.1-pro-preview")),
            "--output",
            str(plan_output),
        ]
        ok2a = execute_step(2, "worksheets_plan", "规划工作表", cmd2a)
        if fail_fast and (not ok2a):
            pass
        if ok2a:
            context["worksheet_plan_json"] = str(plan_output)
            cmd2b = [
                sys.executable,
                str(SCRIPT_CREATE_WORKSHEETS),
                "--plan-json",
                str(plan_output),
                "--app-auth-json",
                str(app_auth_json),
            ]
            ok2b = execute_step(2, "worksheets_create", "创建工作表", cmd2b)
            if fail_fast and (not ok2b):
                pass
    else:
        steps_report.append({"step_id": 2, "step_key": "worksheets", "title": "规划并创建工作表", "skipped": True, "reason": "disabled_by_spec"})

    if fail_fast and any((x.get("ok") is False) for x in steps_report):
        out = save_report()
        print(f"\n执行失败并终止，报告: {out}")
        return

    # Step 3: 工作表 icon
    if ws["icon_update"].get("enabled", True):
        cmd3 = [
            sys.executable,
            str(SCRIPT_PIPELINE_ICON),
            "--app-auth-json",
            str(app_auth_json),
            "--app-id",
            app_id,
            "--model",
            str(ws.get("model", "gemini-3.1-pro-preview")),
        ]
        if ws["icon_update"].get("refresh_auth", False):
            cmd3.append("--refresh-auth")
        ok3 = execute_step(3, "worksheet_icon", "更新工作表icon", cmd3)
        if fail_fast and (not ok3):
            out = save_report()
            print(f"\n执行失败并终止，报告: {out}")
            return
    else:
        steps_report.append({"step_id": 3, "step_key": "worksheet_icon", "title": "更新工作表icon", "skipped": True, "reason": "disabled_by_spec"})

    # Step 4: 字段布局
    if ws["layout"].get("enabled", True):
        cmd4 = [
            sys.executable,
            str(SCRIPT_PIPELINE_LAYOUT),
            "--app-id",
            app_id,
            "--model",
            str(ws.get("model", "gemini-3.1-pro-preview")),
        ]
        layout_req = str(ws["layout"].get("requirements", "")).strip()
        if layout_req:
            cmd4.extend(["--requirements", layout_req])
        if ws["layout"].get("refresh_auth", False):
            cmd4.append("--refresh-auth")
        ok4 = execute_step(4, "layout", "规划并应用字段布局", cmd4)
        if fail_fast and (not ok4):
            out = save_report()
            print(f"\n执行失败并终止，报告: {out}")
            return
    else:
        steps_report.append({"step_id": 4, "step_key": "layout", "title": "规划并应用字段布局", "skipped": True, "reason": "disabled_by_spec"})

    # Step 5: 应用导航风格
    if app["navi_style"].get("enabled", True):
        cmd5 = [
            sys.executable,
            str(SCRIPT_UPDATE_NAVI),
            "--app-id",
            app_id,
            "--pc-navi-style",
            str(int(app["navi_style"].get("pcNaviStyle", 1))),
        ]
        if app["navi_style"].get("refresh_auth", False):
            cmd5.append("--refresh-auth")
        ok5 = execute_step(5, "navi", "设置应用导航风格", cmd5)
        if fail_fast and (not ok5):
            out = save_report()
            print(f"\n执行失败并终止，报告: {out}")
            return
    else:
        steps_report.append({"step_id": 5, "step_key": "navi", "title": "设置应用导航风格", "skipped": True, "reason": "disabled_by_spec"})

    out = save_report()
    report = build_report()

    print("\n执行完成（摘要）")
    print(f"- dry-run: {execution_dry_run}")
    print(f"- 成功/跳过: {report['summary']['ok_or_skipped']}")
    print(f"- 失败: {report['summary']['failed']}")
    print(f"- 报告文件: {out}")


if __name__ == "__main__":
    main()
