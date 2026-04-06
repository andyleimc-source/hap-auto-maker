"""
共用约束生成器 — 从注册中心提取元数据，供 AI prompt 和 plan 校验使用。

提供:
  - 图表类型约束（哪些类型可用、各类型的字段要求）
  - 字段分类工具（按 type 分组，方便 AI 选择合适字段）
"""

from __future__ import annotations
import sys
from pathlib import Path

# 确保能导入 charts/
_BASE = Path(__file__).resolve().parents[1]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))


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
        "xaxes_null_types": [10, 14, 15],  # 数值图、仪表盘、进度图不需要 xaxes
        "percent_types": [3, 6],         # 饼图、漏斗图建议 showPercent
        "dual_axis_type": 7,             # 需要 yreportType
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
    lines.append("  - 趋势分析 → 折线图(2)，showChartType=2 为面积/区域图")
    lines.append("  - 占比分析 → 饼图(3)，showChartType 区分饼/环")
    lines.append("  - 对比分析 → 柱图(1)，showChartType=2 为横向条形图")
    lines.append("  - 转化漏斗 → 漏斗图(6)")
    lines.append("  - KPI 数字 → 数值图(10)")
    lines.append("  - 排名 → 排行图(16)")
    lines.append("  - 多维对比 → 透视表/雷达图(8)")
    lines.append("  - 地理分布 → 行政区划图(9) 或 地图(17)")
    return "\n".join(lines)


# ─── 字段分类工具 ──────────────────────────────────────────────────────────────

# HAP 字段类型映射（38 种字段类型完整分类）
# type ID 来源：GetWorksheetControls API 实测（2026-04-03）
FIELD_TYPE_CATEGORIES = {
    # 文本类：单行文本、文本组合（文本公式）、自动编号、富文本
    "text": {2, 32, 33, 41},
    # 数值类：数值、金额、大写金额、公式（数值）、公式（日期）、评分
    "number": {6, 8, 25, 31, 38, 47},
    # 日期时间类：日期、日期时间、时间
    "date": {15, 16, 46},
    # 选择类：单选（平铺）、多选（标签）、下拉、检查框（布尔）、等级（星级）
    "select": {9, 10, 11, 36, 28},
    # 联系方式类：手机号、座机、邮箱、链接
    "contact": {3, 4, 5, 7},
    # 人员组织类：成员、部门、组织角色
    "user": {26, 27, 48},
    # 关联类：关联记录、他表字段、子表、级联选择、汇总
    "relation": {29, 30, 34, 35, 37},
    # 附件类：附件、签名
    "attachment": {14, 42},
    # 地理位置类：地区（省市区）、定位（GPS）
    "location": {24, 40},
    # 特殊功能类：二维码、嵌入外部页面
    "special": {43, 45},
    # 布局类（不存储数据）：分段标题、备注说明
    "layout": {22, 49},
}

SYSTEM_FIELDS = {"ctime", "utime", "ownerid", "caid", "record_count"}


def classify_fields(controls: list[dict]) -> dict[str, list[dict]]:
    """将字段按类型分类，返回 {category: [field_info]}。

    兼容 V3 API 字符串类型名（如 "Text", "SingleSelect"）和整数编号两种格式。
    """
    # V3 API 返回的字符串类型名 → 整数编号映射
    _STR_TO_INT: dict[str, int] = {
        "Text": 2, "Textarea": 3, "Phone": 3, "Number": 6, "Money": 8,
        "SingleSelect": 9, "MultipleSelect": 10, "Dropdown": 11,
        "Attachment": 14, "Date": 15, "DateTime": 16, "Time": 46,
        "Location": 19, "Area": 24, "Link": 21, "Email": 5,
        "Collaborator": 26, "Department": 27, "OrgRole": 48,
        "Relation": 29, "Lookup": 30, "SubTable": 34, "Cascade": 35, "Rollup": 37,
        "Checkbox": 36, "Rating": 28, "Score": 47, "Formula": 31,
        "DateFormula": 38, "AutoNumber": 33, "RichText": 41,
        "Signature": 42, "QRCode": 43, "Embed": 45, "Remark": 49,
        "TextCombine": 32, "Section": 22,
    }

    result: dict[str, list[dict]] = {cat: [] for cat in FIELD_TYPE_CATEGORIES}
    result["system"] = []
    result["other"] = []

    for f in controls:
        fid = str(f.get("controlId", "") or f.get("id", "")).strip()
        fname = str(f.get("controlName", "") or f.get("name", "")).strip()
        raw_type = f.get("type", 0) or f.get("controlType", 0) or 0
        # 支持字符串类型名（V3 API）和整数类型编号两种格式
        if isinstance(raw_type, str) and not raw_type.isdigit():
            ftype = _STR_TO_INT.get(raw_type, 0)
        else:
            try:
                ftype = int(raw_type)
            except (ValueError, TypeError):
                ftype = 0
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

    has_select = bool(classified_fields.get("select"))
    has_date = bool(classified_fields.get("date"))
    has_number = bool(classified_fields.get("number"))

    if has_select:
        suggestions.append({
            "reportType": 1, "reason": "有单选/下拉字段，适合做分类柱状图",
            "xaxes_field_category": "select",
        })
        suggestions.append({
            "reportType": 3, "reason": "有单选/下拉字段，适合做占比饼图",
            "xaxes_field_category": "select",
        })
        suggestions.append({
            "reportType": 6, "reason": "有单选/下拉字段（如阶段/状态），适合做转化漏斗图",
            "xaxes_field_category": "select",
        })
        suggestions.append({
            "reportType": 16, "reason": "有单选/下拉字段，适合做 TOP N 排行图",
            "xaxes_field_category": "select",
        })

    if has_date:
        suggestions.append({
            "reportType": 2, "reason": "有日期字段，适合做趋势折线图",
            "xaxes_field_category": "date",
        })

    if has_number:
        suggestions.append({
            "reportType": 10, "reason": "有数值字段，适合做 KPI 数值图",
            "xaxes_field_category": None,
        })
        suggestions.append({
            "reportType": 14, "reason": "有数值字段，适合做仪表盘（目标达成率）",
            "xaxes_field_category": None,
        })
        suggestions.append({
            "reportType": 15, "reason": "有数值字段，适合做进度图（完成进度）",
            "xaxes_field_category": None,
        })

    if has_number and has_date:
        suggestions.append({
            "reportType": 7, "reason": "有数值+日期字段，适合做双轴图（双指标趋势对比）",
            "xaxes_field_category": "date",
        })

    # 总是推荐一个记录数量的数值图
    suggestions.append({
        "reportType": 10, "reason": "通用：记录总数 KPI",
        "xaxes_field_category": None,
        "yaxis_controlId": "record_count",
    })

    # 总是推荐透视表（多维交叉分析）
    suggestions.append({
        "reportType": 8, "reason": "通用：多维交叉分析透视表",
        "xaxes_field_category": None,
    })

    return suggestions
