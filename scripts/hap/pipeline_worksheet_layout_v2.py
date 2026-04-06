#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
布局流水线 v2：按工作表并发执行 fetch_controls → AI规划 → SaveWorksheetControls。
每张表独立线程，受全局 gemini_semaphore 限流（通过 --semaphore-value 传入，默认 1000）。
Gemini 2.5 Flash 付费第一层级：RPD=10K，RPM=1000，TPM=1M。40 张表并发远低于限速。
"""

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parent
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple

import requests

import auth_retry
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config
from utils import now_ts

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
RESULT_DIR = OUTPUT_ROOT / "worksheet_layout_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
SAVE_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetControls"
VALID_SIZES = {12, 6, 4, 3}


def _safe_int(v, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def normalize_layout(size: int, row: int, col: int) -> Tuple[int, int, int]:
    if size not in VALID_SIZES:
        size = 12
    if row < 0:
        row = 0
    slots = {12: 1, 6: 2, 4: 3, 3: 4}[size]
    col = max(0, min(col, slots - 1))
    return size, row, col


def fetch_app_structure(app_key: str, sign: str) -> Tuple[str, List[dict]]:
    """返回 (app_name, worksheets列表)，worksheets 每项含 workSheetId/workSheetName。"""
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json"}
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app_data = data.get("data", {})
    app_name = str(app_data.get("name", "")).strip()

    worksheets: List[dict] = []

    def walk(section: dict):
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append({
                    "workSheetId": str(item.get("id", "")),
                    "workSheetName": str(item.get("name", "")),
                })
        for child in section.get("childSections", []) or []:
            walk(child)

    for sec in app_data.get("sections", []) or []:
        walk(sec)
    return app_name, worksheets


def fetch_controls(worksheet_id: str) -> dict:
    """返回原始 payload（含 sourceId, version, controls）。"""
    resp = auth_retry.hap_web_post(
        GET_CONTROLS_URL, AUTH_CONFIG_PATH,
        referer=f"https://www.mingdao.com/worksheet/field/edit?sourceId={worksheet_id}",
        json={"worksheetId": worksheet_id}, timeout=30,
    )
    data = resp.json()
    wrapped = data.get("data", {})
    if isinstance(wrapped, dict) and isinstance(wrapped.get("data"), dict):
        if int(wrapped.get("code", 0)) != 1:
            raise RuntimeError(f"GetWorksheetControls 失败: {worksheet_id}, resp={data}")
        return wrapped["data"]
    payload = data.get("data", {})
    if not isinstance(payload, dict):
        raise RuntimeError(f"GetWorksheetControls 格式错误: {worksheet_id}, resp={data}")
    return payload


def build_prompt(app_name: str, all_ws_names: List[str], ws_name: str, fields: List[dict], requirements: str) -> str:
    return f"""你是企业级表单布局优化专家。请为当前工作表的字段规划最优布局（size/row/col），提升可读性。

目标应用：{app_name}
应用包含的所有工作表（仅供上下文参考）：{json.dumps(all_ws_names, ensure_ascii=False)}
当前工作表：{ws_name}
额外要求：{requirements or "无"}

当前工作表字段（必须全部覆盖，controlId 原样返回）：
{json.dumps(fields, ensure_ascii=False)}

输出格式（仅 JSON，不要 markdown）：
{{"fields": [{{"controlId": "字段ID", "size": 12, "row": 0, "col": 0, "reason": "简短说明"}}]}}

