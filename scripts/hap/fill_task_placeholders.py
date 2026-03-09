#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取模板文件中的占位符并生成 task.txt（纯本地模式，不调用任何网络接口）。

规则：
1) 先让用户选择应用（来自本地授权与历史产物）；
2) 自动填充 appId / 应用名称；
3) {工作表名称N} / {视图名称N} 自动随机填充（来自本地 JSON / 日志）；
4) 其他占位符交互输入（回车则给默认值，确保不残留 {}）。
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mock_data_common import choose_app

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_TASK_FILE = BASE_DIR / "record" / "task.txt"
DEFAULT_TEMPLATE_FILE = BASE_DIR / "record" / "task_template.txt"
OUTPUT_DIR = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_DIR / "app_authorizations"
APP_INVENTORY_DIR = OUTPUT_DIR / "app_inventory"
VIEW_CREATE_DIR = OUTPUT_DIR / "view_create_results"
VIEW_PLAN_DIR = OUTPUT_DIR / "view_plans"
LAYOUT_PLAN_DIR = OUTPUT_DIR / "worksheet_layout_plans"
TABLEVIEW_FILTER_PLAN_DIR = OUTPUT_DIR / "tableview_filter_plans"
TABLEVIEW_FILTER_APPLY_DIR = OUTPUT_DIR / "tableview_filter_apply_results"
RECORD_RUNS_DIR = BASE_DIR / "record" / "runs"


def extract_placeholders(text: str) -> List[str]:
    return re.findall(r"\{([^{}]+)\}", text)


