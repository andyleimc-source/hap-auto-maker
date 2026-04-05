#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resolve a script name to the canonical implementation path.

The repo currently keeps thin wrappers in `scripts/` and real implementations in
`scripts/hap/` or `scripts/gemini/`. Orchestrators should call the canonical
implementation directly so they do not depend on wrapper indirection.
"""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = BASE_DIR / "scripts"
CURRENT_DIR = Path(__file__).resolve().parent

SEARCH_DIRS = (
    CURRENT_DIR,
    CURRENT_DIR / "planners",
    CURRENT_DIR / "executors",
    CURRENT_DIR / "pipeline",
    SCRIPTS_DIR / "gemini",
    SCRIPTS_DIR / "auth",
    SCRIPTS_DIR,
)


def resolve_script(name: str) -> Path:
    for directory in SEARCH_DIRS:
        candidate = (directory / name).resolve()
        if candidate.exists():
            return candidate
    searched = ", ".join(str(path) for path in SEARCH_DIRS)
    raise FileNotFoundError(f"找不到脚本 {name}，已搜索: {searched}")

