#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据 workflow_plan_v1 创建工作流。

当前仅接入了来自 `old_workflow/record/action/创建工作流.har` 验证过的最小链路：
- 工作表事件触发
- 新增记录节点
- 更新流程名称
- 发布流程

未覆盖的触发器 / 动作节点会被标记为 skipped，不会让整条 pipeline 直接失败。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlencode

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
REPO_HAP_DIR = CURRENT_DIR.parents[2] / "scripts" / "hap"
if str(REPO_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_HAP_DIR))

from mock_data_common import fetch_worksheet_controls, load_web_auth
from workflow_common import (
    APP_MANAGEMENT_ADD_WORKFLOW_URL,
    FLOW_NODE_ADD_URL,
    FLOW_NODE_APP_DTOS_URL,
    FLOW_NODE_APP_TEMPLATE_CONTROLS_URL,
    FLOW_NODE_DETAIL_URL,
    FLOW_NODE_SAVE_URL,
    PRIVATE_WORKFLOW_API_JSON,
    PRIVATE_WORKFLOW_API_MD,
    PROCESS_ADD_URL,
    PROCESS_GET_URL,
    PROCESS_PUBLISH_URL,
    PROCESS_UPDATE_URL,
    WORKFLOW_CREATE_DIR,
    append_log,
    ensure_state_success,
    ensure_workflow_dirs,
    get_private_json,
    load_json,
    load_private_workflow_api_doc,
    make_workflow_log_path,
    make_workflow_output_path,
    now_iso,
    post_private_json,
    resolve_workflow_plan_json,
    write_json_with_latest,
)

TRIGGER_EVENT_TO_ID = {
    "create": "2",
    "update": "3",
}

SUPPORTED_TRIGGER_TYPES = {"worksheet"}
SUPPORTED_NODE_TYPES = {"create_record"}
DEFAULT_ICON_COLOR = "#1677ff"


def build_process_add_payload(app: dict, workflow: dict) -> dict:
    return {
        "companyId": "",
        "relationId": str(app.get("appId", "")).strip(),
        "relationType": 2,
        "startEventAppType": 1,
        "name": str(workflow.get("name", "")).strip() or "未命名工作流",
        "explain": str(workflow.get("summary", "")).strip(),
    }


def build_process_update_payload(company_id: str, process_id: str, workflow: dict) -> dict:
    return {
        "companyId": company_id,
        "processId": process_id,
        "name": str(workflow.get("name", "")).strip() or "未命名工作流",
        "explain": str(workflow.get("summary", "")).strip(),
        "iconColor": DEFAULT_ICON_COLOR,
    }


def append_request_trace(items: List[dict], name: str, url: str, payload: Any = None) -> None:
    record: Dict[str, Any] = {"name": name, "url": url}
    if payload is not None:
        record["payload"] = payload
    items.append(record)


def append_response_trace(items: List[dict], name: str, response: dict) -> None:
    items.append({"name": name, "response": response})


def build_url_with_params(url: str, params: dict) -> str:
    return f"{url}?{urlencode(params)}"


def get_workflow_referer(process_id: str = "") -> str:
    if process_id:
        return f"https://www.mingdao.com/workflowedit/{process_id}"
    return "https://www.mingdao.com/"


def build_trigger_payload(process_id: str, start_node_id: str, workflow: dict) -> dict:
    trigger = workflow.get("trigger", {}) if isinstance(workflow.get("trigger"), dict) else {}
    event = str(trigger.get("event", "")).strip()
    trigger_id = TRIGGER_EVENT_TO_ID.get(event, "")
    if not trigger_id:
        raise RuntimeError(f"当前未支持的 trigger.event: {event}")
    worksheet_id = str(trigger.get("worksheetId", "")).strip()
    controls_payload = fetch_worksheet_controls(worksheet_id, load_web_auth()).get("controls", [])
    return {
        "appId": worksheet_id,
        "appType": 1,
        "assignFieldIds": [
            str(item).strip()
            for item in trigger.get("triggerFieldIds", []) or []
            if str(item).strip()
        ],
        "processId": process_id,
        "nodeId": start_node_id,
        "flowNodeType": 0,
        "operateCondition": trigger.get("conditions", []) or [],
        "triggerId": trigger_id,
        "name": "工作表事件触发",
        "controls": controls_payload,
    }


