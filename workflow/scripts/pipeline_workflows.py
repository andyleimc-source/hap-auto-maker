#!/usr/bin/env python3
"""
一键生成工作流规划 JSON（pipeline_workflows.py）

功能：
  1. 从 data/outputs/app_authorizations/app_authorize_{appId}.json 自动读取
     appKey + sign，通过 HAP v3 API 拉取应用结构
     （应用名称 / 工作表名称 / 字段名称、字段ID 及下拉选项 key/value）
  2. 将结构描述提交给 Gemini，为每个工作表规划 6 个工作流：
       - 3 个自定义动作（按钮触发）
       - 1 个工作表事件触发
       - 1 个时间触发（一次性执行）
       - 1 个定时触发（循环执行）
     每个工作流包含 2-3 个有实际字段映射的动作节点。
  3. 生成 output/pipeline_workflows_latest.json，供 execute_workflow_plan.py 执行

Gemini Key 优先级：
  1. --gemini-key 参数
  2. 环境变量 GEMINI_API_KEY
  3. config/credentials/gemini_auth.json 中的 api_key 字段

用法示例：
  cd /Users/andy/Desktop/hap_auto/workflow
  python3 scripts/pipeline_workflows.py \\
    --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9'
"""

from __future__ import annotations

import json
import math
import os
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time

import requests

sys.path.insert(0, str(Path(__file__).parent))
from workflow_io import persist

# 引入共享的健壮 JSON 解析工具
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from ai_utils import AI_CONFIG_PATH, create_generation_config, get_ai_client, load_ai_config  # type: ignore


# ── 常量 ───────────────────────────────────────────────────────────────────────

_PROJECT_ROOT     = Path(__file__).resolve().parents[2]
_APP_AUTH_DIR     = _PROJECT_ROOT / "data" / "outputs" / "app_authorizations"
_GEMINI_AUTH_JSON = AI_CONFIG_PATH

_FIELD_TYPE_MAP = {
    2: "文本", 3: "电话", 4: "证件号", 5: "Email", 6: "数字",
    7: "金额", 8: "大写金额", 9: "单选", 10: "多选", 11: "下拉单选",
    14: "附件", 15: "日期", 16: "日期时间", 19: "地区", 21: "自由关联",
    24: "备注", 26: "成员", 27: "部门", 28: "成员(多)", 29: "关联记录",
    30: "查找引用", 31: "公式", 32: "文本公式", 35: "子表",
    36: "检查框", 37: "评分", 40: "定位", 41: "富文本",
    42: "签名", 43: "条形码", 45: "嵌入",
}

# v3 API 返回的字符串类型 → HAP 内部数字类型（flowNode/saveNode 使用数字）
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

# 不适合在 action_nodes.fields 中直接设值的字段类型（字符串形式，抓取时过滤）
_SKIP_TYPE_STRS: set[str] = {
    "Attachment", "FreeAssociation", "Relation", "Lookup",
    "Formula", "DateFormula", "TextFormula", "SubSheet",
    "Signature", "Embed", "Collaborator", "Member",
    "Department", "MemberMultiple",
}

# HAP 系统内置字段 ID（不可写，过滤）
_SYSTEM_FIELD_IDS: set[str] = {
    "rowid", "ownerid", "caid", "ctime", "utime", "uaid",
    "wfname", "wfcuaids", "wfcaid", "wfctime", "wfrtime",
    "wfcotime", "wfdtime", "wfftime", "wfstatus",
}

# 不适合在 action_nodes.fields 中直接设值的字段类型（数字形式，prompt 过滤）
_SKIP_FIELD_TYPES = {14, 21, 29, 30, 31, 32, 35, 42, 43, 45}


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="调用 AI 规划 6 个工作流/工作表（含字段映射），生成 pipeline_workflows_latest.json。"
    )
    parser.add_argument("--relation-id", required=True, help="应用 ID（relationId）。")
    parser.add_argument("--app-auth-json", default="", help="应用授权 JSON 文件路径（留空则自动匹配）。")
    parser.add_argument("--thinking", default="none", choices=["none", "low", "medium", "high"], help="主规划调用的推理深度（默认：none）。Prompt 已内置业务分析，无需额外推理；high thinking 反而易导致 JSON 输出破损。")
    parser.add_argument("--skip-analysis", action="store_true", help="跳过业务关系预分析（直接规划，速度更快但质量略低）。")
    parser.add_argument("--output", default="", help="自定义输出路径（默认写入 output/pipeline_workflows_latest.json）。")
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
                key=lambda f: f.stat().st_mtime,
                reverse=True,
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


