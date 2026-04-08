# 视图智能推荐系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 AI 语义推荐替代现有关键词规则，基于应用背景+工作表名+字段语义智能推荐视图类型并生成配置，三模块独立可运行，工作表间并行、视图间并行。

**Architecture:** 三个独立模块串联：`view_recommender.py`（硬约束过滤 + AI 推荐）→ `view_configurator.py`（每视图独立 AI 配置）→ `create_views_from_plan.py`（API 创建，已有）。`pipeline_views.py` 改为并行编排器，对多工作表并行调度整个流程。

**Tech Stack:** Python 3, `ai_utils.py`（统一 AI 调用）, `concurrent.futures.ThreadPoolExecutor`（并行）, `planning/constraints.py`（字段分类）, `views/view_types.py`（视图注册中心）

---

## File Structure

| 文件 | 职责 | 操作 |
|------|------|------|
| `scripts/hap/planners/view_recommender.py` | 硬约束过滤 + AI 推荐视图类型 | 新建 |
| `scripts/hap/planners/view_configurator.py` | 单个视图 AI 配置生成 | 新建 |
| `scripts/hap/pipeline_views.py` | 并行编排器（替代旧的串行流程） | 重写 |
| `scripts/hap/views/view_types.py` | 移除 viewType=6，更新画廊约束 | 修改 |
| `tests/unit/test_view_recommender.py` | 硬约束过滤 + 推荐校验测试 | 新建 |
| `tests/unit/test_view_configurator.py` | 配置校验测试 | 新建 |

不改动的文件：
- `scripts/hap/planning/constraints.py` — `classify_fields` 原样复用
- `scripts/hap/views/view_config_schema.py` — 配置 schema 原样复用
- `scripts/hap/executors/create_views_from_plan.py` — 创建逻辑不变
- `scripts/hap/execute_requirements.py` — 仍调用 `pipeline_views.py`，接口不变

---

### Task 1: 更新 view_types.py — 移除详情视图，更新画廊约束

**Files:**
- Modify: `scripts/hap/views/view_types.py`

- [ ] **Step 1: 移除 viewType=6 详情视图**

在 `scripts/hap/views/view_types.py` 中删除 VIEW_REGISTRY 中 key=6 的整个条目（约 296-296 行附近的整个 `6: {...}` 块）。

- [ ] **Step 2: 更新画廊(3)的 requires_fields**

```python
# 旧
"requires_fields": [],

# 新
"requires_fields": ["image_attachment"],
```

在 viewType=3 的条目中，将 `requires_fields` 从 `[]` 改为 `["image_attachment"]`，并更新 doc：

```python
"doc": "卡片画廊。需要图片相关附件字段(type=14)，字段名含图片/照片/头像等关键词。排除文档/视频类附件。",
```

- [ ] **Step 3: 更新 PLANNABLE_VIEWS**

确认 `PLANNABLE_VIEWS` 是 `set(VIEW_REGISTRY.keys())` 动态生成的，移除 key=6 后自动不含 6，无需额外修改。

- [ ] **Step 4: Commit**

```bash
git add scripts/hap/views/view_types.py
git commit -m "refactor: 移除详情视图(6)，更新画廊约束为图片附件字段"
```

---

### Task 2: 实现 view_recommender.py — 硬约束过滤

**Files:**
- Create: `scripts/hap/planners/view_recommender.py`
- Test: `tests/unit/test_view_recommender.py`

- [ ] **Step 1: 写硬约束过滤的测试**

创建 `tests/unit/test_view_recommender.py`：

