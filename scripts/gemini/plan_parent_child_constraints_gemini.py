#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于工作表字段与父子关联，规划“父子数量/金额等运算一致性”约束。
输出 constraint plan JSON，供 enforce_parent_child_consistency.py 执行。
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
CONSISTENCY_CONTEXT_DIR = OUTPUT_ROOT / "row_consistency_contexts"
CONSISTENCY_PLAN_DIR = OUTPUT_ROOT / "parent_child_constraint_plans"
DEFAULT_MODEL = "gemini-3-flash-preview"

OPERATORS = {"sum_child_lte_parent", "sum_child_eq_parent"}

AMOUNT_KWS = ("金额", "价", "费用", "款", "成本", "单价", "总价", "回款", "付款", "收款", "应收", "应付")
QUANTITY_KWS = ("数量", "数", "件", "个", "箱", "吨", "斤", "库存", "入库", "出库", "发货", "完成", "回收")
EQ_PARENT_KWS = ("已", "累计", "已回", "已收", "已发", "已入", "已完成", "实收", "实发")


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


def resolve_context_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (CONSISTENCY_CONTEXT_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到 context 文件: {value}（也未在 {CONSISTENCY_CONTEXT_DIR} 找到）")
    latest = latest_file(CONSISTENCY_CONTEXT_DIR, "row_consistency_context_*.json")
    if not latest:
        raise FileNotFoundError(f"未找到 context 文件，请传 --context-json（目录: {CONSISTENCY_CONTEXT_DIR}）")
    return latest.resolve()


def load_api_key(config_path: Path) -> str:
    data = load_json(config_path)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"Gemini 配置缺少 api_key: {config_path}")
    return api_key


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Gemini 返回为空")
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Gemini 未返回可解析 JSON:\n{text}")


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "app"


def norm_text(s: str) -> str:
    x = str(s or "").strip().lower()
    x = re.sub(r"[\s\-_:/\\|,，。；;（）()【】\[\]{}<>]+", "", x)
    return x


def score_name(a: str, b: str) -> int:
    x = norm_text(a)
    y = norm_text(b)
    if not x or not y:
        return 0
    if x == y:
        return 100
    if x in y or y in x:
        return 80
    common = len(set(x) & set(y))
    return int((2 * common / max(len(set(x)) + len(set(y)), 1)) * 60)


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
    # 避免把数量字段和金额/单价字段混配；generic 不参与自动规则。
    if pc == "generic" or cc == "generic":
        return False
    return pc == cc


def choose_operator(parent_field_name: str) -> str:
    n = str(parent_field_name or "")
    if any(k in n for k in EQ_PARENT_KWS):
        return "sum_child_eq_parent"
    return "sum_child_lte_parent"


def build_pair_briefs(context: dict) -> Tuple[List[dict], Dict[Tuple[str, str, str], dict]]:
    worksheets = context.get("worksheets") if isinstance(context.get("worksheets"), list) else []
    ws_map = {(str(w.get("appId", "")).strip(), str(w.get("workSheetId", "")).strip()): w for w in worksheets if isinstance(w, dict)}

    briefs = []
    idx = {}
    for w in worksheets:
        if not isinstance(w, dict):
            continue
        app_id = str(w.get("appId", "")).strip()
        child_ws_id = str(w.get("workSheetId", "")).strip()
        child_ws_name = str(w.get("workSheetName", "")).strip()
        rels = w.get("relationFields") if isinstance(w.get("relationFields"), list) else []
        child_num_fields = [
            {"id": str(f.get("id", "")).strip(), "name": str(f.get("name", "")).strip()}
            for f in (w.get("fields") if isinstance(w.get("fields"), list) else [])
            if isinstance(f, dict) and str(f.get("type", "")).strip() == "Number" and str(f.get("id", "")).strip()
        ]
        for rf in rels:
            if not isinstance(rf, dict):
                continue
            sub_type = int(rf.get("subType", 1) or 1)
            if sub_type != 1:
                continue
            rel_fid = str(rf.get("id", "")).strip()
            parent_ws_id = str(rf.get("dataSource", "")).strip()
            if not rel_fid or not parent_ws_id:
                continue
            parent = ws_map.get((app_id, parent_ws_id))
            if not parent:
                continue
            parent_num_fields = [
                {"id": str(f.get("id", "")).strip(), "name": str(f.get("name", "")).strip()}
                for f in (parent.get("fields") if isinstance(parent.get("fields"), list) else [])
                if isinstance(f, dict) and str(f.get("type", "")).strip() == "Number" and str(f.get("id", "")).strip()
            ]
            pair = {
                "appId": app_id,
                "parentWorksheetId": parent_ws_id,
                "parentWorksheetName": str(parent.get("workSheetName", "")).strip(),
                "childWorksheetId": child_ws_id,
                "childWorksheetName": child_ws_name,
                "relationFieldId": rel_fid,
                "relationFieldName": str(rf.get("name", "")).strip(),
                "parentNumberFields": parent_num_fields,
                "childNumberFields": child_num_fields,
            }
            briefs.append(pair)
            idx[(app_id, parent_ws_id, child_ws_id)] = pair
    return briefs, idx


