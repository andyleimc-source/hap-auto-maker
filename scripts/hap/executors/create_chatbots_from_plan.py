#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据已确认的 chatbot plan，请求接口批量创建对话机器人。
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

from chatbot_common import (
    ADD_WORKSHEET_URL,
    CHATBOT_CREATE_DIR,
    GENERATE_CHATBOT_INFO_URL,
    SAVE_CHATBOT_CONFIG_URL,
    append_log,
    ensure_chatbot_dirs,
    ensure_state_success,
    ensure_status_success,
    load_plan_json,
    make_chatbot_log_path,
    now_iso,
    pick_icon_bundle,
    post_json,
    write_json_with_latest,
)


BASE_DIR = Path(__file__).resolve().parents[2]
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"


def build_referer(app_id: str, app_section_id: str) -> str:
    return f"https://www.mingdao.com/app/{app_id}/{app_section_id}"


def call_generate_chatbot_info(app_id: str, description: str, auth_config_path: Path, referer: str) -> dict:
    payload = {
        "appId": app_id,
        "type": 2,
        "robotDescription": description,
        "langType": 0,
        "hasIcon": True,
    }
    data = post_json(GENERATE_CHATBOT_INFO_URL, payload, auth_config_path, referer=referer)
    ensure_state_success(data, "GenerateChatRobotInfo")
    return {"payload": payload, "response": data}


def call_add_chatbot(
    app_id: str,
    app_section_id: str,
    project_id: str,
    proposal: dict,
    prompt: str,
    icon_bundle: dict,
    auth_config_path: Path,
    referer: str,
) -> dict:
    payload = {
        "appId": app_id,
        "appSectionId": app_section_id,
        "name": proposal["name"],
        "remark": proposal["description"],
        "iconColor": icon_bundle["iconColor"],
        "projectId": project_id,
        "icon": icon_bundle["icon"],
        "iconUrl": icon_bundle["iconUrl"],
        "type": 3,
        "prompt": prompt,
    }
    data = post_json(ADD_WORKSHEET_URL, payload, auth_config_path, referer=referer)
    ensure_state_success(data, "AddWorkSheet")
    chatbot_id = str((data.get("data") or {}).get("chatbotId", "")).strip()
    if not chatbot_id:
        raise RuntimeError(f"AddWorkSheet 未返回 chatbotId: {data}")
    return {"payload": payload, "response": data, "chatbotId": chatbot_id}


def call_save_chatbot_config(
    chatbot_id: str,
    proposal: dict,
    generated: dict,
    upload_permission: str,
    auth_config_path: Path,
    referer: str,
) -> dict:
    generated_data = generated.get("response", {}).get("data", {}) if isinstance(generated.get("response"), dict) else {}
    greeting = str(generated_data.get("greeting", "")).strip() or f"您好，我是{proposal['name']}。"
    suggested_questions = generated_data.get("suggestedQuestions", [])
    preset_question = "\n".join(
        [str(item).strip() for item in suggested_questions if str(item).strip()]
    )
    payload = {
        "chatbotId": chatbot_id,
        "name": proposal["name"],
        "welcomeText": greeting,
        "presetQuestion": preset_question,
        "uploadPermission": upload_permission,
    }
    data = post_json(SAVE_CHATBOT_CONFIG_URL, payload, auth_config_path, referer=referer)
    ensure_status_success(data, "saveChatbotConfig")
    return {"payload": payload, "response": data}


