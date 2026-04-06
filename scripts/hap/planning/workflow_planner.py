"""
工作流规划器 — 利用 nodes/ 注册中心，生成高质量工作流 plan。

功能:
  1. 从 NODE_REGISTRY 读取已验证节点类型，只推荐可靠的节点
  2. 生成带约束的 AI prompt（禁用 branch，强制 sendContent 等）
  3. 校验 AI 输出（节点类型合法性、字段引用、跨表检查）

与现有 pipeline_workflows.py 的区别:
  - 节点类型说明从注册中心自动生成（非手写 prompt）
  - 校验增加跨表引用检查
  - 输出的 node plan 可直接对接 execute_workflow_plan.py

节点完整参数文档：
  scripts/hap/planning/workflow_node_schema.py — WORKFLOW_NODE_SCHEMA
  - 包含所有节点类型的 typeId、actionId、saveNode 参数格式
  - 包含 API 实测观测到的真实字段格式
  - 包含验证状态（已验证/创建成功/待验证）
"""

from __future__ import annotations

import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]
_WF_BASE = Path(__file__).resolve().parents[3] / "workflow"
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))
if str(_WF_BASE) not in sys.path:
    sys.path.insert(0, str(_WF_BASE))

from planning.constraints import (
    build_node_type_prompt_section,
    get_node_constraints,
    classify_fields,
)
# 完整节点 Schema（参数格式文档）
try:
    from planning.workflow_node_schema import (
        WORKFLOW_NODE_SCHEMA,
        AI_PLANNING_NODE_TYPES,
        FIELD_VALUE_FORMATS,
        NODE_TYPE_MAP,
    )
    _SCHEMA_AVAILABLE = True
except ImportError:
    _SCHEMA_AVAILABLE = False


# ─── 允许节点工具函数 ─────────────────────────────────────────────────────────────


def _get_allowed_types() -> set[str]:
    """从 NODE_REGISTRY 读取 allowed=True 的节点类型集合。
    update_record / add_record 不在注册中心，始终允许。
    """
    constraints = get_node_constraints()
    allowed = {nt for nt, s in constraints["types"].items() if s.get("allowed")}
    allowed.update({"add_record", "update_record"})
    return allowed


def _filter_action_nodes(nodes: list, allowed_types: set[str]) -> tuple[list, list]:
    """从 action_nodes 里过滤掉禁用节点。
    返回 (保留节点列表, 被过滤节点类型列表)。
    """
    kept, dropped = [], []
    for node in nodes:
        node_type = node.get("type", "")
        if node_type and node_type not in allowed_types:
            dropped.append(node_type)
        else:
            kept.append(node)
    return kept, dropped


# ─── Phase 1: 结构规划（轻量 prompt，只决定工作流骨架）─────────────────────────


