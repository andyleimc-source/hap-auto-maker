#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
串行创建验证：
仅执行创建应用 + 规划工作表 + 创建工作表，
用于验证应用能否成功创建且工作表数量满足下限要求。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "outputs" / "stability_runs"
SPEC_DIR = BASE_DIR / "data" / "outputs" / "creation_specs"
EXECUTE_CMD = [sys.executable, "scripts/hap/execute_requirements.py"]
EXECUTION_RUN_LATEST = BASE_DIR / "data" / "outputs" / "execution_runs" / "execution_run_latest.json"

CASES: List[Dict[str, str]] = [
    {
        "app_name": "大型集团企业运营管理应用",
        "prompt": "请创建一个大型集团企业运营管理应用，覆盖人事、行政、采购、资产、合同、培训、费用、车辆、会议、公告、印章、宿舍、访客、档案、值班、证照、供应商、工单、巡检、报表等场景，要求工作表不少于20张，并保持真实企业管理逻辑。",
    },
    {
        "app_name": "制造企业数字化管理应用",
        "prompt": "请创建一个制造企业数字化管理应用，覆盖设备台账、点检计划、保养计划、备件库存、采购申请、供应商管理、来料检验、生产排程、工单、质检、不良处理、出货、仓储、盘点、能耗、安全检查、隐患整改、培训、维修、统计分析等场景，要求工作表不少于20张。",
    },
    {
        "app_name": "连锁零售企业运营中台应用",
        "prompt": "请创建一个连锁零售企业运营中台应用，覆盖门店档案、商品资料、价格策略、库存调拨、盘点任务、巡店检查、陈列整改、促销活动、会员运营、客诉工单、供应商协同、采购订单、收货验收、报损、值班排班、培训考试、费用报销、合同台账、证照年检、经营报表等场景，要求工作表不少于20张。",
    },
    {
        "app_name": "项目制企业综合管理应用",
        "prompt": "请创建一个项目制企业综合管理应用，覆盖客户档案、商机、合同、项目立项、预算评审、资源分配、任务分解、工时填报、里程碑、风险问题、变更申请、采购需求、付款计划、开票记录、验收、回款、知识库、培训、绩效、复盘等场景，要求工作表不少于20张。",
    },
    {
        "app_name": "物业园区企业综合运营应用",
        "prompt": "请创建一个物业园区企业综合运营应用，覆盖楼栋档案、房源档案、租户档案、合同、收费计划、账单、缴费记录、报修工单、巡检任务、保洁排班、安保排班、访客登记、车辆放行、物资采购、仓库库存、固定资产、能耗抄表、活动场地预订、公告通知、满意度回访、统计报表等场景，要求工作表不少于20张。",
    },
]


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_spec(case: Dict[str, str]) -> Dict[str, Any]:
    prompt = case["prompt"]
    return {
        "schema_version": "workflow_requirement_v1",
        "meta": {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": "serial_creation_runner",
            "conversation_summary": prompt[:100],
        },
        "app": {
            "target_mode": "create_new",
            "name": case["app_name"],
            "group_ids": "",
            "icon_mode": "gemini_match",
            "color_mode": "random",
            "navi_style": {
                "enabled": False,
                "pcNaviStyle": 1,
            },
        },
        "worksheets": {
            "enabled": True,
            "business_context": prompt,
            "requirements": "工作表不少于20张",
            "icon_update": {
                "enabled": False,
                "refresh_auth": False,
            },
            "layout": {
                "enabled": False,
                "requirements": "",
                "refresh_auth": False,
            },
        },
        "views": {"enabled": False},
        "roles": {"enabled": False},
        "view_filters": {"enabled": False},
        "mock_data": {
            "enabled": False,
            "dry_run": False,
            "trigger_workflow": False,
        },
        "chatbots": {"enabled": False, "auto": False, "dry_run": False},
        "workflows": {
            "enabled": False,
            "thinking": "none",
            "no_publish": True,
            "skip_analysis": True,
        },
        "delete_default_views": {"enabled": False, "refresh_auth": False},
        "pages": {"enabled": False},
        "execution": {
            "fail_fast": True,
            "dry_run": False,
        },
    }


def read_created_worksheet_count(execution_report: Dict[str, Any]) -> int:
    context = execution_report.get("context") if isinstance(execution_report.get("context"), dict) else {}
    result_path = str(context.get("worksheet_create_result_json", "")).strip()
    if not result_path or result_path == "None":
        return 0
    create_result = load_json(Path(result_path))
    created = create_result.get("created_worksheets", [])
    return len(created) if isinstance(created, list) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="串行验证 5 个 20+ 工作表应用的创建流程")
    parser.add_argument("--start-index", type=int, default=1, help="从第几个 case 开始（1-based）")
    parser.add_argument("--count", type=int, default=5, help="执行多少个 case")
    args = parser.parse_args()

    ensure_dir(OUTPUT_DIR)
    ensure_dir(SPEC_DIR)

    run_id = now_ts()
    result_path = OUTPUT_DIR / f"creation_run_{run_id}.json"
    results: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cases": [],
        "status": "running",
    }
    write_json(result_path, results)

    selected = CASES[args.start_index - 1: args.start_index - 1 + args.count]
    for offset, case in enumerate(selected, start=args.start_index):
        started = time.time()
        spec = build_spec(case)
        spec_path = SPEC_DIR / f"creation_spec_case_{offset}_{now_ts()}.json"
        write_json(spec_path, spec)

        cmd = EXECUTE_CMD + ["--spec-json", str(spec_path), "--only-steps", "1,2"]
        print(f"\n===== CASE {offset} / {len(CASES)} 开始 =====", flush=True)
        print(case["prompt"], flush=True)
        proc = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            check=False,
        )

        execution_report: Dict[str, Any] = {}
        worksheet_count = 0
        app_id = ""
        if EXECUTION_RUN_LATEST.exists() and EXECUTION_RUN_LATEST.stat().st_mtime >= started - 1:
            execution_report = load_json(EXECUTION_RUN_LATEST)
            context = execution_report.get("context") if isinstance(execution_report.get("context"), dict) else {}
            app_id = str(context.get("app_id", "")).strip()
            worksheet_count = read_created_worksheet_count(execution_report)

        case_result = {
            "index": offset,
            "app_name": case["app_name"],
            "prompt": case["prompt"],
            "spec_json": str(spec_path),
            "duration_seconds": round(time.time() - started, 3),
            "returncode": proc.returncode,
            "app_id": app_id,
            "worksheet_count": worksheet_count,
            "stdout_tail": ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else ""))[-12000:],
        }

        if proc.returncode == 0 and worksheet_count < 20:
            case_result["returncode"] = 100
            case_result["validation_error"] = f"工作表数量不达标: 实际 {worksheet_count} 张"

        results["cases"].append(case_result)
        write_json(result_path, results)

        if case_result["returncode"] != 0:
            results["status"] = "failed"
            results["failed_index"] = offset
            results["ended_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            write_json(result_path, results)
            print(f"CASE {offset} 失败，已停止。结果文件: {result_path}", flush=True)
            return int(case_result["returncode"])

        print(f"CASE {offset} 成功，工作表 {worksheet_count} 张", flush=True)

    results["status"] = "completed"
    results["ended_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json(result_path, results)
    print(f"\n全部完成，结果文件: {result_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