def build_prompt(pair_briefs: List[dict]) -> str:
    return f"""
你是企业数据治理助手。请为父子表关系规划“运算一致性”规则，重点约束数量/金额逻辑。

输入关系与字段：
{json.dumps(pair_briefs, ensure_ascii=False, indent=2)}

输出要求（只输出 JSON）：
{{
  "constraints": [
    {{
      "appId": "xxx",
      "parentWorksheetId": "父表ID",
      "parentWorksheetName": "父表",
      "childWorksheetId": "子表ID",
      "childWorksheetName": "子表",
      "relationFieldId": "子表中的父关联字段ID",
      "rules": [
        {{
          "parentFieldId": "父表数字字段ID",
          "parentFieldName": "父表数字字段名",
          "childFieldId": "子表数字字段ID",
          "childFieldName": "子表数字字段名",
          "operator": "sum_child_lte_parent|sum_child_eq_parent",
          "reason": "简短理由"
        }}
      ]
    }}
  ]
}}

规则：
1) 只使用输入中存在的字段ID。
2) 如果父字段是“总额/总量/计划量”，优先用 sum_child_lte_parent。
3) 如果父字段是“已回款/已完成/累计”，优先用 sum_child_eq_parent。
4) 每个父子关系最多输出 3 条规则。
""".strip()


def fallback_constraints(pair_briefs: List[dict]) -> List[dict]:
    out = []
    for p in pair_briefs:
        parent_fields = p.get("parentNumberFields", [])
        child_fields = p.get("childNumberFields", [])
        if not parent_fields or not child_fields:
            continue

        rules = []
        used_child = set()
        for pf in parent_fields:
            parent_name = str(pf.get("name", "")).strip()
            parent_cat = field_category(parent_name)
            if parent_cat == "generic":
                continue
            candidates = []
            for cf in child_fields:
                cfid = str(cf.get("id", "")).strip()
                if not cfid or cfid in used_child:
                    continue
                child_name = str(cf.get("name", "")).strip()
                child_cat = field_category(child_name)
                if parent_cat != child_cat:
                    continue
                cat_score = 30
                s = score_name(parent_name, child_name) + cat_score
                candidates.append((s, cf))
            if not candidates:
                continue
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0][1]
            used_child.add(str(best.get("id", "")).strip())
            rules.append(
                {
                    "parentFieldId": str(pf.get("id", "")).strip(),
                    "parentFieldName": parent_name,
                    "childFieldId": str(best.get("id", "")).strip(),
                    "childFieldName": str(best.get("name", "")).strip(),
                    "operator": choose_operator(parent_name),
                    "reason": "fallback_by_name_similarity",
                }
            )
            if len(rules) >= 3:
                break

        if rules:
            out.append(
                {
                    "appId": p["appId"],
                    "parentWorksheetId": p["parentWorksheetId"],
                    "parentWorksheetName": p["parentWorksheetName"],
                    "childWorksheetId": p["childWorksheetId"],
                    "childWorksheetName": p["childWorksheetName"],
                    "relationFieldId": p["relationFieldId"],
                    "rules": rules,
                }
            )
    return out


