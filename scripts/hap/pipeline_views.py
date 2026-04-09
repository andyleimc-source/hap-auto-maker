#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图流水线（并行编排器）：
  对每个工作表（并行，up to ws_concurrency）：
    Step 1: recommend_views()           — 1 AI 调用
    Step 2: configure_single_view() × N — N AI 调用，并行
    Step 3: create_single_view_from_config() × N — N API 调用，并行
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

BASE_DIR = Path(__file__).resolve().parents[2]

from ai_utils import load_ai_config
from executors.create_views_from_plan import create_single_view_from_config
from planners.plan_worksheet_views_gemini import (
    fetch_controls,
    fetch_worksheets,
    load_app_auth_rows,
    simplify_field,
)
from planners.view_configurator import configure_single_view
from planners.view_recommender import recommend_views
from utils import now_ts, write_json

# ── 常量 ────────────────────────────────────────────────────────────
DEFAULT_WS_CONCURRENCY = 5
DEFAULT_VIEW_CONCURRENCY = 10

OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
DEFAULT_AUTH_CONFIG = BASE_DIR / "config" / "credentials" / "auth_config.py"


# ── 数据拉取 ────────────────────────────────────────────────────────
def _fetch_worksheets_and_fields(
    auth_config_path: str | Path,
    app_ids: str = "",
) -> list[dict]:
    """拉取应用授权、工作表及字段列表。

    Returns:
        list of dict, 每个元素包含：
        appId, appName, appKey, sign, worksheetId, worksheetName, fields, raw_fields
    """
    auth_config_path = Path(auth_config_path).expanduser().resolve()
    rows = load_app_auth_rows()

    # 可选过滤 appId
    if app_ids.strip():
        wanted = {a.strip() for a in app_ids.split(",") if a.strip()}
        rows = [r for r in rows if r.get("appId", "") in wanted]
    if not rows:
        print("未找到匹配的应用授权")
        return []

    result: list[dict] = []
    for row in rows:
        app_id = str(row.get("appId", ""))
        app_name = str(row.get("appName", ""))
        app_key = str(row.get("appKey", ""))
        sign = str(row.get("sign", ""))

        try:
            worksheets = fetch_worksheets(app_key, sign)
        except Exception as e:
            print(f"  [跳过] 获取工作表列表失败 appId={app_id}: {e}")
            continue

        for ws in worksheets:
            ws_id = ws.get("workSheetId", "")
            ws_name = ws.get("workSheetName", "")
            try:
                ctrl_data = fetch_controls(ws_id, auth_config_path)
                raw_fields = ctrl_data.get("fields", [])
                fields = [simplify_field(f) for f in raw_fields]
            except Exception as e:
                print(f"  [跳过] 获取字段失败 {ws_name}({ws_id}): {e}")
                continue

            result.append(
                {
                    "appId": app_id,
                    "appName": app_name,
                    "appKey": app_key,
                    "sign": sign,
                    "worksheetId": ws_id,
                    "worksheetName": ws_name,
                    "fields": fields,
                    "raw_fields": raw_fields,
                }
            )
    return result


# ── 单工作表处理 ────────────────────────────────────────────────────
def _process_single_worksheet(
    ws: dict,
    all_ws_names: list[str],
    app_background: str,
    auth_config_path: str | Path,
    ai_config: dict,
    dry_run: bool = False,
    view_concurrency: int = DEFAULT_VIEW_CONCURRENCY,
) -> dict:
    """处理单个工作表的推荐→配置→创建全流程。"""
    auth_config_path = Path(auth_config_path).expanduser().resolve()
    ws_name = ws["worksheetName"]
    ws_id = ws["worksheetId"]
    app_name = ws["appName"]
    app_id = ws["appId"]
    fields = ws["fields"]
    raw_fields = ws.get("raw_fields", [])
    other_names = [n for n in all_ws_names if n != ws_name]

    result = {
        "worksheetId": ws_id,
        "worksheetName": ws_name,
        "recommendation": None,
        "configs": [],
        "creates": [],
        "stats": {},
    }
    t0 = time.time()

    # ── Step 1: AI 推荐视图 ──
    print(f"[{ws_name}] Step 1: AI 推荐视图...")
    try:
        rec = recommend_views(
            app_name=app_name,
            app_background=app_background,
            worksheet_name=ws_name,
            worksheet_id=ws_id,
            fields=fields,
            other_worksheet_names=other_names,
            ai_config=ai_config,
        )
    except Exception as e:
        print(f"[{ws_name}] Step 1 失败: {e}")
        result["stats"]["error"] = f"recommend failed: {e}"
        result["stats"]["elapsed_s"] = round(time.time() - t0, 2)
        return result

    result["recommendation"] = rec
    views_to_configure = rec.get("views", [])
    if not views_to_configure:
        print(f"[{ws_name}] Step 1 完成: 无推荐视图")
        result["stats"]["elapsed_s"] = round(time.time() - t0, 2)
        return result
    print(f"[{ws_name}] Step 1 完成: 推荐 {len(views_to_configure)} 个视图")

    # ── Step 2: 并行配置视图 ──
    print(f"[{ws_name}] Step 2: 并行配置 {len(views_to_configure)} 个视图...")
    configs: list[dict | None] = [None] * len(views_to_configure)

    def _configure(idx: int, view_rec: dict) -> tuple[int, dict | None]:
        try:
            cfg = configure_single_view(
                view_recommendation=view_rec,
                worksheet_name=ws_name,
                fields=fields,
                ai_config=ai_config,
            )
            return idx, cfg
        except Exception as e:
            print(f"[{ws_name}] 配置视图 {view_rec.get('name', '?')} 失败: {e}")
            return idx, None

    with ThreadPoolExecutor(max_workers=min(view_concurrency, len(views_to_configure))) as pool:
        futures = {
            pool.submit(_configure, i, v): i
            for i, v in enumerate(views_to_configure)
        }
        for fut in as_completed(futures):
            idx, cfg = fut.result()
            configs[idx] = cfg

    # 过滤成功的配置
    valid_configs = [c for c in configs if c is not None]
    result["configs"] = valid_configs
    print(f"[{ws_name}] Step 2 完成: 配置成功 {len(valid_configs)}/{len(views_to_configure)}")

    if not valid_configs:
        result["stats"]["elapsed_s"] = round(time.time() - t0, 2)
        return result

    # ── Step 3: 并行创建视图 ──
    print(f"[{ws_name}] Step 3: 并行创建 {len(valid_configs)} 个视图...")
    creates: list[dict] = []

    def _create(cfg: dict) -> dict:
        try:
            return create_single_view_from_config(
                worksheet_id=ws_id,
                app_id=app_id,
                view_config=cfg,
                auth_config_path=auth_config_path,
                ws_fields=raw_fields,
                dry_run=dry_run,
            )
        except Exception as e:
            return {"success": False, "error": str(e), "viewName": cfg.get("name", "?")}

    with ThreadPoolExecutor(max_workers=min(view_concurrency, len(valid_configs))) as pool:
        futures = {pool.submit(_create, c): c for c in valid_configs}
        for fut in as_completed(futures):
            creates.append(fut.result())

    result["creates"] = creates
    ok_count = sum(1 for c in creates if c.get("success"))
    print(f"[{ws_name}] Step 3 完成: 创建成功 {ok_count}/{len(valid_configs)}")

    result["stats"]["elapsed_s"] = round(time.time() - t0, 2)
    return result


