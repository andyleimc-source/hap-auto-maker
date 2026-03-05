#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据规划 JSON 自动创建工作表（两阶段）：
1) 按 creation_order 创建所有非 Relation 字段的工作表
2) 回填 Relation 字段（需要目标 worksheetId）
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "https://api.mingdao.com"
CREATE_WS_ENDPOINT = "/v3/app/worksheets"
EDIT_WS_ENDPOINT = "/v3/app/worksheets/{worksheet_id}"
GET_WS_ENDPOINT = "/v3/app/worksheets/{worksheet_id}"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"
WORKSHEET_CREATE_RESULT_DIR = OUTPUT_ROOT / "worksheet_create_results"
ALLOWED_CARDINALITY = {"1-1", "1-N"}


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def resolve_json_input(value: str, default_pattern: str = "") -> Path:
    """
    支持三种输入：
    1) 绝对路径
    2) 相对路径（相对当前工作目录）
    3) 仅文件名（自动在 data/outputs 分类目录下查找）
    """
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()

        search_dirs = [WORKSHEET_PLAN_DIR, APP_AUTH_DIR, OUTPUT_ROOT]
        for d in search_dirs:
            candidate = (d / value).resolve()
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"找不到文件: {value}（也未在 outputs 分类目录下找到）")

    if default_pattern:
        # 优先新目录，兼容旧目录
        for d in (WORKSHEET_PLAN_DIR, APP_AUTH_DIR, OUTPUT_ROOT):
            p = latest_file(d, default_pattern)
            if p:
                return p.resolve()
    raise FileNotFoundError(f"未找到匹配文件: pattern={default_pattern}")


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_app_authorize(auth_path: Path, app_id: str = "") -> dict:
    data = load_json(auth_path)
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"授权文件格式不正确（缺少 data 列表）: {auth_path}")

    if app_id:
        for row in rows:
            if isinstance(row, dict) and row.get("appId") == app_id:
                return row
        raise ValueError(f"授权文件中未找到 appId={app_id}: {auth_path}")
    if not isinstance(rows[0], dict):
        raise ValueError(f"授权文件格式不正确: {auth_path}")
    return rows[0]


def parse_select_options(description: str) -> List[dict]:
    text = (description or "").strip()
    if not text:
        return [{"value": "选项1", "index": 1}, {"value": "选项2", "index": 2}]
    parts = [p.strip() for p in re.split(r"[/、,，;；|]", text) if p.strip()]
    cleaned_parts = []
    for p in parts:
        # 清理示例引导词，避免出现“如：转介绍”“例如xx”等脏选项
        p = re.sub(r"^(如|例如|比如)\s*[:：]\s*", "", p).strip()
        p = re.sub(r"(等|等等)$", "", p).strip()
        if p:
            cleaned_parts.append(p)
    parts = cleaned_parts
    # 去重并限制数量
    seen = set()
    uniq = []
    for p in parts:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
        if len(uniq) >= 10:
            break
    if len(uniq) < 2:
        uniq = ["选项1", "选项2"]
    return [{"value": v, "index": i + 1} for i, v in enumerate(uniq)]


def parse_select_options_from_field(field: dict) -> List[dict]:
    # 优先使用 Gemini 输出的结构化 option_values
    option_values = field.get("option_values")
    if isinstance(option_values, list):
        vals = []
        for v in option_values:
            if not isinstance(v, str):
                continue
            t = v.strip()
            if not t:
                continue
            t = re.sub(r"^(如|例如|比如)\s*[:：]\s*", "", t).strip()
            t = re.sub(r"(等|等等)$", "", t).strip()
            if t and t not in vals:
                vals.append(t)
            if len(vals) >= 10:
                break
        if len(vals) >= 2:
            return [{"value": v, "index": i + 1} for i, v in enumerate(vals)]
    return parse_select_options(str(field.get("description", "")))


def to_required(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "y")
    return bool(v)


def build_field_payload(field: dict, is_first_text_title: bool) -> dict:
    ftype = str(field.get("type", "Text")).strip()
    name = str(field.get("name", "")).strip() or "未命名字段"
    required = to_required(field.get("required", False))
    payload = {
        "name": name,
        "type": ftype,
        "required": required,
    }

    if is_first_text_title and ftype == "Text":
        payload["isTitle"] = 1

    if ftype == "Number":
        payload["precision"] = 2
    elif ftype in ("SingleSelect", "MultipleSelect"):
        payload["options"] = parse_select_options_from_field(field)
    elif ftype == "Collaborator":
        payload["subType"] = 0  # 单选成员
    elif ftype == "Relation":
        # Relation 统一在第二阶段处理
        pass
    return payload


