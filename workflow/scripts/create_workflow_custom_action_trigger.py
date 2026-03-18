#!/usr/bin/env python3
"""
创建自定义动作触发工作流（未发布态）。

触发方式：自定义动作（按钮触发，workflowType=1）
Reference HAR:
- action/创建工作流-自定义动作触发.har -> SaveWorksheetBtn + getProcessByTriggerId

与工作表/时间触发的核心差异：
  - 无 process/add 调用，工作流由 SaveWorksheetBtn 自动创建
  - 需要 --worksheet-id 和 --app-id（而非 --relation-id）
  - 流程：创建按钮 -> 通过 triggerId 获取 processId -> 可选发布 -> 回填 workflowId 更新按钮
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
        description="创建自定义动作触发工作流（按钮触发）。"
    )
    parser.add_argument(
        "--worksheet-id",
        required=True,
        help="目标工作表 ID（示例：69aead6fd777aea8806b9302）。",
    )
    parser.add_argument(
        "--app-id",
        required=True,
        help="应用 ID（示例：c2259f27-8b27-4ecb-8def-10fdff5911d9）。",
    )
    parser.add_argument(
        "--name",
        default="未命名按钮",
        help="按钮名称，同时作为工作流名称（默认：未命名按钮）。",
    )
    parser.add_argument(
        "--confirm-msg",
        default="你确认执行此操作吗？",
        help="确认弹窗提示语（默认：你确认执行此操作吗？）。",
    )
    parser.add_argument(
        "--sure-name",
        default="确认",
        help="确认按钮文案（默认：确认）。",
    )
    parser.add_argument(
        "--cancel-name",
        default="取消",
        help="取消按钮文案（默认：取消）。",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="创建后立即发布工作流。",
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
    btn_payload = {
        "btnId": "",
        "name": args.name,
        "worksheetId": args.worksheet_id,
        "filters": [],
        "confirmMsg": args.confirm_msg,
        "sureName": args.sure_name,
        "cancelName": args.cancel_name,
        "workflowId": "",
        "desc": "",
        "appId": args.app_id,
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

    # Step 1: 创建按钮（同时在后端自动创建工作流）
    btn_resp = session.post(
        "https://www.mingdao.com/api/Worksheet/SaveWorksheetBtn",
        btn_payload,
    )
    print(
        f"[debug] SaveWorksheetBtn (create) → {json.dumps(btn_resp, ensure_ascii=False)}",
        file=sys.stderr,
    )

    if btn_resp.get("state") != 1:
        return {"status": 0, "msg": "SaveWorksheetBtn failed", "raw": btn_resp}

    btn_id = str(btn_resp.get("data", "")).strip()
    if not btn_id:
        return {"status": 0, "msg": "btnId is empty", "raw": btn_resp}

    # Step 2: 通过 triggerId 获取自动创建的 processId
    trigger_resp = session.get(
        f"https://api.mingdao.com/workflow/process/getProcessByTriggerId"
        f"?appId={args.worksheet_id}&triggerId={btn_id}",
    )
    print(
        f"[debug] getProcessByTriggerId → status={trigger_resp.get('status')}",
        file=sys.stderr,
    )

    if trigger_resp.get("status") != 1:
        return {"status": 0, "msg": "getProcessByTriggerId failed", "raw": trigger_resp}

    processes = trigger_resp.get("data") or []
    if not processes:
        return {"status": 0, "msg": "no process found for trigger", "raw": trigger_resp}

    process = processes[0]
    process_id = str(process.get("id", "")).strip()
    start_event_id = str(process.get("startEventId", "")).strip()

    if not process_id:
        return {"status": 0, "msg": "processId is empty", "raw": trigger_resp}

    # Step 3: 可选发布
    if args.publish:
        pub_resp = session.get(
            f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={process_id}",
        )
        print(
            f"[debug] process/publish → isPublish={pub_resp.get('data', {}).get('isPublish')}",
            file=sys.stderr,
        )

    # Step 4: 回填 workflowId，更新按钮使其与工作流正式绑定
    btn_payload_update = dict(btn_payload)
    btn_payload_update["btnId"] = btn_id
    btn_payload_update["workflowId"] = process_id

    btn_update_resp = session.post(
        "https://www.mingdao.com/api/Worksheet/SaveWorksheetBtn",
        btn_payload_update,
    )
    print(
        f"[debug] SaveWorksheetBtn (update) → {json.dumps(btn_update_resp, ensure_ascii=False)}",
        file=sys.stderr,
    )

    return {
        "status": 1,
        "btn_id": btn_id,
        "process_id": process_id,
        "start_event_id": start_event_id,
        "process": process,
    }


def main() -> int:
    started_at = time.time()
    args = parse_args()
    script_name = Path(__file__).stem
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
        persist(script_name, None, args=log_args, error="missing cookie", started_at=started_at)
        return 2

    session = Session(cookie, account_id, authorization, args.origin)

    try:
        result = create_once(args, session)
    except Exception as exc:
        if not args.refresh_on_fail:
            persist(script_name, None, args=log_args,
                    error=str(exc), started_at=started_at, session=session)
            raise
        print(f"Create failed ({exc}), trying auth refresh and one retry...", file=sys.stderr)
        refresh_auth(headless=args.headless)
        account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
        if not cookie:
            persist(script_name, None, args=log_args,
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
            persist(script_name, None, args=log_args,
                    error="cookie missing after refresh", started_at=started_at, session=session)
            return 2
        session = Session(cookie, account_id, authorization, args.origin)
        result = create_once(args, session)
        status = result.get("status")

    if status != 1:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        print("Create workflow failed: status != 1", file=sys.stderr)
        persist(script_name, None, args=log_args,
                error=f"status={status}", started_at=started_at, session=session)
        return 1

    process = result.get("process", {})
    output = {
        "btn_id": result.get("btn_id"),
        "process_id": result.get("process_id"),
        "start_event_id": result.get("start_event_id"),
        "trigger_type": "custom_action",
        "worksheet_id": args.worksheet_id,
        "app_id": args.app_id,
        "name": args.name,
        "publish_status": 1 if args.publish else 0,
        "created_date": process.get("createdDate"),
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{result.get('process_id')}",
        "cookie_source": cookie_source,
        "raw": result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    persist(script_name, output, args=log_args, started_at=started_at, session=session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
