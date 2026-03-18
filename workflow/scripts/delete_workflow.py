#!/usr/bin/env python3
"""
交互式删除工作流 & 自定义动作脚本。

流程：
1. 同时拉取指定应用下的工作流列表和自定义动作列表（自动遍历所有工作表）
2. 分两组展示，序号全局连续
3. 输入「删除全部」全删，输入序号（支持 1,2,5 多选）删除指定条目，任意其他键取消

可通过 --type 只操作某一类：workflow / action / all（默认）
可通过 --worksheet-id 只查询指定工作表的自定义动作（不影响工作流列表）

Reference HAR: action/删除工作流.har, action/删除自定义动作.har
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

import requests as _requests

from workflow_io import Session, persist


# ── 常量 ───────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_APP_AUTH_DIR = _PROJECT_ROOT / "data" / "outputs" / "app_authorizations"


# ── 参数解析 ───────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    default_auth_config = _PROJECT_ROOT / "config" / "credentials" / "auth_config.py"
    parser = argparse.ArgumentParser(
        description="交互式列出并删除应用下的工作流和自定义动作。"
    )
    parser.add_argument(
        "--app-id",
        required=True,
        help="应用 ID（示例：c2259f27-8b27-4ecb-8def-10fdff5911d9）。",
    )
    parser.add_argument(
        "--type",
        default="all",
        choices=["all", "workflow", "action"],
        help="操作范围：all（默认）| workflow（仅工作流）| action（仅自定义动作）。",
    )
    parser.add_argument(
        "--worksheet-id",
        default="",
        help="只查询指定工作表的自定义动作。留空则遍历全部工作表。",
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
        help="执行前先刷新 auth（调用 scripts/auth/refresh_auth.py）。",
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


# ── 认证解析 ───────────────────────────────────────────────────────────────────

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
    refresh_script = _PROJECT_ROOT / "scripts" / "refresh_auth.py"
    if not refresh_script.exists():
        raise RuntimeError(f"Refresh script not found: {refresh_script}")
    cmd = [sys.executable, str(refresh_script)]
    if headless:
        cmd.append("--headless")
    subprocess.run(cmd, check=True)


# ── 工作流 API ────────────────────────────────────────────────────────────────

def fetch_workflows(app_id: str, session: Session) -> list[dict]:
    """返回扁平化的工作流列表，每项含 id、name、enabled。"""
    resp = session.get(f"https://api.mingdao.com/workflow/v1/process/listAll?relationId={app_id}")
    if resp.get("status") != 1:
        raise RuntimeError(f"listAll failed: {json.dumps(resp, ensure_ascii=False)}")
    result = []
    for group in resp.get("data") or []:
        for item in group.get("processList") or []:
            result.append({
                "id":      item.get("id", ""),
                "name":    item.get("name", "（未命名）"),
                "enabled": item.get("enabled", False),
            })
    return result


def delete_workflow(process_id: str, session: Session) -> bool:
    resp = session.post(
        "https://api.mingdao.com/workflow/process/deleteProcess",
        {"processId": process_id},
    )
    return resp.get("status") == 1 and resp.get("data") is True


# ── 自定义动作 API ────────────────────────────────────────────────────────────

def _load_app_key_sign(app_id: str) -> tuple[str, str]:
    auth_file = _APP_AUTH_DIR / f"app_authorize_{app_id}.json"
    if not auth_file.exists():
        raise FileNotFoundError(
            f"找不到应用授权文件：{auth_file}\n"
            "请先运行 create_workflow_worksheet_trigger.py，或手动指定 --worksheet-id。"
        )
    data = json.loads(auth_file.read_text(encoding="utf-8"))
    entry = data["data"][0] if isinstance(data.get("data"), list) else data
    return str(entry["appKey"]), str(entry["sign"])


def _walk_sections(sections: list, worksheets: list) -> None:
    for sec in sections or []:
        for item in sec.get("items") or []:
            if item.get("type") == 0:
                worksheets.append({"id": str(item.get("id", "")), "name": str(item.get("name", ""))})
        _walk_sections(sec.get("childSections") or [], worksheets)


def fetch_all_worksheets(app_id: str) -> list[dict]:
    app_key, sign = _load_app_key_sign(app_id)
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json"}
    resp = _requests.get("https://api.mingdao.com/v3/app", headers=headers, timeout=30)
    resp.raise_for_status()
    app_data = resp.json()
    if not app_data.get("success"):
        raise RuntimeError(f"获取应用信息失败：{app_data.get('error_msg', app_data)}")
    worksheets: list[dict] = []
    _walk_sections(app_data.get("data", {}).get("sections") or [], worksheets)
    return worksheets


def fetch_custom_actions(worksheet_id: str, session: Session) -> list[dict]:
    resp = session.post(
        "https://www.mingdao.com/api/Worksheet/GetWorksheetBtns",
        {"worksheetId": worksheet_id},
    )
    if resp.get("state") != 1:
        raise RuntimeError(f"GetWorksheetBtns failed: {json.dumps(resp, ensure_ascii=False)}")
    return resp.get("data") or []


def delete_custom_action(btn_id: str, worksheet_id: str, app_id: str, session: Session) -> bool:
    resp = session.post(
        "https://www.mingdao.com/api/Worksheet/OptionWorksheetBtn",
        {"appId": app_id, "viewId": "", "btnId": btn_id, "worksheetId": worksheet_id, "optionType": 9},
    )
    return resp.get("state") == 1 and resp.get("data") is True


# ── 展示 ──────────────────────────────────────────────────────────────────────

def print_items(flat: list[dict]) -> None:
    """flat 每项：{seq, kind, name, id, enabled?, worksheetId?, worksheetName?}"""
    # 工作流区块
    wf_items = [x for x in flat if x["kind"] == "workflow"]
    ac_items = [x for x in flat if x["kind"] == "action"]

    if wf_items:
        print(f"\n── 工作流（{len(wf_items)} 个）{'─' * 40}")
        for item in wf_items:
            status = "启用" if item.get("enabled") else "停用"
            print(f"  [{item['seq']:>3}] {item['name']}  ({status})  id={item['id']}")

    if ac_items:
        print(f"\n── 自定义动作（{len(ac_items)} 个）{'─' * 38}")
        current_ws = None
        for item in ac_items:
            if item.get("worksheetName") != current_ws:
                current_ws = item.get("worksheetName")
                print(f"  【{current_ws}】")
            print(f"    [{item['seq']:>3}] {item['name']}  id={item['id']}")

    print()


# ── 多选解析 ──────────────────────────────────────────────────────────────────

def parse_selection(choice: str, total: int) -> list[int] | None:
    indices = []
    for part in choice.split(","):
        part = part.strip()
        if not part.isdigit():
            return None
        idx = int(part)
        if idx < 1 or idx > total:
            print(f"序号 {idx} 超出范围（1~{total}），已取消。")
            return None
        indices.append(idx - 1)
    return indices


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

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
    flat: list[dict] = []

    # ── 工作流 ────────────────────────────────────────────────────────────────
    if args.type in ("all", "workflow"):
        print("正在拉取工作流列表...")
        try:
            workflows = fetch_workflows(args.app_id, session)
            for wf in workflows:
                flat.append({
                    "seq":     len(flat) + 1,
                    "kind":    "workflow",
                    "id":      wf["id"],
                    "name":    wf["name"],
                    "enabled": wf["enabled"],
                })
            print(f"  → {len(workflows)} 个工作流")
        except Exception as exc:
            print(f"  ⚠ 拉取工作流失败：{exc}", file=sys.stderr)

    # ── 自定义动作 ────────────────────────────────────────────────────────────
    if args.type in ("all", "action"):
        if args.worksheet_id:
            worksheets = [{"id": args.worksheet_id, "name": args.worksheet_id}]
        else:
            print("正在拉取工作表列表...")
            worksheets = fetch_all_worksheets(args.app_id)
            print(f"  → {len(worksheets)} 个工作表，正在拉取自定义动作...")

        action_count = 0
        for ws in worksheets:
            try:
                btns = fetch_custom_actions(ws["id"], session)
            except Exception as exc:
                print(f"  ⚠ 拉取 {ws['name']} 失败：{exc}", file=sys.stderr)
                btns = []
            for btn in btns:
                flat.append({
                    "seq":           len(flat) + 1,
                    "kind":          "action",
                    "id":            btn.get("btnId", ""),
                    "name":          btn.get("name", "（未命名）"),
                    "worksheetId":   ws["id"],
                    "worksheetName": ws["name"],
                })
                action_count += 1
        print(f"  → {action_count} 个自定义动作")

    if not flat:
        print("\n未找到任何条目。")
        persist("delete_workflow", {"deleted": [], "failed": [], "total": 0},
                args=log_args, started_at=started_at, session=session)
        return 0

    print(f"\n共 {len(flat)} 项：")
    print_items(flat)
    print("操作说明：输入「删除全部」全部删除 | 输入序号（支持 1,2,5 多选）删除指定条目 | 任意其他键取消")
    choice = input("请输入：").strip()

    if choice == "删除全部":
        targets = flat
    elif any(c.isdigit() for c in choice):
        indices = parse_selection(choice, len(flat))
        if indices is None:
            print("已取消。")
            persist("delete_workflow", None, args=log_args, error="cancelled",
                    started_at=started_at, session=session)
            return 0
        targets = [flat[i] for i in indices]
    else:
        print("已取消。")
        persist("delete_workflow", None, args=log_args, error="cancelled",
                started_at=started_at, session=session)
        return 0

    deleted, failed = [], []
    for item in targets:
        try:
            if item["kind"] == "workflow":
                ok = delete_workflow(item["id"], session)
            else:
                ok = delete_custom_action(item["id"], item["worksheetId"], args.app_id, session)
            status = "OK" if ok else "FAIL"
        except Exception as exc:
            ok = False
            status = f"ERROR: {exc}"

        kind_label = "工作流" if item["kind"] == "workflow" else f"动作/{item.get('worksheetName', '')}"
        print(f"  {'✓' if ok else '✗'} [{kind_label}] {item['name']}  [{status}]")
        entry = {"id": item["id"], "name": item["name"], "kind": item["kind"]}
        (deleted if ok else failed).append(entry)

    print(f"\n完成：成功 {len(deleted)} 个，失败 {len(failed)} 个。")
    output = {"deleted": deleted, "failed": failed, "total": len(deleted) + len(failed)}
    persist("delete_workflow", output, args=log_args, started_at=started_at, session=session)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
