#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于应用结构，用 Gemini 交互式生成对话机器人候选方案。
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from ai_utils import create_generation_config, get_ai_client, load_ai_config

from chatbot_common import (
    CHATBOT_PLAN_DIR,
    CHATBOT_SCHEMA_DIR,
    append_log,
    ensure_chatbot_dirs,
    extract_json_object,
    load_schema_json,
    make_chatbot_log_path,
    now_iso,
    write_json,
    write_json_with_latest,
)

DEFAULT_CHATBOT_COUNT = 2


def build_schema_summary(schema: dict) -> str:
    lines: List[str] = []
    for worksheet in schema.get("worksheets", []):
        ws_name = str(worksheet.get("worksheetName", "")).strip()
        if not ws_name:
            continue
        parts: List[str] = []
        for field in worksheet.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            field_name = str(field.get("fieldName", "")).strip()
            if not field_name:
                continue
            field_type = str(field.get("fieldType", "")).strip() or "Unknown"
            text = f"{field_name}<{field_type}>"
            values = [str(x).strip() for x in (field.get("values", []) or []) if str(x).strip()]
            if values:
                text += f"[可选值:{'/'.join(values[:5])}]"
            parts.append(text)
        relation_parts: List[str] = []
        for relation in worksheet.get("relations", []) or []:
            if not isinstance(relation, dict):
                continue
            source_field = str(relation.get("sourceFieldName", "")).strip()
            target_name = str(relation.get("targetWorksheetName", "")).strip()
            if not source_field or not target_name:
                continue
            multi_text = "多条" if relation.get("multiple") else "单条"
            relation_parts.append(f"{source_field}->{target_name}({multi_text})")
        preview = "；".join(parts[:10])
        if len(parts) > 10:
            preview += "；等"
        if relation_parts:
            relation_preview = "；".join(relation_parts[:5])
            if len(relation_parts) > 5:
                relation_preview += "；等"
            if preview:
                preview += f"；关联关系:{relation_preview}"
            else:
                preview = f"关联关系:{relation_preview}"
        lines.append(f"- {ws_name}: {preview}")
    return "\n".join(lines) if lines else "- 该应用下暂无工作表"


def build_prompt(schema: dict, feedback_history: List[dict], previous_proposals: List[dict]) -> str:
    runtime = schema.get("runtime", {})
    runtime_app = runtime.get("app", {}) if isinstance(runtime, dict) else {}
    selected_section = runtime.get("selectedSection", {}) if isinstance(runtime, dict) else {}
    app_name = str(schema.get("appName", "")).strip() or str(runtime_app.get("appName", "")).strip()
    feedback_text = "无"
    if feedback_history:
        parts = []
        for item in feedback_history:
            parts.append(f"Round {item['round']}: {item['feedback']}")
        feedback_text = "\n".join(parts)

    previous_text = "无"
    if previous_proposals:
        previous_text = json.dumps(previous_proposals, ensure_ascii=False, indent=2)

    return f"""
你是明道云 HAP 对话机器人策划顾问。请基于以下应用结构，为该应用规划合适数量的对话机器人方案（1-3 个，根据应用复杂度决定，最多不超过 3 个）。

应用名称：{app_name}
目标分组：{str(selected_section.get('name', '')).strip() or '默认分组'}
工作表与字段概览：
{build_schema_summary(schema)}

上一轮方案：
{previous_text}

用户反馈历史：
{feedback_text}

要求：
1. 根据应用复杂度规划合适数量的机器人（1-3 个，最多不超过 3 个），职责各有侧重，不要重复。简单应用规划 1 个，中等复杂度规划 2 个，高度复杂应用最多规划 3 个。
2. 机器人必须适配该应用现有工作表，不要脱离业务。
3. 名称简洁，不要出现”助手”这种占位名。
4. 简介要说明它主要处理什么数据、解决什么问题。
5. 输出严格 JSON，不要 markdown，不要解释。

JSON 结构如下：
{{
  "summary": "一句话总结本轮方案",
  "proposals": [
    {{
      "name": "机器人名称",
      "description": "机器人简介"
    }}
  ],
  "notes": ["可选说明1", "可选说明2"]
}}
""".strip()


def normalize_proposals(raw: Dict[str, Any]) -> List[dict]:
    source = raw.get("proposals", raw.get("chatbots", raw.get("robots", [])))
    if not isinstance(source, list):
        raise ValueError("Gemini 返回缺少 proposals 数组")
    result: List[dict] = []
    seen = set()
    for item in source:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        description = str(
            item.get("description", "") or item.get("intro", "") or item.get("summary", "") or item.get("remark", "")
        ).strip()
        if not name or not description:
            continue
        if name in seen:
            continue
        seen.add(name)
        result.append({"name": name, "description": description})
    if len(result) < 1:
        raise ValueError("Gemini 返回的有效方案为 0 个")
    if len(result) > 3:
        result = result[:3]
    return result


