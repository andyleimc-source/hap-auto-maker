#!/usr/bin/env python3
"""
抓取 HAP 所有字段类型的完整 API 参数。

在临时工作表上逐个创建各种类型的字段，然后通过 GetWorksheetControls
获取前端存储的完整字段结构（包括 advancedSetting、enumDefault 等）。
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "hap"))
from auth_retry import hap_web_post

WORKSHEET_ID = "69d0fb3c315b3a65f499df50"  # _tmp_字段参数抓取
WEB_BASE = "https://www.mingdao.com/api/Worksheet"


def get_controls_and_version() -> tuple[list, int]:
    """获取当前字段列表和 version。"""
    resp = hap_web_post(f"{WEB_BASE}/GetWorksheetControls",
                        json={"worksheetId": WORKSHEET_ID}, timeout=30)
    body = resp.json()
    if body.get("data", {}).get("code") != 1:
        print(f"  ⚠ GetControls error: {body}")
        return [], 0
    data = body["data"]["data"]
    return data.get("controls", []), data.get("version", 0)


def add_field(field_def: dict) -> bool:
    """添加单个字段，自动获取 version。"""
    controls, version = get_controls_and_version()
    if not controls and version == 0:
        return False
    controls.append(field_def)
    resp = hap_web_post(f"{WEB_BASE}/SaveWorksheetControls",
                        json={"version": version, "sourceId": WORKSHEET_ID, "controls": controls},
                        timeout=30)
    body = resp.json()
    code = body.get("data", {}).get("code") if isinstance(body.get("data"), dict) else None
    if code and code != 1:
        print(f"  ✗ code={code}: {body['data'].get('msg')}")
        return False
    return code == 1


# 定义所有字段类型
FIELD_DEFS = [
    # ── 基础文本 ──
    {"controlId": "", "controlName": "F02_文本", "type": 2,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F41_富文本", "type": 41,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F03_手机", "type": 3,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F04_座机", "type": 4,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F05_邮箱", "type": 5,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F07_链接", "type": 7,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 数值 ──
    {"controlId": "", "controlName": "F06_数值", "type": 6, "dot": 2,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F08_金额", "type": 8, "dot": 2, "unit": "¥",
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F25_大写金额", "type": 25,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 日期时间 ──
    {"controlId": "", "controlName": "F15_日期", "type": 15,
     "advancedSetting": {"sorttype": "zh", "showtype": "3"}},
    {"controlId": "", "controlName": "F16_日期时间", "type": 16,
     "advancedSetting": {"sorttype": "zh", "showtype": "1"}},
    {"controlId": "", "controlName": "F46_时间", "type": 46,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 选择 ──
    {"controlId": "", "controlName": "F09_单选", "type": 9,
     "options": [
         {"key": "a001", "value": "选项A", "index": 1, "color": "#2196F3"},
         {"key": "a002", "value": "选项B", "index": 2, "color": "#4CAF50"},
         {"key": "a003", "value": "选项C", "index": 3, "color": "#FF9800"},
     ],
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F10_多选", "type": 10,
     "options": [
         {"key": "b001", "value": "标签A", "index": 1, "color": "#2196F3"},
         {"key": "b002", "value": "标签B", "index": 2, "color": "#4CAF50"},
         {"key": "b003", "value": "标签C", "index": 3, "color": "#FF9800"},
     ],
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F11_下拉", "type": 11,
     "options": [
         {"key": "c001", "value": "下拉A", "index": 1},
         {"key": "c002", "value": "下拉B", "index": 2},
         {"key": "c003", "value": "下拉C", "index": 3},
     ],
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F36_检查框", "type": 36,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F28_等级", "type": 28,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F47_评分", "type": 47,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 人员组织 ──
    {"controlId": "", "controlName": "F26_成员", "type": 26,
     "advancedSetting": {"sorttype": "zh", "usertype": "1"}},
    {"controlId": "", "controlName": "F27_部门", "type": 27,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F48_组织角色", "type": 48,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 地理位置 ──
    {"controlId": "", "controlName": "F24_地区", "type": 24, "enumDefault2": 3,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F40_定位", "type": 40,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 文件 ──
    {"controlId": "", "controlName": "F14_附件", "type": 14,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F42_签名", "type": 42,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 布局 ──
    {"controlId": "", "controlName": "F22_分段", "type": 22,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F49_备注", "type": 49,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 特殊 ──
    {"controlId": "", "controlName": "F33_自动编号", "type": 33, "strDefault": "increase",
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F43_二维码", "type": 43,
     "advancedSetting": {"sorttype": "zh"}},
    {"controlId": "", "controlName": "F45_嵌入", "type": 45,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 公式 ──
    {"controlId": "", "controlName": "F31_公式数值", "type": 31,
     "advancedSetting": {"sorttype": "zh", "nullzero": "0"}},
    {"controlId": "", "controlName": "F32_文本组合", "type": 32,
     "advancedSetting": {"sorttype": "zh", "analysislink": "1"}},
    {"controlId": "", "controlName": "F38_公式日期", "type": 38,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 关联（自引用） ──
    {"controlId": "", "controlName": "F29_关联记录", "type": 29,
     "dataSource": WORKSHEET_ID, "enumDefault": 2,
     "advancedSetting": {"sorttype": "zh", "showtype": "2", "allowlink": "1"}},

    # ── 子表 ──
    {"controlId": "", "controlName": "F34_子表", "type": 34,
     "advancedSetting": {"sorttype": "zh"}},

    # ── 级联 ──
    {"controlId": "", "controlName": "F35_级联", "type": 35,
     "advancedSetting": {"sorttype": "zh"}},
]


def main():
    print(f"=== 开始创建 {len(FIELD_DEFS)} 个字段 ===\n")

    success_count = 0
    for i, fdef in enumerate(FIELD_DEFS, 1):
        name = fdef["controlName"]
        ftype = fdef["type"]
        print(f"[{i}/{len(FIELD_DEFS)}] 创建 {name} (type={ftype})...", end=" ", flush=True)
        ok = add_field(fdef)
        print("✓" if ok else "✗")
        if ok:
            success_count += 1
        time.sleep(0.5)

    print(f"\n成功创建 {success_count}/{len(FIELD_DEFS)} 个字段")

    # 创建依赖关联字段的 他表字段(30) 和 汇总(37)
    controls, version = get_controls_and_version()
    rel_field = next((c for c in controls if c.get("controlName") == "F29_关联记录"), None)

    if rel_field:
        rel_id = rel_field["controlId"]
        print(f"\n关联字段 ID: {rel_id}")

        print(f"[+1] 创建 F30_他表字段 (type=30)...", end=" ", flush=True)
        ok = add_field({
            "controlId": "", "controlName": "F30_他表字段", "type": 30,
            "dataSource": rel_id,
            "advancedSetting": {"sorttype": "zh"}
        })
        print("✓" if ok else "✗")
        time.sleep(0.5)

        print(f"[+2] 创建 F37_汇总 (type=37)...", end=" ", flush=True)
        ok = add_field({
            "controlId": "", "controlName": "F37_汇总", "type": 37,
            "dataSource": rel_id,
            "advancedSetting": {"sorttype": "zh"}
        })
        print("✓" if ok else "✗")
    else:
        print("\n⚠ 未找到关联字段，跳过他表字段和汇总")

    # 最终获取完整字段结构
    print("\n=== 获取完整字段结构 ===")
    controls, version = get_controls_and_version()

    user_fields = [c for c in controls if c.get("controlName", "").startswith("F")]
    print(f"共 {len(user_fields)} 个用户字段（version={version}）")

    out_dir = Path(__file__).parent.parent / "data" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 保存精简版
    output = {}
    for c in user_fields:
        key = c["controlName"]
        output[key] = {k: v for k, v in c.items() if v is not None and v != "" and v != 0 and v != [] and v != {}}

    out_path = out_dir / "field_params_captured.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 已保存到 {out_path}")

    # 保存完整原始版
    raw_path = out_dir / "field_params_raw.json"
    raw_output = {c["controlName"]: c for c in user_fields}
    raw_path.write_text(json.dumps(raw_output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 原始数据已保存到 {raw_path}")


if __name__ == "__main__":
    main()
