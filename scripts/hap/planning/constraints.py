"""
共用约束生成器 — 从注册中心提取元数据，供 AI prompt 和 plan 校验使用。

提供:
  - 图表类型约束（哪些类型可用、各类型的字段要求）
  - 工作流节点约束（哪些类型已验证、各类型的配置要求）
  - 字段分类工具（按 type 分组，方便 AI 选择合适字段）
"""

from __future__ import annotations
import sys
from pathlib import Path

# 确保能导入 charts/ 和 nodes/
_BASE = Path(__file__).resolve().parents[1]
_WF_BASE = Path(__file__).resolve().parents[3] / "workflow"
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))
if str(_WF_BASE) not in sys.path:
    sys.path.insert(0, str(_WF_BASE))


# ─── 图表约束 ─────────────────────────────────────────────────────────────────

def get_chart_constraints() -> dict:
    """从 charts/ 注册中心提取图表类型约束。"""
    from charts import CHART_REGISTRY

    types = {}
    for rt, spec in sorted(CHART_REGISTRY.items()):
        types[rt] = {
            "name": spec["name"],
            "verified": spec.get("verified", False),
            "doc": spec.get("doc", ""),
            "module": spec.get("module", "").split(".")[-1],
        }

    return {
        "total_types": len(types),
        "verified_types": [rt for rt, s in types.items() if s["verified"]],
        "types": types,
        "xaxes_null_types": [10, 12],  # 数值图、进度图不需要 xaxes
        "percent_types": [3, 4, 5],     # 饼图、环形图、漏斗图建议 showPercent
        "dual_axis_type": 8,            # 需要 yreportType
    }


def build_chart_type_prompt_section() -> str:
    """生成 AI prompt 中的图表类型说明段落。"""
    c = get_chart_constraints()
    lines = ["可用的图表类型（reportType）："]
    for rt, spec in sorted(c["types"].items()):
        v = "✓已验证" if spec["verified"] else ""
        doc = spec["doc"]
        lines.append(f"  {rt:2d}. {spec['name']} {v} — {doc}")
    lines.append("")
    lines.append("选型指南：")
    lines.append("  - 趋势分析 → 折线图(2) 或 区域图(11)，xaxes 用日期字段")
    lines.append("  - 占比分析 → 饼图(3) 或 环形图(4)")
    lines.append("  - 对比分析 → 柱状图(1) 或 条形图(7)")
    lines.append("  - 转化漏斗 → 漏斗图(5)")
    lines.append("  - KPI 数字 → 数值图(10)，xaxes.controlId=null")
    lines.append("  - 排名 → 排行图(15)")
    lines.append("  - 多维对比 → 雷达图(6)")
    return "\n".join(lines)


# ─── 工作流节点约束 ────────────────────────────────────────────────────────────

def get_node_constraints() -> dict:
    """从 nodes/ 注册中心提取工作流节点约束。"""
    from nodes import NODE_REGISTRY

    types = {}
    for nt, spec in NODE_REGISTRY.items():
        types[nt] = {
            "name": spec["name"],
            "typeId": spec["typeId"],
            "actionId": spec.get("actionId"),
            "verified": spec.get("verified", False),
            "doc": spec.get("doc", ""),
        }

    return {
        "total_types": len(types),
        "verified_types": [nt for nt, s in types.items() if s["verified"]],
        "types": types,
        "skip_savenode": ["api_request", "code_block", "subprocess"],
        "sendcontent_types": ["notify", "push", "copy"],
        "content_types": ["sms", "email"],
    }