```python
"""tests/unit/test_view_recommender.py — 硬约束过滤 + 推荐校验"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))


# ── 测试数据 ──────────────────────────────────────────────────────────────────

FIELDS_FULL = [
    {"id": "f_title", "name": "标题", "type": 2},
    {"id": "f_status", "name": "订单状态", "type": 11, "options": [
        {"key": "o1", "value": "待付款"}, {"key": "o2", "value": "已付款"},
        {"key": "o3", "value": "已发货"}, {"key": "o4", "value": "已完成"},
    ]},
    {"id": "f_date1", "name": "下单日期", "type": 15},
    {"id": "f_date2", "name": "发货日期", "type": 16},
    {"id": "f_member", "name": "负责人", "type": 26},
    {"id": "f_photo", "name": "商品图片", "type": 14},
    {"id": "f_loc", "name": "收货定位", "type": 40},
    {"id": "f_doc", "name": "合同文件", "type": 14},
]

FIELDS_MINIMAL = [
    {"id": "f_title", "name": "标题", "type": 2},
    {"id": "f_num", "name": "金额", "type": 6},
]


# ── 硬约束过滤测试 ────────────────────────────────────────────────────────────

class TestHardConstraints:
    def test_full_fields_all_types_available(self):
        from planners.view_recommender import get_available_view_types
        available = get_available_view_types(FIELDS_FULL)
        assert 0 in available  # 表格分组：有单选
        assert 1 in available  # 看板：有单选
        assert 3 in available  # 画廊：有图片附件
        assert 4 in available  # 日历：有日期
        assert 5 in available  # 甘特：有2个日期
        assert 7 in available  # 资源：有成员+2日期
        assert 8 in available  # 地图：有定位

    def test_minimal_fields_no_views(self):
        from planners.view_recommender import get_available_view_types
        available = get_available_view_types(FIELDS_MINIMAL)
        assert len(available) == 0

    def test_gallery_excludes_doc_attachment(self):
        """附件字段名含文档关键词时不触发画廊"""
        from planners.view_recommender import get_available_view_types
        fields = [
            {"id": "f1", "name": "标题", "type": 2},
            {"id": "f2", "name": "合同文件", "type": 14},
        ]
        available = get_available_view_types(fields)
        assert 3 not in available

    def test_gallery_includes_image_attachment(self):
        """附件字段名含图片关键词时触发画廊"""
        from planners.view_recommender import get_available_view_types
        fields = [
            {"id": "f1", "name": "标题", "type": 2},
            {"id": "f2", "name": "产品图片", "type": 14},
        ]
        available = get_available_view_types(fields)
        assert 3 in available

    def test_gantt_needs_two_dates(self):
        """甘特图需要两个日期字段"""
        from planners.view_recommender import get_available_view_types
        fields = [
            {"id": "f1", "name": "标题", "type": 2},
            {"id": "f2", "name": "日期", "type": 15},
        ]
        available = get_available_view_types(fields)
        assert 4 in available  # 日历可以
        assert 5 not in available  # 甘特不行

    def test_resource_needs_member_and_two_dates(self):
        """资源视图需要成员+两个日期"""
        from planners.view_recommender import get_available_view_types
        fields = [
            {"id": "f1", "name": "标题", "type": 2},
            {"id": "f2", "name": "开始", "type": 15},
            {"id": "f3", "name": "结束", "type": 16},
        ]
        available = get_available_view_types(fields)
        assert 7 not in available  # 无成员字段

    def test_no_detail_view(self):
        """详情视图(6)已移除，不应出现"""
        from planners.view_recommender import get_available_view_types
        available = get_available_view_types(FIELDS_FULL)
        assert 6 not in available


# ── 推荐结果校验测试 ──────────────────────────────────────────────────────────

class TestValidateRecommendation:
    def test_valid_recommendation_passes(self):
        from planners.view_recommender import validate_recommendation
        rec = {
            "views": [
                {"viewType": 1, "name": "状态看板", "reason": "有状态流转"},
                {"viewType": 4, "name": "订单日历", "reason": "按日期浏览"},
            ]
        }
        available = {0, 1, 3, 4, 5, 7, 8}
        result = validate_recommendation(rec, available)
        assert len(result["views"]) == 2

    def test_disallowed_type_dropped(self):
        from planners.view_recommender import validate_recommendation
        rec = {
            "views": [
                {"viewType": 1, "name": "看板", "reason": "..."},
                {"viewType": 8, "name": "地图", "reason": "..."},  # 不在可选池
            ]
        }
        available = {0, 1, 4}
        result = validate_recommendation(rec, available)
        assert len(result["views"]) == 1
        assert result["views"][0]["viewType"] == 1

    def test_duplicate_type_keeps_first(self):
        from planners.view_recommender import validate_recommendation
        rec = {
            "views": [
                {"viewType": 1, "name": "看板1", "reason": "..."},
                {"viewType": 1, "name": "看板2", "reason": "..."},
            ]
        }
        available = {1}
        result = validate_recommendation(rec, available)
        assert len(result["views"]) == 1
        assert result["views"][0]["name"] == "看板1"

    def test_max_seven_views(self):
        from planners.view_recommender import validate_recommendation
        rec = {
            "views": [{"viewType": i, "name": f"v{i}", "reason": "..."} for i in [0, 1, 3, 4, 5, 7, 8, 0]]
        }
        available = {0, 1, 3, 4, 5, 7, 8}
        result = validate_recommendation(rec, available)
        assert len(result["views"]) <= 7

    def test_empty_views_accepted(self):
        from planners.view_recommender import validate_recommendation
        rec = {"views": []}
        result = validate_recommendation(rec, {0, 1})
        assert result["views"] == []
```

- [ ] **Step 2: 运行测试确认全部失败**

```bash
cd /Users/andy/Documents/coding/hap-auto-maker
python -m pytest tests/unit/test_view_recommender.py -v
```

预期：全部 FAIL（`ModuleNotFoundError` 或 `ImportError`）

- [ ] **Step 3: 实现 view_recommender.py 的硬约束过滤和校验**

创建 `scripts/hap/planners/view_recommender.py`：

```python
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

    # 可选视图类型说明
    type_lines = []
    for vt, info in sorted(available_view_types.items()):
        spec = VIEW_REGISTRY.get(vt, {})
        name = spec.get("name", f"视图类型{vt}")
        doc = spec.get("doc", "")[:80]
        field_hints = ", ".join(
            f"{role}={f.get('name', '')}" for role, f in info.get("fields", {}).items()
        )
        type_lines.append(f"  {vt}. {name} — {doc}\n     可用字段: {field_hints}")

    available_section = "\n".join(type_lines) if type_lines else "  （无可用视图类型）"

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
            opt_str = f" 选项: {', '.join(vals)}"
        field_lines.append(f"  {fid} | type={ftype} | {fname}{opt_str}")

    fields_section = "\n".join(field_lines)

    other_ws = ", ".join(other_worksheet_names) if other_worksheet_names else "无"

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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_view_recommender.py -v
```