def build_structure_prompt(
    app_name: str,
    worksheets_info: list[dict],
    ca_per_ws: int = 2,
    ev_per_ws: int = 1,
    num_tt: int = 1,
) -> str:
    """Phase 1 — 只规划工作流骨架：触发器、节点类型序列、名称。

    不要求 AI 填写字段值、saveNode 参数等细节。
    输出的 plan 将传给 build_node_config_prompt() 进行第二阶段细化。
    """
    node_type_section = build_node_type_prompt_section()

    ws_lines = []
    for ws in worksheets_info:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        classified = classify_fields(fields)

        ws_lines.append(f"\n工作表「{ws_name}」(ID: {ws_id})")
        # 只列出字段摘要（不含 option UUID），减轻 prompt 压力
        for cat_name, cat_label in [
            ("text", "文本"), ("number", "数值"), ("date", "日期"),
            ("select", "单选/下拉"), ("user", "成员"), ("relation", "关联"),
        ]:
            cat_fields = classified.get(cat_name, [])
            if cat_fields:
                fids = ", ".join(f"{f['id']}({f['name']})" for f in cat_fields[:8])
                ws_lines.append(f"  [{cat_label}] {fids}")

    ws_detail = "\n".join(ws_lines)

    return f"""你是一名企业应用自动化专家，正在为「{app_name}」规划工作流骨架。

{node_type_section}

## 应用工作表结构（摘要）
{ws_detail}

## 任务

为每个工作表规划工作流骨架。只需决定：
- 工作流名称、触发类型
- 节点序列（每个节点的类型和名称）
- 不需要填写字段值或详细配置

## 输出 JSON 格式（严格 JSON，无注释）

{{
  "worksheets": [
    {{
      "worksheet_id": "来自上方",
      "worksheet_name": "工作表名称",
      "custom_actions": [
        {{
          "name": "业务动作名",
          "confirm_msg": "确认提示",
          "sure_name": "确认",
          "cancel_name": "取消",
          "action_nodes": [
            {{"name": "节点名", "type": "update_record|add_record|notify|copy|delay_duration|calc|aggregate", "target_worksheet_id": "跨表时填目标工作表ID，操作本表则填本表ID"}}
          ]
        }}
      ],
      "worksheet_events": [
        {{
          "name": "事件名",
          "trigger_id": "1|2|3|4",
          "action_nodes": [
            {{"name": "节点名", "type": "节点类型", "target_worksheet_id": "..."}}
          ]
        }}
      ],
      "date_triggers": [
        {{
          "name": "日期触发名",
          "assign_field_id": "日期字段ID或ctime/mtime",
          "execute_time_type": 1,
          "number": 1, "unit": 3,
          "end_time": "09:00",
          "frequency": 0
        }}
      ]
    }}
  ],
  "time_triggers": [
    {{
      "name": "定时任务名",
      "execute_time": "08:00",
      "execute_end_time": "23:00",
      "repeat_type": "1",
      "interval": 1, "frequency": 7,
      "week_days": [],
      "action_nodes": [
        {{"name": "节点名", "type": "节点类型", "target_worksheet_id": "..."}}
      ]
    }}
  ]
}}

## 规则

1. 所有 worksheet_id 必须来自上方，不能编造
2. action_nodes 只填 name + type + target_worksheet_id，不填 fields/content
3. 每个工作流 3~5 个节点，至少 1 个跨表
4. 每工作表 custom_actions={ca_per_ws} 个，worksheet_events={ev_per_ws} 个
5. 全应用 time_triggers 共 {num_tt} 个
6. 禁止使用 branch 节点
7. date_triggers 的 assign_field_id 必须是 type=15/16 的日期字段或 ctime/mtime
8. 没有日期字段的工作表 date_triggers 为空数组
9. trigger_id: "1"=仅新增, "2"=新增或更新, "4"=仅更新, "3"=删除"""