def build_create_node_add_payload(process_id: str, previous_node_id: str, node: dict) -> dict:
    return {
        "processId": process_id,
        "actionId": "1",
        "appType": 1,
        "name": str(node.get("name", "")).strip() or "新增记录",
        "prveId": previous_node_id,
        "typeId": 6,
    }


def fetch_process_graph(process_id: str, requests_payload: List[dict], responses_payload: List[dict]) -> dict:
    params = {"processId": process_id, "count": 200}
    url = build_url_with_params(PROCESS_GET_URL, params)
    append_request_trace(requests_payload, "getProcessGraph", url)
    resp = get_private_json(PROCESS_GET_URL, referer=get_workflow_referer(process_id), params=params)
    append_response_trace(responses_payload, "getProcessGraph", resp)
    ensure_state_success(resp, "GetProcessGraph")
    data = resp.get("data", {}) if isinstance(resp.get("data"), dict) else {}
    if not data:
        raise RuntimeError(f"GetProcessGraph 未返回 data: {resp}")
    return data


def fetch_node_detail(process_id: str, node_id: str, flow_node_type: int, worksheet_id: str) -> dict:
    params = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": flow_node_type,
        "appId": worksheet_id,
        "instanceId": "",
    }
    return get_private_json(FLOW_NODE_DETAIL_URL, referer=get_workflow_referer(process_id), params=params)


def fetch_target_controls(process_id: str, node_id: str, target_worksheet_id: str) -> List[dict]:
    params = {
        "processId": process_id,
        "nodeId": node_id,
        "selectNodeId": "",
        "appId": target_worksheet_id,
        "appType": 1,
    }
    resp = get_private_json(
        FLOW_NODE_APP_TEMPLATE_CONTROLS_URL,
        referer=get_workflow_referer(process_id),
        params=params,
    )
    ensure_state_success(resp, "GetAppTemplateControls")
    data = resp.get("data", [])
    if not isinstance(data, list):
        raise RuntimeError(f"GetAppTemplateControls 返回格式错误: {resp}")
    return data


def fetch_available_source_nodes(process_id: str, node_id: str) -> List[dict]:
    params = {
        "nodeId": node_id,
        "processId": process_id,
        "sourceAppId": "",
        "type": 2,
        "enumDefault": 0,
        "selectNodeId": "",
        "dataSource": "",
        "current": "false",
        "filterType": 0,
    }
    resp = get_private_json(
        FLOW_NODE_APP_DTOS_URL,
        referer=get_workflow_referer(process_id),
        params=params,
    )
    ensure_state_success(resp, "GetFlowNodeAppDtos")
    data = resp.get("data", [])
    if not isinstance(data, list):
        raise RuntimeError(f"GetFlowNodeAppDtos 返回格式错误: {resp}")
    return data


def stringify_static_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def normalize_select_value(control: dict, value: Any) -> str:
    raw_options = control.get("options", []) or []
    options = [item for item in raw_options if isinstance(item, dict)]
    if not options:
        return stringify_static_value(value)
    text = stringify_static_value(value).strip()
    if not text:
        return ""
    for option in options:
        key = str(option.get("key", "")).strip()
        if key and text == key:
            return key
    for option in options:
        option_value = str(option.get("value", "")).strip()
        key = str(option.get("key", "")).strip()
        if option_value and text == option_value and key:
            return key
    if text.isdigit():
        wanted_index = int(text)
        for option in options:
            try:
                option_index = int(option.get("index", 0) or 0)
            except Exception:
                continue
            key = str(option.get("key", "")).strip()
            if option_index == wanted_index and key:
                return key
    substring_matches: list[str] = []
    for option in options:
        option_value = str(option.get("value", "")).strip()
        key = str(option.get("key", "")).strip()
        if not option_value or not key:
            continue
        if text in option_value or option_value in text:
            substring_matches.append(key)
    if len(substring_matches) == 1:
        return substring_matches[0]
    prefix_matches: list[str] = []
    for option in options:
        option_value = str(option.get("value", "")).strip()
        key = str(option.get("key", "")).strip()
        if not option_value or not key:
            continue
        common_prefix_len = 0
        for left, right in zip(text, option_value):
            if left != right:
                break
            common_prefix_len += 1
        if common_prefix_len >= 1:
            prefix_matches.append(key)
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return text


def normalize_static_field_value(control: dict, value: Any) -> str:
    control_type = int(control.get("type", 0) or 0)
    if control_type in {9, 10, 11}:
        if control_type == 10 and isinstance(value, list):
            items = [normalize_select_value(control, item) for item in value]
            return json.dumps([item for item in items if item], ensure_ascii=False, separators=(",", ":"))
        return normalize_select_value(control, value)
    return stringify_static_value(value)


