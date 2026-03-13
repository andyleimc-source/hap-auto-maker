#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于工作流 schema，用 Gemini 生成 3 个可直接执行的工作流方案。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from google import genai
from google.genai import types

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from workflow_common import (
    GEMINI_CONFIG_PATH,
    SUPPORTED_NODE_TYPES,
    SUPPORTED_TRIGGER_EVENTS,
    WORKFLOW_PLAN_DIR,
    append_log,
    build_schedule_defaults,
    ensure_workflow_dirs,
    extract_json_object,
    find_field,
    find_worksheet,
    load_gemini_api_key,
    load_json,
    make_workflow_log_path,
    make_workflow_output_path,
    now_iso,
    resolve_workflow_schema_json,
    summarize_schema_for_prompt,
    write_json,
    write_json_with_latest,
)

DEFAULT_MODEL = "gemini-2.5-pro"
REQUIRED_KEYS = ["worksheet_create_trigger", "worksheet_update_trigger", "scheduled_trigger"]
EXECUTABLE_NODE_TYPES = {"create_record"}


def build_prompt(schema: dict) -> str:
    app = schema.get("app", {}) if isinstance(schema, dict) else {}
    hints = schema.get("workflowPlanningHints", {}) if isinstance(schema, dict) else {}
    return f"""
你是明道云 HAP 工作流策划引擎。请基于以下应用 schema，直接输出 3 个“可执行”的工作流规划 JSON。

应用：
- appId: {app.get("appId", "")}
- appName: {app.get("appName", "")}

可用工作表与字段：
{summarize_schema_for_prompt(schema)}

规划提示：
{json.dumps(hints, ensure_ascii=False, indent=2)}

必须输出严格 JSON 对象，不要 markdown，不要解释，不要注释。输出结构如下：
{{
  "workflows": [
    {{
      "key": "worksheet_create_trigger",
      "name": "工作流名称",
      "summary": "一句话说明",
      "trigger": {{
        "type": "worksheet",
        "worksheetId": "必须存在于 schema",
        "worksheetName": "必须与 schema 对应",
        "event": "create",
        "triggerFieldIds": [],
        "conditions": []
      }},
      "nodes": [
        {{
          "nodeType": "create_record",
          "name": "节点名称",
          "config": {{
            "targetWorksheetId": "必须存在于 schema",
            "targetWorksheetName": "必须与 schema 对应",
            "fieldValues": [
              {{
                "fieldId": "目标字段ID",
                "valueType": "static|trigger_field",
                "value": "静态值时填写",
                "sourceFieldId": "引用触发记录字段时填写"
              }}
            ]
          }}
        }}
      ],
      "publish": true,
      "enable": true
    }},
    {{
      "key": "worksheet_update_trigger",
      "name": "工作流名称",
      "summary": "一句话说明",
      "trigger": {{
        "type": "worksheet",
        "worksheetId": "必须存在于 schema",
        "worksheetName": "必须与 schema 对应",
        "event": "update",
        "triggerFieldIds": ["建议填写 1-3 个字段ID，必须存在于 schema"],
        "conditions": []
      }},
      "nodes": [
        {{
          "nodeType": "create_record",
          "name": "节点名称",
          "config": {{
            "targetWorksheetId": "必须存在于 schema",
            "targetWorksheetName": "必须与 schema 对应",
            "fieldValues": [
              {{
                "fieldId": "目标字段ID",
                "valueType": "static|trigger_field",
                "value": "静态值时填写",
                "sourceFieldId": "引用触发记录字段时填写"
              }}
            ]
          }}
        }}
      ],
      "publish": true,
      "enable": true
    }},
    {{
      "key": "scheduled_trigger",
      "name": "工作流名称",
      "summary": "一句话说明",
      "trigger": {{
        "type": "schedule",
        "worksheetId": "建议选择一个目标工作表",
        "worksheetName": "必须与 schema 对应",
        "event": "schedule",
        "schedule": {{
          "frequency": "weekday|daily",
          "interval": 1,
          "time": "09:00",
          "timezone": "Asia/Shanghai"
        }},
        "triggerFieldIds": [],
        "conditions": []
      }},
      "nodes": [
        {{
          "nodeType": "create_record",
          "name": "节点名称",
          "config": {{
            "targetWorksheetId": "必须存在于 schema",
            "targetWorksheetName": "必须与 schema 对应",
            "fieldValues": [
              {{
                "fieldId": "目标字段ID",
                "valueType": "static",
                "value": "定时触发没有触发记录，建议只输出静态值",
                "sourceFieldId": ""
              }}
            ]
          }}
        }}
      ],
      "publish": true,
      "enable": true
    }}
  ]
}}

强约束：
1. 只能输出 3 个工作流，key 必须正好是 worksheet_create_trigger、worksheet_update_trigger、scheduled_trigger。
2. 所有 worksheetId、fieldId 必须来自提供的 schema。
3. 新增触发和更新触发必须引用两个不同的工作流对象，event 分别固定为 create 和 update。
4. schedule 工作流必须带完整 schedule，frequency 只能是 weekday 或 daily。
5. 当前可执行节点仅允许 create_record，不要输出 update_fields 或 send_notice。
6. 每个工作流至少 1 个节点，最多 2 个节点。
7. nodeType=create_record 时，config 必须包含 targetWorksheetId、targetWorksheetName、fieldValues 数组。
8. fieldValues 每项必须包含 fieldId、valueType。valueType=static 时填写 value；valueType=trigger_field 时填写 sourceFieldId。
9. scheduled_trigger 没有触发记录，fieldValues 只能使用 static。
10. 更新触发尽量选择 1-3 个 triggerFieldIds；新增触发和定时触发的 triggerFieldIds 必须为空数组。
11. output 必须是合法 JSON。
""".strip()