# ── 拉取应用结构（HAP v3 API）─────────────────────────────────────────────────

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


def fetch_app_structure(relation_id: str, app_key: str, sign: str) -> dict:
    headers = _hap_headers(app_key, sign)

    print("[fetch] 正在拉取应用信息...", file=sys.stderr)
    resp = requests.get("https://api.mingdao.com/v3/app", headers=headers, timeout=30)
    resp.raise_for_status()
    app_data = resp.json()

    if not app_data.get("success"):
        raise RuntimeError(f"获取应用信息失败：{app_data.get('error_msg', app_data)}")

    info     = app_data.get("data") or {}
    app_name = str(info.get("name", relation_id)).strip() or relation_id

    raw_worksheets: list[dict] = []
    _walk_sections(info.get("sections") or [], raw_worksheets)
    print(f"[fetch] 应用：{app_name}，发现 {len(raw_worksheets)} 个工作表", file=sys.stderr)

    worksheets: list[dict] = []
    for ws in raw_worksheets:
        ws_id, ws_name = ws["id"], ws["name"]
        if not ws_id:
            continue

        print(f"[fetch]   ├─ {ws_name}（{ws_id}）拉取字段...", file=sys.stderr)
        ws_resp = requests.get(
            f"https://api.mingdao.com/v3/app/worksheets/{ws_id}",
            headers=headers, timeout=30,
        )
        ws_resp.raise_for_status()
        ws_data = ws_resp.json()

        fields: list[dict] = []
        if ws_data.get("success"):
            # v3 API: 字段数组在 data.fields（不是 controls），type 为字符串
            for ctrl in (ws_data.get("data") or {}).get("fields") or []:
                field_id   = str(ctrl.get("id", "")).strip()
                field_name = str(ctrl.get("name", "")).strip()
                type_str   = str(ctrl.get("type", "")).strip()

                # 跳过系统字段
                if field_id in _SYSTEM_FIELD_IDS:
                    continue
                # 跳过不可写类型
                if type_str in _SKIP_TYPE_STRS:
                    continue
                # 跳过 id 或 name 为空
                if not field_id or not field_name:
                    continue

                type_int = _TYPE_STR_TO_INT.get(type_str, 2)  # 未知类型默认按文本(2)处理
                field: dict = {
                    "id":       field_id,
                    "name":     field_name,
                    "type":     type_int,
                    "type_str": type_str,
                }
                opts = ctrl.get("options") or []
                if opts:
                    field["options"] = [
                        {"key": str(o.get("key", "")), "value": str(o.get("value", ""))}
                        for o in opts if o.get("value")
                    ]
                fields.append(field)

        print(f"[fetch]      └─ {len(fields)} 个字段", file=sys.stderr)
        worksheets.append({"id": ws_id, "name": ws_name, "fields": fields})

    return {"app_name": app_name, "app_id": relation_id, "worksheets": worksheets}


# ── 构建 Gemini Prompt ─────────────────────────────────────────────────────────

def _describe_app_for_prompt(app_structure: dict) -> str:
    """
    生成带完整字段 ID 和选项 key 的应用描述，让 Gemini 能直接引用这些 ID。
    每个工作表标注可操作字段总数。add_record 要求填全部字段，update_record 只填业务相关字段。
    """
    lines = [f"应用名称：{app_structure.get('app_name', '未知应用')}", ""]
    for ws in app_structure.get("worksheets", []):
        valid_fields = [
            f for f in ws.get("fields", [])
            if f.get("id") and f.get("name") and f["type"] not in _SKIP_FIELD_TYPES
        ]
        lines.append(f"┌─ 工作表：{ws['name']}")
        lines.append(f"│  worksheet_id = \"{ws['id']}\"")
        lines.append(f"│  可操作字段数 = {len(valid_fields)}（add_record 须填全部，update_record 只填业务相关字段）")
        if not valid_fields:
            lines.append("│  （无可操作字段）")
        for f in valid_fields:
            type_name = _FIELD_TYPE_MAP.get(f["type"], f"type={f['type']}")
            lines.append(f"│  ├─ 字段「{f['name']}」  field_id=\"{f['id']}\"  type={f['type']}({type_name})")
            for opt in (f.get("options") or [])[:6]:
                lines.append(f"│  │   选项 key=\"{opt['key']}\"  value=\"{opt['value']}\"")
        lines.append("└" + "─" * 40)
        lines.append("")
    return "\n".join(lines)