def build_action_field_payload(
    field_value_item: dict,
    target_control_map: dict,
    trigger_node_id: str,
    available_source_field_ids: set[str],
) -> dict:
    field_id = str(field_value_item.get("fieldId", "")).strip()
    control = target_control_map.get(field_id)
    if not control:
        raise RuntimeError(f"目标字段不存在于目标工作表控件中: fieldId={field_id}")

    value_type = str(field_value_item.get("valueType", "")).strip()
    if value_type == "trigger_field":
        source_field_id = str(field_value_item.get("sourceFieldId", "")).strip()
        if not source_field_id:
            raise RuntimeError(f"fieldId={field_id} 缺少 sourceFieldId")
        if source_field_id not in available_source_field_ids:
            raise RuntimeError(f"sourceFieldId 不在可引用触发字段中: {source_field_id}")
        field_value = f"${trigger_node_id}-{source_field_id}$"
    elif value_type == "static":
        field_value = normalize_static_field_value(control, field_value_item.get("value"))
    else:
        raise RuntimeError(f"暂不支持的 valueType: {value_type}")

    return {
        "fieldId": field_id,
        "type": control.get("type", 2),
        "enumDefault": control.get("enumDefault", 0),
        "nodeId": "",
        "nodeName": "",
        "fieldValueId": "",
        "fieldValueName": "",
        "fieldValue": field_value,
        "nodeAppId": "",
    }


def build_create_node_save_payload(
    process_id: str,
    node_id: str,
    node: dict,
    trigger_node_id: str,
    available_source_field_ids: set[str],
) -> dict:
    config = node.get("config", {}) if isinstance(node.get("config"), dict) else {}
    target_worksheet_id = str(config.get("targetWorksheetId", "")).strip()
    target_controls = fetch_target_controls(process_id, node_id, target_worksheet_id)
    target_control_map = {
        str(item.get("controlId", "")).strip(): item
        for item in target_controls
        if isinstance(item, dict) and str(item.get("controlId", "")).strip()
    }
    configured_items = [
        item
        for item in config.get("fieldValues", []) or []
        if isinstance(item, dict) and str(item.get("fieldId", "")).strip()
    ]
    configured_payload_map = {
        str(item.get("fieldId", "")).strip(): build_action_field_payload(
            item,
            target_control_map,
            trigger_node_id,
            available_source_field_ids,
        )
        for item in configured_items
    }
    if not configured_payload_map:
        raise RuntimeError("create_record 节点至少需要 1 个 fieldValues")
    fields: List[dict] = []
    for control in target_controls:
        if not isinstance(control, dict):
            continue
        control_id = str(control.get("controlId", "")).strip()
        if not control_id:
            continue
        payload = configured_payload_map.get(control_id)
        if payload is None:
            payload = {
                "fieldId": control_id,
                "type": control.get("type", 2),
                "enumDefault": control.get("enumDefault", 0),
                "nodeId": "",
                "nodeName": "",
                "fieldValueId": "",
                "fieldValueName": "",
                "fieldValue": "[]" if control_id == "ownerid" else "",
                "nodeAppId": "",
            }
        fields.append(payload)
    return {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 6,
        "actionId": "1",
        "name": str(node.get("name", "")).strip() or "新增记录",
        "selectNodeId": "",
        "appId": target_worksheet_id,
        "appType": 1,
        "fields": fields,
        "filters": [],
    }


def collect_source_field_ids(source_nodes: List[dict]) -> set[str]:
    result: set[str] = set()
    for source_node in source_nodes:
        if not isinstance(source_node, dict):
            continue
        for control in source_node.get("controls", []) or []:
            if not isinstance(control, dict):
                continue
            control_id = str(control.get("controlId", "")).strip()
            if control_id:
                result.add(control_id)
    return result


