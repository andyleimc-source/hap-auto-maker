"""
视图规划器 — 利用 views/ 注册中心 + 字段分类，规划+配置视图。

两个能力合一：
  1. 规划：决定每个表应有哪些视图类型和名称
  2. 配置：为每种视图生成完整的 postCreateUpdates 配置

与现有 plan_worksheet_views_gemini.py 的区别:
  - 视图类型约束从注册中心自动生成
  - 根据字段分类智能推荐视图类型（有日期→日历/甘特图，有单选→看板）
  - 配置生成逻辑集中管理（二次保存参数）
"""

from __future__ import annotations

import sys
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from views.view_types import VIEW_REGISTRY, VIEW_TYPE_NAMES
from planning.constraints import classify_fields


def build_view_type_prompt_section() -> str:
    """生成 AI prompt 中的视图类型说明。"""
    lines = ["可用的视图类型（viewType）："]
    for vt, spec in sorted(VIEW_REGISTRY.items()):
        v = "✓" if spec.get("verified") else ""
        reqs = spec.get("requires_fields", [])
        req_str = f" [需要: {', '.join(reqs)}]" if reqs else ""
        lines.append(f"  {vt}. {spec['name']} {v}{req_str} — {spec['doc'][:60]}")
    return "\n".join(lines)


def suggest_views(classified_fields: dict[str, list[dict]], worksheet_id: str = "") -> list[dict]:
    """根据字段分类推荐适合的视图类型。"""
    suggestions = []

    # 有单选/下拉 → 看板 + 分组表格
    # 注意：type=36（检查框/布尔）只有两个值，不适合看板；type=28（等级）也不适合
    # 看板适合 type=9（单选平铺）、type=11（下拉单选）
    KANBAN_SUITABLE_TYPES = {9, 11}
    selects = [f for f in classified_fields.get("select", []) if f.get("type") in KANBAN_SUITABLE_TYPES]
    if selects:
        suggestions.append({
            "viewType": 1, "name": f"按{selects[0]['name']}看板",
            "reason": f"有单选字段「{selects[0]['name']}」，适合看板",
            "viewControl": selects[0]["id"],
        })
        suggestions.append({
            "viewType": 0, "name": f"按{selects[0]['name']}分组",
            "reason": "分组表格视图",
        })

    # 有日期 → 日历 + 甘特图
    dates = classified_fields.get("date", [])
    if len(dates) >= 2:
        suggestions.append({
            "viewType": 5, "name": "甘特图",
            "reason": f"有日期字段「{dates[0]['name']}」+「{dates[1]['name']}」",
            "begindate": dates[0]["id"],
            "enddate": dates[1]["id"],
        })
    if dates:
        suggestions.append({
            "viewType": 4, "name": "日历视图",
            "reason": f"有日期字段「{dates[0]['name']}」",
            "calendarcid": dates[0]["id"],
        })

    # 有自关联 → 层级视图
    relations = classified_fields.get("relation", [])
    for r in relations:
        if r.get("dataSource") == worksheet_id:
            suggestions.append({
                "viewType": 2, "name": "层级视图",
                "reason": f"有自关联字段「{r['name']}」",
                "layersControlId": r["id"],
            })
            break

    # 地图视图(viewType=8) — 必须有定位字段(type=40)，仅地区字段(type=24)不够
    # 2026-04-04 抓包确认：地图视图需要 type=40 定位字段作为 viewControl
    locations = classified_fields.get("location", [])
    location_40 = [f for f in locations if f.get("type") == 40]
    if location_40:
        suggestions.append({
            "viewType": 8, "name": "地图视图",
            "reason": f"有定位字段「{location_40[0]['name']}」",
            "latlng": location_40[0]["id"],
        })

    return suggestions


# ─── Phase 1: 结构规划（只决定视图类型+名称，不涉及配置细节）─────────────────


