#!/usr/bin/env python3
"""在 CRM 应用的市场活动表中创建所有类型的视图。"""

from __future__ import annotations
import sys, json, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))
import auth_retry

AUTH_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
APP_ID = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"

# 用刚创建的「全字段类型演示」表 — 有各种字段类型
WS_ID = "69cf74eef9434db36c6e0816"

SAVE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetView"
DELETE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/DeleteWorksheetView"


def web_post(url, body):
    referer = f"https://www.mingdao.com/app/{APP_ID}/{WS_ID}"
    resp = auth_retry.hap_web_post(url, AUTH_PATH, referer=referer, json=body, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:200]}


def get_ws_fields():
    """获取工作表字段。"""
    resp = auth_retry.hap_web_post(
        "https://www.mingdao.com/api/Worksheet/GetWorksheetInfo", AUTH_PATH,
        referer=f"https://www.mingdao.com/app/{APP_ID}",
        json={"worksheetId": WS_ID, "getTemplate": True, "getViews": True}, timeout=30
    ).json()
    return resp.get("data", {}).get("template", {}).get("controls", [])


def create_view(name, view_type, extra=None):
    """创建视图并返回 (ok, viewId, resp)。"""
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
    """视图二次保存。"""
    body = {
        "appId": APP_ID,
        "worksheetId": WS_ID,
        "viewId": view_id,
        "name": name,
    }
    body.update(update_body)
    return web_post(SAVE_VIEW_URL, body)


