#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图智能推荐器 — Step 0 硬约束过滤 + Step 1 AI 语义推荐。

可独立运行测试：
  python view_recommender.py --app-name "订单管理" --worksheet-name "订单" --fields-json fields.json
  python view_recommender.py --spec-json requirement_spec.json --auth-config auth_config.py

也可被 pipeline_views.py 作为模块调用。
"""

from __future__ import annotations

import sys
from pathlib import Path

_HAP_DIR = Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import time
from typing import Any, Dict, List, Optional, Set

from planning.constraints import classify_fields
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json
from i18n import get_runtime_language, normalize_language

# ── 画廊附件字段语义判断 ─────────────────────────────────────────────────────

IMAGE_KEYWORDS = {
    "图片", "图像", "照片", "头像", "封面", "缩略图", "截图",
    "logo", "图标", "banner", "image", "photo", "picture",
    "cover", "thumbnail", "相册", "写真", "证件照",
}
DOC_VIDEO_EXCLUDE = {
    "文档", "文件", "视频", "音频", "合同", "附件", "资料",
    "报告", "方案", "简历",
}

MAX_VIEWS_PER_WORKSHEET = 7


def _is_image_attachment(field: dict) -> bool:
    """判断附件字段是否与图片/图像相关。"""
    name = str(field.get("name", "")).strip().lower()
    if not name:
        return False
    has_image = any(kw in name for kw in IMAGE_KEYWORDS)
    has_exclude = any(kw in name for kw in DOC_VIDEO_EXCLUDE)
    return has_image and not has_exclude


# ── Step 0: 硬约束过滤 ───────────────────────────────────────────────────────

def get_available_view_types(fields: list[dict]) -> dict[int, dict]:
    """根据字段列表，返回该工作表可创建的视图类型及关联字段信息。

    Returns:
        {viewType: {"fields": {字段角色: field_info}}}
        例如 {1: {"fields": {"select": {"id": "f1", "name": "状态", "type": 11}}}}
    """
    classified = classify_fields(fields)
    available: dict[int, dict] = {}

    # 单选字段（type=9 或 type=11）
    select_fields = [
        f for f in classified.get("select", [])
        if f.get("type") in (9, 11) and f.get("options")
    ]

    # 日期字段
    date_fields = classified.get("date", [])

    # 成员字段（type=26）
    member_fields = [f for f in classified.get("user", []) if f.get("type") == 26]

    # 图片附件字段
    attachment_fields = classified.get("attachment", [])
    image_attachments = [f for f in attachment_fields if _is_image_attachment(f)]

    # 定位字段（type=40）
    location_fields = classified.get("location", [])
    gps_fields = [f for f in location_fields if f.get("type") == 40]

    # 表格分组(0)：需要单选字段
    if select_fields:
        available[0] = {"fields": {"select": select_fields[0]}}

    # 看板(1)：需要单选字段
    if select_fields:
        available[1] = {"fields": {"select": select_fields[0]}}

    # 画廊(3)：需要图片附件字段
    if image_attachments:
        available[3] = {"fields": {"image_attachment": image_attachments[0]}}

    # 日历(4)：需要日期字段
    if date_fields:
        available[4] = {"fields": {"date": date_fields[0]}}

    # 甘特(5)：需要两个日期字段
    if len(date_fields) >= 2:
        available[5] = {"fields": {"begin_date": date_fields[0], "end_date": date_fields[1]}}

    # 资源(7)：需要成员字段 + 两个日期字段
    if member_fields and len(date_fields) >= 2:
        available[7] = {"fields": {
            "member": member_fields[0],
            "begin_date": date_fields[0],
            "end_date": date_fields[1],
        }}

    # 地图(8)：需要定位字段(type=40)
    if gps_fields:
        available[8] = {"fields": {"location": gps_fields[0]}}

    return available


# ── Step 1.5: 推荐结果校验 ───────────────────────────────────────────────────

def validate_recommendation(
    raw: dict,
    available_types: set[int],
) -> dict:
    """校验 AI 推荐结果，丢弃不合法的视图。

    规则：
    - viewType 必须在 available_types 内
    - 同一 viewType 只保留第一个
    - 总数不超过 MAX_VIEWS_PER_WORKSHEET
    """
    views = raw.get("views", [])
    if not isinstance(views, list):
        return {"views": []}

    seen_types: set[int] = set()
    filtered: list[dict] = []

    for view in views:
        vt_raw = view.get("viewType")
        try:
            vt = int(vt_raw)
        except (ValueError, TypeError):
            continue

        if vt not in available_types:
            print(f"  [validate] 丢弃 viewType={vt}（不在可选池 {available_types} 中）")
            continue

        if vt in seen_types:
            print(f"  [validate] 丢弃重复 viewType={vt}（已有同类型视图）")
            continue

        seen_types.add(vt)
        view["viewType"] = vt  # 统一为 int
        filtered.append(view)

        if len(filtered) >= MAX_VIEWS_PER_WORKSHEET:
            break

    return {"views": filtered}


# ── Step 1: AI 推荐 ──────────────────────────────────────────────────────────

def build_recommend_prompt(
    app_name: str,
    app_background: str,
    worksheet_name: str,
    fields: list[dict],
    other_worksheet_names: list[str],
    available_view_types: dict[int, dict],
) -> str:
    """构建 AI 推荐 prompt。"""
    from views.view_types import VIEW_REGISTRY
    lang = normalize_language(get_runtime_language())
    is_en = lang == "en"

    # 可选视图类型说明
    type_lines = []
    for vt, info in sorted(available_view_types.items()):
        spec = VIEW_REGISTRY.get(vt, {})
        name = spec.get("name", f"视图类型{vt}")
        doc = spec.get("doc", "")[:80]
        field_hints = ", ".join(
            f"{role}={f.get('name', '')}" for role, f in info.get("fields", {}).items()
        )
        if is_en:
            type_lines.append(f"  {vt}. {name} — {doc}\n     Available fields: {field_hints}")
        else:
            type_lines.append(f"  {vt}. {name} — {doc}\n     可用字段: {field_hints}")

    available_section = "\n".join(type_lines) if type_lines else ("  (no available view types)" if is_en else "  （无可用视图类型）")

    # 字段摘要
    field_lines = []
    for f in fields:
        fid = f.get("id", f.get("controlId", ""))
        fname = f.get("name", f.get("controlName", ""))
        ftype = f.get("type", "")
        opts = f.get("options", [])
        opt_str = ""
        if opts and isinstance(opts, list):
            vals = [str(o.get("value", "")) for o in opts[:6] if isinstance(o, dict)]
            opt_str = f" Options: {', '.join(vals)}" if is_en else f" 选项: {', '.join(vals)}"
        field_lines.append(f"  {fid} | type={ftype} | {fname}{opt_str}")

    fields_section = "\n".join(field_lines)

    other_ws = ", ".join(other_worksheet_names) if other_worksheet_names else ("none" if is_en else "无")

    if is_en:
        return f"""You are an enterprise app view design expert. Recommend the most valuable views for this worksheet based on the business context and available fields.