def build_structure_prompt(
    app_name: str,
    worksheets_data: list[dict],
) -> str:
    """Phase 1 — 只规划每个工作表的视图类型、名称和理由。

    不要求 AI 输出 advancedSetting、postCreateUpdates 等配置。
    """
    view_type_section = build_view_type_prompt_section()

    ws_sections = []
    for ws in worksheets_data:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        classified = classify_fields(fields)
        suggestions = suggest_views(classified, ws_id)

        lines = [f"\n### 工作表「{ws_name}」(ID: {ws_id})"]
        for cat, label in [("select", "单选/下拉"), ("date", "日期"),
                           ("text", "文本"), ("number", "数值"), ("relation", "关联")]:
            cat_fields = classified.get(cat, [])
            if cat_fields:
                fids = ", ".join(f"{f['id']}({f['name']})" for f in cat_fields[:5])
                lines.append(f"  [{label}] {fids}")

        if suggestions:
            lines.append("  推荐视图：")
            for sg in suggestions:
                lines.append(f"    - viewType={sg['viewType']} {sg['name']} ({sg['reason']})")

        ws_sections.append("\n".join(lines))

    count = len(worksheets_data)

    return f"""你是一名应用配置专家，正在为「{app_name}」的所有工作表规划视图。

{view_type_section}

## 工作表与字段
{"".join(ws_sections)}

## 任务

为每个工作表规划视图，只需决定视图类型、名称和理由。不需要配置细节。

规则：
1) viewType 必须是整数：0(表格/列表), 1(看板), 2(层级), 3(画廊), 4(日历), 5(甘特图)
   ⚠️ 系统已自动创建名为"全部"的默认列表视图，不要再规划 viewType=0 的"全部"视图。只规划其他类型或有明确分组/筛选用途的额外视图
2) ⚠️ 保守策略：绝大多数工作表只有 1 个列表视图（viewType=0）就够了。只有真正能大幅提升该表使用体验的情况下，才额外添加 1 个其他类型视图
3) 看板(1)：仅适合"状态流转"是核心使用场景的表（如任务/工单/审批流程）；必须有多状态单选字段(type=9 或 type=11)；检查框/等级字段不能用
4) 甘特图(5)：仅适合核心用途是"时间计划管理"的表（如项目/排产/合同）；必须有开始+结束两个日期字段
5) 日历(4)：仅适合核心用途是"以日期查看"的表（如排班/预约/日程）；需要日期字段
6) 层级(2)：仅适合有明确父子关系的表；需要自关联字段(type=29)
7) 画廊(3)：仅适合图片是核心内容的表；需要附件字段
8) 判断标准：先问"没有这个视图，用户用起来有明显不便吗？"——答案是"否"则只建列表视图

## 输出格式（严格 JSON，viewType 必须是整数）

{{
  "worksheets": [
    {{
      "worksheetId": "来自上方",
      "worksheetName": "名称",
      "views": [
        {{
          "name": "视图名",
          "viewType": 1,
          "reason": "业务理由",
          "viewControl": "看板时填单选字段ID，其他留空"
        }}
      ]
    }}
  ]
}}

worksheets 数组长度必须等于 {count}，不能遗漏。"""