预期：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/hap/planners/view_recommender.py tests/unit/test_view_recommender.py
git commit -m "feat: 视图推荐器 — 硬约束过滤 + AI 推荐 + 校验"
```

---

### Task 3: 实现 view_configurator.py — 单视图 AI 配置

**Files:**
- Create: `scripts/hap/planners/view_configurator.py`
- Test: `tests/unit/test_view_configurator.py`

- [ ] **Step 1: 写配置校验的测试**

创建 `tests/unit/test_view_configurator.py`：

```python
"""tests/unit/test_view_configurator.py — 视图配置生成校验"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))

FIELDS = [
    {"id": "f_title", "name": "标题", "type": 2},
    {"id": "f_status", "name": "订单状态", "type": 11, "options": [
        {"key": "o1", "value": "待付款"}, {"key": "o2", "value": "已付款"},
    ]},
    {"id": "f_date1", "name": "下单日期", "type": 15},
    {"id": "f_date2", "name": "发货日期", "type": 16},
    {"id": "f_member", "name": "负责人", "type": 26},
]

FIELD_IDS = {f["id"] for f in FIELDS}


class TestValidateConfig:
    def test_valid_kanban_config(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 1,
            "name": "状态看板",
            "viewControl": "f_status",
            "advancedSetting": {"enablerules": "1"},
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is not None
        assert result["viewControl"] == "f_status"

    def test_invalid_field_id_discards_view(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 1,
            "name": "看板",
            "viewControl": "nonexistent_field",
            "advancedSetting": {},
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is None  # viewControl 必须存在，否则丢弃

    def test_unknown_advanced_setting_key_removed(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 4,
            "name": "日历",
            "advancedSetting": {
                "enablerules": "1",
                "bogus_key": "should_be_removed",
            },
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is not None
        assert "bogus_key" not in result.get("advancedSetting", {})

    def test_gantt_config_valid(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 5,
            "name": "甘特图",
            "advancedSetting": {},
            "postCreateUpdates": [{
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["begindate", "enddate"],
                "advancedSetting": {"begindate": "f_date1", "enddate": "f_date2"},
            }],
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        assert result is not None

    def test_post_create_updates_invalid_field_drops_entry(self):
        from planners.view_configurator import validate_view_config
        config = {
            "viewType": 5,
            "name": "甘特图",
            "advancedSetting": {},
            "postCreateUpdates": [{
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["begindate", "enddate"],
                "advancedSetting": {"begindate": "bad_id", "enddate": "f_date2"},
            }],
        }
        result = validate_view_config(config, FIELD_IDS, FIELDS)
        # 降级：postCreateUpdates 中引用了不存在的字段，该条目被移除
        assert result is not None
        pcu = result.get("postCreateUpdates", [])
        # 要么整个 postCreateUpdates 被清空，要么 bad_id 被移除
        for entry in pcu:
            ads = entry.get("advancedSetting", {})
            for v in ads.values():
                if isinstance(v, str) and v and not v.startswith("["):
                    assert v in FIELD_IDS or v == ""
```

- [ ] **Step 2: 运行测试确认全部失败**

```bash
python -m pytest tests/unit/test_view_configurator.py -v
```

预期：全部 FAIL

- [ ] **Step 3: 实现 view_configurator.py**

创建 `scripts/hap/planners/view_configurator.py`：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图配置生成器 — 为单个视图生成完整的 advancedSetting 和 postCreateUpdates。

可独立运行：
  python view_configurator.py --recommendation rec.json --fields-json fields.json

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

from views.view_types import VIEW_REGISTRY
from views.view_config_schema import VIEW_SCHEMA, COMMON_ADVANCED_KEYS
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json


# ── Step 2.5: 配置校验 ───────────────────────────────────────────────────────

def _get_allowed_ad_keys(view_type: int) -> set[str]:
    """获取该视图类型允许的 advancedSetting key 集合。"""
    allowed = set(COMMON_ADVANCED_KEYS.keys())
    registry_entry = VIEW_REGISTRY.get(view_type, {})
    ad_keys = registry_entry.get("advancedSetting_keys", {})
    allowed.update(ad_keys.keys())
    return allowed


def _check_field_ref(value: str, field_ids: set[str]) -> bool:
    """检查一个值是否是合法的字段 ID 引用。"""
    if not value or not isinstance(value, str):
        return True  # 空值合法
    if value.startswith("[") or value.startswith("{"):
        return True  # JSON 字符串不在此检查
    if value.startswith("$") and value.endswith("$"):
        inner = value[1:-1]
        return inner in field_ids
    return value in field_ids


def _try_fix_field_ref(value: str, field_ids: set[str], fields: list[dict]) -> str | None:
    """尝试按字段名匹配修正不存在的字段 ID。返回 None 表示无法修正。"""
    if not value or value in field_ids:
        return value
    # 按名称匹配
    for f in fields:
        fname = str(f.get("name", f.get("controlName", ""))).strip()
        if fname == value:
            return str(f.get("id", f.get("controlId", ""))).strip()
    return None


def validate_view_config(
    config: dict,
    field_ids: set[str],
    fields: list[dict],
) -> dict | None:
    """校验单个视图配置。返回校验后的 config，或 None（丢弃该视图）。

    校验规则：
    1. viewControl 引用的字段 ID 必须存在（看板/资源/地图必需，否则丢弃）
    2. advancedSetting 中未知 key 静默移除
    3. postCreateUpdates 中引用不存在的字段 ID → 尝试修正，失败则移除该条目
    """
    vt = int(config.get("viewType", 0))

    # 1. viewControl 校验（看板/资源/地图必需）
    vc = config.get("viewControl", "")
    needs_vc = vt in (1, 7, 8)
    if needs_vc and vc:
        fixed = _try_fix_field_ref(vc, field_ids, fields)
        if fixed is None:
            print(f"  [validate_config] 丢弃 viewType={vt}（viewControl={vc!r} 不存在）")
            return None
        config["viewControl"] = fixed

    # 2. advancedSetting key 过滤
    ad = config.get("advancedSetting", {})
    if isinstance(ad, dict):
        allowed_keys = _get_allowed_ad_keys(vt)
        unknown = [k for k in ad if k not in allowed_keys]
        for k in unknown:
            print(f"  [validate_config] 移除未知 advancedSetting key: {k}")
            del ad[k]
        config["advancedSetting"] = ad

    # 3. postCreateUpdates 校验
    pcu_list = config.get("postCreateUpdates", [])
    if isinstance(pcu_list, list):
        valid_pcu = []
        for entry in pcu_list:
            if not isinstance(entry, dict):
                continue
            entry_ad = entry.get("advancedSetting", {})
            entry_fields = entry.get("fields", {})

            # 检查 advancedSetting 中的字段引用
            bad = False
            if isinstance(entry_ad, dict):
                for k, v in list(entry_ad.items()):
                    if isinstance(v, str) and v and not v.startswith("[") and not v.startswith("{"):
                        if not _check_field_ref(v, field_ids):
                            fixed = _try_fix_field_ref(v, field_ids, fields)
                            if fixed is None:
                                print(f"  [validate_config] postCreateUpdates 字段引用 {k}={v!r} 不存在，移除条目")
                                bad = True
                                break
                            entry_ad[k] = fixed

            # 检查 fields 中的字段引用
            if not bad and isinstance(entry_fields, dict):
                for k, v in list(entry_fields.items()):
                    if isinstance(v, str) and v:
                        if not _check_field_ref(v, field_ids):
                            fixed = _try_fix_field_ref(v, field_ids, fields)
                            if fixed is None:
                                print(f"  [validate_config] postCreateUpdates.fields {k}={v!r} 不存在，移除条目")
                                bad = True
                                break
                            entry_fields[k] = fixed

            if not bad:
                valid_pcu.append(entry)

        config["postCreateUpdates"] = valid_pcu

    return config


# ── Step 2: AI 配置生成 ──────────────────────────────────────────────────────

def build_config_prompt(
    view_recommendation: dict,
    worksheet_name: str,
    fields: list[dict],
) -> str:
    """为单个视图构建配置 prompt。"""
    vt = view_recommendation.get("viewType", 0)
    view_name = view_recommendation.get("name", "")
    reason = view_recommendation.get("reason", "")

    registry_entry = VIEW_REGISTRY.get(vt, {})
    type_name = registry_entry.get("name", f"视图类型{vt}")
    ad_keys = registry_entry.get("advancedSetting_keys", {})
    top_level_extra = registry_entry.get("top_level_extra", {})
    post_create = registry_entry.get("post_create")

    # advancedSetting key 说明
    ad_lines = []
    for k, desc in sorted(ad_keys.items()):
        ad_lines.append(f"    {k}: {desc}")
    ad_section = "\n".join(ad_lines) if ad_lines else "    （无特殊配置项）"

    # 字段列表
    field_lines = []
    for f in fields:
        fid = f.get("id", f.get("controlId", ""))
        fname = f.get("name", f.get("controlName", ""))
        ftype = f.get("type", "")
        opts = f.get("options", [])
        opt_str = ""
        if opts and isinstance(opts, list):
            vals = [str(o.get("value", "")) for o in opts[:6] if isinstance(o, dict)]
            if vals:
                opt_str = f" 选项: {', '.join(vals)}"
        field_lines.append(f"  {fid} | type={ftype} | {fname}{opt_str}")
    fields_section = "\n".join(field_lines)

    # postCreateUpdates 模板
    pcu_hint = ""
    if post_create:
        pcu_hint = f"""