def normalize_constraints(raw: dict, pair_index: Dict[Tuple[str, str, str], dict], fallback: List[dict]) -> List[dict]:
    raw_constraints = raw.get("constraints") if isinstance(raw.get("constraints"), list) else []
    out = []
    seen = set()

    for c in raw_constraints:
        if not isinstance(c, dict):
            continue
        app_id = str(c.get("appId", "")).strip()
        pws = str(c.get("parentWorksheetId", "")).strip()
        cws = str(c.get("childWorksheetId", "")).strip()
        key = (app_id, pws, cws)
        pair = pair_index.get(key)
        if not pair:
            continue

        parent_ids = {str(x.get("id", "")).strip() for x in pair.get("parentNumberFields", [])}
        child_ids = {str(x.get("id", "")).strip() for x in pair.get("childNumberFields", [])}
        parent_name_by_id = {
            str(x.get("id", "")).strip(): str(x.get("name", "")).strip()
            for x in pair.get("parentNumberFields", [])
            if isinstance(x, dict) and str(x.get("id", "")).strip()
        }
        child_name_by_id = {
            str(x.get("id", "")).strip(): str(x.get("name", "")).strip()
            for x in pair.get("childNumberFields", [])
            if isinstance(x, dict) and str(x.get("id", "")).strip()
        }
        rules_raw = c.get("rules") if isinstance(c.get("rules"), list) else []
        rules = []
        for r in rules_raw:
            if not isinstance(r, dict):
                continue
            pfid = str(r.get("parentFieldId", "")).strip()
            cfid = str(r.get("childFieldId", "")).strip()
            op = str(r.get("operator", "")).strip()
            if (
                pfid in parent_ids
                and cfid in child_ids
                and op in OPERATORS
                and is_category_compatible(parent_name_by_id.get(pfid, ""), child_name_by_id.get(cfid, ""))
            ):
                rules.append(
                    {
                        "parentFieldId": pfid,
                        "parentFieldName": parent_name_by_id.get(pfid, "") or str(r.get("parentFieldName", "")).strip(),
                        "childFieldId": cfid,
                        "childFieldName": child_name_by_id.get(cfid, "") or str(r.get("childFieldName", "")).strip(),
                        "operator": op,
                        "reason": str(r.get("reason", "")).strip() or "gemini",
                    }
                )
            if len(rules) >= 3:
                break
        if not rules:
            continue

        out.append(
            {
                "appId": app_id,
                "parentWorksheetId": pws,
                "parentWorksheetName": pair["parentWorksheetName"],
                "childWorksheetId": cws,
                "childWorksheetName": pair["childWorksheetName"],
                "relationFieldId": pair["relationFieldId"],
                "rules": rules,
            }
        )
        seen.add(key)

    for f in fallback:
        key = (f["appId"], f["parentWorksheetId"], f["childWorksheetId"])
        if key in seen:
            continue
        out.append(f)

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="规划父子表运算一致性约束")
    parser.add_argument("--context-json", required=True, help="row_consistency_context JSON 路径")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    context_path = resolve_context_json(args.context_json)
    context = load_json(context_path)
    pair_briefs, pair_index = build_pair_briefs(context)
    fallback = fallback_constraints(pair_briefs)

    constraints = fallback
    model_used = "fallback"
    if pair_briefs:
        try:
            api_key = load_api_key(Path(args.config).expanduser().resolve())
            client = genai.Client(api_key=api_key)
            prompt = build_prompt(pair_briefs)
            resp = client.models.generate_content(
                model=args.model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
            )
            raw = extract_json(resp.text or "")
            constraints = normalize_constraints(raw, pair_index, fallback)
            model_used = args.model
        except Exception:
            constraints = fallback
            model_used = "fallback"

    payload = {
        "appId": str(context.get("appId", "")).strip(),
        "appName": str(context.get("appName", "")).strip(),
        "sourceContextJson": str(context_path),
        "strategyVersion": "parent_child_constraint_v1",
        "model": model_used,
        "constraints": constraints,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        CONSISTENCY_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        seed = sanitize_name(str(payload.get("appId") or payload.get("appName") or "app"))
        output_path = (CONSISTENCY_PLAN_DIR / f"parent_child_constraint_plan_{seed}_{ts}.json").resolve()

    write_json(output_path, payload)
    write_json((CONSISTENCY_PLAN_DIR / "parent_child_constraint_plan_latest.json").resolve(), payload)

    print("父子约束规划完成（概览）")
    print(f"- appId: {payload.get('appId', '')}")
    print(f"- 约束数量: {len(payload.get('constraints', []) if isinstance(payload.get('constraints', []), list) else [])}")
    print(f"- 模型: {model_used}")
    print(f"- 输出文件: {output_path}")


if __name__ == "__main__":
    main()
