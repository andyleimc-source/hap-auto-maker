#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按应用名/工作表名执行角色规划、角色写入，并可选接入 run_app_to_video.py 做校验。

每一步都会在单次运行目录中留下：
1) 结构化输入/输出 JSON
2) 子命令 stdout/stderr 日志
3) 流水线总报告与 JSONL 事件日志
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import (
    DEFAULT_BASE_URL,
    OUTPUT_ROOT,
    append_log,
    choose_app,
    discover_authorized_apps,
    ensure_dir,
    fetch_app_worksheets,
    load_json,
    sanitize_name,
    write_json,
)

PLAN_SCRIPT = CURRENT_DIR / "plan_role_recommendations_gemini.py"
CREATE_SCRIPT = CURRENT_DIR / "create_roles_from_recommendation.py"
APP_VIDEO_SCRIPT = CURRENT_DIR / "run_app_to_video.py"
APP_ROLE_RUN_DIR = OUTPUT_ROOT / "app_role_runs"
APP_ROLE_RUN_LATEST = APP_ROLE_RUN_DIR / "app_role_run_latest.json"
EXECUTION_RUN_LATEST = OUTPUT_ROOT / "execution_runs" / "execution_run_latest.json"
APP_VIDEO_RUNS_DIR = OUTPUT_ROOT / "app_video_runs"
DEFAULT_MODEL = "gemini-2.5-flash"
VIDEO_MODE_SKIP = "skip"
VIDEO_MODE_RESUME_LATEST = "resume-latest"


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def choose_app_by_name(apps: List[dict], app_name: str) -> dict:
    target = app_name.strip()
    if not target:
        raise ValueError("应用名称不能为空")
    matched = [app for app in apps if str(app.get("appName", "")).strip() == target]
    if not matched:
        raise ValueError(f"未找到应用名称={target}")
    if len(matched) > 1:
        app_ids = ", ".join(str(app.get("appId", "")).strip() for app in matched)
        raise ValueError(f"应用名称重复，请改用 --app-id 指定。appName={target}, appIds={app_ids}")
    return matched[0]


def resolve_app(apps: List[dict], app_id: str = "", app_name: str = "", app_index: int = 0) -> dict:
    if app_id.strip():
        return choose_app(apps, app_id=app_id.strip(), app_index=0)
    if app_name.strip():
        return choose_app_by_name(apps, app_name.strip())
    return choose_app(apps, app_id="", app_index=app_index)


