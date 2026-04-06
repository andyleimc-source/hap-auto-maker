"""
公用工具函数 — 替代散落在各脚本中的重复定义。
所有 scripts/hap/ 下的脚本统一从此导入。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def now_ts() -> str:
    """返回当前时间戳字符串，格式 YYYYmmdd_HHMMSS。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    """返回 ISO 8601 格式时间字符串（含时区）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    """读取 JSON 文件，文件不存在时抛出 FileNotFoundError。"""
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> Path:
    """写入 JSON 文件，自动创建父目录。返回写入路径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    """返回目录下匹配 pattern 的最新文件（按 mtime），无匹配返回 None。"""
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def write_json_with_latest(
    output_dir: Path,
    output_path: Path,
    latest_name: str,
    payload: Any,
) -> Path:
    """写入 JSON 文件，同时更新同目录下的 latest_name 文件。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_path, payload)
    latest_path = (output_dir / latest_name).resolve()
    write_json(latest_path, payload)
    return output_path


SUMMARY_PREFIX = "[SUMMARY] "

def log_summary(msg: str) -> None:
    """输出带 [SUMMARY] 前缀的摘要行，供 step_runner 在非 verbose 模式下透传。"""
    print(f"{SUMMARY_PREFIX}{msg}", flush=True)
