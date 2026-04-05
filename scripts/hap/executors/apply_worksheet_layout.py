#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取布局规划 JSON，调用私有接口保存字段布局：
- GET: /api/Worksheet/GetWorksheetControls
- POST: /api/Worksheet/SaveWorksheetControls
"""

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import auth_retry
from utils import latest_file

BASE_DIR = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
LAYOUT_PLAN_DIR = OUTPUT_ROOT / "worksheet_layout_plans"
RESULT_DIR = OUTPUT_ROOT / "worksheet_layout_apply_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
SAVE_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetControls"
VALID_SIZES = {12, 6, 4, 3}


def resolve_plan_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (LAYOUT_PLAN_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到规划文件: {value}（也未在 {LAYOUT_PLAN_DIR} 找到）")
    p = latest_file(LAYOUT_PLAN_DIR, "worksheet_layout_plan_*.json")
    if not p:
        raise FileNotFoundError(f"未找到布局规划文件，请传 --plan-json（目录: {LAYOUT_PLAN_DIR}）")
    return p.resolve()



def _safe_int(v, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def normalize_layout(size: int, row: int, col: int) -> tuple[int, int, int]:
    if size not in VALID_SIZES:
        size = 12
    if row < 0:
        row = 0
    slots = {12: 1, 6: 2, 4: 3, 3: 4}[size]
    if col < 0:
        col = 0
    if col >= slots:
        col = slots - 1
    return size, row, col


def fetch_controls(source_id: str) -> dict:
    resp = auth_retry.hap_web_post(GET_CONTROLS_URL, AUTH_CONFIG_PATH, referer=f"https://www.mingdao.com/worksheet/field/edit?sourceId={source_id}", json={"worksheetId": source_id}, timeout=30)
    data = resp.json()
    wrapped = data.get("data", {})
    if not isinstance(wrapped, dict) or int(wrapped.get("code", 0)) != 1:
        raise RuntimeError(f"获取控件失败: sourceId={source_id}, resp={data}")
    payload = wrapped.get("data", {})
    if not isinstance(payload, dict):
        raise RuntimeError(f"获取控件失败: sourceId={source_id}, resp={data}")
    controls = payload.get("controls", [])
    if not isinstance(controls, list):
        raise RuntimeError(f"控件格式错误: sourceId={source_id}, resp={data}")
    return payload


def apply_plan_to_controls(controls: list, plan_fields: dict) -> tuple[list, int]:
    changed = 0
    out = []
    for ctrl in controls:
        if not isinstance(ctrl, dict):
            out.append(ctrl)
            continue
        cid = str(ctrl.get("controlId", "")).strip()
        if cid and cid in plan_fields:
            plan_item = plan_fields[cid]
            size = _safe_int(plan_item.get("size"), _safe_int(ctrl.get("size"), 12))
            row = _safe_int(plan_item.get("row"), _safe_int(ctrl.get("row"), 0))
            col = _safe_int(plan_item.get("col"), _safe_int(ctrl.get("col"), 0))
            size, row, col = normalize_layout(size, row, col)

            old_size = _safe_int(ctrl.get("size"), 12)
            old_row = _safe_int(ctrl.get("row"), 0)
            old_col = _safe_int(ctrl.get("col"), 0)

            if (old_size, old_row, old_col) != (size, row, col):
                changed += 1
            ctrl["size"] = size
            ctrl["row"] = row
            ctrl["col"] = col
        out.append(ctrl)
    return out, changed


def main() -> None:
    parser = argparse.ArgumentParser(description="应用字段布局规划（SaveWorksheetControls）")
    parser.add_argument("--plan-json", default="", help="布局规划 JSON 文件名或路径（默认取最新）")
    parser.add_argument("--refresh-auth", action="store_true", help="执行前先刷新网页登录认证")
    parser.add_argument("--headless", action="store_true", help="配合 --refresh-auth 无头刷新")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际保存")
    args = parser.parse_args()

    if args.refresh_auth:
        auth_retry.refresh_auth(AUTH_CONFIG_PATH, headless=args.headless)

    plan_path = resolve_plan_json(args.plan_json)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError(f"规划文件格式错误，缺少 worksheets: {plan_path}")

    results = []
    total_changed = 0
    for ws in worksheets:
        if not isinstance(ws, dict):
            continue
        source_id = str(ws.get("workSheetId", "")).strip()
        ws_name = str(ws.get("workSheetName", "")).strip()
        fields = ws.get("fields", [])
        if not source_id or not isinstance(fields, list):
            continue

        plan_fields = {}
        for f in fields:
            if not isinstance(f, dict):
                continue
            cid = str(f.get("controlId", "")).strip()
            if cid:
                plan_fields[cid] = f

        current = fetch_controls(source_id)
        controls = current.get("controls", [])
        version = _safe_int(current.get("version"), 0)
        source_id_from_api = str(current.get("sourceId", source_id)).strip() or source_id

        new_controls, changed = apply_plan_to_controls(controls, plan_fields)
        total_changed += changed

        payload = {
            "version": version,
            "sourceId": source_id_from_api,
            "controls": new_controls,
        }

        if args.dry_run:
            resp_data = {"dry_run": True}
            status_code = 0
        else:
            resp = auth_retry.hap_web_post(SAVE_CONTROLS_URL, AUTH_CONFIG_PATH, referer=f"https://www.mingdao.com/worksheet/field/edit?sourceId={source_id_from_api}", json=payload, timeout=60)
            status_code = resp.status_code
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {"text": resp.text}

        results.append(
            {
                "workSheetId": source_id,
                "workSheetName": ws_name,
                "plannedFields": len(plan_fields),
                "changedControls": changed,
                "statusCode": status_code,
                "response": resp_data,
            }
        )

    summary = {
        "plan_json": str(plan_path),
        "dry_run": args.dry_run,
        "worksheetCount": len(results),
        "totalChangedControls": total_changed,
        "results": results,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"worksheet_layout_apply_{ts}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = RESULT_DIR / "worksheet_layout_apply_latest.json"
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("布局应用完成（摘要）")
    print(f"- 规划文件: {plan_path}")
    print(f"- 工作表数量: {len(results)}")
    print(f"- 变更字段数量: {total_changed}")
    print(f"- dry-run: {args.dry_run}")
    print(f"- 结果文件: {out}")
    print(f"- 最新文件: {latest}")


if __name__ == "__main__":
    main()