def validate_conditions(conditions: Any, schema: dict, worksheet_id: str) -> List[str]:
    errors: List[str] = []
    if conditions is None:
        return errors
    if not isinstance(conditions, list):
        return ["trigger.conditions 必须是数组"]
    for idx, cond in enumerate(conditions, start=1):
        if not isinstance(cond, dict):
            errors.append(f"condition[{idx}] 必须是对象")
            continue
        field_id = str(cond.get("fieldId", "")).strip()
        if field_id and not find_field(schema, worksheet_id, field_id):
            errors.append(f"condition[{idx}] 引用了不存在的 fieldId={field_id}")
    return errors


def validate_node(node: Any, schema: dict, workflow_key: str) -> List[str]:
    errors: List[str] = []
    if not isinstance(node, dict):
        return [f"{workflow_key} 的 node 必须是对象"]
    node_type = str(node.get("nodeType", "")).strip()
    if node_type not in SUPPORTED_NODE_TYPES:
        return [f"{workflow_key} 的 nodeType 不支持: {node_type}"]
    if node_type not in EXECUTABLE_NODE_TYPES:
        return [f"{workflow_key} 的 nodeType 当前未接入真实 HAR 执行链: {node_type}"]
    config = node.get("config")
    if not isinstance(config, dict):
        return [f"{workflow_key} 的 {node_type} 节点 config 必须是对象"]

    target_ws_id = str(config.get("targetWorksheetId", "")).strip()
    if not target_ws_id:
        errors.append(f"{workflow_key} 的 {node_type} 缺少 targetWorksheetId")
    elif not find_worksheet(schema, target_ws_id):
        errors.append(f"{workflow_key} 的 {node_type} 引用了不存在的 targetWorksheetId={target_ws_id}")
    values = config.get("fieldValues")
    if not isinstance(values, list) or not values:
        errors.append(f"{workflow_key} 的 {node_type} 缺少非空 fieldValues")
    else:
        for idx, item in enumerate(values, start=1):
            if not isinstance(item, dict):
                errors.append(f"{workflow_key} 的 fieldValues[{idx}] 必须是对象")
                continue
            field_id = str(item.get("fieldId", "")).strip()
            if not field_id:
                errors.append(f"{workflow_key} 的 fieldValues[{idx}] 缺少 fieldId")
            elif target_ws_id and not find_field(schema, target_ws_id, field_id):
                errors.append(f"{workflow_key} 的 fieldValues[{idx}] 引用了不存在的 fieldId={field_id}")
            value_type = str(item.get("valueType", "")).strip()
            if value_type not in {"static", "trigger_field"}:
                errors.append(f"{workflow_key} 的 fieldValues[{idx}] valueType 仅允许 static 或 trigger_field")
                continue
            if value_type == "static" and item.get("value", None) in (None, ""):
                errors.append(f"{workflow_key} 的 fieldValues[{idx}] 使用 static 时必须提供 value")
            if value_type == "trigger_field":
                source_field_id = str(item.get("sourceFieldId", "")).strip()
                if not source_field_id:
                    errors.append(f"{workflow_key} 的 fieldValues[{idx}] 使用 trigger_field 时必须提供 sourceFieldId")

    return errors


