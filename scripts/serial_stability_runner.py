#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
串行稳定性回归：
按顺序调用 `python3 scripts/run_app_pipeline.py --requirements-text ...`，
记录每轮执行结果；遇到失败立即停止，方便修复后从指定下标继续。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "data" / "outputs" / "stability_runs"
PIPELINE_CMD = [sys.executable, "scripts/run_app_pipeline.py"]

PROMPTS: List[str] = [
    "请创建一个企业行政管理应用，包含员工档案、固定资产、办公用品申领、会议室预订、行政公告等模块，要求适合中型企业日常运营管理。",
    "请创建一个企业采购审批应用，包含供应商名录、采购申请、采购订单三个核心模块，适合一般企业内部采购流程。",
    "请创建一个企业招聘管理应用，包含招聘需求、候选人台账、面试安排三个核心模块，适合人事部门日常招聘协作。",
    "请创建一个企业培训管理应用，包含培训计划、培训课程、培训签到三个核心模块，适合内部培训运营。",
    "请创建一个企业合同管理应用，包含客户合同、付款节点、续约提醒三个核心模块，适合法务和销售协作。",
    "请创建一个企业售后工单应用，包含客户档案、售后工单、处理回访三个核心模块，适合服务团队管理。",
    "请创建一个企业费用报销应用，包含报销单、费用科目、审批记录三个核心模块，适合财务审批流程。",
    "请创建一个企业车辆管理应用，包含车辆档案、用车申请、维修保养三个核心模块，适合行政车队管理。",
    "请创建一个企业仓库盘点应用，包含物料台账、盘点任务、差异处理三个核心模块，适合基础仓储管理。",
    "请创建一个企业客户拜访管理应用，包含客户名单、拜访计划、拜访记录三个核心模块，适合销售外勤管理。",
]


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def extract(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_summary(output: str) -> Dict[str, Any]:
    raw_url = extract(r"应用地址\s+(https://\S+)", output)
    return {
        "app_name": extract(r"✓ 运行完成\s+(.+?)\s+│", output),
        "app_url": raw_url.rstrip("│"),
        "worksheet_count": extract(r"工作表\s+(\d+)\s+张", output),
        "view_count": extract(r"视图\s+(\d+)\s+个", output),
        "workflow_count": extract(r"工作流\s+(\d+)\s+个", output),
        "duration_human": extract(r"总耗时\s+([0-9A-Za-z :msh]+)\s+│", output),
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="串行执行 10 个企业管理应用稳定性用例")
    parser.add_argument("--start-index", type=int, default=1, help="从第几个 case 开始（1-based）")
    parser.add_argument("--count", type=int, default=10, help="最多执行多少个 case")
    args = parser.parse_args()

    if args.start_index < 1:
        raise SystemExit("--start-index 必须 >= 1")

    ensure_dir(OUTPUT_DIR)
    run_id = now_ts()
    result_path = OUTPUT_DIR / f"stability_run_{run_id}.json"
    results: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.executable,
        "cases": [],
        "status": "running",
    }
    write_json(result_path, results)

    selected = PROMPTS[args.start_index - 1 : args.start_index - 1 + args.count]
    for offset, prompt in enumerate(selected, start=args.start_index):
        started = time.time()
        case_started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        cmd = PIPELINE_CMD + ["--requirements-text", prompt]
        print(f"\n===== CASE {offset} / {len(PROMPTS)} 开始 =====", flush=True)
        print(prompt, flush=True)
        proc = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        combined_output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        case_result = {
            "index": offset,
            "prompt": prompt,
            "started_at": case_started_at,
            "duration_seconds": round(time.time() - started, 3),
            "returncode": proc.returncode,
            "summary": parse_summary(combined_output),
            "stdout_tail": combined_output[-12000:],
        }
        results["cases"].append(case_result)
        write_json(result_path, results)

        if proc.returncode != 0:
            print(f"CASE {offset} 失败，已停止。结果文件: {result_path}", flush=True)
            results["status"] = "failed"
            results["failed_index"] = offset
            results["ended_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            write_json(result_path, results)
            return proc.returncode

        print(f"CASE {offset} 成功", flush=True)

    results["status"] = "completed"
    results["ended_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_json(result_path, results)
    print(f"\n全部完成，结果文件: {result_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
