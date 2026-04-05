#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互式修改应用导航风格（pcNaviStyle）。

流程：
1) 从 app_authorizations 中读取可用应用并列出
2) 选择一个应用
3) 输入 pcNaviStyle（默认 1，回车即使用默认）
4) 调用 https://www.mingdao.com/api/HomeApp/EditAppInfo
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import auth_retry
from utils import latest_file

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
RESULT_DIR = OUTPUT_ROOT / "app_navi_style_updates"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

APP_INFO_URL = "https://api.mingdao.com/v3/app"
EDIT_APP_INFO_URL = "https://www.mingdao.com/api/HomeApp/EditAppInfo"


def load_app_auth_rows() -> List[dict]:
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"未找到授权文件：{APP_AUTH_DIR}")
    rows: List[dict] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload = data.get("data")
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            app_id = str(row.get("appId", "")).strip()
            app_key = str(row.get("appKey", "")).strip()
            sign = str(row.get("sign", "")).strip()
            if not app_id or not app_key or not sign:
                continue
            item = dict(row)
            item["_auth_path"] = str(path.resolve())
            rows.append(item)

    # 按 appId 去重，仅保留最新
    dedup: Dict[str, dict] = {}
    for r in rows:
        app_id = str(r.get("appId", "")).strip()
        if app_id and app_id not in dedup:
            dedup[app_id] = r
    return list(dedup.values())


def fetch_app_meta(app_key: str, sign: str) -> dict:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=30)
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"获取应用信息失败: {data}")
    app = data.get("data", {})
    if not isinstance(app, dict):
        raise RuntimeError(f"应用信息返回格式错误: {data}")
    return app


def icon_from_icon_url(icon_url: str) -> str:
    url = (icon_url or "").strip()
    if not url:
        return ""
    # 例如: .../customIcon/sys_1_11_car.svg -> sys_1_11_car
    name = url.split("/")[-1]
    if name.endswith(".svg"):
        return name[:-4]
    return name


def parse_style_input(raw: str) -> int:
    value = raw.strip()
    if not value:
        return 1
    try:
        style = int(value)
        if style < 0:
            return 1
        return style
    except Exception:
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="交互式修改应用导航风格（pcNaviStyle）")
    parser.add_argument("--refresh-auth", action="store_true", help="执行前先刷新 Cookie/Authorization")
    parser.add_argument("--headless", action="store_true", help="配合 --refresh-auth 使用，无头模式")
    parser.add_argument("--dry-run", action="store_true", help="仅打印请求，不实际调用")
    parser.add_argument("--app-id", default="", help="可选，指定 appId（传入后跳过应用选择交互）")
    parser.add_argument("--pc-navi-style", type=int, default=None, help="可选，指定 pcNaviStyle（传入后跳过样式输入交互）")
    args = parser.parse_args()

    if args.refresh_auth:
        auth_retry.refresh_auth(AUTH_CONFIG_PATH, headless=args.headless)

    app_rows = load_app_auth_rows()
    if not app_rows:
        raise RuntimeError("没有可用应用授权记录")

    apps: List[dict] = []
    for row in app_rows:
        app_id = str(row.get("appId", "")).strip()
        app_key = str(row.get("appKey", "")).strip()
        sign = str(row.get("sign", "")).strip()
        project_id = str(row.get("projectId", "")).strip()
        if not app_id or not app_key or not sign:
            continue
        meta = fetch_app_meta(app_key=app_key, sign=sign)
        apps.append(
            {
                "appId": app_id,
                "appKey": app_key,
                "sign": sign,
                "projectId": project_id,
                "name": str(meta.get("name", "")).strip() or app_id,
                "color": str(meta.get("color", "")).strip() or "#00bcd4",
                "iconUrl": str(meta.get("iconUrl", "")).strip(),
                "authPath": row.get("_auth_path", ""),
            }
        )

    if not apps:
        raise RuntimeError("授权记录不可用，无法获取应用列表")

    if args.app_id.strip():
        app = next((x for x in apps if x["appId"] == args.app_id.strip()), None)
        if not app:
            raise ValueError(f"未找到 appId={args.app_id.strip()} 的应用授权记录")
    else:
        print("可选应用：")
        print("序号 | 应用名称 | 应用ID")
        for i, a in enumerate(apps, start=1):
            print(f"{i}. {a['name']} | {a['appId']}")

        pick_raw = input("请输入要编辑的应用序号: ").strip()
        if not pick_raw.isdigit():
            print("输入无效，已取消。")
            return
        idx = int(pick_raw)
        if idx < 1 or idx > len(apps):
            print("序号超出范围，已取消。")
            return
        app = apps[idx - 1]

    if args.pc_navi_style is not None:
        pc_navi_style = parse_style_input(str(args.pc_navi_style))
    else:
        style_raw = input("请输入 pcNaviStyle（默认 1，回车直接使用默认）: ")
        pc_navi_style = parse_style_input(style_raw)

    payload = {
        "appId": app["appId"],
        "projectId": app["projectId"],
        "iconColor": app["color"],
        "navColor": app["color"],
        "icon": icon_from_icon_url(app["iconUrl"]),
        "description": "",
        "name": app["name"],
        "shortDesc": "",
        "pcNaviStyle": pc_navi_style,
        "displayIcon": "011",
    }

    if not payload["projectId"]:
        raise ValueError("当前授权记录缺少 projectId，无法调用 EditAppInfo")

    if args.dry_run:
        response_data = {"dry_run": True}
        status_code = 0
    else:
        resp = auth_retry.hap_web_post(
            EDIT_APP_INFO_URL,
            AUTH_CONFIG_PATH,
            referer=f"https://www.mingdao.com/app/{app['appId']}",
            json=payload,
            timeout=30,
        )
        status_code = resp.status_code
        try:
            response_data = resp.json()
        except Exception:
            response_data = {"status_code": resp.status_code, "text": resp.text}

    summary = {
        "appId": app["appId"],
        "appName": app["name"],
        "projectId": app["projectId"],
        "pcNaviStyle": pc_navi_style,
        "dry_run": args.dry_run,
        "status_code": status_code,
        "payload": payload,
        "response": response_data,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = (RESULT_DIR / f"app_navi_style_update_{ts}.json").resolve()
    latest = (RESULT_DIR / "app_navi_style_update_latest.json").resolve()
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n执行结果：")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n已保存: {out}")
    print(f"已更新: {latest}")


if __name__ == "__main__":
    main()
