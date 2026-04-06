#!/usr/bin/env python3
"""
工作流规划 JSON 生成器（pipeline_workflows.py）— v2 三阶段逐表规划

三阶段流程：
  Phase -1: 表名筛选 — 极轻量 AI 调用，判断哪些表适合做工作流触发源
  Phase  0: 全局骨架 — 轻量 AI 调用，规划每表工作流分配和跨表关系
  Phase  1: 逐表规划 — N 次并行 AI 调用，每表独立输出完整 action_nodes

优势（vs 旧版一锅端模式）：
  - 单次 prompt 从 2000-5000 行降��� 200-400 行
  - 总 prompt 量减少 85%+
  - Phase 1 可并行，速度更快
  - 单表失败只需重试该表

用法示例：
  python3 scripts/pipeline_workflows.py --relation-id 'c2259f27-...'
"""

from __future__ import annotations

import json
import math
import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time

import requests

sys.path.insert(0, str(Path(__file__).parent))
from workflow_io import persist

# 引入共享的健壮 JSON 解析工具
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config, parse_ai_json  # type: ignore

# 引入节点约束（用于 Phase 0 prompt 中的节点类型说明）
_HAP_PLANNING_DIR = Path(__file__).resolve().parents[2] / "scripts" / "hap"
if str(_HAP_PLANNING_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_PLANNING_DIR))

try:
    from planning.constraints import build_node_type_prompt_section, classify_fields
except ImportError:
    build_node_type_prompt_section = None
    classify_fields = None

# 引入校验器
try:
    from planning.workflow_planner import validate_structure_plan, validate_node_config
    _VALIDATOR_AVAILABLE = True
except ImportError:
    _VALIDATOR_AVAILABLE = False


# ── 常量 ───────────────────────────────────────────────────────────────────────

_PROJECT_ROOT     = Path(__file__).resolve().parents[2]
_APP_AUTH_DIR     = _PROJECT_ROOT / "data" / "outputs" / "app_authorizations"

_FIELD_TYPE_MAP = {
    2: "文本", 3: "电话", 4: "证件号", 5: "Email", 6: "数字",
    7: "金额", 8: "大写金额", 9: "单选", 10: "多选", 11: "下拉单选",
    14: "附件", 15: "日期", 16: "日期时间", 19: "地区", 21: "自由关联",
    24: "备注", 26: "成员", 27: "部门", 28: "成员(多)", 29: "关联记录",
    30: "查找引用", 31: "公式", 32: "文本公式", 35: "子表",
    36: "检查框", 37: "评分", 40: "定位", 41: "富文本",
    42: "签名", 43: "条形码", 45: "嵌入",
}

_TYPE_STR_TO_INT: dict[str, int] = {
    "Text": 2, "Phone": 3, "IDCard": 4, "Email": 5,
    "Number": 6, "Money": 7, "BigNumber": 8,
    "SingleSelect": 9, "MultiSelect": 10, "Dropdown": 11,
    "Attachment": 14, "Date": 15, "DateTime": 16,
    "Area": 19, "FreeAssociation": 21, "Remark": 24,
    "Member": 26, "Collaborator": 26, "Department": 27,
    "MemberMultiple": 28, "Relation": 29, "Lookup": 30,
    "Formula": 31, "DateFormula": 31, "TextFormula": 32,
    "SubSheet": 35, "CheckBox": 36, "Rating": 37,
    "Location": 40, "RichText": 41, "Signature": 42,
    "Barcode": 43, "Embed": 45,
}

_SKIP_TYPE_STRS: set[str] = {
    "Attachment", "FreeAssociation", "Relation", "Lookup",
    "Formula", "DateFormula", "TextFormula", "SubSheet",
    "Signature", "Embed", "Collaborator", "Member",
    "Department", "MemberMultiple",
}

_SYSTEM_FIELD_IDS: set[str] = {
    "rowid", "ownerid", "caid", "ctime", "utime", "uaid",
    "wfname", "wfcuaids", "wfcaid", "wfctime", "wfrtime",
    "wfcotime", "wfdtime", "wfftime", "wfstatus",
}

_SKIP_FIELD_TYPES = {14, 21, 29, 30, 31, 32, 35, 42, 43, 45}

_MAX_TOTAL_WORKFLOWS = 25
_MAX_JSON_RETRIES = 3

_THINKING_BUDGETS: dict[str, int] = {
    "low": 1024, "medium": 8192, "high": 24576,
}

_DEBUG_OUTPUT_DIR = _PROJECT_ROOT / "data" / "outputs" / "workflow_debug"


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="三阶段逐表规划工作流，生成 pipeline_workflows_latest.json。"
    )
    parser.add_argument("--relation-id", required=True, help="应用 ID（relationId）。")
    parser.add_argument("--app-auth-json", default="", help="应用授权 JSON 文件路径（留空则自动匹配）。")
    parser.add_argument("--thinking", default="none", choices=["none", "low", "medium", "high"],
                        help="AI 推理深度（默认 none）。")
    parser.add_argument("--skip-analysis", action="store_true",
                        help="（兼容旧参数，已无效果——预分析已合并到 Phase 0）。")
    parser.add_argument("--output", default="", help="自定义输出路径。")
    parser.add_argument("--max-parallel", type=int, default=5,
                        help="Phase 1 逐表规划的最大并行数（默认 5）。")
    return parser.parse_args()


# ── 读取 app_authorize 文件 ────────────────────────────────────────────────────