postCreateUpdates 模板（此视图类型需要二次保存）:
  editAttrs: {post_create.get('editAttrs', [])}
  editAdKeys: {post_create.get('editAdKeys', [])}
  请根据字段列表填入真实字段 ID。"""

    return f"""你是明道云视图配置专家。请为以下视图生成完整配置参数。

## 视图信息
- 类型: {vt} ({type_name})
- 名称: {view_name}
- 推荐理由: {reason}

## 工作表「{worksheet_name}」字段列表
{fields_section}

## 该视图可用的 advancedSetting 配置项
{ad_section}

## 顶层额外参数
{json.dumps(top_level_extra, ensure_ascii=False, indent=2) if top_level_extra else "无"}
{pcu_hint}

## 任务

根据视图类型和字段，输出完整配置。要求：
1. displayControls: 选 5-8 个最重要的字段 ID
2. viewControl: 看板(1)/资源(7)/地图(8) 必须填字段 ID；其他留空
3. advancedSetting: 只填有意义的配置，enablerules 默认 "1"
4. postCreateUpdates: 需要二次保存的视图必须填写，字段 ID 必须来自上方字段列表
5. 所有 JSON 字符串值用紧凑格式（无空格）
6. coverCid: 画廊(3) 填附件字段 ID；其他留空

