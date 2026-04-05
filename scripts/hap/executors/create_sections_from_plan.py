#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 2d：根据 sections_plan.json 创建应用导航分组，并将 appSectionId 写回 worksheet_plan.json。

模式一（不传 --ws-create-result）：
  - 调用 AddAppSection + UpdateAppSectionName 创建分组
  - 原地更新 worksheet_plan.json 每个工作表的 appSectionId
  - 输出 sections_create_result.json

模式二（传入 --ws-create-result）：
  - 读取 worksheet_create_result.json，获取每个工作表的真实 worksheetId
  - 调用 RemoveWorkSheetAscription 将工作表批量移入正确分组
  - 追加移动结果到 sections_create_result.json
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import auth_retry
from utils import now_ts, load_json, write_json

BASE_DIR = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
SECTIONS_CREATE_RESULT_DIR = OUTPUT_ROOT / "sections_create_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

BASE_URL = "https://www.mingdao.com"
ADD_SECTION_URL    = BASE_URL + "/api/HomeApp/AddAppSection"
RENAME_SECTION_URL = BASE_URL + "/api/HomeApp/UpdateAppSectionName"
MOVE_WORKSHEET_URL = BASE_URL + "/api/AppManagement/RemoveWorkSheetAscription"


def referer(app_id: str) -> str:
    return f"https://www.mingdao.com/app/{app_id}"


