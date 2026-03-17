#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键流水线（创建应用 + 授权 + 智能匹配应用 icon + 回写）：
1) 创建应用（create_app.py）
2) 获取应用授权信息（get_app_authorize.py）
3) 获取应用名称清单（list_apps_for_icon.py）
4) Gemini 匹配应用 icon（match_app_icons_gemini.py）
5) 回写应用 icon（update_app_icons.py）
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from script_locator import resolve_script

BASE_DIR = Path(__file__).resolve().parents[2]
CREATE_APP_SCRIPT = resolve_script("create_app.py")
GET_AUTH_SCRIPT = resolve_script("get_app_authorize.py")
LIST_APPS_SCRIPT = resolve_script("list_apps_for_icon.py")
MATCH_APPS_ICON_SCRIPT = resolve_script("match_app_icons_gemini.py")
UPDATE_APPS_ICON_SCRIPT = resolve_script("update_app_icons.py")
DEFAULT_GROUP_IDS = ""  # 从 organization_auth.json 读取，不再硬编码

OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
APP_INVENTORY_DIR = OUTPUT_ROOT / "app_inventory"
APP_ICON_MATCH_DIR = OUTPUT_ROOT / "app_icon_match_plans"


def run_command(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def parse_create_result(stdout: str) -> dict:
    text = stdout.strip()
    if not text:
        raise ValueError("create_app.py 无输出")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(text[idx:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
        raise ValueError(f"create_app.py 输出不是合法 JSON:\n{text}")


def build_create_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [sys.executable, str(CREATE_APP_SCRIPT), "--name", args.name]
    if args.icon:
        cmd.extend(["--icon", args.icon])
    if args.color:
        cmd.extend(["--color", args.color])
    if args.group_ids:
        cmd.extend(["--group-ids", args.group_ids])
    if args.base_url:
        cmd.extend(["--base-url", args.base_url])
    if args.project_id:
        cmd.extend(["--project-id", args.project_id])
    if args.owner_id:
        cmd.extend(["--owner-id", args.owner_id])
    return cmd


def build_get_auth_cmd(args: argparse.Namespace, app_id: str, auth_output: Path) -> list[str]:
    cmd = [sys.executable, str(GET_AUTH_SCRIPT), "--app-id", app_id, "--output", str(auth_output)]
    if args.base_url:
        cmd.extend(["--base-url", args.base_url])
    if args.project_id:
        cmd.extend(["--project-id", args.project_id])
    return cmd


def print_cmd(title: str, cmd: list[str]) -> None:
    print(f"\n== {title} ==")
    print("命令:", " ".join(cmd))


def ensure_scripts() -> None:
    required = [
        CREATE_APP_SCRIPT,
        GET_AUTH_SCRIPT,
        LIST_APPS_SCRIPT,
        MATCH_APPS_ICON_SCRIPT,
        UPDATE_APPS_ICON_SCRIPT,
    ]
    for p in required:
        if not p.exists():
            raise FileNotFoundError(f"缺少脚本: {p}")


def main() -> None:
    parser = argparse.ArgumentParser(description="创建应用并自动匹配/更新应用 icon")
    parser.add_argument("--name", required=True, help="应用名称")
    parser.add_argument("--icon", default="", help="图标名称，如 0_lego")
    parser.add_argument("--color", default="", help="主题颜色，如 #00bcd4")
    parser.add_argument("--group-ids", default=DEFAULT_GROUP_IDS, help="应用分组Id列表，逗号分隔")
    parser.add_argument("--base-url", default="", help="API 基础地址（默认沿用子脚本默认值）")
    parser.add_argument("--project-id", default="", help="HAP 组织Id")
    parser.add_argument("--owner-id", default="", help="应用拥有者 HAP 账号Id")
    parser.add_argument("--gemini-model", default="gemini-2.5-pro", help="Gemini 模型名")
    parser.add_argument("--skip-smart-icon", action="store_true", help="跳过步骤3-5，不执行智能 icon 匹配/更新")
    parser.add_argument("--dry-run-icon-update", action="store_true", help="智能 icon 的更新步骤仅预览，不实际更新")
    args = parser.parse_args()

    ensure_scripts()

    create_cmd = build_create_cmd(args)
    print_cmd("Step 1/5 创建应用", create_cmd)
    create_proc = run_command(create_cmd)
    if create_proc.returncode != 0:
        print(create_proc.stdout.strip())
        print(create_proc.stderr.strip())
        raise SystemExit(f"create_app.py 执行失败，退出码: {create_proc.returncode}")

    create_result = parse_create_result(create_proc.stdout)
    print(json.dumps(create_result, ensure_ascii=False, indent=2))
    if not create_result.get("success"):
        raise SystemExit(f"创建应用失败: {create_result.get('error_msg', '未知错误')}")

    app_id: Optional[str] = (create_result.get("data") or {}).get("appId")
    if not app_id:
        raise SystemExit("创建成功但未返回 appId，无法继续")
    print(f"\n创建成功，appId: {app_id}")

    auth_output = (APP_AUTH_DIR / f"app_authorize_{app_id}.json").resolve()
    get_auth_cmd = build_get_auth_cmd(args, app_id, auth_output)
    print_cmd("Step 2/5 获取应用授权信息并保存", get_auth_cmd)
    get_auth_proc = run_command(get_auth_cmd)
    if get_auth_proc.returncode != 0:
        print(get_auth_proc.stdout.strip())
        print(get_auth_proc.stderr.strip())
        raise SystemExit(f"get_app_authorize.py 执行失败，退出码: {get_auth_proc.returncode}")
    print(get_auth_proc.stdout.strip())
    if get_auth_proc.stderr.strip():
        print(get_auth_proc.stderr.strip())

    if args.skip_smart_icon:
        print("\n已跳过智能 icon 步骤（--skip-smart-icon）")
        print("\n流水线执行完成")
        return

    app_inventory_output = (APP_INVENTORY_DIR / f"app_inventory_{app_id}.json").resolve()
    list_apps_cmd = [
        sys.executable,
        str(LIST_APPS_SCRIPT),
        "--app-auth-json",
        str(auth_output),
        "--app-ids",
        app_id,
        "--output",
        str(app_inventory_output),
    ]
    print_cmd("Step 3/5 获取应用名称清单", list_apps_cmd)
    p3 = run_command(list_apps_cmd)
    if p3.returncode != 0:
        print(p3.stdout.strip())
        print(p3.stderr.strip())
        raise SystemExit(f"list_apps_for_icon.py 执行失败，退出码: {p3.returncode}")
    print(p3.stdout.strip())

    app_icon_match_output = (APP_ICON_MATCH_DIR / f"app_icon_match_plan_{app_id}.json").resolve()
    match_icon_cmd = [
        sys.executable,
        str(MATCH_APPS_ICON_SCRIPT),
        "--app-json",
        str(app_inventory_output),
        "--model",
        args.gemini_model,
        "--output",
        str(app_icon_match_output),
    ]
    print_cmd("Step 4/5 Gemini 匹配应用 icon", match_icon_cmd)
    p4 = run_command(match_icon_cmd)
    if p4.returncode != 0:
        print(p4.stdout.strip())
        print(p4.stderr.strip())
        raise SystemExit(f"match_app_icons_gemini.py 执行失败，退出码: {p4.returncode}")
    print(p4.stdout.strip())

    update_icon_cmd = [
        sys.executable,
        str(UPDATE_APPS_ICON_SCRIPT),
        "--mapping-json",
        str(app_icon_match_output),
        "--app-auth-json",
        str(auth_output),
    ]
    if args.base_url:
        update_icon_cmd.extend(["--base-url", args.base_url])
    if args.project_id:
        update_icon_cmd.extend(["--project-id", args.project_id])
    if args.owner_id:
        update_icon_cmd.extend(["--operator-id", args.owner_id])
    if args.dry_run_icon_update:
        update_icon_cmd.append("--dry-run")

    print_cmd("Step 5/5 更新应用 icon", update_icon_cmd)
    p5 = run_command(update_icon_cmd)
    if p5.returncode != 0:
        print(p5.stdout.strip())
        print(p5.stderr.strip())
        raise SystemExit(f"update_app_icons.py 执行失败，退出码: {p5.returncode}")
    print(p5.stdout.strip())

    print("\n流水线执行完成")


if __name__ == "__main__":
    main()