## App context
- App name: {app_name}
- Business context: {app_background}
- Other worksheets in the same app: {other_ws}

## Current worksheet: {worksheet_name}

### Fields
{fields_section}

### Available view types
{available_section}

## Task

Choose the views that have clear business value. At most one per view type and no more than {MAX_VIEWS_PER_WORKSHEET} total.

Evaluation rules:
- Kanban (1): use only when the select field represents a real workflow or status transition.
- Calendar (4): use only when the date field has real browsing value over time.
- Gantt (5): use only when two date fields represent a meaningful start/end span.
- Resource (7): use only when there is a scheduling or allocation scenario involving people and time.
- Gallery (3): use only when browsing images is useful to the business.
- Map (8): use only when location is a core business dimension.
- Grouped table (0): use only when grouped browsing adds value beyond the default list.

Do not force recommendations. If a view has no clear value, do not select it.

## Output

Return strict JSON only:
{{
  "views": [
    {{
      "viewType": 1,
      "name": "English view name with clear business meaning",
      "reason": "English reason describing the business value"
    }}
  ]
}}"""

    return f"""你是一名企业软件视图设计专家。请根据业务背景和工作表字段，从可选视图类型中推荐最有业务价值的视图。

## 应用背景
- 应用名称: {app_name}
- 业务场景: {app_background}
- 同应用其他工作表: {other_ws}

## 当前工作表: {worksheet_name}

### 字段列表
{fields_section}

### 可选视图类型（已通过字段约束检查，以下类型均可创建）
{available_section}

## 任务

从可选视图类型中选择有业务价值的视图。每种类型最多选 1 个，总数不超过 {MAX_VIEWS_PER_WORKSHEET} 个。

