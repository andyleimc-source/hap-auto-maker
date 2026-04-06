#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按应用/工作表结构规划视图：
1) 选择应用（y=全部；序号=部分；其他取消）
2) 拉取每张工作表字段
3) 调用 Gemini 规划可创建视图与参数
4) 输出为 JSON
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_HAP_DIR = _Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from google import genai

import requests
import auth_retry
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config
from utils import now_ts, latest_file, load_json, write_json
try:
    from planning.view_planner import (
        build_view_type_prompt_section,
        suggest_views,
        build_structure_prompt as _vp_build_structure_prompt,
        validate_structure_plan as _vp_validate_structure_plan,
        build_config_prompt as _vp_build_config_prompt,
        validate_config_plan as _vp_validate_config_plan,
        build_config_prompt_single_ws as _vp_build_config_prompt_single_ws,
        validate_config_plan_single_ws as _vp_validate_config_plan_single_ws,
    )
    from planning.constraints import classify_fields
    from ai_utils import parse_ai_json as _parse_ai_json
    _HAS_VIEW_PLANNER = True
except ImportError as _vp_import_err:
    _HAS_VIEW_PLANNER = False
    print(f"[warning] view_planner 不可用，回退到单阶段模式: {_vp_import_err}", file=_sys.stderr)

BASE_DIR = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
VIEW_PLAN_DIR = OUTPUT_ROOT / "view_plans"
GEMINI_CONFIG_PATH = AI_CONFIG_PATH
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

CURRENT_AI_CONFIG: Dict[str, str] = {}

APP_INFO_URL = "https://api.mingdao.com/v3/app"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
ALLOWED_VIEW_TYPES = {"0", "1", "2", "3", "4", "5"}


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
    choice = input(prompt).strip()
    if choice.lower() == "y":
        return list(range(1, items_count + 1))
    try:
        picked = parse_selection(choice, items_count)
    except ValueError:
        return None
    if not picked:
        return None
    return picked


def sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "app"


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
    dedup: Dict[str, dict] = {}
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

    # 按工作表名称去重（保留同名中最后一个，因为 pipeline 多次重试时最新批次排在后面）
    seen_names: dict = {}
    for ws in worksheets:
        seen_names[ws["workSheetName"]] = ws
    deduped = list(seen_names.values())
    if len(deduped) < len(worksheets):
        print(f"  [去重] 工作表总数 {len(worksheets)}，按名称去重后 {len(deduped)} 个")
    return deduped


def fetch_controls(worksheet_id: str, auth_config_path: Path) -> dict:
    resp = auth_retry.hap_web_post(
        GET_CONTROLS_URL, auth_config_path,
        referer=f"https://www.mingdao.com/worksheet/field/edit?sourceId={worksheet_id}",
        json={"worksheetId": worksheet_id}, timeout=30,
    )
    data = resp.json()
    wrapped = data.get("data", {})
    if isinstance(wrapped, dict) and isinstance(wrapped.get("data"), dict):
        if int(wrapped.get("code", 0) or 0) != 1:
            raise RuntimeError(f"获取工作表控件失败: worksheetId={worksheet_id}, resp={data}")
        payload = wrapped["data"]
    else:
        payload = data.get("data", {})
        if not isinstance(payload, dict):
            raise RuntimeError(f"获取工作表控件失败: worksheetId={worksheet_id}, resp={data}")
    controls = payload.get("controls", [])
    if not isinstance(controls, list):
        raise RuntimeError(f"工作表控件格式错误: worksheetId={worksheet_id}, resp={data}")
    return {
        "worksheetId": worksheet_id,
        "worksheetName": str(payload.get("worksheetName", "") or ""),
        "fields": controls,
    }


def simplify_field(field: dict) -> dict:
    options = []
    raw_opts = field.get("options")
    if isinstance(raw_opts, list):
        for o in raw_opts:
            if not isinstance(o, dict):
                continue
            if o.get("isDeleted", False):
                continue
            options.append(
                {
                    "key": str(o.get("key", "")).strip(),
                    "value": str(o.get("value", "")).strip(),
                }
            )
            if len(options) >= 20:
                break
    field_id = str(field.get("id", "") or field.get("controlId", "")).strip()
    field_name = str(field.get("name", "") or field.get("controlName", "")).strip()
    is_system = bool(field.get("isSystemControl", False))
    if not is_system:
        try:
            is_system = int(field.get("attribute", 0) or 0) == 1
        except Exception:
            is_system = False
    return {
        "id": field_id,
        "name": field_name,
        "type": str(field.get("type", "")).strip(),
        "subType": int(field.get("subType", 0) or 0),
        "isTitle": bool(field.get("isTitle", False)),
        "required": bool(field.get("required", False)),
        "isSystem": is_system,
        "options": options,
    }


def default_display_controls(fields: List[dict]) -> List[str]:
    ids = []
    title_id = ""
    for f in fields:
        fid = str(f.get("id", "")).strip()
        if not fid:
            continue
        if bool(f.get("isTitle", False)) and not title_id:
            title_id = fid
        if not bool(f.get("isSystem", False)):
            ids.append(fid)
    out = []
    if title_id:
        out.append(title_id)
    for fid in ids:
        if fid not in out:
            out.append(fid)
        if len(out) >= 3:
            break
    return out