def normalize_workflow_plan(raw: dict, schema: dict) -> dict:
    raw_workflows = raw.get("workflows")
    if not isinstance(raw_workflows, list):
        raise ValueError("Gemini 返回缺少 workflows 数组")
    workflows: List[dict] = []
    for workflow in raw_workflows:
        if not isinstance(workflow, dict):
            continue
        trigger = workflow.get("trigger")
        if not isinstance(trigger, dict):
            trigger = {}
        nodes = workflow.get("nodes")
        if not isinstance(nodes, list):
            nodes = []
        if str(trigger.get("type", "")).strip() == "schedule":
            schedule = trigger.get("schedule")
            if not isinstance(schedule, dict):
                trigger["schedule"] = build_schedule_defaults()
            else:
                merged = build_schedule_defaults()
                merged.update({k: v for k, v in schedule.items() if v not in (None, "")})
                trigger["schedule"] = merged
            trigger["event"] = "schedule"
        workflows.append(
            {
                "key": str(workflow.get("key", "")).strip(),
                "name": str(workflow.get("name", "")).strip(),
                "summary": str(workflow.get("summary", "")).strip(),
                "trigger": {
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
                    **({"schedule": trigger.get("schedule")} if isinstance(trigger.get("schedule"), dict) else {}),
                },
                "nodes": nodes,
                "publish": bool(workflow.get("publish", True)),
                "enable": bool(workflow.get("enable", True)),
            }
        )
    return {
        "schemaVersion": "workflow_plan_v1",
        "createdAt": now_iso(),
        "app": schema.get("app", {}),
        "workflows": workflows,
    }


def validate_plan(plan: dict, schema: dict) -> List[str]:
    errors: List[str] = []
    workflows = plan.get("workflows")
    if not isinstance(workflows, list):
        return ["workflows 必须是数组"]
    if len(workflows) != 3:
        errors.append("workflows 数量必须为 3")

    by_key = {str(item.get("key", "")).strip(): item for item in workflows if isinstance(item, dict)}
    if sorted(by_key.keys()) != sorted(REQUIRED_KEYS):
        errors.append(f"workflow keys 必须正好是 {', '.join(REQUIRED_KEYS)}")

    for key in REQUIRED_KEYS:
        workflow = by_key.get(key)
        if not workflow:
            continue
        name = str(workflow.get("name", "")).strip()
        if not name:
            errors.append(f"{key} 缺少 name")
        trigger = workflow.get("trigger")
        if not isinstance(trigger, dict):
            errors.append(f"{key} 缺少 trigger 对象")
            continue
        trigger_type = str(trigger.get("type", "")).strip()
        event = str(trigger.get("event", "")).strip()
        worksheet_id = str(trigger.get("worksheetId", "")).strip()
        if key == "scheduled_trigger":
            if trigger_type != "schedule":
                errors.append(f"{key} 的 trigger.type 必须是 schedule")
            if event != "schedule":
                errors.append(f"{key} 的 trigger.event 必须是 schedule")
        else:
            if trigger_type != "worksheet":
                errors.append(f"{key} 的 trigger.type 必须是 worksheet")
            expected_event = "create" if key == "worksheet_create_trigger" else "update"
            if event != expected_event:
                errors.append(f"{key} 的 trigger.event 必须是 {expected_event}")
        if event not in SUPPORTED_TRIGGER_EVENTS:
            errors.append(f"{key} 使用了不支持的 trigger.event={event}")
        if worksheet_id:
            worksheet = find_worksheet(schema, worksheet_id)
            if not worksheet:
                errors.append(f"{key} 引用了不存在的 worksheetId={worksheet_id}")
            else:
                worksheet_name = str(trigger.get("worksheetName", "")).strip()
                if worksheet_name and worksheet_name != str(worksheet.get("worksheetName", "")).strip():
                    errors.append(f"{key} 的 worksheetName 与 schema 不一致")
        else:
            errors.append(f"{key} 缺少 worksheetId")

        trigger_field_ids = trigger.get("triggerFieldIds")
        if not isinstance(trigger_field_ids, list):
            errors.append(f"{key} 的 triggerFieldIds 必须是数组")
        else:
            if key in {"worksheet_create_trigger", "scheduled_trigger"} and trigger_field_ids:
                errors.append(f"{key} 的 triggerFieldIds 必须为空数组")
            if key == "worksheet_update_trigger" and not trigger_field_ids:
                errors.append("worksheet_update_trigger 至少需要 1 个 triggerFieldIds")
            for field_id in trigger_field_ids:
                if worksheet_id and not find_field(schema, worksheet_id, field_id):
                    errors.append(f"{key} 引用了不存在的触发字段 fieldId={field_id}")

        errors.extend(validate_conditions(trigger.get("conditions"), schema, worksheet_id))
        nodes = workflow.get("nodes")
        if key == "scheduled_trigger":
            schedule = trigger.get("schedule")
            if not isinstance(schedule, dict):
                errors.append("scheduled_trigger 缺少 schedule")
            else:
                if str(schedule.get("frequency", "")).strip() not in {"weekday", "daily"}:
                    errors.append("scheduled_trigger.schedule.frequency 仅允许 weekday 或 daily")
                if not str(schedule.get("time", "")).strip():
                    errors.append("scheduled_trigger.schedule.time 不能为空")
                if not str(schedule.get("timezone", "")).strip():
                    errors.append("scheduled_trigger.schedule.timezone 不能为空")
            for node in nodes or []:
                config = node.get("config", {}) if isinstance(node, dict) else {}
                for idx, item in enumerate(config.get("fieldValues", []) or [], start=1):
                    if isinstance(item, dict) and str(item.get("valueType", "")).strip() != "static":
                        errors.append(f"{key} 的 fieldValues[{idx}] 仅允许 static")

        if not isinstance(nodes, list) or not nodes:
            errors.append(f"{key} 至少需要 1 个节点")
        elif len(nodes) > 2:
            errors.append(f"{key} 最多允许 2 个节点")
        else:
            for node in nodes:
                errors.extend(validate_node(node, schema, key))

    return errors