def split_fields(fields: List[dict]) -> (List[dict], List[dict]):
    normal = []
    relation = []
    title_set = False

    for fld in fields:
        ftype = str(fld.get("type", "Text")).strip()
        if ftype == "Relation":
            relation.append(fld)
            continue
        payload = build_field_payload(fld, is_first_text_title=not title_set)
        if payload.get("isTitle") == 1:
            title_set = True
        normal.append(payload)

    # 兜底：如果没有任何字段，补一个标题字段
    if not normal:
        normal = [{"name": "名称", "type": "Text", "required": True, "isTitle": 1}]
        title_set = True

    # 若没标题字段，给第一个 Text 字段设标题；没有 Text 则补一个标题字段
    if not title_set:
        for fld in normal:
            if fld.get("type") == "Text":
                fld["isTitle"] = 1
                title_set = True
                break
    if not title_set:
        normal.insert(0, {"name": "名称", "type": "Text", "required": True, "isTitle": 1})

    return normal, relation


def build_relationship_rules(plan: dict) -> Dict[Tuple[str, str], dict]:
    """
    从规划 JSON 的 relationships 构建约束：
    - 仅允许 1-1 / 1-N
    - 同一对表（无序对）只保留一条关系规则
    """
    relationships = plan.get("relationships", [])
    if not isinstance(relationships, list):
        return {}

    rules: Dict[Tuple[str, str], dict] = {}
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        src = str(rel.get("from", "")).strip()
        dst = str(rel.get("to", "")).strip()
        cardinality = str(rel.get("cardinality", "")).strip().upper()
        field_name = str(rel.get("field", "")).strip()
        if not src or not dst:
            continue
        if cardinality and cardinality not in ALLOWED_CARDINALITY:
            raise ValueError(f"不支持的关系类型: {cardinality}（仅允许 1-1 或 1-N）")
        # 缺省按 1-N 处理（常见业务场景）
        if not cardinality:
            cardinality = "1-N"
        key = tuple(sorted((src, dst)))
        if key in rules:
            prev = rules[key]
            if prev["cardinality"] != cardinality:
                raise ValueError(
                    f"关系规则冲突: {src}<->{dst} 同时出现 {prev['cardinality']} 与 {cardinality}"
                )
            # 同一对表重复定义时保留第一条，并补充空字段名
            if not prev.get("field") and field_name:
                prev["field"] = field_name
            continue
        rules[key] = {"from": src, "to": dst, "cardinality": cardinality, "field": field_name}
    return rules


def create_worksheet(base_url: str, headers: dict, name: str, fields: List[dict]) -> dict:
    url = base_url.rstrip("/") + CREATE_WS_ENDPOINT
    payload = {
        "name": name,
        "fields": fields,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"创建工作表失败 [{name}]: {data}")
    return data


def collect_relation_field_candidates(worksheets: List[dict]) -> Dict[Tuple[str, str], List[dict]]:
    """
    从 worksheets 字段里提取 relation 候选：
    key=(source, target)
    value=[{"field_name": ..., "required": ...}, ...]
    """
    candidates: Dict[Tuple[str, str], List[dict]] = {}
    for ws in worksheets:
        if not isinstance(ws, dict):
            continue
        ws_name = str(ws.get("name", "")).strip()
        if not ws_name:
            continue
        fields = ws.get("fields", [])
        if not isinstance(fields, list):
            continue
        for fld in fields:
            if not isinstance(fld, dict):
                continue
            if str(fld.get("type", "")).strip() != "Relation":
                continue
            target_name = str(fld.get("relation_target", "")).strip()
            if not target_name:
                continue
            key = (ws_name, target_name)
            candidates.setdefault(key, []).append(
                {
                    "field_name": str(fld.get("name", "")).strip(),
                    "required": to_required(fld.get("required", False)),
                }
            )
    return candidates


def _pick_field_meta(candidates: Dict[Tuple[str, str], List[dict]], source: str, target: str, fallback_name: str) -> dict:
    arr = candidates.get((source, target), [])
    if arr:
        picked = arr[0]
        field_name = str(picked.get("field_name", "")).strip() or fallback_name
        return {"name": field_name, "required": bool(picked.get("required", False))}
    return {"name": fallback_name, "required": False}