判断标准：
- 看板(1)：该单选字段是否代表「阶段流转」（如待处理→处理中→已完成）？纯分类字段（类型、来源、行业）不适合看板。
- 日历(4)：该日期字段是否有时间维度浏览意义？流水账类（台账、明细）不太需要日历。
- 甘特(5)：两个日期字段是否代表起止跨度？任务/项目/计划类工作表适合。
- 资源(7)：是否有人员+时间的排期/分配场景？
- 画廊(3)：图片浏览是否有业务意义？
- 地图(8)：地理位置信息是否是核心业务维度？
- 表格分组(0)：分组浏览是否比默认列表视图有额外价值？

不要勉强推荐——如果某种视图对该业务场景没有明确价值，就不要选它。

## 输出格式（严格 JSON）

{{
  "views": [
    {{
      "viewType": 1,
      "name": "视图名称（简洁有业务含义）",
      "reason": "推荐理由（说明该视图对这个业务场景的价值）"
    }}
  ]
}}"""


def recommend_views(
    app_name: str,
    app_background: str,
    worksheet_name: str,
    worksheet_id: str,
    fields: list[dict],
    other_worksheet_names: list[str] | None = None,
    ai_config: dict | None = None,
) -> dict:
    """执行完整的推荐流程：硬约束过滤 → AI 推荐 → 校验。

    Returns:
        {
            "worksheetId": str,
            "worksheetName": str,
            "available_view_types": [int, ...],
            "views": [{viewType, name, reason}, ...],
            "stats": {"elapsed_s": float, "ai_called": bool},
        }
    """
    start = time.time()

    # Step 0: 硬约束过滤
    available = get_available_view_types(fields)
    if not available:
        return {
            "worksheetId": worksheet_id,
            "worksheetName": worksheet_name,
            "available_view_types": [],
            "views": [],
            "stats": {"elapsed_s": time.time() - start, "ai_called": False},
        }

    # Step 1: AI 推荐
    prompt = build_recommend_prompt(
        app_name=app_name,
        app_background=app_background,
        worksheet_name=worksheet_name,
        fields=fields,
        other_worksheet_names=other_worksheet_names or [],
        available_view_types=available,
    )

    config = ai_config or load_ai_config()
    client = get_ai_client(config)
    gen_config = create_generation_config(config, temperature=0.2)

    max_retries = 2
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=config.get("model", ""),
                contents=prompt,
                config=gen_config,
            )
            raw_text = response.text if hasattr(response, "text") else str(response)
            raw_json = parse_ai_json(raw_text)
            break
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                print(f"  [recommend] AI 调用失败（第{attempt+1}次），重试: {e}")
                time.sleep(1)
            else:
                print(f"  [recommend] AI 调用失败（已重试{max_retries}次）: {last_error}")
                return {
                    "worksheetId": worksheet_id,
                    "worksheetName": worksheet_name,
                    "available_view_types": list(available.keys()),
                    "views": [],
                    "stats": {"elapsed_s": time.time() - start, "ai_called": True, "error": str(last_error)},
                }

    # Step 1.5: 校验
    validated = validate_recommendation(raw_json, set(available.keys()))

    return {
        "worksheetId": worksheet_id,
        "worksheetName": worksheet_name,
        "available_view_types": list(available.keys()),
        "views": validated["views"],
        "stats": {"elapsed_s": time.time() - start, "ai_called": True},
    }


# ── CLI 独立运行 ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="视图智能推荐器（可独立运行测试）")
    parser.add_argument("--app-name", default="测试应用", help="应用名称")
    parser.add_argument("--background", default="通用企业管理", help="业务背景描述")
    parser.add_argument("--worksheet-name", default="", help="工作表名称")
    parser.add_argument("--worksheet-id", default="test_ws", help="工作表 ID")
    parser.add_argument("--fields-json", default="", help="字段 JSON 文件路径")
    parser.add_argument("--other-worksheets", default="", help="其他工作表名称（逗号分隔）")
    parser.add_argument("--spec-json", default="", help="从 requirement_spec 提取信息")
    parser.add_argument("--auth-config", default="", help="auth_config.py 路径（在线拉取字段）")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    args = parser.parse_args()

    # 加载字段
    if args.fields_json:
        fields = json.loads(Path(args.fields_json).read_text(encoding="utf-8"))
    else:
        fields = []
        print("[warning] 未指定 --fields-json，使用空字段列表")

    other_ws = [n.strip() for n in args.other_worksheets.split(",") if n.strip()] if args.other_worksheets else []

    result = recommend_views(
        app_name=args.app_name,
        app_background=args.background,
        worksheet_name=args.worksheet_name,
        worksheet_id=args.worksheet_id,
        fields=fields,
        other_worksheet_names=other_ws,
    )

    output_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"推荐结果已写入: {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