def load_app_auth(relation_id: str, app_auth_json: str) -> tuple[str, str, str]:
    if app_auth_json:
        p = Path(app_auth_json).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的授权文件不存在：{p}")
    else:
        exact = _APP_AUTH_DIR / f"app_authorize_{relation_id}.json"
        if exact.exists():
            p = exact
        else:
            candidates = sorted(
                _APP_AUTH_DIR.glob("app_authorize_*.json"),
                key=lambda f: f.stat().st_mtime, reverse=True,
            )
            if not candidates:
                raise FileNotFoundError(
                    f"未找到授权文件，请先创建应用或手动指定 --app-auth-json。\n（目录：{_APP_AUTH_DIR}）"
                )
            p = candidates[0]

    print(f"[auth] 使用授权文件：{p.name}", file=sys.stderr)
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = data.get("data") or []

    for row in rows:
        if isinstance(row, dict) and str(row.get("appId", "")).strip() == relation_id:
            app_key = str(row.get("appKey", "")).strip()
            sign    = str(row.get("sign", "")).strip()
            if app_key and sign:
                return relation_id, app_key, sign

    if rows and isinstance(rows[0], dict):
        row     = rows[0]
        app_id  = str(row.get("appId", relation_id)).strip()
        app_key = str(row.get("appKey", "")).strip()
        sign    = str(row.get("sign", "")).strip()
        if app_key and sign:
            return app_id, app_key, sign

    raise ValueError(f"授权文件中未找到有效的 appKey/sign：{p}")


# ── 拉取应用结构（HAP v3 API）— 拆分为列表 + 按需拉字段 ────────────────────────

def _hap_headers(app_key: str, sign: str) -> dict:
    return {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }


def _walk_sections(sections: list, worksheets: list) -> None:
    for sec in sections or []:
        for item in sec.get("items") or []:
            if item.get("type") == 0:
                worksheets.append({"id": str(item.get("id", "")), "name": str(item.get("name", ""))})
        _walk_sections(sec.get("childSections") or [], worksheets)


def fetch_worksheet_list(relation_id: str, app_key: str, sign: str) -> tuple[str, list[dict]]:
    """只拉取应用名和工作表列表（表名+表ID），不拉字段。"""
    headers = _hap_headers(app_key, sign)
    print("[fetch] 正在拉取应用信息...", file=sys.stderr)
    resp = requests.get("https://api.mingdao.com/v3/app", headers=headers, timeout=30)
    resp.raise_for_status()
    app_data = resp.json()
    if not app_data.get("success"):
        raise RuntimeError(f"获取应用信息失败：{app_data.get('error_msg', app_data)}")

    info = app_data.get("data") or {}
    app_name = str(info.get("name", relation_id)).strip() or relation_id
    raw_worksheets: list[dict] = []
    _walk_sections(info.get("sections") or [], raw_worksheets)
    worksheets = [ws for ws in raw_worksheets if ws.get("id")]
    print(f"[fetch] 应用：{app_name}，发现 {len(worksheets)} 个工作表", file=sys.stderr)
    return app_name, worksheets


def fetch_worksheet_fields(ws_id: str, app_key: str, sign: str) -> list[dict]:
    """拉取单个工作表的字段列表（含 field_id、type、options）。"""
    headers = _hap_headers(app_key, sign)
    ws_resp = requests.get(
        f"https://api.mingdao.com/v3/app/worksheets/{ws_id}",
        headers=headers, timeout=30,
    )
    ws_resp.raise_for_status()
    ws_data = ws_resp.json()

    fields: list[dict] = []
    if ws_data.get("success"):
        for ctrl in (ws_data.get("data") or {}).get("fields") or []:
            field_id   = str(ctrl.get("id", "")).strip()
            field_name = str(ctrl.get("name", "")).strip()
            type_str   = str(ctrl.get("type", "")).strip()
            if field_id in _SYSTEM_FIELD_IDS:
                continue
            if type_str in _SKIP_TYPE_STRS:
                continue
            if not field_id or not field_name:
                continue

            type_int = _TYPE_STR_TO_INT.get(type_str, 2)
            field: dict = {
                "id": field_id, "name": field_name,
                "type": type_int, "type_str": type_str,
            }
            opts = ctrl.get("options") or []
            if opts:
                field["options"] = [
                    {"key": str(o.get("key", "")), "value": str(o.get("value", ""))}
                    for o in opts if o.get("value")
                ]
            fields.append(field)
    return fields


# ── AI 调用基础设施 ────────────────────────────────────────────────────────────

def _log_prompt(label: str, prompt: str) -> None:
    preview = prompt[:200].replace("\n", " ")
    print(f"[prompt:{label}] 长度={len(prompt)} 字符  预览: {preview!r}", file=sys.stderr)


def _save_raw_json(label: str, raw_json: str, run_ts: str) -> Path:
    _DEBUG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"raw_ai_{label}_{run_ts}.json"
    out_path = _DEBUG_OUTPUT_DIR / filename
    out_path.write_text(raw_json, encoding="utf-8")
    print(f"[debug] AI 原始 JSON → {out_path}", file=sys.stderr)
    return out_path


def _call_ai_once(prompt: str, ai_config: dict, thinking: str) -> str:
    """发起一次 AI API 调用，返回原始文本。含 API 级重试。"""
    budget = None if thinking == "none" else _THINKING_BUDGETS.get(thinking, 8192)
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]
    provider = ai_config.get("provider", "gemini")
    print(f"[ai] 调用中（provider={provider}，model={model_name}，thinking={thinking}）...", file=sys.stderr)
    last_exc = None
    for attempt in range(1, 4):
        try:
            resp = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=create_generation_config(
                    ai_config,
                    response_mime_type="application/json",
                    thinking_budget=budget,
                ),
            )
            return resp.text
        except Exception as exc:
            last_exc = exc
            if attempt < 3:
                wait = min(16, 2 ** (attempt - 1))
                print(f"[ai] API 调用失败（第 {attempt} 次），{wait}s 后重试：{exc}", file=sys.stderr)
                time.sleep(wait)
    raise last_exc


