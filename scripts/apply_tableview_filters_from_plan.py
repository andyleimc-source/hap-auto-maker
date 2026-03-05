#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import runpy

runpy.run_path(str((Path(__file__).resolve().parent / "hap/apply_tableview_filters_from_plan.py").resolve()), run_name="__main__")

