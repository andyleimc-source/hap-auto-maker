#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2g1 — 创建自定义页面（Web POST /api/AppManagement/AddWorkSheet，type=1）

用法:
    uv run python3 hap-auto-maker/scripts/hap/page_create.py \
        --app-id <appId> \
        --app-section-id <appSectionId> \
        --name <pageName> \
        [--project-id <projectId>] \
        [--icon <iconName>] [--icon-color <color>]
"""

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth_retry

BASE_DIR = Path(__file__).resolve().parents[2]
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
ADD_WORKSHEET_URL = "https://www.mingdao.com/api/AppManagement/AddWorkSheet"


def create_page(app_id: str, app_section_id: str, name: str, project_id: str,
                icon: str, icon_color: str, auth_config_path: Path) -> dict:
    icon_url = f"https://fp1.mingdaoyun.cn/customIcon/{icon}.svg"
    body = {
        "appId": app_id,
        "appSectionId": app_section_id,
        "name": name,
        "remark": "",
        "iconColor": icon_color,
        "projectId": project_id,
        "icon": icon,
        "iconUrl": icon_url,
        "type": 1,
        "createType": 0,
    }
    resp = auth_retry.hap_web_post(ADD_WORKSHEET_URL, auth_config_path, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    is_ok = data.get("state") == 1 or data.get("status") == 1
    if not is_ok:
        raise RuntimeError(f"AddWorkSheet 失败: {data}")
    page_id = str(data.get("data", {}).get("pageId", "")).strip()
    if not page_id:
        raise RuntimeError(f"AddWorkSheet 未返回 pageId: {data}")
    return {"pageId": page_id, "raw": data}


def main() -> None:
    parser = argparse.ArgumentParser(description="2g1 — 创建自定义页面")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--app-section-id", required=True, help="分组 ID（appSectionId）")
    parser.add_argument("--name", required=True, help="页面名称")
    parser.add_argument("--project-id", default="", help="项目 ID（可留空）")
    parser.add_argument("--icon", default="dashboard", help="图标名（默认 dashboard）")
    parser.add_argument("--icon-color", default="#2196F3", help="图标颜色（默认 #2196F3）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    args = parser.parse_args()

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    result = create_page(
        args.app_id, args.app_section_id, args.name,
        args.project_id, args.icon, args.icon_color,
        auth_config_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nOK — pageId: {result['pageId']}")


if __name__ == "__main__":
    main()
