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
    suggestions = [
        {"viewType": 0, "name": "全部", "reason": "默认表格视图"},
    ]

    # 有单选/下拉 → 看板 + 分组表格
    selects = classified_fields.get("select", [])
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

    return suggestions


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
1) viewType 允许 0(表格), 1(看板), 2(层级), 3(画廊), 4(日历), 5(甘特图)
2) 每个工作表 1-5 个视图，实用不凑数
3) displayControls 必须来自该工作表的字段 ID
4) 看板(1) 必须设 viewControl 为单选字段(type=11)ID，无合适字段则不创建看板
5) 甘特图(5) 需要两个日期字段
6) 层级(2) 需要自关联字段(type=29, dataSource=本表)
7) 日历(4) 需要日期字段，在 postCreateUpdates 中设 calendarcids
8) 表格(0) 名称含"分组"/"分类"时，在 advancedSetting 中设 groupView

## 输出格式（严格 JSON）

{{
  "worksheets": [
    {{
      "worksheetId": "来自上方",
      "worksheetName": "名称",
      "views": [
        {{
          "name": "视图名",
          "viewType": "0",
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
