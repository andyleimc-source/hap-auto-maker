#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于已创建记录上下文，为关联字段生成语义关系映射计划（row_relation_plan）。
当 Gemini 输出不完整或不合法时，使用本地规则兜底补齐。
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
REL_CONTEXT_DIR = OUTPUT_ROOT / "row_relation_contexts"
REL_PLAN_DIR = OUTPUT_ROOT / "row_relation_plans"
DEFAULT_MODEL = "gemini-3-flash-preview"


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


def resolve_input_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (REL_CONTEXT_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到输入文件: {value}（也未在 {REL_CONTEXT_DIR} 找到）")
    latest = latest_file(REL_CONTEXT_DIR, "row_relation_context_*.json")
    if not latest:
        raise FileNotFoundError(f"未找到 row_relation_context 文件，请传 --input-json（目录: {REL_CONTEXT_DIR}）")
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


def normalize_text(value: str) -> str:
    x = str(value or "").strip().lower()
    x = re.sub(r"[\s\-_:/\\|,，。；;（）()【】\[\]{}<>]+", "", x)
    return x


def score_text(source: str, target: str) -> int:
    s = normalize_text(source)
    t = normalize_text(target)
    if not s or not t:
        return 0
    if s == t:
        return 100
    if s in t or t in s:
        return 80
    common = len(set(s) & set(t))
    if common == 0:
        return 0
    return int((2 * common / max(len(set(s)) + len(set(t)), 1)) * 60)


def pick_fallback_targets(source_row: dict, candidates: List[dict], sub_type: int) -> List[str]:
    if not candidates:
        return []
    source_text = str(source_row.get("displayText", "")).strip()
    source_index = int(source_row.get("sourceIndex", 0) or 0)

    scored = []
    for idx, c in enumerate(candidates):
        rid = str(c.get("rowId", "")).strip()
        if not rid:
            continue
        label = str(c.get("displayText", "")).strip()
        score = score_text(source_text, label)
        scored.append((score, -idx, rid))
    scored.sort(reverse=True)

    if not scored:
        return []

    if scored[0][0] <= 0:
        # 完全无法匹配时，退化为稳定轮询
        rid = str(candidates[source_index % len(candidates)].get("rowId", "")).strip()
        if not rid:
            rid = str(candidates[0].get("rowId", "")).strip()
        if sub_type == 2:
            out = [rid]
            if len(candidates) > 1:
                rid2 = str(candidates[(source_index + 1) % len(candidates)].get("rowId", "")).strip()
                if rid2 and rid2 != rid:
                    out.append(rid2)
            return out
        return [rid] if rid else []

    best = scored[0][2]
    if sub_type == 2:
        out = [best]
        for _, _, rid in scored[1:]:
            if rid != best:
                out.append(rid)
                break
        return out
    return [best]


def build_prompt(payload: dict) -> str:
    return f"""
你是企业主数据关联规划助手。请根据 source 行文本与 target 候选项，给出合理关联。

输入数据：
{json.dumps(payload, ensure_ascii=False, indent=2)}

输出要求：
只输出 JSON，不要 markdown。格式：
{{
  "links": [
    {{
      "sourceWorksheetId": "xxx",
      "sourceRowId": "xxx",
      "fieldLinks": [
        {{
          "fieldId": "关联字段ID",
          "targetRowIds": ["rowId1"]
        }}
      ]
    }}
  ]
}}

约束：
1) 只允许使用输入里出现的 sourceRowId / fieldId / targetRowId。
2) 每个 sourceRowId 的每个关联字段都应有一条 fieldLinks。
3) subType=1 时 targetRowIds 只能 1 条；subType=2 时最多 2 条。
4) 优先让“采购订单明细名/物料名”与“食材名”等语义一致，避免随机映射。
""".strip()


def normalize_links(raw: dict, context: dict) -> dict:
    raw_links = raw.get("links") if isinstance(raw.get("links"), list) else []

    target_map: Dict[str, List[dict]] = {}
    valid_target_ids: Dict[str, set] = {}
    for t in context.get("targets", []) or []:
        if not isinstance(t, dict):
            continue
        ws_id = str(t.get("workSheetId", "")).strip()
        rows = t.get("rows") if isinstance(t.get("rows"), list) else []
        if not ws_id:
            continue
        target_map[ws_id] = rows
        valid_target_ids[ws_id] = {str(r.get("rowId", "")).strip() for r in rows if str(r.get("rowId", "")).strip()}

    raw_index: Dict[Tuple[str, str, str], List[str]] = {}
    for link in raw_links:
        if not isinstance(link, dict):
            continue
        src_ws = str(link.get("sourceWorksheetId", "")).strip()
        src_row = str(link.get("sourceRowId", "")).strip()
        if not src_ws or not src_row:
            continue
        field_links = link.get("fieldLinks") if isinstance(link.get("fieldLinks"), list) else []
        for fl in field_links:
            if not isinstance(fl, dict):
                continue
            fid = str(fl.get("fieldId", "")).strip()
            targets = fl.get("targetRowIds") if isinstance(fl.get("targetRowIds"), list) else []
            norm = [str(x).strip() for x in targets if str(x).strip()]
            if fid:
                raw_index[(src_ws, src_row, fid)] = norm

    out_links = []
    sources = context.get("sources") if isinstance(context.get("sources"), list) else []
    total_fields = 0
    model_hit_fields = 0

    for src in sources:
        if not isinstance(src, dict):
            continue
        src_ws = str(src.get("workSheetId", "")).strip()
        rows = src.get("rows") if isinstance(src.get("rows"), list) else []
        rel_fields = src.get("relationFields") if isinstance(src.get("relationFields"), list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("rowId", "")).strip()
            if not row_id:
                continue
            field_links_out = []
            for rf in rel_fields:
                if not isinstance(rf, dict):
                    continue
                fid = str(rf.get("id", "")).strip()
                ds = str(rf.get("dataSource", "")).strip()
                sub_type = int(rf.get("subType", 1) or 1)
                if not fid or not ds:
                    continue
                total_fields += 1
                candidates = target_map.get(ds, [])
                valid_ids = valid_target_ids.get(ds, set())

                planned = raw_index.get((src_ws, row_id, fid), [])
                planned = [rid for rid in planned if rid in valid_ids]
                if sub_type == 1 and len(planned) > 1:
                    planned = planned[:1]
                if sub_type == 2 and len(planned) > 2:
                    planned = planned[:2]
                if planned:
                    model_hit_fields += 1

                if not planned:
                    planned = pick_fallback_targets(source_row=row, candidates=candidates, sub_type=sub_type)
                    planned = [rid for rid in planned if rid in valid_ids]
                    if sub_type == 1 and len(planned) > 1:
                        planned = planned[:1]
                    if sub_type == 2 and len(planned) > 2:
                        planned = planned[:2]

                if planned:
                    field_links_out.append({"fieldId": fid, "targetRowIds": planned})

            if field_links_out:
                out_links.append(
                    {
                        "sourceWorksheetId": src_ws,
                        "sourceRowId": row_id,
                        "fieldLinks": field_links_out,
                    }
                )

    return {
        "appId": str(context.get("appId", "")).strip(),
        "appName": str(context.get("appName", "")).strip(),
        "sourceContextJson": str(context.get("sourceContextJson", "")).strip(),
        "strategyVersion": "row_relation_link_v1",
        "stats": {
            "totalFieldLinks": total_fields,
            "modelHitFieldLinks": model_hit_fields,
            "fallbackFieldLinks": max(total_fields - model_hit_fields, 0),
        },
        "links": out_links,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="使用 Gemini 规划关联字段回填关系")
    parser.add_argument("--input-json", required=True, help="row_relation_context JSON 路径")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    context_path = resolve_input_json(args.input_json)
    context = load_json(context_path)
    context["sourceContextJson"] = str(context_path)

    api_key = load_api_key(Path(args.config).expanduser().resolve())
    client = genai.Client(api_key=api_key)

    prompt = build_prompt(context)
    response = client.models.generate_content(
        model=args.model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
    )
    raw = extract_json(response.text or "")
    final = normalize_links(raw, context)

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        REL_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        seed = sanitize_name(str(final.get("appId") or final.get("appName") or "app"))
        output_path = (REL_PLAN_DIR / f"row_relation_plan_{seed}_{ts}.json").resolve()

    write_json(output_path, final)
    write_json((REL_PLAN_DIR / "row_relation_plan_latest.json").resolve(), final)

    print("关系规划完成（概览）")
    print(f"- appId: {final.get('appId', '')}")
    print(f"- 链接行数: {len(final.get('links', []) if isinstance(final.get('links', []), list) else [])}")
    print(f"- 输出文件: {output_path}")


if __name__ == "__main__":
    main()
