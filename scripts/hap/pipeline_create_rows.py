#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互式批量造数流水线：
1) 选择应用（Y=全选，序号=部分，其他取消）
2) 选择工作表（Y=全选，序号=部分，其他取消）
3) 输入记录数量
4) 拉取字段结构并保存 JSON
5) 调用 Gemini 生成可录入记录 JSON
6) 调用批量新增接口写入记录
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
SCHEMA_DIR = OUTPUT_ROOT / "row_seed_schemas"
PLAN_DIR = OUTPUT_ROOT / "row_seed_plans"
RESULT_DIR = OUTPUT_ROOT / "row_seed_results"
GEMINI_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "gemini_auth.json"
DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_COLLABORATOR_ACCOUNT_ID = "a020cd58-b50b-4fa2-b33c-7dd877c805bd"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
WORKSHEET_DETAIL_URL = "https://api.mingdao.com/v3/app/worksheets/{worksheet_id}"
BATCH_CREATE_URL = "https://api.mingdao.com/v3/app/worksheets/{worksheet_id}/rows/batch"
PATCH_ROW_URL = "https://api.mingdao.com/v3/app/worksheets/{worksheet_id}/rows/{row_id}"
ROWS_LIST_URL = "https://api.mingdao.com/v3/app/worksheets/{worksheet_id}/rows/list"


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_gemini_api_key() -> str:
    data = load_json(GEMINI_CONFIG_PATH)
    api_key = str(data.get("api_key", "")).strip()
    if not api_key:
        raise ValueError(f"Gemini 配置缺少 api_key: {GEMINI_CONFIG_PATH}")
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


def parse_selection(text: str, max_index: int) -> List[int]:
    parts = [p for p in re.split(r"[^\d]+", text) if p]
    if not parts:
        return []
    out: List[int] = []
    for p in parts:
        idx = int(p)
        if idx < 1 or idx > max_index:
            raise ValueError(f"序号超出范围: {idx}（有效范围 1-{max_index}）")
        if idx not in out:
            out.append(idx)
    return out


def choose_indexes(prompt: str, items_count: int) -> Optional[List[int]]:
    """
    返回：
    - list[int]：所选索引（1-based）
    - None：取消
    """
    choice = input(prompt).strip()
    if choice == "" or choice.lower() == "y":
        return list(range(1, items_count + 1))
    try:
        picked = parse_selection(choice, items_count)
    except ValueError:
        return None
    if not picked:
        return None
    return picked


def load_app_auth_rows() -> List[dict]:
    rows: List[dict] = []
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload = data.get("data")
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            app_id = str(row.get("appId", "")).strip()
            app_key = str(row.get("appKey", "")).strip()
            sign = str(row.get("sign", "")).strip()
            if not app_id or not app_key or not sign:
                continue
            x = dict(row)
            x["_auth_path"] = str(path.resolve())
            rows.append(x)
    if not rows:
        raise FileNotFoundError(f"未找到可用授权文件：{APP_AUTH_DIR}")
    # 按 appId 去重，仅保留最新
    dedup = {}
    for r in rows:
        app_id = str(r.get("appId", "")).strip()
        if app_id not in dedup:
            dedup[app_id] = r
    return list(dedup.values())


