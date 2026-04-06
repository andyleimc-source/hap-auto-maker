"""
HAP Auto Maker — 注册中心 & 规划师总览 CLI

用法:
    python scripts/show_registry.py              # 全部总览
    python scripts/show_registry.py fields        # 只看字段
    python scripts/show_registry.py views         # 只看视图
    python scripts/show_registry.py charts        # 只看图表
    python scripts/show_registry.py planners      # 只看规划师
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保 import 路径
_ROOT = Path(__file__).resolve().parents[1]
_HAP = _ROOT / "scripts" / "hap"
for p in [str(_HAP)]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── 颜色辅助 ──────────────────────────────────────────────────────────────────

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def bold(t: str) -> str: return _c(t, "1")
def dim(t: str) -> str: return _c(t, "2")
def green(t: str) -> str: return _c(t, "32")
def cyan(t: str) -> str: return _c(t, "36")
def yellow(t: str) -> str: return _c(t, "33")
def magenta(t: str) -> str: return _c(t, "35")
def white_bg(t: str) -> str: return _c(t, "7")


def _header(title: str, count: int, source: str):
    print()
    print(bold(f"{'=' * 60}"))
    print(bold(f"  {title}") + dim(f"  ({count} 种)"))
    print(dim(f"  来源: {source}"))
    print(bold(f"{'=' * 60}"))


def _table(rows: list[list[str]], headers: list[str]):
    """简单表格打印。"""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            # 计算不含 ANSI 转义的实际宽度
            clean = cell
            while "\033[" in clean:
                start = clean.index("\033[")
                end = clean.index("m", start) + 1
                clean = clean[:start] + clean[end:]
            widths[i] = max(widths[i], len(clean))

    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    # header
    header_line = fmt.format(*headers)
    print(f"  {bold(header_line)}")
    print(f"  {'─' * sum(widths + [2 * (len(widths) - 1)])}")
    for row in rows:
        # 手动 pad（因为 ANSI 干扰 format）
        padded = []
        for i, cell in enumerate(row):
            clean = cell
            while "\033[" in clean:
                start = clean.index("\033[")
                end = clean.index("m", start) + 1
                clean = clean[:start] + clean[end:]
            pad = widths[i] - len(clean)
            padded.append(cell + " " * max(pad, 0))
        print(f"  {'  '.join(padded)}")


# ── 各注册中心展示 ────────────────────────────────────────────────────────────

def show_fields():
    from worksheets.field_types import FIELD_REGISTRY, FIELD_CATEGORIES

    _header("字段类型注册中心 (FIELD_REGISTRY)", len(FIELD_REGISTRY),
            "worksheets/field_types.py")

    # 按 category 分组展示
    cat_names = {
        "basic": "基础文本", "number": "数值", "select": "选择",
        "date": "日期时间", "contact": "联系方式", "people": "人员组织",
        "relation": "关联", "file": "文件", "location": "地理位置",
        "advanced": "高级/特殊", "layout": "布局（不存数据）",
    }
    for cat, type_names in FIELD_CATEGORIES.items():
        label = cat_names.get(cat, cat)
        print(f"\n  {cyan(f'[{label}]')} ({len(type_names)} 种)")
        rows = []
        for tn in type_names:
            spec = FIELD_REGISTRY[tn]
            flags = []
            if spec.get("requires_options"):
                flags.append(yellow("需选项"))
            if spec.get("requires_relation_target"):
                flags.append(yellow("需目标表"))
            if spec.get("force_not_required"):
                flags.append(dim("强制非必填"))
            if spec.get("can_be_title"):
                flags.append(green("可做标题"))
            rows.append([
                tn,
                str(spec["controlType"]),
                spec["name"],
                " ".join(flags) if flags else dim("-"),
            ])
        _table(rows, ["Key", "Type", "名称", "约束"])


def show_views():
    from views.view_types import VIEW_REGISTRY

    _header("视图类型注册中心 (VIEW_REGISTRY)", len(VIEW_REGISTRY),
            "views/view_types.py")

    rows = []
    for vt in sorted(VIEW_REGISTRY.keys()):
        spec = VIEW_REGISTRY[vt]
        verified = green("Yes") if spec.get("verified") else yellow("No")
        reqs = spec.get("requires_fields", [])
        req_str = ", ".join(reqs) if reqs else dim("-")
        rows.append([
            str(vt),
            spec["name"],
            spec.get("category", "-"),
            verified,
            req_str,
        ])
    _table(rows, ["viewType", "名称", "分类", "已验证", "字段要求"])


def show_charts():
    from charts import CHART_REGISTRY

    _header("图表类型注册中心 (CHART_REGISTRY)", len(CHART_REGISTRY),
            "charts/__init__.py + 子模块")

    rows = []
    for rt in sorted(CHART_REGISTRY.keys()):
        spec = CHART_REGISTRY[rt]
        verified = green("Yes") if spec.get("verified") else yellow("No")
        mod = spec.get("module", "").split(".")[-1]
        rows.append([
            str(rt),
            spec["name"],
            verified,
            mod,
            spec.get("doc", "")[:40],
        ])
    _table(rows, ["reportType", "名称", "已验证", "子模块", "说明"])


def show_planners():
    _header("规划师 (Planners)", 3, "planning/*.py")

    planners = [
        {
            "name": "工作表规划师",
            "file": "planning/worksheet_planner.py",
            "registry": "FIELD_REGISTRY (38 种字段)",
            "functions": "build_enhanced_prompt(), validate_worksheet_plan()",
            "output": "工作表名、字段、关联关系、创建顺序",
        },
        {
            "name": "视图规划师",
            "file": "planning/view_planner.py",
            "registry": "VIEW_REGISTRY (9 种视图)",
            "functions": "build_enhanced_prompt(), suggest_views(), validate_view_plan()",
            "output": "每个表的视图类型、名称、配置",
        },
        {
            "name": "图表规划师",
            "file": "planning/chart_planner.py",
            "registry": "CHART_REGISTRY (15 种图表)",
            "functions": "build_enhanced_prompt(), validate_enhanced_plan()",
            "output": "统计图表配置",
        },
    ]

    for p in planners:
        print(f"\n  {cyan(p['name'])}")
        print(f"    文件:     {p['file']}")
        print(f"    注册中心: {p['registry']}")
        print(f"    函数:     {p['functions']}")
        print(f"    输出:     {dim(p['output'])}")


def show_summary():
    """顶部汇总。"""
    print(bold("\n  HAP Auto Maker — 注册中心 & 规划师总览\n"))
    items = [
        ("字段类型", "FIELD_REGISTRY", "38", "worksheets/field_types.py"),
        ("视图类型", "VIEW_REGISTRY", "9", "views/view_types.py"),
        ("图表类型", "CHART_REGISTRY", "15", "charts/__init__.py"),
        ("规划师", "planning/*.py", "3", "planning/"),
    ]
    rows = [[n, r, c, f] for n, r, c, f in items]
    _table(rows, ["模块", "注册变量", "数量", "文件"])


# ── 主入口 ────────────────────────────────────────────────────────────────────

SECTIONS = {
    "fields": show_fields,
    "views": show_views,
    "charts": show_charts,
    "planners": show_planners,
}

def main():
    args = sys.argv[1:]

    if not args:
        show_summary()
        for fn in SECTIONS.values():
            fn()
        print()
        return

    for arg in args:
        key = arg.lower().strip()
        if key in SECTIONS:
            SECTIONS[key]()
        else:
            print(f"未知模块: {key}。可选: {', '.join(SECTIONS.keys())}")
    print()


if __name__ == "__main__":
    main()
