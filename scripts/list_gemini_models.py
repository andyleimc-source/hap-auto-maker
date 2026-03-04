#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import runpy

runpy.run_path(str((Path(__file__).resolve().parent / "gemini/list_gemini_models.py").resolve()), run_name="__main__")