def build_prompt(app_name: str, worksheet_name: str, worksheet_id: str, fields: List[dict]) -> str:
    # 视图类型说明（优先使用注册中心）
    if _HAS_VIEW_PLANNER:
        view_type_section = build_view_type_prompt_section()
        classified = classify_fields(fields)
        suggestions = suggest_views(classified, worksheet_id, worksheet_name)
        suggestion_lines = []
        for sg in suggestions:
            suggestion_lines.append(
                f"  - viewType={sg['viewType']} [{sg['name']}]({sg.get('reason', '')})"
            )
        suggestion_text = "推荐视图（根据字段分析）：\n" + "\n".join(suggestion_lines) if suggestion_lines else ""
    else:
        view_type_section = "允许 viewType=0(表格),1(看板),3(画廊),4(日历),5(甘特图)；❌ viewType=2(层级视图)已禁用，禁止使用"
        suggestion_text = ""

    return f"""
你是明道云视图规划助手。请基于工作表名称和字段，规划"建议创建的视图列表"。

应用名：{app_name}
工作表名：{worksheet_name}
工作表ID：{worksheet_id}
字段列表：
{json.dumps(fields, ensure_ascii=False, indent=2)}

{view_type_section}

{suggestion_text}

仅输出 JSON（不要 markdown）：
{{
  "worksheetId": "{worksheet_id}",
  "worksheetName": "{worksheet_name}",
  "views": [
    {{
      "name": "视图名",
      "viewType": "0|1|2|3|4|5",
      "reason": "建议理由",
      "displayControls": ["字段ID1", "字段ID2"],
      "coverCid": "封面字段ID或空字符串",
      "viewControl": "看板分组字段ID或空字符串",
      "advancedSetting": {{}},
      "postCreateUpdates": [
        {{
          "editAttrs": ["advancedSetting"],
          "editAdKeys": ["calendarcids"],
          "advancedSetting": {{}}
        }}
      ]
    }}
  ]
}}

规则：
1) 允许 viewType=0(表格),1(看板),3(画廊),4(日历),5(甘特图)。
   ❌ viewType=0 的额外表格视图只有一种情况可以创建：有明确的分组字段（单选字段 type=9/11），能通过 groupsetting 展示分组。否则与系统内置"全部"视图无区别，禁止创建。
   ❌ viewType=2（层级视图）：已禁用，任何情况下禁止选。
2) 视图数量 1-4 个，尽量多样化——系统已内置"全部"列表视图，额外视图应优先选非表格类型（看板/日历/画廊/甘特图）。
3) displayControls / coverCid / viewControl 必须来自提供的字段ID；无法确定时填空或省略。
4) 日历视图必须在 postCreateUpdates.advancedSetting 中提供 calendarcids（字符串化 JSON），格式必须为：'[{{"begin":"日期字段ID","end":"结束日期字段ID或空字符串"}}]'。begin 为开始日期字段ID（必填），end 为结束日期字段ID（无则填空字符串）。
5) 【强制】看板视图(viewType=1)：
   - viewControl 必须设置为 type=9 或 type=11 的单选字段ID
   - 该字段必须有「状态流转/优先级」语义：字段名包含「状态、阶段、进度、步骤、环节、审批、审核、审查、审定、优先级、紧急程度、严重程度、风险等级、紧急级别、重要程度」之一
   - ❌ 禁止用「类型、分类、方式、来源、渠道、性别、行业、地区、部门、岗位、职位、职级」等纯分类字段作为看板列
   - 不满足以上条件则不要创建看板视图
6) 【强制】表格视图(viewType=0)如果视图名包含"按...分组"、"按...分类"、"分组"等含义，必须通过 postCreateUpdates 二次保存分组配置，格式：{{"editAttrs":["advancedSetting"],"editAdKeys":["groupsetting","groupsorts","groupcustom","groupshow","groupfilters","groupopen"],"advancedSetting":{{"groupsetting":"[{{\\\"controlId\\\":\\\"分组字段ID\\\",\\\"isAsc\\\":true}}]","groupsorts":"","groupcustom":"","groupshow":"0","groupfilters":"[]","groupopen":""}}}}。groupsetting 是字符串化 JSON 数组，controlId 必须为有实际选项的单选字段(type=9/11)的ID，isAsc 控制升序。
7) 【强制】甘特图视图（viewType=5）：
   - 必须有开始+结束两个日期字段
   - 工作表必须有项目/任务语义：表名包含「项目、任务、里程碑、迭代、冲刺、需求、工单、计划、工期、排产、路线图、版本、发布」之一
   - 不满足以上条件则不要创建甘特图
8) 【强制】日历视图（viewType=4）：
   - 必须有日期字段
   - 工作表必须有排期/事件语义：表名包含「活动、日程、排期、预约、预订、排班、班次、事件、会议、培训、考勤、假期、出差、值班、计划、安排、档期、节假日」之一
   - ❌ 台账、主数据、档案、明细、记录（流水类）表不适合日历视图
   - 不满足以上条件则不要创建日历视图
9) 画廊视图（viewType=3）有附件字段（type=14）时推荐，适合以卡片形式浏览内容；设置 coverCid 为附件字段ID。
10) 若字段不支持某视图，请不要输出该视图类型。
11) 输出必须是可解析 JSON。
12) 【重要】每个视图必须有实际业务含义——不仅有名称，还要有对应的配置（viewControl/advancedSetting/postCreateUpdates），空配置的视图没有价值。
13) 【格式要求】所有 advancedSetting 中的 JSON 字符串值必须是紧凑格式（无空格）。
""".strip()


def _find_single_select_field(fields: List[dict]) -> str:
    """从字段列表中找第一个非系统单选字段 ID，用于自动补全 viewControl/groupsetting。"""
    for f in fields:
        if bool(f.get("isSystem", False)):
            continue
        if str(f.get("type", "")).strip() == "11" and f.get("options"):
            return str(f.get("id", "")).strip()
    return ""


def _find_date_fields(fields: List[dict]) -> List[str]:
    """找非系统日期字段 ID（type=15 或 16），用于甘特图自动补全。"""
    result = []
    for f in fields:
        if bool(f.get("isSystem", False)):
            continue
        if str(f.get("type", "")).strip() in ("15", "16"):
            fid = str(f.get("id", "")).strip()
            if fid:
                result.append(fid)
    return result