def fetch_app_meta(app_key: str, sign: str) -> dict:
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json, text/plain, */*"}
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app = data.get("data", {})
    if not isinstance(app, dict):
        raise RuntimeError(f"应用信息格式错误: {data}")
    return app


def fetch_worksheets(app_key: str, sign: str) -> List[dict]:
    app_meta = fetch_app_meta(app_key, sign)
    worksheets: List[dict] = []

    def walk_sections(section: dict):
        section_id = str(section.get("id", ""))
        section_name = str(section.get("name", ""))
        for item in section.get("items", []) or []:
            if item.get("type") == 0:
                worksheets.append(
                    {
                        "workSheetId": str(item.get("id", "")),
                        "workSheetName": str(item.get("name", "")),
                        "appSectionId": section_id,
                        "appSectionName": section_name,
                    }
                )
        for child in section.get("childSections", []) or []:
            walk_sections(child)

    for sec in app_meta.get("sections", []) or []:
        walk_sections(sec)
    return worksheets


def fetch_worksheet_schema(app_key: str, sign: str, worksheet_id: str) -> dict:
    headers = {"HAP-Appkey": app_key, "HAP-Sign": sign, "Accept": "application/json, text/plain, */*"}
    url = WORKSHEET_DETAIL_URL.format(worksheet_id=worksheet_id)
    resp = requests.get(url, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取工作表结构失败: worksheetId={worksheet_id}, resp={data}")
    ws = data.get("data", {})
    if not isinstance(ws, dict):
        raise RuntimeError(f"工作表结构格式错误: worksheetId={worksheet_id}, resp={data}")
    fields = ws.get("fields", [])
    if not isinstance(fields, list):
        fields = []
    return {
        "worksheetId": worksheet_id,
        "worksheetName": str(ws.get("name", "")),
        "fields": fields,
    }


def simplify_field(field: dict) -> dict:
    field_type = str(field.get("type", "")).strip()
    options = []
    raw_opts = field.get("options")
    if isinstance(raw_opts, list):
        for o in raw_opts:
            if not isinstance(o, dict):
                continue
            key = str(o.get("key", "")).strip()
            value = str(o.get("value", "")).strip()
            if key and value and not o.get("isDeleted", False):
                options.append({"key": key, "value": value})
    return {
        "id": str(field.get("id", "")).strip(),
        "name": str(field.get("name", "")).strip(),
        "type": field_type,
        "subType": int(field.get("subType", 0) or 0),
        "required": bool(field.get("required", False)),
        "readOnly": bool(field.get("isReadOnly", False)),
        "hidden": bool(field.get("isHidden", False)),
        "isTitle": bool(field.get("isTitle", False)),
        "dataSource": str(field.get("dataSource", "")).strip(),
        "options": options,
    }


def build_gemini_prompt(app_name: str, worksheet_name: str, row_count: int, fields: List[dict]) -> str:
    return f"""
你是企业业务数据录入助手。请基于字段定义，生成可直接用于 API 写入的数据。

应用名：{app_name}
工作表：{worksheet_name}
需要生成记录数：{row_count}

字段定义（仅可写字段）：
{json.dumps(fields, ensure_ascii=False, indent=2)}

输出要求（只输出 JSON，不要 markdown）：
{{
  "rows": [
    {{
      "fields": [
        {{"id": "字段ID", "value": "字段值"}}
      ]
    }}
  ]
}}

约束：
1) rows 数量必须等于 {row_count}。
2) 字段值必须和字段类型兼容：
   - Text: 字符串
   - Number: 数字
   - SingleSelect: 传 option 的 key（字符串）
   - MultipleSelect: 传 option key 数组
   - Date/DateTime: 传 YYYY-MM-DD 或 YYYY-MM-DD HH:mm
   - Collaborator: 传 accountId 数组（例如 ["{DEFAULT_COLLABORATOR_ACCOUNT_ID}"]）
   - Relation: 传 rowId 数组（本脚本后续会回填，阶段A可留空数组）
   - Checkbox: 0 或 1
3) 对 required=true 的字段必须给值。
4) 不要输出无关字段。
""".strip()


def normalize_value_by_type(value: Any, field: dict) -> Any:
    t = field["type"]
    if t == "Number":
        try:
            return float(value)
        except Exception:
            return 1
    if t == "SingleSelect":
        option_keys = [o["key"] for o in field.get("options", [])]
        option_values = [o["value"] for o in field.get("options", [])]
        if isinstance(value, str):
            v = value.strip()
            if v in option_keys:
                return v
            if v in option_values:
                idx = option_values.index(v)
                return option_keys[idx]
        return option_keys[0] if option_keys else ""
    if t == "MultipleSelect":
        option_keys = [o["key"] for o in field.get("options", [])]
        option_values = [o["value"] for o in field.get("options", [])]
        vals = value if isinstance(value, list) else [value]
        out = []
        for x in vals:
            if isinstance(x, str):
                v = x.strip()
                if v in option_keys and v not in out:
                    out.append(v)
                elif v in option_values:
                    idx = option_values.index(v)
                    key = option_keys[idx]
                    if key not in out:
                        out.append(key)
        if not out and option_keys:
            out = [option_keys[0]]
        return out
    if t in ("Date", "DateTime"):
        return str(value).strip()
    if t == "Checkbox":
        if str(value).strip() in ("1", "true", "True", "yes", "Y", "y"):
            return 1
        return 0
    if t == "Collaborator":
        # 业务规则：人员字段统一写固定账号，忽略模型返回
        return [DEFAULT_COLLABORATOR_ACCOUNT_ID]
    if t == "Relation":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []
    return str(value).strip()


def generate_rows_by_gemini(
    client: genai.Client,
    model: str,
    app_name: str,
    worksheet_name: str,
    row_count: int,
    writable_fields: List[dict],
) -> List[dict]:
    prompt = build_gemini_prompt(app_name, worksheet_name, row_count, writable_fields)
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3),
    )
    result = extract_json(resp.text or "")
    rows = result.get("rows", [])
    if not isinstance(rows, list):
        rows = []

    field_map = {f["id"]: f for f in writable_fields}

    normalized_rows = []
    for i in range(row_count):
        src = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
        src_fields = src.get("fields", [])
        field_values = {}
        if isinstance(src_fields, list):
            for it in src_fields:
                if not isinstance(it, dict):
                    continue
                fid = str(it.get("id", "")).strip()
                if fid in field_map:
                    field_values[fid] = normalize_value_by_type(it.get("value", ""), field_map[fid])

        out_fields = []
        for f in writable_fields:
            fid = f["id"]
            if f["type"] == "Collaborator":
                # 业务规则：只要是人员字段，统一填固定账号
                out_fields.append({"id": fid, "value": [DEFAULT_COLLABORATOR_ACCOUNT_ID]})
                continue
            val = field_values.get(fid)
            if val in ("", [], None):
                # 人员字段默认写入固定账号
                # 必填字段兜底
                if f["required"]:
                    t = f["type"]
                    if t == "Number":
                        val = 1
                    elif t == "SingleSelect":
                        opts = [o["key"] for o in f.get("options", [])]
                        val = opts[0] if opts else ""
                    elif t == "MultipleSelect":
                        opts = [o["key"] for o in f.get("options", [])]
                        val = [opts[0]] if opts else []
                    elif t == "Checkbox":
                        val = 1
                    elif t in ("Date", "DateTime"):
                        val = "2026-01-01"
                    elif t == "Collaborator":
                        val = [DEFAULT_COLLABORATOR_ACCOUNT_ID]
                    elif t == "Relation":
                        val = []
                    else:
                        val = f"{f['name']}_{i+1}"
                else:
                    continue
            out_fields.append({"id": fid, "value": val})

        normalized_rows.append({"fields": out_fields})
    return normalized_rows