def save_round_raw(app_id: str, attempt: int, raw: dict) -> Path:
    path = (WORKFLOW_PLAN_DIR / f"workflow_plan_draft_{app_id}_attempt{attempt}.json").resolve()
    write_json(path, raw)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="基于工作流 schema，用 Gemini 规划 3 个工作流")
    parser.add_argument("--schema-json", default="", help="工作流 schema JSON 路径")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    parser.add_argument("--max-retries", type=int, default=3, help="校验失败重试次数")
    args = parser.parse_args()

    ensure_workflow_dirs()
    schema_path = resolve_workflow_schema_json(args.schema_json)
    schema = load_json(schema_path)
    app = schema.get("app", {}) if isinstance(schema, dict) else {}
    app_id = str(app.get("appId", "")).strip()
    app_name = str(app.get("appName", "")).strip()

    log_path = make_workflow_log_path("workflow_plan", app_id)
    append_log(log_path, "start", schemaJson=str(schema_path), appId=app_id, appName=app_name, model=args.model)

    api_key = load_gemini_api_key(Path(args.config).expanduser().resolve())
    client = genai.Client(api_key=api_key)
    prompt = build_prompt(schema)

    last_errors: List[str] = []
    final_plan = None
    for attempt in range(1, max(1, args.max_retries) + 1):
        current_prompt = prompt
        if last_errors:
            current_prompt += "\n\n上一次输出不合规，请修正以下问题后重新输出完整 JSON：\n"
            current_prompt += "\n".join(f"- {item}" for item in last_errors)
        append_log(log_path, "gemini_request", attempt=attempt, previousErrors=last_errors)
        response = client.models.generate_content(
            model=args.model,
            contents=current_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        raw = extract_json_object(response.text or "")
        draft_path = save_round_raw(app_id, attempt, raw)
        append_log(log_path, "gemini_response", attempt=attempt, draftPath=str(draft_path), raw=raw)
        normalized = normalize_workflow_plan(raw, schema)
        normalized["sourceSchemaJson"] = str(schema_path)
        normalized["model"] = args.model
        normalized["logFile"] = str(log_path)
        last_errors = validate_plan(normalized, schema)
        if not last_errors:
            final_plan = normalized
            break
        append_log(log_path, "validation_failed", attempt=attempt, errors=last_errors)

    if not final_plan:
        raise RuntimeError("Gemini 输出未通过校验: " + "；".join(last_errors))

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = make_workflow_output_path(WORKFLOW_PLAN_DIR, "workflow_plan", app_id)
    write_json_with_latest(WORKFLOW_PLAN_DIR, output_path, "workflow_plan_latest.json", final_plan)
    append_log(log_path, "finished", output=str(output_path), workflowCount=len(final_plan.get("workflows", [])))

    print("工作流规划完成")
    print(f"- 应用: {app_name} ({app_id})")
    print(f"- 工作流数量: {len(final_plan.get('workflows', []))}")
    print(f"- 结果文件: {output_path}")
    print(f"- 日志文件: {log_path}")
    print(json.dumps(final_plan, ensure_ascii=False, indent=2))
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {log_path}")


if __name__ == "__main__":
    main()
