#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据 workflow_plan_v1 生成工作流私有接口请求，支持 dry-run，保留适配器骨架。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from workflow_common import (
    ENABLE_PROCESS_URL,
    PRIVATE_WORKFLOW_API_JSON,
    PRIVATE_WORKFLOW_API_MD,
    PUBLISH_PROCESS_URL,
    START_PROCESS_URL,
    WORKFLOW_CREATE_DIR,
    append_log,
    ensure_state_success,
    ensure_workflow_dirs,
    load_json,
    load_private_workflow_api_doc,
    make_workflow_log_path,
    make_workflow_output_path,
    now_iso,
    post_private_json,
    resolve_workflow_plan_json,
    write_json_with_latest,
)


def build_trigger_payload(trigger: dict) -> dict:
    payload = {
        "type": str(trigger.get("type", "")).strip(),
        "worksheetId": str(trigger.get("worksheetId", "")).strip(),
        "worksheetName": str(trigger.get("worksheetName", "")).strip(),
        "event": str(trigger.get("event", "")).strip(),
        "triggerFieldIds": [
            str(item).strip()
            for item in trigger.get("triggerFieldIds", []) or []
            if str(item).strip()
        ],
        "conditions": trigger.get("conditions", []) or [],
    }
    if isinstance(trigger.get("schedule"), dict):
        payload["schedule"] = dict(trigger["schedule"])
    return payload


def build_node_payloads(nodes: List[dict]) -> List[dict]:
    payloads: List[dict] = []
    for index, node in enumerate(nodes, start=1):
        payloads.append(
            {
                "sort": index,
                "nodeType": str(node.get("nodeType", "")).strip(),
                "name": str(node.get("name", "")).strip(),
                "config": node.get("config", {}) if isinstance(node.get("config"), dict) else {},
            }
        )
    return payloads


def build_draft_payload(app: dict, workflow: dict) -> dict:
    return {
        "schemaVersion": "workflow_private_request_draft_v1",
        "appId": str(app.get("appId", "")).strip(),
        "appName": str(app.get("appName", "")).strip(),
        "name": str(workflow.get("name", "")).strip(),
        "summary": str(workflow.get("summary", "")).strip(),
        "key": str(workflow.get("key", "")).strip(),
        "trigger": build_trigger_payload(workflow.get("trigger", {}) if isinstance(workflow.get("trigger"), dict) else {}),
        "nodes": build_node_payloads(workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []),
        "publish": bool(workflow.get("publish", True)),
        "enable": bool(workflow.get("enable", True)),
    }


def build_publish_payload(process_id: str, workflow: dict) -> dict:
    return {
        "processId": process_id,
        "publish": bool(workflow.get("publish", True)),
        "key": str(workflow.get("key", "")).strip(),
    }


def build_enable_payload(process_id: str, workflow: dict) -> dict:
    return {
        "processId": process_id,
        "status": 1 if bool(workflow.get("enable", True)) else 0,
        "key": str(workflow.get("key", "")).strip(),
    }


def get_referer(app_id: str, worksheet_id: str = "") -> str:
    if worksheet_id:
        return f"https://www.mingdao.com/app/{app_id}/{worksheet_id}"
    return f"https://www.mingdao.com/app/{app_id}"