## 输出格式（严格 JSON）

{{
  "viewType": {vt},
  "name": "{view_name}",
  "displayControls": ["字段ID1", "字段ID2"],
  "viewControl": "",
  "coverCid": "",
  "advancedSetting": {{}},
  "postCreateUpdates": []
}}"""


def configure_single_view(
    view_recommendation: dict,
    worksheet_name: str,
    fields: list[dict],
    field_ids: set[str] | None = None,
    ai_config: dict | None = None,
) -> dict | None:
    """为单个视图生成配置。返回完整配置 dict 或 None（失败）。"""
    start = time.time()
    if field_ids is None:
        field_ids = {
            str(f.get("id", f.get("controlId", ""))).strip()
            for f in fields
        }

    prompt = build_config_prompt(view_recommendation, worksheet_name, fields)

    config = ai_config or load_ai_config()
    client = get_ai_client(config)
    gen_config = create_generation_config(config, temperature=0.2)

    max_retries = 2
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
            if attempt < max_retries:
                print(f"  [configure] AI 失败（第{attempt+1}次），重试: {e}")
                time.sleep(1)
            else:
                print(f"  [configure] AI 失败（已重试{max_retries}次）: {e}")
                return None

    # Step 2.5: 校验
    validated = validate_view_config(raw_json, field_ids, fields)
    if validated:
        validated["_stats"] = {"elapsed_s": round(time.time() - start, 2)}
    return validated


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="视图配置生成器（可独立运行）")
    parser.add_argument("--recommendation", required=True, help="推荐结果 JSON 文件（单个视图）")
    parser.add_argument("--fields-json", required=True, help="字段 JSON 文件路径")
    parser.add_argument("--worksheet-name", default="测试表", help="工作表名称")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    args = parser.parse_args()

    rec = json.loads(Path(args.recommendation).read_text(encoding="utf-8"))
    fields = json.loads(Path(args.fields_json).read_text(encoding="utf-8"))

    result = configure_single_view(rec, args.worksheet_name, fields)

    output_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"配置结果已写入: {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/unit/test_view_configurator.py -v
```

预期：全部 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/hap/planners/view_configurator.py tests/unit/test_view_configurator.py
git commit -m "feat: 视图配置生成器 — 单视图 AI 配置 + 校验"
```

---

### Task 4: 重写 pipeline_views.py — 并行编排器

**Files:**
- Modify: `scripts/hap/pipeline_views.py`

- [ ] **Step 1: 重写 pipeline_views.py**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图流水线 v2 — 并行编排器。

对每个工作表并行执行：
  Step 0: 硬约束过滤 (代码)
  Step 1: AI 推荐 (1次AI)
  Step 2: AI 配置 × N (N次AI，视图间并行)
  Step 3: API 创建 × N (N次API，视图间并行)

用法：
  python pipeline_views.py --auth-config config/credentials/auth_config.py
  python pipeline_views.py --auth-config ... --app-ids "appId1,appId2"
  python pipeline_views.py --auth-config ... --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

from script_locator import resolve_script
from utils import now_ts, write_json

# 延迟导入（避免循环依赖）
def _import_recommender():
    from planners.view_recommender import recommend_views, get_available_view_types
    return recommend_views, get_available_view_types

def _import_configurator():
    from planners.view_configurator import configure_single_view
    return configure_single_view

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
VIEW_PLAN_DIR = OUTPUT_ROOT / "view_plans"
VIEW_CREATE_RESULT_DIR = OUTPUT_ROOT / "view_create_results"
DEFAULT_AUTH_CONFIG = BASE_DIR / "config" / "credentials" / "auth_config.py"

# 并行度控制
DEFAULT_WS_CONCURRENCY = 5    # 最多 N 个工作表同时规划
DEFAULT_VIEW_CONCURRENCY = 10  # 最多 N 个视图同时配置/创建


def _fetch_worksheets_and_fields(auth_config_path: Path, app_ids: str = "") -> list[dict]:
    """拉取应用、工作表和字段信息。复用现有 plan_worksheet_views_gemini 中的逻辑。"""
    from planners.plan_worksheet_views_gemini import (
        load_app_auth_rows, fetch_worksheets, fetch_controls, simplify_field,
    )

    rows = load_app_auth_rows()
    if app_ids:
        target_ids = {a.strip() for a in app_ids.split(",") if a.strip()}
        rows = [r for r in rows if r.get("appId", "") in target_ids]

    all_worksheets = []
    for row in rows:
        app_key = row.get("appKey", "")
        sign = row.get("sign", "")
        app_id = row.get("appId", "")
        app_name = row.get("appName", "") or row.get("name", "") or app_id

        ws_list = fetch_worksheets(app_key, sign)
        for ws in ws_list:
            ws_id = ws.get("workSheetId", "")
            controls_data = fetch_controls(ws_id, auth_config_path)
            raw_fields = controls_data.get("fields", [])
            fields = [simplify_field(f) for f in raw_fields]

            all_worksheets.append({
                "appId": app_id,
                "appName": app_name,
                "appKey": app_key,
                "sign": sign,
                "worksheetId": ws_id,
                "worksheetName": ws.get("workSheetName", ""),
                "fields": fields,
                "raw_fields": raw_fields,
            })

    return all_worksheets


def _process_single_worksheet(
    ws: dict,
    all_ws_names: list[str],
    app_background: str,
    auth_config_path: Path,
    ai_config: dict,
    dry_run: bool = False,
    view_concurrency: int = DEFAULT_VIEW_CONCURRENCY,
) -> dict:
    """处理单个工作表的完整流程：推荐 → 配置 → 创建。"""
    recommend_views, _ = _import_recommender()
    configure_single_view = _import_configurator()

    ws_id = ws["worksheetId"]
    ws_name = ws["worksheetName"]
    app_name = ws["appName"]
    fields = ws["fields"]
    start = time.time()

    result = {
        "worksheetId": ws_id,
        "worksheetName": ws_name,
        "recommendation": None,
        "configs": [],
        "creates": [],
        "stats": {},
    }

    other_names = [n for n in all_ws_names if n != ws_name]

    # Step 0 + 1: 推荐
    print(f"\n[{ws_name}] Step 1: AI 推荐视图...")
    rec = recommend_views(
        app_name=app_name,
        app_background=app_background,
        worksheet_name=ws_name,
        worksheet_id=ws_id,
        fields=fields,
        other_worksheet_names=other_names,
        ai_config=ai_config,
    )
    result["recommendation"] = rec
    views = rec.get("views", [])

    if not views:
        print(f"[{ws_name}] 无推荐视图，跳过")
        result["stats"] = {"elapsed_s": round(time.time() - start, 2), "views_recommended": 0}
        return result

    print(f"[{ws_name}] 推荐 {len(views)} 个视图: {', '.join(v['name'] for v in views)}")

    # Step 2: 并行配置
    print(f"[{ws_name}] Step 2: 并行配置 {len(views)} 个视图...")
    field_ids = {str(f.get("id", "")).strip() for f in fields}
    configs = []

    with ThreadPoolExecutor(max_workers=min(len(views), view_concurrency)) as pool:
        futures = {
            pool.submit(configure_single_view, v, ws_name, fields, field_ids, ai_config): v
            for v in views
        }
        for future in as_completed(futures):
            view_rec = futures[future]
            try:
                cfg = future.result()
                if cfg:
                    configs.append(cfg)
                    print(f"  [✓] {view_rec['name']} 配置完成")
                else:
                    print(f"  [✗] {view_rec['name']} 配置失败，丢弃")
            except Exception as e:
                print(f"  [✗] {view_rec['name']} 配置异常: {e}")

    result["configs"] = configs

    if not configs:
        print(f"[{ws_name}] 所有视图配置失败，跳过创建")
        result["stats"] = {"elapsed_s": round(time.time() - start, 2), "views_recommended": len(views), "views_configured": 0}
        return result

    # Step 3: 并行创建
    if dry_run:
        print(f"[{ws_name}] --dry-run 模式，跳过创建")
        result["stats"] = {
            "elapsed_s": round(time.time() - start, 2),
            "views_recommended": len(views),
            "views_configured": len(configs),
            "dry_run": True,
        }
        return result

    print(f"[{ws_name}] Step 3: 并行创建 {len(configs)} 个视图...")
    from executors.create_views_from_plan import create_single_view_from_config
    import auth_retry

    creates = []
    with ThreadPoolExecutor(max_workers=min(len(configs), view_concurrency)) as pool:
        futures = {}
        for cfg in configs:
            # 构建 create_views_from_plan 兼容的参数
            view_data = {
                "name": cfg.get("name", ""),
                "viewType": str(cfg.get("viewType", "0")),
                "displayControls": cfg.get("displayControls", []),
                "viewControl": cfg.get("viewControl", ""),
                "coverCid": cfg.get("coverCid", ""),
                "advancedSetting": cfg.get("advancedSetting", {}),
                "postCreateUpdates": cfg.get("postCreateUpdates", []),
            }
            futures[pool.submit(
                create_single_view_from_config,
                ws_id, ws["appId"], view_data, auth_config_path
            )] = cfg

        for future in as_completed(futures):
            cfg = futures[future]
            try:
                create_result = future.result()
                creates.append(create_result)
                status = "✓" if create_result.get("success") else "✗"
                print(f"  [{status}] {cfg.get('name', '')} 创建{'成功' if status == '✓' else '失败'}")
            except Exception as e:
                print(f"  [✗] {cfg.get('name', '')} 创建异常: {e}")
                creates.append({"name": cfg.get("name", ""), "success": False, "error": str(e)})

    result["creates"] = creates
    result["stats"] = {
        "elapsed_s": round(time.time() - start, 2),
        "views_recommended": len(views),
        "views_configured": len(configs),
        "views_created": sum(1 for c in creates if c.get("success")),
        "views_failed": sum(1 for c in creates if not c.get("success")),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="视图流水线 v2 — 并行编排器")
    parser.add_argument("--auth-config", default=str(DEFAULT_AUTH_CONFIG))
    parser.add_argument("--app-ids", default="", help="可选，仅执行指定 appId（逗号分隔）")
    parser.add_argument("--dry-run", action="store_true", help="仅规划和配置，不实际创建")
    parser.add_argument("--ws-concurrency", type=int, default=DEFAULT_WS_CONCURRENCY)
    parser.add_argument("--view-concurrency", type=int, default=DEFAULT_VIEW_CONCURRENCY)
    parser.add_argument("--background", default="通用企业管理场景", help="应用业务背景")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    args = parser.parse_args()

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    from ai_utils import load_ai_config
    ai_config = load_ai_config()

    print("=" * 60)
    print("视图流水线 v2 — 并行编排器")
    print("=" * 60)

    # 拉取工作表和字段
    print("\n拉取应用和工作表信息...")
    all_ws = _fetch_worksheets_and_fields(auth_config_path, args.app_ids)
    all_ws_names = [ws["worksheetName"] for ws in all_ws]
    print(f"共 {len(all_ws)} 个工作表: {', '.join(all_ws_names)}")

    # 并行处理工作表
    pipeline_start = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=args.ws_concurrency) as pool:
        futures = {
            pool.submit(
                _process_single_worksheet,
                ws, all_ws_names, args.background,
                auth_config_path, ai_config, args.dry_run,
                args.view_concurrency,
            ): ws
            for ws in all_ws
        }
        for future in as_completed(futures):
            ws = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"\n[✗] {ws['worksheetName']} 整体失败: {e}")
                results.append({
                    "worksheetId": ws["worksheetId"],
                    "worksheetName": ws["worksheetName"],
                    "error": str(e),
                })

    # Summary
    total_elapsed = time.time() - pipeline_start
    print(f"\n{'=' * 60}")
    print("视图流水线 Summary")
    print(f"{'=' * 60}")
    for r in results:
        stats = r.get("stats", {})
        name = r.get("worksheetName", "?")
        if "error" in r:
            print(f"  {name}: 失败 — {r['error']}")
        elif stats.get("dry_run"):
            print(f"  {name}: 推荐 {stats.get('views_recommended', 0)} → 配置 {stats.get('views_configured', 0)} (dry-run)")
        else:
            print(f"  {name}: 推荐 {stats.get('views_recommended', 0)} → 配置 {stats.get('views_configured', 0)} → 创建 {stats.get('views_created', 0)}/{stats.get('views_configured', 0)}")
    print(f"  总耗时: {total_elapsed:.1f}s")

    # 保存结果
    output_path = args.output or str(VIEW_PLAN_DIR / f"view_pipeline_v2_{now_ts()}.json")
    write_json(Path(output_path), {"results": results, "elapsed_s": round(total_elapsed, 2)})
    print(f"\n结果已写入: {output_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 确认 create_views_from_plan.py 有 create_single_view_from_config 函数**

检查 `scripts/hap/executors/create_views_from_plan.py` 是否已有可复用的单视图创建函数。如果没有，需要从中提取一个 `create_single_view_from_config(ws_id, app_id, view_data, auth_config_path) -> dict` 函数。

现有的创建逻辑在 `create_views_from_plan.py` 中，需要确认其接口是否能直接调用。如果该文件目前只有 `main()` 入口，需要从中抽取创建单个视图的函数。

具体做法：阅读 `create_views_from_plan.py` 找到创建单个视图的核心逻辑（通常是调用 `SaveWorksheetView` API 的部分），将其提取为 `create_single_view_from_config` 函数，接收 `(worksheet_id, app_id, view_config, auth_config_path)` 参数，返回 `{"success": bool, "viewId": str, "error": str}`。

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/pipeline_views.py
git commit -m "feat: 重写视图流水线为并行编排器（工作表间并行+视图间并行）"
```

---

### Task 5: 提取 create_single_view_from_config 函数

**Files:**
- Modify: `scripts/hap/executors/create_views_from_plan.py`

- [ ] **Step 1: 阅读现有创建逻辑**

阅读 `scripts/hap/executors/create_views_from_plan.py` 的完整代码，找到调用 `SaveWorksheetView` API 创建视图的核心函数。

- [ ] **Step 2: 提取 create_single_view_from_config**

如果现有代码没有独立的单视图创建函数，从现有逻辑中提取一个：

```python
def create_single_view_from_config(
    worksheet_id: str,
    app_id: str,
    view_config: dict,
    auth_config_path: Path,
) -> dict:
    """创建单个视图。供 pipeline_views.py 并行调用。

    Args:
        worksheet_id: 工作表 ID
        app_id: 应用 ID
        view_config: {name, viewType, displayControls, viewControl, coverCid, advancedSetting, postCreateUpdates}
        auth_config_path: auth_config.py 路径

    Returns:
        {"success": bool, "viewId": str, "name": str, "error": str}
    """
    # 复用现有的 SaveWorksheetView API 调用逻辑
    # 包含：创建 → 二次保存 postCreateUpdates
    ...
```

核心是把现有的批量创建逻辑中"创建单个视图"的部分抽出来，使其可被外部并行调用。

- [ ] **Step 3: 确保原有 main() 入口不受影响**

原有的 `main()` 和 CLI 入口保持不变（仍然读取 plan JSON 文件批量创建）。新增的函数是给 `pipeline_views.py` 调用的。

- [ ] **Step 4: Commit**

```bash
git add scripts/hap/executors/create_views_from_plan.py
git commit -m "refactor: 提取 create_single_view_from_config 供并行流水线调用"
```

---

### Task 6: 集成测试 — 端到端 dry-run

**Files:**
- 无新文件，使用已有脚本

- [ ] **Step 1: 运行所有单元测试**

```bash
cd /Users/andy/Documents/coding/hap-auto-maker
python -m pytest tests/unit/test_view_recommender.py tests/unit/test_view_configurator.py -v
```

预期：全部 PASS

- [ ] **Step 2: 独立测试推荐器（用 mock 数据）**

创建一个临时测试字段文件，手动验证推荐器输出：

```bash
cat > /tmp/test_fields.json << 'EOF'
[
  {"id": "f1", "name": "订单编号", "type": 33},
  {"id": "f2", "name": "订单状态", "type": 11, "options": [
    {"key": "o1", "value": "待付款"}, {"key": "o2", "value": "已付款"},
    {"key": "o3", "value": "已发货"}, {"key": "o4", "value": "已完成"}
  ]},
  {"id": "f3", "name": "下单日期", "type": 15},
  {"id": "f4", "name": "发货日期", "type": 16},
  {"id": "f5", "name": "客户", "type": 2},
  {"id": "f6", "name": "金额", "type": 8},
  {"id": "f7", "name": "负责人", "type": 26}
]
EOF

cd /Users/andy/Documents/coding/hap-auto-maker/scripts/hap
python planners/view_recommender.py \
  --app-name "电商订单管理" \
  --background "覆盖下单、支付、发货、退换货全流程的电商订单管理系统" \
  --worksheet-name "订单" \
  --fields-json /tmp/test_fields.json \
  --other-worksheets "客户,商品,物流"
```

预期：输出 JSON，包含推荐的视图列表（应该包含看板、日历、甘特图、资源视图）。

- [ ] **Step 3: 验证旧测试不受影响**

```bash
python -m pytest tests/unit/test_view_planner.py -v
```

如果旧测试因 viewType=6 移除而失败，需要更新测试数据。

- [ ] **Step 4: Commit**

```bash
git commit -m "test: 集成测试通过，视图推荐器端到端验证"
```

---

### Task 7: 清理旧代码

**Files:**
- Modify: `scripts/hap/planning/view_planner.py`
- Modify: `scripts/hap/planners/plan_worksheet_views_gemini.py`

- [ ] **Step 1: 在 view_planner.py 中标记旧函数为废弃**

在 `scripts/hap/planning/view_planner.py` 中：
- `suggest_views` 函数顶部加 `# DEPRECATED: 被 planners/view_recommender.py 替代`
- `build_structure_prompt` 函数顶部加同样标记
- `build_config_prompt` 函数顶部加同样标记

暂不删除（保持向后兼容，旧的 `plan_worksheet_views_gemini.py` 仍可运行），等新流水线稳定后再清理。

- [ ] **Step 2: 在 plan_worksheet_views_gemini.py 中同样标记**

在文件顶部 docstring 加注：

```python
"""
[DEPRECATED] 旧版视图规划脚本。新流水线使用 pipeline_views.py v2 + view_recommender + view_configurator。
此文件保留以支持回退。
"""
```

- [ ] **Step 3: Commit**

```bash
git add scripts/hap/planning/view_planner.py scripts/hap/planners/plan_worksheet_views_gemini.py
git commit -m "refactor: 标记旧视图规划代码为 DEPRECATED，保留回退能力"
```