def _call_ai_json(prompt: str, ai_config: dict, thinking: str, label: str, run_ts: str) -> dict:
    """调用 AI 并解析 JSON，含重试。"""
    last_exc: Exception = RuntimeError("未知错误")
    for attempt in range(1, _MAX_JSON_RETRIES + 2):
        try:
            raw = _call_ai_once(prompt, ai_config, thinking)
            print(f"[ai:{label}] 响应长度 {len(raw)} 字符", file=sys.stderr)
            _save_raw_json(label, raw, run_ts)
            return parse_ai_json(raw)
        except Exception as exc:
            last_exc = exc
            if attempt <= _MAX_JSON_RETRIES:
                wait = attempt * 5
                print(f"[ai:{label}] JSON 解析失败（第 {attempt} 次），{wait}s 后重试：{exc}", file=sys.stderr)
                time.sleep(wait)
    raise last_exc


# ── 工作流数量计算 ─────────────────────────────────────────────────────────────

def _calc_workflow_params(num_ws: int) -> dict:
    """根据工作表数量动态计算工作流数量参数，总数不超过 _MAX_TOTAL_WORKFLOWS。"""
    if num_ws <= 3:
        ca_per_ws, ev_per_ws = 2, 1  # 小应用提升到 2，确保 3-6 个自定义动作
    elif num_ws <= 6:
        ca_per_ws, ev_per_ws = 2, 1
    else:
        ca_per_ws, ev_per_ws = 2, 1

    # 覆盖更多工作表：从 ceil(n/2) 提升到 ceil(n*0.7)，确保 3-6 个 custom_actions
    num_ca_ws = num_ws if num_ws <= 3 else min(num_ws, max(3, math.ceil(num_ws * 0.7)))
    total = num_ca_ws * ca_per_ws + ev_per_ws * num_ws
    while total > _MAX_TOTAL_WORKFLOWS and ca_per_ws > 1:
        ca_per_ws -= 1
        total = num_ca_ws * ca_per_ws + ev_per_ws * num_ws
    while total > _MAX_TOTAL_WORKFLOWS and num_ca_ws > 1:
        num_ca_ws -= 1
        total = num_ca_ws * ca_per_ws + ev_per_ws * num_ws

    return {"ca_per_ws": ca_per_ws, "ev_per_ws": ev_per_ws, "num_ca_ws": num_ca_ws}


# ══════════════════════════════════════════════════════════════════════════════
# Phase -1: 表名筛选
# ══════════════════════════════════════════════════════════════════════════════

def _build_filter_prompt(app_name: str, worksheet_names: list[str]) -> str:
    ws_list = "\n".join(f"  {i+1}. {name}" for i, name in enumerate(worksheet_names))
    return f"""应用「{app_name}」包含以下工作表：
{ws_list}

请判断哪些工作表适合作为工作流的触发源（即：当该表数据发生变化时，需要触发自动化业务流程）。

筛选标准：
- 适合触发：主业务实体表（如"订单"、"客户"、"合同"、"报销单"等），数据变动会引发后续业务动作
- 不适合触发：明细/子表（如"订单明细"）、日志/记录表（如"操作日志"）、纯配置/字典表（如"产品分类"）、纯统计/汇总表

注意：被排除的表仍然可以作为其他工作流的跨表操作目标（如 add_record 到明细表），只是不作为触发源。

只输出 JSON，不要解释：
{{"trigger_tables": ["适合触发的表名1", "表名2", ...], "skip_tables": ["不适合触发的表名1", ...]}}"""


def filter_trigger_tables(
    app_name: str,
    worksheet_names: list[str],
    ai_config: dict,
    run_ts: str,
) -> tuple[list[str], list[str]]:
    """Phase -1：AI 判断哪些表适合做工作流触发源。返回 (trigger_names, skip_names)。"""
    if len(worksheet_names) <= 2:
        # 表太少，不值得筛选，全部保留
        print(f"[phase-1] 工作表 ≤ 2，跳过筛选，全部保留", file=sys.stderr)
        return worksheet_names, []

    prompt = _build_filter_prompt(app_name, worksheet_names)
    _log_prompt("phase-1_filter", prompt)

    result = _call_ai_json(prompt, ai_config, "none", "phase-1_filter", run_ts)
    trigger = result.get("trigger_tables", worksheet_names)
    skip = result.get("skip_tables", [])

    # 兜底：如果 AI 全部淘汰了，保留全部
    if not trigger:
        print(f"[phase-1] ⚠ AI 返回 trigger_tables 为空，保留全部工作表", file=sys.stderr)
        return worksheet_names, []

    print(f"[phase-1] ✓ 筛选完成：{len(trigger)} 个触发表，{len(skip)} 个跳过", file=sys.stderr)
    for name in trigger:
        print(f"  ✓ {name}", file=sys.stderr)
    for name in skip:
        print(f"  ✗ {name}（跳过）", file=sys.stderr)
    return trigger, skip


# ══════════════════════════════════════════════════════════════════════════════
# Phase 0: 全局骨架（合并业务关系分析 + 结构规划）
# ══════════════════════════════════════════════════════════════════════════════