def _find_self_relation_field(fields: List[dict], worksheet_id: str) -> str:
    """找自关联字段（type=29 且 dataSource = 本工作表 ID），用于层级视图自动补全。"""
    if not worksheet_id:
        return ""
    for f in fields:
        if bool(f.get("isSystem", False)):
            continue
        if str(f.get("type", "")).strip() == "29":
            ds = str(f.get("dataSource", "")).strip()
            if ds == worksheet_id:
                return str(f.get("id", "")).strip()
    return ""


def _is_grouping_view_name(name: str) -> bool:
    """判断视图名是否暗示分组含义。"""
    import re as _re
    return bool(_re.search(r"按.{1,8}分[组类]|分组|分类查看", name))


def normalize_views(raw_views: Any, fields: List[dict], worksheet_id: str = "") -> List[dict]:
    if not isinstance(raw_views, list):
        return []
    field_ids = {str(f.get("id", "")).strip() for f in fields if str(f.get("id", "")).strip()}
    fallback_display = default_display_controls(fields)
    out: List[dict] = []
    seen_names = set()

    for item in raw_views:
        if not isinstance(item, dict):
            continue
        view_type = str(item.get("viewType", "")).strip()
        if view_type not in ALLOWED_VIEW_TYPES:
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            name = f"视图_{view_type}_{len(out)+1}"
        if name in seen_names:
            name = f"{name}_{len(out)+1}"
        seen_names.add(name)

        display_controls = item.get("displayControls")
        if not isinstance(display_controls, list):
            display_controls = []
        display_controls = [str(x).strip() for x in display_controls if str(x).strip() in field_ids]
        if not display_controls:
            display_controls = fallback_display

        cover_cid = str(item.get("coverCid", "")).strip()
        if cover_cid and cover_cid not in field_ids:
            cover_cid = ""
        view_control = str(item.get("viewControl", "")).strip()
        if view_control and view_control not in field_ids:
            view_control = ""

        advanced_setting = item.get("advancedSetting")
        if not isinstance(advanced_setting, dict):
            advanced_setting = {}

        # 自动补全：看板视图缺 viewControl 时，自动匹配第一个单选字段
        if view_type == "1" and not view_control:
            fallback_vc = _find_single_select_field(fields)
            if fallback_vc:
                view_control = fallback_vc
                print(f"    ⚠ 看板视图「{name}」缺少 viewControl，自动补全为 {fallback_vc}")

        # 自动补全：表格视图名暗示分组但缺 groupsetting 配置
        # 注意：表格视图行分组使用 advancedSetting.groupsetting（JSON字符串数组），
        # 而非 groupView（groupView 是看板等视图的导航分组，不适用于表格行分组）。
        if view_type == "0" and _is_grouping_view_name(name):
            # 检查 postCreateUpdates 中是否已有 groupsetting
            has_group_update = any(
                isinstance(upd, dict) and "groupsetting" in (upd.get("editAdKeys") or [])
                for upd in (item.get("postCreateUpdates") or [])
            )
            if not has_group_update:
                fallback_gc = _find_single_select_field(fields)
                if fallback_gc:
                    groupsetting_val = json.dumps(
                        [{"controlId": fallback_gc, "isAsc": True}],
                        ensure_ascii=False, separators=(",", ":")
                    )
                    if not isinstance(item.get("postCreateUpdates"), list):
                        item["postCreateUpdates"] = []
                    item["postCreateUpdates"].append({
                        "editAttrs": ["advancedSetting"],
                        "editAdKeys": ["groupsetting", "groupsorts", "groupcustom", "groupshow", "groupfilters", "groupopen"],
                        "advancedSetting": {
                            "groupsetting": groupsetting_val,
                            "groupsorts": "",
                            "groupcustom": "",
                            "groupshow": "0",
                            "groupfilters": "[]",
                            "groupopen": "",
                        },
                    })
                    print(f"    ⚠ 分组视图「{name}」缺少 groupsetting，自动补全为字段 {fallback_gc}")

        # 自动补全：甘特图缺 begindate/enddate 时自动匹配日期字段
        if view_type == "5":
            has_gantt = any(
                isinstance(u, dict) and "begindate" in (u.get("editAdKeys") or [])
                for u in (item.get("postCreateUpdates") or [])
            )
            if not has_gantt:
                date_fids = _find_date_fields(fields)
                if len(date_fids) >= 2:
                    begin_id, end_id = date_fids[0], date_fids[1]
                elif len(date_fids) == 1:
                    begin_id = end_id = date_fids[0]
                else:
                    begin_id = end_id = "ctime"
                if not isinstance(item.get("postCreateUpdates"), list):
                    item["postCreateUpdates"] = []
                item["postCreateUpdates"].append({
                    "editAttrs": ["advancedSetting"],
                    "editAdKeys": ["begindate", "enddate"],
                    "advancedSetting": {"begindate": begin_id, "enddate": end_id},
                })
                print(f"    ⚠ 甘特图「{name}」自动补全 begindate={begin_id} enddate={end_id}")

        # 自动补全：层级视图缺 childType/layersControlId 时自动匹配自关联字段
        if view_type == "2":
            has_hier = any(
                isinstance(u, dict) and "childType" in (u.get("editAttrs") or [])
                for u in (item.get("postCreateUpdates") or [])
            )
            if not has_hier:
                rel_fid = _find_self_relation_field(fields, worksheet_id)
                if rel_fid:
                    if not isinstance(item.get("postCreateUpdates"), list):
                        item["postCreateUpdates"] = []
                    item["postCreateUpdates"].append({
                        "editAttrs": ["childType", "layersControlId"],
                        "childType": 0,
                        "layersControlId": rel_fid,
                    })
                    print(f"    ⚠ 层级视图「{name}」自动补全 layersControlId={rel_fid}")
                else:
                    print(f"    ⚠ 层级视图「{name}」未找到自关联字段，跳过该视图")
                    continue  # 没有自关联字段则不创建层级视图，否则前端会因 layersControlId 为空而崩溃

        post_updates = item.get("postCreateUpdates")
        if not isinstance(post_updates, list):
            post_updates = []
        normalized_updates = []
        for upd in post_updates:
            if not isinstance(upd, dict):
                continue
            normalized_updates.append(upd)

        out.append(
            {
                "name": name,
                "viewType": view_type,
                "reason": str(item.get("reason", "")).strip(),
                "displayControls": display_controls,
                "coverCid": cover_cid,
                "viewControl": view_control,
                "advancedSetting": advanced_setting,
                "postCreateUpdates": normalized_updates,
            }
        )
        if len(out) >= 8:
            break

    # 层级视图(viewType=2) 已禁用，不再自动注入

    return out