def normalize_worksheet_names(values: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in values:
        for piece in str(raw or "").split(","):
            name = piece.strip()
            if not name or name in seen:
                continue
            out.append(name)
            seen.add(name)
    return out


def select_worksheets(all_names: List[str], requested_names: List[str]) -> List[str]:
    if not requested_names:
        return all_names
    available = {name: name for name in all_names}
    missing = [name for name in requested_names if name not in available]
    if missing:
        raise ValueError(f"以下工作表不存在于应用中: {missing}")
    return [available[name] for name in requested_names]


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def extract_marker_path(output: str, marker: str) -> str:
    for line in reversed((output or "").splitlines()):
        text = line.strip()
        if text.startswith(marker):
            return text.split(":", 1)[1].strip()
    return ""


def run_step(
    *,
    step_no: int,
    step_key: str,
    title: str,
    cmd: List[str],
    cwd: Path,
    run_dir: Path,
    pipeline_log: Path,
) -> Dict[str, Any]:
    started_at = now_iso()
    print(f"\n== Step {step_no}: {title} ==")
    print("命令:", " ".join(cmd))
    append_log(pipeline_log, "step_start", step=step_key, title=title, cmd=cmd, cwd=str(cwd))
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    ended_at = now_iso()

    log_dir = ensure_dir(run_dir / "logs")
    stdout_log = write_text(log_dir / f"{step_no:02d}_{step_key}.stdout.log", proc.stdout or "")
    stderr_log = write_text(log_dir / f"{step_no:02d}_{step_key}.stderr.log", proc.stderr or "")
    result = {
        "step": step_key,
        "title": title,
        "cmd": cmd,
        "cwd": str(cwd),
        "startedAt": started_at,
        "endedAt": ended_at,
        "returncode": proc.returncode,
        "stdoutLog": str(stdout_log.resolve()),
        "stderrLog": str(stderr_log.resolve()),
        "stdoutTail": (proc.stdout or "")[-4000:],
        "stderrTail": (proc.stderr or "")[-4000:],
        "markers": {
            "resultJson": extract_marker_path(proc.stdout or "", "RESULT_JSON"),
            "logFile": extract_marker_path(proc.stdout or "", "LOG_FILE"),
        },
    }

    step_result_path = run_dir / f"{step_no:02d}_{step_key}_step_result.json"
    write_json(step_result_path, result)
    append_log(
        pipeline_log,
        "step_finished",
        step=step_key,
        title=title,
        returncode=proc.returncode,
        stepResultJson=str(step_result_path.resolve()),
        stdoutLog=str(stdout_log.resolve()),
        stderrLog=str(stderr_log.resolve()),
    )

    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr.strip():
            print(proc.stderr.strip())
        raise RuntimeError(f"{title} 失败，退出码={proc.returncode}")
    return result


def latest_run_dir_after(before: List[Path]) -> Optional[Path]:
    before_set = {item.resolve() for item in before}
    after = sorted(APP_VIDEO_RUNS_DIR.glob("*"), key=lambda p: p.stat().st_mtime)
    new_dirs = [item.resolve() for item in after if item.resolve() not in before_set]
    if new_dirs:
        return new_dirs[-1]
    if after:
        return after[-1].resolve()
    return None


def prepare_video_step_result(
    *,
    mode: str,
    app: dict,
    request_path: Path,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "schemaVersion": "app_role_video_request_v1",
        "generatedAt": now_iso(),
        "videoMode": mode,
        "app": {"appId": app["appId"], "appName": app["appName"]},
        "requestJson": str(request_path.resolve()),
    }
    if mode == VIDEO_MODE_SKIP:
        result.update({"status": "skipped", "reason": "video_mode=skip"})
        return result

    if not EXECUTION_RUN_LATEST.exists():
        result.update(
            {
                "status": "skipped",
                "reason": f"缺少最新 execution report，无法对接 {APP_VIDEO_SCRIPT.name}: {EXECUTION_RUN_LATEST}",
            }
        )
        return result

    execution_data = load_json(EXECUTION_RUN_LATEST)
    context = execution_data.get("context") if isinstance(execution_data.get("context"), dict) else {}
    latest_app_id = str(context.get("app_id", "")).strip()
    if latest_app_id != str(app.get("appId", "")).strip():
        result.update(
            {
                "status": "skipped",
                "reason": (
                    "run_app_to_video.py 目前只能基于 --resume-latest 继续最近一次应用执行结果，"
                    f"最近执行的 app_id={latest_app_id or '空'}，目标 app_id={app['appId']}。"
                ),
                "latestExecutionRun": str(EXECUTION_RUN_LATEST.resolve()),
            }
        )
        return result

    result.update(
        {
            "status": "pending",
            "latestExecutionRun": str(EXECUTION_RUN_LATEST.resolve()),
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="按应用名/工作表名生成并写入角色，可选接入视频校验")
    parser.add_argument("--app-id", default="", help="可选，按 appId 定位应用")
    parser.add_argument("--app-name", default="", help="可选，按应用名称精确定位应用")
    parser.add_argument("--app-index", type=int, default=0, help="可选，按应用序号定位")
    parser.add_argument(
        "--worksheet-name",
        action="append",
        default=[],
        help="可选，限制参与角色规划的工作表名称。可重复传入，也可使用逗号分隔。",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型")
    parser.add_argument("--config", default="", help="Gemini 配置 JSON 路径")
    parser.add_argument("--skip-existing", action="store_true", default=True, help="角色已存在时跳过（默认启用）")
    parser.add_argument("--no-skip-existing", dest="skip_existing", action="store_false", help="角色已存在时仍尝试创建")
    parser.add_argument(
        "--video-mode",
        choices=[VIDEO_MODE_SKIP, VIDEO_MODE_RESUME_LATEST],
        default=VIDEO_MODE_SKIP,
        help="是否在角色写入后接入 run_app_to_video.py 做校验",
    )
    args = parser.parse_args()

    apps = discover_authorized_apps(base_url=args.base_url)
    app = resolve_app(apps, app_id=args.app_id, app_name=args.app_name, app_index=args.app_index)
    requested_worksheet_names = normalize_worksheet_names(args.worksheet_name)

    app_meta, worksheets = fetch_app_worksheets(
        base_url=args.base_url,
        app_key=app["appKey"],
        sign=app["sign"],
    )
    all_worksheet_names = sorted(
        {
            str(item.get("worksheetName", "")).strip()
            for item in worksheets
            if str(item.get("worksheetName", "")).strip()
        }
    )
    selected_worksheet_names = select_worksheets(all_worksheet_names, requested_worksheet_names)

    run_id = f"app_role_run_{sanitize_name(app['appId'])}_{now_ts()}"
    run_dir = ensure_dir(APP_ROLE_RUN_DIR / run_id)
    pipeline_log = run_dir / "pipeline.jsonl"
    append_log(
        pipeline_log,
        "start",
        appId=app["appId"],
        appName=app["appName"],
        requestedWorksheetNames=requested_worksheet_names,
        selectedWorksheetNames=selected_worksheet_names,
        model=args.model,
        videoMode=args.video_mode,
    )

    artifacts_dir = ensure_dir(run_dir / "artifacts")
    context_json = artifacts_dir / "01_scope.json"
    worksheet_inventory_json = artifacts_dir / "02_worksheet_inventory.json"
    role_prompt_txt = artifacts_dir / "02_role_prompt.txt"
    role_raw_txt = artifacts_dir / "02_gemini_raw_response.txt"
    role_plan_json = artifacts_dir / "02_role_plan.json"
    role_create_result_json = artifacts_dir / "03_role_create_result.json"
    video_request_json = artifacts_dir / "04_video_request.json"
    video_result_json = artifacts_dir / "04_video_result.json"

    context_payload = {
        "schemaVersion": "app_role_scope_v1",
        "generatedAt": now_iso(),
        "app": {
            "appId": app["appId"],
            "appName": str(app_meta.get("name", "")).strip() or app["appName"],
            "authFile": app.get("authFile", ""),
        },
        "selectionMode": "manual" if requested_worksheet_names else "all",
        "requestedWorksheetNames": requested_worksheet_names,
        "selectedWorksheetNames": selected_worksheet_names,
        "allWorksheetNames": all_worksheet_names,
        "videoMode": args.video_mode,
        "model": args.model,
    }
    write_json(context_json, context_payload)
    context_step = {
        "step": "resolve_scope",
        "title": "解析应用与工作表范围",
        "startedAt": now_iso(),
        "endedAt": now_iso(),
        "artifacts": {
            "scopeJson": str(context_json.resolve()),
        },
        "logSource": str(pipeline_log.resolve()),
    }
    write_json(run_dir / "01_resolve_scope_step_result.json", context_step)

    report: Dict[str, Any] = {
        "schemaVersion": "app_role_pipeline_run_v1",
        "createdAt": now_iso(),
        "runDir": str(run_dir.resolve()),
        "pipelineLog": str(pipeline_log.resolve()),
        "app": context_payload["app"],
        "selectionMode": context_payload["selectionMode"],
        "requestedWorksheetNames": requested_worksheet_names,
        "selectedWorksheetNames": selected_worksheet_names,
        "videoMode": args.video_mode,
        "steps": [],
        "artifacts": {
            "scopeJson": str(context_json.resolve()),
        },
        "ok": False,
    }
    report["steps"].append(context_step)

    try:
        plan_cmd = [
            sys.executable,
            str(PLAN_SCRIPT.resolve()),
            "--app-id",
            app["appId"],
            "--base-url",
            args.base_url,
            "--model",
            args.model,
            "--output",
            str(role_plan_json.resolve()),
            "--inventory-output",
            str(worksheet_inventory_json.resolve()),
            "--prompt-output",
            str(role_prompt_txt.resolve()),
            "--raw-output",
            str(role_raw_txt.resolve()),
        ]
        if args.config:
            plan_cmd.extend(["--config", args.config])
        for worksheet_name in selected_worksheet_names:
            plan_cmd.extend(["--worksheet-name", worksheet_name])
        plan_step = run_step(
            step_no=2,
            step_key="plan_roles",
            title="生成角色规划 JSON",
            cmd=plan_cmd,
            cwd=CURRENT_DIR,
            run_dir=run_dir,
            pipeline_log=pipeline_log,
        )
        plan_step["artifacts"] = {
            "inventoryJson": str(worksheet_inventory_json.resolve()),
            "promptText": str(role_prompt_txt.resolve()),
            "rawResponseText": str(role_raw_txt.resolve()),
            "planJson": str(role_plan_json.resolve()),
        }
        write_json(run_dir / "02_plan_roles_step_result.json", plan_step)
        report["steps"].append(plan_step)
        report["artifacts"].update(plan_step["artifacts"])

        create_cmd = [
            sys.executable,
            str(CREATE_SCRIPT.resolve()),
            "--plan-json",
            str(role_plan_json.resolve()),
            "--app-id",
            app["appId"],
            "--base-url",
            args.base_url,
            "--output",
            str(role_create_result_json.resolve()),
        ]
        if args.skip_existing:
            create_cmd.append("--skip-existing")
        else:
            create_cmd.append("--no-skip-existing")
        create_step = run_step(
            step_no=3,
            step_key="create_roles",
            title="把规划角色写入应用",
            cmd=create_cmd,
            cwd=CURRENT_DIR,
            run_dir=run_dir,
            pipeline_log=pipeline_log,
        )
        create_step["artifacts"] = {
            "createResultJson": str(role_create_result_json.resolve()),
        }
        write_json(run_dir / "03_create_roles_step_result.json", create_step)
        report["steps"].append(create_step)
        report["artifacts"].update(create_step["artifacts"])

        video_request = prepare_video_step_result(mode=args.video_mode, app=app, request_path=video_request_json)
        write_json(video_request_json, video_request)
        report["artifacts"]["videoRequestJson"] = str(video_request_json.resolve())

        if video_request.get("status") == "pending":
            before_video_dirs = list(APP_VIDEO_RUNS_DIR.glob("*")) if APP_VIDEO_RUNS_DIR.exists() else []
            video_cmd = [sys.executable, str(APP_VIDEO_SCRIPT.resolve()), "--resume-latest"]
            video_step = run_step(
                step_no=4,
                step_key="app_to_video",
                title="调用 run_app_to_video.py 做应用校验",
                cmd=video_cmd,
                cwd=CURRENT_DIR,
                run_dir=run_dir,
                pipeline_log=pipeline_log,
            )
            latest_video_dir = latest_run_dir_after(before_video_dirs)
            video_payload = {
                **video_request,
                "status": "success",
                "videoRunDir": str(latest_video_dir.resolve()) if latest_video_dir else "",
                "stdoutLog": video_step["stdoutLog"],
                "stderrLog": video_step["stderrLog"],
            }
            write_json(video_result_json, video_payload)
            video_step["artifacts"] = {
                "videoResultJson": str(video_result_json.resolve()),
                "videoRunDir": video_payload["videoRunDir"],
            }
            report["steps"].append(video_step)
            report["artifacts"].update(video_step["artifacts"])
        else:
            write_json(video_result_json, video_request)
            report["steps"].append(
                {
                    "step": "app_to_video",
                    "title": "调用 run_app_to_video.py 做应用校验",
                    "skipped": True,
                    "reason": video_request.get("reason", ""),
                    "artifacts": {
                        "videoResultJson": str(video_result_json.resolve()),
                    },
                }
            )
            report["artifacts"]["videoResultJson"] = str(video_result_json.resolve())
            append_log(
                pipeline_log,
                "step_skipped",
                step="app_to_video",
                reason=video_request.get("reason", ""),
                videoResultJson=str(video_result_json.resolve()),
            )

        report["ok"] = True
        append_log(pipeline_log, "pipeline_succeeded", artifacts=report["artifacts"])
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        append_log(pipeline_log, "pipeline_failed", error=str(exc), artifacts=report.get("artifacts", {}))

    report_path = run_dir / "pipeline_report.json"
    write_json(report_path, report)
    write_json(APP_ROLE_RUN_LATEST.resolve(), report)
    append_log(pipeline_log, "finished", ok=report.get("ok", False), reportJson=str(report_path.resolve()))

    print("\n应用角色流水线执行结束")
    print(f"- 应用: {report['app']['appName']} ({report['app']['appId']})")
    print(f"- 状态: {'成功' if report.get('ok') else '失败'}")
    print(f"- 运行目录: {run_dir}")
    print(f"- 报告文件: {report_path}")
    print(f"- 日志文件: {pipeline_log}")
    print(f"RESULT_JSON: {report_path}")
    print(f"LOG_FILE: {pipeline_log}")
    if not report.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