def _build_global_skeleton_prompt(
    app_name: str,
    trigger_worksheets: list[dict],  # [{id, name, field_names: [str]}]
    skip_worksheets: list[dict],     # [{id, name}]
    params: dict,
) -> str:
    """构建 Phase 0 全局骨架 prompt。只含表名和字段名（无 ID/UUID），保持轻量。"""
    node_type_section = build_node_type_prompt_section() if build_node_type_prompt_section else ""

    ws_lines = []
    for ws in trigger_worksheets:
        field_names = ws.get("field_names", [])
        ws_lines.append(f"  工作表「{ws['name']}」(id={ws['id']})")
        if field_names:
            ws_lines.append(f"    字段：{'、'.join(field_names[:20])}")
            if len(field_names) > 20:
                ws_lines.append(f"    ...及另外 {len(field_names) - 20} 个字段")
        else:
            ws_lines.append(f"    （无可操作字段）")

    skip_lines = ""
    if skip_worksheets:
        skip_names = "、".join(ws["name"] for ws in skip_worksheets)
        skip_lines = f"\n跳过的工作表（不做触发源，但可作为跨表操作目标）：{skip_names}"

    ca_per_ws = params["ca_per_ws"]
    ev_per_ws = params["ev_per_ws"]
    num_ca_ws = params["num_ca_ws"]
    num_trigger = len(trigger_worksheets)

    return f"""你是一位企业数字化顾问，正在为「{app_name}」规划工作流骨架。

## 应用工作表

触发源工作表（{num_trigger} 个）：
{"".join(ws_lines)}
{skip_lines}

{node_type_section}

## 任务

1. 分析各表之间的业务关联关系（哪些表之间存在数据联动）
2. 为每个触发源工作表规划工作流骨架

## 工作流数量规则

- custom_actions：从 {num_trigger} 个触发表中选 {num_ca_ws} 个，每个 {ca_per_ws} 个
- worksheet_events：每个触发表 {ev_per_ws} 个
- date_triggers：全应用最多 2 个，仅分配给有日期字段的最重要的 2 张表（Phase 1 阶段细化）

## 输出 JSON 格式（严格 JSON，无注释）

{{
  "business_analysis": {{
    "summary": "1-2 句描述核心业务场景",
    "cross_table_flows": [
      {{
        "trigger_table": "触发表名",
        "target_table": "目标表名",
        "action": "add_record 或 update_record",
        "description": "操作说明"
      }}
    ]
  }},
  "worksheets": [
    {{
      "worksheet_id": "取自上方",
      "worksheet_name": "表名",
      "custom_actions": [
        {{
          "name": "业务动作名",
          "confirm_msg": "确认提示",
          "sure_name": "确认",
          "cancel_name": "取消",
          "action_nodes": [
            {{"name": "节点名", "type": "节点类型", "target_worksheet_name": "目标表名"}}
          ]
        }}
      ],
      "worksheet_events": [
        {{
          "name": "事件名[示范]",
          "trigger_id": "1|2|3|4",
          "action_nodes": [
            {{"name": "节点名", "type": "节点类型", "target_worksheet_name": "目标表名"}}
          ]
        }}
      ]
    }}
  ]
}}

## 规则

1. action_nodes 只填 name + type + target_worksheet_name（用表名而非表ID，Phase 1 会转换）
2. 不填 fields/sendContent/fieldValue 等细节（Phase 1 填充）
3. 每个工作流 2~3 个节点，至少 1 个跨表操作
4. trigger_id: "1"=仅新增, "2"=新增或更新, "4"=仅更新, "3"=删除
5. worksheet_events 的 name 末尾加"[示范]"后缀
6. custom_actions 的 name 不加后缀
7. 节点类型只允许 update_record 和 add_record，禁止其他类型
8. 跨表目标可以包含跳过的工作表（如向明细表 add_record）"""


def plan_global_skeleton(
    app_name: str,
    trigger_worksheets: list[dict],
    skip_worksheets: list[dict],
    params: dict,
    ai_config: dict,
    thinking: str,
    run_ts: str,
) -> dict:
    """Phase 0：生成全局骨架。"""
    print(f"\n[phase-0] 全局骨架规划（{len(trigger_worksheets)} 个触发表）", file=sys.stderr)
    prompt = _build_global_skeleton_prompt(app_name, trigger_worksheets, skip_worksheets, params)
    _log_prompt("phase-0_skeleton", prompt)
    result = _call_ai_json(prompt, ai_config, thinking, "phase-0_skeleton", run_ts)

    # 基础校验
    planned_ws = result.get("worksheets", [])
    if not planned_ws:
        raise ValueError("Phase 0 输出缺少 worksheets")
    print(f"[phase-0] ✓ 骨架规划完成：{len(planned_ws)} 个表，"
          f"time_triggers {len(result.get('time_triggers', []))} 个", file=sys.stderr)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: 逐表规划（并行）
# ══════════════════════════════════════════════════════════════════════════════

def _describe_fields_for_prompt(fields: list[dict]) -> str:
    """生成带完整字段 ID 和选项 key 的字段描述（用于 Phase 1 prompt）。"""
    lines = []
    for f in fields:
        if f["type"] in _SKIP_FIELD_TYPES:
            continue
        type_name = _FIELD_TYPE_MAP.get(f["type"], f"type={f['type']}")
        line = f'  field_id="{f["id"]}"  type={f["type"]}({type_name})  {f["name"]}'
        opts = f.get("options") or []
        if opts:
            opt_str = ", ".join(f'key="{o["key"]}" value="{o["value"]}"' for o in opts[:8])
            line += f"  选项: {opt_str}"
            if len(opts) > 8:
                line += f" ...及 {len(opts)-8} 个"
        lines.append(line)
    return "\n".join(lines)


