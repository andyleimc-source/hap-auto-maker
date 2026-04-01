#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2g4 — 删除自定义页面（Web POST /api/AppManagement/RemoveWorkSheetForApp，type=1）

WARNING: isPermanentlyDelete=True 时不可逆，页面将被永久删除。

用法:
    uv run python3 hap-auto-maker/scripts/hap/page_delete.py \
        --app-id <appId> \
        --app-section-id <appSectionId> \
        --page-id <pageId> \
        [--project-id <projectId>] \
        [--permanent] [--yes]
"""

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_retry

BASE_DIR = Path(__file__).resolve().parents[2]
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
REMOVE_URL = "https://www.mingdao.com/api/AppManagement/RemoveWorkSheetForApp"


def delete_page(app_id: str, app_section_id: str, page_id: str, project_id: str,
                permanent: bool, auth_config_path: Path) -> dict:
    body = {
        "appId": app_id,
        "appSectionId": app_section_id,
        "workSheetId": page_id,
        "projectId": project_id,
        "type": 1,
        "isPermanentlyDelete": permanent,
    }
    resp = auth_retry.hap_web_post(REMOVE_URL, auth_config_path, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    is_ok = data.get("state") == 1 or data.get("status") == 1 or data.get("success") is True
    if not is_ok:
        raise RuntimeError(f"RemoveWorkSheetForApp 失败: {data}")
    return {"ok": True, "pageId": page_id, "permanent": permanent, "raw": data}


def main() -> None:
    parser = argparse.ArgumentParser(description="2g4 — 删除自定义页面")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--app-section-id", required=True, help="分组 ID（appSectionId）")
    parser.add_argument("--page-id", required=True, help="页面 ID（pageId）")
    parser.add_argument("--project-id", default="", help="项目 ID（可留空）")
    parser.add_argument("--permanent", action="store_true", help="永久删除（默认移至回收站）")
    parser.add_argument("--yes", action="store_true", help="跳过确认提示直接执行")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    args = parser.parse_args()

    if not args.yes:
        action = "永久删除" if args.permanent else "移至回收站"
        confirm = input(f"确认{action}页面 {args.page_id}？[y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            print("已取消")
            return

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    result = delete_page(
        args.app_id, args.app_section_id, args.page_id,
        args.project_id, args.permanent, auth_config_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    action = "永久删除" if args.permanent else "已移至回收站"
    print(f"\nOK — pageId={args.page_id} {action}")


if __name__ == "__main__":
    main()
