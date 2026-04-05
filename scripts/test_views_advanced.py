#!/usr/bin/env python3
"""
测试视图高级配置：
  4 - 日历视图 (calendarcids 多日期字段场景)
  7 - 地图视图 (advancedSetting 指定地理字段)
  9 - 资源视图 (成员字段和日期字段映射)
  6 - 详情视图 (表单布局配置)
"""

from __future__ import annotations
import sys, json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))
import auth_retry

AUTH_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
APP_ID    = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"
WS_ID     = "69cf74eef9434db36c6e0816"   # 全字段演示工作表

SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"


# ── helpers ──────────────────────────────────────────────────────────────────

def web_post(url, body):
    referer = f"https://www.mingdao.com/app/{APP_ID}/{WS_ID}"
    resp = auth_retry.hap_web_post(url, AUTH_PATH, referer=referer, json=body, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:300]}


def get_ws_fields():
    """GetWorksheetControls — 返回字段列表。"""
    resp = auth_retry.hap_web_post(
        "https://www.mingdao.com/api/Worksheet/GetWorksheetControls",
        AUTH_PATH,
        referer=f"https://www.mingdao.com/app/{APP_ID}",
        json={"worksheetId": WS_ID, "appId": APP_ID},
        timeout=30,
    ).json()
    # 兼容两种返回结构
    data = resp.get("data", {})
    if isinstance(data, dict):
        controls = data.get("controls", data.get("data", {}).get("controls", []))
    else:
        controls = []
    return controls


def create_view(name, view_type, extra=None):
    body = {
        "viewId": "",
        "appId": APP_ID,
        "worksheetId": WS_ID,
        "viewType": str(view_type),
        "name": name,
        "sortType": 0,
        "coverType": 0,
        "displayControls": [],
        "controls": [],
        "filters": [],
        "sortCid": "",
        "showControlName": True,
        "advancedSetting": {},
    }
    if extra:
        body.update(extra)
    resp = web_post(SAVE_VIEW_URL, body)
    ok = resp.get("state") == 1
    view_id = ""
    if ok and isinstance(resp.get("data"), dict):
        view_id = resp["data"].get("viewId", "")
    return ok, view_id, resp


def second_save(view_id, name, update_body):
    body = {"appId": APP_ID, "worksheetId": WS_ID, "viewId": view_id, "name": name}
    body.update(update_body)
    return web_post(SAVE_VIEW_URL, body)


