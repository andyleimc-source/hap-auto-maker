"""
Pages 规划模块 — 仅根据工作表名称规划自定义分析页（Page）。

与 plan_pages_gemini.py 的区别：
  - 不需要字段信息，仅需工作表名称列表
  - 输出 worksheetNames（而非 worksheetIds）
  - 更轻量，适用于事件驱动 pipeline
"""

from __future__ import annotations

import json
from typing import Any

from i18n import normalize_language

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 图标候选列表（仅使用明道云 customIcon CDN 中已验证可用的图标）
ICON_CANDIDATES: list[dict[str, str]] = [
    {"name": "sys_dashboard", "desc": "综合概览/仪表盘"},
    {"name": "sys_2_3_statistics", "desc": "统计汇总/数据总览"},
    {"name": "sys_1_1_combo_chart", "desc": "综合图表/多维分析"},
    {"name": "sys_2_1_bar_chart", "desc": "柱状图/销售业绩/对比分析"},
    {"name": "sys_2_2_pie_chart", "desc": "饼图/占比分析/分布"},
    {"name": "sys_chart-growth_finance", "desc": "增长趋势/业绩走势"},
    {"name": "sys_chart-bar_finance", "desc": "财务柱图/收支分析"},
    {"name": "sys_money-bag_finance", "desc": "财务/资金/成本"},
    {"name": "sys_1_3_us_dollar", "desc": "金额/营收/财务指标"},
    {"name": "sys_stock-market_office", "desc": "市场/销售/行情"},
    {"name": "sys_chart-pie_office", "desc": "市场占比/客户分布"},
    {"name": "sys_folder-chart-bar_office", "desc": "报告/数据报表"},
    {"name": "sys_1_10_people", "desc": "人员/HR/团队"},
    {"name": "sys_2_5_handshake", "desc": "客户/合作/关系"},
    {"name": "sys_8_3_briefcase", "desc": "项目/业务/工作"},
]

VALID_ICONS: set[str] = {ic["name"] for ic in ICON_CANDIDATES}

# 颜色池（Material Design 主色调）
COLOR_POOL: list[str] = [
    "#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336",
    "#00BCD4", "#795548", "#607D8B", "#E91E63", "#3F51B5",
]


# ---------------------------------------------------------------------------
# Prompt 构建
# ---------------------------------------------------------------------------

def build_pages_prompt(app_name: str, worksheet_names: list[str], language: str = "zh") -> str:
    """生成 Pages 规划 prompt，仅需工作表名称列表。

    根据工作表数量决定 Pages 数量：
      - 1-6 表  → 1 页
      - 7-15 表 → 2 页
      - 16+ 表  → 3 页
    """
    num_ws = len(worksheet_names)
    lang = normalize_language(language)
    if num_ws <= 6:
        target_pages = 1
    elif num_ws <= 15:
        target_pages = 2
    else:
        target_pages = 3

    ws_list_str = json.dumps(worksheet_names, ensure_ascii=False)
    icon_desc_lines = "\n".join(
        f"   - {ic['name']}（{ic['desc']}）" for ic in ICON_CANDIDATES
    )
    colors_str = "、".join(COLOR_POOL[:6])

    if lang == "en":
        return f"""You are an enterprise analytics architect. Plan custom analytics pages for this application.
Each page should focus on one distinct business analysis theme for business users.

Application:
- appName: {app_name}

Worksheet names:
{ws_list_str}

Requirements:
1. Plan exactly {target_pages} pages, each covering a different business theme.
2. Each page must include worksheetNames selected from the list above.
3. Every worksheet must appear in at least one page.
4. Choose each page icon from the candidate list below:
{icon_desc_lines}
   Try not to repeat icons.
5. Choose iconColor from: {colors_str}. Avoid duplicates when possible.
6. desc must be a short English business description.
7. name must be a concise English page name, ideally 1-4 words.
8. Every page must include at least one worksheet.

Return strict JSON only:
{{
  "pages": [
    {{
      "name": "Page Name",
      "icon": "sys_dashboard",
      "iconColor": "#2196F3",
      "desc": "Short business description",
      "worksheetNames": ["Worksheet A", "Worksheet B"]
    }}
  ]
}}"""

    return f"""你是企业数据分析架构师。请根据下面的应用结构，为该应用规划自定义数据分析页（Page）。
每个 Page 聚焦一个独立的业务分析主题，供经营层快速查看数据。

应用信息：
- appName: {app_name}

工作表名称列表：
{ws_list_str}

设计要求：
1. 规划恰好 {target_pages} 个 Page，每个 Page 聚焦不同业务主题（选取最有价值的业务维度）。
2. 每个 Page 的 worksheetNames 列出该 Page 需要统计分析的工作表名称（从上面的列表中选择）。
3. 所有工作表必须被至少一个 Page 关联。
4. icon 从以下候选列表中，根据每个 Page 的业务主题选择最贴切的一个：
{icon_desc_lines}
   每个 Page 选不同的 icon（尽量不重复）。
5. iconColor 从以下选择（两个 Page 颜色不重复）：{colors_str}
6. desc 简短说明该 Page 的业务分析价值（20 字以内）。
7. 各 Page 名称简洁有业务含义（10 字以内）。
8. 每个 Page 必须关联至少 1 个工作表。

输出严格 JSON，不要 markdown，不要任何解释：
{{
  "pages": [
    {{
      "name": "Page 名称",
      "icon": "sys_dashboard",
      "iconColor": "#2196F3",
      "desc": "简短业务描述",
      "worksheetNames": ["工作表名称1", "工作表名称2"]
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def validate_pages_plan(raw: dict, valid_ws_names: set[str]) -> list[dict]:
    """校验 AI 输出的 pages plan。

    - 过滤无效工作表名
    - 修正非法 icon（回退到 sys_dashboard）
    - 确保 iconColor 有值
    - 添加 iconUrl

    Returns:
        校验通过的 page 列表。

    Raises:
        ValueError: 当 pages 数组缺失或为空、page 格式错误等。
    """
    pages = raw.get("pages", [])
    if not isinstance(pages, list) or len(pages) == 0:
        raise ValueError("AI 未返回 pages 数组")
    if not (1 <= len(pages) <= 4):
        raise ValueError(f"期望 1-4 个 Page，实际返回 {len(pages)} 个")

    validated: list[dict[str, Any]] = []
    for i, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ValueError(f"Page {i+1} 格式错误")

        name = str(page.get("name", "")).strip()
        if not name:
            raise ValueError(f"Page {i+1} 缺少 name")

        # 校验 worksheetNames，过滤不存在的名称
        ws_names = page.get("worksheetNames", [])
        if not isinstance(ws_names, list) or len(ws_names) == 0:
            raise ValueError(f"Page {i+1} 缺少 worksheetNames")
        valid_names = [n for n in ws_names if str(n).strip() in valid_ws_names]
        if not valid_names:
            print(f"[警告] Page {i+1} 的 worksheetNames 均不在应用工作表中，已跳过: {ws_names}")
            continue
        page["worksheetNames"] = valid_names

        # 校验 icon：只允许候选列表中的图标，否则回退到 sys_dashboard
        icon = str(page.get("icon", "")).strip()
        if icon not in VALID_ICONS:
            icon = "sys_dashboard"
        page["icon"] = icon
        page["iconColor"] = str(page.get("iconColor", "#2196F3")).strip() or "#2196F3"
        page["iconUrl"] = f"https://fp1.mingdaoyun.cn/customIcon/{icon}.svg"

        validated.append(page)

    return validated
