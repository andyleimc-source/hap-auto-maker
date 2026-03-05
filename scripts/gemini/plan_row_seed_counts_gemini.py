#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 row_seed_schema JSON，调用 Gemini 评估每个工作表的造数层级与建议数量。
输出结果会强制满足分层下限，并在模型输出异常时本地兜底补齐。
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
SCHEMA_DIR = OUTPUT_ROOT / "row_seed_schemas"
COUNT_PLAN_DIR = OUTPUT_ROOT / "row_seed_count_plans"
DEFAULT_MODEL = "gemini-3-flash-preview"

RULES = {
    "core": 6,
    "mid": 12,
    "secondary": 18,
}

SECONDARY_NAME_HINTS = ("明细", "日志", "流水", "记录", "详情", "item")
CORE_NAME_HINTS = (
    "订单",
    "客户",
    "合同",
    "产品",
    "商机",
    "线索",
    "发票",
    "项目",
    "员工",
    "供应商",
)


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


def resolve_schema_json(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (SCHEMA_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到 schema 文件: {value}（也未在 {SCHEMA_DIR} 找到）")
    latest = latest_file(SCHEMA_DIR, "row_seed_schema_*.json")
    if not latest:
        raise FileNotFoundError(f"未找到 schema 文件，请传 --schema-json（目录: {SCHEMA_DIR}）")
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


def infer_app_meta(targets: List[dict]) -> Tuple[str, str]:
    app_id = ""
    app_name = ""
    for t in targets:
        if not isinstance(t, dict):
            continue
        app_id = app_id or str(t.get("appId", "")).strip()
        app_name = app_name or str(t.get("appName", "")).strip()
        if app_id and app_name:
            break
    return app_id, app_name


def summarize_targets(schema: dict) -> List[dict]:
    targets = schema.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("schema.targets 为空或格式错误")

    id_set = set()
    inbound_count: Dict[str, int] = {}
    for t in targets:
        if not isinstance(t, dict):
            continue
        ws_id = str(t.get("workSheetId", "")).strip()
        if ws_id:
            id_set.add(ws_id)

    for t in targets:
        if not isinstance(t, dict):
            continue
        for rel in t.get("relationFields", []) or []:
            if not isinstance(rel, dict):
                continue
            ds = str(rel.get("dataSource", "")).strip()
            if ds and ds in id_set:
                inbound_count[ds] = inbound_count.get(ds, 0) + 1

    out = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        ws_id = str(t.get("workSheetId", "")).strip()
        ws_name = str(t.get("workSheetName", "")).strip()
        if not ws_id or not ws_name:
            continue
        fields = t.get("fields") if isinstance(t.get("fields"), list) else []
        relation_fields = t.get("relationFields") if isinstance(t.get("relationFields"), list) else []
        field_names = []
        for f in fields:
            if isinstance(f, dict):
                name = str(f.get("name", "")).strip()
                if name:
                    field_names.append(name)
        out.append(
            {
                "appId": str(t.get("appId", "")).strip(),
                "appName": str(t.get("appName", "")).strip(),
                "workSheetId": ws_id,
                "workSheetName": ws_name,
                "inboundRelationCount": inbound_count.get(ws_id, 0),
                "outboundRelationCount": len(relation_fields),
                "fieldCount": len(fields),
                "fieldNameSample": field_names[:10],
            }
        )
    if not out:
        raise ValueError("schema 中没有有效工作表")
    return out


def build_prompt(table_inputs: List[dict]) -> str:
    return f"""
你是企业业务造数策略分析助手。请为每个工作表判断造数层级和数量。

输入工作表：
{json.dumps(table_inputs, ensure_ascii=False, indent=2)}

输出要求：
只输出 JSON，不要 markdown，格式必须如下：
{{
  "tableAnalyses": [
    {{
      "workSheetId": "xxx",
      "workSheetName": "xxx",
      "tier": "core|mid|secondary",
      "judgement": "判断理由",
      "seedCount": 6,
      "confidence": 0.85,
      "signals": ["命中信号1", "命中信号2"]
    }}
  ]
}}

约束：
1) 必须覆盖全部 workSheetId，每个 workSheetId 只出现一次。
2) tier 只能是 core/mid/secondary。
3) seedCount 必须为正整数，且满足下限：core>=6, mid>=12, secondary>=18。
4) 明细、日志、流水、记录、详情、item 这类明显次要表，优先判定为 secondary，seedCount 建议 18。
5) 如果 outboundRelationCount=0（不是任何表的关联子表/根表），优先判定为 core，seedCount 固定建议 6。
6) 主实体或被多个表依赖的基础主表，优先判定为 core，seedCount 建议 6。
7) 其他一般判定为 mid，seedCount 建议 12。
""".strip()


def normalize_tier(value: str) -> str:
    tier = str(value or "").strip().lower()
    if tier in RULES:
        return tier
    return "mid"


def looks_secondary(name: str) -> bool:
    lower = name.lower()
    for hint in SECONDARY_NAME_HINTS:
        if hint in name or hint in lower:
            return True
    return False


def looks_core(name: str, inbound_count: int) -> bool:
    if inbound_count >= 2:
        return True
    for hint in CORE_NAME_HINTS:
        if hint in name:
            return True
    return False


def looks_root_non_child(table_item: dict) -> bool:
    try:
        outbound = int(table_item.get("outboundRelationCount", 0) or 0)
    except Exception:
        outbound = 0
    return outbound <= 0


def fallback_single(table_item: dict) -> dict:
    ws_name = str(table_item.get("workSheetName", "")).strip()
    inbound_count = int(table_item.get("inboundRelationCount", 0) or 0)

    if looks_secondary(ws_name):
        tier = "secondary"
        seed_count = RULES[tier]
        judgement = "表名命中明细/日志类特征，按次要表处理"
        signals = ["name:secondary_hint"]
    elif looks_root_non_child(table_item):
        tier = "core"
        seed_count = RULES[tier]
        judgement = "非关联子表（根表）按基础表处理，固定取最小样本量"
        signals = ["root_non_child"]
    elif looks_core(ws_name, inbound_count):
        tier = "core"
        seed_count = RULES[tier]
        judgement = "被多表依赖或主实体语义明显，按基础表处理"
        signals = ["inbound_or_core_hint"]
    else:
        tier = "mid"
        seed_count = RULES[tier]
        judgement = "未命中主表/明细强特征，按中间层处理"
        signals = ["default_mid"]

    return {
        "workSheetId": table_item["workSheetId"],
        "workSheetName": ws_name,
        "tier": tier,
        "judgement": judgement,
        "seedCount": seed_count,
        "signals": signals,
    }


def normalize_analysis(raw: dict, table_index: Dict[str, dict]) -> List[dict]:
    raw_items = raw.get("tableAnalyses") if isinstance(raw.get("tableAnalyses"), list) else []
    normalized_by_id: Dict[str, dict] = {}

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        ws_id = str(item.get("workSheetId", "")).strip()
        if not ws_id or ws_id not in table_index:
            continue
        src = table_index[ws_id]
        tier = normalize_tier(item.get("tier", ""))
        min_count = RULES[tier]
        seed_count_raw = item.get("seedCount", min_count)
        try:
            seed_count = int(seed_count_raw)
        except Exception:
            seed_count = min_count
        seed_count = max(seed_count, min_count)
        ws_name = str(src.get("workSheetName", "")).strip()

        # 根表强制 core=6，避免流程主表被放大到 mid=12。
        if (not looks_secondary(ws_name)) and looks_root_non_child(src):
            tier = "core"
            seed_count = RULES[tier]
            judgement = "非关联子表（根表）强制按 core=6 处理"
        else:
            judgement = str(item.get("judgement", "")).strip() or "Gemini 判断"

        out = {
            "workSheetId": ws_id,
            "workSheetName": ws_name,
            "tier": tier,
            "judgement": judgement,
            "seedCount": seed_count,
        }
        conf = item.get("confidence")
        if isinstance(conf, (int, float)):
            out["confidence"] = max(0.0, min(1.0, float(conf)))
        signals = item.get("signals")
        if isinstance(signals, list):
            out["signals"] = [str(s).strip() for s in signals if str(s).strip()]
        normalized_by_id[ws_id] = out

    for ws_id, src in table_index.items():
        if ws_id in normalized_by_id:
            continue
        normalized_by_id[ws_id] = fallback_single(src)

    ordered = [normalized_by_id[ws_id] for ws_id in table_index.keys()]
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description="使用 Gemini 分析工作表造数层级与数量")
    parser.add_argument("--schema-json", required=True, help="row_seed_schema JSON 文件路径")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Gemini 配置 JSON 路径")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    schema_path = resolve_schema_json(args.schema_json)
    schema = load_json(schema_path)
    table_inputs = summarize_targets(schema)

    table_index = {t["workSheetId"]: t for t in table_inputs}
    app_id, app_name = infer_app_meta(schema.get("targets") if isinstance(schema.get("targets"), list) else [])

    api_key = load_api_key(Path(args.config).expanduser().resolve())
    client = genai.Client(api_key=api_key)

    prompt = build_prompt(table_inputs)
    response = client.models.generate_content(
        model=args.model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
    )
    raw_result = extract_json(response.text or "")
    analyses = normalize_analysis(raw_result, table_index)

    payload = {
        "appId": app_id,
        "appName": app_name,
        "sourceSchemaJson": str(schema_path),
        "strategyVersion": "row_seed_count_v1",
        "rules": {
            "core_min": RULES["core"],
            "mid_min": RULES["mid"],
            "secondary_min": RULES["secondary"],
        },
        "tableAnalyses": analyses,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        COUNT_PLAN_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        seed = sanitize_name(app_id or app_name or "app")
        output_path = (COUNT_PLAN_DIR / f"row_seed_count_plan_{seed}_{ts}.json").resolve()

    write_json(output_path, payload)
    write_json((COUNT_PLAN_DIR / "row_seed_count_plan_latest.json").resolve(), payload)

    print("造数数量分析完成（概览）")
    print(f"- appId: {app_id}")
    print(f"- 工作表数量: {len(analyses)}")
    print(f"- 输出文件: {output_path}")


if __name__ == "__main__":
    main()
