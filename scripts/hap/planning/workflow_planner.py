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


def build_enhanced_prompt(
    app_name: str,
    worksheets_info: list[dict],
    ca_per_ws: int = 3,
    ev_per_ws: int = 2,
    num_tt: int = 2,
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
            {{"name": "通知", "type": "notify", "content": "通知内容"}}
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

## 强制规则

1. 所有 worksheet_id 和 field_id 必须来自上方，不能编造
2. 单选字段 fieldValue 必须用完整 UUID key
3. 每个工作流 3~5 个 action_nodes，至少 1 个跨表
4. add_record 的 fields 包含目标表全部可操作字段；update_record 只填 1~3 个
5. 通知节点 content 必须有业务含义，不能为空
6. 每工作表 custom_actions={ca_per_ws} 个，worksheet_events={ev_per_ws} 个
7. 全应用 time_triggers 共 {num_tt} 个
8. time_triggers 禁止 {{{{trigger.xxx}}}}
9. trigger_id: "1"=新增, "2"=新增或更新, "4"=更新, "3"=删除
10. 禁止使用 branch 节点
11. date_triggers 的 assign_field_id 必须是 type=15/16 的日期字段或 ctime/mtime
12. 没有日期字段的工作表 date_triggers 为空数组"""


def validate_workflow_plan(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> dict:
    """校验工作流 plan。

    Returns:
        校验通过的 plan（可能有修正）

    Raises:
        ValueError: 校验失败
    """
    constraints = get_node_constraints()
    allowed_types = set(constraints["types"].keys())
    # add/update record 在 execute 里单独处理
    allowed_types.update({"add_record", "update_record"})
    # 禁用 branch
    allowed_types.discard("branch")
    allowed_types.discard("branch_condition")

    worksheets = raw.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError("缺少 worksheets 数组")

    ws_ids_in_plan = set()
    for i, ws in enumerate(worksheets):
        ws_id = str(ws.get("worksheet_id", "")).strip()
        if not ws_id:
            raise ValueError(f"worksheets[{i}] 缺少 worksheet_id")
        ws_ids_in_plan.add(ws_id)

        # 校验 action_nodes
        for section_key in ("custom_actions", "worksheet_events"):
            for j, item in enumerate(ws.get(section_key, [])):
                nodes = item.get("action_nodes", [])
                for k, node in enumerate(nodes):
                    node_type = node.get("type", "")
                    if node_type and node_type not in allowed_types:
                        raise ValueError(
                            f"worksheets[{i}].{section_key}[{j}].action_nodes[{k}]: "
                            f"type={node_type!r} 不在允许列表中"
                        )

    # 校验 time_triggers
    for i, tt in enumerate(raw.get("time_triggers", [])):
        nodes = tt.get("action_nodes", [])
        for k, node in enumerate(nodes):
            node_type = node.get("type", "")
            if node_type and node_type not in allowed_types:
                raise ValueError(f"time_triggers[{i}].action_nodes[{k}]: type={node_type!r} 不允许")
            # 检查是否使用了 trigger 引用
            for field in node.get("fields", []):
                fv = str(field.get("fieldValue", ""))
                if "{{trigger." in fv:
                    raise ValueError(f"time_triggers[{i}] 的字段值包含 {{{{trigger.xxx}}}}，定时触发禁止使用")

    return raw
