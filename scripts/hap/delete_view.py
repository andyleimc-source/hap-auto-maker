#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
delete_view.py — 删除指定工作表中的单个视图。

从 delete_default_views.py 提取 delete_view() 核心逻辑，封装为独立 CLI 脚本。

用法（CLI）：
    python3 delete_view.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --view-id <viewId>

    # dry-run：仅打印，不实际删除
    python3 delete_view.py \\
        --app-id <appId> \\
        --worksheet-id <worksheetId> \\
        --view-id <viewId> \\
        --dry-run

用法（Python）：
    from delete_view import delete_view
    ok = delete_view(
        app_id="xxx",
        worksheet_id="yyy",
        view_id="zzz",
        auth_config_path=Path("config/credentials/auth_config.py"),
    )
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
CURRENT_DIR = Path(__file__).resolve().parent

if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import auth_retry

AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
DELETE_VIEW_URL = "https://www.mingdao.com/api/Worksheet/DeleteWorksheetView"


# ── 核心删除函数 ───────────────────────────────────────────────────────────────

def delete_view(
    app_id: str,
    worksheet_id: str,
    view_id: str,
    auth_config_path: Path,
) -> bool:
    """
    调用 DeleteWorksheetView 接口删除指定视图。

    Args:
        app_id: 应用 ID
        worksheet_id: 工作表 ID
        view_id: 视图 ID
        auth_config_path: auth_config.py 路径（用于 browser auth）
    Returns:
        True 表示删除成功，False 表示失败
    """
    payload = {
        "appId": app_id,
        "viewId": view_id,
        "worksheetId": worksheet_id,
        "status": 9,
    }
    referer = f"https://www.mingdao.com/app/{app_id}/{worksheet_id}"
    resp = auth_retry.hap_web_post(
        DELETE_VIEW_URL, auth_config_path,
        referer=referer,
        json=payload,
        timeout=30,
        proxies={},
    )
    data = resp.json()
    # Web API：state == 1 或 data 字段为真值均表示成功
    return bool(data.get("state") == 1 or data.get("data"))


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="删除工作表中的指定视图")
    parser.add_argument("--app-id", required=True, help="应用 ID")
    parser.add_argument("--worksheet-id", required=True, help="工作表 ID")
    parser.add_argument("--view-id", required=True, help="视图 ID")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不实际删除")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    args = parser.parse_args()

    app_id = args.app_id.strip()
    worksheet_id = args.worksheet_id.strip()
    view_id = args.view_id.strip()
    auth_config_path = Path(args.auth_config).expanduser().resolve()

    if args.dry_run:
        print(f"[预览] 应用={app_id}  工作表={worksheet_id}  视图={view_id}  → 待删除（dry-run，未实际执行）")
        return

    print(f"[delete_view] 删除视图 {view_id}（工作表 {worksheet_id}）...")
    ok = delete_view(
        app_id=app_id,
        worksheet_id=worksheet_id,
        view_id=view_id,
        auth_config_path=auth_config_path,
    )

    if ok:
        print(f"✓ 删除成功  视图 {view_id}")
    else:
        print(f"✗ 删除失败  视图 {view_id}")
        sys.exit(1)


if __name__ == "__main__":
    main()