def hap_post(url: str, app_id: str, payload: dict, dry_run: bool) -> dict:
    if dry_run:
        print(f"  [dry-run] POST {url}")
        print(f"           {json.dumps(payload, ensure_ascii=False)}")
        return {"dry_run": True, "state": 1, "data": {"data": "dry-run-section-id"}}
    resp = auth_retry.hap_web_post(url, AUTH_CONFIG_PATH, referer=referer(app_id), json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


# ---------------------------------------------------------------------------
# 模式一：创建分组
# ---------------------------------------------------------------------------

def create_section(app_id: str, name: str, dry_run: bool) -> str:
    """两步创建分组：Add（得 ID，直接传真实名称）→ UpdateName（确保名称正确）。返回 appSectionId。"""
    resp_add = hap_post(ADD_SECTION_URL, app_id, {"appId": app_id, "name": name}, dry_run)
    if not dry_run:
        if resp_add.get("state") != 1:
            raise RuntimeError(f"AddAppSection 失败: {resp_add}")
        section_id = str(resp_add.get("data", {}).get("data", "")).strip()
        if not section_id:
            raise RuntimeError(f"AddAppSection 未返回 sectionId: {resp_add}")
    else:
        section_id = f"dry-run-{name}"

    # 二次确认改名，带重试和错误检查
    max_retries = 3
    for attempt in range(max_retries):
        resp_rename = hap_post(RENAME_SECTION_URL, app_id, {
            "appId": app_id,
            "appSectionId": section_id,
            "name": name,
        }, dry_run)
        if dry_run or resp_rename.get("state") == 1:
            break
        print(f"  ⚠ UpdateAppSectionName 第 {attempt + 1} 次失败: {resp_rename}")
        if attempt == max_retries - 1:
            raise RuntimeError(f"UpdateAppSectionName 重试 {max_retries} 次仍失败，分组「{name}」(id={section_id}) 可能未正确命名: {resp_rename}")

    print(f"  ✓ 创建分组「{name}」→ {section_id}")
    return section_id


def patch_worksheet_plan(plan_path: Path, sections: List[dict], name_to_section_id: Dict[str, str]) -> None:
    """原地更新 worksheet_plan.json，将每个工作表的 appSectionId 改为真实 ID。"""
    plan = load_json(plan_path)

    # 构建工作表名 → appSectionId 映射
    ws_to_section_id: Dict[str, str] = {}
    for sec in sections:
        sec_id = name_to_section_id.get(sec["name"], "")
        if not sec_id:
            continue
        for ws_name in sec.get("worksheets", []):
            ws_to_section_id[str(ws_name).strip()] = sec_id

    updated = 0
    for ws in plan.get("worksheets", []):
        ws_name = str(ws.get("name", "")).strip()
        if ws_name in ws_to_section_id:
            ws["appSectionId"] = ws_to_section_id[ws_name]
            updated += 1

    write_json(plan_path, plan)
    print(f"  ✓ 已更新 worksheet_plan.json 中 {updated} 个工作表的 appSectionId")


def rename_section(app_id: str, section_id: str, name: str, dry_run: bool) -> None:
    """重命名已有分组。"""
    max_retries = 3
    for attempt in range(max_retries):
        resp = hap_post(RENAME_SECTION_URL, app_id, {
            "appId": app_id,
            "appSectionId": section_id,
            "name": name,
        }, dry_run)
        if dry_run or resp.get("state") == 1:
            return
        print(f"  ⚠ 重命名默认分组第 {attempt + 1} 次失败: {resp}")
        if attempt == max_retries - 1:
            raise RuntimeError(f"重命名默认分组失败: {resp}")


def run_mode_one(args) -> dict:
    """创建分组并写回 worksheet_plan。返回 result dict。"""
    sections_plan = load_json(Path(args.sections_plan_json).expanduser().resolve())
    plan_path = Path(args.plan_json).expanduser().resolve()

    sections = sections_plan.get("sections", [])
    if not sections:
        print("sections_plan 中没有分组，跳过")
        return {"app_id": args.app_id, "sections": [], "worksheet_name_to_section_id": {}}

    # 获取默认分组 ID，第一个分组复用它（避免留下"未命名分组"）
    default_section_id = get_default_section_id(args.app_id) if not args.dry_run else ""

    name_to_section_id: Dict[str, str] = {}
    result_sections = []
    first_section = True

    for sec in sections:
        name = str(sec.get("name", "")).strip()
        if not name:
            print(f"  ⚠ 跳过无名分组: {sec}")
            continue

        if first_section and default_section_id:
            # 复用默认分组：重命名而非新建
            rename_section(args.app_id, default_section_id, name, args.dry_run)
            section_id = default_section_id
            print(f"  ✓ 复用默认分组→「{name}」({section_id})")
            first_section = False
        else:
            section_id = create_section(args.app_id, name, args.dry_run)
            first_section = False

        name_to_section_id[name] = section_id
        result_sections.append({
            "name": name,
            "appSectionId": section_id,
            "worksheets": sec.get("worksheets", []),
        })

    # 写回 worksheet_plan
    if not args.dry_run:
        patch_worksheet_plan(plan_path, sections, name_to_section_id)

    # 构建 name→sectionId 映射（供模式二使用）
    ws_name_to_section_id: Dict[str, str] = {}
    for sec in sections:
        sid = name_to_section_id.get(sec.get("name", ""), "")
        for ws_name in sec.get("worksheets", []):
            ws_name_to_section_id[str(ws_name).strip()] = sid

    return {
        "app_id": args.app_id,
        "sections": result_sections,
        "worksheet_name_to_section_id": ws_name_to_section_id,
    }


# ---------------------------------------------------------------------------
# 模式二：移动工作表到分组
# ---------------------------------------------------------------------------

def parse_worksheet_create_result(result_path: Path) -> List[dict]:
    """从 worksheet_create_result.json 中提取工作表信息列表。"""
    data = load_json(result_path)
    worksheets = []

    # 兼容两种结构
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("worksheets", data.get("created_worksheets", data.get("results", data.get("data", []))))
        if isinstance(items, dict):
            items = list(items.values())
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        ws_id = str(item.get("worksheetId", item.get("id", ""))).strip()
        ws_name = str(item.get("worksheetName", item.get("name", ""))).strip()
        if ws_id and ws_name:
            worksheets.append({
                "workSheetId": ws_id,
                "workSheetName": ws_name,
                "type": int(item.get("type", 0) or 0),
                "icon": str(item.get("icon", "table")),
                "iconColor": str(item.get("iconColor", "#757575")),
                "iconUrl": str(item.get("iconUrl", "https://fp1.mingdaoyun.cn/customIcon/table.svg")),
                "createType": 0,
            })
    return worksheets


def get_default_section_id(app_id: str) -> str:
    """获取应用默认分组 ID（第一个分组）。用于 sourceAppSectionId。"""
    try:
        resp = auth_retry.hap_web_post(
            "https://www.mingdao.com/api/HomeApp/GetApp",
            AUTH_CONFIG_PATH,
            referer=referer(app_id),
            json={"appId": app_id, "getSection": True},
            timeout=30,
        )
        data = resp.json()
        sections = data.get("data", {}).get("sections", [])
        if sections:
            return str(sections[0].get("appSectionId", "")).strip()
    except Exception as e:
        print(f"  ⚠ 获取默认分组 ID 失败: {e}")
    return ""


def run_mode_two(args, sections_create_result: dict) -> List[dict]:
    """读取工作表创建结果，将工作表批量移入对应分组。返回移动结果列表。"""
    ws_create_path = Path(args.ws_create_result).expanduser().resolve()
    worksheets = parse_worksheet_create_result(ws_create_path)

    if not worksheets:
        print("  ⚠ worksheet_create_result 中未找到工作表，跳过移动")
        return []

    ws_name_to_section_id = sections_create_result.get("worksheet_name_to_section_id", {})
    if not ws_name_to_section_id:
        print("  ⚠ 没有工作表→分组映射，跳过移动")
        return []

    # 获取默认分组 ID（作为 sourceAppSectionId）
    source_section_id = get_default_section_id(args.app_id) if not args.dry_run else "dry-run-default-section"
    if not source_section_id and not args.dry_run:
        print("  ⚠ 无法获取默认分组 ID，跳过移动")
        return []

    # 按 plan 顺序分组工作表（保持分组内排序与规划一致）
    ws_by_name = {ws["workSheetName"]: ws for ws in worksheets}
    target_to_worksheets: Dict[str, List[dict]] = {}
    for sec in sections_create_result.get("sections", []):
        target_id = sec.get("appSectionId", "")
        if not target_id:
            continue
        for ws_name in sec.get("worksheets", []):
            ws_name = str(ws_name).strip()
            ws = ws_by_name.get(ws_name)
            if ws:
                target_to_worksheets.setdefault(target_id, []).append(ws)
    # 补充未被 plan 覆盖的工作表（通过旧映射兜底）
    assigned_names = {ws["workSheetName"] for wsl in target_to_worksheets.values() for ws in wsl}
    for ws in worksheets:
        if ws["workSheetName"] not in assigned_names:
            target_id = ws_name_to_section_id.get(ws["workSheetName"], "")
            if target_id:
                target_to_worksheets.setdefault(target_id, []).append(ws)

    move_results = []
    for target_section_id, ws_list in target_to_worksheets.items():
        # 跳过已在目标分组的（source == target）
        if source_section_id == target_section_id:
            continue
        # API 每次只能移动一张表，必须逐张调用
        ok_names = []
        fail_names = []
        for ws in ws_list:
            payload = {
                "sourceAppId": args.app_id,
                "resultAppId": args.app_id,
                "sourceAppSectionId": source_section_id,
                "ResultAppSectionId": target_section_id,
                "workSheetsInfo": [ws],
            }
            resp = hap_post(MOVE_WORKSHEET_URL, args.app_id, payload, args.dry_run)
            if args.dry_run or resp.get("state") == 1 or resp.get("dry_run"):
                ok_names.append(ws["workSheetName"])
            else:
                fail_names.append(ws["workSheetName"])
                print(f"  ✗ 移动失败「{ws['workSheetName']}」(section={target_section_id}): {resp}")
        if ok_names:
            print(f"  ✓ 移动 {len(ok_names)} 张到分组 {target_section_id}: {ok_names}")
        move_results.append({
            "targetSectionId": target_section_id,
            "worksheets": ok_names,
            "failed": fail_names,
            "ok": len(fail_names) == 0,
        })

    return move_results


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="创建工作表分组并移动工作表")
    parser.add_argument("--sections-plan-json", required=True, help="sections_plan.json 路径")
    parser.add_argument("--plan-json", required=True, help="worksheet_plan.json 路径（原地修改 appSectionId）")
    parser.add_argument("--app-id", required=True, help="应用 UUID 格式 appId")
    parser.add_argument("--app-auth-json", default="", help="app_authorize_*.json 路径（暂未使用，预留）")
    parser.add_argument("--output", default="", help="输出 sections_create_result.json 路径")
    parser.add_argument("--ws-create-result", default="", help="模式二：worksheet_create_result.json 路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求，不实际调用 API")
    args = parser.parse_args()

    is_mode_two = bool(args.ws_create_result)

    if not is_mode_two:
        # 模式一：创建分组
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 模式一：创建工作表分组...")
        result = run_mode_one(args)
        result["move_results"] = []
    else:
        # 模式二：移动工作表
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 模式二：移动工作表到分组...")
        # 先读已有的 sections_create_result（模式一已经写出）
        if args.output and Path(args.output).exists():
            result = load_json(Path(args.output).expanduser().resolve())
        else:
            # 尝试从输出目录找最新的
            existing = sorted(SECTIONS_CREATE_RESULT_DIR.glob(f"*{args.app_id}*.json"),
                              key=lambda p: p.stat().st_mtime, reverse=True)
            if existing:
                result = load_json(existing[0])
            else:
                print("  ✗ 找不到模式一的输出文件，无法执行模式二")
                sys.exit(1)
        move_results = run_mode_two(args, result)
        result["move_results"] = move_results

    # 确定输出路径
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        SECTIONS_CREATE_RESULT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = SECTIONS_CREATE_RESULT_DIR / f"sections_create_{args.app_id}_{now_ts()}.json"

    write_json(output_path, result)
    print(f"已保存: {output_path}")

    if not is_mode_two:
        print(f"创建了 {len(result['sections'])} 个分组")
    else:
        ok_count = sum(1 for r in result.get("move_results", []) if r.get("ok"))
        print(f"移动完成: {ok_count}/{len(result.get('move_results', []))} 个分组处理成功")


if __name__ == "__main__":
    main()