def topo_sort_targets(schema_items: List[dict]) -> List[Tuple[str, str]]:
    """
    基于 Relation(dataSource) 关系做拓扑排序：
    - 节点: (appId, workSheetId)
    - 边: 当前表 -> 目标表（表示当前表依赖目标表，目标表应先创建）
    """
    nodes = {(s["appId"], s["workSheetId"]) for s in schema_items}
    deps: Dict[Tuple[str, str], set] = {n: set() for n in nodes}
    reverse: Dict[Tuple[str, str], set] = {n: set() for n in nodes}
    for s in schema_items:
        cur = (s["appId"], s["workSheetId"])
        for f in s.get("relationFields", []):
            target_ws = str(f.get("dataSource", "")).strip()
            if not target_ws:
                continue
            target = (s["appId"], target_ws)
            if target in nodes and target != cur:
                deps[cur].add(target)
                reverse[target].add(cur)

    indegree = {n: len(deps[n]) for n in nodes}
    queue = [n for n in nodes if indegree[n] == 0]
    ordered: List[Tuple[str, str]] = []
    while queue:
        n = queue.pop(0)
        ordered.append(n)
        for child in reverse[n]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(ordered) != len(nodes):
        # 存在环依赖时，保留已排序部分，剩余按输入顺序追加
        remaining = [n for n in nodes if n not in set(ordered)]
        ordered.extend(remaining)
    return ordered