def validate_structure_plan(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> dict:
    """Phase 1 校验 — 只检查视图类型和基本约束。"""
    worksheets = raw.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError("缺少 worksheets 数组")

    for i, ws in enumerate(worksheets):
        ws_id = str(ws.get("worksheetId", "")).strip()
        views = ws.get("views", [])
        if not isinstance(views, list):
            raise ValueError(f"worksheets[{i}] views 不是数组")

        for j, view in enumerate(views):
            vt_raw = view.get("viewType", "")
            try:
                vt_int = int(str(vt_raw).strip())
            except (ValueError, TypeError):
                raise ValueError(f"worksheets[{i}].views[{j}] viewType={vt_raw!r} 非法（非整数）")
            # 0 是合法的表格/列表视图，合法范围 0-8
            if vt_int not in VIEW_REGISTRY:
                raise ValueError(f"worksheets[{i}].views[{j}] viewType={vt_int} 非法（不在 VIEW_REGISTRY 中）")
            # 统一写回整数
            view["viewType"] = vt_int

    return raw


# ─── Phase 2: 视图配置规划（给定结构 + 真实 viewId，输出配置细节）───────────────


def build_config_prompt(
    app_name: str,
    structure_plan: dict,
    worksheets_data: list[dict],
) -> str:
    """Phase 2 — 给定 Phase 1 的视图结构 + 真实字段 ID，
    为每个视图生成 displayControls、advancedSetting、postCreateUpdates。

    Args:
        app_name: 应用名称
        structure_plan: Phase 1 输出（含视图类型、名称）
        worksheets_data: [{worksheetId, worksheetName, fields: [...]}]
    """
    # 构建字段参考
    ws_field_sections = []
    for ws in worksheets_data:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        classified = classify_fields(fields)

        lines = [f"\n### 工作表「{ws_name}」(ID: {ws_id})"]
        for cat, label in [("select", "单选/下拉"), ("date", "日期"),
                           ("text", "文本"), ("number", "数值"),
                           ("user", "成员"), ("relation", "关联"),
                           ("attachment", "附件")]:
            cat_fields = classified.get(cat, [])
            if cat_fields:
                for f in cat_fields:
                    lines.append(f"  {f['id']}  type={f['type']}  {f['name']}")
        ws_field_sections.append("\n".join(lines))

    field_detail = "\n".join(ws_field_sections)

    # 序列化已规划的视图结构
    plan_lines = []
    for ws in structure_plan.get("worksheets", []):
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        plan_lines.append(f"\n## 工作表「{ws_name}」(ID: {ws_id})")
        for view in ws.get("views", []):
            vc = view.get("viewControl", "")
            vc_str = f" viewControl={vc}" if vc else ""
            plan_lines.append(
                f"  - viewType={view.get('viewType', '')} \"{view.get('name', '')}\"{vc_str}"
            )

    plan_summary = "\n".join(plan_lines)

    return f"""你是一名视图配置专家，正在为「{app_name}」的视图填写具体配置。

## 已规划的视图结构
{plan_summary}

## 完整字段参考
{field_detail}

## 任务

为每个视图补充完整配置。根据视图类型填写：

- **所有视图**：displayControls（显示字段 ID 列表，选最重要的 5-8 个字段）
- **表格(0) 含"分组"/"分类"关键词的**：advancedSetting.groupView（需 viewId 占位，用 "{{viewId}}" 表示）
- **日历(4)**：postCreateUpdates 中设 calendarcids（开始/结束日期字段 ID）
- **甘特图(5)**：视图顶层设 begindate（开始日期字段 ID）和 enddate（结束日期字段 ID），同时在 postCreateUpdates 中通过 editAdKeys 二次保存
- **层级(2)**：视图顶层设 layersControlId（自关联字段 ID），postCreateUpdates 用 editAttrs=["viewControl","childType","viewType"]，viewControl 可设为 "create"（自动创建自关联字段）或具体字段 ID
- **资源(7)**：视图顶层设 viewControl（分组字段 ID）+ advancedSetting.begindate/enddate，postCreateUpdates 二次保存
- **地图(8)**：必须有定位字段(type=40)，视图顶层设 latlng（定位字段 ID），viewControl 指向定位字段

## 配置格式说明

groupView 格式（JSON 紧凑字符串）：
  '{{"viewId":"{{viewId}}","groupFilters":[{{"controlId":"<单选字段ID>","values":[],"dataType":<字段type>,"spliceType":1,"filterType":2,"dateRange":0,"minValue":"","maxValue":"","isGroup":true}}],"navShow":true}}'

calendarcids 格式（JSON 紧凑字符串）：
  '[{{"begin":"<日期字段ID>","end":"<结束日期字段ID或空>"}}]'

## 输出 JSON 格式

{{
  "worksheets": [
    {{
      "worksheetId": "...",
      "worksheetName": "...",
      "views": [
        {{
          "name": "视图名",
          "viewType": "0",
          "displayControls": ["字段ID1", "字段ID2"],
          "coverCid": "",
          "viewControl": "",
          "advancedSetting": {{}},
          "postCreateUpdates": [
            {{
              "editAttrs": ["advancedSetting"],
              "editAdKeys": ["calendarcids"],
              "advancedSetting": {{"calendarcids": "[...]"}}
            }}
          ]
        }}
      ]
    }}
  ]
}}"""


def validate_config_plan(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> dict:
    """Phase 2 校验 — 检查 displayControls、advancedSetting 的字段引用。"""
    worksheets = raw.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError("缺少 worksheets 数组")

    for i, ws in enumerate(worksheets):
        ws_id = str(ws.get("worksheetId", "")).strip()
        views = ws.get("views", [])
        if not isinstance(views, list):
            raise ValueError(f"worksheets[{i}] views 不是数组")

        ws_info = worksheets_by_id.get(ws_id)
        if not ws_info:
            continue

        field_ids = {
            str(f.get("id", "") or f.get("controlId", "")).strip()
            for f in ws_info.get("fields", [])
            if str(f.get("id", "") or f.get("controlId", "")).strip()
        }

        for j, view in enumerate(views):
            # 校验 displayControls
            dc = view.get("displayControls", [])
            if isinstance(dc, list):
                view["displayControls"] = [x for x in dc if str(x).strip() in field_ids]

            # 校验 viewControl
            vc = str(view.get("viewControl", "")).strip()
            if vc and vc not in field_ids:
                view["viewControl"] = ""

    return raw


# ─── 原有一体化接口（向后兼容）───────────────────────────────────────────────────


def build_enhanced_prompt(
    app_name: str,
    worksheets_data: list[dict],
) -> str:
    """生成增强版视图规划 prompt。

    Args:
        app_name: 应用名称
        worksheets_data: [{worksheetId, worksheetName, fields: [...]}]
    """
    view_type_section = build_view_type_prompt_section()

    ws_sections = []
    for ws in worksheets_data:
        ws_id = ws.get("worksheetId", "")
        ws_name = ws.get("worksheetName", "")
        fields = ws.get("fields", [])
        classified = classify_fields(fields)
        suggestions = suggest_views(classified, ws_id)

        lines = [f"\n### 工作表「{ws_name}」(ID: {ws_id})"]

        # 字段摘要
        for cat, label in [("select", "单选/下拉"), ("date", "日期"),
                           ("text", "文本"), ("number", "数值"), ("relation", "关联")]:
            cat_fields = classified.get(cat, [])
            if cat_fields:
                fids = ", ".join(f"{f['id']}({f['name']})" for f in cat_fields[:5])
                lines.append(f"  [{label}] {fids}")

        if suggestions:
            lines.append("  推荐视图：")
            for sg in suggestions:
                lines.append(f"    - viewType={sg['viewType']} {sg['name']} ({sg['reason']})")

        ws_sections.append("\n".join(lines))

    count = len(worksheets_data)

    return f"""你是一名应用配置专家，正在为「{app_name}」的所有工作表规划视图。

{view_type_section}

## 工作表与字段
{"".join(ws_sections)}

## 任务

为每个工作表规划 1-5 个视图，类型多样化，且每个视图有实际业务用途。

规则：
1) viewType 必须是整数：0(表格/列表), 1(看板), 2(层级), 3(画廊), 4(日历), 5(甘特图)
   ⚠️ 系统已自动创建名为"全部"的默认列表视图，不要再规划 viewType=0 的"全部"视图。只规划其他类型或有明确分组/筛选用途的额外视图
2) ⚠️ 保守策略：绝大多数工作表只有 1 个列表视图就够了。只有真正能大幅提升使用体验的情况才添加 1 个其他类型视图
3) displayControls 必须来自该工作表的字段 ID
4) 看板(1)：仅适合"状态流转"是核心使用场景的表（任务/工单/审批）；必须有多状态单选字段(type=9/11)；检查框/等级不能用
5) 甘特图(5)：仅适合核心用途是"时间计划管理"的表（项目/排产/合同）；必须有开始+结束两个日期字段
6) 日历(4)：仅适合核心用途是"以日期查看"的表（排班/预约/日程）；需要日期字段，在 postCreateUpdates 中设 calendarcids
7) 层级(2)：仅适合有明确父子关系的表；需要自关联字段(type=29)
8) 画廊(3)：仅适合图片是核心内容的表；需要附件字段
9) 表格(0) 名称含"分组"/"分类"时，在 advancedSetting 中设 groupView
10) 判断标准：先问"没有这个视图，用户用起来有明显不便吗？"——答案是"否"则只建列表视图

## 输出格式（严格 JSON，viewType 必须是整数）

{{
  "worksheets": [
    {{
      "worksheetId": "来自上方",
      "worksheetName": "名称",
      "views": [
        {{
          "name": "视图名",
          "viewType": 1,
          "reason": "业务理由",
          "displayControls": ["字段ID1", "字段ID2"],
          "coverCid": "",
          "viewControl": "",
          "advancedSetting": {{}},
          "postCreateUpdates": []
        }}
      ]
    }}
  ]
}}

worksheets 数组长度必须等于 {count}，不能遗漏。"""


def validate_view_plan(
    raw: dict,
    worksheets_by_id: dict[str, dict],
) -> dict:
    """校验视图 plan，检查字段引用和类型约束。"""
    worksheets = raw.get("worksheets", [])
    if not isinstance(worksheets, list) or not worksheets:
        raise ValueError("缺少 worksheets 数组")

    for i, ws in enumerate(worksheets):
        ws_id = str(ws.get("worksheetId", "")).strip()
        views = ws.get("views", [])
        if not isinstance(views, list):
            raise ValueError(f"worksheets[{i}] views 不是数组")

        ws_info = worksheets_by_id.get(ws_id)
        if not ws_info:
            continue

        field_ids = {
            str(f.get("id", "") or f.get("controlId", "")).strip()
            for f in ws_info.get("fields", [])
            if str(f.get("id", "") or f.get("controlId", "")).strip()
        }

        for j, view in enumerate(views):
            vt = str(view.get("viewType", "")).strip()
            if vt not in {str(k) for k in VIEW_REGISTRY}:
                raise ValueError(f"worksheets[{i}].views[{j}] viewType={vt} 非法")

            # 检查 displayControls 引用
            dc = view.get("displayControls", [])
            if isinstance(dc, list):
                view["displayControls"] = [x for x in dc if str(x).strip() in field_ids]

            # 检查 viewControl 引用
            vc = str(view.get("viewControl", "")).strip()
            if vc and vc not in field_ids:
                view["viewControl"] = ""

    return raw