def validate_structure_plan(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> dict:
    """Phase 1 校验 — 过滤禁用节点，空 action_nodes 的工作流从 plan 里移除。"""
    allowed_types = _get_allowed_types()

    worksheets = raw.get("worksheets", [])
    if not isinstance(worksheets, list):
        raise ValueError("缺少 worksheets 数组")

    for ws in worksheets:
        ws_id = str(ws.get("worksheet_id", "")).strip()
        if not ws_id:
            raise ValueError("worksheet 缺少 worksheet_id")

        for section_key in ("custom_actions", "worksheet_events"):
            kept_items = []
            for item in ws.get(section_key, []):
                nodes, dropped = _filter_action_nodes(
                    item.get("action_nodes", []), allowed_types
                )
                for t in dropped:
                    print(f"[plan-filter] {section_key} '{item.get('name','')}': 节点 {t!r} 不在允许列表，已过滤", file=sys.stderr)
                if nodes:
                    item["action_nodes"] = nodes
                    kept_items.append(item)
                else:
                    print(f"[plan-filter] {section_key} '{item.get('name','')}': 过滤后无有效节点，跳过整个工作流", file=sys.stderr)
            ws[section_key] = kept_items

    kept_tt = []
    for tt in raw.get("time_triggers", []):
        nodes, dropped = _filter_action_nodes(
            tt.get("action_nodes", []), allowed_types
        )
        for t in dropped:
            print(f"[plan-filter] time_trigger '{tt.get('name','')}': 节点 {t!r} 不在允许列表，已过滤", file=sys.stderr)
        if nodes:
            tt["action_nodes"] = nodes
            kept_tt.append(tt)
        else:
            print(f"[plan-filter] time_trigger '{tt.get('name','')}': 过滤后无有效节点，跳过", file=sys.stderr)
    raw["time_triggers"] = kept_tt

    return raw


# ─── Phase 2: 节点配置规划（给定骨架 + 完整字段，输出 saveNode 参数）──────────


def build_node_config_prompt(
    app_name: str,
    structure_plan: dict,
    worksheets_info: list[dict],
) -> str:
    """Phase 2 — 给定 Phase 1 的骨架 plan + 完整字段详情（含 option UUID keys），
    为每个节点输出具体的 fields/sendContent 等配置。

    Args:
        app_name: 应用名称
        structure_plan: Phase 1 输出的结构 plan
        worksheets_info: 完整字段列表（含 options 的完整 UUID key）
    """
    import json as _json

    # 构建完整字段参考（含 option UUID keys）
    ws_lines = []
    for ws in worksheets_info:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        classified = classify_fields(fields)

        ws_lines.append(f"\n### 工作表「{ws_name}」(ID: {ws_id})")
        for cat_name, cat_label in [
            ("text", "文本"), ("number", "数值"), ("date", "日期"),
            ("select", "单选/下拉"), ("user", "成员"), ("relation", "关联"),
        ]:
            cat_fields = classified.get(cat_name, [])
            if cat_fields:
                for f in cat_fields:
                    opts = ""
                    if f.get("options"):
                        opts = "  选项: " + ", ".join(
                            f'key="{o["key"]}" value="{o["value"]}"'
                            for o in f["options"][:8]
                        )
                    ws_lines.append(f"  field_id={f['id']}  type={f['type']}  {f['name']}{opts}")

    ws_detail = "\n".join(ws_lines)

    # 序列化结构 plan（精简版，方便 AI 参考）
    structure_summary_parts = []
    for ws in structure_plan.get("worksheets", []):
        ws_id = ws.get("worksheet_id", "")
        ws_name = ws.get("worksheet_name", "")
        structure_summary_parts.append(f"\n## 工作表「{ws_name}」(ID: {ws_id})")
        for section_key, section_label in [
            ("custom_actions", "自定义动作"),
            ("worksheet_events", "工作表事件"),
        ]:
            for item in ws.get(section_key, []):
                structure_summary_parts.append(f"  [{section_label}] {item.get('name', '')}")
                for node in item.get("action_nodes", []):
                    target = node.get("target_worksheet_id", "")
                    structure_summary_parts.append(
                        f"    → {node.get('type', '')} \"{node.get('name', '')}\" target={target}"
                    )
        for dt in ws.get("date_triggers", []):
            structure_summary_parts.append(f"  [日期触发] {dt.get('name', '')}")
            for node in dt.get("action_nodes", []):
                structure_summary_parts.append(
                    f"    → {node.get('type', '')} \"{node.get('name', '')}\""
                )

    for tt in structure_plan.get("time_triggers", []):
        structure_summary_parts.append(f"\n## 定时触发「{tt.get('name', '')}」")
        for node in tt.get("action_nodes", []):
            structure_summary_parts.append(
                f"  → {node.get('type', '')} \"{node.get('name', '')}\""
            )

    structure_summary = "\n".join(structure_summary_parts)

    return f"""你是一名工作流配置专家，正在为「{app_name}」的工作流节点填写具体配置。

## 已规划的工作流骨架
{structure_summary}

## 完整字段参考（含选项 UUID key）
{ws_detail}

## 任务

为骨架中的每个 action_node 补充具体配置：
- update_record / add_record：填写 fields 数组
- notify / copy：填写 sendContent
- delay_duration：填写延时参数
- calc / aggregate：填写公式参数

## 关键规则

1. 单选字段(type=9/11) 的 fieldValue 必须使用上方完整 UUID key，禁止截断或编造
2. 动态引用触发记录字段值用 {{{{trigger.FIELD_ID}}}}
3. add_record 的 fields 应包含目标表全部可操作字段
4. update_record 只填 1~3 个需要更新的字段
5. notify/copy 的内容字段名是 sendContent（不是 content）
6. sendContent 必须有业务含义
7. time_triggers 的节点字段值禁止 {{{{trigger.xxx}}}}

## 输出 JSON 格式

对每个工作流的每个节点，输出完整配置。结构与骨架相同，但 action_nodes 增加 fields/sendContent 等字段：

{{
  "worksheets": [
    {{
      "worksheet_id": "...",
      "worksheet_name": "...",
      "custom_actions": [
        {{
          "name": "...",
          "confirm_msg": "...",
          "sure_name": "确认",
          "cancel_name": "取消",
          "action_nodes": [
            {{
              "name": "节点名",
              "type": "update_record",
              "target_worksheet_id": "...",
              "fields": [
                {{"fieldId": "字段ID", "type": 字段type数字, "fieldValue": "值或{{{{trigger.xxx}}}}"}}
              ]
            }},
            {{
              "name": "通知",
              "type": "notify",
              "sendContent": "通知内容，可包含动态值"
            }}
          ]
        }}
      ],
      "worksheet_events": [...],
      "date_triggers": [...]
    }}
  ],
  "time_triggers": [...]
}}"""


def validate_node_config(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> dict:
    """Phase 2 校验 — 检查字段值、sendContent 等配置细节。"""
    worksheets = raw.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError("缺少 worksheets 数组")

    for i, ws in enumerate(worksheets):
        ws_id = str(ws.get("worksheet_id", "")).strip()
        if not ws_id:
            raise ValueError(f"worksheets[{i}] 缺少 worksheet_id")

        for section_key in ("custom_actions", "worksheet_events"):
            for j, item in enumerate(ws.get(section_key, [])):
                nodes = item.get("action_nodes", [])
                for k, node in enumerate(nodes):
                    node_type = node.get("type", "")
                    _validate_single_node_config(
                        node, node_type, worksheets_by_id,
                        f"worksheets[{i}].{section_key}[{j}].action_nodes[{k}]"
                    )

    for i, tt in enumerate(raw.get("time_triggers", [])):
        for k, node in enumerate(tt.get("action_nodes", [])):
            node_type = node.get("type", "")
            # 定时触发禁止 trigger 引用
            for field in node.get("fields", []):
                fv = str(field.get("fieldValue", ""))
                if "{{trigger." in fv or "$" in fv:
                    raise ValueError(
                        f"time_triggers[{i}].action_nodes[{k}] 的字段值包含触发引用，定时触发禁止使用"
                    )
            _validate_single_node_config(
                node, node_type, worksheets_by_id,
                f"time_triggers[{i}].action_nodes[{k}]"
            )

    return raw


def _validate_single_node_config(
    node: dict,
    node_type: str,
    worksheets_by_id: dict[str, dict],
    path: str,
) -> None:
    """校验单个节点的配置完整性。"""
    if node_type in ("add_record", "update_record"):
        fields = node.get("fields", [])
        if not isinstance(fields, list):
            raise ValueError(f"{path}: fields 不是数组")
        if node_type == "add_record" and len(fields) < 2:
            raise ValueError(f"{path}: add_record 至少需要 2 个字段")
        if node_type == "update_record" and len(fields) < 1:
            raise ValueError(f"{path}: update_record 至少需要 1 个字段")

        target_ws_id = str(node.get("target_worksheet_id", "")).strip()
        if target_ws_id and target_ws_id in worksheets_by_id:
            ws_info = worksheets_by_id[target_ws_id]
            valid_fids = {
                str(f.get("id", "") or f.get("controlId", "")).strip()
                for f in ws_info.get("fields", [])
                if str(f.get("id", "") or f.get("controlId", "")).strip()
            }
            for fi, field in enumerate(fields):
                fid = str(field.get("fieldId", "")).strip()
                if fid and fid not in valid_fids:
                    raise ValueError(f"{path}.fields[{fi}]: fieldId={fid!r} 不在目标工作表字段中")

    elif node_type in ("notify", "copy"):
        content = node.get("sendContent", "")
        if not content or not str(content).strip():
            raise ValueError(f"{path}: {node_type} 节点缺少 sendContent")


# ─── Phase 2 逐表: 节点配置规划（单工作表粒度）──────────────────────────────────


def build_node_config_prompt_per_ws(
    app_name: str,
    ws_structure: dict,
    ws_info: dict,
    related_ws_infos: list[dict],
) -> str:
    """Phase 2 逐表版 — 只为单个工作表的工作流节点填写具体配置。

    与 build_node_config_prompt() 功能相同，但每次只处理一个工作表，
    大幅缩短 prompt 长度，提高 AI 输出质量。

    Args:
        app_name: 应用名称
        ws_structure: Phase1 输出中该工作表的部分，包含：
            worksheet_id, worksheet_name, custom_actions, worksheet_events, date_triggers
        ws_info: 该表的完整字段信息
            {worksheetId, worksheetName, fields: [{id, name, type, options}]}
        related_ws_infos: 被引用的关联表信息（只含该工作表引用到的 target_worksheet_id 对应的表）
            [{worksheetId, worksheetName, fields: [{id, name, type, options}]}]
    """
    ws_id = ws_info.get("worksheetId", "")
    ws_name = ws_info.get("worksheetName", "")
    fields = ws_info.get("fields", [])
    classified = classify_fields(fields)

    # 当前表完整字段（含 option UUID keys）
    field_lines = [f"### 当前工作表「{ws_name}」(ID: {ws_id})"]
    for cat_name, cat_label in [
        ("text", "文本"), ("number", "数值"), ("date", "日期"),
        ("select", "单选/下拉"), ("user", "成员"), ("relation", "关联"),
    ]:
        cat_fields = classified.get(cat_name, [])
        if cat_fields:
            for f in cat_fields:
                opts = ""
                if f.get("options"):
                    opts = "  选项: " + ", ".join(
                        f'key="{o["key"]}" value="{o["value"]}"'
                        for o in f["options"][:8]
                    )
                field_lines.append(f"  field_id={f['id']}  type={f['type']}  {f['name']}{opts}")

    # 关联表字段摘要（跨表节点需要）
    for rws in related_ws_infos:
        rws_id = rws.get("worksheetId", "")
        rws_name = rws.get("worksheetName", "")
        rws_fields = rws.get("fields", [])
        rws_classified = classify_fields(rws_fields)

        field_lines.append(f"\n### 关联工作表「{rws_name}」(ID: {rws_id})")
        for cat_name, cat_label in [
            ("text", "文本"), ("number", "数值"), ("date", "日期"),
            ("select", "单选/下拉"), ("user", "成员"), ("relation", "关联"),
        ]:
            cat_fields = rws_classified.get(cat_name, [])
            if cat_fields:
                for f in cat_fields:
                    opts = ""
                    if f.get("options"):
                        opts = "  选项: " + ", ".join(
                            f'key="{o["key"]}" value="{o["value"]}"'
                            for o in f["options"][:8]
                        )
                    field_lines.append(f"  field_id={f['id']}  type={f['type']}  {f['name']}{opts}")

    ws_detail = "\n".join(field_lines)

    # 骨架摘要（仅当前工作表的部分）
    structure_lines = []
    ws_struct_id = ws_structure.get("worksheet_id", ws_id)
    ws_struct_name = ws_structure.get("worksheet_name", ws_name)
    structure_lines.append(f"## 工作表「{ws_struct_name}」(ID: {ws_struct_id})")

    for section_key, section_label in [
        ("custom_actions", "自定义动作"),
        ("worksheet_events", "工作表事件"),
    ]:
        for item in ws_structure.get(section_key, []):
            structure_lines.append(f"  [{section_label}] {item.get('name', '')}")
            for node in item.get("action_nodes", []):
                target = node.get("target_worksheet_id", "")
                structure_lines.append(
                    f"    → {node.get('type', '')} \"{node.get('name', '')}\" target={target}"
                )

    for dt in ws_structure.get("date_triggers", []):
        structure_lines.append(f"  [日期触发] {dt.get('name', '')}")
        for node in dt.get("action_nodes", []):
            structure_lines.append(
                f"    → {node.get('type', '')} \"{node.get('name', '')}\""
            )

    structure_summary = "\n".join(structure_lines)

    return f"""你是一名工作流配置专家，正在为「{app_name}」的工作流节点填写具体配置。

## 已规划的工作流骨架（当前工作表）
{structure_summary}

## 完整字段参考（含选项 UUID key）
{ws_detail}

## 任务

为骨架中的每个 action_node 补充具体配置：
- update_record / add_record：填写 fields 数组
- notify / copy：填写 sendContent
- delay_duration：填写延时参数
- calc / aggregate：填写公式参数

## 关键规则

1. 单选字段(type=9/11) 的 fieldValue 必须使用上方完整 UUID key，禁止截断或编造
2. 动态引用触发记录字段值用 {{{{trigger.FIELD_ID}}}}
3. add_record 的 fields 应包含目标表全部可操作字段
4. update_record 只填 1~3 个需要更新的字段
5. notify/copy 的内容字段名是 sendContent（不是 content）
6. sendContent 必须有业务含义

## 输出 JSON 格式

只输出当前工作表的工作流配置，结构与骨架相同，但 action_nodes 增加 fields/sendContent 等字段：

{{
  "worksheet_id": "{ws_struct_id}",
  "worksheet_name": "{ws_struct_name}",
  "custom_actions": [
    {{
      "name": "...",
      "confirm_msg": "...",
      "sure_name": "确认",
      "cancel_name": "取消",
      "action_nodes": [
        {{
          "name": "节点名",
          "type": "update_record",
          "target_worksheet_id": "...",
          "fields": [
            {{"fieldId": "字段ID", "type": 字段type数字, "fieldValue": "值或{{{{trigger.xxx}}}}"}}
          ]
        }},
        {{
          "name": "通知",
          "type": "notify",
          "sendContent": "通知内容，可包含动态值"
        }}
      ]
    }}
  ],
  "worksheet_events": [...],
  "date_triggers": [...]
}}"""


def validate_node_config_per_ws(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> dict:
    """Phase 2 逐表校验 — 检查单个工作表的节点配置。

    与 validate_node_config() 逻辑一致，但输入是单个工作表的配置（无外层 worksheets 数组）。

    Args:
        raw: AI 输出的单个工作表 JSON，包含 worksheet_id, custom_actions, worksheet_events, date_triggers
        worksheets_by_id: {worksheetId: {fields: [...]}} 全部工作表信息（用于跨表字段校验）

    Returns:
        校验通过的 raw dict

    Raises:
        ValueError: 校验失败
    """
    ws_id = str(raw.get("worksheet_id", "")).strip()
    if not ws_id:
        raise ValueError("缺少 worksheet_id")

    for section_key in ("custom_actions", "worksheet_events"):
        for j, item in enumerate(raw.get(section_key, [])):
            nodes = item.get("action_nodes", [])
            for k, node in enumerate(nodes):
                node_type = node.get("type", "")
                _validate_single_node_config(
                    node, node_type, worksheets_by_id,
                    f"{section_key}[{j}].action_nodes[{k}]"
                )

    for j, dt in enumerate(raw.get("date_triggers", [])):
        for k, node in enumerate(dt.get("action_nodes", [])):
            node_type = node.get("type", "")
            _validate_single_node_config(
                node, node_type, worksheets_by_id,
                f"date_triggers[{j}].action_nodes[{k}]"
            )

    return raw


# ─── 原有一体化接口（向后兼容）───────────────────────────────────────────────────


def build_enhanced_prompt(
    app_name: str,
    worksheets_info: list[dict],
    ca_per_ws: int = 2,
    ev_per_ws: int = 1,
    num_tt: int = 1,
) -> str:
    """生成增强版工作流规划 prompt。

    Args:
        app_name: 应用名称
        worksheets_info: [{worksheetId, worksheetName, fields: [{controlId, controlName, type, options}]}]
        ca_per_ws: 每个工作表的自定义动作数
        ev_per_ws: 每个工作表的事件触发数
        num_tt: 全局定时触发数
    """
    node_type_section = build_node_type_prompt_section()

    # 构建工作表描述
    ws_lines = []
    for ws in worksheets_info:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        classified = classify_fields(fields)

        ws_lines.append(f"\n工作表「{ws_name}」(ID: {ws_id})")
        for cat_name, cat_label in [
            ("text", "文本"), ("number", "数值"), ("date", "日期"),
            ("select", "单选/下拉"), ("user", "成员"), ("relation", "关联"),
        ]:
            cat_fields = classified.get(cat_name, [])
            if cat_fields:
                for f in cat_fields:
                    opts = ""
                    if f.get("options"):
                        opts = "  选项: " + ", ".join(
                            f'key="{o["key"]}" value="{o["value"]}"'
                            for o in f["options"][:6]
                        )
                    ws_lines.append(f"  field_id={f['id']}  type={f['type']}  {f['name']}{opts}")

    ws_detail = "\n".join(ws_lines)

    return f"""你是一名企业应用自动化专家，正在为「{app_name}」规划工作流。

{node_type_section}

## 应用工作表结构
{ws_detail}

## 任务

为每个工作表规划工作流，包括自定义动作按钮、工作表事件触发、日期字段触发。

## 输出 JSON 格式

{{
  "worksheets": [
    {{
      "worksheet_id": "来自上方",
      "worksheet_name": "工作表名称",
      "custom_actions": [
        {{
          "name": "业务动作名",
          "confirm_msg": "确认提示",
          "sure_name": "确认",
          "cancel_name": "取消",
          "action_nodes": [
            {{"name": "节点名", "type": "update_record", "target_worksheet_id": "...", "fields": [...]}},
            {{"name": "通知", "type": "notify", "sendContent": "通知内容，可包含动态值"}}
          ]
        }}
      ],
      "worksheet_events": [
        {{
          "name": "事件名",
          "trigger_id": "1",
          "action_nodes": [...]
        }}
      ],
      "date_triggers": [
        {{
          "name": "日期触发名",
          "assign_field_id": "日期字段ID或ctime/mtime",
          "execute_time_type": 1,
          "number": 1, "unit": 3,
          "end_time": "09:00",
          "frequency": 0
        }}
      ]
    }}
  ],
  "time_triggers": [
    {{
      "name": "定时任务名",
      "execute_time": "08:00",
      "execute_end_time": "23:00",
      "repeat_type": "1",
      "interval": 1, "frequency": 7,
      "week_days": [],
      "action_nodes": [...]
    }}
  ]
}}

## 业务场景示例（参考，不要照搬）

示例1: 员工档案表
  - worksheet_event(trigger_id="1"): "新员工入职自动创建考勤记录"
    → add_record(考勤记录表, 员工=trigger.员工字段ID)
    → notify(sendContent="新员工 XXX 已入职，请安排座位和设备")
  - custom_action: "标记离职"
    → update_record(在职状态=离职option_key)
    → notify(sendContent="员工 XXX 已标记为离职")

示例2: 合同管理表
  - date_trigger(到期日期): "合同到期提醒"
    → notify(sendContent="合同即将到期，请及时处理续签")
  - worksheet_event(trigger_id="1"): "新合同创建同步客户信息"
    → update_record(客户信息表, 最新合同=trigger.合同名称)

## 强制规则

1. 所有 worksheet_id 和 field_id 必须来自上方，不能编造
2. 单选字段(type=9/11) fieldValue 必须用完整 UUID key，不能截断
3. 每个工作流 3~5 个 action_nodes，至少 1 个跨表
4. add_record 的 fields 包含目标表全部可操作字段；update_record 只填 1~3 个
5. 通知节点的内容字段名是 sendContent（不是 content），必须有业务含义
6. 每工作表 custom_actions={ca_per_ws} 个，worksheet_events={ev_per_ws} 个
7. 全应用 time_triggers 共 {num_tt} 个
8. time_triggers 禁止 {{{{trigger.xxx}}}}
9. trigger_id: "1"=仅新增, "2"=新增或更新（默认）, "4"=仅更新, "3"=删除
10. 禁止使用 branch 节点
11. date_triggers 的 assign_field_id 必须是 type=15/16 的日期字段或 ctime/mtime
12. 没有日期字段的工作表 date_triggers 为空数组
13. 动态引用触发记录字段值用 {{{{trigger.FIELD_ID}}}}（执行时自动替换为 $startNodeId-fieldId$）
14. fieldValue 填写规则：
    - 文本字段: 直接填字符串值，或 {{{{trigger.字段ID}}}} 引用触发记录
    - 单选字段: 必须用完整 UUID option key（从上方选项列表中选取）
    - 数值字段: 填数字字符串如 "0" 或 {{{{trigger.字段ID}}}}
    - 日期字段: 填 ISO 格式或 {{{{trigger.字段ID}}}}
    - 成员字段: 填 "[]" 或 {{{{trigger.字段ID}}}}"""


def validate_workflow_plan(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> dict:
    """校验工作流 plan（一体化接口，向后兼容）。
    禁用节点被过滤，空工作流被移除。
    """
    allowed_types = _get_allowed_types()

    worksheets = raw.get("worksheets", [])
    if not isinstance(worksheets, list):
        raise ValueError("缺少 worksheets 数组")

    for ws in worksheets:
        ws_id = str(ws.get("worksheet_id", "")).strip()
        if not ws_id:
            raise ValueError("worksheet 缺少 worksheet_id")

        for section_key in ("custom_actions", "worksheet_events"):
            kept_items = []
            for item in ws.get(section_key, []):
                nodes, dropped = _filter_action_nodes(
                    item.get("action_nodes", []), allowed_types
                )
                for t in dropped:
                    print(f"[plan-filter] {section_key} '{item.get('name','')}': 节点 {t!r} 不在允许列表，已过滤", file=sys.stderr)
                if nodes:
                    item["action_nodes"] = nodes
                    # 保留原有 sendContent / fields 校验
                    for node in nodes:
                        node_type = node.get("type", "")
                        _validate_single_node_config(
                            node, node_type, worksheets_by_id,
                            f"{section_key}.{item.get('name','')}.{node.get('name','')}"
                        )
                    kept_items.append(item)
                else:
                    print(f"[plan-filter] {section_key} '{item.get('name','')}': 过滤后无有效节点，跳过", file=sys.stderr)
            ws[section_key] = kept_items

    kept_tt = []
    for tt in raw.get("time_triggers", []):
        nodes, dropped = _filter_action_nodes(
            tt.get("action_nodes", []), allowed_types
        )
        for t in dropped:
            print(f"[plan-filter] time_trigger '{tt.get('name','')}': 节点 {t!r} 不在允许列表，已过滤", file=sys.stderr)
        if nodes:
            # 定时触发禁止 trigger 引用
            for field in [f for n in nodes for f in n.get("fields", [])]:
                fv = str(field.get("fieldValue", ""))
                if "{{trigger." in fv or "$" in fv:
                    raise ValueError(f"time_trigger '{tt.get('name','')}' 的字段值包含触发引用，定时触发禁止使用")
            tt["action_nodes"] = nodes
            kept_tt.append(tt)
        else:
            print(f"[plan-filter] time_trigger '{tt.get('name','')}': 过滤后无有效节点，跳过", file=sys.stderr)
    raw["time_triggers"] = kept_tt

    return raw