class WorkflowPrivateApiAdapter:
    def __init__(self, config: dict | None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.save_url = str(self.config.get("saveFlowUrl", "")).strip() or START_PROCESS_URL
        self.publish_url = str(self.config.get("publishUrl", "")).strip() or PUBLISH_PROCESS_URL
        self.enable_url = str(self.config.get("enableUrl", "")).strip() or ENABLE_PROCESS_URL

    def ensure_available(self) -> None:
        if self.enabled:
            return
        hint = PRIVATE_WORKFLOW_API_JSON if PRIVATE_WORKFLOW_API_JSON.exists() else PRIVATE_WORKFLOW_API_MD
        raise RuntimeError(
            "当前未配置可执行的工作流私有接口适配器。"
            f"请补充 {hint}，至少提供 enabled=true 及接口 URL，再执行非 dry-run 创建。"
        )

    def create_workflow(self, app: dict, workflow: dict) -> Tuple[List[dict], List[dict], Dict[str, str]]:
        self.ensure_available()
        app_id = str(app.get("appId", "")).strip()
        trigger = workflow.get("trigger", {}) if isinstance(workflow.get("trigger"), dict) else {}
        referer = get_referer(app_id, str(trigger.get("worksheetId", "")).strip())

        draft_payload = build_draft_payload(app, workflow)
        save_resp = post_private_json(self.save_url, draft_payload, referer=referer)
        ensure_state_success(save_resp, "SaveFlow")
        save_data = save_resp.get("data", {}) if isinstance(save_resp.get("data"), dict) else {}
        process_id = str(save_data.get("processId", "") or save_resp.get("processId", "")).strip()
        version_id = str(save_data.get("versionId", "") or save_resp.get("versionId", "")).strip()
        if not process_id:
            raise RuntimeError(f"SaveFlow 未返回 processId: {save_resp}")

        requests_payload = [{"name": "saveFlow", "url": self.save_url, "payload": draft_payload}]
        responses_payload = [{"name": "saveFlow", "response": save_resp}]

        if bool(workflow.get("publish", True)):
            publish_payload = build_publish_payload(process_id, workflow)
            publish_resp = post_private_json(self.publish_url, publish_payload, referer=referer)
            ensure_state_success(publish_resp, "PublishFlow")
            requests_payload.append({"name": "publish", "url": self.publish_url, "payload": publish_payload})
            responses_payload.append({"name": "publish", "response": publish_resp})

        if bool(workflow.get("enable", True)):
            enable_payload = build_enable_payload(process_id, workflow)
            enable_resp = post_private_json(self.enable_url, enable_payload, referer=referer)
            ensure_state_success(enable_resp, "EnableFlow")
            requests_payload.append({"name": "enable", "url": self.enable_url, "payload": enable_payload})
            responses_payload.append({"name": "enable", "response": enable_resp})

        return requests_payload, responses_payload, {"processId": process_id, "versionId": version_id}


def main() -> None:
    parser = argparse.ArgumentParser(description="根据 workflow_plan_v1 生成或创建工作流")
    parser.add_argument("--plan-json", default="", help="workflow_plan_v1 JSON 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅生成请求草稿，不实际调用私有接口")
    parser.add_argument("--output", default="", help="输出结果 JSON 路径")
    args = parser.parse_args()

    ensure_workflow_dirs()
    plan_path = resolve_workflow_plan_json(args.plan_json)
    plan = load_json(plan_path)
    app = plan.get("app", {}) if isinstance(plan, dict) else {}
    app_id = str(app.get("appId", "")).strip()
    app_name = str(app.get("appName", "")).strip()

    log_path = make_workflow_log_path("workflow_create", app_id)
    append_log(log_path, "start", planJson=str(plan_path), appId=app_id, appName=app_name, dryRun=bool(args.dry_run))

    private_api_config, private_api_path = load_private_workflow_api_doc()
    adapter = WorkflowPrivateApiAdapter(private_api_config)
    results: List[dict] = []
    ok_count = 0
    fail_count = 0

    for index, workflow in enumerate(plan.get("workflows", []) or [], start=1):
        workflow_key = str(workflow.get("key", "")).strip()
        workflow_name = str(workflow.get("name", "")).strip()
        append_log(log_path, "workflow_start", index=index, workflowKey=workflow_key, workflowName=workflow_name)
        item_result: Dict[str, Any] = {
            "index": index,
            "workflowKey": workflow_key,
            "workflowName": workflow_name,
            "ok": False,
            "remoteIds": {"processId": "", "versionId": ""},
            "requests": [],
            "responses": [],
            "error": "",
        }
        try:
            draft_payload = build_draft_payload(app, workflow)
            if args.dry_run:
                dry_run_requests = [{"name": "saveFlow", "url": adapter.save_url, "payload": draft_payload}]
                if bool(workflow.get("publish", True)):
                    dry_run_requests.append(
                        {"name": "publish", "url": adapter.publish_url, "payload": build_publish_payload("DRY_RUN_PROCESS_ID", workflow)}
                    )
                if bool(workflow.get("enable", True)):
                    dry_run_requests.append(
                        {"name": "enable", "url": adapter.enable_url, "payload": build_enable_payload("DRY_RUN_PROCESS_ID", workflow)}
                    )
                item_result["ok"] = True
                item_result["requests"] = dry_run_requests
                item_result["responses"] = []
                ok_count += 1
                append_log(log_path, "workflow_finished", index=index, workflowKey=workflow_key, dryRun=True)
            else:
                requests_payload, responses_payload, remote_ids = adapter.create_workflow(app, workflow)
                item_result["ok"] = True
                item_result["requests"] = requests_payload
                item_result["responses"] = responses_payload
                item_result["remoteIds"] = remote_ids
                ok_count += 1
                append_log(
                    log_path,
                    "workflow_finished",
                    index=index,
                    workflowKey=workflow_key,
                    processId=remote_ids.get("processId", ""),
                    versionId=remote_ids.get("versionId", ""),
                )
        except Exception as exc:
            item_result["error"] = str(exc)
            item_result["requests"] = item_result["requests"] or [{"name": "saveFlow", "url": adapter.save_url, "payload": build_draft_payload(app, workflow)}]
            fail_count += 1
            append_log(log_path, "workflow_failed", index=index, workflowKey=workflow_key, error=str(exc))
        results.append(item_result)

    result = {
        "schemaVersion": "workflow_create_result_v1",
        "createdAt": now_iso(),
        "sourcePlanJson": str(plan_path),
        "app": app,
        "dryRun": bool(args.dry_run),
        "adapter": {
            "enabled": bool(adapter.enabled),
            "configPath": str(private_api_path) if private_api_path else "",
            "saveFlowUrl": adapter.save_url,
            "publishUrl": adapter.publish_url,
            "enableUrl": adapter.enable_url,
        },
        "results": results,
        "summary": {
            "total": len(results),
            "success": ok_count,
            "failed": fail_count,
        },
        "logFile": str(log_path),
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = make_workflow_output_path(WORKFLOW_CREATE_DIR, "workflow_create_result", app_id)
    write_json_with_latest(WORKFLOW_CREATE_DIR, output_path, "workflow_create_result_latest.json", result)
    append_log(log_path, "finished", output=str(output_path), successCount=ok_count, failedCount=fail_count)

    print("工作流创建阶段完成")
    print(f"- 应用: {app_name} ({app_id})")
    print(f"- dry-run: {bool(args.dry_run)}")
    print(f"- 成功: {ok_count}")
    print(f"- 失败: {fail_count}")
    print(f"- 结果文件: {output_path}")
    print(f"- 日志文件: {log_path}")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {log_path}")
    if not args.dry_run and fail_count > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