def _build_per_table_prompt(
    ws_info: dict,           # {id, name, fields: [...]}
    skeleton_entry: dict,    # Phase 0 骨架中该表的部分
    cross_table_ws: list[dict],  # 跨表目标表的 [{id, name, fields}]
    time_triggers: list[dict] | None,  # 分配给该表的 time_triggers（如有）
    allow_date_triggers: bool = True,  # 全应用最多 2 个 date_triggers，超出则不分配
) -> str:
    """构建 Phase 1 逐表 prompt。只含本表 + 跨表目标表的字段。"""

    # 本表字段描述
    ws_fields_desc = _describe_fields_for_prompt(ws_info.get("fields", []))
    # 本表可操作字段数
    operable_count = sum(1 for f in ws_info.get("fields", []) if f["type"] not in _SKIP_FIELD_TYPES)
    # 本表日期字段（用于 date_triggers）
    date_fields = [f for f in ws_info.get("fields", []) if f["type"] in (15, 16)]

    # 跨表字段描述
    cross_sections = []
    for cws in cross_table_ws:
        cfields = _describe_fields_for_prompt(cws.get("fields", []))
        c_operable = sum(1 for f in cws.get("fields", []) if f["type"] not in _SKIP_FIELD_TYPES)
        cross_sections.append(
            f"### 跨表目标：「{cws['name']}」(id={cws['id']})\n"
            f"可操作字段数: {c_operable}\n{cfields}"
        )
    cross_desc = "\n\n".join(cross_sections) if cross_sections else "（无跨表目标）"

    # 骨架中的工作流清单
    skeleton_json = json.dumps(skeleton_entry, ensure_ascii=False, indent=2)

    # time_triggers 部分
    tt_section = ""
    if time_triggers:
        tt_json = json.dumps(time_triggers, ensure_ascii=False, indent=2)
        tt_section = f"""
## 该表关联的 time_triggers（需填充字段）

{tt_json}
"""

    # date_triggers 部分
    dt_section = ""
    if date_fields and allow_date_triggers:
        dt_desc = ", ".join(f'"{f["name"]}"(id={f["id"]}, type={f["type"]})' for f in date_fields)
        dt_section = f"""
## 日期字段（可用于 date_triggers）

该表有以下日期字段：{dt_desc}
请为该表规划 1 个 date_triggers（日期到期提醒类工作流），assign_field_id 使用上述日期字段 ID。
"""
    else:
        dt_section = "\n该表没有日期字段或已达全应用 date_triggers 上限（2 个），date_triggers 为空数组 []。\n"

    return f"""你是一名工作流配置专家，正在为工作表「{ws_info['name']}」填充工作流节点的具体配置。

## 本表字段（完整，含 field_id 和选项 key）

工作表「{ws_info['name']}」(id={ws_info['id']})
可操作字段数: {operable_count}
{ws_fields_desc}

## 跨表目标表字段

{cross_desc}

## 已规划的工作流骨架

{skeleton_json}
{tt_section}{dt_section}
## 任务

为骨架中每个工作流的每个 action_node 补充具体配置：
- update_record / add_record：填写 fields 数组
- notify / copy：填写 sendContent
- delay_duration：填写延时参数
- calc / aggregate：填写公式参数
- delete_record：fields 为空数组
- 将 target_worksheet_name 转换为 target_worksheet_id

## 关键规则

1. 单选字段(type=9/11) 的 fieldValue 必须使用上方的完整 UUID key，禁止截断或编造
2. 动态引用触发记录字段值用 {{{{trigger.FIELD_ID}}}}（FIELD_ID 是十六进制，禁止用字段名）
3. add_record 的 fields 应包含目标表全部可操作字段
4. update_record 只填 1~3 个需要更新的字段
5. notify/copy 的内容字段名是 sendContent（不是 content），必须有业务含义
6. time_triggers 的节点字段值禁止 {{{{trigger.xxx}}}}（定时触发没有触发记录）
7. 日期/时间字段(type=15/16) fieldValue 留空 ""（系统自动填当前时间）
8. date_triggers 参数：execute_time_type: 0=当天, 1=日期前N单位, 2=日期后N单位; unit: 1=年,2=月,3=天,4=小时; frequency: 0=不重复

## 输出 JSON

{{
  "worksheet_id": "{ws_info['id']}",
  "worksheet_name": "{ws_info['name']}",
  "custom_actions": [...完整配置...],
  "worksheet_events": [...完整配置...],
  "date_triggers": [...如有日期字段则规划1个...]
}}"""


def plan_single_worksheet(
    ws_info: dict,
    skeleton_entry: dict,
    cross_table_ws: list[dict],
    time_triggers: list[dict] | None,
    ai_config: dict,
    thinking: str,
    run_ts: str,
    allow_date_triggers: bool = True,
) -> dict:
    """Phase 1：为单张表规划完整工作流配置。含重试。"""
    ws_name = ws_info["name"]
    ws_id = ws_info["id"]
    prompt = _build_per_table_prompt(ws_info, skeleton_entry, cross_table_ws, time_triggers, allow_date_triggers)
    label = f"phase-1_{ws_id[:8]}"
    _log_prompt(label, prompt)

    result = _call_ai_json(prompt, ai_config, thinking, label, run_ts)
    # 确保 worksheet_id 正确
    result["worksheet_id"] = ws_id
    result["worksheet_name"] = ws_name
    print(f"[phase-1] ✓ {ws_name}："
          f"custom_actions={len(result.get('custom_actions', []))}, "
          f"worksheet_events={len(result.get('worksheet_events', []))}, "
          f"date_triggers={len(result.get('date_triggers', []))}", file=sys.stderr)
    return result


