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
from typing import Dict, List, Optional

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "https://api.mingdao.com"
CREATE_WS_ENDPOINT = "/v3/app/worksheets"
EDIT_WS_ENDPOINT = "/v3/app/worksheets/{worksheet_id}"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"
WORKSHEET_CREATE_RESULT_DIR = OUTPUT_ROOT / "worksheet_create_results"


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
        payload["options"] = parse_select_options(str(field.get("description", "")))
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


def add_relation_fields(
    base_url: str,
    headers: dict,
    worksheet_id: str,
    worksheet_name: str,
    relation_fields: List[dict],
    name_to_id: Dict[str, str],
) -> dict:
    add_fields = []
    for fld in relation_fields:
        target_name = str(fld.get("relation_target", "")).strip()
        if not target_name:
            raise ValueError(f"工作表[{worksheet_name}] 字段[{fld.get('name')}] 缺少 relation_target")
        target_id = name_to_id.get(target_name)
        if not target_id:
            raise ValueError(f"工作表[{worksheet_name}] 字段[{fld.get('name')}] 目标表不存在: {target_name}")

        add_fields.append(
            {
                "name": str(fld.get("name", "")).strip() or "关联记录",
                "type": "Relation",
                "required": to_required(fld.get("required", False)),
                "dataSource": target_id,
                "subType": 1,  # 单条关联
                "relation": {"showFields": [], "bidirectional": False},
            }
        )

    if not add_fields:
        return {"success": True, "data": {"worksheetId": worksheet_id}}

    url = base_url.rstrip("/") + EDIT_WS_ENDPOINT.format(worksheet_id=worksheet_id)
    payload = {"addFields": add_fields}
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"补充关联字段失败 [{worksheet_name}]: {data}")
    return data


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

    preview = []
    for ws in worksheets:
        name = str(ws.get("name", "")).strip() or "未命名工作表"
        fields = ws.get("fields", [])
        normal_fields, relation_fields = split_fields(fields if isinstance(fields, list) else [])
        preview.append(
            {
                "name": name,
                "normal_fields_count": len(normal_fields),
                "relation_fields_count": len(relation_fields),
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
        relation_fields = item["relation_fields"]
        if not relation_fields:
            continue
        result = add_relation_fields(
            args.base_url,
            headers,
            ws_id,
            ws_name,
            relation_fields,
            name_to_id,
        )
        relation_results.append({"name": ws_name, "worksheetId": ws_id, "relation_fields_count": len(relation_fields), "result": result})

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    WORKSHEET_CREATE_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = (WORKSHEET_CREATE_RESULT_DIR / f"worksheet_create_result_{ts}.json").resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "app_id": app_id,
        "plan_json": str(plan_path),
        "app_auth_json": str(auth_path),
        "created_worksheets": create_results,
        "relation_updates": relation_results,
        "name_to_worksheet_id": name_to_id,
    }
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n已保存: {output_path}")


if __name__ == "__main__":
    main()