# ── CLI 入口 ────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="视图流水线：推荐 → 配置 → 创建（并行）")
    parser.add_argument("--auth-config", default=str(DEFAULT_AUTH_CONFIG), help="auth_config.py 路径")
    parser.add_argument("--app-ids", default="", help="可选，仅执行指定 appId（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际调用创建接口")
    parser.add_argument("--ws-concurrency", type=int, default=DEFAULT_WS_CONCURRENCY, help="工作表并行数")
    parser.add_argument("--view-concurrency", type=int, default=DEFAULT_VIEW_CONCURRENCY, help="视图并行数")
    parser.add_argument("--background", default="", help="应用背景描述（传递给 AI）")
    parser.add_argument("--output", default="", help="结果 JSON 输出路径")
    args = parser.parse_args()

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    ai_config = load_ai_config()

    # ── 拉取全部工作表和字段 ──
    print("拉取工作表和字段...")
    all_ws = _fetch_worksheets_and_fields(auth_config_path, app_ids=args.app_ids)
    if not all_ws:
        print("未找到任何工作表，退出")
        return
    print(f"共 {len(all_ws)} 个工作表\n")

    all_ws_names = [ws["worksheetName"] for ws in all_ws]
    t_start = time.time()

    # ── 并行处理工作表 ──
    results: list[dict] = [None] * len(all_ws)  # type: ignore[list-item]

    def _process(idx: int, ws: dict) -> tuple[int, dict]:
        r = _process_single_worksheet(
            ws=ws,
            all_ws_names=all_ws_names,
            app_background=args.background,
            auth_config_path=auth_config_path,
            ai_config=ai_config,
            dry_run=args.dry_run,
            view_concurrency=args.view_concurrency,
        )
        return idx, r

    with ThreadPoolExecutor(max_workers=args.ws_concurrency) as pool:
        futures = {pool.submit(_process, i, ws): i for i, ws in enumerate(all_ws)}
        for fut in as_completed(futures):
            try:
                idx, r = fut.result()
                results[idx] = r
            except Exception as e:
                idx = futures[fut]
                results[idx] = {
                    "worksheetId": all_ws[idx]["worksheetId"],
                    "worksheetName": all_ws[idx]["worksheetName"],
                    "recommendation": None,
                    "configs": [],
                    "creates": [],
                    "stats": {"error": str(e)},
                }

    total_elapsed = round(time.time() - t_start, 1)

    # ── 打印 Summary ──
    print("\n" + "=" * 50)
    print("视图流水线 Summary")
    print("=" * 50)
    for r in results:
        name = r["worksheetName"]
        rec = r.get("recommendation")
        configs = r.get("configs", [])
        creates = r.get("creates", [])
        err = r.get("stats", {}).get("error")

        if err:
            print(f"  {name}: 推荐 失败 → 跳过")
            continue

        n_rec = len(rec.get("views", [])) if rec else 0
        n_cfg = len(configs)
        n_ok = sum(1 for c in creates if c.get("success"))
        n_total = len(creates)
        print(f"  {name}: 推荐 {n_rec} → 配置 {n_cfg} → 创建 {n_ok}/{n_total}")

    print(f"  总耗时: {total_elapsed}s")
    print("=" * 50)

    # ── 保存结果 ──
    output_path = args.output.strip()
    if not output_path:
        output_dir = OUTPUT_ROOT / "view_pipeline_results"
        output_path = str(output_dir / f"pipeline_result_{now_ts()}.json")

    payload = {
        "timestamp": now_ts(),
        "total_elapsed_s": total_elapsed,
        "dry_run": args.dry_run,
        "worksheets": results,
    }
    saved = write_json(Path(output_path), payload)
    print(f"\n结果已保存: {saved}")


if __name__ == "__main__":
    main()