def plan_all_worksheets(
    trigger_ws_with_fields: list[dict],  # [{id, name, fields}]
    all_ws_map: dict[str, dict],         # {ws_id: {id, name, fields}} 含跳过的表
    skeleton: dict,
    ai_config: dict,
    thinking: str,
    run_ts: str,
    max_parallel: int = 5,
) -> tuple[list[dict], list[dict]]:
    """Phase 1：并行为所有触发表规划工作流。返回 (worksheet_plans, time_trigger_plans)。"""
    skeleton_ws_map: dict[str, dict] = {}
    for ws in skeleton.get("worksheets", []):
        ws_id = ws.get("worksheet_id", "")
        if ws_id:
            skeleton_ws_map[ws_id] = ws

    # 构建表名→表ID映射（用于解析 target_worksheet_name）
    name_to_id: dict[str, str] = {}
    for ws_id, ws_data in all_ws_map.items():
        name_to_id[ws_data["name"]] = ws_id

    # 定时触发已禁用，强制为空
    skeleton_tt = []
    tt_assigned_to: str = ""

    # 预先标记哪些表允许生成 date_triggers（全应用最多 2 个）
    # 取前 2 张有日期字段（type=15/16）的表
    _MAX_DATE_TRIGGER_TABLES = 2
    _dt_allowed_ids: set[str] = set()
    for _ws in trigger_ws_with_fields:
        if len(_dt_allowed_ids) >= _MAX_DATE_TRIGGER_TABLES:
            break
        _has_date = any(f["type"] in (15, 16) for f in _ws.get("fields", []))
        if _has_date:
            _dt_allowed_ids.add(_ws["id"])

    print(f"\n[phase-1] 逐表并行规划（{len(trigger_ws_with_fields)} 个表，max_parallel={max_parallel}）",
          file=sys.stderr)
    print(f"[phase-1] date_triggers 分配给：{[w['name'] for w in trigger_ws_with_fields if w['id'] in _dt_allowed_ids]}",
          file=sys.stderr)

    results: list[dict] = []
    errors: list[str] = []

    def _plan_one(ws_info: dict) -> dict:
        ws_id = ws_info["id"]
        skel = skeleton_ws_map.get(ws_id, {
            "worksheet_id": ws_id,
            "worksheet_name": ws_info["name"],
            "custom_actions": [],
            "worksheet_events": [],
        })

        # 收集跨表目标表
        cross_table_names: set[str] = set()
        for section in ("custom_actions", "worksheet_events"):
            for wf in skel.get(section, []):
                for node in wf.get("action_nodes", []):
                    target_name = node.get("target_worksheet_name", "")
                    if target_name and target_name != ws_info["name"]:
                        cross_table_names.add(target_name)

        # 按需获取跨表字段
        cross_table_list: list[dict] = []
        for ct_name in cross_table_names:
            ct_id = name_to_id.get(ct_name)
            if ct_id and ct_id in all_ws_map:
                cross_table_list.append(all_ws_map[ct_id])

        # time_triggers 分配
        tt = skeleton_tt if ws_id == tt_assigned_to else None

        return plan_single_worksheet(
            ws_info, skel, cross_table_list, tt, ai_config, thinking, run_ts,
            allow_date_triggers=(ws_id in _dt_allowed_ids),
        )

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        future_map = {pool.submit(_plan_one, ws): ws for ws in trigger_ws_with_fields}
        for future in as_completed(future_map):
            ws = future_map[future]
            try:
                plan = future.result()
                results.append(plan)
            except Exception as exc:
                err_msg = f"表「{ws['name']}」规划失败：{exc}"
                print(f"[phase-1] ✗ {err_msg}", file=sys.stderr)
                errors.append(err_msg)
                # 生成空壳，不阻断其他表
                results.append({
                    "worksheet_id": ws["id"],
                    "worksheet_name": ws["name"],
                    "custom_actions": [],
                    "worksheet_events": [],
                    "date_triggers": [],
                    "_error": str(exc),
                })

    if errors:
        print(f"[phase-1] ⚠ {len(errors)} 个表规划失败", file=sys.stderr)

    # 从第一个表的结果中提取 time_triggers（如果有的话由 Phase 1 prompt 返回）
    # time_triggers 是全局的，不在逐表结果中——使用骨架中的 time_triggers
    return results, skeleton_tt


# ── 后处理 ─────────────────────────────────────────────────────────────────────

def _fix_trigger_references(plan: dict, ws_fields_map: dict[str, dict[str, str]]) -> int:
    """将 AI 可能生成的 {{trigger.字段名}} 修正为 {{trigger.field_id}}。"""
    fix_count = 0

    def _fix_value(value: str, trigger_ws_id: str) -> str:
        nonlocal fix_count
        if "{{trigger." not in value:
            return value
        name_map = ws_fields_map.get(trigger_ws_id, {})

        def replacer(m: re.Match) -> str:
            nonlocal fix_count
            ref = m.group(1)
            if re.fullmatch(r'[0-9a-f]{24}', ref):
                return m.group(0)
            field_id = name_map.get(ref)
            if field_id:
                fix_count += 1
                return f"{{{{trigger.{field_id}}}}}"
            return m.group(0)

        return re.sub(r'\{\{trigger\.([^}]+)\}\}', replacer, value)

    for ws in plan.get("worksheets", []):
        ws_id = ws.get("worksheet_id", "")
        for group_key in ("custom_actions", "worksheet_events"):
            for wf in ws.get(group_key) or []:
                for node in wf.get("action_nodes") or []:
                    for field in node.get("fields") or []:
                        if not isinstance(field, dict):
                            continue
                        fv = str(field.get("fieldValue", "") or "")
                        field["fieldValue"] = _fix_value(fv, ws_id)
    return fix_count


def _normalize_notify_content(plan: dict) -> int:
    """将 sendContent 字段重命名为 content，兼容 execute_workflow_plan.py。"""
    count = 0

    def _fix_nodes(nodes: list) -> None:
        nonlocal count
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if "sendContent" in node and "content" not in node:
                node["content"] = node.pop("sendContent")
                count += 1

    for ws in plan.get("worksheets", []):
        for section in ("custom_actions", "worksheet_events"):
            for item in ws.get(section, []):
                _fix_nodes(item.get("action_nodes", []))
        for dt in ws.get("date_triggers", []):
            _fix_nodes(dt.get("action_nodes", []))
    for tt in plan.get("time_triggers", []):
        _fix_nodes(tt.get("action_nodes", []))
    return count


def _resolve_target_names_to_ids(plan: dict, name_to_id: dict[str, str]) -> int:
    """将 action_nodes 中的 target_worksheet_name 转换为 target_worksheet_id。"""
    resolved = 0

    def _fix_nodes(nodes: list) -> None:
        nonlocal resolved
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            # 如果已有 target_worksheet_id 且是合法 24 位 hex，跳过
            tid = str(node.get("target_worksheet_id", "")).strip()
            if re.fullmatch(r'[0-9a-f]{24}', tid):
                continue
            # 尝试从 target_worksheet_name 解析
            tname = node.get("target_worksheet_name", "")
            if tname and tname in name_to_id:
                node["target_worksheet_id"] = name_to_id[tname]
                resolved += 1

    for ws in plan.get("worksheets", []):
        for section in ("custom_actions", "worksheet_events"):
            for item in ws.get(section, []):
                _fix_nodes(item.get("action_nodes", []))
        for dt in ws.get("date_triggers", []):
            _fix_nodes(dt.get("action_nodes", []))
    for tt in plan.get("time_triggers", []):
        _fix_nodes(tt.get("action_nodes", []))
    return resolved