def build_node_type_prompt_section() -> str:
    """生成 AI prompt 中的节点类型说明段落。"""
    c = get_node_constraints()
    lines = ["可用的工作流节点类型："]
    lines.append("")
    lines.append("📌 数据操作节点（需要 target_worksheet_id + fields）：")
    lines.append("  - update_record — 更新记录（1~3 个字段）")
    lines.append("  - add_record — 新增记录（需所有可操作字段）")
    lines.append("  - delete_record — 删除记录（fields 为空）")
    lines.append("")
    lines.append("📌 流程控制节点：")
    for nt in ["delay_duration", "approval"]:
        spec = c["types"].get(nt, {})
        v = "✓" if spec.get("verified") else ""
        lines.append(f"  - {nt} — {spec.get('name', '')} {v}")
    lines.append("  ⚠ branch（分支）当前版本不支持自动配置，禁止使用")
    lines.append("")
    lines.append("📌 通知节点（需要 content）：")
    for nt in ["notify", "copy"]:
        spec = c["types"].get(nt, {})
        v = "✓" if spec.get("verified") else ""
        lines.append(f"  - {nt} — {spec.get('name', '')} {v}")
    lines.append("")
    lines.append("📌 运算节点：")
    for nt in ["calc", "aggregate"]:
        spec = c["types"].get(nt, {})
        v = "✓" if spec.get("verified") else ""
        lines.append(f"  - {nt} — {spec.get('name', '')} {v}")
    lines.append("")
    lines.append("关键规则：")
    lines.append("  - 单选字段(type=9/11) fieldValue 必须用完整 UUID key，不能截断")
    lines.append("  - 通知/抄送的内容字段是 sendContent（不是 content）")
    lines.append("  - 禁止使用 branch 节点")
    lines.append("  - 每个工作流 3~5 个节点，至少 1 个跨表")
    return "\n".join(lines)


# ─── 字段分类工具 ──────────────────────────────────────────────────────────────

# HAP 字段类型映射
FIELD_TYPE_CATEGORIES = {
    "text": {2, 32, 33},        # 文本、富文本、自动编号
    "number": {6, 8, 31},       # 数字、金额、公式数值
    "date": {15, 16},           # 日期、日期时间
    "select": {9, 10, 11},      # 单选、多选、下拉
    "user": {26},               # 成员
    "relation": {29},           # 关联
    "attachment": {14},         # 附件
    "formula": {31, 38},        # 公式、汇总
}

SYSTEM_FIELDS = {"ctime", "utime", "ownerid", "caid", "record_count"}


def classify_fields(controls: list[dict]) -> dict[str, list[dict]]:
    """将字段按类型分类，返回 {category: [field_info]}。"""
    result: dict[str, list[dict]] = {cat: [] for cat in FIELD_TYPE_CATEGORIES}
    result["system"] = []
    result["other"] = []

    for f in controls:
        fid = str(f.get("controlId", "") or f.get("id", "")).strip()
        fname = str(f.get("controlName", "") or f.get("name", "")).strip()
        ftype = int(f.get("type", 0) or f.get("controlType", 0) or 0)
        is_system = bool(f.get("isSystem", False))

        info = {"id": fid, "name": fname, "type": ftype}
        if f.get("options"):
            info["options"] = [{"key": o["key"], "value": o["value"]} for o in f["options"]]

        if is_system or fid in SYSTEM_FIELDS:
            result["system"].append(info)
            continue

        placed = False
        for cat, type_set in FIELD_TYPE_CATEGORIES.items():
            if ftype in type_set:
                result[cat].append(info)
                placed = True
                break
        if not placed:
            result["other"].append(info)

    return result


def suggest_chart_types(classified_fields: dict[str, list[dict]]) -> list[dict]:
    """根据字段分类推荐适合的图表类型。"""
    suggestions = []

    if classified_fields.get("select"):
        suggestions.append({
            "reportType": 1, "reason": "有单选/下拉字段，适合做分类柱状图",
            "xaxes_field_category": "select",
        })
        suggestions.append({
            "reportType": 3, "reason": "有单选/下拉字段，适合做占比饼图",
            "xaxes_field_category": "select",
        })

    if classified_fields.get("date"):
        suggestions.append({
            "reportType": 2, "reason": "有日期字段，适合做趋势折线图",
            "xaxes_field_category": "date",
        })

    if classified_fields.get("number"):
        suggestions.append({
            "reportType": 10, "reason": "有数值字段，适合做 KPI 数值图",
            "xaxes_field_category": None,
        })

    # 总是推荐一个记录数量的数值图
    suggestions.append({
        "reportType": 10, "reason": "通用：记录总数 KPI",
        "xaxes_field_category": None,
        "yaxis_controlId": "record_count",
    })

    return suggestions
