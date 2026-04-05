#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
需求执行引擎：
读取 workflow_requirement_v1 JSON，并编排现有脚本执行全流程。

并行策略：
  - Wave 2:   Step 2a + Step 3 并行（受 Gemini 信号量约束）
  - Wave 2.5: Step 2c AI 规划工作表分组（串行，依赖 2a）；Step 8 在此之后执行（依赖分组数动态决定导航样式）
  - Wave 3:   Step 2d 创建分组+写回 plan（串行，依赖 2c）；Step 2b 创建工作表（依赖 2d）；
              Step 2d-2 移动工作表到分组（串行，依赖 2b）
  - Wave 4:   Step 4/5/6/9/10/11/13 全部提交，Semaphore(3) 限制同时 Gemini 调用数；13 不用 Gemini
  - Wave 5:   Step 7（依赖 6）、Step 12（依赖 11），无 Gemini 限制
  - Wave 6:   Step 14 统计图表 Pages（串行，依赖 Wave 4/5 完成，用 Gemini）
"""

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from ai_utils import AI_CONFIG_PATH
from script_locator import resolve_script

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
EXECUTION_RUN_DIR = OUTPUT_ROOT / "execution_runs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"

CONFIG_GEMINI = AI_CONFIG_PATH
CONFIG_ORG = BASE_DIR / "config" / "credentials" / "organization_auth.json"
CONFIG_WEB_AUTH = BASE_DIR / "config" / "credentials" / "auth_config.py"

SCRIPT_PIPELINE_CREATE_APP = resolve_script("pipeline_create_app.py")
SCRIPT_PLAN_WORKSHEETS = resolve_script("plan_app_worksheets_gemini.py")
SCRIPT_CREATE_WORKSHEETS = resolve_script("create_worksheets_from_plan.py")
SCRIPT_PIPELINE_APP_ROLES = resolve_script("pipeline_app_roles.py")
SCRIPT_PIPELINE_ICON = resolve_script("pipeline_icon.py")
SCRIPT_PIPELINE_LAYOUT = resolve_script("pipeline_worksheet_layout.py")
SCRIPT_PIPELINE_VIEWS = resolve_script("pipeline_views.py")
SCRIPT_PIPELINE_TABLEVIEW_FILTERS = resolve_script("pipeline_tableview_filters.py")
SCRIPT_UPDATE_NAVI = resolve_script("update_app_navi_style.py")
SCRIPT_PIPELINE_MOCK_DATA = resolve_script("pipeline_mock_data.py")
SCRIPT_PIPELINE_CHATBOTS = resolve_script("pipeline_chatbots.py")
WORKFLOW_SCRIPTS_DIR = BASE_DIR / "workflow" / "scripts"
WORKFLOW_OUTPUT_DIR = BASE_DIR / "workflow" / "output"
SCRIPT_PIPELINE_WORKFLOWS = WORKFLOW_SCRIPTS_DIR / "pipeline_workflows.py"
SCRIPT_EXECUTE_WORKFLOWS = WORKFLOW_SCRIPTS_DIR / "execute_workflow_plan.py"
SCRIPT_DELETE_DEFAULT_VIEWS = resolve_script("delete_default_views.py")
SCRIPT_PIPELINE_PAGES = resolve_script("pipeline_pages.py")
SCRIPT_PLAN_PAGES = resolve_script("plan_pages_gemini.py")
SCRIPT_PLAN_SECTIONS    = resolve_script("plan_app_sections_gemini.py")
SCRIPT_CREATE_SECTIONS  = resolve_script("create_sections_from_plan.py")
VIEW_PLAN_DIR = OUTPUT_ROOT / "view_plans"
VIEW_CREATE_RESULT_DIR = OUTPUT_ROOT / "view_create_results"
TABLEVIEW_FILTER_PLAN_DIR = OUTPUT_ROOT / "tableview_filter_plans"
TABLEVIEW_FILTER_APPLY_RESULT_DIR = OUTPUT_ROOT / "tableview_filter_apply_results"
SECTIONS_PLAN_DIR          = OUTPUT_ROOT / "sections_plans"
SECTIONS_CREATE_RESULT_DIR = OUTPUT_ROOT / "sections_create_results"

# Gemini 并发上限（同时最多 3 个步骤调用 Gemini）
GEMINI_SEMAPHORE = threading.Semaphore(3)




def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
        data = load_json(CONFIG_ORG)
        return str(data.get("group_ids", "")).strip()
    except Exception:
        return ""


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
    app.setdefault("group_ids", _load_org_group_ids())
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
    spec["views"] = views

    roles = spec.get("roles") if isinstance(spec.get("roles"), dict) else {}
    roles.setdefault("enabled", True)
    roles.setdefault("skip_existing", True)
    roles.setdefault("video_mode", "skip")
    spec["roles"] = roles

    view_filters = spec.get("view_filters") if isinstance(spec.get("view_filters"), dict) else {}
    view_filters.setdefault("enabled", True)
    spec["view_filters"] = view_filters

    mock_data = spec.get("mock_data") if isinstance(spec.get("mock_data"), dict) else {}
    mock_data.setdefault("enabled", True)
    mock_data.setdefault("dry_run", False)
    mock_data.setdefault("trigger_workflow", False)
    spec["mock_data"] = mock_data

    chatbots = spec.get("chatbots") if isinstance(spec.get("chatbots"), dict) else {}
    chatbots.setdefault("enabled", True)
    chatbots.setdefault("auto", True)
    chatbots.setdefault("dry_run", False)
    spec["chatbots"] = chatbots

    workflows = spec.get("workflows") if isinstance(spec.get("workflows"), dict) else {}
    workflows.setdefault("enabled", True)
    workflows.setdefault("thinking", "none")
    workflows.setdefault("no_publish", False)
    workflows.setdefault("skip_analysis", True)  # ER图已包含关系信息，跳过冗余预分析
    spec["workflows"] = workflows

    delete_default_views = spec.get("delete_default_views") if isinstance(spec.get("delete_default_views"), dict) else {}
    delete_default_views.setdefault("enabled", True)
    delete_default_views.setdefault("refresh_auth", False)  # pipeline 启动时 auth 已新鲜，无需重复刷新
    spec["delete_default_views"] = delete_default_views

    pages = spec.get("pages") if isinstance(spec.get("pages"), dict) else {}
    pages.setdefault("enabled", True)
    spec["pages"] = pages

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
        SCRIPT_PIPELINE_APP_ROLES,
        SCRIPT_PIPELINE_ICON,
        SCRIPT_PIPELINE_LAYOUT,
        SCRIPT_PIPELINE_VIEWS,
        SCRIPT_PIPELINE_TABLEVIEW_FILTERS,
        SCRIPT_UPDATE_NAVI,
        SCRIPT_PIPELINE_MOCK_DATA,
        SCRIPT_PIPELINE_CHATBOTS,
        SCRIPT_PIPELINE_WORKFLOWS,
        SCRIPT_EXECUTE_WORKFLOWS,
        SCRIPT_DELETE_DEFAULT_VIEWS,
        SCRIPT_PIPELINE_PAGES,
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


def extract_report_path(text: str) -> Optional[str]:
    m = re.search(r"-\s*报告:\s*(.+)", text or "")
    if not m:
        return None
    return m.group(1).strip()


def extract_saved_path(text: str) -> Optional[str]:
    m = re.search(r"已保存:\s*(.+)", text or "")
    if not m:
        return None
    return m.group(1).strip()


def extract_labeled_path(text: str, label: str) -> Optional[str]:
    pattern = rf"-\s*{re.escape(label)}:\s*(.+)"
    m = re.search(pattern, text or "")
    if not m:
        return None
    return m.group(1).strip()


def extract_marker_path(text: str, marker: str) -> Optional[str]:
    for line in reversed((text or "").splitlines()):
        item = line.strip()
        if item.startswith(marker):
            return item.split(":", 1)[1].strip()
    return None


def run_cmd(cmd: List[str], dry_run: bool, verbose: bool) -> Dict[str, object]:
    cmd_text = " ".join(cmd)
    if dry_run:
        return {"dry_run": True, "cmd": cmd, "cmd_text": cmd_text, "returncode": 0, "stdout": "", "stderr": ""}

    # 改进：使用 Popen 实时流式输出，防止长耗时步骤触发 Gemini 终端超时
    stdout_lines = []
    stderr_lines = []
    
    proc = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        text=True, 
        bufsize=1,
        universal_newlines=True
    )

    def reader(pipe, bucket, is_stdout):
        for line in pipe:
            bucket.append(line)
            if verbose:
                # 实时打印到终端，保持活动
                print(line, end="", flush=True)

    # 定时打印心跳点，防止静默超时
    def heartbeat(process):
        while process.poll() is None:
            if not verbose:
                print(".", end="", flush=True)
            time.sleep(30)

    t1 = threading.Thread(target=reader, args=(proc.stdout, stdout_lines, True))
    t2 = threading.Thread(target=reader, args=(proc.stderr, stderr_lines, False))
    t3 = threading.Thread(target=heartbeat, args=(proc,))
    t1.start()
    t2.start()
    t3.start()
    
    returncode = proc.wait()
    t1.join()
    t2.join()
    # t3 will exit shortly after

    full_stdout = "".join(stdout_lines)
    full_stderr = "".join(stderr_lines)
    
    if not verbose and not dry_run:
        # 清除刚才打的点
        print(" ", end="\r")

    return {
        "dry_run": False,
        "cmd": cmd,
        "cmd_text": cmd_text,
        "returncode": returncode,
        "stdout": full_stdout,
        "stderr": full_stderr,
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
    out = [(CONFIG_GEMINI, "AI 配置"), (CONFIG_ORG, "组织认证配置")]
    ws = spec["worksheets"]
    views = spec["views"]
    view_filters = spec["view_filters"]
    navi = spec["app"]["navi_style"]
    need_web_auth = False
    if ws["icon_update"]["enabled"] and not ws["icon_update"].get("refresh_auth", False):
        need_web_auth = True
    if ws["layout"]["enabled"] and not ws["layout"].get("refresh_auth", False):
        need_web_auth = True
    if views.get("enabled", True):
        need_web_auth = True
    if view_filters.get("enabled", True):
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
    parser.add_argument(
        "--only-steps",
        default="",
        help="仅执行指定步骤（逗号分隔：1,2,3 或 create_app,worksheets_plan,worksheets_create,roles,worksheet_icon,layout,views,view_filters,navi,mock_data,chatbots,workflows_plan,workflows_execute,delete_default_views,pages）",
    )
    parser.add_argument("--verbose", action="store_true", help="打印子脚本完整输出")
    parser.add_argument(
        "--gemini-concurrency",
        type=int,
        default=3,
        help="Gemini API 最大并发调用数（默认 3）",
    )
    parser.add_argument(
        "--app-id",
        default="",
        help="已有应用 ID，跳过创建步骤并使用该 appId 初始化 context（配合 --only-steps 补跑）",
    )
    args = parser.parse_args()

    # 根据参数调整信号量
    global GEMINI_SEMAPHORE
    GEMINI_SEMAPHORE = threading.Semaphore(args.gemini_concurrency)

    pipeline_start = time.time()

    ensure_scripts_exist()
    spec_path = Path(args.spec_json).expanduser().resolve()
    spec = normalize_spec(load_json(spec_path))
    if args.app_id.strip():
        spec["app"]["target_mode"] = "use_existing"
        spec["app"]["app_id"] = args.app_id.strip()
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
        "sections_plan_json": None,
        "sections_create_result_json": None,
        "worksheet_create_result_json": None,
        "role_pipeline_report_json": None,
        "role_plan_json": None,
        "role_create_result_json": None,
        "worksheet_layout_plan_json": None,
        "worksheet_layout_apply_result_json": None,
        "view_plan_json": None,
        "view_create_result_json": None,
        "tableview_filter_plan_json": None,
        "tableview_filter_apply_result_json": None,
        "mock_data_run_json": None,
        "chatbot_pipeline_result_json": None,
        "workflow_plan_json": None,
        "workflow_execute_result_json": None,
    }
    steps_report: List[dict] = []
    steps_lock = threading.Lock()

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
                "sections_plan_json": context.get("sections_plan_json"),
                "sections_create_result_json": context.get("sections_create_result_json"),
                "worksheet_create_result_json": context.get("worksheet_create_result_json"),
                "role_pipeline_report_json": context.get("role_pipeline_report_json"),
                "role_plan_json": context.get("role_plan_json"),
                "role_create_result_json": context.get("role_create_result_json"),
                "worksheet_layout_plan_json": context.get("worksheet_layout_plan_json"),
                "worksheet_layout_apply_result_json": context.get("worksheet_layout_apply_result_json"),
                "view_plan_json": context.get("view_plan_json"),
                "view_create_result_json": context.get("view_create_result_json"),
                "tableview_filter_plan_json": context.get("tableview_filter_plan_json"),
                "tableview_filter_apply_result_json": context.get("tableview_filter_apply_result_json"),
                "mock_data_run_json": context.get("mock_data_run_json"),
                "chatbot_pipeline_result_json": context.get("chatbot_pipeline_result_json"),
                "workflow_plan_json": context.get("workflow_plan_json"),
                "workflow_execute_result_json": context.get("workflow_execute_result_json"),
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

    def has_failure() -> bool:
        with steps_lock:
            return any(x.get("ok") is False and not x.get("non_fatal") for x in steps_report)

    def execute_step(
        step_id: int,
        step_key: str,
        title: str,
        cmd: Optional[List[str]],
        uses_gemini: bool = False,
    ) -> bool:
        if not step_selected(step_id, step_key, selected_steps):
            with steps_lock:
                steps_report.append({"step_id": step_id, "step_key": step_key, "title": title, "skipped": True, "reason": "not_selected", "result": {}})
            return True
        if cmd is None:
            with steps_lock:
                steps_report.append({"step_id": step_id, "step_key": step_key, "title": title, "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True

        elapsed_total = time.time() - pipeline_start
        print(f"  ▶ Step {step_id:2d} / 14  {title}  [{elapsed_total:.0f}s]", flush=True)
        started = now_iso()
        step_start = time.time()

        if uses_gemini:
            with GEMINI_SEMAPHORE:
                result = run_cmd(cmd, dry_run=execution_dry_run, verbose=args.verbose)
        else:
            result = run_cmd(cmd, dry_run=execution_dry_run, verbose=args.verbose)

        ended = now_iso()
        ok = int(result.get("returncode", 1)) == 0
        duration = time.time() - step_start
        elapsed_total = time.time() - pipeline_start
        status = "✓" if ok else "✗"
        print(f"  {status} Step {step_id:2d} / 14  {title}  ({duration:.0f}s, 总计 {elapsed_total:.0f}s)", flush=True)
        if not ok:
            err = str(result.get("stderr", "") or "").strip()
            if err:
                print(err[-600:], flush=True)
        step_item = {
            "step_id": step_id,
            "step_key": step_key,
            "title": title,
            "started_at": started,
            "ended_at": ended,
            "ok": ok,
            "result": result,
        }
        with steps_lock:
            steps_report.append(step_item)
        return ok

    app = spec["app"]
    ws = spec["worksheets"]
    roles = spec["roles"]
    views = spec["views"]
    view_filters = spec["view_filters"]
    mock_data = spec["mock_data"]
    chatbots = spec["chatbots"]
    workflows = spec["workflows"]
    delete_default_views_cfg = spec["delete_default_views"]
    pages_cfg = spec["pages"]

    # ──────────────────────────────────────────────
    # Wave 1: Step 1 创建应用（串行，后续步骤依赖 app_id）
    # ──────────────────────────────────────────────
    if app.get("target_mode") == "create_new":
        cmd1 = [
            sys.executable,
            str(SCRIPT_PIPELINE_CREATE_APP),
            "--name",
            str(app.get("name", "CRM自动化应用")),
            "--group-ids",
            str(app.get("group_ids", _load_org_group_ids())),
        ]
        if str(app.get("icon_mode", "gemini_match")) != "gemini_match":
            cmd1.append("--skip-smart-icon")
        ok = execute_step(1, "create_app", "创建应用+授权+应用icon", cmd1, uses_gemini=True)
        if not ok and fail_fast:
            out = save_report()
            print(f"\n执行失败并终止，报告: {out}")
            return
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
        existing_app_id = str(app.get("app_id", "")).strip()
        if not existing_app_id:
            raise ValueError("target_mode=use_existing 时，spec.app.app_id 必填")
        auth_file = find_auth_file_by_app_id(existing_app_id)
        if not auth_file:
            raise FileNotFoundError(f"未找到 appId={existing_app_id} 的授权文件（目录: {APP_AUTH_DIR}）")
        context["app_id"] = existing_app_id
        context["app_auth_json"] = str(auth_file)
        with steps_lock:
            steps_report.append({"step_id": 1, "step_key": "create_app", "title": "创建应用+授权+应用icon", "skipped": True, "reason": "use_existing", "result": {}})

    app_id = str(context.get("app_id") or "")
    app_auth_json = str(context.get("app_auth_json") or "")
    if (not app_id) or (not app_auth_json):
        raise RuntimeError("未获得 app_id/app_auth_json，无法继续执行")

    # ──────────────────────────────────────────────
    # Wave 2: Step 2a + Step 3 + Step 8 并行
    #   2a 用 Gemini（pro），3 用 Gemini（flash），8 不用 Gemini
    # ──────────────────────────────────────────────
    print(f"\n── Wave 2: 工作表规划 / 角色 / 导航风格（并行） ─── 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    plan_output = (WORKSHEET_PLAN_DIR / f"worksheet_plan_{app_id}_{now_ts()}.json").resolve()

    def run_step_2a() -> bool:
        if not ws.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 2, "step_key": "worksheets_plan", "title": "规划工作表", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd2a = [
            sys.executable, str(SCRIPT_PLAN_WORKSHEETS),
            "--app-name", str(app.get("name", "CRM自动化应用")),
            "--business-context", str(ws.get("business_context", "通用企业管理场景")),
            "--requirements", str(ws.get("requirements", "")),
            "--output", str(plan_output),
        ]
        max_ws = int(ws.get("max_worksheets", 0) or 0)
        if max_ws > 0:
            cmd2a.extend(["--max-worksheets", str(max_ws)])
        return execute_step(2, "worksheets_plan", "规划工作表", cmd2a, uses_gemini=True)

    def run_step_3() -> bool:
        if not roles.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 3, "step_key": "roles", "title": "规划并创建应用角色", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd3 = [
            sys.executable, str(SCRIPT_PIPELINE_APP_ROLES),
            "--app-id", app_id,
            "--video-mode", str(roles.get("video_mode", "skip")),
        ]
        if not bool(roles.get("skip_existing", True)):
            cmd3.append("--no-skip-existing")
        ok3 = execute_step(3, "roles", "规划并创建应用角色", cmd3, uses_gemini=True)
        if ok3 and not execution_dry_run:
            role_report = extract_marker_path(str(steps_report[-1]["result"].get("stdout", "")), "RESULT_JSON")
            if role_report:
                context["role_pipeline_report_json"] = role_report
                try:
                    role_data = load_json(Path(role_report))
                    artifacts = role_data.get("artifacts", {}) if isinstance(role_data.get("artifacts"), dict) else {}
                    context["role_plan_json"] = artifacts.get("planJson")
                    context["role_create_result_json"] = artifacts.get("createResultJson")
                except Exception:
                    pass
        return ok3

    def run_step_8() -> bool:
        if not app["navi_style"].get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 8, "step_key": "navi", "title": "设置应用导航风格", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd8 = [
            sys.executable, str(SCRIPT_UPDATE_NAVI),
            "--app-id", app_id,
            "--pc-navi-style", str(int(app["navi_style"].get("pcNaviStyle", 1))),
        ]
        if app["navi_style"].get("refresh_auth", False):
            cmd8.append("--refresh-auth")
        return execute_step(8, "navi", "设置应用导航风格", cmd8, uses_gemini=False)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f2a = pool.submit(run_step_2a)
        f3  = pool.submit(run_step_3)
        ok2a = f2a.result()
        f3.result()

    if fail_fast and has_failure():
        out = save_report()
        print(f"\n执行失败并终止，报告: {out}")
        return

    # ──────────────────────────────────────────────
    # Wave 2.5: Step 2c AI 规划工作表分组（串行，依赖 2a）
    # ──────────────────────────────────────────────
    print(f"\n── Wave 2.5: AI 规划工作表分组 ─── 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    sections_plan_output = (SECTIONS_PLAN_DIR / f"sections_plan_{app_id}_{now_ts()}.json").resolve()
    sections_create_output = (SECTIONS_CREATE_RESULT_DIR / f"sections_create_{app_id}_{now_ts()}.json").resolve()
    ok2c = True
    ok2d = True
    sections_create_result_path: Optional[str] = None

    if ws.get("enabled", True) and ok2a:
        context["worksheet_plan_json"] = str(plan_output)
        cmd2c = [
            sys.executable, str(SCRIPT_PLAN_SECTIONS),
            "--plan-json", str(plan_output),
            "--output", str(sections_plan_output),
        ]
        ok2c = execute_step(2, "sections_plan", "AI 规划工作表分组", cmd2c, uses_gemini=True)
        if ok2c and not execution_dry_run:
            context["sections_plan_json"] = str(sections_plan_output)
        if fail_fast and not ok2c:
            out = save_report()
            print(f"\n执行失败并终止，报告: {out}")
            return

    # 根据分组数动态决定导航样式：>3 个分组 → 经典导航（pcNaviStyle=2）
    if ok2c and sections_plan_output.exists() and not execution_dry_run:
        try:
            sections_data = json.loads(sections_plan_output.read_text(encoding="utf-8"))
            section_count = len(sections_data.get("sections", []))
            if section_count > 3:
                app["navi_style"]["pcNaviStyle"] = 0
                print(f"  ℹ 分组数={section_count} > 3，自动切换为经典导航（pcNaviStyle=0）", flush=True)
        except Exception as e:
            print(f"  ⚠ 读取分组数失败，使用默认导航样式: {e}", flush=True)

    # Step 8：设置应用导航风格（依赖分组数，在 Wave 2.5 后串行执行）
    run_step_8()

    if fail_fast and has_failure():
        out = save_report()
        print(f"\n执行失败并终止，报告: {out}")
        return

    # ──────────────────────────────────────────────
    # Wave 3: Step 2d 创建分组（依赖 2c）；Step 2b 创建工作表（依赖 2d）；Step 2d-2 移动工作表（依赖 2b）
    # ──────────────────────────────────────────────
    print(f"\n── Wave 3: 创建工作表 ─── 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    # Step 2d 模式一：创建分组，写回 worksheet_plan
    if ws.get("enabled", True) and ok2c and not execution_dry_run:
        cmd2d = [
            sys.executable, str(SCRIPT_CREATE_SECTIONS),
            "--sections-plan-json", str(sections_plan_output),
            "--plan-json", str(plan_output),
            "--app-id", app_id,
            "--app-auth-json", str(app_auth_json),
            "--output", str(sections_create_output),
        ]
        ok2d = execute_step(2, "sections_create", "创建工作表分组", cmd2d, uses_gemini=False)
        if ok2d:
            sections_create_result_path = str(sections_create_output)
            context["sections_create_result_json"] = sections_create_result_path
        if fail_fast and not ok2d:
            out = save_report()
            print(f"\n执行失败并终止，报告: {out}")
            return

    worksheet_create_result_path: Optional[str] = None
    if ws.get("enabled", True) and ok2a:
        cmd2b = [
            sys.executable, str(SCRIPT_CREATE_WORKSHEETS),
            "--plan-json", str(plan_output),
            "--app-auth-json", str(app_auth_json),
        ]
        ok2b = execute_step(2, "worksheets_create", "创建工作表", cmd2b, uses_gemini=False)
        if ok2b and not execution_dry_run:
            worksheet_create_result_path = extract_saved_path(str(steps_report[-1]["result"].get("stdout", "")))
            context["worksheet_create_result_json"] = worksheet_create_result_path
        if fail_fast and not ok2b:
            out = save_report()
            print(f"\n执行失败并终止，报告: {out}")
            return

        # Step 2d 模式二：移动工作表到分组
        if ok2b and ok2d and sections_create_result_path and worksheet_create_result_path and not execution_dry_run:
            cmd2d2 = [
                sys.executable, str(SCRIPT_CREATE_SECTIONS),
                "--sections-plan-json", str(sections_plan_output),
                "--plan-json", str(plan_output),
                "--app-id", app_id,
                "--app-auth-json", str(app_auth_json),
                "--output", str(sections_create_output),
                "--ws-create-result", str(worksheet_create_result_path),
            ]
            execute_step(2, "sections_move", "移动工作表到分组", cmd2d2, uses_gemini=False)

    elif not ws.get("enabled", True):
        with steps_lock:
            steps_report.append({"step_id": 2, "step_key": "worksheets_create", "title": "创建工作表", "skipped": True, "reason": "disabled_by_spec", "result": {}})

    if fail_fast and has_failure():
        out = save_report()
        print(f"\n执行失败并终止，报告: {out}")
        return

    # ──────────────────────────────────────────────
    # Wave 4: Step 4/5/6/9/10/11 并行
    #   全部使用 Gemini，受 GEMINI_SEMAPHORE 约束
    # ──────────────────────────────────────────────
    print(f"\n── Wave 4: icon / 布局 / 视图 / 造数 / 机器人 / 工作流规划 / 规划图表页（并行） ─── 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    view_plan_output = (VIEW_PLAN_DIR / f"view_plan_{app_id}_{now_ts()}.json").resolve()
    view_create_output = (VIEW_CREATE_RESULT_DIR / f"view_create_result_{app_id}_{now_ts()}.json").resolve()
    workflow_plan_output = (WORKFLOW_OUTPUT_DIR / f"pipeline_workflows_{app_id}_{now_ts()}.json").resolve()
    page_plan_output = (OUTPUT_ROOT / "page_plans" / f"page_plan_{app_id}_pipeline.json").resolve()
    ok_14a = False

    def run_step_4() -> bool:
        if not ws["icon_update"].get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 4, "step_key": "worksheet_icon", "title": "更新工作表icon", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd4 = [
            sys.executable, str(SCRIPT_PIPELINE_ICON),
            "--app-auth-json", str(app_auth_json),
            "--app-id", app_id,
        ]
        if ws["icon_update"].get("refresh_auth", False):
            cmd4.append("--refresh-auth")
        return execute_step(4, "worksheet_icon", "更新工作表icon", cmd4, uses_gemini=True)

    def run_step_5() -> bool:
        if not ws["layout"].get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 5, "step_key": "layout", "title": "规划并应用字段布局", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd5 = [
            sys.executable, str(SCRIPT_PIPELINE_LAYOUT),
            "--app-id", app_id,
        ]
        layout_req = str(ws["layout"].get("requirements", "")).strip()
        if layout_req:
            cmd5.extend(["--requirements", layout_req])
        if ws["layout"].get("refresh_auth", False):
            cmd5.append("--refresh-auth")
        ok5 = execute_step(5, "layout", "规划并应用字段布局", cmd5, uses_gemini=True)
        if ok5 and not execution_dry_run:
            layout_stdout = str(steps_report[-1]["result"].get("stdout", ""))
            context["worksheet_layout_plan_json"] = extract_labeled_path(layout_stdout, "输出文件")
            context["worksheet_layout_apply_result_json"] = extract_labeled_path(layout_stdout, "结果文件")
        return ok5

    def run_step_6() -> bool:
        if not views.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 6, "step_key": "views", "title": "规划并创建视图", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd6 = [
            sys.executable, str(SCRIPT_PIPELINE_VIEWS),
            "--app-ids", app_id,
            "--plan-output", str(view_plan_output),
            "--create-output", str(view_create_output),
        ]
        ok6 = execute_step(6, "views", "规划并创建视图", cmd6, uses_gemini=True)
        if ok6:
            context["view_plan_json"] = str(view_plan_output)
            context["view_create_result_json"] = str(view_create_output)
        return ok6

    def run_step_9() -> bool:
        if not mock_data.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 9, "step_key": "mock_data", "title": "执行造数流水线", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd9 = [
            sys.executable, str(SCRIPT_PIPELINE_MOCK_DATA),
            "--app-id", app_id,
        ]
        if execution_dry_run or mock_data.get("dry_run", False):
            cmd9.append("--dry-run")
        if mock_data.get("trigger_workflow", False):
            cmd9.append("--trigger-workflow")
        ok9 = execute_step(9, "mock_data", "执行造数流水线", cmd9, uses_gemini=True)
        if ok9 and not execution_dry_run:
            context["mock_data_run_json"] = extract_report_path(str(steps_report[-1]["result"].get("stdout", "")))
        if not ok9:
            # 造数失败不应阻断后续步骤（视图筛选、工作流、图表页），标记为非致命
            with steps_lock:
                for sr in steps_report:
                    if sr.get("step_id") == 9 and not sr.get("ok", True):
                        sr["non_fatal"] = True
                        break
        return ok9

    def run_step_10() -> bool:
        if not chatbots.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 10, "step_key": "chatbots", "title": "创建对话机器人", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd10 = [
            sys.executable, str(SCRIPT_PIPELINE_CHATBOTS),
            "--app-id", app_id,
        ]
        if chatbots.get("auto", True):
            cmd10.append("--auto")
        if chatbots.get("dry_run", False) or execution_dry_run:
            cmd10.append("--dry-run-create")
        ok10 = execute_step(10, "chatbots", "创建对话机器人", cmd10, uses_gemini=True)
        if ok10 and not execution_dry_run:
            context["chatbot_pipeline_result_json"] = extract_labeled_path(
                str(steps_report[-1]["result"].get("stdout", "")), "RESULT_JSON"
            )
        return ok10

    def run_step_11() -> bool:
        if not workflows.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 11, "step_key": "workflows_plan", "title": "规划工作流（AI）", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        WORKFLOW_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cmd11 = [
            sys.executable, str(SCRIPT_PIPELINE_WORKFLOWS),
            "--relation-id", app_id,
            "--thinking", str(workflows.get("thinking", "none")),
            "--output", str(workflow_plan_output),
        ]
        if workflows.get("skip_analysis", False):
            cmd11.append("--skip-analysis")
        ok11 = execute_step(11, "workflows_plan", "规划工作流（AI）", cmd11, uses_gemini=True)
        if ok11:
            context["workflow_plan_json"] = str(workflow_plan_output)
        return ok11

    def run_step_13() -> bool:
        if not delete_default_views_cfg.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 13, "step_key": "delete_default_views", "title": "删除[全部]默认视图", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd13 = [
            sys.executable, str(SCRIPT_DELETE_DEFAULT_VIEWS),
            "--app-id", app_id,
            "--app-auth-json", str(app_auth_json),
            "--auth-config", str(CONFIG_WEB_AUTH),
        ]
        if delete_default_views_cfg.get("refresh_auth", True):
            cmd13.extend(["--refresh-auth", "--headless"])
        if execution_dry_run:
            cmd13.append("--dry-run")
        return execute_step(13, "delete_default_views", "删除[全部]默认视图", cmd13, uses_gemini=False)

    def run_step_14a() -> bool:
        nonlocal ok_14a
        if not pages_cfg.get("enabled", True):
            ok_14a = False
            return True
        cmd14a = [
            sys.executable, str(SCRIPT_PLAN_PAGES),
            "--app-id", app_id,
            "--auth-config", str(CONFIG_WEB_AUTH),
            "--output", str(page_plan_output),
        ]
        elapsed_total = time.time() - pipeline_start
        print(f"  ▶ Step 14a/ 14  规划统计图表页（AI）  [{elapsed_total:.0f}s]", flush=True)
        step_start = time.time()
        with GEMINI_SEMAPHORE:
            result = run_cmd(cmd14a, dry_run=execution_dry_run, verbose=args.verbose)
        ok_14a = int(result.get("returncode", 1)) == 0
        duration = time.time() - step_start
        elapsed_total = time.time() - pipeline_start
        status = "✓" if ok_14a else "✗"
        print(f"  {status} Step 14a/ 14  规划统计图表页（AI）  ({duration:.0f}s, 总计 {elapsed_total:.0f}s)", flush=True)
        if not ok_14a:
            err = str(result.get("stderr", "") or "").strip()
            if err:
                print(err[-600:], flush=True)
        return ok_14a

    with ThreadPoolExecutor(max_workers=7) as pool:
        f4   = pool.submit(run_step_4)
        f5   = pool.submit(run_step_5)
        f6   = pool.submit(run_step_6)
        f9   = pool.submit(run_step_9)
        f10  = pool.submit(run_step_10)
        f11  = pool.submit(run_step_11)
        f14a = pool.submit(run_step_14a)
        f4.result()
        f5.result()
        ok6  = f6.result()
        f9.result()
        f10.result()
        ok11 = f11.result()
        f14a.result()

    if fail_fast and has_failure():
        out = save_report()
        print(f"\n执行失败并终止，报告: {out}")
        return

    # ──────────────────────────────────────────────
    # Wave 5: Step 7（依赖 6）+ Step 12（依赖 11）并行
    # ──────────────────────────────────────────────
    print(f"\n── Wave 5: 视图筛选 / 创建工作流（并行） ─── 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    filter_plan_output = (TABLEVIEW_FILTER_PLAN_DIR / f"tableview_filter_plan_{app_id}_{now_ts()}.json").resolve()
    filter_apply_output = (
        TABLEVIEW_FILTER_APPLY_RESULT_DIR / f"tableview_filter_apply_result_{app_id}_{now_ts()}.json"
    ).resolve()

    def run_step_7() -> bool:
        if not view_filters.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 7, "step_key": "view_filters", "title": "规划并应用视图筛选", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd7 = [
            sys.executable, str(SCRIPT_PIPELINE_TABLEVIEW_FILTERS),
            "--app-ids", app_id,
            "--plan-output", str(filter_plan_output),
            "--apply-output", str(filter_apply_output),
            "--app-auth-json", str(app_auth_json),
        ]
        if ok6 and view_create_output.exists():
            cmd7.extend(["--view-create-result", str(view_create_output)])
        if execution_dry_run:
            cmd7.append("--dry-run")
        ok7 = execute_step(7, "view_filters", "规划并应用视图筛选", cmd7, uses_gemini=True)
        if ok7:
            context["tableview_filter_plan_json"] = str(filter_plan_output)
            context["tableview_filter_apply_result_json"] = str(filter_apply_output)
        return ok7

    def run_step_12() -> bool:
        if not workflows.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 12, "step_key": "workflows_execute", "title": "创建工作流", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        if not ok11:
            with steps_lock:
                steps_report.append({"step_id": 12, "step_key": "workflows_execute", "title": "创建工作流", "skipped": True, "reason": "step11_failed", "result": {}})
            return True
        workflow_execute_output = (WORKFLOW_OUTPUT_DIR / "execute_workflow_plan_latest.json").resolve()
        cmd12 = [
            sys.executable, str(SCRIPT_EXECUTE_WORKFLOWS),
            "--plan-file", str(workflow_plan_output),
        ]
        if workflows.get("no_publish", False):
            cmd12.append("--no-publish")
        ok12 = execute_step(12, "workflows_execute", "创建工作流", cmd12, uses_gemini=False)
        if ok12:
            context["workflow_execute_result_json"] = str(workflow_execute_output)
        return ok12

    with ThreadPoolExecutor(max_workers=2) as pool:
        f7  = pool.submit(run_step_7)
        f12 = pool.submit(run_step_12)
        f7.result()
        f12.result()

    # ──────────────────────────────────────────────
    # Wave 6: Step 14 统计图表 Pages（依赖 Wave 4/5 完成）
    # ──────────────────────────────────────────────
    print(f"\n── Wave 6: 统计图表 Pages ─── 总计 {time.time()-pipeline_start:.0f}s", flush=True)

    def run_step_14() -> bool:
        if not pages_cfg.get("enabled", True):
            with steps_lock:
                steps_report.append({"step_id": 14, "step_key": "pages", "title": "创建统计图表页", "skipped": True, "reason": "disabled_by_spec", "result": {}})
            return True
        cmd14 = [
            sys.executable, str(SCRIPT_PIPELINE_PAGES),
            "--app-id", app_id,
            "--auth-config", str(CONFIG_WEB_AUTH),
            "--plan-output", str(page_plan_output),
        ]
        # Wave 4 已完成 Gemini 规划（14a），直接跳过规划阶段
        if ok_14a:
            cmd14.append("--skip-plan")
        if execution_dry_run:
            cmd14.append("--dry-run")
        title = "创建统计图表页" if ok_14a else "规划并创建统计图表页"
        return execute_step(14, "pages", title, cmd14, uses_gemini=not ok_14a)

    run_step_14()

    # ──────────────────────────────────────────────
    # Wave 7: 删除默认视图（最后一步，确保所有视图已创建完毕）
    # ──────────────────────────────────────────────
    print(f"\n── Wave 7: 删除[全部]默认视图 ─── 总计 {time.time()-pipeline_start:.0f}s", flush=True)
    run_step_13()

    out = save_report()
    report = build_report()

    total_elapsed = time.time() - pipeline_start
    print(f"\n── 执行完成  成功/跳过: {report['summary']['ok_or_skipped']}  失败: {report['summary']['failed']}  总耗时: {total_elapsed:.0f}s", flush=True)


if __name__ == "__main__":
    main()