def _enrich_fields(plan: dict, all_ws_map: dict) -> int:
    """后处理：统一字段键名并从 all_ws_map 补充 type。

    AI 可能输出 field_id（下划线），执行层期望 fieldId（驼峰）。
    AI 不输出 type，执行层校验时需要整数 type。
    此函数：
      1. field_id / field_value → fieldId / fieldValue
      2. 从 all_ws_map 反查字段 type，找不到则默认 2（文本）
    """
    # 构建 field_id → type 的全局查找表
    field_type_map: dict[str, int] = {}
    for ws_data in all_ws_map.values():
        for f in ws_data.get("fields", []):
            fid = f.get("id", "")
            ftype = f.get("type")
            if fid and ftype is not None:
                try:
                    field_type_map[fid] = int(ftype)
                except (TypeError, ValueError):
                    pass

    enriched = 0

    def _fix_fields(fields: list) -> None:
        nonlocal enriched
        for f in fields:
            if not isinstance(f, dict):
                continue
            # 统一键名
            if "field_id" in f and "fieldId" not in f:
                f["fieldId"] = f.pop("field_id")
            if "field_value" in f and "fieldValue" not in f:
                f["fieldValue"] = f.pop("field_value")
            # 补充 type
            if "type" not in f:
                fid = f.get("fieldId", "")
                f["type"] = field_type_map.get(fid, 2)
                enriched += 1

    def _fix_nodes(nodes: list) -> None:
        for node in nodes:
            if isinstance(node, dict):
                _fix_fields(node.get("fields") or [])

    for ws in plan.get("worksheets", []):
        for section in ("custom_actions", "worksheet_events"):
            for item in ws.get(section, []):
                _fix_nodes(item.get("action_nodes", []))
        for dt in ws.get("date_triggers", []):
            _fix_nodes(dt.get("action_nodes", []))
    for tt in plan.get("time_triggers", []):
        _fix_nodes(tt.get("action_nodes", []))

    return enriched


def _cap_workflows(planned_ws: list[dict], planned_tt: list[dict]) -> None:
    """硬性截断：AI 可能无视数量限制，强制不超过 _MAX_TOTAL_WORKFLOWS。"""
    total_ca = sum(len(ws.get("custom_actions") or []) for ws in planned_ws)
    total_ev = sum(len(ws.get("worksheet_events") or []) for ws in planned_ws)
    total = total_ca + total_ev + len(planned_tt)
    if total <= _MAX_TOTAL_WORKFLOWS:
        return

    print(f"[cap] 工作流总数 {total} 超过上限 {_MAX_TOTAL_WORKFLOWS}，开始截断...", file=sys.stderr)
    # 先截 custom_actions
    remaining = _MAX_TOTAL_WORKFLOWS - total_ev - len(planned_tt)
    if remaining < 0:
        remaining = 0
    for ws in planned_ws:
        ca = ws.get("custom_actions") or []
        if len(ca) > 1 and total_ca > remaining:
            ws["custom_actions"] = ca[:1]
            total_ca = sum(len(w.get("custom_actions") or []) for w in planned_ws)
    # 再截 worksheet_events
    ev_budget = _MAX_TOTAL_WORKFLOWS - total_ca - len(planned_tt)
    if ev_budget < total_ev:
        ev_count = 0
        for ws in planned_ws:
            ev = ws.get("worksheet_events") or []
            if ev_count + len(ev) > ev_budget:
                ws["worksheet_events"] = ev[:max(0, ev_budget - ev_count)]
            ev_count += len(ws.get("worksheet_events") or [])
    # 最后截 time_triggers
    tt_budget = _MAX_TOTAL_WORKFLOWS - sum(len(ws.get("custom_actions") or []) for ws in planned_ws) - sum(len(ws.get("worksheet_events") or []) for ws in planned_ws)
    if tt_budget < len(planned_tt):
        del planned_tt[max(1, tt_budget):]


# ── 简化模式：为第一个工作表生成 1 个 custom_action + 1 个 worksheet_event ──────