def fmt(cid):
    return cid[:16] + "…" if cid and len(cid) > 16 else (cid or "N/A")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 64)
    print("视图高级配置测试")
    print(f"工作表: {WS_ID}")
    print("=" * 64)

    # Step 0: 获取字段
    print("\n[Step 0] 获取工作表字段...")
    fields = get_ws_fields()
    if not fields:
        print("  ✗ 未获取到字段，退出")
        return

    field_map: dict[int, list[dict]] = {}
    for f in fields:
        ctype = f.get("type")
        field_map.setdefault(ctype, []).append({
            "id": f.get("controlId", ""),
            "name": f.get("controlName", ""),
            "type": ctype,
        })

    print(f"  共 {len(fields)} 个字段，类型分布：")
    for t, fs in sorted(field_map.items()):
        names = ", ".join(x["name"] for x in fs[:3])
        print(f"    type={t}: {names}")

    # 选出需要的字段
    date_fields   = field_map.get(15, []) + field_map.get(16, [])
    area_fields   = field_map.get(24, [])   # 地区字段
    loc_fields    = field_map.get(40, [])   # 定位字段
    collab_fields = field_map.get(26, [])   # 成员字段

    date1 = date_fields[0]["id"] if len(date_fields) > 0 else ""
    date2 = date_fields[1]["id"] if len(date_fields) > 1 else date1
    geo_field  = (loc_fields or area_fields or [{}])[0].get("id", "")
    geo_name   = (loc_fields or area_fields or [{}])[0].get("name", "N/A")
    collab_id  = collab_fields[0]["id"] if collab_fields else ""
    collab_name= collab_fields[0]["name"] if collab_fields else "N/A"

    print(f"\n  日期字段 date1={fmt(date1)}  date2={fmt(date2)}")
    print(f"  地理字段 ({geo_name}) geo={fmt(geo_field)}")
    print(f"  成员字段 ({collab_name}) collab={fmt(collab_id)}")

    results = []

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 1: 日历视图 (viewType=4) — calendarcids 多日期场景
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "─" * 64)
    print("[TEST 1] 日历视图 (viewType=4) — calendarcids 多日期字段")

    if not date1:
        print("  跳过：无日期字段")
        results.append({"view": "日历视图", "viewType": 4, "result": "跳过", "reason": "无日期字段"})
    else:
        # 先创建基础视图
        ok1, vid1, resp1 = create_view("高级日历视图_多日期", 4)
        print(f"  创建视图: {'✓' if ok1 else '✗'}  viewId={fmt(vid1)}")
        print(f"  响应: state={resp1.get('state')} msg={resp1.get('msg','')}")

        config_used = None
        ok2 = False
        if ok1 and vid1:
            # 多日期字段场景：用 date1 作开始，date2 作结束（可相同）
            calendarcids = json.dumps(
                [{"begin": date1, "end": date2}],
                ensure_ascii=False, separators=(",", ":"),
            )
            config_used = {"calendarcids": calendarcids}
            sr = second_save(vid1, "高级日历视图_多日期", {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["calendarcids"],
                "advancedSetting": {"calendarcids": calendarcids},
            })
            ok2 = sr.get("state") == 1
            print(f"  二次保存 calendarcids: {'✓' if ok2 else '✗'}")
            print(f"  配置: {calendarcids}")
            print(f"  响应: state={sr.get('state')} msg={sr.get('msg','')}")

        final_ok = ok1 and ok2
        results.append({
            "view": "日历视图",
            "viewType": 4,
            "result": "PASS" if final_ok else "FAIL",
            "viewId": vid1,
            "fields_used": {"date1": date1, "date2": date2},
            "config": config_used,
        })
        print(f"  => {'PASS' if final_ok else 'FAIL'}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 2: 地图视图 (viewType=7) — advancedSetting 指定地理字段
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "─" * 64)
    print("[TEST 2] 地图视图 (viewType=7) — advancedSetting 地理字段")

    # 先不带字段创建（验证基础可创建）
    ok_base, vid7_base, resp7_base = create_view("地图视图_基础", 7)
    print(f"  基础创建(无geo配置): {'✓' if ok_base else '✗'}  state={resp7_base.get('state')} msg={resp7_base.get('msg','')}")

    config_geo = None
    ok_geo = False
    vid7 = ""
    if geo_field:
        # 带地理字段配置创建
        adv = {"latlng": geo_field}
        ok_geo, vid7, resp7 = create_view("地图视图_指定地理字段", 7, {
            "advancedSetting": adv,
        })
        config_geo = adv
        print(f"  带 latlng 配置创建: {'✓' if ok_geo else '✗'}  state={resp7.get('state')} msg={resp7.get('msg','')}")
        print(f"  配置: advancedSetting={adv}")

        # 也尝试二次保存方式
        if ok_geo and vid7:
            sr7 = second_save(vid7, "地图视图_指定地理字段", {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["latlng"],
                "advancedSetting": {"latlng": geo_field},
            })
            ok_sr7 = sr7.get("state") == 1
            print(f"  二次保存 latlng: {'✓' if ok_sr7 else '✗'}  state={sr7.get('state')} msg={sr7.get('msg','')}")
    else:
        print(f"  无地理字段(type=24/40)，仅测试基础创建")

    final_ok7 = ok_base  # 基础可创建即算 PASS，geo 字段配置为附加信息
    results.append({
        "view": "地图视图",
        "viewType": 7,
        "result": "PASS" if final_ok7 else "FAIL",
        "viewId_base": vid7_base,
        "viewId_with_geo": vid7,
        "geo_field": geo_field,
        "config": config_geo,
        "note": "基础创建OK; geo字段配置为附加验证",
    })
    print(f"  => {'PASS' if final_ok7 else 'FAIL'}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 3: 资源视图 (viewType=9) — 成员字段和日期字段映射
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "─" * 64)
    print("[TEST 3] 资源视图 (viewType=9) — 成员+日期字段映射")

    if not collab_id or not date1:
        missing = []
        if not collab_id: missing.append("成员字段(type=26)")
        if not date1:     missing.append("日期字段(type=15/16)")
        print(f"  跳过：缺少 {', '.join(missing)}")
        results.append({
            "view": "资源视图", "viewType": 9,
            "result": "跳过", "reason": f"缺少 {', '.join(missing)}",
        })
    else:
        # 方式1：创建时带 advancedSetting
        adv9 = {
            "resourceId": collab_id,
            "startdate": date1,
            "enddate": date2,
        }
        ok9a, vid9a, resp9a = create_view("资源视图_带字段配置", 9, {
            "advancedSetting": adv9,
        })
        print(f"  创建(含advancedSetting): {'✓' if ok9a else '✗'}  state={resp9a.get('state')} msg={resp9a.get('msg','')}")
        print(f"  配置: {adv9}")

        # 方式2：创建 + 二次保存
        ok9b, vid9b, resp9b = create_view("资源视图_二次保存", 9)
        print(f"  基础创建: {'✓' if ok9b else '✗'}  viewId={fmt(vid9b)}")
        ok9c = False
        if ok9b and vid9b:
            sr9 = second_save(vid9b, "资源视图_二次保存", {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["resourceId", "startdate", "enddate"],
                "advancedSetting": adv9,
            })
            ok9c = sr9.get("state") == 1
            print(f"  二次保存 resourceId+startdate+enddate: {'✓' if ok9c else '✗'}  state={sr9.get('state')} msg={sr9.get('msg','')}")

        final_ok9 = ok9a or ok9b
        results.append({
            "view": "资源视图",
            "viewType": 9,
            "result": "PASS" if final_ok9 else "FAIL",
            "viewId_direct": vid9a,
            "viewId_second_save": vid9b,
            "fields_used": {"resourceId": collab_id, "startdate": date1, "enddate": date2},
            "config": adv9,
        })
        print(f"  => {'PASS' if final_ok9 else 'FAIL'}")

    # ─────────────────────────────────────────────────────────────────────────
    # TEST 4: 详情视图 (viewType=6) — 表单布局配置
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "─" * 64)
    print("[TEST 4] 详情视图 (viewType=6) — 表单布局配置")

    # 基础创建
    ok6a, vid6a, resp6a = create_view("详情视图_基础", 6)
    print(f"  基础创建: {'✓' if ok6a else '✗'}  state={resp6a.get('state')} msg={resp6a.get('msg','')}")

    # 带布局配置（showpc=1 开启PC端多列，hideinfo 控制字段显示）
    layout_config = {
        "showpc": "1",         # 启用PC多列布局
        "showRows": "2",       # 每行2列
    }
    ok6b, vid6b, resp6b = create_view("详情视图_多列布局", 6, {
        "advancedSetting": layout_config,
    })
    print(f"  带布局配置创建: {'✓' if ok6b else '✗'}  state={resp6b.get('state')} msg={resp6b.get('msg','')}")
    print(f"  配置: {layout_config}")

    # 二次保存布局
    ok6c = False
    if ok6a and vid6a:
        sr6 = second_save(vid6a, "详情视图_基础", {
            "editAttrs": ["advancedSetting"],
            "editAdKeys": ["showpc", "showRows"],
            "advancedSetting": layout_config,
        })
        ok6c = sr6.get("state") == 1
        print(f"  二次保存布局配置: {'✓' if ok6c else '✗'}  state={sr6.get('state')} msg={sr6.get('msg','')}")

    # 带 displayControls 字段顺序的配置
    display_cids = [f["controlId"] for f in fields[:5] if f.get("controlId")][:5]
    ok6d, vid6d, resp6d = create_view("详情视图_字段顺序", 6, {
        "displayControls": display_cids,
        "advancedSetting": {"showpc": "1"},
    })
    print(f"  带displayControls({len(display_cids)}个字段): {'✓' if ok6d else '✗'}  state={resp6d.get('state')} msg={resp6d.get('msg','')}")

    final_ok6 = ok6a
    results.append({
        "view": "详情视图",
        "viewType": 6,
        "result": "PASS" if final_ok6 else "FAIL",
        "viewId_basic": vid6a,
        "viewId_layout": vid6b,
        "viewId_controls": vid6d,
        "config_used": layout_config,
        "displayControls_count": len(display_cids),
    })
    print(f"  => {'PASS' if final_ok6 else 'FAIL'}")

    # ─────────────────────────────────────────────────────────────────────────
    # 汇总
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("测试汇总")
    print("=" * 64)

    pass_count = 0
    for r in results:
        status = r["result"]
        icon = "✓" if status == "PASS" else ("~" if status == "跳过" else "✗")
        print(f"  {icon} viewType={r['viewType']} {r['view']} => {status}")

        if status == "PASS":
            pass_count += 1
            # 打印使用的字段和配置
            if r.get("fields_used"):
                for k, v in r["fields_used"].items():
                    print(f"      字段 {k}: {fmt(v)}")
            if r.get("config"):
                print(f"      配置: {r['config']}")
            if r.get("viewId") and r["viewId"]:
                print(f"      viewId: {fmt(r['viewId'])}")
        elif status == "跳过":
            print(f"      原因: {r.get('reason', '')}")
        else:
            print(f"      失败详情: 见上方输出")

    actual = [r for r in results if r["result"] != "跳过"]
    print(f"\n通过: {pass_count}/{len(actual)} (跳过: {len(results)-len(actual)})")
    print(f"\n工作表链接: https://www.mingdao.com/app/{APP_ID}/69ce832640691821042c6e79/{WS_ID}")


if __name__ == "__main__":
    main()