def _future_date(days_ahead: int = 1, hour: int = 9) -> str:
    return (datetime.now() + timedelta(days=days_ahead)).strftime(f"%Y-%m-%d {hour:02d}:00")


def _end_date(months_ahead: int = 18, hour: int = 9) -> str:
    return (datetime.now() + timedelta(days=30 * months_ahead)).strftime(f"%Y-%m-%d {hour:02d}:00")


# ── 业务关系预分析 ─────────────────────────────────────────────────────────────

def build_analysis_prompt(app_structure: dict) -> str:
    """
    构建业务关系分析 Prompt。
    只传入表名 + 字段名（不含 field_id），让 Gemini 以业务视角分析各表关联。
    """
    app_name = app_structure.get("app_name", "该应用")
    lines = [f"应用名称：{app_name}", ""]
    for ws in app_structure.get("worksheets", []):
        valid_fields = [
            f for f in ws.get("fields", [])
            if f.get("id") and f.get("name") and f["type"] not in _SKIP_FIELD_TYPES
        ]
        field_names = "、".join(f["name"] for f in valid_fields) or "（无字段）"
        lines.append(f"  工作表：{ws['name']}（id={ws['id']}）")
        lines.append(f"    字段：{field_names}")
    app_desc_simple = "\n".join(lines)

    return f"""请分析「{app_name}」中各工作表的业务关联关系。

{app_desc_simple}

请识别：当某张工作表发生数据变化（新增/修改）时，通常需要对哪些其他表进行什么操作（新增记录 or 更新记录），以实现跨表数据联动。

只输出 JSON，不要任何解释：
{{
  "app_summary": "1-2 句描述该应用的核心业务场景",
  "cross_table_flows": [
    {{
      "trigger_worksheet_id": "触发表ID",
      "trigger_worksheet_name": "触发表名",
      "trigger_event": "触发场景简述（如：新增销售订单）",
      "targets": [
        {{
          "worksheet_id": "目标表ID",
          "worksheet_name": "目标表名",
          "action": "add_record 或 update_record",
          "description": "具体操作说明（如：在库存表中减少对应商品库存数量）"
        }}
      ]
    }}
  ]
}}"""


def analyze_relationships(app_structure: dict, ai_config: dict) -> dict:
    """调用 AI 分析各工作表的业务关联关系（轻量调用，使用 fast 档位）。"""
    print("[ai] 第1步：分析业务关联关系...", file=sys.stderr)
    prompt = build_analysis_prompt(app_structure)
    # 业务分析使用 fast 档位即可
    fast_config = load_ai_config(tier="fast")
    try:
        result = call_ai(prompt, fast_config, thinking="none")
        flows = result.get("cross_table_flows", [])
        summary = result.get("app_summary", "")
        print(f"[ai] 业务分析完成：{summary}", file=sys.stderr)
        print(f"[ai] 识别跨表数据流转 {len(flows)} 条", file=sys.stderr)
        return result
    except Exception as exc:
        print(f"[ai] 业务关系分析失败（跳过）：{exc}", file=sys.stderr)
        return {}


def _fix_trigger_references(plan: dict, app_structure: dict) -> int:
    """
    后处理：将 Gemini 可能生成的 {{trigger.字段名}} 修正为 {{trigger.field_id}}。
    返回修正的引用数量。
    """
    # 构建每个工作表的 字段名→字段ID 映射
    ws_field_maps: dict[str, dict[str, str]] = {}
    for ws in app_structure.get("worksheets", []):
        name_to_id: dict[str, str] = {}
        for f in ws.get("fields", []):
            if f.get("name") and f.get("id"):
                name_to_id[f["name"]] = f["id"]
        ws_field_maps[ws["id"]] = name_to_id

    fix_count = 0

    def _fix_value(value: str, trigger_ws_id: str) -> str:
        nonlocal fix_count
        if "{{trigger." not in value:
            return value
        name_map = ws_field_maps.get(trigger_ws_id, {})

        def replacer(m: re.Match) -> str:
            nonlocal fix_count
            ref = m.group(1)
            # 已经是十六进制 field_id，跳过
            if re.fullmatch(r'[0-9a-f]{24}', ref):
                return m.group(0)
            # 尝试按字段名解析
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


