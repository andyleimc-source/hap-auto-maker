#!/usr/bin/env python3
"""
Add a "新增记录" action node to an existing HAP workflow.

Reference HAR:
- action/创建新增记录节点.har
- POST https://api.mingdao.com/workflow/flowNode/add
- POST https://api.mingdao.com/workflow/flowNode/saveNode
- GET  https://api.mingdao.com/workflow/process/publish  (optional)

Typical usage:
    python3 scripts/add_new_record_node.py \\
        --process-id  'YOUR_PROCESS_ID' \\
        --prev-node-id 'YOUR_PREV_NODE_ID' \\
        --worksheet-id 'YOUR_WORKSHEET_ID' \\
        --fields '[{"fieldId":"xxx","type":2,"enumDefault":0,"fieldValue":"hello"}]' \\
        --publish

Field value formats:
  - Static text:       "hello"
  - Dynamic (from another node): "$<nodeId>-<fieldId>$"
  - Empty (leave blank): ""
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    default_auth_config = project_root / "config" / "credentials" / "auth_config.py"
    parser = argparse.ArgumentParser(
        description="Add a 新增记录 action node to an existing workflow."
    )
    parser.add_argument(
        "--process-id",
        required=True,
        help="Workflow process ID (e.g. 69b4b92f9c92de5d02cd921f).",
    )
    parser.add_argument(
        "--prev-node-id",
        required=True,
        help="ID of the node this new node should be inserted after (usually the trigger node).",
    )
    parser.add_argument(
        "--worksheet-id",
        required=True,
        help="Target worksheet ID where new records will be created.",
    )
    parser.add_argument(
        "--name",
        default="新增记录",
        help="Display name for the node (default: 新增记录).",
    )
    parser.add_argument(
        "--fields",
        default="[]",
        help=(
            "JSON array of field mappings, or path to a .json file. "
            "Each item: {fieldId, type, enumDefault, fieldValue, ...}. "
            "Dynamic ref format: \"$<nodeId>-<fieldId>$\". "
            "Default: [] (no pre-filled fields, configure in UI)."
        ),
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish the workflow after adding the node.",
    )
    parser.add_argument(
        "--cookie",
        default="",
        help="Cookie header value. If omitted, auto-load from env/auth_config.py.",
    )
    parser.add_argument(
        "--auth-config",
        default=str(default_auth_config),
        help="Path to auth_config.py.",
    )
    parser.add_argument(
        "--refresh-auth",
        action="store_true",
        help="Refresh auth before running.",
    )
    parser.add_argument(
        "--refresh-on-fail",
        action="store_true",
        help="Refresh auth and retry once on failure.",
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


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _make_headers(base: dict) -> dict:
    return {k: v for k, v in base.items() if v}


def post_json(url: str, payload: dict, headers: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url=url, data=data, method="POST")
    for k, v in _make_headers(headers).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"HTTP {err.code}: {err.read().decode()}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"Network error: {err}") from err


def get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url=url, method="GET")
    for k, v in _make_headers(headers).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"HTTP {err.code}: {err.read().decode()}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"Network error: {err}") from err


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def load_fields(fields_arg: str) -> list:
    """Accept inline JSON string or path to a .json file."""
    p = Path(fields_arg)
    if p.exists() and p.suffix == ".json":
        return json.loads(p.read_text(encoding="utf-8"))
    return json.loads(fields_arg)


def run_once(args: argparse.Namespace, account_id: str, authorization: str, cookie: str) -> dict:
    base_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": args.origin,
        "Referer": "https://www.mingdao.com/",
        "X-Requested-With": "XMLHttpRequest",
        "Cookie": cookie,
    }
    if account_id:
        base_headers["AccountId"] = account_id
        base_headers["accountid"] = account_id
    if authorization:
        base_headers["Authorization"] = authorization

    fields = load_fields(args.fields)

    # Step 1: add the node skeleton
    add_resp = post_json(
        "https://api.mingdao.com/workflow/flowNode/add",
        {
            "processId": args.process_id,
            "actionId": "1",       # 1 = 新增记录
            "appType": 1,          # 1 = 工作表
            "name": args.name,
            "prveId": args.prev_node_id,
            "typeId": 6,           # 6 = 动作节点
        },
        base_headers,
    )
    print(
        f"[debug] flowNode/add → status={add_resp.get('status')} msg={add_resp.get('msg')}",
        file=sys.stderr,
    )
    if add_resp.get("status") != 1:
        raise RuntimeError(f"flowNode/add failed: {add_resp}")

    added_nodes = add_resp.get("data", {}).get("addFlowNodes", [])
    if not added_nodes:
        raise RuntimeError("flowNode/add returned no addFlowNodes")
    node_id = added_nodes[0]["id"]
    print(f"[debug] new nodeId = {node_id}", file=sys.stderr)

    # Step 2: configure the node (target worksheet + field mappings)
    save_resp = post_json(
        "https://api.mingdao.com/workflow/flowNode/saveNode",
        {
            "processId": args.process_id,
            "nodeId": node_id,
            "flowNodeType": 6,
            "actionId": "1",
            "name": args.name,
            "selectNodeId": "",
            "appId": args.worksheet_id,
            "appType": 1,
            "fields": fields,
            "filters": [],
        },
        base_headers,
    )
    print(
        f"[debug] flowNode/saveNode → status={save_resp.get('status')} msg={save_resp.get('msg')}",
        file=sys.stderr,
    )
    if save_resp.get("status") != 1:
        raise RuntimeError(f"flowNode/saveNode failed: {save_resp}")

    # Step 3: publish (optional)
    publish_result = None
    if args.publish:
        pub_resp = get_json(
            f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={args.process_id}",
            base_headers,
        )
        print(
            f"[debug] process/publish → status={pub_resp.get('status')} "
            f"isPublish={pub_resp.get('data', {}).get('isPublish')} "
            f"msg={pub_resp.get('msg')}",
            file=sys.stderr,
        )
        publish_result = {
            "status": pub_resp.get("status"),
            "is_publish": pub_resp.get("data", {}).get("isPublish"),
            "error_node_ids": pub_resp.get("data", {}).get("errorNodeIds", []),
            "warnings": pub_resp.get("data", {}).get("processWarnings", []),
        }

    return {
        "process_id": args.process_id,
        "node_id": node_id,
        "prev_node_id": args.prev_node_id,
        "worksheet_id": args.worksheet_id,
        "name": args.name,
        "fields_count": len(fields),
        "published": args.publish,
        "publish_result": publish_result,
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{args.process_id}",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    auth_config_path = Path(args.auth_config).expanduser().resolve()

    if args.refresh_auth:
        print("Refreshing auth before run...", file=sys.stderr)
        refresh_auth(headless=args.headless)

    account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
    if not cookie:
        print("Error: missing cookie.", file=sys.stderr)
        return 2

    try:
        result = run_once(args, account_id, authorization, cookie)
    except Exception as exc:
        if not args.refresh_on_fail:
            raise
        print(f"Failed ({exc}), refreshing auth and retrying...", file=sys.stderr)
        refresh_auth(headless=args.headless)
        account_id, authorization, cookie, _ = resolve_auth(args.cookie, auth_config_path)
        if not cookie:
            print("Retry aborted: cookie still missing.", file=sys.stderr)
            return 2
        result = run_once(args, account_id, authorization, cookie)

    result["cookie_source"] = cookie_source
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
