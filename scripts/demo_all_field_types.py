#!/usr/bin/env python3
"""在 CRM 应用中创建一个包含所有字段类型的工作表。"""

from __future__ import annotations
import sys, json, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))
import auth_retry

AUTH_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
APP_ID = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"
PROJECT_ID = "faa2f6b1-f706-4084-9a8d-50616817f890"
SECTION_ID = "69ce832640691821042c6e79"  # 基础设置

ADD_WS_URL = "https://www.mingdao.com/api/AppManagement/AddWorkSheet"
GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
SAVE_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetControls"


def web_post(url, body, referer=""):
    ref = referer or f"https://www.mingdao.com/app/{APP_ID}"
    resp = auth_retry.hap_web_post(url, AUTH_PATH, referer=ref, json=body, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:200], "status_code": resp.status_code}


def main():
    print("=" * 60)
    print("创建工作表：全字段类型演示")
    print("=" * 60)

    # Step 1: 创建工作表
    print("\n[Step 1] 创建工作表...")
    resp = web_post(ADD_WS_URL, {
        "appId": APP_ID,
        "appSectionId": SECTION_ID,
        "name": "全字段类型演示",
        "remark": "",
        "iconColor": "#FF9800",
        "projectId": PROJECT_ID,
        "icon": "table",
        "iconUrl": "https://fp1.mingdaoyun.cn/customIcon/table.svg",
        "type": 0,
        "createType": 0,
    })
    ws_id = ""
    if resp.get("state") == 1:
        d = resp.get("data", {})
        ws_id = str(d.get("worksheetId", "") or d.get("workSheetId", "") or d.get("pageId", "")).strip()
    if not ws_id:
        print(f"  ✗ 创建失败: {resp}")
        return
    print(f"  ✓ worksheetId={ws_id}")

    referer = f"https://www.mingdao.com/worksheet/field/edit?sourceId={ws_id}"
    time.sleep(0.5)

    # Step 2: 获取当前字段（新表默认有标题字段）
    print("\n[Step 2] 获取当前字段...")
    ctrl_resp = web_post(GET_CONTROLS_URL, {"worksheetId": ws_id, "appId": APP_ID}, referer)
    data = ctrl_resp.get("data", {}).get("data", ctrl_resp.get("data", {}))
    version = int(data.get("version", 0))
    controls = data.get("controls", [])
    print(f"  version={version}, 字段数={len(controls)}")

    # Step 3: 逐批添加字段（每次 3-4 个，避免请求过大）
    # 定义所有要创建的字段（排除布局类和需要特殊依赖的类型）
    field_batches = [
        # Batch 1: 基础文本+数值
        [
            {"controlName": "富文本描述", "type": 41},
            {"controlName": "自动编号", "type": 33},
            {"controlName": "数值字段", "type": 6, "dot": 2},
            {"controlName": "金额字段", "type": 8, "dot": 2, "unit": "¥"},
        ],
        # Batch 2: 选择类
        [
            {"controlName": "单选状态", "type": 9, "options": [
                {"key": "a1", "value": "待处理", "index": 0, "isDeleted": False, "color": "#2196F3"},
                {"key": "a2", "value": "进行中", "index": 1, "isDeleted": False, "color": "#FF9800"},
                {"key": "a3", "value": "已完成", "index": 2, "isDeleted": False, "color": "#4CAF50"},
                {"key": "a4", "value": "已取消", "index": 3, "isDeleted": False, "color": "#F44336"},
            ]},
            {"controlName": "多选标签", "type": 10, "options": [
                {"key": "b1", "value": "紧急", "index": 0, "isDeleted": False, "color": "#F44336"},
                {"key": "b2", "value": "重要", "index": 1, "isDeleted": False, "color": "#FF9800"},
                {"key": "b3", "value": "普通", "index": 2, "isDeleted": False, "color": "#2196F3"},
            ]},
            {"controlName": "下拉选择", "type": 11, "options": [
                {"key": "c1", "value": "选项A", "index": 0, "isDeleted": False, "color": "#2196F3"},
                {"key": "c2", "value": "选项B", "index": 1, "isDeleted": False, "color": "#4CAF50"},
                {"key": "c3", "value": "选项C", "index": 2, "isDeleted": False, "color": "#FF9800"},
            ]},
            {"controlName": "检查框", "type": 36},
        ],
        # Batch 3: 日期+评分
        [
            {"controlName": "日期字段", "type": 15},
            {"controlName": "日期时间", "type": 16},
            {"controlName": "时间字段", "type": 46},
            {"controlName": "等级评分", "type": 28},
        ],
        # Batch 4: 联系方式
        [
            {"controlName": "电话号码", "type": 3},
            {"controlName": "邮箱地址", "type": 5},
            {"controlName": "链接地址", "type": 7},
        ],
        # Batch 5: 人员+文件
        [
            {"controlName": "负责人", "type": 26},
            {"controlName": "部门", "type": 27},
            {"controlName": "附件", "type": 14},
        ],
        # Batch 6: 地理+高级
        [
            {"controlName": "所在地区", "type": 24},
            {"controlName": "定位", "type": 40},
            {"controlName": "签名", "type": 42},
        ],
        # Batch 7: 更多
        [
            {"controlName": "分段标题", "type": 22},
            {"controlName": "嵌入页面", "type": 45},
        ],
    ]

    total_added = 0
    for batch_idx, batch in enumerate(field_batches, 1):
        new_fields = []
        for f in batch:
            field = {
                "controlId": "",
                "controlName": f["controlName"],
                "type": f["type"],
                "attribute": 0,
                "row": len(controls) + len(new_fields),
                "col": 0,
                "size": 12,
                "hint": "",
                "default": "",
                "required": False,
                "unique": False,
                "encryId": "",
                "showControls": [],
                "advancedSetting": {},
            }
            if "options" in f:
                field["options"] = f["options"]
            if "dot" in f:
                field["dot"] = f["dot"]
            if "unit" in f:
                field["unit"] = f["unit"]
            new_fields.append(field)

        all_controls = controls + new_fields
        save_resp = web_post(SAVE_CONTROLS_URL, {
            "version": version,
            "sourceId": ws_id,
            "controls": all_controls,
        }, referer)

        inner = save_resp.get("data", {}).get("data", save_resp.get("data", {}))
        if isinstance(inner, dict) and inner.get("version"):
            version = int(inner["version"])
            controls = inner.get("controls", all_controls)
            added = len([f for f in batch])
            total_added += added
            names = ", ".join(f["controlName"] for f in batch)
            print(f"  ✓ Batch {batch_idx}: {names}")
        else:
            print(f"  ✗ Batch {batch_idx} 失败: {str(save_resp)[:200]}")

        time.sleep(0.3)

    print(f"\n共添加 {total_added} 个字段")
    print(f"工作表链接: https://www.mingdao.com/app/{APP_ID}/{SECTION_ID}/{ws_id}")
    return ws_id


if __name__ == "__main__":
    main()