def build_batch_prompt(app_name: str, worksheets_data: List[dict]) -> str:
    """一次 Prompt 规划所有工作表视图。worksheets_data: [{worksheetId, worksheetName, fields}]"""
    count = len(worksheets_data)
    ws_section = json.dumps(worksheets_data, ensure_ascii=False, indent=2)
    return f"""你是明道云视图规划助手。请基于以下 {count} 个工作表的名称和字段，为每个工作表规划"建议创建的视图列表"。

应用名：{app_name}
工作表列表：
{ws_section}

仅输出 JSON（不要 markdown）：
{{
  "worksheets": [
    {{
      "worksheetId": "工作表ID",
      "worksheetName": "工作表名",
      "views": [
        {{
          "name": "视图名",
          "viewType": "0|1|2|3|4|5",
          "reason": "建议理由",
          "displayControls": ["字段ID1", "字段ID2"],
          "coverCid": "封面字段ID或空字符串",
          "viewControl": "看板分组字段ID或空字符串",
          "advancedSetting": {{}},
          "postCreateUpdates": [
            {{
              "editAttrs": ["advancedSetting"],
              "editAdKeys": ["calendarcids"],
              "advancedSetting": {{}}
            }}
          ]
        }}
      ]
    }}
  ]
}}

规则：
1) 允许 viewType=0(表格),1(看板),3(画廊),4(日历),5(甘特图)。
   ❌ viewType=0 的额外表格视图只有一种情况可以创建：有明确的分组字段（单选字段 type=9/11），能通过 groupsetting 展示分组。否则与系统内置"全部"视图无区别，禁止创建。
   ❌ viewType=2（层级视图）：已禁用，任何情况下禁止选。
2) 每个工作表视图数量 1-4 个，尽量多样化——系统已内置"全部"列表视图，额外视图应优先选非表格类型（看板/日历/画廊/甘特图）。
3) displayControls / coverCid / viewControl 必须来自对应工作表提供的字段ID；无法确定时填空或省略。
4) 日历视图必须在 postCreateUpdates.advancedSetting 中提供 calendarcids（字符串化 JSON），格式必须为：'[{{"begin":"日期字段ID","end":"结束日期字段ID或空字符串"}}]'。begin 为开始日期字段ID（必填），end 为结束日期字段ID（无则填空字符串）。
5) 【强制】看板视图(viewType=1)：
   - viewControl 必须设置为 type=9 或 type=11 的单选字段ID
   - 该字段必须有「状态流转/优先级」语义：字段名包含「状态、阶段、进度、步骤、环节、审批、审核、审查、审定、优先级、紧急程度、严重程度、风险等级、紧急级别、重要程度」之一
   - ❌ 禁止用「类型、分类、方式、来源、渠道、性别、行业、地区、部门、岗位、职位、职级」等纯分类字段作为看板列
   - 不满足以上条件则不要创建看板视图
6) 【强制】表格视图(viewType=0)如果视图名包含"按...分组"、"按...分类"、"分组"等含义，必须通过 postCreateUpdates 二次保存分组配置，格式：{{"editAttrs":["advancedSetting"],"editAdKeys":["groupsetting","groupsorts","groupcustom","groupshow","groupfilters","groupopen"],"advancedSetting":{{"groupsetting":"[{{\\\"controlId\\\":\\\"分组字段ID\\\",\\\"isAsc\\\":true}}]","groupsorts":"","groupcustom":"","groupshow":"0","groupfilters":"[]","groupopen":""}}}}。groupsetting 是字符串化 JSON 数组，controlId 必须为有实际选项的单选字段(type=9/11)的ID，isAsc 控制升序。
7) 【强制】甘特图视图（viewType=5）：
   - 必须有开始+结束两个日期字段
   - 工作表必须有项目/任务语义：表名包含「项目、任务、里程碑、迭代、冲刺、需求、工单、计划、工期、排产、路线图、版本、发布」之一
   - 不满足以上条件则不要创建甘特图
8) 【强制】日历视图（viewType=4）：
   - 必须有日期字段
   - 工作表必须有排期/事件语义：表名包含「活动、日程、排期、预约、预订、排班、班次、事件、会议、培训、考勤、假期、出差、值班、计划、安排、档期、节假日」之一
   - ❌ 台账、主数据、档案、明细、记录（流水类）表不适合日历视图
   - 不满足以上条件则不要创建日历视图
9) 画廊视图（viewType=3）有附件字段（type=14）时推荐；设 coverCid 为附件字段ID。
10) 若字段不支持某视图，请不要输出该视图类型。
11) 输出必须是可解析 JSON，worksheets 数组长度必须等于 {count}。
12) 【重要】每个视图必须有实际业务含义——不仅有名称，还要有对应的配置（viewControl/advancedSetting/postCreateUpdates），空配置的视图没有价值。
13) 【格式要求】所有 advancedSetting 中的 JSON 字符串值必须是紧凑格式（无空格）。""".strip()


