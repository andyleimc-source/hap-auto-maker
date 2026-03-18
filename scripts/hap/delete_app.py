#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 组织授权接口：删除应用
基于组织密钥 AppKey/SecretKey 生成签名后调用 /v1/open/app/delete
"""

import argparse
import base64
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Dict, List

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "organization_auth.json"
DEFAULT_BASE_URL = "https://api.mingdao.com"
ENDPOINT = "/v1/open/app/delete"
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
APP_INFO_URL = "https://api.mingdao.com/v3/app"


def load_org_auth() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"缺少配置文件: {CONFIG_PATH}")
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for k in ("app_key", "secret_key"):
        if not data.get(k):
            raise ValueError(f"配置缺少字段: {k}")
    return data


def build_sign(app_key: str, secret_key: str, timestamp_ms: int) -> str:
    raw = f"AppKey={app_key}&SecretKey={secret_key}&Timestamp={timestamp_ms}"
    digest_hex = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return base64.b64encode(digest_hex.encode("utf-8")).decode("utf-8")


def extract_apps_from_outputs(output_dir: Path) -> List[Dict[str, object]]:
    apps: Dict[str, Dict[str, object]] = {}
    if not output_dir.exists():
        return []

    for json_file in output_dir.glob("*.json"):
        # Priority 1: file name pattern app_authorize_<appId>.json
        prefix = "app_authorize_"
        suffix = ".json"
        name = json_file.name
        if name.startswith(prefix) and name.endswith(suffix):
            app_id = name[len(prefix) : -len(suffix)]
            if app_id:
                app = apps.setdefault(
                    app_id,
                    {
                        "appId": app_id,
                        "name": "",
                        "createTime": "",
                        "creator": "",
                        "appKey": "",
                        "sign": "",
                        "files": [],
                    },
                )
                app["files"].append(str(json_file))

        # Priority 2: parse json payload and extract data[*].appId
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = data.get("data")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    app_id = row.get("appId")
                    if isinstance(app_id, str) and app_id.strip():
                        app_id = app_id.strip()
                        app_name = row.get("name")
                        app_name = app_name.strip() if isinstance(app_name, str) else ""
                        create_time = row.get("createTime")
                        create_time = create_time.strip() if isinstance(create_time, str) else ""
                        creator = row.get("creater", {}).get("name") if isinstance(row.get("creater"), dict) else ""
                        creator = creator.strip() if isinstance(creator, str) else ""
                        app = apps.setdefault(
                            app_id,
                            {
                                "appId": app_id,
                                "name": "",
                                "createTime": "",
                                "creator": "",
                                "appKey": "",
                                "sign": "",
                                "files": [],
                            },
                        )
                        app_key = row.get("appKey")
                        sign = row.get("sign")
                        if isinstance(app_key, str) and app_key.strip():
                            app["appKey"] = app_key.strip()
                        if isinstance(sign, str) and sign.strip():
                            app["sign"] = sign.strip()
                        if app_name:
                            app["name"] = app_name
                        if create_time:
                            app["createTime"] = create_time
                        if creator:
                            app["creator"] = creator
                        if str(json_file) not in app["files"]:
                            app["files"].append(str(json_file))
        elif isinstance(rows, dict):
            app_id = rows.get("appId")
            if isinstance(app_id, str) and app_id.strip():
                app_id = app_id.strip()
                app_name = rows.get("name")
                app_name = app_name.strip() if isinstance(app_name, str) else ""
                create_time = rows.get("createTime")
                create_time = create_time.strip() if isinstance(create_time, str) else ""
                creator = rows.get("creater", {}).get("name") if isinstance(rows.get("creater"), dict) else ""
                creator = creator.strip() if isinstance(creator, str) else ""
                app = apps.setdefault(
                    app_id,
                    {
                        "appId": app_id,
                        "name": "",
                        "createTime": "",
                        "creator": "",
                        "appKey": "",
                        "sign": "",
                        "files": [],
                    },
                )
                app_key = rows.get("appKey")
                sign = rows.get("sign")
                if isinstance(app_key, str) and app_key.strip():
                    app["appKey"] = app_key.strip()
                if isinstance(sign, str) and sign.strip():
                    app["sign"] = sign.strip()
                if app_name:
                    app["name"] = app_name
                if create_time:
                    app["createTime"] = create_time
                if creator:
                    app["creator"] = creator
                if str(json_file) not in app["files"]:
                    app["files"].append(str(json_file))
    return [apps[k] for k in sorted(apps.keys())]


def fetch_app_name(app_key: str, sign: str) -> str:
    headers = {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }
    resp = requests.get(APP_INFO_URL, headers=headers, timeout=20)
    data = resp.json()
    if not data.get("success"):
        return ""
    app = data.get("data", {})
    if not isinstance(app, dict):
        return ""
    return str(app.get("name", "")).strip()


def enrich_app_names(apps: List[Dict[str, object]]) -> None:
    for app in apps:
        app_key = str(app.get("appKey", "")).strip()
        sign = str(app.get("sign", "")).strip()
        name = ""
        if app_key and sign:
            try:
                name = fetch_app_name(app_key=app_key, sign=sign)
            except Exception:
                name = ""
        # 强制优先使用实时应用名；失败时回退到本地字段
        if name:
            app["name"] = name


def collect_all_json_files(root: Path) -> List[str]:
    if not root.exists():
        return []
    return sorted(str(p.resolve()) for p in root.rglob("*.json") if p.is_file())


def parse_selection(choice: str, max_index: int) -> List[int]:
    # Support inputs like: 1,2,3 or 1.2.3 or 1 2 3
    parts = [p for p in re.split(r"[^\d]+", choice) if p]
    if not parts:
        return []
    selected: List[int] = []
    for p in parts:
        idx = int(p)
        if idx < 1 or idx > max_index:
            raise ValueError(f"序号超出范围: {idx} (有效范围 1-{max_index})")
        if idx not in selected:
            selected.append(idx)
    return selected


def call_delete_app(
    *,
    base_url: str,
    app_key: str,
    secret_key: str,
    project_id: str,
    operator_id: str,
    app_id: str,
    dry_run: bool,
) -> Dict:
    timestamp_ms = int(time.time() * 1000)
    sign = build_sign(app_key, secret_key, timestamp_ms)
    payload = {
        "appKey": app_key,
        "sign": sign,
        "timestamp": timestamp_ms,
        "projectId": project_id,
        "appId": app_id,
        "operatorId": operator_id,
    }

    if dry_run:
        return {"dry_run": True, "payload": payload}

    url = base_url.rstrip("/") + ENDPOINT
    resp = requests.post(url, json=payload, timeout=30)
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="删除 HAP 应用")
    parser.add_argument("--app-id", help="应用 ID")
    parser.add_argument(
        "--delete-all",
        action="store_true",
        help="删除 app_authorizations 下记录到的所有应用，并按规则清理 outputs 下 JSON 文件",
    )
    parser.add_argument(
        "--delete-all-exclusion",
        nargs="?",
        const="PROMPT",
        default=None,
        help="删除所有应用时的排除序号，如 1,2。如果不带具体序号，则显示列表后交互输入。",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API 基础地址")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求体，不发送")

    auth = load_org_auth()
    app_key = auth["app_key"]
    secret_key = auth["secret_key"]
    default_project_id = auth.get("project_id", "")
    default_operator_id = auth.get("owner_id", "")

    parser.add_argument("--project-id", default=default_project_id, help="HAP 组织Id")
    parser.add_argument("--operator-id", default=default_operator_id, help="操作者 HAP 账号Id")
    args = parser.parse_args()

    if args.delete_all_exclusion is not None:
        args.delete_all = True

    if args.delete_all and args.app_id:
        raise ValueError("--delete-all 与 --app-id 只能二选一")
    if not args.delete_all and not args.app_id:
        raise ValueError("请传 --app-id，或使用 --delete-all")

    if not args.project_id:
        raise ValueError("缺少 projectId，请通过 --project-id 或在配置中设置 project_id")
    if not args.operator_id:
        raise ValueError("缺少 operatorId，请通过 --operator-id 或在配置中设置 owner_id")

    if args.delete_all:
        apps = extract_apps_from_outputs(APP_AUTH_DIR)
        # 兼容旧目录：若新目录为空，尝试读取 outputs 根目录历史文件
        if not apps:
            apps = extract_apps_from_outputs(OUTPUT_ROOT)
        enrich_app_names(apps)
        print(f"发现应用数量: {len(apps)}")
        print("序号 | 应用名称 | 创建时间 | 应用ID | 创建人")
        for idx, app in enumerate(apps, start=1):
            app_name = app.get("name") or "(未知)"
            create_time = app.get("createTime") or "(未知)"
            app_id = app.get("appId")
            creator = app.get("creator") or "(未知)"
            print(f"{idx}. {app_name} | {create_time} | {app_id} | {creator}")

        if not apps:
            print("未发现可删除应用，流程结束。")
            return

        selected_apps: List[Dict[str, object]]
        files_to_delete: List[str]
        delete_all_json = False

        if args.delete_all_exclusion is not None:
            if args.delete_all_exclusion == "PROMPT":
                exclusion_value = input("请输入要【保留(不删除)】的序号(如 1,2,3 或 1.2.3)。其他输入将取消: ").strip()
                if not exclusion_value:
                    print("未输入任何内容，已取消删除。")
                    return
            else:
                exclusion_value = args.delete_all_exclusion

            try:
                excluded_indexes = parse_selection(exclusion_value, len(apps))
            except ValueError as e:
                print(f"解析排除序号失败: {e}")
                return
            selected_indexes = [i for i in range(1, len(apps) + 1) if i not in excluded_indexes]
            if not selected_indexes:
                print("所有应用都已被排除，未选中任何待删除应用。")
                return
            selected_apps = [apps[i - 1] for i in selected_indexes]
            files_set = set()
            for app in selected_apps:
                for fp in app.get("files", []):
                    files_set.add(fp)
            files_to_delete = sorted(files_set)
            print(f"自动执行删除，共排除了序号: {excluded_indexes}")
        else:
            choice = input("请输入 Y(全删) / 序号(如 1,2,3 或 1.2.3 仅删除所选)。其他任意输入将取消: ").strip()
            choice_lower = choice.lower()

            if choice_lower == "y":
                selected_apps = apps
                files_to_delete = collect_all_json_files(OUTPUT_ROOT)
                delete_all_json = True
            else:
                try:
                    selected_indexes = parse_selection(choice, len(apps))
                except ValueError:
                    print("已取消删除。")
                    return
                if not selected_indexes:
                    print("未选择任何序号，已取消删除。")
                    return
                selected_apps = [apps[i - 1] for i in selected_indexes]
                files_set = set()
                for app in selected_apps:
                    for fp in app.get("files", []):
                        files_set.add(fp)
                files_to_delete = sorted(files_set)

        results = []
        for app in selected_apps:
            app_id = app["appId"]
            result = call_delete_app(
                base_url=args.base_url,
                app_key=app_key,
                secret_key=secret_key,
                project_id=args.project_id,
                operator_id=args.operator_id,
                app_id=app_id,
                dry_run=args.dry_run,
            )
            results.append({"appId": app_id, "result": result})

        deleted_files = []
        for file_path in files_to_delete:
            deleted_files.append(file_path)
            if not args.dry_run:
                Path(file_path).unlink(missing_ok=True)

        print(
            json.dumps(
                {
                    "delete_all": True,
                    "delete_mode": "all" if delete_all_json else "partial",
                    "dry_run": args.dry_run,
                    "results": results,
                    "json_files": {
                        "count": len(deleted_files),
                        "files": deleted_files,
                        "deleted": not args.dry_run,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    data = call_delete_app(
        base_url=args.base_url,
        app_key=app_key,
        secret_key=secret_key,
        project_id=args.project_id,
        operator_id=args.operator_id,
        app_id=args.app_id,
        dry_run=args.dry_run,
    )
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
