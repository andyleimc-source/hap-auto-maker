#!/usr/bin/env python3
"""
执行工作流规划 JSON，批量创建工作流（execute_workflow_plan.py）

读取 output/workflow_plan_latest.json（由 pipeline_workflows.py 生成），
为每个工作表创建：
  - 3 个自定义动作（按钮触发工作流）
  - 1 个工作表事件触发工作流
  - 1 个定时触发工作流

执行完成后，每个工作表理论上拥有 5 个新工作流：
  custom_action × 3 + worksheet_event × 1 + time_trigger × 1

结果写入：
  output/execute_workflow_plan_latest.json      - 执行汇总（最新覆盖）
  logs/execute_workflow_plan_{timestamp}.json   - 每次运行的详细日志

用法：
  cd /Users/andy/Desktop/hap_auto/workflow

  # 基础：读取默认 plan 文件，用 auth_config.py 或环境变量中的 Cookie
  python3 scripts/execute_workflow_plan.py

  # 指定 plan 文件
  python3 scripts/execute_workflow_plan.py \\
    --plan-file output/my_plan.json

  # 指定 Cookie（覆盖自动读取）
  python3 scripts/execute_workflow_plan.py \\
    --cookie 'your_cookie_here'

  # 跳过已成功创建的工作表（防止重复执行）
  python3 scripts/execute_workflow_plan.py \\
    --skip-existing

  # 只执行指定工作表（调试用）
  python3 scripts/execute_workflow_plan.py \\
    --only-worksheet 69aead6f952cd046bb57e3f2

  # 发布所有自定义动作工作流
  python3 scripts/execute_workflow_plan.py \\
    --publish-custom-actions
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from workflow_io import Session, persist


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    default_auth_config = project_root / "config" / "credentials" / "auth_config.py"
    scripts_dir = Path(__file__).parent
    default_plan = scripts_dir.parent / "output" / "pipeline_workflows_latest.json"

    parser = argparse.ArgumentParser(
        description="执行 workflow_plan_latest.json，批量创建所有工作流。"
    )
    parser.add_argument(
        "--plan-file",
        default=str(default_plan),
        help=f"工作流规划 JSON 文件路径（默认：{default_plan}）。",
    )
    parser.add_argument(
        "--cookie",
        default="",
        help="Cookie header 值。留空则自动从环境变量或 auth_config.py 加载。",
    )
    parser.add_argument(
        "--auth-config",
        default=str(default_auth_config),
        help="auth_config.py 路径（默认：config/credentials/auth_config.py）。",
    )
    parser.add_argument(
        "--origin",
        default="https://www.mingdao.com",
        help="请求 Origin header。",
    )
    parser.add_argument(
        "--publish-custom-actions",
        action="store_true",
        help="创建自定义动作后立即发布工作流（默认只创建不发布）。",
    )
    parser.add_argument(
        "--only-worksheet",
        default="",
        help="只执行指定工作表 ID（调试用，不填则执行全部）。",
    )
    parser.add_argument(
        "--skip-on-error",
        action="store_true",
        help="遇到错误时跳过当前工作流，继续执行后续（默认：继续）。",
    )
    return parser.parse_args()


# ── 认证解析 ───────────────────────────────────────────────────────────────────

def load_auth_from_auth_config(path: Path) -> tuple[str, str, str]:
    if not path.exists():
        return "", "", ""
    spec = importlib.util.spec_from_file_location("auth_config_runtime", str(path))
    if spec is None or spec.loader is None:
        return "", "", ""
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    account_id = str(getattr(module, "ACCOUNT_ID", "")).strip()
    authorization = str(getattr(module, "AUTHORIZATION", "")).strip()
    cookie = str(getattr(module, "COOKIE", "")).strip()
    return account_id, authorization, cookie


def resolve_auth(cli_cookie: str, auth_config_path: Path) -> tuple[str, str, str, str]:
    account_id = os.environ.get("MINGDAO_ACCOUNT_ID", "").strip()
    authorization = os.environ.get("MINGDAO_AUTHORIZATION", "").strip()

    if cli_cookie.strip():
        return account_id, authorization, cli_cookie.strip(), "cli"
    env_cookie = os.environ.get("MINGDAO_COOKIE", "").strip()
    if env_cookie:
        return account_id, authorization, env_cookie, "env"

    cfg_account_id, cfg_authorization, cfg_cookie = load_auth_from_auth_config(auth_config_path)
    if cfg_cookie:
        return cfg_account_id, cfg_authorization, cfg_cookie, f"auth_config:{auth_config_path}"
    return "", "", "", "none"


# ── 创建自定义动作工作流 ───────────────────────────────────────────────────────

def create_custom_action(
    session: Session,
    worksheet_id: str,
    app_id: str,
    name: str,
    confirm_msg: str,
    sure_name: str,
    cancel_name: str,
    publish: bool = False,
) -> dict:
    """
    创建自定义动作触发工作流（按钮触发）。
    流程：SaveWorksheetBtn → getProcessByTriggerId → (publish) → SaveWorksheetBtn(回填workflowId)
    """
    btn_payload = {
        "btnId": "",
        "name": name,
        "worksheetId": worksheet_id,
        "filters": [],
        "confirmMsg": confirm_msg,
        "sureName": sure_name,
        "cancelName": cancel_name,
        "workflowId": "",
        "desc": "",
        "appId": app_id,
        "isAllView": 1,
        "color": "transparent",
        "icon": "",
        "writeControls": [],
        "addRelationControlId": "",
        "relationControl": "",
        "writeType": "",
        "writeObject": "",
        "clickType": 1,
        "showType": 1,
        "advancedSetting": {
            "remarkrequired": "1",
            "remarkname": "操作原因",
            "tiptext": "操作完成",
        },
        "workflowType": 1,
    }

    # Step 1: 创建按钮（后端自动创建工作流）
    btn_resp = session.post(
        "https://www.mingdao.com/api/Worksheet/SaveWorksheetBtn",
        btn_payload,
    )
    print(
        f"    [SaveWorksheetBtn] state={btn_resp.get('state')} "
        f"data={btn_resp.get('data')!r}",
        file=sys.stderr,
    )

    if btn_resp.get("state") != 1:
        return {"ok": False, "step": "SaveWorksheetBtn(create)", "raw": btn_resp}

    btn_id = str(btn_resp.get("data", "")).strip()
    if not btn_id:
        return {"ok": False, "step": "btnId empty", "raw": btn_resp}

    # Step 2: 获取 processId
    trigger_resp = session.get(
        f"https://api.mingdao.com/workflow/process/getProcessByTriggerId"
        f"?appId={worksheet_id}&triggerId={btn_id}",
    )
    print(
        f"    [getProcessByTriggerId] status={trigger_resp.get('status')}",
        file=sys.stderr,
    )

    if trigger_resp.get("status") != 1:
        return {"ok": False, "step": "getProcessByTriggerId", "raw": trigger_resp}

    processes = trigger_resp.get("data") or []
    if not processes:
        return {"ok": False, "step": "no process found", "raw": trigger_resp}

    process = processes[0]
    process_id = str(process.get("id", "")).strip()
    start_event_id = str(process.get("startEventId", "")).strip()

    if not process_id:
        return {"ok": False, "step": "processId empty", "raw": trigger_resp}

    # Step 3: 可选发布
    if publish:
        pub_resp = session.get(
            f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={process_id}",
        )
        print(
            f"    [publish] isPublish={pub_resp.get('data', {}).get('isPublish')}",
            file=sys.stderr,
        )

    # Step 4: 回填 workflowId
    btn_payload_update = dict(btn_payload)
    btn_payload_update["btnId"] = btn_id
    btn_payload_update["workflowId"] = process_id

    btn_update_resp = session.post(
        "https://www.mingdao.com/api/Worksheet/SaveWorksheetBtn",
        btn_payload_update,
    )
    print(
        f"    [SaveWorksheetBtn(update)] state={btn_update_resp.get('state')}",
        file=sys.stderr,
    )

    return {
        "ok": True,
        "trigger_type": "custom_action",
        "name": name,
        "btn_id": btn_id,
        "process_id": process_id,
        "start_event_id": start_event_id,
        "publish_status": 1 if publish else 0,
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{process_id}",
    }


# ── 创建工作表事件触发工作流 ───────────────────────────────────────────────────

def create_worksheet_event(
    session: Session,
    relation_id: str,
    worksheet_id: str,
    name: str,
    trigger_id: str = "2",
) -> dict:
    """
    创建工作表事件触发工作流。
    流程：process/add → AppManagement/AddWorkflow → getProcessPublish → flowNode/saveNode
    """
    # Step 1: 创建工作流
    add_resp = session.post(
        "https://api.mingdao.com/workflow/process/add",
        {
            "companyId": "",
            "relationId": relation_id,
            "relationType": 2,
            "startEventAppType": 1,
            "name": name,
            "explain": "",
        },
    )
    print(
        f"    [process/add] status={add_resp.get('status')} "
        f"id={add_resp.get('data', {}).get('id')!r}",
        file=sys.stderr,
    )

    if add_resp.get("status") != 1:
        return {"ok": False, "step": "process/add", "raw": add_resp}

    data = add_resp.get("data") or {}
    process_id = str(data.get("id", "")).strip()
    company_id = str(data.get("companyId", "")).strip()

    if not (process_id and company_id):
        return {"ok": False, "step": "process_id/company_id empty", "raw": add_resp}

    # Step 2: 注册到 AppManagement
    session.post(
        "https://www.mingdao.com/api/AppManagement/AddWorkflow",
        {"projectId": company_id, "name": name},
        extra_headers={"Referer": f"https://www.mingdao.com/workflowedit/{process_id}"},
    )

    # Step 3: 获取 startNodeId
    publish_resp = session.get(
        f"https://api.mingdao.com/workflow/process/getProcessPublish?processId={process_id}",
    )
    start_node_id = ""
    if publish_resp.get("status") == 1:
        pdata = publish_resp.get("data") or {}
        start_node_id = str(pdata.get("startNodeId", "")).strip()
    print(
        f"    [getProcessPublish] startNodeId={start_node_id!r}",
        file=sys.stderr,
    )

    if not start_node_id:
        return {
            "ok": True,  # 工作流已创建，只是触发节点未配置
            "trigger_type": "worksheet_event",
            "name": name,
            "process_id": process_id,
            "start_node_configured": False,
            "warning": "saveNode skipped: startNodeId not found",
            "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{process_id}",
        }

    # Step 4: 配置触发节点（绑定工作表）
    save_node_resp = session.post(
        "https://api.mingdao.com/workflow/flowNode/saveNode",
        {
            "appId": worksheet_id,
            "appType": 1,
            "assignFieldIds": [],
            "processId": process_id,
            "nodeId": start_node_id,
            "flowNodeType": 0,
            "operateCondition": [],
            "triggerId": trigger_id,
            "name": "工作表事件触发",
            "controls": [],
        },
    )
    print(
        f"    [flowNode/saveNode] status={save_node_resp.get('status')} "
        f"msg={save_node_resp.get('msg')!r}",
        file=sys.stderr,
    )

    return {
        "ok": True,
        "trigger_type": "worksheet_event",
        "name": name,
        "process_id": process_id,
        "trigger_id": trigger_id,
        "start_node_configured": save_node_resp.get("status") == 1,
        "publish_status": 0,
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{process_id}",
    }


# ── 创建定时触发工作流 ─────────────────────────────────────────────────────────

def create_time_trigger(
    session: Session,
    relation_id: str,
    name: str,
    execute_time: str,
    execute_end_time: str = "",
    repeat_type: str = "1",
    interval: int = 1,
    frequency: int = 7,
    week_days: list | None = None,
) -> dict:
    """
    创建定时触发工作流。
    流程：process/add（startEventAppType=5）→ AppManagement/AddWorkflow → flowNode/saveNode
    """
    if week_days is None:
        week_days = []

    # Step 1: 创建工作流（时间触发 startEventAppType=5）
    add_resp = session.post(
        "https://api.mingdao.com/workflow/process/add",
        {
            "companyId": "",
            "relationId": relation_id,
            "relationType": 2,
            "startEventAppType": 5,
            "name": name,
            "explain": "",
        },
    )
    print(
        f"    [process/add] status={add_resp.get('status')} "
        f"id={add_resp.get('data', {}).get('id')!r}",
        file=sys.stderr,
    )

    if add_resp.get("status") != 1:
        return {"ok": False, "step": "process/add", "raw": add_resp}

    data = add_resp.get("data") or {}
    process_id = str(data.get("id", "")).strip()
    company_id = str(data.get("companyId", "")).strip()

    if not (process_id and company_id):
        return {"ok": False, "step": "process_id/company_id empty", "raw": add_resp}

    # Step 2: 注册到 AppManagement
    session.post(
        "https://www.mingdao.com/api/AppManagement/AddWorkflow",
        {"projectId": company_id, "name": name},
        extra_headers={"Referer": f"https://www.mingdao.com/workflowedit/{process_id}"},
    )

    # Step 3: 获取 startNodeId
    publish_resp = session.get(
        f"https://api.mingdao.com/workflow/process/getProcessPublish?processId={process_id}",
    )
    start_node_id = ""
    if publish_resp.get("status") == 1:
        pdata = publish_resp.get("data") or {}
        start_node_id = str(pdata.get("startNodeId", "")).strip()
    print(
        f"    [getProcessPublish] startNodeId={start_node_id!r}",
        file=sys.stderr,
    )

    if not start_node_id:
        return {
            "ok": True,
            "trigger_type": "time_trigger",
            "name": name,
            "process_id": process_id,
            "timer_configured": False,
            "warning": "saveNode skipped: startNodeId not found",
            "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{process_id}",
        }

    # Step 4: 配置定时触发节点
    save_node_resp = session.post(
        "https://api.mingdao.com/workflow/flowNode/saveNode",
        {
            "appType": 5,
            "assignFieldIds": [],
            "processId": process_id,
            "nodeId": start_node_id,
            "flowNodeType": 0,
            "name": "定时触发",
            "executeTime": execute_time,
            "executeEndTime": execute_end_time,
            "repeatType": repeat_type,
            "interval": interval,
            "frequency": frequency,
            "weekDays": week_days,
            "controls": [],
            "returns": [],
        },
    )
    print(
        f"    [flowNode/saveNode] status={save_node_resp.get('status')} "
        f"msg={save_node_resp.get('msg')!r}",
        file=sys.stderr,
    )

    return {
        "ok": True,
        "trigger_type": "time_trigger",
        "name": name,
        "process_id": process_id,
        "execute_time": execute_time,
        "execute_end_time": execute_end_time,
        "timer_configured": save_node_resp.get("status") == 1,
        "publish_status": 0,
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{process_id}",
    }


# ── 执行单个工作表的所有工作流 ─────────────────────────────────────────────────

def execute_worksheet_plan(
    session: Session,
    app_id: str,
    ws_plan: dict,
    publish_custom_actions: bool = False,
) -> dict:
    """
    对一个工作表执行完整的 5 个工作流创建：
      3 × custom_action + 1 × worksheet_event + 1 × time_trigger
    返回该工作表的执行结果汇总。
    """
    worksheet_id = ws_plan.get("worksheet_id", "")
    worksheet_name = ws_plan.get("worksheet_name", worksheet_id)
    results: list[dict] = []

    # ── 3 个自定义动作 ─────────────────────────────────────────────────────────
    for i, action in enumerate(ws_plan.get("custom_actions", [])[:3], 1):
        name = action.get("name", f"自定义动作{i}")
        confirm_msg = action.get("confirm_msg", "你确认执行此操作吗？")
        sure_name = action.get("sure_name", "确认")
        cancel_name = action.get("cancel_name", "取消")

        print(
            f"\n  [{i}/5] 自定义动作 \"{name}\"",
            file=sys.stderr,
        )
        try:
            result = create_custom_action(
                session=session,
                worksheet_id=worksheet_id,
                app_id=app_id,
                name=name,
                confirm_msg=confirm_msg,
                sure_name=sure_name,
                cancel_name=cancel_name,
                publish=publish_custom_actions,
            )
        except Exception as exc:
            result = {"ok": False, "step": "exception", "error": str(exc)}
            print(f"    ❌ 异常：{exc}", file=sys.stderr)

        result["seq"] = i
        results.append(result)
        status_icon = "✓" if result.get("ok") else "✗"
        print(f"    {status_icon} process_id={result.get('process_id')}", file=sys.stderr)

    # ── 工作表事件触发 ─────────────────────────────────────────────────────────
    ws_event = ws_plan.get("worksheet_event", {})
    event_name = ws_event.get("name", "工作表事件触发")
    trigger_id = str(ws_event.get("trigger_id", "2"))

    print(f"\n  [4/5] 工作表事件触发 \"{event_name}\"", file=sys.stderr)
    try:
        result = create_worksheet_event(
            session=session,
            relation_id=app_id,
            worksheet_id=worksheet_id,
            name=event_name,
            trigger_id=trigger_id,
        )
    except Exception as exc:
        result = {"ok": False, "step": "exception", "error": str(exc)}
        print(f"    ❌ 异常：{exc}", file=sys.stderr)

    result["seq"] = 4
    results.append(result)
    status_icon = "✓" if result.get("ok") else "✗"
    print(f"    {status_icon} process_id={result.get('process_id')}", file=sys.stderr)

    # ── 定时触发 ──────────────────────────────────────────────────────────────
    tt = ws_plan.get("time_trigger", {})
    tt_name = tt.get("name", "定时触发")
    execute_time = tt.get("execute_time", "")
    execute_end_time = tt.get("execute_end_time", "")
    repeat_type = str(tt.get("repeat_type", "1"))
    interval = int(tt.get("interval", 1))
    frequency = int(tt.get("frequency", 7))
    week_days = tt.get("week_days") or []

    print(f"\n  [5/5] 定时触发 \"{tt_name}\"", file=sys.stderr)
    try:
        result = create_time_trigger(
            session=session,
            relation_id=app_id,
            name=tt_name,
            execute_time=execute_time,
            execute_end_time=execute_end_time,
            repeat_type=repeat_type,
            interval=interval,
            frequency=frequency,
            week_days=week_days,
        )
    except Exception as exc:
        result = {"ok": False, "step": "exception", "error": str(exc)}
        print(f"    ❌ 异常：{exc}", file=sys.stderr)

    result["seq"] = 5
    results.append(result)
    status_icon = "✓" if result.get("ok") else "✗"
    print(f"    {status_icon} process_id={result.get('process_id')}", file=sys.stderr)

    ok_count = sum(1 for r in results if r.get("ok"))
    return {
        "worksheet_id": worksheet_id,
        "worksheet_name": worksheet_name,
        "total": len(results),
        "ok": ok_count,
        "failed": len(results) - ok_count,
        "workflows": results,
    }


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    started_at = time.time()
    args = parse_args()
    script_name = Path(__file__).stem
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    log_args = {k: v for k, v in vars(args).items() if k != "cookie"}

    # 1. 读取规划文件
    plan_path = Path(args.plan_file).expanduser().resolve()
    print(f"\n[step 1/3] 读取规划文件：{plan_path}", file=sys.stderr)
    if not plan_path.exists():
        print(
            f"Error: 规划文件不存在：{plan_path}\n"
            "  请先运行：python3 scripts/pipeline_workflows.py --relation-id <appId>",
            file=sys.stderr,
        )
        persist(script_name, None, args=log_args, error="plan file not found", started_at=started_at)
        return 2

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    app_id = plan.get("app_id", "")
    app_name = plan.get("app_name", "未知应用")
    worksheets = plan.get("worksheets", [])

    if not app_id:
        print("Error: 规划文件中缺少 app_id 字段。", file=sys.stderr)
        persist(script_name, None, args=log_args, error="missing app_id in plan", started_at=started_at)
        return 2

    # 过滤指定工作表
    if args.only_worksheet:
        worksheets = [ws for ws in worksheets if ws.get("worksheet_id") == args.only_worksheet]
        if not worksheets:
            print(f"Error: 未找到工作表 ID：{args.only_worksheet}", file=sys.stderr)
            return 2

    print(
        f"[step 1/3] ✓ 应用：{app_name}，共 {len(worksheets)} 个工作表，"
        f"预计创建 {len(worksheets) * 5} 个工作流",
        file=sys.stderr,
    )

    # 2. 解析认证
    account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
    if not cookie:
        print(
            "Error: 缺少 Cookie。\n"
            "  方式1：--cookie '...'\n"
            "  方式2：export MINGDAO_COOKIE='...'\n"
            "  方式3：在 config/credentials/auth_config.py 中设置 COOKIE 变量",
            file=sys.stderr,
        )
        persist(script_name, None, args=log_args, error="missing cookie", started_at=started_at)
        return 2

    print(f"[step 2/3] Cookie 来源：{cookie_source}", file=sys.stderr)
    session = Session(cookie, account_id, authorization, args.origin)

    # 3. 执行每个工作表的工作流创建
    print(f"\n[step 3/3] 开始批量创建工作流...", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    all_results: list[dict] = []
    total_ok = 0
    total_failed = 0

    for idx, ws_plan in enumerate(worksheets, 1):
        ws_name = ws_plan.get("worksheet_name", ws_plan.get("worksheet_id", "?"))
        ws_id = ws_plan.get("worksheet_id", "")
        print(
            f"\n【{idx}/{len(worksheets)}】工作表：{ws_name}（{ws_id}）",
            file=sys.stderr,
        )

        try:
            ws_result = execute_worksheet_plan(
                session=session,
                app_id=app_id,
                ws_plan=ws_plan,
                publish_custom_actions=args.publish_custom_actions,
            )
        except Exception as exc:
            print(f"  ❌ 工作表执行异常：{exc}", file=sys.stderr)
            ws_result = {
                "worksheet_id": ws_id,
                "worksheet_name": ws_name,
                "total": 5,
                "ok": 0,
                "failed": 5,
                "error": str(exc),
                "workflows": [],
            }

        all_results.append(ws_result)
        total_ok += ws_result.get("ok", 0)
        total_failed += ws_result.get("failed", 0)

        ok_icon = "✅" if ws_result.get("failed", 0) == 0 else "⚠️ "
        print(
            f"  {ok_icon} 完成：{ws_result.get('ok')}/{ws_result.get('total')} 成功",
            file=sys.stderr,
        )

    # 4. 汇总输出
    print("\n" + "=" * 60, file=sys.stderr)

    output = {
        "app_id": app_id,
        "app_name": app_name,
        "plan_file": str(plan_path),
        "executed_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "total_workflows": total_ok + total_failed,
        "ok": total_ok,
        "failed": total_failed,
        "worksheet_count": len(all_results),
        "publish_custom_actions": args.publish_custom_actions,
        "worksheets": all_results,
    }

    persist(script_name, output, args=log_args, started_at=started_at, session=session)

    # 打印汇总
    overall_icon = "✅" if total_failed == 0 else "⚠️ "
    print(f"{overall_icon} 执行完成！", file=sys.stderr)
    print(f"   应用：{app_name}", file=sys.stderr)
    print(f"   工作表数：{len(all_results)}", file=sys.stderr)
    print(f"   工作流创建成功：{total_ok} / {total_ok + total_failed}", file=sys.stderr)
    if total_failed > 0:
        print(f"   ⚠️  失败数：{total_failed}（详见 logs/ 目录）", file=sys.stderr)
    print(f"   结果文件：output/execute_workflow_plan_latest.json", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
