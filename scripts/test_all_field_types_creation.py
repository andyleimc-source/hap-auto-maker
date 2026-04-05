#!/usr/bin/env python3
"""
验证脚本：通过 create_worksheets_from_plan.py 的流程创建包含全部字段类型的工作表。
模拟完整的 Phase 1 + Phase 1.5 流程。
"""

import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))

from auth_retry import hap_web_post
from worksheets.field_types import FIELD_REGISTRY, FIELD_TYPE_MAP
from create_worksheets_from_plan import (
    _CREATE_WS_SUPPORTED_TYPES,
    _build_web_api_field,
    _add_deferred_fields_via_web_api,
    build_field_payload,
    parse_select_options_from_field,
    create_worksheet,
    to_required,
)
from hap_api_client import HapClient

# 用已有的应用
APP_ID = "bee6bcca-9943-4192-be76-86119476b4b5"


def main():
    client = HapClient()

    # 构造全部 38 种字段（除 Relation/OtherTableField/Rollup 需要依赖其他表/字段）
    all_fields = [
        {"name": "标题", "type": "Text"},
        {"name": "富文本描述", "type": "RichText"},
        {"name": "手机号", "type": "Phone"},
        {"name": "座机电话", "type": "Landline"},
        {"name": "电子邮箱", "type": "Email"},
        {"name": "网站链接", "type": "Link"},
        {"name": "数量", "type": "Number", "dot": 0},
        {"name": "单价", "type": "Money", "unit": "¥"},
        {"name": "大写总价", "type": "MoneyCapital"},
        {"name": "入职日期", "type": "Date"},
        {"name": "面试时间", "type": "DateTime"},
        {"name": "签到时间", "type": "Time"},
        {"name": "状态", "type": "SingleSelect", "option_values": ["待处理", "进行中", "已完成", "已取消"]},
        {"name": "标签", "type": "MultipleSelect", "option_values": ["紧急", "重要", "一般"]},
        {"name": "类别", "type": "Dropdown", "option_values": ["A类", "B类", "C类"]},
        {"name": "是否完成", "type": "Checkbox"},
        {"name": "优先级", "type": "Rating"},
        {"name": "满意度", "type": "Score"},
        {"name": "负责人", "type": "Collaborator"},
        # Department 公开 API 不支持，走 deferred
        {"name": "所属部门", "type": "Department"},
        {"name": "角色", "type": "OrgRole"},
        {"name": "所在地区", "type": "Area"},
        {"name": "签到定位", "type": "Location"},
        {"name": "附件", "type": "Attachment"},
        {"name": "签名", "type": "Signature"},
        {"name": "分段标题", "type": "Section"},
        {"name": "填写说明", "type": "Remark"},
        {"name": "编号", "type": "AutoNumber"},
        {"name": "二维码", "type": "QRCode"},
        {"name": "嵌入页面", "type": "Embed"},
        {"name": "合计公式", "type": "Formula"},
        {"name": "全名拼接", "type": "TextCombine"},
        {"name": "剩余天数", "type": "FormulaDate"},
        {"name": "子表明细", "type": "SubTable"},
        {"name": "级联分类", "type": "Cascade"},
    ]

    # 分类
    normal_fields = []
    deferred_fields = []
    title_set = False

    for fld in all_fields:
        ftype = fld["type"]
        if ftype in _CREATE_WS_SUPPORTED_TYPES:
            is_title = not title_set and ftype == "Text"
            normal_fields.append(build_field_payload(fld, is_first_text_title=is_title))
            if is_title:
                title_set = True
        else:
            deferred_fields.append(fld)

    print(f"=== 全量字段创建验证 ===")
    print(f"  总字段数: {len(all_fields)}")
    print(f"  Phase 1 (公开API): {len(normal_fields)} 个 — {[f['name'] for f in normal_fields]}")
    print(f"  Phase 1.5 (私有API): {len(deferred_fields)} 个 — {[f['name'] for f in deferred_fields]}")

    # Phase 1: 用公开 API 创建工作表 + 白名单内字段
    auth_path = BASE_DIR / "data" / "outputs" / "app_authorizations"
    auth_files = sorted(auth_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not auth_files:
        raise FileNotFoundError(f"找不到授权文件: {auth_path}")

    auth_data = json.loads(auth_files[0].read_text())
    rows = auth_data.get("data", [])
    app_auth = next((r for r in rows if r.get("appId") == APP_ID), rows[0] if rows else None)
    if not app_auth:
        raise ValueError("找不到应用授权")

    headers = {
        "Content-Type": "application/json",
        "HAP-Appkey": app_auth["appKey"],
        "HAP-Sign": app_auth["sign"],
    }

    ws_name = f"_验证全量字段_{int(time.time())}"
    print(f"\n[Phase 1] 创建工作表 '{ws_name}' + {len(normal_fields)} 个基础字段...")

    try:
        result = create_worksheet("https://api.mingdao.com", headers, ws_name, normal_fields)
        ws_id = result.get("data", {}).get("worksheetId")
        if not ws_id:
            raise RuntimeError(f"未返回 worksheetId: {result}")
        print(f"  ✓ 工作表创建成功: {ws_id}")
    except Exception as e:
        print(f"  ✗ Phase 1 失败: {e}")
        return

    # Phase 1.5: 用私有 Web API 补加 deferred 字段
    if deferred_fields:
        print(f"\n[Phase 1.5] 通过私有 API 补加 {len(deferred_fields)} 个 deferred 字段...")
        try:
            result = _add_deferred_fields_via_web_api(ws_id, deferred_fields)
            print(f"  ✓ 补加成功: {result}")
        except Exception as e:
            print(f"  ✗ Phase 1.5 失败: {e}")
            return

    # 验证：获取最终字段列表
    print(f"\n[验证] 获取最终字段结构...")
    resp = hap_web_post(
        "https://www.mingdao.com/api/Worksheet/GetWorksheetControls",
        json={"worksheetId": ws_id}, timeout=30
    )
    body = resp.json()
    controls = body.get("data", {}).get("data", {}).get("controls", [])

    # 过滤掉系统字段
    system_ids = {"rowid", "ownerid", "caid", "ctime", "utime", "uaid",
                  "wfname", "wfstatus", "wfcuaids", "wfrtime", "wfcotime",
                  "wfdtime", "wfftime", "wfcaid", "wfctime"}
    user_fields = [c for c in controls if c["controlId"] not in system_ids]

    print(f"\n=== 验证结果 ===")
    print(f"  目标: {len(all_fields)} 种字段")
    print(f"  实际创建: {len(user_fields)} 个用户字段")

    # 按 type 统计
    type_counts = {}
    for c in user_fields:
        t = c["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"  字段类型分布:")
    for c in user_fields:
        t = c["type"]
        name = c["controlName"]
        as_keys = list(c.get("advancedSetting", {}).keys())
        print(f"    type={t:2d} | {name} | advancedSetting: {as_keys}")

    expected = len(all_fields)
    actual = len(user_fields)
    if actual >= expected:
        print(f"\n  ✓✓✓ 全部 {expected} 种字段创建成功！")
    else:
        print(f"\n  ✗ 只创建了 {actual}/{expected} 种字段")

    print(f"\n  工作表 ID: {ws_id}")
    print(f"  URL: https://www.mingdao.com/worksheet/{ws_id}")


if __name__ == "__main__":
    main()