def fetch_existing_row_ids(app_key: str, sign: str, worksheet_id: str, limit: int = 200) -> List[str]:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    payload = {
        "pageIndex": 1,
        "pageSize": min(max(limit, 1), 1000),
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
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("rowid", "")).strip()
        if rid:
            out.append(rid)
    return out


def patch_row_fields(
    app_key: str,
    sign: str,
    worksheet_id: str,
    row_id: str,
    fields: List[dict],
    dry_run: bool,
) -> dict:
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


def batch_create_rows(app_key: str, sign: str, worksheet_id: str, rows: List[dict], dry_run: bool) -> dict:
    url = BATCH_CREATE_URL.format(worksheet_id=worksheet_id)
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    payload = {"rows": rows}
    if dry_run:
        return {"dry_run": True, "payload_preview_rows": len(rows)}
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "text": resp.text}
    return data


def fetch_row_ids_page(app_key: str, sign: str, worksheet_id: str, page_index: int, page_size: int = 1000) -> List[str]:
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
    row_ids = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("rowid", "")).strip()
        if rid:
            row_ids.append(rid)
    return row_ids


def fetch_all_row_ids(app_key: str, sign: str, worksheet_id: str, max_pages: int = 200) -> List[str]:
    out: List[str] = []
    for page in range(1, max_pages + 1):
        page_ids = fetch_row_ids_page(app_key, sign, worksheet_id, page_index=page, page_size=1000)
        if not page_ids:
            break
        out.extend(page_ids)
        if len(page_ids) < 1000:
            break
    # 去重保序
    uniq = []
    for rid in out:
        if rid not in uniq:
            uniq.append(rid)
    return uniq


def batch_delete_rows(app_key: str, sign: str, worksheet_id: str, row_ids: List[str], dry_run: bool) -> dict:
    if dry_run:
        return {"dry_run": True, "worksheetId": worksheet_id, "toDelete": len(row_ids)}
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
    }
    url = BATCH_CREATE_URL.format(worksheet_id=worksheet_id)
    payload = {"rowIds": row_ids, "permanent": False}
    resp = requests.delete(url, headers=headers, json=payload, timeout=60)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


