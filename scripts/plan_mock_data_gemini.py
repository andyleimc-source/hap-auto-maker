#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import runpy

runpy.run_path(str((Path(__file__).resolve().parent / "hap/plan_mock_data_gemini.py").resolve()), run_name="__main__")