def _format_relationships(relationships: dict) -> str:
    """将业务关系分析结果格式化为 prompt 中可读的文字段落。"""
    if not relationships:
        return "（未做业务关系预分析）"
    lines = []
    summary = relationships.get("app_summary", "")
    if summary:
        lines.append(f"业务场景：{summary}")
        lines.append("")
    for flow in relationships.get("cross_table_flows", []):
        trigger = f"{flow.get('trigger_worksheet_name')}（{flow.get('trigger_event', '')}）"
        lines.append(f"▸ {trigger}")
        for t in flow.get("targets", []):
            act = "→ 新增记录到" if t.get("action") == "add_record" else "→ 更新记录在"
            lines.append(f"    {act}「{t.get('worksheet_name')}」：{t.get('description', '')}")
    return "\n".join(lines) if lines else "（未识别到跨表关系）"


# ── 构建主规划 Prompt ──────────────────────────────────────────────────────────

def build_prompt(app_structure: dict, relationships: dict | None = None) -> str:
    app_desc      = _describe_app_for_prompt(app_structure)
    app_name      = app_structure.get("app_name", "该应用")
    ws_ids        = [{"id": ws["id"], "name": ws["name"]} for ws in app_structure.get("worksheets", [])]
    ws_list       = json.dumps(ws_ids, ensure_ascii=False)
    ex_time       = _future_date(1, 9)
    ex_end        = _end_date(18, 9)
    rel_section   = _format_relationships(relationships or {})
    num_ws        = len(ws_ids)
    num_ca_ws     = math.ceil(num_ws / 2)        # 有自定义动作的工作表数量
    ca_per_ws     = 3                             # 每个被选中的工作表的自定义动作数
    ev_per_ws     = 2                             # 每个工作表的事件触发数
    num_tt        = 2                             # 全局时间触发数

    return f"""你是一位资深的企业数字化顾问，正在为「{app_name}」这个 HAP 明道云应用规划工作流自动化。

以下是该应用的完整结构（每个字段都标注了 field_id，选项标注了 key）：

{app_desc}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 业务关系分析（必须基于此设计跨表数据流转）

{rel_section}

🔴 核心要求：工作流必须体现真实的跨表数据联动，禁止所有 action_nodes 都指向同一张表。
   每个工作流的 action_nodes 中，至少一个节点的 target_worksheet_id 必须与触发表不同（跨表操作）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 任务：精确生成以下工作流

🔹 custom_actions（自定义动作 / 按钮触发）：
  - 总共 {num_ca_ws} 个工作表拥有 custom_actions，每个工作表精确 {ca_per_ws} 个，场景各不相同
  - 由你从 {num_ws} 个工作表中随机选择 {num_ca_ws} 个来分配，其余工作表的 custom_actions 为空数组 []
🔹 worksheet_events（工作表事件触发）：
  - 每个工作表精确 {ev_per_ws} 个，触发条件各不相同
🔹 time_triggers（时间触发）：
  - 全应用共精确 {num_tt} 个，针对不同工作表

每个工作流必须包含 2~3 个 action_nodes。
🏷️ name 后缀规则：
  - custom_actions 的 name 不加任何后缀（因为按钮名称直接面向用户）
  - worksheet_events 和 time_triggers 的 name 末尾必须加上"[示范]"后缀，例如："新增客户时初始化状态[示范]"、"每日清晨预排产[示范]"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 worksheet_events 的 trigger_id 含义（必须严格遵守）

  "1" = 仅新增记录时触发
  "2" = 当新增或更新记录时触发
  "4" = 仅更新记录时触发
  "3" = 删除记录时触发（⚠️ 极少使用，除非业务确实需要在删除时联动）

🚨 trigger_id 必须与工作流名称和 action_nodes 的业务语义一致：
  - 名称含"新增/录入/创建"→ trigger_id 用 "1" 或 "2"
  - 名称含"更新/修改/变更/状态切换"→ trigger_id 用 "4" 或 "2"
  - 名称含"删除/移除/作废"→ trigger_id 用 "3"
  - 如果 action_nodes 中有 update_record 更新触发表自身，则 trigger_id 不能是 "3"（删除后无法更新）
  - 每个工作表的 {ev_per_ws} 个 worksheet_events 应使用不同的 trigger_id，覆盖不同触发场景

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 动作节点（action_nodes）规则

每个 action_node 必须包含：
  - name: 节点名称（如"更新订单状态"、"新增库存变动记录"）
  - type: "update_record"（更新触发表记录）或 "add_record"（向目标表新增记录）
  - target_worksheet_id: 目标工作表 ID（必须来自上方结构，不能编造）
  - fields: 字段映射数组（见下方格式）

🚨 字段填充规则（按节点类型区分）：
  ▸ type=add_record（新增记录）：fields 必须填写目标工作表的【全部可操作字段】，一个都不能少。
  ▸ type=update_record（更新记录）：fields 只填写本次业务操作需要更新的字段（1~3 个），
    根据实际业务语义选择要更新的字段和值，不要把所有字段都填进去。
    例如："确认订单"只需更新「订单状态」字段为"已确认"，不需要更新客户名、金额等无关字段。

fields 中每项格式：
  {{"fieldId": "<上方列出的 field_id>", "type": <字段type数字>, "enumDefault": 0, "fieldValue": "<值>"}}

fieldValue 值的填写规则：
  • 文本字段（type=2）：直接填写文本，如 "已处理"、"待审核"
  • 单选/下拉（type=9/11）：必须使用选项的 key（UUID），不能用显示名称
  • 数字/金额（type=6/7）：填数字字符串，如 "0"、"100"
  • 日期/时间（type=15/16）：留空 ""（系统处理）
  • 引用触发记录的字段值：{{{{trigger.<字段的field_id>}}}}
    ⚠️ 这里的 FIELD_ID 必须是上方列出的十六进制字段 ID（如 69aead6f2c5497945dc602ac），
    绝对不能用字段名称（如「客户名称」）！
    示例：{{{{trigger.69aead6f2c5497945dc602ac}}}}  ← 正确
          {{{{trigger.客户名称}}}}  ← 错误！禁止！
    ⚠️ 仅限 custom_actions 和 worksheet_events 可用；time_triggers 禁止使用

type=update_record：更新触发该工作流的记录，target_worksheet_id = 触发工作表
type=add_record：向目标表新增一条记录，可跨表，所有触发类型均适用

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📐 输出 JSON 格式（严格遵守，不要添加任何解释）

{{
  "worksheets": [
    {{
      "worksheet_id": "（来自上方，不能编造）",
      "worksheet_name": "工作表名称",
      "custom_actions": [
        {{
          "name": "业务动作名1",
          "confirm_msg": "确认提示（说明操作影响）",
          "sure_name": "确认",
          "cancel_name": "取消",
          "action_nodes": [
            {{
              "name": "更新本表状态",
              "type": "update_record",
              "target_worksheet_id": "（触发工作表 ID）",
              "fields": [仅业务相关的1~3个字段]
            }},
            {{
              "name": "跨表新增记录",
              "type": "add_record",
              "target_worksheet_id": "（其他工作表 ID，必须与上面不同）",
              "fields": [目标表所有可操作字段，引用触发值用 {{{{trigger.<十六进制field_id>}}}}]
            }}
          ]
        }},
        {{
          "name": "业务动作名2",
          "confirm_msg": "确认提示2",
          "sure_name": "确认",
          "cancel_name": "取消",
          "action_nodes": [...]
        }},
        {{
          "name": "业务动作名3",
          "confirm_msg": "确认提示3",
          "sure_name": "确认",
          "cancel_name": "取消",
          "action_nodes": [...]
        }}
      ],
      "worksheet_events": [
        {{
          "name": "新增时同步数据（示例名，需改为实际业务名）",
          "trigger_id": "1",
          "action_nodes": [
            {{
              "name": "更新本表",
              "type": "update_record",
              "target_worksheet_id": "（触发工作表 ID）",
              "fields": [仅业务相关的1~3个字段]
            }},
            {{
              "name": "跨表新增",
              "type": "add_record",
              "target_worksheet_id": "（其他工作表 ID）",
              "fields": [目标表所有可操作字段，引用 {{{{trigger.<十六进制field_id>}}}}]
            }}
          ]
        }},
        {{
          "name": "状态变更联动（示例名，需改为实际业务名）",
          "trigger_id": "4",
          "action_nodes": [...]
        }}
      ]
    }}
  ],
  "time_triggers": [
    {{
      "name": "定时任务名1（如：每日生成汇总记录）",
      "execute_time": "{ex_time}",
      "execute_end_time": "{ex_end}",
      "repeat_type": "1",
      "interval": 1,
      "frequency": 1,
      "week_days": [],
      "action_nodes": [
        {{
          "name": "新增汇总记录",
          "type": "add_record",
          "target_worksheet_id": "（某工作表 ID）",
          "fields": [目标表所有可操作字段，静态值，禁止用 trigger 引用]
        }}
      ]
    }},
    {{
      "name": "定时任务名2（如：每周检查库存）",
      "execute_time": "{ex_time}",
      "execute_end_time": "{ex_end}",
      "repeat_type": "1",
      "interval": 1,
      "frequency": 7,
      "week_days": [],
      "action_nodes": [...]
    }}
  ]
}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 强制规则：
1. 所有 worksheet_id 和 field_id 必须来自上方应用结构，不能编造
2. 单选/下拉字段（type=9/10/11）的 fieldValue 必须是选项 key（UUID），不能用显示名称
3. 每个工作流必须有 2~3 个 action_nodes，且至少一个节点跨表（target 与触发表不同）
4. add_record 的 fields 必须包含目标工作表的【全部可操作字段】；update_record 只填业务相关的 1~3 个字段
5. 被选中工作表的 custom_actions 精确 {ca_per_ws} 个，每个工作表的 worksheet_events 精确 {ev_per_ws} 个
6. 全应用 time_triggers 精确 {num_tt} 个（不是每个工作表各 {num_tt} 个，是整体共 {num_tt} 个）
7. time_triggers 的 fields 中禁止使用 {{{{trigger.xxx}}}} 语法
10. {{{{trigger.xxx}}}} 中的 xxx 必须是十六进制 field_id（如 69aead6f2c5497945dc602ac），绝对禁止使用中文字段名
8. 需要为全部工作表生成，不能遗漏任何一个
9. worksheet_events 的 trigger_id 只能是 "1"/"2"/"4"/"3"，必须与业务语义匹配（参见上方 trigger_id 说明），禁止在"更新/变更"业务场景使用 trigger_id="3"（那是删除触发）

当前工作表列表：{ws_list}"""


