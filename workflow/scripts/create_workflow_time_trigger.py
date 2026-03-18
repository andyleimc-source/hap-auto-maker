#!/usr/bin/env python3
"""
创建定时触发工作流（未发布态）。

触发方式：时间触发（startEventAppType=5）
Reference HAR:
- action/创建工作流-时间触发.har -> process/add + AppManagement/AddWorkflow + flowNode/saveNode

与工作表事件触发的核心差异：
  - process/add 中 startEventAppType=5（工作表事件为 1）
  - saveNode 中 appType=5，无 appId/triggerId/operateCondition
  - saveNode 中新增时间字段：executeTime、executeEndTime、repeatType、interval、frequency、weekDays
  - 无需 --worksheet-id，定时触发本身不绑定工作表
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from workflow_io import Session, persist


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    default_auth_config = project_root / "config" / "credentials" / "auth_config.py"
    parser = argparse.ArgumentParser(
        description="创建定时触发工作流（时间触发，startEventAppType=5）。"
    )
    parser.add_argument(
        "--relation-id",
        required=True,
        help="App relationId（示例：c2259f27-8b27-4ecb-8def-10fdff5911d9）。",
    )
    parser.add_argument(
        "--name",
        default="未命名工作流",
        help="工作流名称（默认：未命名工作流）。",
    )
    parser.add_argument(
        "--execute-time",
        default="",
        help="首次执行时间，格式 'YYYY-MM-DD HH:MM'（示例：2026-03-14 18:25）。留空则不调用 saveNode。",
    )
    parser.add_argument(
        "--execute-end-time",
        default="",
        help="结束执行时间，格式 'YYYY-MM-DD HH:MM'（示例：2026-03-31 18:25）。",
    )
    parser.add_argument(
        "--repeat-type",
        default="1",
        help="重复类型（默认：1）。",
    )
    parser.add_argument(
        "--interval",
        default="1",
        type=int,
        help="间隔数值（默认：1）。",
    )
    parser.add_argument(
        "--frequency",
        default="1",
        type=int,
        help="频率单位（默认：1）。",
    )
    parser.add_argument(
        "--week-days",
        default="[]",
        help="按周重复时的星期数组，JSON 格式（默认：[]）。",
    )
    parser.add_argument(
        "--cookie",
        default="",
        help="Cookie header 值。留空则自动从环境变量或 auth_config.py 加载。",
    )
    parser.add_argument(
        "--auth-config",
        default=str(default_auth_config),
        help="auth_config.py 路径（用于自动加载 cookie）。",
    )
    parser.add_argument(
        "--refresh-auth",
        action="store_true",
        help="创建前先刷新 auth（调用 scripts/auth/refresh_auth.py）。",
    )
    parser.add_argument(
        "--refresh-on-fail",
        action="store_true",
        help="创建失败时刷新 auth 后重试一次。",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="刷新 auth 时使用 headless 模式。",
    )
    parser.add_argument(
        "--origin",
        default="https://www.mingdao.com",
        help="请求 Origin header。",
    )
    return parser.parse_args()


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


def refresh_auth(headless: bool) -> None:
    project_root = Path(__file__).resolve().parents[2]
    refresh_script = project_root / "scripts" / "refresh_auth.py"
    if not refresh_script.exists():
        raise RuntimeError(f"Refresh script not found: {refresh_script}")
    cmd = [sys.executable, str(refresh_script)]
    if headless:
        cmd.append("--headless")
    subprocess.run(cmd, check=True)


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


def create_once(args: argparse.Namespace, session: Session) -> dict:
    # Step 1: 创建工作流
    process_add_resp = session.post(
        "https://api.mingdao.com/workflow/process/add",
        {
            "companyId": "",
            "relationId": args.relation_id,
            "relationType": 2,
            "startEventAppType": 5,  # 5 = 时间触发（工作表事件触发为 1）
            "name": args.name,
            "explain": "",
        },
    )

    if process_add_resp.get("status") == 1:
        data = process_add_resp.get("data", {}) if isinstance(process_add_resp.get("data"), dict) else {}
        process_id = str(data.get("id", "")).strip()
        company_id = str(data.get("companyId", "")).strip()

        if company_id and process_id:
            # Step 2: 注册到 AppManagement 列表
            add_wf_resp = session.post(
                "https://www.mingdao.com/api/AppManagement/AddWorkflow",
                {"projectId": company_id, "name": args.name},
                extra_headers={"Referer": f"https://www.mingdao.com/workflowedit/{process_id}"},
            )
            print(
                f"[debug] AppManagement/AddWorkflow → {json.dumps(add_wf_resp, ensure_ascii=False)}",
                file=sys.stderr,
            )

            # Step 3: 配置定时触发节点（仅当传入 --execute-time 时调用）
            if args.execute_time:
                publish_resp = session.get(
                    f"https://api.mingdao.com/workflow/process/getProcessPublish?processId={process_id}",
                )
                start_node_id = ""
                if publish_resp.get("status") == 1:
                    pdata = publish_resp.get("data") or {}
                    start_node_id = str(pdata.get("startNodeId", "")).strip()
                print(
                    f"[debug] getProcessPublish → startNodeId={start_node_id!r}",
                    file=sys.stderr,
                )

                if start_node_id:
                    try:
                        week_days = json.loads(args.week_days)
                    except (json.JSONDecodeError, TypeError):
                        week_days = []

                    save_node_resp = session.post(
                        "https://api.mingdao.com/workflow/flowNode/saveNode",
                        {
                            "appType": 5,  # 5 = 时间触发（工作表事件触发为 1）
                            "assignFieldIds": [],
                            "processId": process_id,
                            "nodeId": start_node_id,
                            "flowNodeType": 0,
                            "name": "定时触发",
                            "executeTime": args.execute_time,
                            "executeEndTime": args.execute_end_time,
                            "repeatType": args.repeat_type,
                            "interval": args.interval,
                            "frequency": args.frequency,
                            "weekDays": week_days,
                            "controls": [],
                            "returns": [],
                        },
                    )
                    print(
                        f"[debug] flowNode/saveNode → status={save_node_resp.get('status')} "
                        f"msg={save_node_resp.get('msg')}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "[debug] saveNode skipped: could not obtain startNodeId",
                        file=sys.stderr,
                    )

    return process_add_resp


def main() -> int:
    started_at = time.time()
    args = parse_args()
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    log_args = {k: v for k, v in vars(args).items() if k != "cookie"}

    if args.refresh_auth:
        print("Refreshing auth before create...")
        refresh_auth(headless=args.headless)

    account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
    if not cookie:
        print(
            "Error: missing cookie. Use --cookie / MINGDAO_COOKIE / valid auth_config.py.",
            file=sys.stderr,
        )
        persist("create_workflow_time_trigger", None, args=log_args,
                error="missing cookie", started_at=started_at)
        return 2

    session = Session(cookie, account_id, authorization, args.origin)

    try:
        result = create_once(args, session)
    except Exception as exc:
        if not args.refresh_on_fail:
            persist("create_workflow_time_trigger", None, args=log_args,
                    error=str(exc), started_at=started_at, session=session)
            raise
        print(f"Create failed ({exc}), trying auth refresh and one retry...", file=sys.stderr)
        refresh_auth(headless=args.headless)
        account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
        if not cookie:
            print("Retry aborted: cookie still missing after auth refresh.", file=sys.stderr)
            persist("create_workflow_time_trigger", None, args=log_args,
                    error="cookie missing after refresh", started_at=started_at, session=session)
            return 2
        session = Session(cookie, account_id, authorization, args.origin)
        result = create_once(args, session)

    status = result.get("status")
    if status != 1 and args.refresh_on_fail:
        print("Business create failed, trying auth refresh and one retry...", file=sys.stderr)
        refresh_auth(headless=args.headless)
        account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
        if not cookie:
            print("Retry aborted: cookie still missing after auth refresh.", file=sys.stderr)
            persist("create_workflow_time_trigger", None, args=log_args,
                    error="cookie missing after refresh", started_at=started_at, session=session)
            return 2
        session = Session(cookie, account_id, authorization, args.origin)
        result = create_once(args, session)
        status = result.get("status")

    if status != 1:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        print("Create workflow failed: status != 1", file=sys.stderr)
        persist("create_workflow_time_trigger", None, args=log_args,
                error=f"status={status}", started_at=started_at, session=session)
        return 1

    data = result.get("data", {})
    output = {
        "process_id": data.get("id"),
        "app_id": args.relation_id,
        "trigger_type": "time",
        "execute_time": args.execute_time or None,
        "execute_end_time": args.execute_end_time or None,
        "name": data.get("name"),
        "publish_status": data.get("publishStatus"),
        "created_date": data.get("createdDate"),
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{data.get('id')}",
        "app_workflow_list_url": f"https://www.mingdao.com/app/{args.relation_id}/workflow",
        "cookie_source": cookie_source,
        "raw": result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    persist("create_workflow_time_trigger", output, args=log_args,
            started_at=started_at, session=session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
