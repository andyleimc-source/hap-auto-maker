#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_workflow.py — 为已有应用中的某个工作表增量添加工作流。

流程：
  1. 通过 app_context 获取应用上下文（工作表 + 字段）
  2. 调用 workflow_planner（两阶段）规划工作流
  3. 调用 execute_workflow_plan 执行创建

用法（CLI）：
    python3 add_workflow.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --description "审批工作流：提交后通知审批人"

    python3 add_workflow.py \\
        --app-id <appId> \\
        --all-worksheets   # 为所有工作表规划工作流

用法（Python）：
    from incremental.add_workflow import add_workflow_for_worksheet
    result = add_workflow_for_worksheet(
        app_id="xxx",
        worksheet_id="yyy",
        description="审批工作流",
    )
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_HAP = BASE_DIR / "scripts" / "hap"
WORKFLOW_SCRIPTS = BASE_DIR / "workflow" / "scripts"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
INCREMENTAL_OUTPUT_DIR = OUTPUT_ROOT / "incremental"

for p in [str(SCRIPTS_HAP), str(WORKFLOW_SCRIPTS)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from incremental.app_context import load_app_context
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json
from planning.workflow_planner import (
    build_structure_prompt,
    validate_structure_plan,
    build_node_config_prompt,
    validate_node_config,
)


# ── AI 调用工具 ────────────────────────────────────────────────────────────────

def call_ai(prompt: str, config: dict) -> str:
    client = get_ai_client(config)
    gen_cfg = create_generation_config(config, response_mime_type="application/json")
    resp = client.models.generate_content(
        model=config["model"],
        contents=prompt,
        config=gen_cfg,
    )
    if hasattr(resp, "text"):
        return resp.text
    return str(resp)


# ── 规划 ───────────────────────────────────────────────────────────────────────

def plan_workflows_for_worksheets(
    app_name: str,
    worksheets_info: list[dict],
    ai_config: dict,
    ca_per_ws: int = 2,
    ev_per_ws: int = 1,
    num_tt: int = 1,
) -> dict:
    """
    两阶段规划工作流：Phase 1（骨架）→ Phase 2（节点配置）。

    Args:
        worksheets_info: [{"worksheetId": ..., "worksheetName": ..., "fields": [...]}]
    Returns:
        完整 workflow plan dict
    """
    worksheets_by_id = {ws["worksheetId"]: ws for ws in worksheets_info}

    # Phase 1: 规划骨架
    print("  [Phase 1] 规划工作流骨架...")
    p1_prompt = build_structure_prompt(
        app_name=app_name,
        worksheets_info=worksheets_info,
        ca_per_ws=ca_per_ws,
        ev_per_ws=ev_per_ws,
        num_tt=num_tt,
    )
    p1_raw = call_ai(p1_prompt, ai_config)
    p1_plan = parse_ai_json(p1_raw)
    p1_plan = validate_structure_plan(p1_plan, worksheets_by_id)
    print(f"  [Phase 1] 完成，工作表数: {len(p1_plan.get('worksheets', []))}")

    # Phase 2: 填充节点配置
    print("  [Phase 2] 规划节点配置...")
    p2_prompt = build_node_config_prompt(
        app_name=app_name,
        structure_plan=p1_plan,
        worksheets_info=worksheets_info,
    )
    p2_raw = call_ai(p2_prompt, ai_config)
    p2_plan = parse_ai_json(p2_raw)
    p2_plan = validate_node_config(p2_plan, worksheets_by_id)
    print("  [Phase 2] 完成")

    return p2_plan


# ── 执行 ───────────────────────────────────────────────────────────────────────

def _load_execute_module():
    """动态加载 execute_workflow_plan.py。"""
    exec_path = WORKFLOW_SCRIPTS / "execute_workflow_plan.py"
    if not exec_path.exists():
        raise FileNotFoundError(f"找不到 execute_workflow_plan.py: {exec_path}")
    spec = importlib.util.spec_from_file_location("execute_workflow_plan", exec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def execute_workflow_plan(plan: dict, app_id: str, auth_config_path: Optional[Path] = None) -> dict:
    """
    执行工作流规划，调用 execute_workflow_plan.py 的核心逻辑。

    Returns:
        {"created": [...], "failed": [...], "skipped": [...]}
    """
    # 将 plan 写到临时文件
    INCREMENTAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    plan_file = INCREMENTAL_OUTPUT_DIR / f"workflow_plan_{app_id}_{ts}.json"
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  工作流规划已保存: {plan_file}")

    if auth_config_path is None:
        auth_config_path = BASE_DIR / "config" / "credentials" / "auth_config.py"

    mod = _load_execute_module()

    # 修改 sys.argv 以传参给 execute_workflow_plan
    orig_argv = sys.argv[:]
    sys.argv = [
        "execute_workflow_plan.py",
        "--plan-file", str(plan_file),
        "--auth-config", str(auth_config_path),
    ]
    try:
        # 调用模块 main() — execute_workflow_plan.py 把结果打印到 stdout
        # 我们通过捕获其内部函数来获取结构化结果
        args = mod.parse_args()
        account_id, authorization, cookie = mod.load_auth_from_auth_config(args.auth_config)
        if not cookie and not authorization:
            raise RuntimeError(f"auth_config.py 缺少认证信息: {args.auth_config}")
        account_id, authorization, cookie, origin = mod.resolve_auth(
            args.cookie, Path(args.auth_config)
        )
        plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
        result = mod.run_plan(plan_data, account_id, authorization, cookie, origin, args)
        return result if isinstance(result, dict) else {"status": "executed", "plan_file": str(plan_file)}
    except AttributeError:
        # execute_workflow_plan 没有 run_plan 函数时，降级到 subprocess 调用
        return _execute_via_subprocess(plan_file, auth_config_path)
    finally:
        sys.argv = orig_argv


def _execute_via_subprocess(plan_file: Path, auth_config_path: Path) -> dict:
    """降级方案：通过 subprocess 调用 execute_workflow_plan.py。"""
    import subprocess
    exec_path = WORKFLOW_SCRIPTS / "execute_workflow_plan.py"
    result = subprocess.run(
        [sys.executable, str(exec_path),
         "--plan-file", str(plan_file),
         "--auth-config", str(auth_config_path)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"execute_workflow_plan 失败:\n{result.stderr[-2000:]}")
    print(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
    return {"status": "executed_subprocess", "plan_file": str(plan_file)}


# ── 公共接口 ───────────────────────────────────────────────────────────────────

def add_workflow_for_worksheet(
    app_id: str,
    worksheet_id: str,
    description: str = "",
    app_auth_json: str = "",
    ai_config: Optional[dict] = None,
    execute: bool = True,
) -> dict:
    """
    为指定工作表添加工作流（完整流程：规划 + 创建）。

    Args:
        app_id: 应用 ID
        worksheet_id: 目标工作表 ID
        description: 业务描述，提示 AI 规划方向
        app_auth_json: 授权文件路径（默认自动查找）
        ai_config: AI 配置（默认从 ai_auth.json 加载）
        execute: 是否真实创建（False 时只生成 plan JSON）
    Returns:
        {"plan": {...}, "result": {...}}
    """
    if ai_config is None:
        ai_config = load_ai_config(tier="fast")

    print(f"\n[add_workflow] 加载应用上下文 app_id={app_id}...")
    ctx = load_app_context(app_id=app_id, app_auth_json=app_auth_json)

    # 找到目标工作表
    target_ws = next((ws for ws in ctx["worksheets"] if ws["worksheetId"] == worksheet_id), None)
    if not target_ws:
        available = [f"{ws['worksheetName']}({ws['worksheetId']})" for ws in ctx["worksheets"]]
        raise ValueError(f"找不到工作表 {worksheet_id}，可用工作表: {', '.join(available)}")

    # 构建给规划器的 worksheets_info（只含目标表及其关联表字段）
    worksheets_info = _build_worksheets_info_for_planner([target_ws])

    app_name = _guess_app_name(ctx)
    if description:
        app_name = f"{app_name}（{description}）"

    print(f"[add_workflow] 开始规划工作流，目标工作表: {target_ws['worksheetName']}...")
    plan = plan_workflows_for_worksheets(
        app_name=app_name,
        worksheets_info=worksheets_info,
        ai_config=ai_config,
        ca_per_ws=2,
        ev_per_ws=1,
        num_tt=0,
    )

    result = {}
    if execute:
        print("[add_workflow] 执行工作流创建...")
        result = execute_workflow_plan(plan, app_id)
    else:
        INCREMENTAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        plan_file = INCREMENTAL_OUTPUT_DIR / f"workflow_plan_{app_id}_{ts}.json"
        plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[add_workflow] 已生成规划（未执行）: {plan_file}")
        result = {"status": "plan_only", "plan_file": str(plan_file)}

    return {"plan": plan, "result": result}


def add_workflows_for_all(
    app_id: str,
    app_auth_json: str = "",
    ai_config: Optional[dict] = None,
    execute: bool = True,
    ca_per_ws: int = 2,
    ev_per_ws: int = 1,
    num_tt: int = 1,
) -> dict:
    """为应用所有工作表批量规划+创建工作流。"""
    if ai_config is None:
        ai_config = load_ai_config(tier="fast")

    print(f"\n[add_workflow] 加载应用上下文 app_id={app_id}...")
    ctx = load_app_context(app_id=app_id, app_auth_json=app_auth_json)

    worksheets_info = _build_worksheets_info_for_planner(ctx["worksheets"])
    app_name = _guess_app_name(ctx)

    print(f"[add_workflow] 规划 {len(worksheets_info)} 个工作表的工作流...")
    plan = plan_workflows_for_worksheets(
        app_name=app_name,
        worksheets_info=worksheets_info,
        ai_config=ai_config,
        ca_per_ws=ca_per_ws,
        ev_per_ws=ev_per_ws,
        num_tt=num_tt,
    )

    result = {}
    if execute:
        print("[add_workflow] 执行工作流创建...")
        result = execute_workflow_plan(plan, app_id)
    else:
        INCREMENTAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        plan_file = INCREMENTAL_OUTPUT_DIR / f"workflow_plan_{app_id}_{ts}.json"
        plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {"status": "plan_only", "plan_file": str(plan_file)}

    return {"plan": plan, "result": result}


# ── 内部工具 ───────────────────────────────────────────────────────────────────

def _build_worksheets_info_for_planner(worksheets: list[dict]) -> list[dict]:
    """将 app_context 的 worksheets 格式转换为 workflow_planner 期望的格式。"""
    result = []
    for ws in worksheets:
        fields = ws.get("fields", [])
        # 字段 id 归一化（v3 API 返回 controlId，规划器期望 id）
        normalized_fields = []
        for f in fields:
            nf = dict(f)
            if not nf.get("id"):
                nf["id"] = nf.get("controlId", "")
            if not nf.get("name"):
                nf["name"] = nf.get("controlName", "")
            if not nf.get("type") and nf.get("type") != 0:
                nf["type"] = nf.get("controlType", 0)
            # options: v3 API 返回 options 列表
            if "options" not in nf and "options" in f:
                nf["options"] = f["options"]
            normalized_fields.append(nf)

        result.append({
            "worksheetId": ws["worksheetId"],
            "worksheetName": ws["worksheetName"],
            "fields": normalized_fields,
        })
    return result


def _guess_app_name(ctx: dict) -> str:
    """从上下文推断应用名称（暂用 app_id 代替，未来可从 API 获取）。"""
    return ctx.get("app_name", f"应用({ctx['app_id'][:8]}...)")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="增量添加工作流到已有应用")
    parser.add_argument("--app-id", default="", help="应用 ID")
    parser.add_argument("--app-auth-json", default="", help="授权 JSON 文件路径")
    parser.add_argument("--worksheet-id", default="", help="目标工作表 ID（不传则处理所有工作表）")
    parser.add_argument("--description", default="", help="业务描述，指导 AI 规划方向")
    parser.add_argument("--no-execute", action="store_true", help="只生成规划，不实际创建")
    parser.add_argument("--ca-per-ws", type=int, default=2, help="每个工作表的自定义动作数（默认 2）")
    parser.add_argument("--ev-per-ws", type=int, default=1, help="每个工作表的事件触发数（默认 1）")
    parser.add_argument("--num-tt", type=int, default=1, help="全局定时触发数（默认 1）")
    args = parser.parse_args()

    if not args.app_id and not args.app_auth_json:
        parser.error("请传 --app-id 或 --app-auth-json")

    execute = not args.no_execute

    if args.worksheet_id:
        result = add_workflow_for_worksheet(
            app_id=args.app_id,
            worksheet_id=args.worksheet_id,
            description=args.description,
            app_auth_json=args.app_auth_json,
            execute=execute,
        )
    else:
        result = add_workflows_for_all(
            app_id=args.app_id,
            app_auth_json=args.app_auth_json,
            execute=execute,
            ca_per_ws=args.ca_per_ws,
            ev_per_ws=args.ev_per_ws,
            num_tt=args.num_tt,
        )

    print("\n[add_workflow] 完成")
    if "result" in result:
        print(json.dumps(result["result"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
