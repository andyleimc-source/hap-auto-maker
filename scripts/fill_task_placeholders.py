#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import runpy
from pathlib import Path

runpy.run_path(
    str((Path(__file__).resolve().parent / "hap/fill_task_placeholders.py").resolve()),
    run_name="__main__",
)
