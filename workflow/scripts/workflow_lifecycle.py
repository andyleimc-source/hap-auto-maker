#!/usr/bin/env python3
"""
工作流生命周期管理：获取详情、列出、启用、禁用。

覆盖蓝图条目：
  3j1  获取工作流详情   GET  /workflow/process/getProcessPublish
  3j2  列出工作流       GET  /workflow/v1/process/listAll
  3j3  启用工作流       POST /workflow/process/publish
  3j4  禁用工作流       POST /workflow/process/unPublish

用法示例：
  # 列出应用下所有工作流
  uv run python3 workflow_lifecycle.py --action list --app-id <appId>

  # 获取某工作流详情
  uv run python3 workflow_lifecycle.py --action get --process-id <processId>

  # 启用工作流
  uv run python3 workflow_lifecycle.py --action publish --process-id <processId>

  # 禁用工作流
  uv run python3 workflow_lifecycle.py --action unpublish --process-id <processId>
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


# ── 常量 ───────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_API2_BASE = "https://api2.mingdao.com"
_API_BASE = "https://api.mingdao.com"


# ── 参数解析 ───────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    default_auth_config = _PROJECT_ROOT / "config" / "credentials" / "auth_config.py"
    parser = argparse.ArgumentParser(
        description="工作流生命周期管理：列出、获取详情、启用、禁用。"
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["list", "get", "publish", "unpublish"],
        help=(
            "操作类型：\n"
            "  list       列出应用下所有工作流（需要 --app-id）\n"
            "  get        获取工作流详情（需要 --process-id）\n"
            "  publish    启用工作流（需要 --process-id）\n"
            "  unpublish  禁用工作流（需要 --process-id）"
        ),
    )
    parser.add_argument(
        "--app-id",
        default="",
        help="应用 ID（list 操作必填）。",
    )
    parser.add_argument(
        "--process-id",
        default="",
        help="工作流 ID（get/publish/unpublish 操作必填）。",
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


# ── 认证 ───────────────────────────────────────────────────────────────────────

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
    refresh_script = _PROJECT_ROOT / "scripts" / "auth" / "refresh_auth.py"
    if not refresh_script.exists():
        raise RuntimeError(f"Refresh script not found: {refresh_script}")
    cmd = [sys.executable, str(refresh_script)]
    if headless:
        cmd.append("--headless")
    subprocess.run(cmd, check=True)


# ── API 函数 ───────────────────────────────────────────────────────────────────

def list_workflows(app_id: str, session: Session) -> list[dict]:
    """3j2: 列出应用下所有工作流（扁平化）。"""
    resp = session.get(f"{_API_BASE}/workflow/v1/process/listAll?relationId={app_id}")
    if resp.get("status") != 1:
        raise RuntimeError(f"listAll 失败: {json.dumps(resp, ensure_ascii=False)}")
    result = []
    for group in resp.get("data") or []:
        for item in group.get("processList") or []:
            result.append({
                "id":               item.get("id", ""),
                "name":             item.get("name", "（未命名）"),
                "enabled":          item.get("enabled", False),
                "publishStatus":    item.get("publishStatus", 0),
                "startEventAppType": item.get("startEventAppType", 0),
                "groupName":        group.get("groupName", ""),
            })
    return result


def get_workflow_detail(process_id: str, session: Session) -> dict:
    """3j1: 获取工作流详情（含 startNodeId）。"""
    resp = session.get(f"{_API2_BASE}/workflow/process/getProcessPublish?processId={process_id}")
    if resp.get("status") != 1:
        raise RuntimeError(f"getProcessPublish 失败: {json.dumps(resp, ensure_ascii=False)}")
    return resp.get("data") or {}


def publish_workflow(process_id: str, session: Session) -> bool:
    """3j3: 启用工作流（发布）。

    GET /workflow/process/publish?isPublish=true&processId=xxx
    响应 data.isPublish == true 表示启用成功。
    工作流必须已配置触发节点才能发布，否则 isPublish 仍为 false。
    """
    resp = session.get(
        f"{_API_BASE}/workflow/process/publish?isPublish=true&processId={process_id}",
    )
    if resp.get("status") != 1:
        raise RuntimeError(f"publish 失败: {json.dumps(resp, ensure_ascii=False)}")
    data = resp.get("data") or {}
    is_publish = data.get("isPublish", False)
    if not is_publish:
        error_nodes = data.get("errorNodeIds", [])
        warnings = [w.get("warningType") for w in data.get("processWarnings") or []]
        raise RuntimeError(
            f"工作流发布失败（未通过校验）。errorNodeIds={error_nodes} warnings={warnings}\n"
            "请先确保工作流已配置触发节点。"
        )
    return True


def unpublish_workflow(process_id: str, session: Session) -> bool:
    """3j4: 禁用工作流（取消发布）。

    GET /workflow/process/publish?isPublish=false&processId=xxx
    """
    resp = session.get(
        f"{_API_BASE}/workflow/process/publish?isPublish=false&processId={process_id}",
    )
    if resp.get("status") != 1:
        raise RuntimeError(f"unPublish 失败: {json.dumps(resp, ensure_ascii=False)}")
    return True


# ── 展示 ──────────────────────────────────────────────────────────────────────

_PUBLISH_STATUS = {0: "未发布", 1: "已发布"}
_APP_TYPE = {
    1: "工作表事件",
    5: "循环定时",
    6: "按日期字段",
    7: "Webhook",
    11: "组织人员事件",
    14: "自定义按钮",
}


def print_workflows(workflows: list[dict]) -> None:
    if not workflows:
        print("  （无工作流）")
        return
    for i, wf in enumerate(workflows, 1):
        enabled_label = "启用" if wf.get("enabled") else "停用"
        publish_label = _PUBLISH_STATUS.get(wf.get("publishStatus", 0), "?")
        type_label = _APP_TYPE.get(wf.get("startEventAppType", 0), f"类型{wf.get('startEventAppType')}")
        print(
            f"  [{i:>3}] {wf['name']}  [{enabled_label}/{publish_label}]  "
            f"触发:{type_label}  id={wf['id']}"
        )


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

def main() -> int:
    started_at = time.time()
    args = parse_args()
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    log_args = {k: v for k, v in vars(args).items() if k != "cookie"}

    # 参数校验
    if args.action == "list" and not args.app_id:
        print("Error: --app-id 是 list 操作的必填参数。", file=sys.stderr)
        return 2
    if args.action in ("get", "publish", "unpublish") and not args.process_id:
        print(f"Error: --process-id 是 {args.action} 操作的必填参数。", file=sys.stderr)
        return 2

    if args.refresh_auth:
        print("Refreshing auth...")
        refresh_auth(headless=args.headless)

    account_id, authorization, cookie = resolve_auth(args.cookie, auth_config_path)
    if not cookie:
        print("Error: missing cookie. Use --cookie / MINGDAO_COOKIE / valid auth_config.py.", file=sys.stderr)
        persist("workflow_lifecycle", None, args=log_args, error="missing cookie", started_at=started_at)
        return 2

    session = Session(cookie, account_id, authorization, args.origin)

    # ── list ──────────────────────────────────────────────────────────────────
    if args.action == "list":
        print(f"正在列出应用 {args.app_id} 下的工作流...")
        workflows = list_workflows(args.app_id, session)
        print(f"共 {len(workflows)} 个工作流：")
        print_workflows(workflows)
        output = {"workflows": workflows, "total": len(workflows)}
        persist("workflow_lifecycle", output, args=log_args, started_at=started_at, session=session)
        return 0

    # ── get ───────────────────────────────────────────────────────────────────
    if args.action == "get":
        print(f"正在获取工作流 {args.process_id} 的详情...")
        detail = get_workflow_detail(args.process_id, session)
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        persist("workflow_lifecycle", detail, args=log_args, started_at=started_at, session=session)
        return 0

    # ── publish ───────────────────────────────────────────────────────────────
    if args.action == "publish":
        print(f"正在启用工作流 {args.process_id}...")
        ok = publish_workflow(args.process_id, session)
        status = "✓ 启用成功" if ok else "✗ 启用失败（接口返回非 true）"
        print(status)
        persist("workflow_lifecycle", {"processId": args.process_id, "action": "publish", "ok": ok},
                args=log_args, started_at=started_at, session=session)
        return 0 if ok else 1

    # ── unpublish ─────────────────────────────────────────────────────────────
    if args.action == "unpublish":
        print(f"正在禁用工作流 {args.process_id}...")
        ok = unpublish_workflow(args.process_id, session)
        status = "✓ 禁用成功" if ok else "✗ 禁用失败（接口返回非 true）"
        print(status)
        persist("workflow_lifecycle", {"processId": args.process_id, "action": "unpublish", "ok": ok},
                args=log_args, started_at=started_at, session=session)
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