def main() -> None:
    parser = argparse.ArgumentParser(description="根据 chatbot plan 批量创建对话机器人")
    parser.add_argument("--plan-json", default="", help="chatbot plan JSON 路径（默认使用 latest）")
    parser.add_argument("--upload-permission", default="11", help="上传权限，默认 11")
    parser.add_argument("--dry-run", action="store_true", help="仅生成请求计划，不真正创建")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    ensure_chatbot_dirs()
    plan_path = Path(args.plan_json).expanduser().resolve() if args.plan_json else (CHATBOT_CREATE_DIR.parent / "plans" / "chatbot_plan_latest.json").resolve()
    plan = load_plan_json(plan_path)
    runtime = plan.get("runtime", {})
    if not isinstance(runtime, dict):
        raise ValueError("plan.runtime 缺失，无法创建机器人")
    app = runtime.get("app", {})
    if not isinstance(app, dict):
        raise ValueError("plan.runtime.app 缺失，无法创建机器人")
    app_id = str(app["appId"]).strip()
    app_name = str(plan.get("appName", "")).strip() or str(app["appName"]).strip()
    app_section = runtime.get("selectedSection", {})
    if not isinstance(app_section, dict):
        raise ValueError("plan.runtime.selectedSection 缺失，无法创建机器人")
    app_section_id = str(app_section["appSectionId"]).strip()
    project_id = str(app.get("projectId", "")).strip()
    if not project_id:
        raise ValueError("plan.app.projectId 为空，无法创建机器人")

    log_path = make_chatbot_log_path("chatbot_create", app_id)
    append_log(
        log_path,
        "start",
        planJson=str(plan_path),
        appId=app_id,
        appName=app_name,
        dryRun=bool(args.dry_run),
        targetSection=app_section_id,
    )

    referer = build_referer(app_id, app_section_id)
    results: List[dict] = []
    ok_count = 0
    fail_count = 0
    for idx, proposal in enumerate(plan.get("proposals", []), start=1):
        seed = f"{proposal['name']}::{proposal['description']}"
        icon_bundle = pick_icon_bundle(seed)
        item_result: Dict[str, Any] = {
            "index": idx,
            "proposal": proposal,
            "icon": icon_bundle,
        }
        append_log(log_path, "proposal_start", index=idx, name=proposal["name"])
        try:
            if args.dry_run:
                item_result["ok"] = True
                item_result["dryRunPlan"] = {
                    "generateChatRobotInfo": {
                        "appId": app_id,
                        "type": 2,
                        "robotDescription": proposal["description"],
                        "langType": 0,
                        "hasIcon": True,
                    },
                    "addWorkSheet": {
                        "appId": app_id,
                        "appSectionId": app_section_id,
                        "name": proposal["name"],
                        "remark": proposal["description"],
                        "iconColor": icon_bundle["iconColor"],
                        "projectId": project_id,
                        "icon": icon_bundle["icon"],
                        "iconUrl": icon_bundle["iconUrl"],
                        "type": 3,
                        "prompt": proposal["description"],
                    },
                    "saveChatbotConfig": {
                        "name": proposal["name"],
                        "uploadPermission": args.upload_permission,
                    },
                }
                ok_count += 1
                append_log(log_path, "proposal_finished", index=idx, name=proposal["name"], dryRun=True)
                results.append(item_result)
                continue

            generated = call_generate_chatbot_info(
                app_id, proposal["description"], AUTH_CONFIG_PATH, referer=referer
            )
            generated_data = generated["response"].get("data", {}) if isinstance(generated["response"], dict) else {}
            prompt = str(generated_data.get("systemPrompt", "")).strip() or proposal["description"]
            item_result["generated"] = generated

            add_chatbot = call_add_chatbot(
                app_id=app_id,
                app_section_id=app_section_id,
                project_id=project_id,
                proposal=proposal,
                prompt=prompt,
                icon_bundle=icon_bundle,
                auth_config_path=AUTH_CONFIG_PATH,
                referer=referer,
            )
            item_result["create"] = add_chatbot

            save_config = call_save_chatbot_config(
                chatbot_id=add_chatbot["chatbotId"],
                proposal=proposal,
                generated=generated,
                upload_permission=args.upload_permission,
                auth_config_path=AUTH_CONFIG_PATH,
                referer=referer,
            )
            item_result["config"] = save_config
            item_result["ok"] = True
            ok_count += 1
            append_log(log_path, "proposal_finished", index=idx, name=proposal["name"], chatbotId=add_chatbot["chatbotId"])
        except Exception as exc:
            item_result["ok"] = False
            item_result["error"] = str(exc)
            fail_count += 1
            append_log(log_path, "proposal_failed", index=idx, name=proposal["name"], error=str(exc))
        results.append(item_result)

    result = {
        "schemaVersion": "chatbot_create_result_v1",
        "generatedAt": now_iso(),
        "sourcePlanJson": str(plan_path),
        "app": app,
        "selectedSection": app_section,
        "dryRun": bool(args.dry_run),
        "summary": {
            "proposalCount": len(results),
            "successCount": ok_count,
            "failedCount": fail_count,
        },
        "results": results,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = (CHATBOT_CREATE_DIR / f"chatbot_create_result_{app_id}.json").resolve()
    write_json_with_latest(
        CHATBOT_CREATE_DIR,
        output_path,
        "chatbot_create_result_latest.json",
        result,
    )
    append_log(log_path, "finished", output=str(output_path), successCount=ok_count, failedCount=fail_count)

    print("对话机器人创建流程完成")
    print(f"- 应用: {app_name} ({app_id})")
    print(f"- 分组: {app_section['name']} ({app_section_id})")
    print(f"- 方案数量: {len(results)}")
    print(f"- 成功: {ok_count}")
    print(f"- 失败: {fail_count}")
    print(f"- 结果文件: {output_path}")
    print(f"- 日志文件: {log_path}")
    print(f"RESULT_JSON: {output_path}")
    print(f"LOG_FILE: {log_path}")
    if not args.dry_run and fail_count > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
