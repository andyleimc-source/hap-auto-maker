#!/usr/bin/env python3
"""
交互式删除工作流脚本。

流程：
1. 拉取指定应用下所有工作流列表（listAll）
2. 展示带序号的列表
3. 输入 Y 全删，输入序号删除对应工作流，任意其他键取消

Reference HAR: action/删除工作流.har
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
        description="交互式列出并删除指定应用下的工作流。"
    )
    parser.add_argument(
        "--relation-id",
        required=True,
        help="App relationId（示例：c2259f27-8b27-4ecb-8def-10fdff5911d9）。",
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
        help="执行前先刷新 auth（调用 scripts/refresh_auth.py）。",
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
    return (
        str(getattr(module, "ACCOUNT_ID", "")).strip(),
        str(getattr(module, "AUTHORIZATION", "")).strip(),
        str(getattr(module, "COOKIE", "")).strip(),
    )


def resolve_auth(cli_cookie: str, auth_config_path: Path) -> tuple[str, str, str]:
    account_id = os.environ.get("MINGDAO_ACCOUNT_ID", "").strip()
    authorization = os.environ.get("MINGDAO_AUTHORIZATION", "").strip()

    if cli_cookie.strip():
        return account_id, authorization, cli_cookie.strip()
    env_cookie = os.environ.get("MINGDAO_COOKIE", "").strip()
    if env_cookie:
        return account_id, authorization, env_cookie

    cfg_account_id, cfg_authorization, cfg_cookie = load_auth_from_auth_config(auth_config_path)
    if cfg_cookie:
        return cfg_account_id, cfg_authorization, cfg_cookie
    return "", "", ""


def refresh_auth(headless: bool) -> None:
    project_root = Path(__file__).resolve().parents[2]
    refresh_script = project_root / "scripts" / "refresh_auth.py"
    if not refresh_script.exists():
        raise RuntimeError(f"Refresh script not found: {refresh_script}")
    cmd = [sys.executable, str(refresh_script)]
    if headless:
        cmd.append("--headless")
    subprocess.run(cmd, check=True)


def fetch_workflows(relation_id: str, session: Session) -> list[dict]:
    """返回扁平化的工作流列表，每项含 id、name、groupName。"""
    resp = session.get(f"https://api.mingdao.com/workflow/v1/process/listAll?relationId={relation_id}")
    if resp.get("status") != 1:
        raise RuntimeError(f"listAll failed: {json.dumps(resp, ensure_ascii=False)}")

    workflows: list[dict] = []
    for group in resp.get("data") or []:
        group_name = group.get("groupName", "")
        for item in group.get("processList") or []:
            workflows.append({
                "id": item.get("id", ""),
                "name": item.get("name", "（未命名）"),
                "groupName": group_name,
                "enabled": item.get("enabled", False),
            })
    return workflows


def delete_workflow(process_id: str, session: Session) -> bool:
    resp = session.post(
        "https://api.mingdao.com/workflow/process/deleteProcess",
        {"processId": process_id},
    )
    return resp.get("status") == 1 and resp.get("data") is True


def print_list(workflows: list[dict]) -> None:
    print(f"\n共找到 {len(workflows)} 个工作流：\n")
    for i, wf in enumerate(workflows, 1):
        status = "启用" if wf["enabled"] else "停用"
        print(f"  [{i:>2}] {wf['name']}  ({status})  id={wf['id']}")
    print()


def main() -> int:
    started_at = time.time()
    args = parse_args()
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    log_args = {k: v for k, v in vars(args).items() if k != "cookie"}

    if args.refresh_auth:
        print("Refreshing auth...")
        refresh_auth(headless=args.headless)

    account_id, authorization, cookie = resolve_auth(args.cookie, auth_config_path)
    if not cookie:
        print("Error: missing cookie. Use --cookie / MINGDAO_COOKIE / valid auth_config.py.", file=sys.stderr)
        persist("delete_workflow", None, args=log_args, error="missing cookie", started_at=started_at)
        return 2

    session = Session(cookie, account_id, authorization, args.origin)

    print("正在拉取工作流列表...")
    workflows = fetch_workflows(args.relation_id, session)

    if not workflows:
        print("该应用下没有工作流。")
        persist("delete_workflow", {"deleted": [], "failed": [], "total": 0},
                args=log_args, started_at=started_at, session=session)
        return 0

    print_list(workflows)
    print("操作说明：输入 / 全部删除 | 输入序号删除对应工作流 | 任意其他键取消")
    choice = input("请输入：").strip()

    if choice == "/":
        deleted, failed = [], []
        for wf in workflows:
            try:
                ok = delete_workflow(wf["id"], session)
                status = "OK" if ok else "FAIL"
            except Exception as exc:
                ok = False
                status = f"ERROR: {exc}"
            print(f"  {'✓' if ok else '✗'} {wf['name']}  [{status}]")
            (deleted if ok else failed).append({"id": wf["id"], "name": wf["name"]})
        print(f"\n完成：成功 {len(deleted)} 个，失败 {len(failed)} 个。")
        output = {"deleted": deleted, "failed": failed, "total": len(deleted) + len(failed)}
        persist("delete_workflow", output, args=log_args, started_at=started_at, session=session)
        return 0 if not failed else 1

    if choice.isdigit():
        idx = int(choice)
        if idx < 1 or idx > len(workflows):
            print(f"序号超出范围（1~{len(workflows)}），已取消。")
            return 0
        wf = workflows[idx - 1]
        ok = delete_workflow(wf["id"], session)
        if ok:
            print(f"已删除：{wf['name']}")
            output = {"deleted": [{"id": wf["id"], "name": wf["name"]}], "failed": [], "total": 1}
            persist("delete_workflow", output, args=log_args, started_at=started_at, session=session)
            return 0
        else:
            print(f"删除失败：{wf['name']}", file=sys.stderr)
            output = {"deleted": [], "failed": [{"id": wf["id"], "name": wf["name"]}], "total": 1}
            persist("delete_workflow", output, args=log_args, started_at=started_at, session=session)
            return 1

    print("已取消。")
    persist("delete_workflow", None, args=log_args, error="cancelled",
            started_at=started_at, session=session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