def _call_ai_with_retry(
    client,
    model: str,
    prompt: str,
    max_retries: int = 3,
    label: str = "",
) -> str:
    """调用 AI 并在失败时重试，返回响应文本。"""
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=create_generation_config(
                    CURRENT_AI_CONFIG,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return resp.text or ""
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                wait_seconds = attempt * 2
                print(
                    f"[{label}] AI 请求失败 attempt={attempt}/{max_retries}，"
                    f"{wait_seconds}s 后重试: {exc}",
                    file=_sys.stderr,
                )
                time.sleep(wait_seconds)
    raise last_exc or RuntimeError(f"[{label}] AI 请求失败")


def plan_views_two_phase(
    client,
    model: str,
    app_name: str,
    ws_with_fields: List[tuple],
) -> List[dict]:
    """两阶段视图规划：Phase 1 规划结构，Phase 2 逐表补全配置细节。

    Phase 1: build_structure_prompt → AI → validate_structure_plan（一次调用，所有表）
    Phase 2: build_config_prompt_single_ws → AI → validate（逐表并行，Semaphore=3）
    返回 [{worksheetId, worksheetName, fields, views}]，兼容 create_views_from_plan.py。
    """
    import threading

    ws_data = [
        {
            "worksheetId": ws["workSheetId"],
            "worksheetName": ws["workSheetName"],
            "fields": fields,
        }
        for ws, fields in ws_with_fields
    ]
    worksheets_by_id = {item["worksheetId"]: item for item in ws_data}

    # ── Phase 1: 结构规划（一次调用，所有表） ────────────────────────────────────
    print(f"\n[view two-phase] Phase 1: 结构规划（{app_name}，{len(ws_data)} 个表）", file=_sys.stderr)
    p1_prompt = _vp_build_structure_prompt(app_name, ws_data)
    print(
        f"[view] Phase1 prompt 长度: {len(p1_prompt)}, 前200字: {p1_prompt[:200]}",
        file=_sys.stderr,
    )

    p1_raw: dict = {}
    last_p1_error: Optional[str] = None
    for val_attempt in range(1, 4):
        try:
            prompt_with_ctx = p1_prompt
            if last_p1_error:
                prompt_with_ctx = (
                    p1_prompt
                    + f"\n\n# 上次输出校验失败（第 {val_attempt - 1} 次）\n错误：{last_p1_error}\n请修正后重新输出。"
                )
            raw_text = _call_ai_with_retry(client, model, prompt_with_ctx, label="view:p1")
            print(f"[view:p1] 响应长度 {len(raw_text)} 字符", file=_sys.stderr)
            p1_raw = _parse_ai_json(raw_text)
            _vp_validate_structure_plan(p1_raw, worksheets_by_id)
            break
        except Exception as exc:
            last_p1_error = str(exc)
            if val_attempt >= 3:
                print(
                    f"[view two-phase] Phase 1 校验失败（已重试 {val_attempt} 次），继续执行 Phase 2: {exc}",
                    file=_sys.stderr,
                )
                break
            print(f"[view:p1 retry {val_attempt}] {exc}", file=_sys.stderr)

    # 按 worksheetId 索引 Phase1 结果
    p1_ws_map: Dict[str, dict] = {}
    for ws_item in p1_raw.get("worksheets", []):
        if isinstance(ws_item, dict):
            ws_id = str(ws_item.get("worksheetId", "")).strip()
            if ws_id:
                p1_ws_map[ws_id] = ws_item

    # ── Phase 2: 逐表配置补全（并行，Semaphore=3）────────────────────────────────
    print(f"\n[view two-phase] Phase 2: 逐表配置补全（{app_name}，并发=3）", file=_sys.stderr)

    semaphore = threading.Semaphore(3)
    p2_results: Dict[str, dict] = {}  # ws_id → {worksheetId, worksheetName, views}
    p2_lock = threading.Lock()

    def _phase2_single(ws_id: str, ws_name: str, ws_item_data: dict):
        """对单张工作表执行 Phase2 配置补全。"""
        structure_for_ws = p1_ws_map.get(ws_id, {"worksheetId": ws_id, "worksheetName": ws_name, "views": []})

        if not structure_for_ws.get("views"):
            print(f"  [view:p2] 工作表「{ws_name}」Phase1 无视图，跳过 Phase2", file=_sys.stderr)
            with p2_lock:
                p2_results[ws_id] = {"worksheetId": ws_id, "worksheetName": ws_name, "views": []}
            return

        with semaphore:
            p2_prompt = _vp_build_config_prompt_single_ws(app_name, structure_for_ws, ws_item_data)
            print(
                f"  [view:p2] 工作表「{ws_name}」prompt 长度: {len(p2_prompt)}",
                file=_sys.stderr,
            )

            p2_ws_raw: dict = {}
            last_p2_error: Optional[str] = None
            for val_attempt in range(1, 4):
                try:
                    prompt_with_ctx = p2_prompt
                    if last_p2_error:
                        prompt_with_ctx = (
                            p2_prompt
                            + f"\n\n# 上次输出校验失败（第 {val_attempt - 1} 次）\n错误：{last_p2_error}\n请修正后重新输出。"
                        )
                    raw_text = _call_ai_with_retry(
                        client, model, prompt_with_ctx,
                        label=f"view:p2:{ws_name}",
                    )
                    print(f"  [view:p2] 工作表「{ws_name}」响应长度 {len(raw_text)} 字符", file=_sys.stderr)
                    p2_ws_raw = _parse_ai_json(raw_text)
                    _vp_validate_config_plan_single_ws(p2_ws_raw, ws_item_data)
                    break
                except Exception as exc:
                    last_p2_error = str(exc)
                    if val_attempt >= 3:
                        print(
                            f"  [view:p2] 工作表「{ws_name}」校验警告（已重试 {val_attempt} 次），使用当前输出: {exc}",
                            file=_sys.stderr,
                        )
                        break
                    print(f"  [view:p2 retry {val_attempt}] 工作表「{ws_name}」: {exc}", file=_sys.stderr)

            with p2_lock:
                p2_results[ws_id] = p2_ws_raw if p2_ws_raw.get("views") else structure_for_ws

    # 启动并行线程
    threads = []
    for wd in ws_data:
        ws_id = wd["worksheetId"]
        ws_name = wd["worksheetName"]
        t = threading.Thread(target=_phase2_single, args=(ws_id, ws_name, wd), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # ── 合并结果 ────────────────────────────────────────────────────────────────
    results = []
    for ws, fields in ws_with_fields:
        ws_id = ws["workSheetId"]
        p2_ws = p2_results.get(ws_id, {})
        views_raw = p2_ws.get("views", [])
        views = normalize_views(views_raw, fields, ws_id)
        results.append({
            "worksheetId": ws_id,
            "worksheetName": ws["workSheetName"],
            "fields": fields,
            "views": views,
        })
    return results


def plan_views_batch(
    client: genai.Client,
    model: str,
    app_name: str,
    ws_with_fields: List[tuple],
) -> List[dict]:
    """一次 Gemini 调用规划所有工作表视图。返回 [{worksheetId, worksheetName, fields, views}]

    若 view_planner 可用，优先走两阶段规划；否则回退到单阶段批量规划。
    """
    if _HAS_VIEW_PLANNER:
        return plan_views_two_phase(client, model, app_name, ws_with_fields)

    ws_data_for_prompt = [
        {"worksheetId": ws["workSheetId"], "worksheetName": ws["workSheetName"], "fields": fields}
        for ws, fields in ws_with_fields
    ]
    base_prompt = build_batch_prompt(app_name, ws_data_for_prompt)
    validation_retries = 3
    last_error: Optional[str] = None
    ws_views_map: Dict[str, List] = {}

    for val_attempt in range(1, validation_retries + 1):
        prompt = base_prompt
        if last_error:
            prompt = base_prompt + f"\n\n# 上次输出验证失败（第 {val_attempt - 1} 次）\n错误信息：{last_error}\n请仔细检查并修正后重新输出。"
        last_exc: Optional[Exception] = None
        resp = None
        for attempt in range(1, 4):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=create_generation_config(
                        CURRENT_AI_CONFIG,
                        response_mime_type="application/json",
                        temperature=0.2,
                    ),
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= 3:
                    raise
                wait_seconds = attempt * 2
                print(f"Gemini 批量规划视图请求失败 attempt={attempt}/3，{wait_seconds} 秒后重试: {exc}")
                time.sleep(wait_seconds)
        if resp is None:
            raise last_exc or RuntimeError("Gemini 批量规划视图失败")
        parsed = extract_json(resp.text or "")
        try:
            ws_list = parsed.get("worksheets", [])
            if not isinstance(ws_list, list):
                raise ValueError(f"返回的 worksheets 类型错误（得到 {type(ws_list).__name__}，期望 list）")
            if len(ws_list) == 0:
                raise ValueError("返回的 worksheets 数组为空，AI 未生成任何工作表视图规划")
            ws_views_map = {}
            for ws_item in ws_list:
                if not isinstance(ws_item, dict):
                    continue
                ws_id = str(ws_item.get("worksheetId", "")).strip()
                if ws_id:
                    ws_views_map[ws_id] = ws_item.get("views", [])
            break
        except Exception as exc:
            last_error = str(exc)
            if val_attempt >= validation_retries:
                raise
            print(f"[验证重试 {val_attempt}/{validation_retries}] 批量视图解析失败，重新生成：{exc}")

    results = []
    for ws, fields in ws_with_fields:
        ws_id = ws["workSheetId"]
        views_raw = ws_views_map.get(ws_id, [])
        views = normalize_views(views_raw, fields, ws_id)
        results.append({
            "worksheetId": ws_id,
            "worksheetName": ws["workSheetName"],
            "fields": fields,
            "views": views,
        })
    return results


def plan_views_for_worksheet(client, model: str, app_name: str, worksheet: dict, fields: List[dict]) -> dict:
    base_prompt = build_prompt(app_name, worksheet["workSheetName"], worksheet["workSheetId"], fields)
    print(
        f"[view] prompt 长度: {len(base_prompt)}, 前200字: {base_prompt[:200]}",
        file=_sys.stderr,
    )
    validation_retries = 3
    views = None
    last_error: Optional[str] = None
    for val_attempt in range(1, validation_retries + 1):
        prompt = base_prompt
        if last_error:
            prompt = base_prompt + f"\n\n# 上次输出验证失败（第 {val_attempt - 1} 次）\n错误信息：{last_error}\n请仔细检查并修正后重新输出。"
        last_exc: Optional[Exception] = None
        for attempt in range(1, 4):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=create_generation_config(
                        CURRENT_AI_CONFIG,
                        response_mime_type="application/json",
                        temperature=0.2,
                    ),
                )
                break
            except Exception as exc:
                last_exc = exc
                if attempt >= 3:
                    raise
                wait_seconds = attempt * 2
                print(
                    f"Gemini 规划视图请求失败，worksheet={worksheet['workSheetName']} "
                    f"attempt={attempt}/3，{wait_seconds} 秒后重试: {exc}"
                )
                time.sleep(wait_seconds)
        else:
            raise last_exc or RuntimeError("Gemini 规划视图失败")
        parsed = extract_json(resp.text or "")
        try:
            views = normalize_views(parsed.get("views"), fields, worksheet.get("workSheetId", ""))
            break
        except Exception as exc:
            last_error = str(exc)
            if val_attempt >= validation_retries:
                raise
            print(
                f"[验证重试 {val_attempt}/{validation_retries}] 视图验证失败，worksheet={worksheet['workSheetName']}，"
                f"追加错误后重新生成：{exc}"
            )
    assert views is not None
    return {
        "worksheetId": worksheet["workSheetId"],
        "worksheetName": worksheet["workSheetName"],
        "fields": fields,
        "views": views,
    }


def plan_and_create_views_for_ws(
    client,
    model: str,
    app_id: str,
    app_name: str,
    worksheet_id: str,
    worksheet_name: str,
    default_view_id: str,
    auth_config_path: Path,
    dry_run: bool = False,
) -> dict:
    """单表视图原子操作：AI 规划 → 改造默认视图 → 创建新视图 → postCreateUpdates。"""
    from planning.view_planner import (
        build_single_ws_view_prompt,
        validate_single_ws_view_plan,
    )
    from executors.create_views_from_plan import (
        update_default_view,
        build_create_payload,
        build_update_payload,
        save_view,
        auto_complete_post_updates,
        merge_post_updates,
    )

    result = {
        "worksheetId": worksheet_id,
        "worksheetName": worksheet_name,
        "default_view_result": None,
        "new_views_results": [],
        "error": None,
    }

    # 1. 拉取真实字段
    try:
        schema = fetch_controls(worksheet_id, auth_config_path)
    except Exception as exc:
        result["error"] = f"拉取字段失败: {exc}"
        print(f"  ✗ [{worksheet_name}] 拉取字段失败: {exc}", file=_sys.stderr)
        return result

    raw_fields = schema.get("fields", [])
    fields = [simplify_field(f) for f in raw_fields if isinstance(f, dict)]
    field_ids = {str(f.get("id", "")).strip() for f in fields if str(f.get("id", "")).strip()}

    # 2. AI 规划
    prompt = build_single_ws_view_prompt(
        app_name=app_name,
        ws_name=worksheet_name,
        ws_id=worksheet_id,
        fields=fields,
        default_view_id=default_view_id,
    )

    plan = None
    validation_errors: list[str] = []
    for attempt in range(1, 3):
        current_prompt = prompt
        if validation_errors:
            current_prompt = (
                prompt + "\n\n上次输出校验失败，请修正：\n"
                + "\n".join(f"- {e}" for e in validation_errors)
            )
        try:
            raw_text = _call_ai_with_retry(client, model, current_prompt, label=f"view:{worksheet_name}")
            plan = _parse_ai_json(raw_text)
            validation_errors = validate_single_ws_view_plan(plan, field_ids)
            if not validation_errors:
                break
        except Exception as exc:
            validation_errors = [str(exc)]
        if attempt >= 2:
            print(f"  ⚠ [{worksheet_name}] 视图规划校验仍有错误: {validation_errors}", file=_sys.stderr)

    if plan is None:
        result["error"] = f"AI 规划失败: {validation_errors}"
        return result

    # 3. 改造默认视图
    dv_plan = plan.get("default_view_update")
    if isinstance(dv_plan, dict) and default_view_id:
        try:
            dv_resp = update_default_view(
                app_id, worksheet_id, default_view_id, dv_plan, auth_config_path, dry_run
            )
            result["default_view_result"] = {
                "viewId": default_view_id,
                "name": str(dv_plan.get("name", "")).strip(),
                "response": dv_resp,
                "success": dry_run or (isinstance(dv_resp, dict) and int(dv_resp.get("state", 0) or 0) == 1),
            }
            post_updates = dv_plan.get("postCreateUpdates", [])
            if isinstance(post_updates, list):
                for upd in post_updates:
                    if not isinstance(upd, dict):
                        continue
                    upd_payload = build_update_payload(app_id, worksheet_id, default_view_id, upd)
                    skip_reason = str(upd_payload.pop("_skip_reason", "")).strip()
                    if skip_reason:
                        continue
                    save_view(upd_payload, auth_config_path, app_id, worksheet_id, dry_run)
            print(f"  ✓ [{worksheet_name}] 默认视图改造: {dv_plan.get('name', '')}", file=_sys.stderr)
        except Exception as exc:
            result["default_view_result"] = {"error": str(exc)}
            print(f"  ⚠ [{worksheet_name}] 默认视图改造失败: {exc}", file=_sys.stderr)

    # 4. 逐个创建新视图
    new_views = plan.get("new_views", [])
    if not isinstance(new_views, list):
        new_views = []
    new_views = normalize_views(new_views, fields, worksheet_id)

    for view in new_views:
        view_name = str(view.get("name", "")).strip()
        try:
            create_payload = build_create_payload(app_id, worksheet_id, view)
            create_resp = save_view(create_payload, auth_config_path, app_id, worksheet_id, dry_run)

            created_view_id = ""
            if dry_run:
                created_view_id = "__DRY_RUN__"
            elif isinstance(create_resp, dict) and int(create_resp.get("state", 0) or 0) == 1:
                created_view_id = str((create_resp.get("data") or {}).get("viewId", "")).strip()

            view_result = {
                "name": view_name,
                "viewType": view.get("viewType"),
                "createdViewId": created_view_id,
                "success": bool(created_view_id),
                "updates": [],
            }

            if created_view_id and created_view_id != "__DRY_RUN__":
                view_type_int = int(str(view.get("viewType", "0")).strip() or "0")
                ai_updates = view.get("postCreateUpdates", [])
                if not isinstance(ai_updates, list):
                    ai_updates = []
                view_with_ws = dict(view)
                view_with_ws["_worksheetId"] = worksheet_id
                auto_updates = auto_complete_post_updates(view_with_ws, raw_fields)
                post_updates = merge_post_updates(ai_updates, auto_updates, view_type_int)
                for upd in post_updates:
                    if not isinstance(upd, dict):
                        continue
                    upd_payload = build_update_payload(app_id, worksheet_id, created_view_id, upd)
                    skip_reason = str(upd_payload.pop("_skip_reason", "")).strip()
                    if skip_reason:
                        view_result["updates"].append({"skipped": True, "reason": skip_reason})
                        continue
                    upd_resp = save_view(upd_payload, auth_config_path, app_id, worksheet_id, dry_run)
                    view_result["updates"].append({"response": upd_resp})

            result["new_views_results"].append(view_result)
            status = "✓" if view_result["success"] else "✗"
            print(f"  {status} [{worksheet_name}] 新视图: {view_name} (viewType={view.get('viewType')})", file=_sys.stderr)
        except Exception as exc:
            result["new_views_results"].append({"name": view_name, "error": str(exc), "success": False})
            print(f"  ✗ [{worksheet_name}] 新视图创建失败 {view_name}: {exc}", file=_sys.stderr)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="遍历应用工作表并使用 AI 规划视图")
    parser.add_argument("--config", default=str(GEMINI_CONFIG_PATH), help="AI 配置 JSON 路径")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--app-ids", default="", help="可选，应用ID列表（逗号分隔）；不传则交互选择")
    parser.add_argument("--output", default="", help="输出 JSON 文件路径")
    args = parser.parse_args()

    global CURRENT_AI_CONFIG
    CURRENT_AI_CONFIG = load_ai_config(Path(args.config).expanduser().resolve())
    client = get_ai_client(CURRENT_AI_CONFIG)
    model_name = CURRENT_AI_CONFIG["model"]
    auth_config_path = Path(args.auth_config).expanduser().resolve()

    app_rows = load_app_auth_rows()
    apps = []
    for r in app_rows:
        app_id = str(r.get("appId", "")).strip()
        app_key = str(r.get("appKey", "")).strip()
        sign = str(r.get("sign", "")).strip()
        app_name = str(r.get("name", "")).strip() or app_id
        if not app_id or not app_key or not sign:
            continue
        try:
            meta = fetch_app_meta(app_key, sign)
            app_name = str(meta.get("name", "")).strip() or app_name
        except Exception:
            pass
        apps.append({"appId": app_id, "appName": app_name, "appKey": app_key, "sign": sign})
    if not apps:
        raise RuntimeError("没有可用应用")

    picked_apps = []
    app_ids_arg = str(args.app_ids or "").strip()
    if app_ids_arg:
        wanted = {x.strip() for x in app_ids_arg.split(",") if x.strip()}
        picked_apps = [a for a in apps if a["appId"] in wanted]
        if not picked_apps:
            raise ValueError(f"--app-ids 未匹配到应用: {app_ids_arg}")
    else:
        print("可选应用：")
        print("序号 | 应用名称 | 应用ID")
        for i, app in enumerate(apps, start=1):
            print(f"{i}. {app['appName']} | {app['appId']}")
        picked_idx = choose_indexes(
            "请选择应用：输入 y=全部；输入序号(如 1,2,3 / 1.2.3)；任意键取消: ",
            len(apps),
        )
        if not picked_idx:
            print("已取消。")
            return
        picked_apps = [apps[i - 1] for i in picked_idx]

    result_apps = []
    total_worksheets = 0
    total_views = 0
    for app in picked_apps:
        print(f"\n处理应用: {app['appName']} ({app['appId']})")
        worksheets = fetch_worksheets(app["appKey"], app["sign"])
        app_out = {"appId": app["appId"], "appName": app["appName"], "worksheets": []}
        if not worksheets:
            result_apps.append(app_out)
            continue
        # 并行拉取所有工作表字段
        def _fetch_ws(ws):
            schema = fetch_controls(ws["workSheetId"], auth_config_path)
            return ws, [simplify_field(f) for f in schema.get("fields", []) if isinstance(f, dict)]
        with ThreadPoolExecutor(max_workers=min(8, len(worksheets))) as ex:
            ws_with_fields = list(ex.map(_fetch_ws, worksheets))
        # 一次 Gemini 批量调用；若失败则退化为逐表规划
        print(f"  调用 AI 批量规划 {len(worksheets)} 个工作表视图...")
        used_fallback = False
        try:
            planned_list = plan_views_batch(client, model_name, app["appName"], ws_with_fields)
        except Exception as batch_err:
            print(f"  ⚠ 批量视图规划失败（{batch_err}），退化为逐表规划...")
            used_fallback = True
            planned_list = []
            for ws, fields in ws_with_fields:
                try:
                    planned = plan_views_for_worksheet(client, model_name, app["appName"], ws, fields)
                    planned_list.append(planned)
                    print(f"    - {ws['workSheetName']}：规划 {len(planned.get('views', []))} 个视图")
                except Exception as ws_err:
                    print(f"    ✗ {ws['workSheetName']} 视图规划失败：{ws_err}")
                    planned_list.append({
                        "worksheetId": ws["workSheetId"],
                        "worksheetName": ws["workSheetName"],
                        "fields": fields,
                        "views": [],
                    })
        for planned in planned_list:
            app_out["worksheets"].append(planned)
            total_worksheets += 1
            total_views += len(planned.get("views", []))
            if not used_fallback:
                print(f"  - {planned['worksheetName']}：规划 {len(planned.get('views', []))} 个视图")
        result_apps.append(app_out)

    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "model": model_name,
        "source": "ai_view_planner_v1",
        "apps": result_apps,
        "summary": {
            "appCount": len(result_apps),
            "worksheetCount": total_worksheets,
            "viewCount": total_views,
        },
    }

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        app_part = "multi" if len(result_apps) != 1 else sanitize_name(str(result_apps[0].get("appName", "")))
        out_path = (VIEW_PLAN_DIR / f"view_plan_{app_part}_{now_ts()}.json").resolve()
    write_json(out_path, payload)
    print(f"\n规划完成: {out_path}")
    print(f"- 应用数: {payload['summary']['appCount']}")
    print(f"- 工作表数: {payload['summary']['worksheetCount']}")
    print(f"- 视图总数: {payload['summary']['viewCount']}")


if __name__ == "__main__":
    main()