硬性约束：
1) 必须覆盖输入中每个 controlId。
2) size 仅允许 12/6/4/3。
3) size=12->col=0；size=6->col∈[0,1]；size=4->col∈[0,1,2]；size=3->col∈[0,1,2,3]。
4) row 从 0 开始递增。""".strip()


def parse_ai_fields(text: str) -> List[dict]:
    import re
    text = (text or "").strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if not m:
            raise ValueError(f"AI 未返回可解析 JSON: {text[:200]}")
        obj = json.loads(m.group(0))
    if isinstance(obj, list):
        return obj
    return obj.get("fields", [])


def apply_layout_to_controls(controls: List[dict], ai_fields: List[dict]) -> Tuple[List[dict], int]:
    """将 AI 规划的 size/row/col 写入 controls，返回 (new_controls, changed_count)。"""
    plan_map: Dict[str, dict] = {}
    for f in ai_fields:
        cid = str(f.get("controlId", "")).strip()
        if cid:
            plan_map[cid] = f

    changed = 0
    out = []
    for ctrl in controls:
        if not isinstance(ctrl, dict):
            out.append(ctrl)
            continue
        cid = str(ctrl.get("controlId", "")).strip()
        if cid and cid in plan_map:
            pf = plan_map[cid]
            size = _safe_int(pf.get("size"), _safe_int(ctrl.get("size"), 12))
            row  = _safe_int(pf.get("row"),  _safe_int(ctrl.get("row"),  0))
            col  = _safe_int(pf.get("col"),  _safe_int(ctrl.get("col"),  0))
            size, row, col = normalize_layout(size, row, col)
            old = (_safe_int(ctrl.get("size"), 12), _safe_int(ctrl.get("row"), 0), _safe_int(ctrl.get("col"), 0))
            if old != (size, row, col):
                changed += 1
            ctrl = dict(ctrl)
            ctrl["size"], ctrl["row"], ctrl["col"] = size, row, col
        out.append(ctrl)
    return out, changed


def process_worksheet(
    ws_id: str,
    ws_name: str,
    app_name: str,
    all_ws_names: List[str],
    requirements: str,
    client,
    model_name: str,
    ai_config: dict,
    semaphore: threading.Semaphore,
    dry_run: bool,
) -> dict:
    """单张工作表完整流程：fetch → AI → Save。供 ThreadPoolExecutor 调用。"""
    result = {
        "workSheetId": ws_id,
        "workSheetName": ws_name,
        "ok": False,
        "fieldsChanged": 0,
        "error": None,
        "controls": [],
    }
    try:
        # Step 1: fetch controls
        payload = fetch_controls(ws_id)
        controls = payload.get("controls", [])
        version = _safe_int(payload.get("version"), 0)
        source_id = str(payload.get("sourceId", ws_id)).strip() or ws_id

        # Step 2: 构建字段简报（只含当表字段）
        fields_brief = []
        for ctrl in controls:
            if not isinstance(ctrl, dict):
                continue
            cid = str(ctrl.get("controlId", "")).strip()
            if not cid:
                continue
            fields_brief.append({
                "controlId": cid,
                "controlName": str(ctrl.get("controlName", "")),
                "type": _safe_int(ctrl.get("type"), 0),
                "current": {
                    "size": _safe_int(ctrl.get("size"), 12),
                    "row":  _safe_int(ctrl.get("row"),  0),
                    "col":  _safe_int(ctrl.get("col"),  0),
                },
            })

        if not fields_brief:
            result["ok"] = True
            result["controls"] = controls
            return result

        # Step 3: AI 规划（受 semaphore 限流）
        prompt = build_prompt(app_name, all_ws_names, ws_name, fields_brief, requirements)
        with semaphore:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=create_generation_config(ai_config, response_mime_type="application/json", temperature=0.2),
            )
        ai_fields = parse_ai_fields(response.text or "")

        # Step 4: 合并布局到 controls
        new_controls, changed = apply_layout_to_controls(controls, ai_fields)

        # Step 5: Save（dry_run 跳过）
        if not dry_run:
            save_payload = {"version": version, "sourceId": source_id, "controls": new_controls}
            auth_retry.hap_web_post(
                SAVE_CONTROLS_URL, AUTH_CONFIG_PATH,
                referer=f"https://www.mingdao.com/worksheet/field/edit?sourceId={source_id}",
                json=save_payload, timeout=60,
            )

        result["ok"] = True
        result["fieldsChanged"] = changed
        result["controls"] = new_controls

    except Exception as exc:
        result["error"] = str(exc)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="布局流水线 v2：按工作表并发 fetch+AI+Save")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--requirements", default="", help="额外布局要求")
    parser.add_argument("--semaphore-value", type=int, default=1000, help="Gemini 并发限制（从全局 semaphore 传入）")
    parser.add_argument("--dry-run", action="store_true", help="仅规划不保存")
    args = parser.parse_args()

    # 加载 AI 配置
    ai_config = load_ai_config(AI_CONFIG_PATH)
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]
    semaphore = threading.Semaphore(args.semaphore_value)

    # 加载应用授权
    auth_files = sorted(
        APP_AUTH_DIR.glob(f"app_authorize_{args.app_id}.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not auth_files:
        raise FileNotFoundError(f"未找到应用授权文件: {args.app_id}")
    auth_data = json.loads(auth_files[0].read_text(encoding="utf-8"))
    auth_row = auth_data["data"][0]
    app_key = auth_row["appKey"]
    sign = auth_row["sign"]

    # 拉取应用结构（1次 API）
    app_name, worksheets = fetch_app_structure(app_key, sign)
    if not worksheets:
        raise RuntimeError(f"应用下没有工作表: {args.app_id}")

    all_ws_names = [ws["workSheetName"] for ws in worksheets]
    requirements = args.requirements.strip()
    dry_run = args.dry_run

    # 并发处理所有工作表
    print(f"开始布局规划+应用（并发）: {app_name}, {len(worksheets)} 张表", flush=True)
    t0 = time.time()

    ws_results = []
    max_workers = min(len(worksheets), args.semaphore_value)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(
                process_worksheet,
                ws["workSheetId"], ws["workSheetName"],
                app_name, all_ws_names, requirements,
                client, model_name, ai_config, semaphore, dry_run,
            ): ws
            for ws in worksheets
        }
        for future in as_completed(future_map):
            ws_results.append(future.result())

    elapsed = time.time() - t0
    total_changed = sum(r["fieldsChanged"] for r in ws_results)
    failed = [r for r in ws_results if not r["ok"]]

    # 写结果文件（兼容 mock_data_common.load_layout_controls_from_artifacts）
    # 兼容格式：results[].response.data.data.controls
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = now_ts()
    result_data = {
        "appId": args.app_id,
        "appName": app_name,
        "dry_run": dry_run,
        "worksheetCount": len(worksheets),
        "totalFields": sum(len(r["controls"]) for r in ws_results),
        "totalChanged": total_changed,
        "elapsedSeconds": round(elapsed, 1),
        "results": [
            {
                "workSheetId": r["workSheetId"],
                "workSheetName": r["workSheetName"],
                "fieldsChanged": r["fieldsChanged"],
                "ok": r["ok"],
                "error": r.get("error"),
                # 保持与 mock_data_common.load_layout_controls_from_artifacts 兼容
                "response": {
                    "data": {
                        "data": {
                            "controls": r["controls"],
                        }
                    }
                },
            }
            for r in ws_results
        ],
    }
    out = RESULT_DIR / f"worksheet_layout_apply_{ts}.json"
    out.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = RESULT_DIR / "worksheet_layout_apply_latest.json"
    latest.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("布局完成（摘要）")
    print(f"- 应用: {app_name} ({args.app_id})")
    print(f"- 工作表数量: {len(worksheets)}")
    print(f"- 变更字段数量: {total_changed}")
    print(f"- 耗时: {elapsed:.1f}s")
    print(f"- dry-run: {dry_run}")
    if failed:
        print(f"- 失败工作表: {len(failed)} 张")
        for r in failed:
            print(f"  ✗ {r['workSheetName']}: {r['error']}")
    print(f"- 结果文件: {out}")
    print(f"- 最新文件: {latest}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
