"""
通用步骤执行工具：run_cmd（子进程执行）和 execute_step（带报告和信号量的步骤封装）。
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
_HAP_DIR = Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_DIR))

from utils import now_iso


def run_cmd(cmd: List[str], dry_run: bool, verbose: bool) -> Dict[str, Any]:
    """执行子命令，实时流式输出，返回 {returncode, stdout, stderr, ...}。"""
    cmd_text = " ".join(str(c) for c in cmd)
    if dry_run:
        return {
            "dry_run": True,
            "cmd": cmd,
            "cmd_text": cmd_text,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    def reader(pipe, bucket):
        for line in pipe:
            bucket.append(line)
            if verbose:
                print(line, end="", flush=True)

    def heartbeat(process):
        while process.poll() is None:
            if not verbose:
                print(".", end="", flush=True)
            time.sleep(30)

    t1 = threading.Thread(target=reader, args=(proc.stdout, stdout_lines))
    t2 = threading.Thread(target=reader, args=(proc.stderr, stderr_lines))
    t3 = threading.Thread(target=heartbeat, args=(proc,))
    t1.start()
    t2.start()
    t3.start()
    returncode = proc.wait()
    t1.join()
    t2.join()
    # t3 exits shortly after

    if not verbose and not dry_run:
        print(" ", end="\r")

    return {
        "dry_run": False,
        "cmd": cmd,
        "cmd_text": cmd_text,
        "returncode": returncode,
        "stdout": "".join(stdout_lines),
        "stderr": "".join(stderr_lines),
    }


def step_selected(step_id: int, step_key: str, selected: set) -> bool:
    if not selected:
        return True
    return str(step_id) in selected or step_key.lower() in selected


def execute_step(
    step_id: int,
    step_key: str,
    title: str,
    cmd: Optional[List[str]],
    *,
    pipeline_start: float,
    steps_report: List[dict],
    steps_lock: threading.Lock,
    selected_steps: set,
    execution_dry_run: bool,
    verbose: bool,
    gemini_semaphore: Optional[threading.Semaphore] = None,
) -> bool:
    """
    执行一个 pipeline 步骤，写入 steps_report，返回是否成功。
    - cmd=None 表示该步骤被 spec 禁用
    - gemini_semaphore 非空则在获取信号量后再执行
    """
    def _skip(reason: str) -> bool:
        with steps_lock:
            steps_report.append({
                "step_id": step_id,
                "step_key": step_key,
                "title": title,
                "skipped": True,
                "reason": reason,
                "result": {},
            })
        return True

    if not step_selected(step_id, step_key, selected_steps):
        return _skip("not_selected")
    if cmd is None:
        return _skip("disabled_by_spec")

    elapsed_total = time.time() - pipeline_start
    print(f"  ▶ Step {step_id:2d} / 14  {title}  [{elapsed_total:.0f}s]", flush=True)
    started = now_iso()
    step_start = time.time()

    if gemini_semaphore:
        with gemini_semaphore:
            result = run_cmd(cmd, dry_run=execution_dry_run, verbose=verbose)
    else:
        result = run_cmd(cmd, dry_run=execution_dry_run, verbose=verbose)

    ended = now_iso()
    ok = int(result.get("returncode", 1)) == 0
    duration = time.time() - step_start
    elapsed_total = time.time() - pipeline_start
    status = "✓" if ok else "✗"
    print(f"  {status} Step {step_id:2d} / 14  {title}  ({duration:.0f}s, 总计 {elapsed_total:.0f}s)", flush=True)

    if not ok:
        # 打印前 300 + 末尾 600，避免截断根因
        err = str(result.get("stderr", "") or "").strip()
        if err:
            if len(err) > 900:
                print(err[:300], flush=True)
                print("  ...(省略中间内容)...", flush=True)
                print(err[-600:], flush=True)
            else:
                print(err, flush=True)

    with steps_lock:
        steps_report.append({
            "step_id": step_id,
            "step_key": step_key,
            "title": title,
            "started_at": started,
            "ended_at": ended,
            "ok": ok,
            "result": result,
        })
    return ok