def _build_simple_prompt(ws_info: dict) -> str:
    """为第一张工作表生成恰好 1 个 custom_action + 1 个 worksheet_event 的 prompt。"""
    ws_fields_desc = _describe_fields_for_prompt(ws_info.get("fields", []))
    operable_count = sum(1 for f in ws_info.get("fields", []) if f["type"] not in _SKIP_FIELD_TYPES)

    return f"""你是一名工作流配置专家，正在为工作表「{ws_info['name']}」规划工作流。

## 本表字段（完整，含 field_id 和选项 key）

工作表「{ws_info['name']}」(id={ws_info['id']})
可操作字段数: {operable_count}
{ws_fields_desc}

## 任务

为该工作表规划**恰好 2 个工作流**：
1. custom_actions：1 个自定义按钮（name 体现业务动作，如"审批通过""标记完成"）
2. worksheet_events：1 个工作表事件触发（监听数据变化触发业务流程）

每个工作流包含 2~3 个 action_nodes，节点类型只允许 update_record 和 add_record。

## 关键规则

1. 单选字段(type=9/11) 的 fieldValue 必须使用上方的完整 UUID key，禁止截断或编造
2. 动态引用触发记录字段值用 {{{{trigger.FIELD_ID}}}}（FIELD_ID 是十六进制，禁止用字段名）
3. update_record 只填 1~3 个需要更新的字段
4. add_record 的 fields 应包含目标表全部可操作字段
5. target_worksheet_id 填本表 ID：{ws_info['id']}
6. 日期/时间字段(type=15/16) fieldValue 留空 ""

## 输出 JSON（严格 JSON，无注释，无多余字段）

{{
  "worksheet_id": "{ws_info['id']}",
  "worksheet_name": "{ws_info['name']}",
  "custom_actions": [
    {{
      "name": "业务动作名",
      "confirm_msg": "确认提示（说明操作影响）",
      "sure_name": "确认",
      "cancel_name": "取消",
      "action_nodes": [
        {{
          "name": "节点名",
          "type": "update_record",
          "target_worksheet_id": "{ws_info['id']}",
          "fields": [
            {{"fieldId": "字段ID", "fieldValue": "值", "type": 字段类型整数}}
          ]
        }}
      ]
    }}
  ],
  "worksheet_events": [
    {{
      "name": "事件名",
      "trigger_id": "2",
      "action_nodes": [
        {{
          "name": "节点名",
          "type": "update_record",
          "target_worksheet_id": "{ws_info['id']}",
          "fields": [
            {{"fieldId": "字段ID", "fieldValue": "{{{{trigger.字段ID}}}}", "type": 字段类型整数}}
          ]
        }}
      ]
    }}
  ]
}}"""


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    started_at = time.time()
    args = parse_args()
    script_name = Path(__file__).stem
    log_args = {k: v for k, v in vars(args).items()}
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"工作流规划（简化模式：仅第一张表，1 custom_action + 1 worksheet_event）", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # 1. 读取 appKey + sign
    print(f"\n[step 1/3] 读取应用授权（relation_id={args.relation_id}）", file=sys.stderr)
    try:
        _, app_key, sign = load_app_auth(args.relation_id, args.app_auth_json)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 2

    # 2. 拉取工作表列表，取第一个
    try:
        app_name, ws_list = fetch_worksheet_list(args.relation_id, app_key, sign)
    except Exception as exc:
        print(f"Error: 拉取应用结构失败：{exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 1

    if not ws_list:
        msg = "未获取到任何工作表，请检查 appKey/sign 是否有效。"
        print(f"Warning: {msg}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=msg, started_at=started_at)
        return 1

    first_ws = ws_list[0]
    print(f"[step 1/3] ✓ 应用：{app_name}，共 {len(ws_list)} 个工作表，使用第一个：「{first_ws['name']}」", file=sys.stderr)

    # 3. 拉取第一张表字段
    print(f"\n[step 2/3] 拉取工作表「{first_ws['name']}」字段...", file=sys.stderr)
    fields = fetch_worksheet_fields(first_ws["id"], app_key, sign)
    ws_info = {"id": first_ws["id"], "name": first_ws["name"], "fields": fields}
    print(f"[step 2/3] ✓ {len(fields)} 个字段", file=sys.stderr)

    # 4. AI 配置 + 单次调用
    try:
        ai_config = load_ai_config()
    except Exception as exc:
        print(f"Error: 获取 AI 配置失败：{exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 2

    print(f"\n[step 3/3] AI 规划工作流...", file=sys.stderr)
    prompt = _build_simple_prompt(ws_info)
    _log_prompt("simple_plan", prompt)
    try:
        ai_result = _call_ai_json(prompt, ai_config, "none", "simple_plan", run_ts)
    except Exception as exc:
        print(f"Error: AI 调用失败：{exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 1

    # 确保 worksheet_id/name 正确，强制截断为 1 个
    ai_result["worksheet_id"] = ws_info["id"]
    ai_result["worksheet_name"] = ws_info["name"]
    ai_result["custom_actions"] = (ai_result.get("custom_actions") or [])[:1]
    ai_result["worksheet_events"] = (ai_result.get("worksheet_events") or [])[:1]
    ai_result["date_triggers"] = []

    ws_plans = [ai_result]
    tt_plans: list = []

    # ── 后处理 ──────────────────────────────────────────────────────────────
    all_ws_map = {ws_info["id"]: ws_info}
    name_to_id = {ws_info["name"]: ws_info["id"]}
    ws_fields_map = {ws_info["id"]: {f["name"]: f["id"] for f in fields if f.get("name") and f.get("id")}}

    plan: dict = {
        "app_id": args.relation_id,
        "app_name": app_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": ai_config["model"],
        "thinking": "none",
        "planning_mode": "simple_first_table",
        "worksheets": ws_plans,
        "time_triggers": tt_plans,
    }

    resolved = _resolve_target_names_to_ids(plan, name_to_id)
    if resolved:
        print(f"[fix] 解析了 {resolved} 个 target_worksheet_name → target_worksheet_id", file=sys.stderr)

    fix_count = _fix_trigger_references(plan, ws_fields_map)
    if fix_count:
        print(f"[fix] 修正了 {fix_count} 个 trigger 引用（字段名→字段ID）", file=sys.stderr)

    nc_count = _normalize_notify_content(plan)
    if nc_count:
        print(f"[fix] sendContent→content 修正 {nc_count} 个节点", file=sys.stderr)

    enrich_count = _enrich_fields(plan, all_ws_map)
    if enrich_count:
        print(f"[fix] 补全字段 type {enrich_count} 个", file=sys.stderr)

    # ── 统计 & 写出 ────────────────────────────────────────────────────────
    total_ca = len(ai_result.get("custom_actions") or [])
    total_ev = len(ai_result.get("worksheet_events") or [])

    print(f"\n[output] 规划完成：工作表「{first_ws['name']}」，"
          f"自定义动作 {total_ca}，事件触发 {total_ev}，共 {total_ca + total_ev} 个工作流", file=sys.stderr)

    if args.output:
        out = Path(args.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[output] {out}", file=sys.stderr)

    persist(script_name, plan, args=log_args, started_at=started_at)

    elapsed = time.time() - started_at
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"✅ 工作流规划完成！（耗时 {elapsed:.0f}s）", file=sys.stderr)
    print(f"   应用：{app_name}", file=sys.stderr)
    print(f"   工作表：{first_ws['name']}", file=sys.stderr)
    print(f"   工作流：{total_ca + total_ev} 个（custom_action={total_ca}, worksheet_event={total_ev}）", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
