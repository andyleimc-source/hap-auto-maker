#!/usr/bin/env python3
"""
通用工作流节点添加脚本（3b3~3i3）

支持的节点类型（通过 --node-type 指定）:
  delete_record    3b3  删除记录节点        (typeId=6, actionId="3", appType=1)
  get_record       3b4  获取单条数据节点    (typeId=6, actionId="4", appType=1)
  get_records      3b5  获取多条数据节点    (typeId=6, actionId="5", appType=1)
  calibrate_record 3b6  校准记录节点        (typeId=6, actionId="6", appType=1)
  branch           3c1  分支网关            (typeId=1)
  subprocess       3c2  子流程              (typeId=16)
  loop             3c3  循环节点            (typeId=29, actionId="210", appType=45)
  abort            3c4  中止流程            (typeId=30, actionId="2")
  approval         3d1  发起审批            (typeId=26, appType=10)
  fill             3d2  填写节点            (typeId=3)
  copy             3d3  抄送节点            (typeId=5)
  notify           3e1  站内通知            (typeId=27)
  sms              3e2  发送短信            (typeId=10)
  email            3e3  发送邮件            (typeId=11, actionId="202", appType=3)
  push             3e4  界面推送            (typeId=17)
  delay_duration   3f1  延时一段时间        (typeId=12, actionId="301")
  delay_until      3f2  延时到指定日期      (typeId=12, actionId="302")
  calc             3g1  数值运算            (typeId=9, actionId="100")
  aggregate        3g2  从工作表汇总        (typeId=9, actionId="107", appType=1)
  json_parse       3h1  JSON 解析           (typeId=21, actionId="510", appType=18)
  code_block       3h2  代码块              (typeId=9, actionId="103")
  api_request      3h3  发送 API 请求       (typeId=8)
  ai_text          3i1  AI 生成文本         (typeId=31, actionId="531", appType=46)
  ai_object        3i2  AI 生成数据对象     (typeId=31, actionId="532", appType=46)
  ai_agent         3i3  AI Agent            (typeId=33, actionId="533", appType=48)

典型用法:
    uv run python3 hap-auto-maker/workflow/scripts/add_workflow_node.py \\
        --process-id <processId> \\
        --prev-node-id <prevNodeId> \\
        --node-type delete_record \\
        --worksheet-id <worksheetId>

    uv run python3 hap-auto-maker/workflow/scripts/add_workflow_node.py \\
        --process-id <processId> \\
        --prev-node-id <prevNodeId> \\
        --node-type notify \\
        --name "发送站内通知"

Reference: api-specs/block1-private/workflow/workflow-node-configs.md
           api-specs/block1-private/workflow/workflow-node-types.md
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


# ---------------------------------------------------------------------------
# Node type definitions
# ---------------------------------------------------------------------------

NODE_CONFIGS = {
    "delete_record":    {"typeId": 6, "actionId": "3", "appType": 1, "name": "删除记录", "needs_worksheet": True},
    "get_record":       {"typeId": 6, "actionId": "4", "appType": 1, "name": "获取单条数据", "needs_worksheet": True},
    "get_records":      {"typeId": 13, "actionId": "400", "name": "查询工作表", "needs_worksheet": False},
    "calibrate_record": {"typeId": 6, "actionId": "6", "appType": 1, "name": "校准单条数据", "needs_worksheet": True},
    "branch":           {"typeId": 1, "name": "分支"},
    "subprocess":       {"typeId": 16, "name": "子流程"},
    "loop":             {"typeId": 29, "actionId": "210", "appType": 45, "name": "满足条件时循环", "needs_relation": True},
    "abort":            {"typeId": 30, "actionId": "2", "name": "中止流程"},
    "approval":         {"typeId": 26, "appType": 10, "name": "未命名审批流程"},
    "fill":             {"typeId": 3, "name": "填写"},
    "copy":             {"typeId": 5, "name": "抄送"},
    "notify":           {"typeId": 27, "name": "发送站内通知"},
    "sms":              {"typeId": 10, "name": "发送短信"},
    "email":            {"typeId": 11, "actionId": "202", "appType": 3, "name": "发送邮件"},
    "push":             {"typeId": 17, "name": "界面推送"},
    "delay_duration":   {"typeId": 12, "actionId": "301", "name": "延时一段时间"},
    "delay_until":      {"typeId": 12, "actionId": "302", "name": "延时到指定日期"},
    "calc":             {"typeId": 9, "actionId": "100", "name": "数值运算"},
    "aggregate":        {"typeId": 9, "actionId": "107", "appType": 1, "name": "从工作表汇总", "needs_worksheet": True},
    "json_parse":       {"typeId": 21, "actionId": "510", "appType": 18, "name": "JSON 解析"},
    "code_block":       {"typeId": 14, "actionId": "102", "name": "代码块"},
    "api_request":      {"typeId": 8, "appType": 7, "name": "发送自定义请求"},
    "ai_text":          {"typeId": 31, "actionId": "531", "appType": 46, "name": "AI 生成文本"},
    "ai_object":        {"typeId": 31, "actionId": "532", "appType": 46, "name": "AI 生成数据对象"},
    "ai_agent":         {"typeId": 33, "actionId": "533", "appType": 48, "name": "AI Agent"},
}


def build_save_node_body(node_type: str, cfg: dict, process_id: str, node_id: str,
                          worksheet_id: str, name: str, extra: dict):
    """Build the saveNode request body for a given node type.
    Returns None if saveNode should be skipped (node is fully configured by add alone).
    """
    type_id = cfg["typeId"]
    action = cfg.get("actionId", "")

    # These node types do not accept saveNode in their initial unconfigured state;
    # the add response already creates the node correctly.
    if type_id in (6, 8, 14, 16, 17):
        return None

    base = {
        "processId": process_id,
        "flowNodeType": type_id,
        "name": name,
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
        "nodeId": node_id,
    }

    # typeId=12 (timer) must NOT have actionId at top level — it belongs inside timerNode only
    if "actionId" in cfg and type_id != 12:
        base["actionId"] = cfg["actionId"]
    if "appType" in cfg:
        base["appType"] = cfg["appType"]

    # typeId-specific fields
    if type_id == 6:
        # 记录操作节点
        if worksheet_id:
            base["appId"] = worksheet_id
        if action == "1":
            base["fields"] = []
        elif action == "2":
            base["fields"] = []
            base["filters"] = []
        elif action == "3":
            base["filters"] = []
        elif action in ("4", "5"):
            base["filters"] = []
            base["sorts"] = []
            if action == "5":
                base["number"] = 50
        elif action == "6":
            base["fields"] = []
            base["errorFields"] = []

    elif type_id == 1:
        # 分支网关
        base["gatewayType"] = extra.get("gatewayType", 1)
        base["flowIds"] = []
        base.pop("isException", None)

    elif type_id == 2:
        # 分支条件
        base["operateCondition"] = []
        base["flowIds"] = []

    elif type_id in (3, 5):
        # 填写 / 抄送
        base["accounts"] = []
        base["flowIds"] = []
        if type_id == 3:
            base["formProperties"] = []

    elif type_id == 9:
        # 运算节点
        action = cfg.get("actionId", "")
        if action == "100":
            base["formulaMap"] = {}
            base["formulaValue"] = ""
            base["fieldValue"] = ""
        elif action == "107":
            if worksheet_id:
                base["appId"] = worksheet_id
            base["formulaValue"] = ""
            base["fieldValue"] = ""
        # others: minimal body

    elif type_id == 10:
        # 短信
        base["accounts"] = []
        base["content"] = ""

    elif type_id == 11:
        # 邮件
        base["accounts"] = []
        base["title"] = ""
        base["content"] = ""

    elif type_id == 12:
        # 延时节点 — timerNode 结构
        action = cfg.get("actionId", "301")
        empty_field = {
            "fieldValue": "", "fieldNodeId": "", "fieldNodeType": None,
            "fieldNodeName": None, "fieldAppType": None, "fieldActionId": None,
            "fieldControlId": "", "fieldControlName": None, "fieldControlType": None,
            "sourceType": None,
        }
        if action == "301":
            base["timerNode"] = {
                "desc": "",
                "actionId": "301",
                "numberFieldValue": dict(empty_field),
                "hourFieldValue": dict(empty_field),
                "minuteFieldValue": dict(empty_field),
                "secondFieldValue": dict(empty_field),
            }
        else:
            base["timerNode"] = {
                "desc": "",
                "actionId": action,
                "executeTimeType": 0,
                "number": 0,
                "unit": 1,
                "time": "08:00",
            }

    elif type_id == 16:
        # 子流程
        base.pop("isException", None)

    elif type_id == 17:
        # 界面推送
        base["accounts"] = []
        base["content"] = ""

    elif type_id == 21:
        # JSON 解析
        base["jsonContent"] = ""
        base["controls"] = []

    elif type_id == 26:
        # 发起审批
        base["accounts"] = []
        base["formProperties"] = []
        base["flowIds"] = []

    elif type_id == 27:
        # 站内通知
        base["accounts"] = []
        base["content"] = ""

    elif type_id == 29:
        # 循环
        base["flowIds"] = []
        base["subProcessId"] = ""
        base["subProcessName"] = "循环"

    elif type_id == 30:
        # 中止流程
        base.pop("isException", None)

    elif type_id == 31:
        # AI 生成文本 / AI 生成数据对象
        # ai_text (531): needs appId=""
        # ai_object (532): minimal body — only actionId is accepted by server
        base.pop("isException", None)
        if action == "531":
            base["appId"] = ""

    elif type_id == 33:
        # AI Agent
        base.pop("isException", None)
        base["appId"] = ""
        base["tools"] = []

    base.update(extra.get("extra_fields", {}))
    return base


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    default_auth_config = project_root / "config" / "credentials" / "auth_config.py"
    parser = argparse.ArgumentParser(
        description="向已有工作流添加节点（通用脚本，涵盖 3b3~3i3 所有节点类型）。"
    )
    parser.add_argument("--process-id", required=True, help="工作流进程 ID。")
    parser.add_argument("--prev-node-id", required=True, help="上游节点 ID（新节点插在其后）。")
    parser.add_argument("--node-type", required=True, choices=list(NODE_CONFIGS.keys()),
                        help="节点类型标识，见脚本文档。")
    parser.add_argument("--name", default="", help="节点显示名称（留空则使用默认名）。")
    parser.add_argument("--worksheet-id", default="", help="目标工作表 ID（部分节点类型必填）。")
    parser.add_argument("--relation-id", default="", help="应用 ID（部分节点类型如 loop 必填）。")
    parser.add_argument("--gateway-type", type=int, default=1,
                        help="分支类型：1=互斥, 2=并行（仅 branch 节点有效，默认 1）。")
    parser.add_argument("--extra", default="{}",
                        help="额外字段 JSON（追加到 saveNode body），如 '{\"number\": 100}'。")
    parser.add_argument("--publish", action="store_true", help="添加节点后发布工作流。")
    parser.add_argument("--cookie", default="", help="Cookie header 值（留空则自动加载）。")
    parser.add_argument("--auth-config", default=str(default_auth_config), help="auth_config.py 路径。")
    parser.add_argument("--refresh-auth", action="store_true", help="运行前先刷新 auth。")
    parser.add_argument("--refresh-on-fail", action="store_true", help="失败时刷新 auth 后重试。")
    parser.add_argument("--headless", action="store_true", help="刷新 auth 时使用 headless 模式。")
    parser.add_argument("--origin", default="https://www.mingdao.com", help="请求 Origin header。")
    return parser.parse_args()


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


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def run_once(args: argparse.Namespace, session: Session) -> dict:
    cfg = NODE_CONFIGS[args.node_type]
    name = args.name or cfg["name"]

    # Validate worksheet requirement
    if cfg.get("needs_worksheet") and not args.worksheet_id:
        raise ValueError(f"节点类型 '{args.node_type}' 需要 --worksheet-id 参数")

    # Build flowNode/add payload
    add_payload: dict = {
        "processId": args.process_id,
        "prveId": args.prev_node_id,
        "name": name,
        "typeId": cfg["typeId"],
    }
    if "actionId" in cfg:
        add_payload["actionId"] = cfg["actionId"]
    if "appType" in cfg:
        add_payload["appType"] = cfg["appType"]
    if args.worksheet_id and cfg.get("needs_worksheet"):
        add_payload["appId"] = args.worksheet_id
    if cfg.get("needs_relation") and hasattr(args, "relation_id") and args.relation_id:
        add_payload["relationId"] = args.relation_id

    # Step 1: add node skeleton
    add_resp = session.post("https://api.mingdao.com/workflow/flowNode/add", add_payload)
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

    # Step 2: configure node
    try:
        extra = json.loads(args.extra)
    except (json.JSONDecodeError, AttributeError):
        extra = {}
    extra["gatewayType"] = args.gateway_type

    save_body = build_save_node_body(
        args.node_type, cfg, args.process_id, node_id,
        args.worksheet_id, name, extra,
    )

    if save_body is None:
        print("[debug] flowNode/saveNode → skipped (node configured by add)", file=sys.stderr)
    else:
        save_resp = session.post("https://api.mingdao.com/workflow/flowNode/saveNode", save_body)
        print(
            f"[debug] flowNode/saveNode → status={save_resp.get('status')} msg={save_resp.get('msg')}",
            file=sys.stderr,
        )
        if save_resp.get("status") != 1:
            raise RuntimeError(f"flowNode/saveNode failed: {save_resp}")

    # Step 3: publish (optional)
    publish_result = None
    if args.publish:
        pub_resp = session.get(
            f"https://api.mingdao.com/workflow/process/publish?isPublish=true&processId={args.process_id}",
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
        "node_type": args.node_type,
        "type_id": cfg["typeId"],
        "action_id": cfg.get("actionId"),
        "app_type": cfg.get("appType"),
        "prev_node_id": args.prev_node_id,
        "worksheet_id": args.worksheet_id or None,
        "name": name,
        "published": args.publish,
        "publish_result": publish_result,
        "workflow_edit_url": f"https://www.mingdao.com/workflowedit/{args.process_id}",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    started_at = time.time()
    args = parse_args()
    auth_config_path = Path(args.auth_config).expanduser().resolve()
    log_args = {k: v for k, v in vars(args).items() if k != "cookie"}

    if args.refresh_auth:
        print("Refreshing auth before run...", file=sys.stderr)
        refresh_auth(headless=args.headless)

    account_id, authorization, cookie, cookie_source = resolve_auth(args.cookie, auth_config_path)
    if not cookie:
        print("Error: missing cookie.", file=sys.stderr)
        persist("add_workflow_node", None, args=log_args,
                error="missing cookie", started_at=started_at)
        return 2

    session = Session(cookie, account_id, authorization, args.origin)

    try:
        result = run_once(args, session)
    except Exception as exc:
        if not args.refresh_on_fail:
            persist("add_workflow_node", None, args=log_args,
                    error=str(exc), started_at=started_at, session=session)
            raise
        print(f"Failed ({exc}), refreshing auth and retrying...", file=sys.stderr)
        refresh_auth(headless=args.headless)
        account_id, authorization, cookie, _ = resolve_auth(args.cookie, auth_config_path)
        if not cookie:
            print("Retry aborted: cookie still missing.", file=sys.stderr)
            persist("add_workflow_node", None, args=log_args,
                    error="cookie missing after refresh", started_at=started_at, session=session)
            return 2
        session = Session(cookie, account_id, authorization, args.origin)
        result = run_once(args, session)

    result["cookie_source"] = cookie_source
    print(json.dumps(result, ensure_ascii=False, indent=2))
    persist("add_workflow_node", result, args=log_args,
            started_at=started_at, session=session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
