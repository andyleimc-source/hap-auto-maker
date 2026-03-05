#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
删除某个应用下某个工作表的某个视图。
"""

import argparse
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Dict

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
VIEW_DELETE_RESULT_DIR = OUTPUT_ROOT / "view_delete_results"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

DELETE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/DeleteWorksheetView"


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_auth_config(path: Path) -> Dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"认证文件不存在: {path}")
    spec = importlib.util.spec_from_file_location("auth_config_runtime", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载认证文件: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    account_id = str(getattr(mod, "ACCOUNT_ID", "")).strip()
    authorization = str(getattr(mod, "AUTHORIZATION", "")).strip()
    cookie = str(getattr(mod, "COOKIE", "")).strip()
    if not account_id or not authorization or not cookie:
        raise ValueError(f"auth_config.py 缺少 ACCOUNT_ID/AUTHORIZATION/COOKIE: {path}")
    return {"accountId": account_id, "authorization": authorization, "cookie": cookie}


def delete_view(app_id: str, worksheet_id: str, view_id: str, auth: Dict[str, str], dry_run: bool) -> dict:
    payload = {
        "appId": app_id,
        "worksheetId": worksheet_id,
        "viewId": view_id,
    }
    if dry_run:
        return {"dry_run": True, "payload": payload}

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "accountid": auth["accountId"],
        "Authorization": auth["authorization"],
        "Cookie": auth["cookie"],
        "Origin": "https://www.mingdao.com",
        "Referer": f"https://www.mingdao.com/app/{app_id}/{worksheet_id}/{view_id}",
        "X-Requested-With": "XMLHttpRequest",
    }
    resp = requests.post(DELETE_VIEW_URL, headers=headers, json=payload, timeout=30)
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


def main() -> None:
    parser = argparse.ArgumentParser(description="删除某个应用下某个工作表的某个视图")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--view-id", required=True, help="视图 ID")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="认证配置 auth_config.py 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际删除")
    parser.add_argument("--output", default="", help="输出结果 JSON 路径")
    args = parser.parse_args()

    auth = load_auth_config(Path(args.auth_config).expanduser().resolve())
    resp = delete_view(
        app_id=args.app_id.strip(),
        worksheet_id=args.worksheet_id.strip(),
        view_id=args.view_id.strip(),
        auth=auth,
        dry_run=bool(args.dry_run),
    )

    result = {
        "executedAt": datetime.now().isoformat(timespec="seconds"),
        "dryRun": bool(args.dry_run),
        "request": {
            "appId": args.app_id.strip(),
            "worksheetId": args.worksheet_id.strip(),
            "viewId": args.view_id.strip(),
            "endpoint": DELETE_VIEW_URL,
        },
        "response": resp,
    }

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = (VIEW_DELETE_RESULT_DIR / f"view_delete_result_{now_ts()}.json").resolve()
    write_json(out_path, result)

    print(f"执行完成: {out_path}")
    if isinstance(resp, dict):
        state = resp.get("state")
        success = bool(state == 1) if state is not None else False
        print(f"- state: {state}")
        print(f"- success: {success if not args.dry_run else True}")
    else:
        print("- success: False")


if __name__ == "__main__":
    main()

