#!/usr/bin/env python3
"""
3a3 — 创建按日期字段触发工作流。

触发方式：按日期字段触发（startEventAppType=6）
Reference: api-specs/block1-private/workflow/create-workflow-date-trigger.md

与工作表事件触发的核心差异：
  - process/add 中 startEventAppType=6（工作表事件为 1）
  - saveNode 中 appType=6，固定 triggerId="2"
  - saveNode 中有 assignFieldId（监听的日期字段 ID）
  - saveNode 中有 executeTimeType / number / unit / endTime / frequency

典型用法:
    uv run python3 hap-auto-maker/workflow/scripts/create_workflow_date_trigger.py \\
        --relation-id <appId> \\
        --worksheet-id <worksheetId> \\
        --assign-field-id ctime \\
        --name "按日期字段触发工作流" \\
        --execute-time-type 0 \\
        --end-time "08:00" \\
        --frequency 1

executeTimeType 枚举:
  0 = 当天指定时刻触发（endTime 为执行时刻，如 "08:00"）
  1 = 日期前 N 单位触发（number 为偏移量）
  2 = 日期后 N 单位触发（number 为偏移量，endTime="" ）

unit 枚举: 1=分钟, 2=小时, 3=天（默认）
frequency 枚举: 0=不重复, 1=每年, 2=每月, 3=每周
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
        description="创建按日期字段触发工作流（startEventAppType=6）。"
    )
    parser.add_argument("--relation-id", required=True, help="App relationId（应用 UUID）。")
    parser.add_argument("--worksheet-id", required=True, help="监听的工作表 ID。")
    parser.add_argument(
        "--assign-field-id", required=True,
        help="监听的日期字段 ID（系统字段如 ctime=创建时间，mtime=更新时间）。",
    )
    parser.add_argument("--name", default="未命名工作流", help="工作流名称。")
    parser.add_argument(
        "--execute-time-type", type=int, default=0,
        help="触发时机：0=当天指定时刻, 1=日期前N单位, 2=日期后N单位（默认 0）。",
    )
    parser.add_argument(
        "--number", type=int, default=0,
        help="偏移数量（executeTimeType=1/2 时有效，默认 0）。",
    )
    parser.add_argument(
        "--unit", type=int, default=3,
        help="偏移单位：1=分钟, 2=小时, 3=天（默认 3）。",
    )
    parser.add_argument(
        "--end-time", default="08:00",
        help="当天执行时刻，格式 'HH:MM'（executeTimeType=2 时为 ''，默认 '08:00'）。",
    )
    parser.add_argument(
        "--execute-end-time", default="",
        help="结束执行时间的字段引用（如 wfdtime），无则留空。",
    )
    parser.add_argument(
        "--frequency", type=int, default=1,
        help="重复周期：0=不重复, 1=每年, 2=每月, 3=每周（默认 1）。",
    )
    parser.add_argument("--cookie", default="", help="Cookie header 值（留空则自动加载）。")
    parser.add_argument("--auth-config", default=str(default_auth_config), help="auth_config.py 路径。")
    parser.add_argument("--refresh-auth", action="store_true", help="创建前先刷新 auth。")
    parser.add_argument("--refresh-on-fail", action="store_true", help="失败时刷新 auth 后重试一次。")
    parser.add_argument("--headless", action="store_true", help="刷新 auth 时使用 headless 模式。")
    parser.add_argument("--origin", default="https://www.mingdao.com", help="请求 Origin header。")
    return parser.parse_args()


def load_auth_from_auth_config(path: Path) -> tuple[str, str, str]:
    if not path.exists():
        return "", "", ""
    spec = importlib.util.spec_from_file_location("auth_config_runtime", str(path))
    if spec is None or spec.loader is None:
        return "", "", ""
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return (
        str(getattr(module, "ACCOUNT_ID", "")).strip(),
        str(getattr(module, "AUTHORIZATION", "")).strip(),
        str(getattr(module, "COOKIE", "")).strip(),
    )


def refresh_auth(headless: bool) -> None:
    project_root = Path(__file__).resolve().parents[2]
    refresh_script = project_root / "scripts" / "auth" / "refresh_auth.py"
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
    # Step 1: 创建工作流进程
    process_add_resp = session.post(
        "https://api.mingdao.com/workflow/process/add",
        {
            "companyId": "",
            "relationId": args.relation_id,
            "relationType": 2,
            "startEventAppType": 6,  # 6 = 按日期字段触发
            "name": args.name,
            "explain": "",
        },
    )

    if process_add_resp.get("status") != 1:
        return process_add_resp

    data = process_add_resp.get("data", {}) if isinstance(process_add_resp.get("data"), dict) else {}
    process_id = str(data.get("id", "")).strip()
    company_id = str(data.get("companyId", "")).strip()

    if company_id and process_id:
        # Step 2: 注册到 AppManagement
        add_wf_resp = session.post(
            "https://www.mingdao.com/api/AppManagement/AddWorkflow",
            {"projectId": company_id, "name": args.name},
            extra_headers={"Referer": f"https://www.mingdao.com/workflowedit/{process_id}"},
        )
        print(
            f"[debug] AppManagement/AddWorkflow → {json.dumps(add_wf_resp, ensure_ascii=False)}",
            file=sys.stderr,
        )

        # Step 3: 获取触发节点 ID
        publish_resp = session.get(
            f"https://api.mingdao.com/workflow/process/getProcessPublish?processId={process_id}",
        )
        start_node_id = ""
        if publish_resp.get("status") == 1:
            pdata = publish_resp.get("data") or {}
            start_node_id = str(pdata.get("startNodeId", "")).strip()
        print(f"[debug] getProcessPublish → startNodeId={start_node_id!r}", file=sys.stderr)

        if start_node_id:
            # Step 4: 配置日期字段触发节点
            end_time = args.end_time
            if args.execute_time_type == 2:
                end_time = ""

            save_node_resp = session.post(
                "https://api.mingdao.com/workflow/flowNode/saveNode",
                {
                    "appId": args.worksheet_id,
                    "appType": 6,  # 6 = 按日期字段触发
                    "processId": process_id,
                    "nodeId": start_node_id,
                    "flowNodeType": 0,
                    "name": "按日期字段触发",
                    "triggerId": "2",
                    "assignFieldId": args.assign_field_id,
                    "assignFieldIds": [],
                    "executeTimeType": args.execute_time_type,
                    "number": args.number,
                    "unit": args.unit,
                    "time": "",
                    "endTime": end_time,
                    "executeEndTime": args.execute_end_time,
                    "frequency": args.frequency,
                    "operateCondition": [],
                    "controls": [],
                    "returns": [],
                },
            )
            print(
                f"[debug] flowNode/saveNode → status={save_node_resp.get('status')} "
                f"msg={save_node_resp.get('msg')}",
                file=sys.stderr,
            )

    return process_add_resp


def main() -> int:
    started_at = time.time()
    args = parse_args()
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    log_args = {k: v for k, v in vars(args).items() if k != "cookie"}

    if args.refresh_auth:
        print("Refreshing auth before create...", file=sys.stderr)
        refresh_auth(headless=args.headless)

    account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
    if not cookie:
        print("Error: missing cookie.", file=sys.stderr)
        persist("create_workflow_date_trigger", None, args=log_args,
                error="missing cookie", started_at=started_at)
        return 2

    session = Session(cookie, account_id, authorization, args.origin)

    try:
        result = create_once(args, session)
    except Exception as exc:
        if not args.refresh_on_fail:
            persist("create_workflow_date_trigger", None, args=log_args,
                    error=str(exc), started_at=started_at, session=session)
            raise
        print(f"Failed ({exc}), refreshing auth and retrying...", file=sys.stderr)
        refresh_auth(headless=args.headless)
        account_id, authorization, cookie, _ = resolve_auth(args.cookie, auth_config_path)
        if not cookie:
            print("Retry aborted: cookie still missing.", file=sys.stderr)
            persist("create_workflow_date_trigger", None, args=log_args,
                    error="cookie missing after refresh", started_at=started_at, session=session)
            return 2
        session = Session(cookie, account_id, authorization, args.origin)
        result = create_once(args, session)

    if result.get("status") != 1:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        print("Create workflow failed: status != 1", file=sys.stderr)
        persist("create_workflow_date_trigger", None, args=log_args,
                error=f"status={result.get('status')}", started_at=started_at, session=session)
        return 1

    data = result.get("data", {})
    output = {
        "process_id": data.get("id"),
        "app_id": args.relation_id,
        "worksheet_id": args.worksheet_id,
        "assign_field_id": args.assign_field_id,
        "trigger_type": "date_field",
        "execute_time_type": args.execute_time_type,
        "frequency": args.frequency,
        "name": data.get("name"),
        "publish_status": data.get("publishStatus"),
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{data.get('id')}",
        "cookie_source": cookie_source,
        "raw": result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    persist("create_workflow_date_trigger", output, args=log_args,
            started_at=started_at, session=session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
