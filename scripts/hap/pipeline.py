#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import runpy

# Backward-compatible entry, delegates to the renamed pipeline script.
runpy.run_path(str((Path(__file__).resolve().parent / "pipeline_create_app.py").resolve()), run_name="__main__")