def main() -> None:
    parser = argparse.ArgumentParser(description="交互式批量生成并写入记录")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--dry-run", action="store_true", help="仅规划，不实际写入")
    parser.add_argument("--app-id", default="", help="可选，指定应用ID（传入后跳过应用选择交互）")
    parser.add_argument("--worksheet-ids", default="", help="可选，工作表ID列表（逗号分隔）或 all（跳过工作表选择交互）")
    parser.add_argument("--rows-per-table", type=int, default=0, help="可选，每张表创建记录数（正整数，传入后跳过数量输入）")
    parser.add_argument("--delete-history", default="", help="可选，是否删除历史记录：y 或 n（传入后跳过删除确认）")
    args = parser.parse_args()

    app_rows = load_app_auth_rows()
    apps = []
    for r in app_rows:
        app_id = str(r.get("appId", "")).strip()
        app_key = str(r.get("appKey", "")).strip()
        sign = str(r.get("sign", "")).strip()
        app_name = str(r.get("name", "")).strip()
        if not app_id or not app_key or not sign:
            continue
        # 尝试取真实应用名
        try:
            meta = fetch_app_meta(app_key, sign)
            app_name = str(meta.get("name", "")).strip() or app_name or app_id
        except Exception:
            app_name = app_name or app_id
        apps.append(
            {
                "appId": app_id,
                "appName": app_name,
                "appKey": app_key,
                "sign": sign,
                "authPath": r.get("_auth_path", ""),
            }
        )
    if not apps:
        raise RuntimeError("没有可用应用")

    if args.app_id.strip():
        target = next((a for a in apps if a["appId"] == args.app_id.strip()), None)
        if not target:
            raise ValueError(f"--app-id 未匹配到应用: {args.app_id.strip()}")
        picked_apps = [target]
    else:
        print("可选应用：")
        print("序号 | 应用名称 | 应用ID")
        for i, app in enumerate(apps, start=1):
            print(f"{i}. {app['appName']} | {app['appId']}")

        picked_app_idx = choose_indexes(
            "请选择应用：默认Y全选；输入序号(如 1,2,3 / 1.2.3)；其他任意输入取消: ",
            len(apps),
        )
        if not picked_app_idx:
            print("已取消。")
            return
        picked_apps = [apps[i - 1] for i in picked_app_idx]

    all_selected_targets = []
    worksheet_id_filter = str(args.worksheet_ids or "").strip()
    worksheet_id_set = set()
    if worksheet_id_filter and worksheet_id_filter.lower() != "all":
        worksheet_id_set = {x.strip() for x in worksheet_id_filter.split(",") if x.strip()}

    for app in picked_apps:
        ws_list = fetch_worksheets(app["appKey"], app["sign"])
        if not ws_list:
            print(f"应用无工作表，跳过: {app['appName']} ({app['appId']})")
            continue
        if worksheet_id_filter.lower() == "all":
            for ws in ws_list:
                all_selected_targets.append({"app": app, "worksheet": ws})
            continue
        if worksheet_id_set:
            picked = [ws for ws in ws_list if ws["workSheetId"] in worksheet_id_set]
            if not picked:
                raise ValueError(f"--worksheet-ids 在应用[{app['appName']}]下未匹配到任何工作表")
            for ws in picked:
                all_selected_targets.append({"app": app, "worksheet": ws})
            continue

        print(f"\n应用：{app['appName']} ({app['appId']})")
        print("序号 | 工作表名称 | 工作表ID")
        for i, ws in enumerate(ws_list, start=1):
            print(f"{i}. {ws['workSheetName']} | {ws['workSheetId']}")

        picked_ws_idx = choose_indexes(
            "请选择工作表：默认Y全选；输入序号(如 1,2,3 / 1.2.3)；其他任意输入取消: ",
            len(ws_list),
        )
        if not picked_ws_idx:
            print("已取消。")
            return
        for i in picked_ws_idx:
            all_selected_targets.append({"app": app, "worksheet": ws_list[i - 1]})

    if not all_selected_targets:
        print("没有选中的工作表，结束。")
        return

    if args.rows_per_table and args.rows_per_table > 0:
        row_count = int(args.rows_per_table)
    else:
        while True:
            cnt_raw = input("请输入每张表要创建的记录数量（正整数）: ").strip()
            if cnt_raw.isdigit() and int(cnt_raw) > 0:
                row_count = int(cnt_raw)
                break
            print("输入无效，请输入正整数。")

    # 最后一个问题：是否清空所选应用 + 所选工作表下历史记录
    if args.delete_history.strip():
        delete_choice = args.delete_history.strip()
    else:
        delete_choice = input("最后一个问题：是否删除所选应用和所选表下的所有历史记录？输入 y 删除，任意键取消: ").strip()
    deleted_history_summary = {
        "enabled": False,
        "dry_run": args.dry_run,
        "worksheets": [],
        "totalRowsPlannedDelete": 0,
        "totalWorksheetCount": 0,
    }
    if delete_choice.lower() == "y":
        deleted_history_summary["enabled"] = True
        for t in all_selected_targets:
            app = t["app"]
            ws = t["worksheet"]
            ws_id = ws["workSheetId"]
            existing_row_ids = fetch_all_row_ids(app["appKey"], app["sign"], ws_id)
            deleted_history_summary["totalRowsPlannedDelete"] += len(existing_row_ids)
            deleted_history_summary["totalWorksheetCount"] += 1
            if existing_row_ids:
                del_resp = batch_delete_rows(
                    app_key=app["appKey"],
                    sign=app["sign"],
                    worksheet_id=ws_id,
                    row_ids=existing_row_ids,
                    dry_run=args.dry_run,
                )
            else:
                del_resp = {"success": True, "error_code": 1, "message": "no rows"}
            deleted_history_summary["worksheets"].append(
                {
                    "appId": app["appId"],
                    "appName": app["appName"],
                    "workSheetId": ws_id,
                    "workSheetName": ws["workSheetName"],
                    "existingRows": len(existing_row_ids),
                    "response": del_resp,
                }
            )
        print("\n历史记录处理完成（摘要）")
        print(f"- 删除目标表数: {deleted_history_summary['totalWorksheetCount']}")
        print(f"- 计划删除记录数: {deleted_history_summary['totalRowsPlannedDelete']}")
        print(f"- dry-run: {args.dry_run}")
    else:
        print("\n已跳过历史记录删除。")

    # Step 3: 拉字段结构
    schema_items = []
    for t in all_selected_targets:
        app = t["app"]
        ws = t["worksheet"]
        schema = fetch_worksheet_schema(app["appKey"], app["sign"], ws["workSheetId"])
        simple_fields = [simplify_field(f) for f in schema["fields"] if isinstance(f, dict)]
        writable_fields = [f for f in simple_fields if f["id"] and not f["readOnly"] and not f["hidden"]]
        relation_fields = [f for f in writable_fields if f["type"] == "Relation"]
        # 仅回填 subType=1（单条）关系字段；跳过系统自动生成的反向多条字段，避免把 n 端写脏为多关联。
        relation_fields_to_patch = [f for f in relation_fields if int(f.get("subType", 0) or 0) == 1]
        skipped_relation_fields = [f for f in relation_fields if int(f.get("subType", 0) or 0) != 1]
        base_fields = [f for f in writable_fields if f["type"] != "Relation"]
        schema_items.append(
            {
                "appId": app["appId"],
                "appName": app["appName"],
                "appAuthJson": app["authPath"],
                "workSheetId": ws["workSheetId"],
                "workSheetName": ws["workSheetName"],
                "fields": simple_fields,
                "writableFields": writable_fields,
                "baseWritableFields": base_fields,
                "relationFields": relation_fields_to_patch,
                "skippedRelationFields": skipped_relation_fields,
            }
        )

    skipped_relation_fields_total = sum(len(s.get("skippedRelationFields", [])) for s in schema_items)
    if skipped_relation_fields_total > 0:
        print(f"\n已跳过 {skipped_relation_fields_total} 个非单条关联字段（仅回填 subType=1）。")

    schema_payload = {
        "rowCountPerWorksheet": row_count,
        "skippedRelationFieldsTotal": skipped_relation_fields_total,
        "targets": schema_items,
    }
    schema_path = (SCHEMA_DIR / f"row_seed_schema_{now_ts()}.json").resolve()
    write_json(schema_path, schema_payload)
    write_json((SCHEMA_DIR / "row_seed_schema_latest.json").resolve(), schema_payload)

    # Step 4: Gemini 规划记录（仅规划非关联字段；关联字段由真实 rowId 回填）
    client = genai.Client(api_key=load_gemini_api_key())
    plan_items = []
    for s in schema_items:
        rows = generate_rows_by_gemini(
            client=client,
            model=args.model,
            app_name=s["appName"],
            worksheet_name=s["workSheetName"],
            row_count=row_count,
            writable_fields=s["baseWritableFields"],
        )
        plan_items.append(
            {
                "appId": s["appId"],
                "appName": s["appName"],
                "appAuthJson": s["appAuthJson"],
                "workSheetId": s["workSheetId"],
                "workSheetName": s["workSheetName"],
                "baseRows": rows,
                "relationFields": s["relationFields"],
            }
        )
    plan_payload = {"rowCountPerWorksheet": row_count, "targets": plan_items}
    plan_path = (PLAN_DIR / f"row_seed_plan_{now_ts()}.json").resolve()
    write_json(plan_path, plan_payload)
    write_json((PLAN_DIR / "row_seed_plan_latest.json").resolve(), plan_payload)

    # Step 5: 写入（阶段A：非关联字段；阶段B：回填关联字段）
    app_auth_map: Dict[Tuple[str, str], dict] = {}
    invalid_selected_targets: List[dict] = []
    for item in all_selected_targets:
        app = item.get("app") if isinstance(item, dict) else None
        worksheet = item.get("worksheet") if isinstance(item, dict) else None
        app_id = str(app.get("appId", "")).strip() if isinstance(app, dict) else ""
        worksheet_id = str(worksheet.get("workSheetId", "")).strip() if isinstance(worksheet, dict) else ""
        if not app_id or not worksheet_id:
            invalid_selected_targets.append(item if isinstance(item, dict) else {"raw": str(item)})
            continue
        app_auth_map[(app_id, worksheet_id)] = item

    if invalid_selected_targets:
        print("\n警告：以下选中目标缺少 appId 或 workSheetId，已跳过：")
        for idx, bad in enumerate(invalid_selected_targets, start=1):
            print(f"- {idx}. {json.dumps(bad, ensure_ascii=False)}")

    results = []
    success_tables = 0
    unmatched_plan_targets = 0
    unmatched_examples = []
    # A. 非关联字段写入（按依赖拓扑顺序）
    plan_map = {(p["appId"], p["workSheetId"]): p for p in plan_items}
    ordered_keys = topo_sort_targets(schema_items)
    created_row_ids_map: Dict[Tuple[str, str], List[str]] = {}

    for key in ordered_keys:
        p = plan_map.get(key)
        if not p:
            continue
        key = (p["appId"], p["workSheetId"])
        if key not in app_auth_map:
            unmatched_plan_targets += 1
            if len(unmatched_examples) < 10:
                unmatched_examples.append(
                    {
                        "appId": p.get("appId", ""),
                        "workSheetId": p.get("workSheetId", ""),
                        "workSheetName": p.get("workSheetName", ""),
                    }
                )
            continue
        app = app_auth_map[key]["app"]
        resp = batch_create_rows(
            app_key=app["appKey"],
            sign=app["sign"],
            worksheet_id=p["workSheetId"],
            rows=p["baseRows"],
            dry_run=args.dry_run,
        )
        ok = bool(resp.get("success")) if isinstance(resp, dict) and "success" in resp else bool(resp.get("dry_run"))
        if ok:
            success_tables += 1
        created_row_ids = []
        if isinstance(resp, dict):
            data = resp.get("data")
            if isinstance(data, dict) and isinstance(data.get("rowIds"), list):
                created_row_ids = [str(x).strip() for x in data.get("rowIds", []) if str(x).strip()]
        created_row_ids_map[key] = created_row_ids
        results.append(
            {
                "appId": p["appId"],
                "appName": p["appName"],
                "workSheetId": p["workSheetId"],
                "workSheetName": p["workSheetName"],
                "plannedRows": len(p["baseRows"]),
                "phase": "base_create",
                "response": resp,
            }
        )

    # B. 构建可引用 rowId 池（优先使用新建 rowIds，不足则补充已有 rowIds）
    row_pool: Dict[Tuple[str, str], List[str]] = {}
    for key, target in app_auth_map.items():
        app = target["app"]
        ws = target["worksheet"]
        fresh = created_row_ids_map.get(key, [])
        existed = fetch_existing_row_ids(app["appKey"], app["sign"], ws["workSheetId"], limit=max(200, row_count * 5))
        merged = []
        for rid in fresh + existed:
            if rid and rid not in merged:
                merged.append(rid)
        row_pool[key] = merged

    relation_update_success = 0
    relation_update_total = 0
    relation_skip_total = 0

    # C. 回填关联字段：仅对当前批次创建出的记录进行 patch
    for key in ordered_keys:
        p = plan_map.get(key)
        if not p or key not in app_auth_map:
            continue
        app = app_auth_map[key]["app"]
        source_ws_id = p["workSheetId"]
        source_rows = created_row_ids_map.get(key, [])
        rel_fields = p.get("relationFields", [])
        if not source_rows or not rel_fields:
            continue

        for idx, row_id in enumerate(source_rows):
            patch_fields = []
            for rf in rel_fields:
                target_ws_id = str(rf.get("dataSource", "")).strip()
                fid = str(rf.get("id", "")).strip()
                if not target_ws_id or not fid:
                    relation_skip_total += 1
                    continue
                target_key = (p["appId"], target_ws_id)
                target_pool = row_pool.get(target_key, [])
                if not target_pool:
                    relation_skip_total += 1
                    continue
                if int(rf.get("subType", 1) or 1) == 2:
                    # 多条关联，取最多2个，尽量避免自循环
                    refs = []
                    first = target_pool[idx % len(target_pool)]
                    refs.append(first)
                    if len(target_pool) > 1:
                        second = target_pool[(idx + 1) % len(target_pool)]
                        if second != first:
                            refs.append(second)
                    patch_fields.append({"id": fid, "value": refs})
                else:
                    ref = target_pool[idx % len(target_pool)]
                    patch_fields.append({"id": fid, "value": [ref]})

            if not patch_fields:
                continue
            relation_update_total += 1
            patch_resp = patch_row_fields(
                app_key=app["appKey"],
                sign=app["sign"],
                worksheet_id=source_ws_id,
                row_id=row_id,
                fields=patch_fields,
                dry_run=args.dry_run,
            )
            ok = bool(patch_resp.get("success")) if isinstance(patch_resp, dict) and "success" in patch_resp else bool(
                patch_resp.get("dry_run")
            )
            if ok:
                relation_update_success += 1
            results.append(
                {
                    "appId": p["appId"],
                    "appName": p["appName"],
                    "workSheetId": source_ws_id,
                    "workSheetName": p["workSheetName"],
                    "rowId": row_id,
                    "phase": "relation_patch",
                    "patchedFieldCount": len(patch_fields),
                    "response": patch_resp,
                }
            )

    result_payload = {
        "dry_run": args.dry_run,
        "selectedApps": len(picked_apps),
        "selectedWorksheets": len(all_selected_targets),
        "invalidSelectedTargets": len(invalid_selected_targets),
        "validSelectedTargets": len(app_auth_map),
        "unmatchedPlanTargets": unmatched_plan_targets,
        "unmatchedPlanTargetExamples": unmatched_examples,
        "rowCountPerWorksheet": row_count,
        "successTables": success_tables,
        "skippedRelationFieldsTotal": skipped_relation_fields_total,
        "relationUpdateTotal": relation_update_total,
        "relationUpdateSuccess": relation_update_success,
        "relationSkipTotal": relation_skip_total,
        "historyDelete": deleted_history_summary,
        "schemaJson": str(schema_path),
        "planJson": str(plan_path),
        "results": results,
    }
    result_path = (RESULT_DIR / f"row_seed_result_{now_ts()}.json").resolve()
    write_json(result_path, result_payload)
    write_json((RESULT_DIR / "row_seed_result_latest.json").resolve(), result_payload)

    print("\n执行完成（摘要）")
    print(f"- 选择应用数: {len(picked_apps)}")
    print(f"- 选择工作表数: {len(all_selected_targets)}")
    print(f"- 有效目标数: {len(app_auth_map)}")
    print(f"- 无效目标数: {len(invalid_selected_targets)}")
    print(f"- 匹配失败目标数: {unmatched_plan_targets}")
    if unmatched_plan_targets > 0:
        print("- 提示: 存在计划项未匹配，请检查 appId/workSheetId 映射一致性")
    print(f"- 每表记录数: {row_count}")
    print(f"- 成功表数: {success_tables}/{len(all_selected_targets)}")
    print(f"- 关联回填成功: {relation_update_success}/{relation_update_total}")
    print(f"- 关联回填跳过字段数: {relation_skip_total}")
    print(f"- 字段结构文件: {schema_path}")
    print(f"- 记录规划文件: {plan_path}")
    print(f"- 执行结果文件: {result_path}")


if __name__ == "__main__":
    main()
