#!/usr/bin/env python3
"""
创建工作表事件触发工作流（未发布态）。

触发方式：工作表事件触发（startEventAppType=1）
Reference HAR:
- action/创建工作流.har          -> process/add + AppManagement/AddWorkflow
- action/新建工作流-61fad723.har -> adds flowNode/saveNode (links worksheet trigger)

Why saveNode is required:
  listAll (the API that powers the workflow list UI) groups workflows by their
  configured trigger worksheet. A workflow with no trigger configured has no
  groupId and is therefore invisible in the list. saveNode sets the trigger
  worksheet (appId) on the start node, making the workflow visible in listAll.
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
        description="Create a new unpublished workflow via Mingdao API."
    )
    parser.add_argument(
        "--relation-id",
        required=True,
        help="App relationId (example: c2259f27-8b27-4ecb-8def-10fdff5911d9).",
    )
    parser.add_argument(
        "--worksheet-id",
        default="",
        help=(
            "Worksheet ID to bind as the trigger source (appId in saveNode). "
            "Required for the workflow to appear in the app workflow list. "
            "Example: 69aead6f952cd046bb57e3f2"
        ),
    )
    parser.add_argument(
        "--trigger-id",
        default="2",
        help=(
            "Trigger type ID passed to saveNode (default: 2 = 新增或更新记录时). "
            "1=仅新增, 2=新增或更新, 3=删除, 4=仅更新. "
            "Only used when --worksheet-id is provided."
        ),
    )
    parser.add_argument(
        "--name",
        default="未命名工作流",
        help="Workflow name (default: 未命名工作流).",
    )
    parser.add_argument(
        "--cookie",
        default="",
        help="Cookie header value. If omitted, auto-load from env/auth_config.py.",
    )
    parser.add_argument(
        "--auth-config",
        default=str(default_auth_config),
        help="Path to auth_config.py (used for auto-loading cookie).",
    )
    parser.add_argument(
        "--refresh-auth",
        action="store_true",
        help="Refresh auth via scripts/auth/refresh_auth.py before creating workflow.",
    )
    parser.add_argument(
        "--refresh-on-fail",
        action="store_true",
        help="If create fails, refresh auth then retry once.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Use headless mode when refreshing auth.",
    )
    parser.add_argument(
        "--origin",
        default="https://www.mingdao.com",
        help="Request origin header.",
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
    # Step 1: create the workflow process
    process_add_resp = session.post(
        "https://api.mingdao.com/workflow/process/add",
        {
            "companyId": "",
            "relationId": args.relation_id,
            "relationType": 2,
            "startEventAppType": 1,
            "name": args.name,
            "explain": "",
        },
    )

    if process_add_resp.get("status") == 1:
        data = process_add_resp.get("data", {}) if isinstance(process_add_resp.get("data"), dict) else {}
        process_id = str(data.get("id", "")).strip()
        company_id = str(data.get("companyId", "")).strip()

        if company_id and process_id:
            # Step 2: register workflow in app management list.
            # HAR shows Referer must be workflowedit/{processId} for this call.
            add_wf_resp = session.post(
                "https://www.mingdao.com/api/AppManagement/AddWorkflow",
                {"projectId": company_id, "name": args.name},
                extra_headers={"Referer": f"https://www.mingdao.com/workflowedit/{process_id}"},
            )
            print(
                f"[debug] AppManagement/AddWorkflow → {json.dumps(add_wf_resp, ensure_ascii=False)}",
                file=sys.stderr,
            )

            # Step 3: bind the trigger worksheet via saveNode so the workflow
            # appears in listAll (the workflow list UI). Without this step,
            # the workflow has no groupId and is invisible in the list.
            if args.worksheet_id:
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
                    save_node_resp = session.post(
                        "https://api.mingdao.com/workflow/flowNode/saveNode",
                        {
                            "appId": args.worksheet_id,
                            "appType": 1,
                            "assignFieldIds": [],
                            "processId": process_id,
                            "nodeId": start_node_id,
                            "flowNodeType": 0,
                            "operateCondition": [],
                            "triggerId": args.trigger_id,
                            "name": "工作表事件触发",
                            "controls": [],
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
        persist("create_workflow_worksheet_trigger", None, args=log_args,
                error="missing cookie", started_at=started_at)
        return 2

    session = Session(cookie, account_id, authorization, args.origin)

    try:
        result = create_once(args, session)
    except Exception as exc:
        if not args.refresh_on_fail:
            persist("create_workflow_worksheet_trigger", None, args=log_args,
                    error=str(exc), started_at=started_at, session=session)
            raise
        print(f"Create failed ({exc}), trying auth refresh and one retry...", file=sys.stderr)
        refresh_auth(headless=args.headless)
        account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
        if not cookie:
            print("Retry aborted: cookie still missing after auth refresh.", file=sys.stderr)
            persist("create_workflow_worksheet_trigger", None, args=log_args,
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
            persist("create_workflow_worksheet_trigger", None, args=log_args,
                    error="cookie missing after refresh", started_at=started_at, session=session)
            return 2
        session = Session(cookie, account_id, authorization, args.origin)
        result = create_once(args, session)
        status = result.get("status")

    if status != 1:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        print("Create workflow failed: status != 1", file=sys.stderr)
        persist("create_workflow_worksheet_trigger", None, args=log_args,
                error=f"status={status}", started_at=started_at, session=session)
        return 1

    data = result.get("data", {})
    output = {
        "process_id": data.get("id"),
        "app_id": args.relation_id,
        "worksheet_id": args.worksheet_id or None,
        "name": data.get("name"),
        "publish_status": data.get("publishStatus"),
        "created_date": data.get("createdDate"),
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{data.get('id')}",
        "app_workflow_list_url": f"https://www.mingdao.com/app/{args.relation_id}/workflow",
        "cookie_source": cookie_source,
        "raw": result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    persist("create_workflow_worksheet_trigger", output, args=log_args,
            started_at=started_at, session=session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