def normalize_relation_plan(worksheets: List[dict], relationship_rules: Dict[Tuple[str, str], dict]) -> List[dict]:
    """
    把关系规范化为“每对表唯一一条有向 Relation 字段”，彻底避免 N-N。
    规则：
    - relationship_rules 为权威来源（若存在）
    - 1-N 一律落在多端表(to) -> 一端表(from)，subType=1
    - 1-1 仅保留单向一条（优先沿用已有候选方向）
    - 若缺少 relationship_rules 且同一对表出现双向候选，直接报错（避免隐式 N-N）
    """
    ws_names: Set[str] = set()
    for ws in worksheets:
        if isinstance(ws, dict):
            n = str(ws.get("name", "")).strip()
            if n:
                ws_names.add(n)
    if not ws_names:
        return []

    candidates = collect_relation_field_candidates(worksheets)
    by_pair_orientations: Dict[Tuple[str, str], Set[Tuple[str, str]]] = {}
    for source, target in candidates:
        key = tuple(sorted((source, target)))
        by_pair_orientations.setdefault(key, set()).add((source, target))

    normalized: List[dict] = []
    handled_pairs: Set[Tuple[str, str]] = set()

    # 1) 先按 relationships 强约束落地
    for pair_key, rule in relationship_rules.items():
        src = str(rule.get("from", "")).strip()
        dst = str(rule.get("to", "")).strip()
        cardinality = str(rule.get("cardinality", "1-N")).strip().upper() or "1-N"
        rel_field_name = str(rule.get("field", "")).strip()
        if src not in ws_names or dst not in ws_names:
            raise ValueError(f"relationships 引用了不存在的工作表: {src} -> {dst}")

        if cardinality == "1-N":
            # from(一) -> to(多)  ==> 字段应建在 to(多) 指向 from(一)
            relation_source = dst
            relation_target = src
        elif cardinality == "1-1":
            # 1-1 只保留单向一条：优先沿用已有候选方向，避免改名
            fwd_exists = bool(candidates.get((src, dst)))
            rev_exists = bool(candidates.get((dst, src)))
            if fwd_exists and not rev_exists:
                relation_source, relation_target = src, dst
            elif rev_exists and not fwd_exists:
                relation_source, relation_target = dst, src
            else:
                relation_source, relation_target = src, dst
        else:
            raise ValueError(f"不支持的关系类型: {cardinality}（仅允许 1-1 或 1-N）")

        fallback_name = rel_field_name or f"关联{relation_target}"
        meta = _pick_field_meta(candidates, relation_source, relation_target, fallback_name)
        normalized.append(
            {
                "pair_key": pair_key,
                "source": relation_source,
                "target": relation_target,
                "field_name": meta["name"],
                "required": bool(meta["required"]),
                "cardinality": cardinality,
                "origin": "relationship_rule",
            }
        )
        handled_pairs.add(pair_key)

    # 2) 再处理未在 relationships 声明但 fields 里出现的关系
    for pair_key, orientations in by_pair_orientations.items():
        if pair_key in handled_pairs:
            continue
        if len(orientations) > 1:
            a, b = pair_key
            raise ValueError(
                f"检测到未声明 relationships 的双向 Relation 候选: {a}<->{b}。"
                "为防止 N-N，请在 relationships 中明确声明该对表的 cardinality。"
            )
        source, target = next(iter(orientations))
        meta = _pick_field_meta(candidates, source, target, f"关联{target}")
        normalized.append(
            {
                "pair_key": pair_key,
                "source": source,
                "target": target,
                "field_name": meta["name"],
                "required": bool(meta["required"]),
                "cardinality": "1-N",
                "origin": "field_fallback",
            }
        )

    return normalized


def add_relation_fields(
    base_url: str,
    headers: dict,
    worksheet_id: str,
    worksheet_name: str,
    relation_specs: List[dict],
    name_to_id: Dict[str, str],
) -> dict:
    add_fields = []
    for spec in relation_specs:
        target_name = str(spec.get("target", "")).strip()
        field_name = str(spec.get("field_name", "")).strip() or "关联记录"
        required = to_required(spec.get("required", False))
        if not target_name:
            raise ValueError(f"工作表[{worksheet_name}] 字段[{field_name}] 缺少 target")
        target_id = name_to_id.get(target_name)
        if not target_id:
            raise ValueError(f"工作表[{worksheet_name}] 字段[{field_name}] 目标表不存在: {target_name}")

        add_fields.append(
            {
                "name": field_name,
                "type": "Relation",
                "required": required,
                "dataSource": target_id,
                "subType": 1,  # 单条关联
                # 只创建“主边”，由系统自动生成反向字段，确保两端都可见。
                "relation": {"showFields": [], "bidirectional": True},
            }
        )

    if not add_fields:
        return {"success": True, "data": {"worksheetId": worksheet_id}, "skipped_relations": []}

    url = base_url.rstrip("/") + EDIT_WS_ENDPOINT.format(worksheet_id=worksheet_id)
    payload = {"addFields": add_fields}
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"补充关联字段失败 [{worksheet_name}]: {data}")
    data["skipped_relations"] = []
    return data