def dedup_keep_order(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def choose_random(items: List[str], fallback: str) -> str:
    if not items:
        return fallback
    return random.choice(items)


def choose_unique(candidates: List[str], used: Set[str], label: str) -> str:
    available = [x for x in candidates if x and x not in used]
    if not available:
        raise RuntimeError(f"{label} 可选项不足，无法保证不重复。")
    chosen = random.choice(available)
    used.add(chosen)
    return chosen


def read_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_local_app_name(app_id: str) -> str:
    inv_file = APP_INVENTORY_DIR / f"app_inventory_{app_id}.json"
    if inv_file.exists():
        data = read_json_safe(inv_file)
        if isinstance(data, dict):
            apps = data.get("apps")
            if isinstance(apps, list):
                for app in apps:
                    if isinstance(app, dict) and str(app.get("appId", "")).strip() == app_id:
                        name = str(app.get("appName", "")).strip()
                        if name:
                            return name

    candidates = sorted((OUTPUT_DIR / "app_navi_style_updates").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        data = read_json_safe(path)
        if not isinstance(data, dict):
            continue
        if str(data.get("appId", "")).strip() == app_id:
            name = str(data.get("appName", "")).strip()
            if name:
                return name

    for base_dir, pattern in (
        (VIEW_CREATE_DIR, f"view_create_result_{app_id}_*.json"),
        (VIEW_PLAN_DIR, f"view_plan_{app_id}_*.json"),
        (LAYOUT_PLAN_DIR, "worksheet_layout_plan_pipeline_*.json"),
    ):
        for path in sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
            data = read_json_safe(path)
            if not isinstance(data, dict):
                continue
            for app in data.get("apps", []) if isinstance(data.get("apps"), list) else []:
                if not isinstance(app, dict):
                    continue
                if str(app.get("appId", "")).strip() != app_id:
                    continue
                name = str(app.get("appName", "")).strip()
                if name:
                    return name
            app_node = data.get("app")
            if isinstance(app_node, dict) and str(app_node.get("appId", "")).strip() == app_id:
                name = str(app_node.get("appName", "")).strip()
                if name:
                    return name

    return app_id


def load_local_apps() -> List[dict]:
    apps: List[dict] = []
    dedup: Set[str] = set()
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        data = read_json_safe(path)
        if not isinstance(data, dict):
            continue
        rows = data.get("data")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            app_id = str(row.get("appId", "")).strip()
            app_key = str(row.get("appKey", "")).strip()
            sign = str(row.get("sign", "")).strip()
            if not app_id or not app_key or not sign or app_id in dedup:
                continue
            dedup.add(app_id)
            apps.append(
                {
                    "index": len(apps) + 1,
                    "appId": app_id,
                    "appName": find_local_app_name(app_id),
                    "appKey": app_key,
                    "sign": sign,
                    "authFile": path.name,
                    "authPath": str(path.resolve()),
                }
            )
    return apps


def resolve_app_by_id(app_id: str, app_name: str = "") -> dict:
    app_id = str(app_id).strip()
    if not app_id:
        raise ValueError("--app-id 不能为空")

    apps = load_local_apps()
    for app in apps:
        if str(app.get("appId", "")).strip() == app_id:
            if app_name:
                app["appName"] = app_name
            return app

    auth_file = APP_AUTH_DIR / f"app_authorize_{app_id}.json"
    if not auth_file.exists():
        raise RuntimeError(f"未找到 appId={app_id} 的本地授权文件: {auth_file}")

    data = read_json_safe(auth_file) or {}
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"授权文件格式不正确: {auth_file}")

    first = rows[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"授权文件缺少有效 data 行: {auth_file}")

    resolved_name = app_name.strip() or find_local_app_name(app_id)
    return {
        "index": 1,
        "appId": app_id,
        "appName": resolved_name,
        "appKey": str(first.get("appKey", "")).strip(),
        "sign": str(first.get("sign", "")).strip(),
        "authFile": auth_file.name,
        "authPath": str(auth_file.resolve()),
    }


def add_ws_view(ws_view_map: Dict[str, List[str]], ws_name: str, view_name: str) -> None:
    ws_name = ws_name.strip()
    view_name = view_name.strip()
    if not ws_name or not view_name:
        return
    bucket = ws_view_map.setdefault(ws_name, [])
    bucket.append(view_name)


def collect_from_view_create_json(
    path: Path,
    app_id: str,
    worksheet_names: List[str],
    view_names: List[str],
    ws_view_map: Dict[str, List[str]],
    ws_id_map: Dict[str, str],
) -> None:
    data = read_json_safe(path)
    if not isinstance(data, dict):
        return
    for app in data.get("apps", []) if isinstance(data.get("apps"), list) else []:
        if not isinstance(app, dict) or str(app.get("appId", "")).strip() != app_id:
            continue
        for ws in app.get("worksheets", []) if isinstance(app.get("worksheets"), list) else []:
            if not isinstance(ws, dict):
                continue
            ws_name = str(ws.get("worksheetName", "")).strip()
            ws_id = str(ws.get("worksheetId", "")).strip()
            if ws_name:
                worksheet_names.append(ws_name)
                if ws_id and ws_name not in ws_id_map:
                    ws_id_map[ws_name] = ws_id
            for v in ws.get("views", []) if isinstance(ws.get("views"), list) else []:
                if not isinstance(v, dict):
                    continue
                v_name = str(v.get("name", "")).strip()
                if v_name:
                    view_names.append(v_name)
                    add_ws_view(ws_view_map, ws_name, v_name)


def collect_from_view_plan_json(
    path: Path,
    app_id: str,
    worksheet_names: List[str],
    view_names: List[str],
    ws_view_map: Dict[str, List[str]],
    ws_id_map: Dict[str, str],
) -> None:
    data = read_json_safe(path)
    if not isinstance(data, dict):
        return
    for app in data.get("apps", []) if isinstance(data.get("apps"), list) else []:
        if not isinstance(app, dict) or str(app.get("appId", "")).strip() != app_id:
            continue
        for ws in app.get("worksheets", []) if isinstance(app.get("worksheets"), list) else []:
            if not isinstance(ws, dict):
                continue
            ws_name = str(ws.get("worksheetName", "")).strip()
            ws_id = str(ws.get("worksheetId", "")).strip()
            if ws_name:
                worksheet_names.append(ws_name)
                if ws_id and ws_name not in ws_id_map:
                    ws_id_map[ws_name] = ws_id
            for v in ws.get("views", []) if isinstance(ws.get("views"), list) else []:
                if not isinstance(v, dict):
                    continue
                v_name = str(v.get("name", "")).strip()
                if v_name:
                    view_names.append(v_name)
                    add_ws_view(ws_view_map, ws_name, v_name)


def collect_from_layout_plan_json(path: Path, app_id: str, worksheet_names: List[str], ws_id_map: Dict[str, str]) -> None:
    data = read_json_safe(path)
    if not isinstance(data, dict):
        return
    app = data.get("app")
    if not isinstance(app, dict) or str(app.get("appId", "")).strip() != app_id:
        return
    for ws in data.get("worksheets", []) if isinstance(data.get("worksheets"), list) else []:
        if not isinstance(ws, dict):
            continue
        ws_id = str(ws.get("workSheetId", "")).strip() or str(ws.get("worksheetId", "")).strip()
        ws_name = str(ws.get("workSheetName", "")).strip() or str(ws.get("worksheetName", "")).strip()
        if ws_name:
            worksheet_names.append(ws_name)
            if ws_id and ws_name not in ws_id_map:
                ws_id_map[ws_name] = ws_id


def collect_from_tableview_filter_json(path: Path, app_id: str, view_names: List[str]) -> None:
    data = read_json_safe(path)
    if not isinstance(data, dict):
        return

    apps = data.get("apps") if isinstance(data.get("apps"), list) else []
    for app in apps:
        if not isinstance(app, dict) or str(app.get("appId", "")).strip() != app_id:
            continue
        for ws in app.get("worksheets", []) if isinstance(app.get("worksheets"), list) else []:
            if not isinstance(ws, dict):
                continue
            for vp in ws.get("viewPlans", []) if isinstance(ws.get("viewPlans"), list) else []:
                if isinstance(vp, dict):
                    vname = str(vp.get("viewName", "")).strip()
                    if vname:
                        view_names.append(vname)
            for v in ws.get("views", []) if isinstance(ws.get("views"), list) else []:
                if isinstance(v, dict):
                    vname = str(v.get("viewName", "")).strip() or str(v.get("name", "")).strip()
                    if vname:
                        view_names.append(vname)


def collect_from_record_logs(app_id: str, worksheet_names: List[str], view_names: List[str]) -> None:
    pattern = re.compile(rf"https://www\.mingdao\.com/app/{re.escape(app_id)}/")
    click_pattern = re.compile(r'Clicked\s+[^\"]*\"([^\"]+)\"')

    for log_file in sorted(RECORD_RUNS_DIR.glob("*/run_agent.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            text = log_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not pattern.search(text):
            continue

        for hit in click_pattern.findall(text):
            label = hit.strip()
            if not label:
                continue
            if "信息" in label or "表" in label or "目录" in label or "清单" in label:
                worksheet_names.append(label)
            if "视图" in label or label == "全部" or "看板" in label or "画廊" in label or "日历" in label:
                view_names.append(label)


def collect_local_names(app_id: str) -> tuple[List[str], List[str], Dict[str, List[str]], Dict[str, str]]:
    worksheet_names: List[str] = []
    view_names: List[str] = []
    ws_view_map: Dict[str, List[str]] = {}
    ws_id_map: Dict[str, str] = {}

    for path in sorted(VIEW_CREATE_DIR.glob(f"view_create_result_{app_id}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        collect_from_view_create_json(path, app_id, worksheet_names, view_names, ws_view_map, ws_id_map)
    for path in sorted(VIEW_PLAN_DIR.glob(f"view_plan_{app_id}_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        collect_from_view_plan_json(path, app_id, worksheet_names, view_names, ws_view_map, ws_id_map)

    for path in sorted(LAYOUT_PLAN_DIR.glob("worksheet_layout_plan_pipeline_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        collect_from_layout_plan_json(path, app_id, worksheet_names, ws_id_map)

    for base_dir in (TABLEVIEW_FILTER_PLAN_DIR, TABLEVIEW_FILTER_APPLY_DIR):
        for path in sorted(base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            collect_from_tableview_filter_json(path, app_id, view_names)

    collect_from_record_logs(app_id, worksheet_names, view_names)

    worksheet_names = dedup_keep_order([x for x in worksheet_names if x])
    view_names = dedup_keep_order([x for x in view_names if x])
    normalized_map: Dict[str, List[str]] = {}
    for ws_name, views in ws_view_map.items():
        v = dedup_keep_order([x for x in views if x])
        if ws_name and v:
            normalized_map[ws_name] = v

    return worksheet_names, view_names, normalized_map, ws_id_map


def main() -> None:
    parser = argparse.ArgumentParser(description="读取模板并填充 {} 占位符，输出到 task.txt（纯本地模式）")
    parser.add_argument("--template-file", default=str(DEFAULT_TEMPLATE_FILE), help="模板文件路径（默认 record/task_template.txt）")
    parser.add_argument("--task-file", default=str(DEFAULT_TASK_FILE), help="输出 task 文件路径（默认 record/task.txt）")
    parser.add_argument("--app-id", default="", help="指定应用 appId，传入后跳过交互选择")
    parser.add_argument("--app-name", default="", help="可选，指定应用名称，用于输出展示")
    parser.add_argument("--metadata-json", default="", help="可选，写入本次替换的结构化元数据 JSON")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（不传则每次随机）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览替换结果，不写回文件")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    raw_template_path = str(args.template_file).strip()
    if raw_template_path.startswith("@"):
        raw_template_path = raw_template_path[1:]
    template_path = Path(raw_template_path).expanduser()
    if not template_path.is_absolute():
        template_path = (BASE_DIR / "record" / raw_template_path).resolve()
    else:
        template_path = template_path.resolve()

    if not template_path.exists():
        fallback_typo = (BASE_DIR / "record" / "taks_template.txt").resolve()
        if fallback_typo.exists():
            template_path = fallback_typo
        else:
            raise FileNotFoundError(f"模板文件不存在: {template_path}")

    task_path = Path(args.task_file).expanduser().resolve()

    content = template_path.read_text(encoding="utf-8")
    placeholders = extract_placeholders(content)
    if not placeholders:
        print(f"模板中未发现占位符，无需处理: {template_path}")
        return

    if str(args.app_id).strip():
        app = resolve_app_by_id(args.app_id, args.app_name)
    else:
        apps = load_local_apps()
        if not apps:
            raise RuntimeError(f"未找到本地应用授权文件: {APP_AUTH_DIR}")
        app = choose_app(apps)

    app_id = str(app["appId"]).strip()
    app_name = str(app["appName"]).strip()
    print(f"\n已选择应用: {app_name} ({app_id})")

    worksheet_names, view_names, ws_view_map, ws_id_map = collect_local_names(app_id)
    print(f"已从本地文件加载工作表: {len(worksheet_names)} 个")
    print(f"已从本地文件加载视图: {len(view_names)} 个")

    replacement_map: Dict[str, str] = {}
    last_selected_worksheet = ""
    used_worksheets: Set[str] = set()
    used_views: Set[str] = set()
    chosen_worksheet_by_index: Dict[str, str] = {}
    for name in placeholders:
        if name in replacement_map:
            continue

        key = name.strip()
        key_lower = re.sub(r"\s+", "", key.lower())

        if key_lower in {"appid", "app_id", "应用id", "appid"}:
            replacement_map[name] = app_id
            continue
        if key_lower in {"appname", "app_name", "应用名称", "应用名"}:
            replacement_map[name] = app_name
            continue
        m_ws_id = re.match(r"^工作表名称(\d+)的表ID$", key)
        if m_ws_id:
            idx = m_ws_id.group(1)
            ws_name = chosen_worksheet_by_index.get(idx, "")
            if not ws_name:
                raise RuntimeError(f"未找到 工作表名称{idx} 的已选值，无法填充 {name}。请将该占位符放在对应工作表名称之后。")
            ws_id = ws_id_map.get(ws_name, "")
            if not ws_id:
                raise RuntimeError(f"本地数据中未找到工作表“{ws_name}”的表ID，无法填充 {name}。")
            replacement_map[name] = ws_id
            continue
        if key.startswith("工作表名称"):
            m_ws_idx = re.match(r"^工作表名称(\d+)$", key)
            chosen_ws = choose_unique(worksheet_names, used_worksheets, "工作表名称")
            replacement_map[name] = chosen_ws
            last_selected_worksheet = chosen_ws
            if m_ws_idx:
                chosen_worksheet_by_index[m_ws_idx.group(1)] = chosen_ws
            continue
        if key.startswith("视图名称"):
            candidate_views = ws_view_map.get(last_selected_worksheet, []) if last_selected_worksheet else []
            if not candidate_views:
                raise RuntimeError(
                    f"工作表“{last_selected_worksheet or '未指定'}”没有可用视图，无法填充 {name}。"
                )
            replacement_map[name] = choose_unique(candidate_views, used_views, f"视图名称({last_selected_worksheet})")
            continue

        default_value = f"{key}_已填充"
        user_input = input(f"请输入 {{{name}}} 的值（回车使用默认: {default_value}）: ").strip()
        replacement_map[name] = user_input or default_value

    updated = content
    for k, v in replacement_map.items():
        updated = updated.replace(f"{{{k}}}", v)

    remained = extract_placeholders(updated)
    metadata = {
        "template_file": str(template_path),
        "task_file": str(task_path),
        "app": {
            "appId": app_id,
            "appName": app_name,
        },
        "stats": {
            "worksheet_count": len(worksheet_names),
            "view_count": len(view_names),
            "replaced_count": len(replacement_map),
            "remaining_placeholder_count": len(remained),
        },
        "replacement_map": replacement_map,
        "remaining_placeholders": remained,
        "last_selected_worksheet": last_selected_worksheet,
        "worksheet_name_to_id": ws_id_map,
        "worksheet_view_map": ws_view_map,
        "generated_content": updated,
        "dry_run": bool(args.dry_run),
    }

    metadata_json = str(args.metadata_json).strip()
    if metadata_json:
        metadata_path = Path(metadata_json).expanduser()
        if not metadata_path.is_absolute():
            metadata_path = (BASE_DIR / metadata_json).resolve()
        else:
            metadata_path = metadata_path.resolve()
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"- 元数据: {metadata_path}")

    if args.dry_run:
        print("\n预览完成（dry-run，未写入文件）")
        print(f"- 模板: {template_path}")
        print(f"- 输出: {task_path}")
        print(f"- 计划替换占位符: {len(replacement_map)}")
        print(f"- 预览后剩余占位符: {len(remained)}")
        if replacement_map:
            print("- 替换映射:")
            for k, v in replacement_map.items():
                print(f"  {{{k}}} -> {v}")
        if remained:
            print(f"- 未替换项: {sorted(set(remained))}")
        print("\n--- 替换后完整内容（预览）---")
        print(updated)
        print("--- 结束 ---")
        return

    task_path.write_text(updated, encoding="utf-8")

    print("\n替换完成")
    print(f"- 模板: {template_path}")
    print(f"- 输出: {task_path}")
    print(f"- 已替换占位符: {len(replacement_map)}")
    print(f"- 剩余占位符: {len(remained)}")
    if remained:
        print(f"- 未替换项: {sorted(set(remained))}")
    print("\n--- 替换后完整内容 ---")
    print(updated)
    print("--- 结束 ---")


if __name__ == "__main__":
    main()
