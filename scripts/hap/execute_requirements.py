#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
需求执行引擎：
读取 workflow_requirement_v1 JSON，并编排现有脚本执行全流程。

并行策略：
  - Wave 2:   Step 2a + Step 3 并行（受 Gemini 信号量约束）
  - Wave 2.5: Step 2c AI 规划工作表分组（串行，依赖 2a）；Step 8 在此之后执行（依赖分组数动态决定导航样式）
  - Wave 3:   Step 2d 创建分组（串行，依赖 2c）；Step 2b 创建工作表（依赖 2d）；
              Step 2d-2 移动工作表到分组（串行，依赖 2b）
  - Wave 4:   Step 4/5/6/9/10/11/14a 全部提交，Semaphore(3) 限制同时 Gemini 调用数
  - Wave 5:   Step 7（依赖 6）、Step 12（依赖 11），无 Gemini 限制
  - Wave 6:   Step 14 统计图表 Pages（串行，依赖 Wave 4/5 完成，用 Gemini）
  - Wave 7:   Step 13 删除默认视图（最后，确保所有视图已创建）
"""

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from ai_utils import AI_CONFIG_PATH
from script_locator import resolve_script
from utils import now_iso, load_json

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
EXECUTION_RUN_DIR = OUTPUT_ROOT / "execution_runs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"

CONFIG_ORG = BASE_DIR / "config" / "credentials" / "organization_auth.json"
CONFIG_WEB_AUTH = BASE_DIR / "config" / "credentials" / "auth_config.py"

WORKFLOW_SCRIPTS_DIR = BASE_DIR / "workflow" / "scripts"
WORKFLOW_OUTPUT_DIR = BASE_DIR / "workflow" / "output"

# ── Script paths ──────────────────────────────────────────────────────────────

def _scripts() -> dict:
    return {
        "create_app":          resolve_script("pipeline_create_app.py"),
        "plan_worksheets":     resolve_script("plan_app_worksheets_gemini.py"),
        "create_worksheets":   resolve_script("create_worksheets_from_plan.py"),
        "roles":               resolve_script("pipeline_app_roles.py"),
        "icon":                resolve_script("pipeline_icon.py"),
        "layout":              resolve_script("pipeline_worksheet_layout.py"),
        "views":               resolve_script("pipeline_views.py"),
        "view_filters":        resolve_script("pipeline_tableview_filters.py"),
        "navi":                resolve_script("update_app_navi_style.py"),
        "mock_data":           resolve_script("pipeline_mock_data.py"),
        "chatbots":            resolve_script("pipeline_chatbots.py"),
        "workflows_plan":      WORKFLOW_SCRIPTS_DIR / "pipeline_workflows.py",
        "workflows_execute":   WORKFLOW_SCRIPTS_DIR / "execute_workflow_plan.py",
        "delete_default_views": resolve_script("delete_default_views.py"),
        "pages":               resolve_script("pipeline_pages.py"),
        "plan_pages":          resolve_script("plan_pages_gemini.py"),
        "plan_sections":       resolve_script("plan_app_sections_gemini.py"),
        "create_sections":     resolve_script("create_sections_from_plan.py"),
    }


def _dirs() -> dict:
    return {
        "output_root":                    OUTPUT_ROOT,
        "execution_run_dir":              EXECUTION_RUN_DIR,
        "app_auth_dir":                   APP_AUTH_DIR,
        "worksheet_plan_dir":             WORKSHEET_PLAN_DIR,
        "view_plan_dir":                  OUTPUT_ROOT / "view_plans",
        "view_create_result_dir":         OUTPUT_ROOT / "view_create_results",
        "tableview_filter_plan_dir":      OUTPUT_ROOT / "tableview_filter_plans",
        "tableview_filter_apply_result_dir": OUTPUT_ROOT / "tableview_filter_apply_results",
        "sections_plan_dir":              OUTPUT_ROOT / "sections_plans",
        "sections_create_result_dir":     OUTPUT_ROOT / "sections_create_results",
        "workflow_output_dir":            WORKFLOW_OUTPUT_DIR,
        "config_web_auth":                CONFIG_WEB_AUTH,
    }


# ── spec 校验辅助 ──────────────────────────────────────────────────────────────

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
    try:
        data = load_json(CONFIG_ORG)
        return str(data.get("group_ids", "")).strip()
    except FileNotFoundError:
        pass
    except Exception as e:
        warnings.warn(f"读取 organization_auth.json 失败: {e}")
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
    except (ValueError, TypeError):
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
    workflows.setdefault("skip_analysis", True)
    spec["workflows"] = workflows

    delete_default_views = spec.get("delete_default_views") if isinstance(spec.get("delete_default_views"), dict) else {}
    delete_default_views.setdefault("enabled", True)
    delete_default_views.setdefault("refresh_auth", False)
    spec["delete_default_views"] = delete_default_views

    pages = spec.get("pages") if isinstance(spec.get("pages"), dict) else {}
    pages.setdefault("enabled", True)
    spec["pages"] = pages

    execution = spec.get("execution") if isinstance(spec.get("execution"), dict) else {}
    execution.setdefault("fail_fast", True)
    execution.setdefault("dry_run", False)
    spec["execution"] = execution
    return spec


def _required_configs(spec: dict) -> List[Tuple[Path, str]]:
    out = [(AI_CONFIG_PATH, "AI 配置"), (CONFIG_ORG, "组织认证配置")]
    ws = spec["worksheets"]
    views = spec["views"]
    view_filters = spec["view_filters"]
    navi = spec["app"]["navi_style"]
    need_web_auth = any([
        ws["icon_update"]["enabled"] and not ws["icon_update"].get("refresh_auth", False),
        ws["layout"]["enabled"] and not ws["layout"].get("refresh_auth", False),
        views.get("enabled", True),
        view_filters.get("enabled", True),
        navi["enabled"] and not navi.get("refresh_auth", False),
    ])
    if need_web_auth:
        out.append((CONFIG_WEB_AUTH, "网页认证配置"))
    return out


def _ensure_scripts_exist(scripts: dict) -> None:
    missing = [str(p) for p in scripts.values() if not Path(p).exists()]
    if missing:
        raise FileNotFoundError("缺少脚本:\n" + "\n".join(missing))


def _parse_only_steps(value: str) -> set:
    if not value.strip():
        return set()
    return {x.strip().lower() for x in value.split(",") if x.strip()}


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="执行 workflow_requirement_v1 需求 JSON")
    parser.add_argument("--spec-json", required=True, help="需求 JSON 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅输出执行计划，不实际调用")
    parser.add_argument("--continue-on-error", action="store_true", help="遇错继续执行后续步骤")
    parser.add_argument("--only-steps", default="", help="仅执行指定步骤（逗号分隔）")
    parser.add_argument("--verbose", action="store_true", help="打印子脚本完整输出")
    parser.add_argument("--gemini-concurrency", type=int, default=3, help="Gemini API 最大并发调用数（默认 3）")
    parser.add_argument("--app-id", default="", help="已有应用 ID，跳过创建步骤")
    args = parser.parse_args()

    pipeline_start = time.time()
    spec_path = Path(args.spec_json).expanduser().resolve()
    spec = normalize_spec(load_json(spec_path))

    if args.app_id.strip():
        spec["app"]["target_mode"] = "use_existing"
        spec["app"]["app_id"] = args.app_id.strip()
    if spec.get("schema_version") != "workflow_requirement_v1":
        raise ValueError("schema_version 必须是 workflow_requirement_v1")

    scripts = _scripts()
    for cfg, name in _required_configs(spec):
        if not cfg.exists():
            raise FileNotFoundError(f"缺少{name}: {cfg}")
    _ensure_scripts_exist(scripts)

    execution_dry_run = bool(args.dry_run or spec["execution"].get("dry_run", False))
    fail_fast = bool(spec["execution"].get("fail_fast", True)) and (not args.continue_on_error)
    selected_steps = _parse_only_steps(args.only_steps)
    gemini_semaphore = threading.Semaphore(args.gemini_concurrency)

    from pipeline.waves import run_all_waves
    ctx = run_all_waves(
        spec,
        spec_path,
        execution_dry_run=execution_dry_run,
        fail_fast=fail_fast,
        verbose=args.verbose,
        selected_steps=selected_steps,
        gemini_semaphore=gemini_semaphore,
        pipeline_start=pipeline_start,
        scripts=scripts,
        dirs=_dirs(),
    )

    out = ctx.save_report()
    report = ctx.build_report()
    total_elapsed = time.time() - pipeline_start
    print(
        f"\n── 执行完成  成功/跳过: {report['summary']['ok_or_skipped']}"
        f"  失败: {report['summary']['failed']}  总耗时: {total_elapsed:.0f}s",
        flush=True,
    )
    print(f"- 报告: {out}")


if __name__ == "__main__":
    main()