def save_round_snapshot(app_id: str, round_no: int, payload: dict) -> Path:
    ensure_chatbot_dirs()
    path = (CHATBOT_PLAN_DIR / f"chatbot_plan_draft_{app_id}_round{round_no}.json").resolve()
    write_json(path, payload)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="基于应用结构，用 Gemini 交互式生成对话机器人方案")
    parser.add_argument("--schema-json", default="", help="应用结构 JSON 路径（默认使用 latest）")
    parser.add_argument("--output", default="", help="最终输出 JSON 文件路径")
    parser.add_argument("--max-retries", type=int, default=3, help="单轮 Gemini 最大重试次数")
    parser.add_argument("--auto", action="store_true", help="自动确认第一次生成的方案，跳过人工审核（用于自动化流水线）")
    args = parser.parse_args()

    ai_config = load_ai_config()
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]

    ensure_chatbot_dirs()
    schema_path = Path(args.schema_json).expanduser().resolve() if args.schema_json else (CHATBOT_SCHEMA_DIR / "chatbot_app_schema_latest.json").resolve()
    schema = load_schema_json(schema_path)
    runtime = schema.get("runtime", {})
    runtime_app = runtime.get("app", {}) if isinstance(runtime, dict) else {}
    selected_section = runtime.get("selectedSection", {}) if isinstance(runtime, dict) else {}
    app_id = str(runtime_app.get("appId", "")).strip()
    app_name = str(schema.get("appName", "")).strip() or str(runtime_app.get("appName", "")).strip()

    log_path = make_chatbot_log_path("chatbot_plan", app_id)
    append_log(log_path, "start", schemaJson=str(schema_path), appId=app_id, appName=app_name, model=model_name)

    feedback_history: List[dict] = []
    current_proposals: List[dict] = []
    round_no = 1

    while True:
        prompt = build_prompt(schema, feedback_history, current_proposals)
        append_log(log_path, "gemini_request", round=round_no, feedbackCount=len(feedback_history))

        raw: Dict[str, Any] = {}
        last_error = ""
        for attempt in range(1, max(1, args.max_retries) + 1):
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=create_generation_config(
                        ai_config,
                        response_mime_type="application/json",
                        temperature=1.0,
                    ),
                )
                raw = extract_json_object(resp.text or "")
                current_proposals = normalize_proposals(raw)
                append_log(log_path, "gemini_response", round=round_no, attempt=attempt, raw=raw)
                break
            except Exception as exc:
                last_error = str(exc)
                append_log(log_path, "gemini_retry_failed", round=round_no, attempt=attempt, error=last_error)
                if attempt >= max(1, args.max_retries):
                    raise RuntimeError(f"Gemini 生成失败: {last_error}") from exc

        round_payload = {
            "schemaVersion": "chatbot_plan_draft_v1",
            "generatedAt": now_iso(),
            "round": round_no,
            "model": model_name,
            "sourceSchemaJson": str(schema_path),
            "appName": app_name,
            "summary": str(raw.get("summary", "")).strip(),
            "proposals": current_proposals,
            "notes": [str(x).strip() for x in raw.get("notes", []) if str(x).strip()] if isinstance(raw.get("notes"), list) else [],
            "feedbackHistory": feedback_history,
            "runtime": {
                "app": runtime_app,
                "selectedSection": selected_section,
            },
        }
        draft_path = save_round_snapshot(app_id, round_no, round_payload)
        append_log(log_path, "round_snapshot_saved", round=round_no, path=str(draft_path))

        print("\n本轮候选方案：")
        print(json.dumps(round_payload, ensure_ascii=False, indent=2))
        if args.auto:
            print("\n[auto] 自动确认首轮生成方案（--auto）")
            user_text = "/done"
        else:
            user_text = input("\n输入 /done 确认；直接输入反馈继续调整；回车则重新随机生成: ").strip()
        if user_text == "/done":
            final_payload = {
                "schemaVersion": "chatbot_plan_v1",
                "approvedAt": now_iso(),
                "model": model_name,
                "sourceSchemaJson": str(schema_path),
                "appName": app_name,
                "summary": round_payload["summary"],
                "proposals": current_proposals,
                "notes": round_payload["notes"],
                "feedbackHistory": feedback_history,
                "runtime": {
                    "app": runtime_app,
                    "selectedSection": selected_section,
                },
            }
            if args.output:
                output_path = Path(args.output).expanduser().resolve()
            else:
                output_path = (CHATBOT_PLAN_DIR / f"chatbot_plan_{app_id}.json").resolve()
            write_json_with_latest(
                CHATBOT_PLAN_DIR,
                output_path,
                "chatbot_plan_latest.json",
                final_payload,
            )
            append_log(log_path, "approved", output=str(output_path), proposalCount=len(current_proposals))
            print("\n已确认，输出 JSON：")
            print(json.dumps(final_payload, ensure_ascii=False, indent=2))
            print(f"\n结果文件: {output_path}")
            print(f"日志文件: {log_path}")
            print(f"RESULT_JSON: {output_path}")
            print(f"LOG_FILE: {log_path}")
            return

        feedback_history.append({"round": round_no, "feedback": user_text or "请重新随机生成一版，保持业务相关。"})
        append_log(log_path, "user_feedback", round=round_no, feedback=feedback_history[-1]["feedback"])
        round_no += 1


if __name__ == "__main__":
    main()
