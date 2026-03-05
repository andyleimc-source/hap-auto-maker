#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行父子表运算一致性校验与修正。
规则来源：parent_child_constraint_plan（Gemini + fallback）。
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
CONSISTENCY_CONTEXT_DIR = OUTPUT_ROOT / "row_consistency_contexts"
CONSISTENCY_PLAN_DIR = OUTPUT_ROOT / "parent_child_constraint_plans"
CONSISTENCY_RESULT_DIR = OUTPUT_ROOT / "parent_child_consistency_results"
PLAN_SCRIPT = BASE_DIR / "scripts" / "gemini" / "plan_parent_child_constraints_gemini.py"

ROWS_LIST_URL = "https://api.mingdao.com/v3/app/worksheets/{worksheet_id}/rows/list"
PATCH_ROW_URL = "https://api.mingdao.com/v3/app/worksheets/{worksheet_id}/rows/{row_id}"
UNIT_NAME_HINTS = ("计量单位", "单位", "量单位")
QUANTITY_KWS = ("数量", "库存", "入库", "出库", "发货", "收货", "领用", "退货", "件数")
AMOUNT_KWS = ("金额", "价", "费用", "款", "成本", "单价", "总价", "回款", "付款", "收款", "应收", "应付")
DECIMAL_FRIENDLY_UNITS = ("千克", "公斤", "kg", "克", "g", "升", "l", "毫升", "ml")
INTEGER_FRIENDLY_UNITS = (
    "件",
    "箱",
    "个",
    "包",
    "袋",
    "盒",
    "台",
    "份",
    "只",
    "支",
    "瓶",
    "条",
    "块",
    "头",
    "根",
    "张",
    "套",
    "桶",
    "盘",
    "本",
    "棵",
    "颗",
    "粒",
)


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def resolve_json_input(value: str, base_dir: Path, pattern: str, missing_tip: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (base_dir / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到文件: {value}（也未在 {base_dir} 找到）")
    p = latest_file(base_dir, pattern)
    if not p:
        raise FileNotFoundError(missing_tip)
    return p.resolve()


def list_rows_page(app_key: str, sign: str, worksheet_id: str, page_index: int, page_size: int = 1000) -> List[dict]:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    payload = {
        "pageIndex": page_index,
        "pageSize": page_size,
        "includeSystemFields": True,
        "useFieldIdAsKey": True,
    }
    url = ROWS_LIST_URL.format(worksheet_id=worksheet_id)
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    data = resp.json()
    if not data.get("success"):
        return []
    rows = (data.get("data") or {}).get("rows")
    if not isinstance(rows, list):
        return []
    return rows


def list_all_rows(app_key: str, sign: str, worksheet_id: str, max_pages: int = 200) -> List[dict]:
    out = []
    for i in range(1, max_pages + 1):
        rows = list_rows_page(app_key, sign, worksheet_id, i, 1000)
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1000:
            break
    return out


def patch_row_fields(app_key: str, sign: str, worksheet_id: str, row_id: str, fields: List[dict], dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "worksheetId": worksheet_id, "rowId": row_id, "fields": fields}
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    url = PATCH_ROW_URL.format(worksheet_id=worksheet_id, row_id=row_id)
    payload = {"fields": fields}
    resp = requests.patch(url, headers=headers, json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


def to_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        x = value.strip().replace(",", "")
        if not x:
            return None
        try:
            return float(x)
        except Exception:
            return None
    return None


def normalize_unit_text(unit_text: str) -> str:
    return str(unit_text or "").strip().lower().replace(" ", "")


def quantize_number(value: float, decimals: int) -> Any:
    if decimals <= 0:
        return int(round(float(value)))
    return round(float(value), decimals)


def field_category(name: str) -> str:
    n = str(name or "")
    if any(k in n for k in AMOUNT_KWS):
        return "amount"
    if any(k in n for k in QUANTITY_KWS):
        return "quantity"
    return "generic"


def is_category_compatible(parent_field_name: str, child_field_name: str) -> bool:
    pc = field_category(parent_field_name)
    cc = field_category(child_field_name)
    if pc == "generic" or cc == "generic":
        return False
    return pc == cc


def quantity_decimals_by_unit(unit_text: str) -> int:
    if not unit_text:
        return 0
    norm = normalize_unit_text(unit_text)
    for u in DECIMAL_FRIENDLY_UNITS:
        if normalize_unit_text(u) in norm:
            return 2
    for u in INTEGER_FRIENDLY_UNITS:
        if normalize_unit_text(u) in norm:
            return 0
    return 0


def build_worksheet_field_meta(context: dict) -> Dict[Tuple[str, str], dict]:
    meta: Dict[Tuple[str, str], dict] = {}
    worksheets = context.get("worksheets") if isinstance(context.get("worksheets"), list) else []
    for ws in worksheets:
        if not isinstance(ws, dict):
            continue
        app_id = str(ws.get("appId", "")).strip()
        ws_id = str(ws.get("workSheetId", "")).strip()
        if not app_id or not ws_id:
            continue
        fields = ws.get("fields") if isinstance(ws.get("fields"), list) else []
        option_maps: Dict[str, Dict[str, str]] = {}
        unit_field_id = ""
        for f in fields:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id", "")).strip()
            if not fid:
                continue
            fname = str(f.get("name", "")).strip()
            if not unit_field_id and any(h in fname for h in UNIT_NAME_HINTS):
                unit_field_id = fid
            options = f.get("options") if isinstance(f.get("options"), list) else []
            if options:
                m = {}
                for opt in options:
                    if not isinstance(opt, dict):
                        continue
                    k = str(opt.get("key", "")).strip()
                    v = str(opt.get("value", "")).strip()
                    if k and v:
                        m[k] = v
                if m:
                    option_maps[fid] = m
        meta[(app_id, ws_id)] = {"unitFieldId": unit_field_id, "optionMaps": option_maps}
    return meta


def get_field_value(row: dict, field_id: str) -> Any:
    if field_id in row:
        return row.get(field_id)
    fields = row.get("fields") if isinstance(row.get("fields"), list) else []
    for f in fields:
        if isinstance(f, dict) and str(f.get("id", "")).strip() == field_id:
            return f.get("value")
    return None


def get_relation_parent_row_id(row: dict, relation_field_id: str) -> str:
    v = get_field_value(row, relation_field_id)
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, dict):
            for key in ("rowid", "sid", "id"):
                val = str(first.get(key, "")).strip()
                if val:
                    return val
            return ""
        return str(first).strip()
    if isinstance(v, dict):
        for key in ("rowid", "sid", "id"):
            val = str(v.get(key, "")).strip()
            if val:
                return val
        return ""
    if isinstance(v, str):
        return v.strip()
    return ""


def group_child_rows_by_parent(child_rows: List[dict], relation_field_id: str) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for r in child_rows:
        if not isinstance(r, dict):
            continue
        parent_id = get_relation_parent_row_id(r, relation_field_id)
        if not parent_id:
            continue
        grouped.setdefault(parent_id, []).append(r)
    return grouped


def merge_patch_fields(existing: List[dict], fid: str, value: Any) -> List[dict]:
    out = []
    replaced = False
    for it in existing:
        if not isinstance(it, dict):
            continue
        if str(it.get("id", "")).strip() == fid:
            out.append({"id": fid, "value": value})
            replaced = True
        else:
            out.append(it)
    if not replaced:
        out.append({"id": fid, "value": value})
    return out


def resolve_row_unit_text(row: dict, ws_meta: dict) -> str:
    if not isinstance(ws_meta, dict):
        return ""
    unit_fid = str(ws_meta.get("unitFieldId", "")).strip()
    if not unit_fid:
        return ""
    raw = get_field_value(row, unit_fid)
    if raw is None:
        return ""
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("value") or raw.get("title") or "").strip()
    text = str(raw).strip()
    if not text:
        return ""
    option_maps = ws_meta.get("optionMaps") if isinstance(ws_meta.get("optionMaps"), dict) else {}
    unit_opts = option_maps.get(unit_fid) if isinstance(option_maps, dict) else None
    if isinstance(unit_opts, dict) and text in unit_opts:
        return str(unit_opts[text]).strip()
    return text


def infer_rule_decimals(rule: dict, parent_row: dict, parent_ws_meta: dict) -> int:
    parent_name = str(rule.get("parentFieldName", "")).strip()
    child_name = str(rule.get("childFieldName", "")).strip()
    if "quantity" in (field_category(parent_name), field_category(child_name)):
        return quantity_decimals_by_unit(resolve_row_unit_text(parent_row, parent_ws_meta))
    return 2


def run_plan_script(context_json: Path, model: str, output_json: Path) -> dict:
    cmd = [
        sys.executable,
        str(PLAN_SCRIPT),
        "--context-json",
        str(context_json),
        "--model",
        model,
        "--output",
        str(output_json),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"约束规划脚本执行失败: {msg}")
    return load_json(output_json)


def ensure_constraints(payload: dict) -> List[dict]:
    cons = payload.get("constraints") if isinstance(payload.get("constraints"), list) else []
    out = []
    for c in cons:
        if not isinstance(c, dict):
            continue
        relation_field_id = str(c.get("relationFieldId", "")).strip()
        pws = str(c.get("parentWorksheetId", "")).strip()
        cws = str(c.get("childWorksheetId", "")).strip()
        rules = c.get("rules") if isinstance(c.get("rules"), list) else []
        norm_rules = []
        for r in rules:
            if not isinstance(r, dict):
                continue
            pfid = str(r.get("parentFieldId", "")).strip()
            cfid = str(r.get("childFieldId", "")).strip()
            pname = str(r.get("parentFieldName", "")).strip()
            cname = str(r.get("childFieldName", "")).strip()
            op = str(r.get("operator", "")).strip()
            if pfid and cfid and op in ("sum_child_lte_parent", "sum_child_eq_parent") and is_category_compatible(pname, cname):
                norm_rules.append(
                    {
                        "parentFieldId": pfid,
                        "parentFieldName": pname,
                        "childFieldId": cfid,
                        "childFieldName": cname,
                        "operator": op,
                    }
                )
        if relation_field_id and pws and cws and norm_rules:
            out.append(
                {
                    "appId": str(c.get("appId", "")).strip(),
                    "parentWorksheetId": pws,
                    "parentWorksheetName": str(c.get("parentWorksheetName", "")).strip(),
                    "childWorksheetId": cws,
                    "childWorksheetName": str(c.get("childWorksheetName", "")).strip(),
                    "relationFieldId": relation_field_id,
                    "rules": norm_rules,
                }
            )
    return out


def apply_lte_rule(parent_value: float, child_values: List[Tuple[dict, float]], decimals: int = 2) -> Dict[str, Any]:
    total = sum(v for _, v in child_values)
    if total <= parent_value or total <= 0:
        return {}
    scale = max(parent_value / total, 0.0)
    updates: Dict[str, Any] = {}
    accum = 0.0
    for idx, (row, value) in enumerate(child_values):
        rid = str(row.get("rowid", "")).strip()
        if not rid:
            continue
        if idx < len(child_values) - 1:
            nv = quantize_number(value * scale, decimals)
            nv = max(nv, 0)
            updates[rid] = nv
            accum += nv
        else:
            nv = quantize_number(max(parent_value - accum, 0.0), decimals)
            updates[rid] = nv
    return updates


def main() -> None:
    parser = argparse.ArgumentParser(description="执行父子表运算一致性修正")
    parser.add_argument("--context-json", required=True, help="row_consistency_context JSON 路径")
    parser.add_argument("--constraint-plan-json", default="", help="可选，约束规划 JSON 路径")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="Gemini 模型名（仅自动规划时使用）")
    parser.add_argument("--dry-run", action="store_true", help="仅输出修正计划，不实际 patch")
    parser.add_argument("--output", default="", help="输出结果 JSON 路径")
    args = parser.parse_args()

    context_path = resolve_json_input(
        args.context_json,
        CONSISTENCY_CONTEXT_DIR,
        "row_consistency_context_*.json",
        f"未找到 context 文件（目录: {CONSISTENCY_CONTEXT_DIR}）",
    )
    context = load_json(context_path)
    worksheet_field_meta = build_worksheet_field_meta(context)

    apps = context.get("apps") if isinstance(context.get("apps"), list) else []
    app_cred = {}
    for a in apps:
        if not isinstance(a, dict):
            continue
        app_id = str(a.get("appId", "")).strip()
        app_key = str(a.get("appKey", "")).strip()
        sign = str(a.get("sign", "")).strip()
        if app_id and app_key and sign:
            app_cred[app_id] = {"appKey": app_key, "sign": sign}

    plan_path: Optional[Path] = None
    plan_payload: dict = {"constraints": []}
    plan_error = ""
    try:
        if args.constraint_plan_json.strip():
            plan_path = resolve_json_input(
                args.constraint_plan_json,
                CONSISTENCY_PLAN_DIR,
                "parent_child_constraint_plan_*.json",
                f"未找到约束规划文件（目录: {CONSISTENCY_PLAN_DIR}）",
            )
            plan_payload = load_json(plan_path)
        else:
            CONSISTENCY_PLAN_DIR.mkdir(parents=True, exist_ok=True)
            plan_path = (CONSISTENCY_PLAN_DIR / f"parent_child_constraint_plan_{now_ts()}.json").resolve()
            plan_payload = run_plan_script(context_json=context_path, model=args.model, output_json=plan_path)
            write_json((CONSISTENCY_PLAN_DIR / "parent_child_constraint_plan_latest.json").resolve(), plan_payload)
    except Exception as exc:
        plan_error = str(exc)
        plan_payload = {"constraints": []}

    constraints = ensure_constraints(plan_payload)

    # 仅加载约束涉及的工作表
    ws_needed = set()
    for c in constraints:
        app_id = c.get("appId", "")
        ws_needed.add((app_id, c.get("parentWorksheetId", "")))
        ws_needed.add((app_id, c.get("childWorksheetId", "")))

    rows_cache: Dict[Tuple[str, str], List[dict]] = {}
    for app_id, ws_id in ws_needed:
        cred = app_cred.get(app_id)
        if not cred or not ws_id:
            continue
        rows_cache[(app_id, ws_id)] = list_all_rows(cred["appKey"], cred["sign"], ws_id)

    patch_map: Dict[Tuple[str, str, str], List[dict]] = {}
    checks = 0
    violations = 0

    for c in constraints:
        app_id = c.get("appId", "")
        parent_ws = c.get("parentWorksheetId", "")
        child_ws = c.get("childWorksheetId", "")
        relation_fid = c.get("relationFieldId", "")

        parent_rows = rows_cache.get((app_id, parent_ws), [])
        child_rows = rows_cache.get((app_id, child_ws), [])
        if not parent_rows or not child_rows:
            continue

        parent_by_id = {str(r.get("rowid", "")).strip(): r for r in parent_rows if str(r.get("rowid", "")).strip()}
        child_group = group_child_rows_by_parent(child_rows, relation_fid)

        for rule in c.get("rules", []):
            pfid = rule["parentFieldId"]
            cfid = rule["childFieldId"]
            op = rule["operator"]

            for parent_id, rows in child_group.items():
                parent_row = parent_by_id.get(parent_id)
                if not parent_row:
                    continue
                parent_ws_meta = worksheet_field_meta.get((app_id, parent_ws), {})
                decimals = infer_rule_decimals(rule, parent_row, parent_ws_meta)

                parent_val = to_number(get_field_value(parent_row, pfid))
                parent_val = parent_val if parent_val is not None else 0.0

                child_values = []
                for r in rows:
                    v = to_number(get_field_value(r, cfid))
                    if v is None:
                        continue
                    child_values.append((r, v))
                if not child_values:
                    continue

                child_sum = sum(v for _, v in child_values)
                checks += 1

                if op == "sum_child_eq_parent":
                    if abs(child_sum - parent_val) > 0.01:
                        violations += 1
                        parent_new = quantize_number(child_sum, decimals)
                        pkey = (app_id, parent_ws, parent_id)
                        patch_map[pkey] = merge_patch_fields(patch_map.get(pkey, []), pfid, parent_new)
                        parent_row[pfid] = parent_new

                elif op == "sum_child_lte_parent":
                    if parent_val <= 0 and child_sum > 0:
                        # 父值为空或无效时，父值补到子和
                        violations += 1
                        parent_new = quantize_number(child_sum, decimals)
                        pkey = (app_id, parent_ws, parent_id)
                        patch_map[pkey] = merge_patch_fields(patch_map.get(pkey, []), pfid, parent_new)
                        parent_row[pfid] = parent_new
                    elif child_sum - parent_val > 0.01:
                        violations += 1
                        updates = apply_lte_rule(parent_val, child_values, decimals)
                        for rid, new_val in updates.items():
                            ckey = (app_id, child_ws, rid)
                            child_new = quantize_number(new_val, decimals)
                            patch_map[ckey] = merge_patch_fields(patch_map.get(ckey, []), cfid, child_new)
                            # 更新缓存，便于后续规则基于最新值继续计算
                            for rr in child_rows:
                                if str(rr.get("rowid", "")).strip() == rid:
                                    rr[cfid] = child_new
                                    break

    patch_results = []
    patch_success = 0
    for (app_id, ws_id, row_id), fields in patch_map.items():
        cred = app_cred.get(app_id)
        if not cred:
            patch_results.append(
                {"appId": app_id, "workSheetId": ws_id, "rowId": row_id, "ok": False, "reason": "missing_app_cred"}
            )
            continue
        resp = patch_row_fields(
            app_key=cred["appKey"],
            sign=cred["sign"],
            worksheet_id=ws_id,
            row_id=row_id,
            fields=fields,
            dry_run=args.dry_run,
        )
        ok = bool(resp.get("success")) if isinstance(resp, dict) and "success" in resp else bool(resp.get("dry_run"))
        if ok:
            patch_success += 1
        patch_results.append(
            {
                "appId": app_id,
                "workSheetId": ws_id,
                "rowId": row_id,
                "fields": fields,
                "ok": ok,
                "response": resp,
            }
        )

    result = {
        "dry_run": args.dry_run,
        "contextJson": str(context_path),
        "constraintPlanJson": str(plan_path) if plan_path else "",
        "constraintPlanError": plan_error,
        "constraintCount": len(constraints),
        "checkCount": checks,
        "violationCount": violations,
        "patchRowCount": len(patch_map),
        "patchSuccessCount": patch_success,
        "patchResults": patch_results,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        CONSISTENCY_RESULT_DIR.mkdir(parents=True, exist_ok=True)
        ts = now_ts()
        app_id = str(context.get("appId", "")).strip() or "app"
        output_path = (CONSISTENCY_RESULT_DIR / f"parent_child_consistency_result_{app_id}_{ts}.json").resolve()

    write_json(output_path, result)
    write_json((CONSISTENCY_RESULT_DIR / "parent_child_consistency_result_latest.json").resolve(), result)

    print("父子一致性修正完成（概览）")
    print(f"- 约束数量: {len(constraints)}")
    print(f"- 校验次数: {checks}")
    print(f"- 违规次数: {violations}")
    print(f"- 计划修正行数: {len(patch_map)}")
    print(f"- 修正成功行数: {patch_success}")
    print(f"- 结果文件: {output_path}")


if __name__ == "__main__":
    main()