def fetch_worksheet_detail(base_url: str, headers: dict, worksheet_id: str) -> dict:
    url = base_url.rstrip("/") + GET_WS_ENDPOINT.format(worksheet_id=worksheet_id)
    resp = requests.get(url, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取工作表结构失败: worksheetId={worksheet_id}, resp={data}")
    ws = data.get("data", {})
    if not isinstance(ws, dict):
        raise RuntimeError(f"工作表结构格式错误: worksheetId={worksheet_id}, resp={data}")
    return ws


def verify_relation_cardinality(
    base_url: str,
    headers: dict,
    name_to_id: Dict[str, str],
    relationship_rules: Dict[Tuple[str, str], dict],
) -> dict:
    """
    创建后校验：
    - relationship_rules 声明的关系必须满足双向可见与基数约束（1-1 / 1-N）
    - subType 仅允许 1 或 2
    """
    id_to_name = {wid: name for name, wid in name_to_id.items()}
    pair_to_edges: Dict[Tuple[str, str], List[dict]] = {}
    relation_edges: List[dict] = []

    for source_name, source_id in name_to_id.items():
        ws = fetch_worksheet_detail(base_url, headers, source_id)
        fields = ws.get("fields", [])
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, dict):
                continue
            if str(field.get("type", "")).strip() != "Relation":
                continue
            target_id = str(field.get("dataSource", "")).strip()
            target_name = id_to_name.get(target_id)
            if not target_name:
                # 指向非本次创建的表，不纳入 pair 检查，但保留到明细。
                target_name = f"[external:{target_id}]"
            sub_type = int(field.get("subType", 0) or 0)
            if sub_type not in (1, 2):
                raise RuntimeError(
                    f"检测到非法 Relation subType: {source_name}.{field.get('name')} -> {target_name}, subType={sub_type}"
                )
            edge = {
                "source": source_name,
                "target": target_name,
                "field": str(field.get("name", "")).strip(),
                "subType": sub_type,
            }
            relation_edges.append(edge)
            if target_name.startswith("[external:"):
                continue
            pair_key = tuple(sorted((source_name, target_name)))
            pair_to_edges.setdefault(pair_key, []).append(edge)

    violations = []
    for pair_key, rule in relationship_rules.items():
        src = str(rule.get("from", "")).strip()
        dst = str(rule.get("to", "")).strip()
        card = str(rule.get("cardinality", "1-N")).strip().upper() or "1-N"
        edges = pair_to_edges.get(pair_key, [])
        if not edges:
            violations.append({"pair": pair_key, "reason": "missing_relation_edges"})
            continue

        edge_signatures = {(e["source"], e["target"], int(e["subType"])) for e in edges}
        if card == "1-N":
            # 1-N 约束：N端(to)->1端(from) 为单选，1端(from)->N端(to) 为多选
            required = {(dst, src, 1), (src, dst, 2)}
        elif card == "1-1":
            # 1-1 约束：双向都为单选
            required = {(src, dst, 1), (dst, src, 1)}
        else:
            violations.append({"pair": pair_key, "reason": f"unsupported_cardinality:{card}"})
            continue
        missing = sorted(list(required - edge_signatures))
        if missing:
            violations.append({"pair": pair_key, "reason": "visibility_or_cardinality_mismatch", "missing": missing})

    # 对于未声明 rules 的 pair，仍保留基础风控：同向同 subtype 重复过多时视作异常
    for pair_key, edges in pair_to_edges.items():
        if pair_key in relationship_rules:
            continue
        sig_counts: Dict[Tuple[str, str, int], int] = {}
        for e in edges:
            sig = (e["source"], e["target"], int(e["subType"]))
            sig_counts[sig] = sig_counts.get(sig, 0) + 1
        dup = {str(k): v for k, v in sig_counts.items() if v > 1}
        if dup:
            violations.append({"pair": pair_key, "reason": "duplicate_unruled_edges", "detail": dup})

    if violations:
        raise RuntimeError(f"关系校验失败: {violations}")

    return {
        "checked_pairs": len(pair_to_edges),
        "relation_edges": relation_edges,
        "violations": violations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="根据规划 JSON 创建工作表")
    parser.add_argument(
        "--plan-json",
        required=True,
        help="规划 JSON 路径或文件名（仅文件名时优先从 data/outputs/worksheet_plans 查找）",
    )
    parser.add_argument(
        "--app-auth-json",
        required=True,
        help="应用授权 JSON 路径或文件名（仅文件名时优先从 data/outputs/app_authorizations 查找）",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求")
    args = parser.parse_args()

    plan_path = resolve_json_input(args.plan_json)
    plan = load_json(plan_path)

    auth_path = resolve_json_input(args.app_auth_json)
    auth = load_app_authorize(auth_path, app_id="")

    app_key = str(auth.get("appKey", "")).strip()
    sign = str(auth.get("sign", "")).strip()
    app_id = str(auth.get("appId", "")).strip()
    if not app_key or not sign:
        raise ValueError(f"授权文件缺少 appKey/sign: {auth_path}")

    headers = {
        "Content-Type": "application/json",
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
    }

    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError("规划 JSON 缺少 worksheets 列表")
    relationship_rules = build_relationship_rules(plan)
    normalized_relations = normalize_relation_plan(worksheets, relationship_rules)

    order = plan.get("creation_order", [])
    if isinstance(order, list) and order:
        ws_map = {str(w.get("name", "")).strip(): w for w in worksheets if isinstance(w, dict)}
        ordered = []
        for name in order:
            w = ws_map.get(str(name).strip())
            if w:
                ordered.append(w)
        # 把未出现在 creation_order 的工作表补在末尾
        remaining = [w for w in worksheets if w not in ordered]
        worksheets = ordered + remaining

    relation_plan_by_source: Dict[str, List[dict]] = {}
    for rel in normalized_relations:
        relation_plan_by_source.setdefault(rel["source"], []).append(rel)

    preview = []
    for ws in worksheets:
        name = str(ws.get("name", "")).strip() or "未命名工作表"
        fields = ws.get("fields", [])
        normal_fields, relation_fields = split_fields(fields if isinstance(fields, list) else [])
        preview.append(
            {
                "name": name,
                "normal_fields_count": len(normal_fields),
                "relation_fields_in_plan_count": len(relation_fields),
                "relation_fields_to_create_count": len(relation_plan_by_source.get(name, [])),
            }
        )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "app_id": app_id,
                    "app_auth_json": str(auth_path),
                    "plan_json": str(plan_path),
                    "create_plan": preview,
                    "normalized_relations": normalized_relations,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    name_to_id: Dict[str, str] = {}
    create_results = []
    relations_todo = []

    # Phase 1: 创建基础工作表（不含 Relation 字段）
    for ws in worksheets:
        ws_name = str(ws.get("name", "")).strip() or "未命名工作表"
        fields = ws.get("fields", [])
        normal_fields, relation_fields = split_fields(fields if isinstance(fields, list) else [])
        result = create_worksheet(args.base_url, headers, ws_name, normal_fields)
        worksheet_id = result.get("data", {}).get("worksheetId")
        if not worksheet_id:
            raise RuntimeError(f"创建工作表后未返回 worksheetId: {ws_name} / {result}")
        name_to_id[ws_name] = worksheet_id
        create_results.append({"name": ws_name, "worksheetId": worksheet_id, "result": result})
        relations_todo.append({"name": ws_name, "worksheetId": worksheet_id, "relation_fields": relation_fields})

    # Phase 2: 回填关联字段
    relation_results = []
    for item in relations_todo:
        ws_name = item["name"]
        ws_id = item["worksheetId"]
        relation_specs = relation_plan_by_source.get(ws_name, [])
        if not relation_specs:
            continue
        result = add_relation_fields(
            args.base_url,
            headers,
            ws_id,
            ws_name,
            relation_specs,
            name_to_id,
        )
        relation_results.append(
            {
                "name": ws_name,
                "worksheetId": ws_id,
                "relation_fields_count": len(relation_specs),
                "result": result,
            }
        )

    verification = verify_relation_cardinality(args.base_url, headers, name_to_id, relationship_rules)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    WORKSHEET_CREATE_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = (WORKSHEET_CREATE_RESULT_DIR / f"worksheet_create_result_{ts}.json").resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "app_id": app_id,
        "plan_json": str(plan_path),
        "app_auth_json": str(auth_path),
        "created_worksheets": create_results,
        "normalized_relations": normalized_relations,
        "relation_updates": relation_results,
        "relation_verification": verification,
        "name_to_worksheet_id": name_to_id,
    }
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n已保存: {output_path}")


if __name__ == "__main__":
    main()