def main():
    print("=" * 60)
    print("创建全视图类型演示")
    print(f"工作表: {WS_ID}")
    print("=" * 60)

    # 获取字段，找关键字段 ID
    fields = get_ws_fields()
    field_map = {}
    for f in fields:
        cid = f.get("controlId", "")
        ctype = f.get("type")
        cname = f.get("controlName", "")
        field_map.setdefault(ctype, []).append({"id": cid, "name": cname})

    # 找关键字段
    select_field = (field_map.get(9, []) or field_map.get(11, []) or [{}])[0].get("id", "")
    date_fields = field_map.get(15, []) + field_map.get(16, [])
    date1 = date_fields[0]["id"] if len(date_fields) > 0 else ""
    date2 = date_fields[1]["id"] if len(date_fields) > 1 else date1
    area_field = (field_map.get(24, []) or [{}])[0].get("id", "")
    collab_field = (field_map.get(26, []) or [{}])[0].get("id", "")

    print(f"\n字段: select={select_field[:12]}, date1={date1[:12]}, date2={date2[:12]}, area={area_field[:12]}, collab={collab_field[:12]}")

    results = []

    # ── viewType=0 表格视图 ──
    print("\n[0] 表格视图...")
    ok, vid, _ = create_view("全部数据", 0)
    print(f"  {'✓' if ok else '✗'} viewId={vid[:16] if vid else 'N/A'}")
    results.append(("表格视图", 0, ok))

    # ── viewType=0 分组表格 ──
    if select_field:
        print("[0] 分组表格视图...")
        group_view_json = json.dumps({
            "viewId": "", "groupFilters": [{
                "controlId": select_field, "values": [],
                "dataType": 9, "spliceType": 1, "filterType": 2,
                "dateRange": 0, "minValue": "", "maxValue": "", "isGroup": True,
            }], "navShow": True,
        }, ensure_ascii=False)
        ok, vid, _ = create_view("按状态分组", 0, {
            "advancedSetting": {"groupView": group_view_json},
        })
        if ok and vid:
            # 二次保存确保 groupView 生效
            second_save(vid, "按状态分组", {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["groupView"],
                "advancedSetting": {"groupView": group_view_json},
            })
        print(f"  {'✓' if ok else '✗'} 分组表格")
        results.append(("分组表格", 0, ok))

    # ── viewType=1 看板 ──
    if select_field:
        print("[1] 看板视图...")
        ok, vid, _ = create_view("看板视图", 1, {"viewControl": select_field})
        print(f"  {'✓' if ok else '✗'} viewId={vid[:16] if vid else 'N/A'}")
        results.append(("看板视图", 1, ok))

    # ── viewType=2 层级视图 ──
    # 需要自关联字段，新表没有，跳过
    print("[2] 层级视图 — 跳过（需自关联字段）")
    results.append(("层级视图", 2, None))

    # ── viewType=3 画廊 ──
    print("[3] 画廊视图...")
    ok, vid, _ = create_view("画廊视图", 3, {
        "advancedSetting": {"coverstyle": '{"position":"2"}'},
    })
    print(f"  {'✓' if ok else '✗'} viewId={vid[:16] if vid else 'N/A'}")
    results.append(("画廊视图", 3, ok))

    # ── viewType=4 日历 ──
    if date1:
        print("[4] 日历视图...")
        ok, vid, _ = create_view("日历视图", 4)
        if ok and vid:
            cids_json = json.dumps([{"begin": date1, "end": ""}], ensure_ascii=False)
            sr = second_save(vid, "日历视图", {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["calendarcids"],
                "advancedSetting": {"calendarcids": cids_json},
            })
            ok2 = sr.get("state") == 1
            print(f"  {'✓' if ok2 else '✗'} 日历视图 + 二次保存")
            results.append(("日历视图", 4, ok2))
        else:
            print(f"  ✗ 日历视图创建失败")
            results.append(("日历视图", 4, False))

    # ── viewType=5 甘特图 ──
    if date1 and date2:
        print("[5] 甘特图...")
        ok, vid, _ = create_view("甘特图", 5)
        if ok and vid:
            sr = second_save(vid, "甘特图", {
                "editAttrs": ["advancedSetting"],
                "editAdKeys": ["begindate", "enddate"],
                "advancedSetting": {"begindate": date1, "enddate": date2},
            })
            ok2 = sr.get("state") == 1
            print(f"  {'✓' if ok2 else '✗'} 甘特图 + 二次保存")
            results.append(("甘特图", 5, ok2))
        else:
            print(f"  ✗ 甘特图创建失败")
            results.append(("甘特图", 5, False))

    # ── viewType=6 详情视图 ──
    print("[6] 详情视图...")
    ok, vid, _ = create_view("详情视图", 6)
    print(f"  {'✓' if ok else '✗'} viewId={vid[:16] if vid else 'N/A'}")
    results.append(("详情视图", 6, ok))

    # ── viewType=7 地图视图 ──
    print("[7] 地图视图...")
    ok, vid, _ = create_view("地图视图", 7)
    print(f"  {'✓' if ok else '✗'} viewId={vid[:16] if vid else 'N/A'}")
    results.append(("地图视图", 7, ok))

    # ── viewType=8 快速视图 ──
    print("[8] 快速视图...")
    ok, vid, _ = create_view("快速视图", 8)
    print(f"  {'✓' if ok else '✗'} viewId={vid[:16] if vid else 'N/A'}")
    results.append(("快速视图", 8, ok))

    # ── viewType=9 资源视图 ──
    print("[9] 资源视图...")
    ok, vid, _ = create_view("资源视图", 9)
    print(f"  {'✓' if ok else '✗'} viewId={vid[:16] if vid else 'N/A'}")
    results.append(("资源视图", 9, ok))

    # ── viewType=10 自定义视图 ──
    print("[10] 自定义视图...")
    ok, vid, _ = create_view("自定义视图", 10)
    print(f"  {'✓' if ok else '✗'} viewId={vid[:16] if vid else 'N/A'}")
    results.append(("自定义视图", 10, ok))

    # 汇总
    print(f"\n{'=' * 60}")
    print("视图创建结果:")
    for name, vt, ok in results:
        status = "✓" if ok else ("跳过" if ok is None else "✗")
        print(f"  {status} viewType={vt} {name}")
    ok_count = sum(1 for _, _, ok in results if ok)
    print(f"\n成功: {ok_count}/{len(results)}")
    print(f"工作表: https://www.mingdao.com/app/{APP_ID}/69ce832640691821042c6e79/{WS_ID}")


if __name__ == "__main__":
    main()