# ── Gemini 调用 ────────────────────────────────────────────────────────────────

_THINKING_BUDGETS: dict[str, int] = {
    "low": 1024,
    "medium": 8192,
    "high": 24576,
}

_MAX_JSON_RETRIES = 2  # JSON 解析失败时最多重试 Gemini 调用的次数


def _call_ai_once(prompt: str, ai_config: dict, thinking: str) -> str:
    """发起一次 AI API 调用，返回原始文本。"""
    budget = None if thinking == "none" else _THINKING_BUDGETS.get(thinking, 8192)
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]
    provider = ai_config.get("provider", "gemini")
    print(f"[ai] 正在生成工作流规划（provider={provider}，model={model_name}，thinking={thinking}）...", file=sys.stderr)
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


def call_ai(prompt: str, ai_config: dict, thinking: str = "none") -> dict:
    """
    调用 AI API 生成工作流规划 JSON。
    JSON 解析失败时自动重试（最多 _MAX_JSON_RETRIES 次）。
    """
    last_exc: Exception = RuntimeError("未知错误")
    for attempt in range(1, _MAX_JSON_RETRIES + 2):  # 1 次正常 + 最多 _MAX_JSON_RETRIES 次重试
        try:
            raw = _call_ai_once(prompt, ai_config, thinking)
            print(f"[ai] 响应长度 {len(raw)} 字符", file=sys.stderr)
            # 使用 ai_utils 中更健壮的 parse_ai_json
            from ai_utils import parse_ai_json
            return parse_ai_json(raw)
        except (ValueError, Exception) as exc:
            last_exc = exc
            if attempt <= _MAX_JSON_RETRIES:
                wait = attempt * 5
                print(
                    f"[ai] JSON 解析失败（第 {attempt} 次），{wait}s 后重试：{exc}",
                    file=sys.stderr,
                )
                time.sleep(wait)
            else:
                break
    raise last_exc


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    started_at  = time.time()
    args        = parse_args()
    script_name = Path(__file__).stem
    log_args    = {k: v for k, v in vars(args).items() if k not in ("gemini_key",)}

    # 1. 读取 appKey + sign
    print(f"\n[step 1/3] 读取应用授权（relation_id={args.relation_id}）", file=sys.stderr)
    try:
        _, app_key, sign = load_app_auth(args.relation_id, args.app_auth_json)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 2

    # 2. 拉取应用结构
    try:
        app_structure = fetch_app_structure(args.relation_id, app_key, sign)
    except Exception as exc:
        print(f"Error: 拉取应用结构失败：{exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 1

    ws_count = len(app_structure.get("worksheets", []))
    if ws_count == 0:
        msg = "未获取到任何工作表，请检查 appKey/sign 是否有效。"
        print(f"Warning: {msg}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=msg, started_at=started_at)
        return 1
    print(f"[step 1/3] ✓ 应用：{app_structure['app_name']}，共 {ws_count} 个工作表", file=sys.stderr)

    # 3. 获取 AI 配置
    try:
        # 主规划使用 fast 档位，reasoning 对结构化 JSON 输出性价比低且速度慢
        ai_config = load_ai_config(tier="fast")
    except Exception as exc:
        print(f"Error: 获取 AI 配置失败：{exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 2

    # 4. 业务关系预分析（可选）
    relationships: dict = {}
    if not args.skip_analysis:
        print(f"\n[step 2/4] 业务关系预分析（--skip-analysis 可跳过）...", file=sys.stderr)
        relationships = analyze_relationships(app_structure, ai_config)
    else:
        print(f"\n[step 2/4] 跳过业务关系预分析（--skip-analysis）", file=sys.stderr)

    # 5. 主规划：调用 AI
    model_name = ai_config["model"]
    print(f"\n[step 3/4] 调用 AI 生成工作流规划（model={model_name}，thinking={args.thinking}）...", file=sys.stderr)
    try:
        ai_result = call_ai(
            build_prompt(app_structure, relationships), ai_config, args.thinking
        )
    except Exception as exc:
        print(f"Error: AI 调用失败：{exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 1

    planned_ws      = ai_result.get("worksheets", [])
    planned_tt      = ai_result.get("time_triggers", [])

    # 后处理：修正 AI 可能生成的 {{trigger.字段名}} 为 {{trigger.field_id}}
    fix_count = _fix_trigger_references(ai_result, app_structure)
    if fix_count:
        print(f"[fix] 修正了 {fix_count} 个 trigger 引用（字段名→字段ID）", file=sys.stderr)

    total_ca = sum(len(ws.get("custom_actions") or []) for ws in planned_ws)
    total_ev = sum(len(ws.get("worksheet_events") or []) for ws in planned_ws)
    total_estimated = total_ca + total_ev + len(planned_tt)
    print(
        f"[step 3/4] ✓ 规划完成：{len(planned_ws)} 个工作表"
        f"  自定义动作 {total_ca} 个，事件触发 {total_ev} 个，全局时间触发 {len(planned_tt)} 个"
        f"，共 {total_estimated} 个工作流",
        file=sys.stderr,
    )

    # 6. 组装计划
    plan: dict = {
        "app_id":            args.relation_id,
        "app_name":          app_structure.get("app_name", ""),
        "generated_at":      datetime.now().isoformat(timespec="seconds"),
        "model":             model_name,
        "thinking":          args.thinking,
        "skip_analysis":     args.skip_analysis,
        "relationships":     relationships,
        "worksheets":        planned_ws,
        "time_triggers":     planned_tt,
    }

    # 7. 写出
    print(f"\n[step 4/4] 写入规划文件...", file=sys.stderr)
    if args.output:
        out = Path(args.output).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[output] {out}", file=sys.stderr)

    persist(script_name, plan, args=log_args, started_at=started_at)

    print("\n" + "=" * 60, file=sys.stderr)
    print("✅ 工作流规划生成完成！", file=sys.stderr)
    print(f"   应用：{plan['app_name']}", file=sys.stderr)
    print(f"   工作表 {len(planned_ws)} 个：自定义动作 {total_ca}，事件触发 {total_ev}", file=sys.stderr)
    print(f"   全局时间触发 {len(planned_tt)} 个", file=sys.stderr)
    print(f"   规划文件：output/{script_name}_latest.json", file=sys.stderr)
    print(f"\n   下一步执行：python3 scripts/execute_workflow_plan.py --publish", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