def get_supported_reason(workflow: dict) -> str:
    trigger = workflow.get("trigger", {}) if isinstance(workflow.get("trigger"), dict) else {}
    trigger_type = str(trigger.get("type", "")).strip()
    if trigger_type not in SUPPORTED_TRIGGER_TYPES:
        return f"当前 HAR 仅覆盖 worksheet 触发，暂不支持 {trigger_type or 'unknown'}"
    event = str(trigger.get("event", "")).strip()
    if event not in TRIGGER_EVENT_TO_ID:
        return f"当前 HAR 仅接入 create/update 触发，暂不支持 {event or 'unknown'}"
    nodes = workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []
    for node in nodes:
        node_type = str(node.get("nodeType", "")).strip()
        if node_type not in SUPPORTED_NODE_TYPES:
            return f"当前 HAR 仅覆盖 create_record 动作节点，暂不支持 {node_type or 'unknown'}"
    return ""


class WorkflowPrivateApiAdapter:
    def __init__(self, config: dict | None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.process_add_url = str(self.config.get("processAddUrl", "")).strip() or PROCESS_ADD_URL
        self.process_get_url = str(self.config.get("processGetUrl", "")).strip() or PROCESS_GET_URL
        self.process_update_url = str(self.config.get("processUpdateUrl", "")).strip() or PROCESS_UPDATE_URL
        self.process_publish_url = str(self.config.get("processPublishUrl", "")).strip() or PROCESS_PUBLISH_URL
        self.app_management_add_workflow_url = (
            str(self.config.get("appManagementAddWorkflowUrl", "")).strip() or APP_MANAGEMENT_ADD_WORKFLOW_URL
        )
        self.flow_node_add_url = str(self.config.get("flowNodeAddUrl", "")).strip() or FLOW_NODE_ADD_URL
        self.flow_node_save_url = str(self.config.get("flowNodeSaveUrl", "")).strip() or FLOW_NODE_SAVE_URL

    def ensure_available(self) -> None:
        if self.enabled:
            return
        hint = PRIVATE_WORKFLOW_API_JSON if PRIVATE_WORKFLOW_API_JSON.exists() else PRIVATE_WORKFLOW_API_MD
        raise RuntimeError(
            "当前未配置可执行的工作流私有接口适配器。"
            f"请补充 {hint}，至少提供 enabled=true，再执行非 dry-run 创建。"
        )

    def create_workflow(self, app: dict, workflow: dict) -> Tuple[List[dict], List[dict], Dict[str, str]]:
        self.ensure_available()
        requests_payload: List[dict] = []
        responses_payload: List[dict] = []

        process_add_payload = build_process_add_payload(app, workflow)
        append_request_trace(requests_payload, "processAdd", self.process_add_url, process_add_payload)
        process_add_resp = post_private_json(self.process_add_url, process_add_payload, referer=get_workflow_referer())
        append_response_trace(responses_payload, "processAdd", process_add_resp)
        ensure_state_success(process_add_resp, "ProcessAdd")
        process_data = process_add_resp.get("data", {}) if isinstance(process_add_resp.get("data"), dict) else {}
        process_id = str(process_data.get("id", "")).strip()
        company_id = str(process_data.get("companyId", "")).strip()
        if not process_id:
            raise RuntimeError(f"ProcessAdd 未返回 processId: {process_add_resp}")

        add_workflow_payload = {
            "projectId": company_id,
            "name": str(workflow.get("name", "")).strip() or "未命名工作流",
        }
        append_request_trace(
            requests_payload,
            "appManagementAddWorkflow",
            self.app_management_add_workflow_url,
            add_workflow_payload,
        )
        add_workflow_resp = post_private_json(
            self.app_management_add_workflow_url,
            add_workflow_payload,
            referer=get_workflow_referer(process_id),
        )
        append_response_trace(responses_payload, "appManagementAddWorkflow", add_workflow_resp)

        graph = fetch_process_graph(process_id, requests_payload, responses_payload)
        start_node_id = str(graph.get("startEventId", "")).strip()
        if not start_node_id:
            raise RuntimeError(f"GetProcessGraph 未返回 startEventId: {graph}")

        trigger = workflow.get("trigger", {}) if isinstance(workflow.get("trigger"), dict) else {}
        trigger_payload = build_trigger_payload(process_id, start_node_id, workflow)
        append_request_trace(requests_payload, "saveTriggerNode", self.flow_node_save_url, trigger_payload)
        trigger_resp = post_private_json(
            self.flow_node_save_url,
            trigger_payload,
            referer=get_workflow_referer(process_id),
        )
        append_response_trace(responses_payload, "saveTriggerNode", trigger_resp)
        ensure_state_success(trigger_resp, "SaveTriggerNode")
        trigger_control_ids = {
            str(item.get("controlId", "")).strip()
            for item in trigger_payload.get("controls", []) or []
            if isinstance(item, dict) and str(item.get("controlId", "")).strip()
        }

        previous_node_id = start_node_id
        for idx, node in enumerate(workflow.get("nodes", []) or [], start=1):
            add_node_payload = build_create_node_add_payload(process_id, previous_node_id, node)
            append_request_trace(requests_payload, f"addActionNode#{idx}", self.flow_node_add_url, add_node_payload)
            add_node_resp = post_private_json(
                self.flow_node_add_url,
                add_node_payload,
                referer=get_workflow_referer(process_id),
            )
            append_response_trace(responses_payload, f"addActionNode#{idx}", add_node_resp)
            ensure_state_success(add_node_resp, f"AddActionNode#{idx}")
            add_flow_nodes = (
                add_node_resp.get("data", {}).get("addFlowNodes", [])
                if isinstance(add_node_resp.get("data"), dict)
                else []
            )
            if not isinstance(add_flow_nodes, list) or not add_flow_nodes:
                raise RuntimeError(f"AddActionNode#{idx} 未返回 addFlowNodes: {add_node_resp}")
            action_node_id = str(add_flow_nodes[0].get("id", "")).strip()
            if not action_node_id:
                raise RuntimeError(f"AddActionNode#{idx} 未返回节点 id: {add_node_resp}")

            source_nodes = fetch_available_source_nodes(process_id, action_node_id)
            available_source_field_ids = collect_source_field_ids(source_nodes) | trigger_control_ids

            save_node_payload = build_create_node_save_payload(
                process_id=process_id,
                node_id=action_node_id,
                node=node,
                trigger_node_id=start_node_id,
                available_source_field_ids=available_source_field_ids,
            )
            append_request_trace(requests_payload, f"saveActionNode#{idx}", self.flow_node_save_url, save_node_payload)
            save_node_resp = post_private_json(
                self.flow_node_save_url,
                save_node_payload,
                referer=get_workflow_referer(process_id),
            )
            append_response_trace(responses_payload, f"saveActionNode#{idx}", save_node_resp)
            ensure_state_success(save_node_resp, f"SaveActionNode#{idx}")
            previous_node_id = action_node_id

        process_update_payload = build_process_update_payload(company_id, process_id, workflow)
        append_request_trace(requests_payload, "processUpdate", self.process_update_url, process_update_payload)
        process_update_resp = post_private_json(
            self.process_update_url,
            process_update_payload,
            referer=get_workflow_referer(process_id),
        )
        append_response_trace(responses_payload, "processUpdate", process_update_resp)
        ensure_state_success(process_update_resp, "ProcessUpdate")

        published_process_id = ""
        if bool(workflow.get("publish", True)):
            publish_params = {"isPublish": "true", "processId": process_id}
            publish_url = build_url_with_params(self.process_publish_url, publish_params)
            append_request_trace(requests_payload, "processPublish", publish_url)
            publish_resp = get_private_json(
                self.process_publish_url,
                referer=get_workflow_referer(process_id),
                params=publish_params,
            )
            append_response_trace(responses_payload, "processPublish", publish_resp)
            ensure_state_success(publish_resp, "ProcessPublish")
            publish_data = publish_resp.get("data", {}) if isinstance(publish_resp.get("data"), dict) else {}
            process_info = publish_data.get("process", {}) if isinstance(publish_data.get("process"), dict) else {}
            published_process_id = str(process_info.get("id", "")).strip()

        return (
            requests_payload,
            responses_payload,
            {
                "processId": process_id,
                "publishedProcessId": published_process_id,
            },
        )


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
    skipped_count = 0

    for index, workflow in enumerate(plan.get("workflows", []) or [], start=1):
        workflow_key = str(workflow.get("key", "")).strip()
        workflow_name = str(workflow.get("name", "")).strip()
        append_log(log_path, "workflow_start", index=index, workflowKey=workflow_key, workflowName=workflow_name)
        item_result: Dict[str, Any] = {
            "index": index,
            "workflowKey": workflow_key,
            "workflowName": workflow_name,
            "ok": False,
            "skipped": False,
            "remoteIds": {"processId": "", "publishedProcessId": ""},
            "requests": [],
            "responses": [],
            "error": "",
        }
        try:
            unsupported_reason = get_supported_reason(workflow)
            if unsupported_reason:
                item_result["skipped"] = True
                item_result["error"] = unsupported_reason
                skipped_count += 1
                append_log(
                    log_path,
                    "workflow_skipped",
                    index=index,
                    workflowKey=workflow_key,
                    reason=unsupported_reason,
                )
            elif args.dry_run:
                draft_requests = [
                    {
                        "name": "processAdd",
                        "url": adapter.process_add_url,
                        "payload": build_process_add_payload(app, workflow),
                    },
                    {
                        "name": "saveTriggerNode",
                        "url": adapter.flow_node_save_url,
                        "payload": {
                            "processId": "DRY_RUN_PROCESS_ID",
                            "nodeId": "DRY_RUN_START_NODE_ID",
                            "flowNodeType": 0,
                            "appId": workflow.get("trigger", {}).get("worksheetId", ""),
                            "triggerId": TRIGGER_EVENT_TO_ID.get(
                                str(workflow.get("trigger", {}).get("event", "")).strip(),
                                "",
                            ),
                            "assignFieldIds": workflow.get("trigger", {}).get("triggerFieldIds", []),
                            "operateCondition": workflow.get("trigger", {}).get("conditions", []),
                        },
                    },
                    {
                        "name": "processUpdate",
                        "url": adapter.process_update_url,
                        "payload": build_process_update_payload("DRY_RUN_COMPANY_ID", "DRY_RUN_PROCESS_ID", workflow),
                    },
                ]
                for node_index, node in enumerate(workflow.get("nodes", []) or [], start=1):
                    draft_requests.append(
                        {
                            "name": f"addActionNode#{node_index}",
                            "url": adapter.flow_node_add_url,
                            "payload": build_create_node_add_payload("DRY_RUN_PROCESS_ID", "PREVIOUS_NODE_ID", node),
                        }
                    )
                    draft_requests.append(
                        {
                            "name": f"saveActionNode#{node_index}",
                            "url": adapter.flow_node_save_url,
                            "payload": {
                                "processId": "DRY_RUN_PROCESS_ID",
                                "nodeId": f"DRY_RUN_NODE_{node_index}",
                                "flowNodeType": 6,
                                "actionId": "1",
                                "appId": node.get("config", {}).get("targetWorksheetId", ""),
                                "appType": 1,
                                "fields": node.get("config", {}).get("fieldValues", []),
                                "filters": [],
                            },
                        }
                    )
                if bool(workflow.get("publish", True)):
                    draft_requests.append(
                        {
                            "name": "processPublish",
                            "url": build_url_with_params(
                                adapter.process_publish_url,
                                {"isPublish": "true", "processId": "DRY_RUN_PROCESS_ID"},
                            ),
                        }
                    )
                item_result["ok"] = True
                item_result["requests"] = draft_requests
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
                    publishedProcessId=remote_ids.get("publishedProcessId", ""),
                )
        except Exception as exc:
            item_result["error"] = str(exc)
            fail_count += 1
            append_log(log_path, "workflow_failed", index=index, workflowKey=workflow_key, error=str(exc))
        results.append(item_result)

    result = {
        "schemaVersion": "workflow_create_result_v2",
        "createdAt": now_iso(),
        "sourcePlanJson": str(plan_path),
        "app": app,
        "dryRun": bool(args.dry_run),
        "adapter": {
            "enabled": bool(adapter.enabled),
            "configPath": str(private_api_path) if private_api_path else "",
            "processAddUrl": adapter.process_add_url,
            "processGetUrl": adapter.process_get_url,
            "processUpdateUrl": adapter.process_update_url,
            "processPublishUrl": adapter.process_publish_url,
            "flowNodeAddUrl": adapter.flow_node_add_url,
            "flowNodeSaveUrl": adapter.flow_node_save_url,
        },
        "results": results,
        "summary": {
            "total": len(results),
            "success": ok_count,
            "failed": fail_count,
            "skipped": skipped_count,
        },
        "logFile": str(log_path),
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = make_workflow_output_path(WORKFLOW_CREATE_DIR, "workflow_create_result", app_id)
    write_json_with_latest(WORKFLOW_CREATE_DIR, output_path, "workflow_create_result_latest.json", result)
    append_log(
        log_path,
        "finished",
        output=str(output_path),
        successCount=ok_count,
        failedCount=fail_count,
        skippedCount=skipped_count,
    )

    print("工作流创建阶段完成")
    print(f"- 应用: {app_name} ({app_id})")
    print(f"- dry-run: {bool(args.dry_run)}")
    print(f"- 成功: {ok_count}")
    print(f"- 跳过: {skipped_count}")
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
