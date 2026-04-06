#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据规划 JSON 自动创建工作表（两阶段）：
1) 按 creation_order 创建所有非 Relation 字段的工作表
2) 回填 Relation 字段（需要目标 worksheetId）
"""

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import os

import requests
from utils import latest_file, load_json, log_summary

BASE_DIR = Path(__file__).resolve().parents[3]
DEFAULT_BASE_URL = "https://api.mingdao.com"
CREATE_WS_ENDPOINT = "/v3/app/worksheets"
EDIT_WS_ENDPOINT = "/v3/app/worksheets/{worksheet_id}"
GET_WS_ENDPOINT = "/v3/app/worksheets/{worksheet_id}"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"
WORKSHEET_CREATE_RESULT_DIR = OUTPUT_ROOT / "worksheet_create_results"
ALLOWED_CARDINALITY = {"1-1", "1-N"}
RELATION_UPDATE_RETRYABLE_ERRORS = {"数据过时"}


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


def validate_plan_structure(plan: dict) -> None:
    worksheets = plan.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError("规划 JSON 缺少 worksheets 列表")

    errors = []
    for index, worksheet in enumerate(worksheets, start=1):
        if not isinstance(worksheet, dict):
            errors.append(f"第 {index} 个工作表不是对象")
            continue
        name = str(worksheet.get("name", "")).strip() or f"第{index}个工作表"
        fields = worksheet.get("fields", [])
        if not isinstance(fields, list):
            errors.append(f"工作表《{name}》的 fields 必须是数组")
    if errors:
        raise ValueError("；".join(errors))


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
    if ftype == "Collaborator":
        required = False
    payload = {
        "name": name,
        "type": ftype,
        "required": required,
    }

    if is_first_text_title and ftype == "Text":
        payload["isTitle"] = 1

    if ftype in ("Number", "Money"):
        # dot: 小数位数（0=整数, 1=一位小数, 2=两位小数）
        raw_dot = field.get("dot")
        if raw_dot is not None and str(raw_dot).strip() != "":
            try:
                payload["dot"] = int(raw_dot)
            except (ValueError, TypeError):
                payload["dot"] = 2
        else:
            payload["dot"] = 2
        # unit: 后缀/单位（如 % 元 天 小时），写入 advancedSetting
        raw_unit = str(field.get("unit", "") or "").strip()
        if raw_unit:
            payload["advancedSetting"] = {"unit": raw_unit, "unitpos": "0"}
        if ftype == "Number":
            payload["precision"] = payload["dot"]
    elif ftype in ("SingleSelect", "MultipleSelect", "Dropdown"):
        payload["options"] = parse_select_options_from_field(field)
        # 收纳显示方式：单选 showtype=0（下拉），多选 checktype=1（下拉）
        if ftype == "SingleSelect":
            payload["advancedSetting"] = {"sorttype": "zh", "showtype": "0"}
        elif ftype == "MultipleSelect":
            payload["advancedSetting"] = {"sorttype": "zh", "checktype": "1"}
    elif ftype == "Collaborator":
        payload["subType"] = 0  # 单选成员
    elif ftype == "Relation":
        # Relation 统一在第二阶段处理
        pass
    return payload


# 开放平台 CreateWorksheet 支持的基础类型白名单（其余全部 deferred）
# 来源：API 实测，极保守白名单——逐步测试通过：Text/Number/SingleSelect/MultipleSelect/
#        Dropdown/Attachment/Date/DateTime/Collaborator/Rating/Checkbox
# 已知不支持（创建时）：Department/Phone/Money/Area/Cascade/AutoNumber/RichText/Score/Time/
#             Signature/QRCode/Embed/Section/Remark/Formula/FormulaDate/TextCombine/
#             OtherTableField/SubTable/Rollup/MoneyCapital/OrgRole/Location/Link
# NOTE: Department(27) 实测报"开放平台新建工作表不支持Department控件"，需 deferred 补加
_CREATE_WS_SUPPORTED_TYPES = {
    "Text",          # 2  - 单行文本
    "Number",        # 6  - 数值
    "SingleSelect",  # 9  - 单选
    "MultipleSelect",# 10 - 多选
    "Dropdown",      # 11 - 下拉
    "Attachment",    # 14 - 附件
    "Date",          # 15 - 日期
    "DateTime",      # 16 - 日期时间
    "Collaborator",  # 26 - 成员
    # "Department",  # 27 - 部门（API 不支持在 CreateWorksheet 中包含，走 deferred addFields）
    "Rating",        # 28 - 等级（星级）
    "Checkbox",      # 36 - 检查框
}

# 不在白名单的类型全部 deferred，创建后通过 addFields 补加
def _is_deferred_type(ftype: str) -> bool:
    return ftype not in _CREATE_WS_SUPPORTED_TYPES


def split_fields(fields: List[dict]) -> (List[dict], List[dict], List[dict]):
    """返回 (normal_fields, relation_fields, deferred_fields)。
    deferred_fields 是开放平台不支持在创建时包含的字段（如 AutoNumber），
    需在工作表创建成功后通过 EDIT_WS_ENDPOINT addFields 补加。
    """
    normal = []
    relation = []
    deferred = []
    title_set = False

    for fld in fields:
        ftype = str(fld.get("type", "Text")).strip()
        if ftype == "Relation":
            relation.append(fld)
            continue
        if _is_deferred_type(ftype):
            payload = build_field_payload(fld, is_first_text_title=False)
            deferred.append(payload)
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

    return normal, relation, deferred


def build_relationship_rules(plan: dict) -> List[dict]:
    """
    从规划 JSON 的 relationships 构建约束：
    - 仅允许 1-1 / 1-N
    - 保留每一条关系规则，避免同一对表的多字段关系被吞掉
    """
    relationships = plan.get("relationships", [])
    if not isinstance(relationships, list):
        return []

    rules: List[dict] = []
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
        rules.append(
            {
                "from": src,
                "to": dst,
                "cardinality": cardinality,
                "field": field_name,
                "pair_key": tuple(sorted((src, dst))),
            }
        )
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


def _pick_field_meta(
    candidates: Dict[Tuple[str, str], List[dict]],
    source: str,
    target: str,
    fallback_name: str,
    preferred_name: str = "",
) -> dict:
    arr = candidates.get((source, target), [])
    if preferred_name:
        preferred_name = preferred_name.strip()
        for picked in arr:
            field_name = str(picked.get("field_name", "")).strip()
            if field_name == preferred_name:
                return {"name": field_name, "required": bool(picked.get("required", False))}
    if arr:
        picked = arr[0]
        field_name = str(picked.get("field_name", "")).strip() or fallback_name
        return {"name": field_name, "required": bool(picked.get("required", False))}
    return {"name": fallback_name, "required": False}


def normalize_relation_plan(worksheets: List[dict], relationship_rules: List[dict]) -> List[dict]:
    """
    把关系规范化为“每条业务关系对应一条主 Relation 字段”。
    规则：
    - relationship_rules 为权威来源（若存在）
    - 1-N 一律落在多端表(to) -> 一端表(from)，subType=1
    - 1-1 在当前 API 创建方式下也落为单向主字段 + 系统反向字段
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
    for index, rule in enumerate(relationship_rules):
        src = str(rule.get("from", "")).strip()
        dst = str(rule.get("to", "")).strip()
        pair_key = tuple(sorted((src, dst)))
        cardinality = str(rule.get("cardinality", "1-N")).strip().upper() or "1-N"
        rel_field_name = str(rule.get("field", "")).strip()
        if src not in ws_names or dst not in ws_names:
            raise ValueError(f"relationships 引用了不存在的工作表: {src} -> {dst}")

        if cardinality == "1-N":
            # from(一) -> to(多)  ==> 字段应建在 to(多) 指向 from(一)
            relation_source = dst
            relation_target = src
        elif cardinality == "1-1":
            # 1-1 在当前创建策略下也只创建一条主字段。
            # 优先复用声明字段所在方向，其次复用已存在候选方向。
            fwd_has_named = any(
                str(item.get("field_name", "")).strip() == rel_field_name for item in candidates.get((src, dst), [])
            )
            rev_has_named = any(
                str(item.get("field_name", "")).strip() == rel_field_name for item in candidates.get((dst, src), [])
            )
            fwd_exists = bool(candidates.get((src, dst)))
            rev_exists = bool(candidates.get((dst, src)))
            if rev_has_named and not fwd_has_named:
                relation_source, relation_target = dst, src
            elif fwd_has_named and not rev_has_named:
                relation_source, relation_target = src, dst
            elif fwd_exists and not rev_exists:
                relation_source, relation_target = src, dst
            elif rev_exists and not fwd_exists:
                relation_source, relation_target = dst, src
            else:
                relation_source, relation_target = src, dst
        else:
            raise ValueError(f"不支持的关系类型: {cardinality}（仅允许 1-1 或 1-N）")

        fallback_name = rel_field_name or f"关联{relation_target}"
        meta = _pick_field_meta(
            candidates,
            relation_source,
            relation_target,
            fallback_name,
            preferred_name=rel_field_name,
        )
        normalized.append(
            {
                "rule_index": index,
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
            # 双向候选但未在 relationships 中声明：自动选择字母序较小的一方作为多端（source），
            # 避免 N-N 的同时不阻断流程。若需精确控制请在 relationships 中明确声明 cardinality。
            print(
                f"[warn] 未声明 relationships 的双向 Relation: {a}<->{b}，"
                "自动选择方向（按字母序）。建议在 relationships 中明确声明 cardinality。",
                file=sys.stderr,
            )
            source, target = sorted(orientations)[0]
        else:
            source, target = next(iter(orientations))
        fallback_fields = candidates.get((source, target), []) or [{"field_name": f"关联{target}", "required": False}]
        for meta in fallback_fields:
            normalized.append(
                {
                    "pair_key": pair_key,
                    "source": source,
                    "target": target,
                    "field_name": str(meta.get("field_name", "")).strip() or f"关联{target}",
                    "required": bool(meta.get("required", False)),
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
    last_error: Optional[dict] = None
    for attempt in range(1, 6):
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()
        if data.get("success"):
            data["skipped_relations"] = []
            return data
        last_error = data if isinstance(data, dict) else {"raw": data}
        error_msg = str(last_error.get("error_msg", "")).strip()
        if error_msg not in RELATION_UPDATE_RETRYABLE_ERRORS or attempt == 5:
            break
        time.sleep(min(0.6 * attempt, 2.0))
    raise RuntimeError(f"补充关联字段失败 [{worksheet_name}]: {last_error}")


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
    normalized_relations: List[dict],
) -> dict:
    """
    创建后校验：
    - 每条主 Relation 字段都必须落地成功（source -> target, subType=1）
    - 非自关联字段必须能看到系统生成的反向字段
    - subType 仅允许 1 或 2
    """
    id_to_name = {wid: name for name, wid in name_to_id.items()}
    pair_to_edges: Dict[Tuple[str, str], List[dict]] = {}
    relation_edges: List[dict] = []

    def _fetch_and_extract(item):
        source_name, source_id = item
        ws = fetch_worksheet_detail(base_url, headers, source_id)
        fields = ws.get("fields", [])
        edges = []
        if not isinstance(fields, list):
            return source_name, edges
        for field in fields:
            if not isinstance(field, dict):
                continue
            if str(field.get("type", "")).strip() != "Relation":
                continue
            target_id = str(field.get("dataSource", "")).strip()
            target_name = id_to_name.get(target_id) or f"[external:{target_id}]"
            sub_type = int(field.get("subType", 0) or 0)
            if sub_type not in (1, 2):
                raise RuntimeError(
                    f"检测到非法 Relation subType: {source_name}.{field.get('name')} -> {target_name}, subType={sub_type}"
                )
            edges.append({
                "source": source_name,
                "target": target_name,
                "field": str(field.get("name", "")).strip(),
                "subType": sub_type,
            })
        return source_name, edges

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_fetch_and_extract, item) for item in name_to_id.items()]
        for future in as_completed(futures):
            _, edges = future.result()
            for edge in edges:
                relation_edges.append(edge)
                if edge["target"].startswith("[external:"):
                    continue
                pair_key = tuple(sorted((edge["source"], edge["target"])))
                pair_to_edges.setdefault(pair_key, []).append(edge)

    violations = []
    notes: List[str] = []
    for spec in normalized_relations:
        src = str(spec.get("source", "")).strip()
        dst = str(spec.get("target", "")).strip()
        field_name = str(spec.get("field_name", "")).strip()
        card = str(spec.get("cardinality", "1-N")).strip().upper() or "1-N"
        if not src or not dst or not field_name:
            violations.append({"spec": spec, "reason": "invalid_normalized_relation"})
            continue

        primary_matches = [
            e
            for e in relation_edges
            if e["source"] == src and e["target"] == dst and int(e["subType"]) == 1 and e["field"] == field_name
        ]
        if not primary_matches:
            violations.append(
                {
                    "spec": {"source": src, "target": dst, "field_name": field_name, "cardinality": card},
                    "reason": "missing_primary_relation_field",
                }
            )
            continue

        if src != dst:
            reverse_matches = [
                e
                for e in relation_edges
                if e["source"] == dst and e["target"] == src and int(e["subType"]) in (1, 2)
            ]
            if not reverse_matches:
                violations.append(
                    {
                        "spec": {"source": src, "target": dst, "field_name": field_name, "cardinality": card},
                        "reason": "missing_reverse_relation_field",
                    }
                )

        if card == "1-1":
            notes.append(
                f"字段 {src}.{field_name} 声明为 1-1，但当前接口创建后反向字段通常为多选展示，未做反向单选强校验。"
            )

    if violations:
        # 降级为警告，不抛出异常，避免阻断 result 文件输出和后续分组移动
        print(f"  ⚠ 关系校验发现 {len(violations)} 个问题（已记录，不中断流程）: {violations}")

    return {
        "checked_pairs": len(pair_to_edges),
        "relation_edges": relation_edges,
        "violations": violations,
        "notes": notes,
    }


_TYPE_NAME_MAP = {
    "Text": 2, "Number": 6, "SingleSelect": 9, "MultipleSelect": 10,
    "Dropdown": 11, "Attachment": 14, "Date": 15, "DateTime": 16,
    "Collaborator": 26, "Department": 27, "Rating": 28, "Checkbox": 36,
    "Phone": 3, "Money": 8, "Email": 5, "Area": 24, "RichText": 41,
    "AutoNumber": 33, "Formula": 31, "Score": 47, "Remark": 49,
}


def _type_name_to_int(type_name: str) -> int:
    """将字段类型名称转为整数类型编号，未知类型默认返回 2（Text）。"""
    return _TYPE_NAME_MAP.get(type_name, 2)


def _fetch_real_fields(base_url: str, headers: dict, worksheet_id: str) -> list:
    """
    通过 v3 API 获取工作表的实际字段列表。
    返回 [{controlId, controlName, controlType}]，跳过 Relation/SubTable/Rollup 类型。
    """
    url = base_url.rstrip("/") + GET_WS_ENDPOINT.format(worksheet_id=worksheet_id)
    resp = requests.get(url, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        print(f"[warn] 获取工作表字段失败: {worksheet_id}, resp={data}")
        return []
    ws_data = data.get("data", {})
    fields = ws_data.get("fields", [])
    if not isinstance(fields, list):
        return []
    # 跳过 Relation(29), SubTable(34), Rollup(37)
    skip_types = {29, 34, 37}
    result = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        ctype = int(f.get("type", 0) or 0)
        if ctype in skip_types:
            continue
        result.append({
            "controlId": str(f.get("controlId", "")),
            "controlName": str(f.get("name", "")),
            "controlType": ctype,
        })
    return result


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
    parser.add_argument("--page-registry", default="", help="page_registry.json 路径")
    parser.add_argument("--app-name", default="", help="应用名称（图表规划用）")
    args = parser.parse_args()

    # 加载 page_registry（图表回调所需）
    page_registry = None
    ai_config = None
    if args.page_registry and Path(args.page_registry).exists():
        page_registry = load_json(Path(args.page_registry))
        from ai_utils import load_ai_config
        ai_config = load_ai_config()
        pages = page_registry.get("pages", [])
        print(f"[page-registry] 已加载 {len(pages)} 个页面")

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

    validate_plan_structure(plan)
    worksheets = plan.get("worksheets", [])
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
        normal_fields, relation_fields, deferred_fields = split_fields(fields if isinstance(fields, list) else [])
        preview.append(
            {
                "name": name,
                "normal_fields_count": len(normal_fields),
                "deferred_fields_count": len(deferred_fields),
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

    # Phase 1: 并发创建基础工作表（不含 Relation 和 deferred 字段）
    def _create_one_ws(ws):
        ws_name = str(ws.get("name", "")).strip() or "未命名工作表"
        fields = ws.get("fields", [])
        normal_fields, relation_fields, deferred_fields = split_fields(fields if isinstance(fields, list) else [])
        result = create_worksheet(args.base_url, headers, ws_name, normal_fields)
        worksheet_id = result.get("data", {}).get("worksheetId")
        if not worksheet_id:
            raise RuntimeError(f"创建工作表后未返回 worksheetId: {ws_name} / {result}")
        return ws_name, worksheet_id, result, relation_fields, deferred_fields

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(_create_one_ws, ws): ws for ws in worksheets}
        for future in as_completed(futures):
            ws_name, worksheet_id, result, relation_fields, deferred_fields = future.result()
            # 摘要：工作表名 + 字段列表
            ws_obj = futures[future]
            all_fields = []
            for f in (ws_obj.get("fields", []) if isinstance(ws_obj.get("fields"), list) else []):
                if isinstance(f, dict):
                    fname = str(f.get("name", "") or f.get("controlName", "")).strip()
                    ftype = str(f.get("type", "")).strip()
                    if fname:
                        all_fields.append(f"{fname}({ftype})" if ftype else fname)
            log_summary(f"✓ 工作表「{ws_name}」已创建（{len(all_fields)} 个字段）")
            if all_fields:
                log_summary(f"  {' | '.join(all_fields)}")
            name_to_id[ws_name] = worksheet_id
            create_results.append({"name": ws_name, "worksheetId": worksheet_id, "result": result})
            relations_todo.append({
                "name": ws_name,
                "worksheetId": worksheet_id,
                "relation_fields": relation_fields,
                "deferred_fields": deferred_fields,
            })

    # Phase 1.5: 并发回填 deferred 字段（开放平台不支持在创建时包含的字段）
    # 注意：逐字段发送，避免单个不支持的类型导致整批失败
    def _add_deferred_one(item):
        import sys as _sys
        ws_name = item["name"]
        ws_id = item["worksheetId"]
        deferred = item.get("deferred_fields", [])
        if not deferred:
            return None
        url = args.base_url.rstrip("/") + EDIT_WS_ENDPOINT.format(worksheet_id=ws_id)
        ok_count = 0
        for field in deferred:
            payload = {"addFields": [field]}
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            data = resp.json()
            if data.get("success"):
                ok_count += 1
            else:
                fname = field.get("controlName") or field.get("name") or str(field.get("type", "?"))
                print(f"[warn] 补加 deferred 字段失败 [{ws_name}]「{fname}」: {data}", file=_sys.stderr)
        return {"name": ws_name, "worksheetId": ws_id, "deferred_count": ok_count, "success": ok_count > 0}

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_add_deferred_one, item) for item in relations_todo]
        for future in as_completed(futures):
            future.result()  # 失败已在函数内打印警告，不中断主流程

    # Phase 1.6: 为每个 Page 规划并创建图表（需要 page_registry）
    if page_registry and ai_config:
        from executors.create_page_charts import plan_and_create_page_charts

        auth_config_path = os.environ.get("AUTH_CONFIG_PATH", "")
        sem = threading.Semaphore(2)

        # 构建 ws_name -> ws_info 映射（聚合已创建工作表的字段）
        ws_fields_map: dict = {}
        for item in relations_todo:
            ws_name = item["name"]
            ws_id = item["worksheetId"]
            real_fields = _fetch_real_fields(args.base_url, headers, ws_id)
            if real_fields:
                ws_fields_map[ws_name] = {
                    "worksheetId": ws_id,
                    "worksheetName": ws_name,
                    "fields": real_fields,
                    "views": [],
                }

        # 构建 worksheets_by_id（validate_plan 需要）
        worksheets_by_id = {
            info["worksheetId"]: info
            for info in ws_fields_map.values()
        }

        # 逐 Page 规划+创建图表（串行，避免并发写同一 Page 冲突）
        pages = page_registry.get("pages", [])
        total_charts = 0
        for page_entry in pages:
            if not isinstance(page_entry, dict):
                continue
            page_result = plan_and_create_page_charts(
                page_entry=page_entry,
                ws_fields_map=ws_fields_map,
                app_id=app_id,
                app_name=getattr(args, "app_name", "") or "",
                auth_config_path=auth_config_path,
                ai_config=ai_config,
                gemini_semaphore=sem,
                worksheets_by_id=worksheets_by_id,
            )
            total_charts += page_result.get("charts_created", 0)

        print(f"  ✔ Phase 1.6 图表: {len(pages)} 个 Page 共生成 {total_charts} 个图表")

    # Phase 2: 并发回填关联字段
    relation_results = []

    def _add_relations_one(item):
        ws_name = item["name"]
        ws_id = item["worksheetId"]
        relation_specs = relation_plan_by_source.get(ws_name, [])
        if not relation_specs:
            return None
        result = add_relation_fields(args.base_url, headers, ws_id, ws_name, relation_specs, name_to_id)
        return {"name": ws_name, "worksheetId": ws_id, "relation_fields_count": len(relation_specs), "result": result}

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(_add_relations_one, item) for item in relations_todo]
        for future in as_completed(futures):
            r = future.result()
            if r is not None:
                relation_results.append(r)

    verification = verify_relation_cardinality(args.base_url, headers, name_to_id, normalized_relations)

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
