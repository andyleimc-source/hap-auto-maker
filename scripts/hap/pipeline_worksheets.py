#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交互式工作表流水线：
1) 规划工作表（AI）
2) 创建工作表
3) 匹配并更新工作表 icon
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from script_locator import resolve_script
from gemini_utils import load_gemini_config

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
APP_AUTH_DIR = OUTPUT_ROOT / "app_authorizations"
WORKSHEET_PLAN_DIR = OUTPUT_ROOT / "worksheet_plans"
WORKSHEET_CREATE_RESULT_DIR = OUTPUT_ROOT / "worksheet_create_results"

PLAN_SCRIPT = resolve_script("plan_app_worksheets_gemini.py")
CREATE_SCRIPT = resolve_script("create_worksheets_from_plan.py")
PIPELINE_ICON_SCRIPT = resolve_script("pipeline_icon.py")

APP_INFO_URL = "https://api.mingdao.com/v3/app"


def latest_file(base_dir: Path, pattern: str) -> Optional[Path]:
    files = sorted(base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def extract_json_object(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


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


def discover_apps() -> list[dict]:
    files = sorted(APP_AUTH_DIR.glob("app_authorize_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    apps: list[dict] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = data.get("data")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                app_id = str(row.get("appId", "")).strip()
                app_key = str(row.get("appKey", "")).strip()
                sign = str(row.get("sign", "")).strip()
                if not app_id or not app_key or not sign:
                    continue
                app_name = fetch_app_name(app_key=app_key, sign=sign) or app_id
                apps.append(
                    {
                        "app_id": app_id,
                        "app_name": app_name,
                        "auth_path": str(path.resolve()),
                        "auth_file": path.name,
                        "create_time": str(row.get("createTime", "")).strip(),
                        "app_key": app_key,
                        "sign": sign,
                    }
                )
        except Exception:
            continue

    # 去重：同 appId 只保留最新授权文件
    dedup = {}
    for item in apps:
        if item["app_id"] not in dedup:
            dedup[item["app_id"]] = item
    return list(dedup.values())


def print_apps(apps: list[dict]) -> None:
    print("\n可用应用列表：")
    print("序号 | 应用名称 | 应用ID | 授权文件")
    print("-" * 120)
    for i, app in enumerate(apps, start=1):
        print(f"{i:>4} | {app['app_name']} | {app['app_id']} | {app['auth_file']}")


def ask_app_index(max_index: int) -> int:
    while True:
        raw = input("\n请输入要执行的应用序号: ").strip()
        if not raw.isdigit():
            print("输入无效，请输入数字序号。")
            continue
        idx = int(raw)
        if 1 <= idx <= max_index:
            return idx
        print(f"输入超出范围，请输入 1 到 {max_index}。")


def run_step(cmd: list[str], title: str) -> subprocess.CompletedProcess:
    print(f"\n== {title} ==")
    print("命令:", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        if proc.stdout.strip():
            print(proc.stdout.strip())
        if proc.stderr.strip():
            print(proc.stderr.strip())
        raise SystemExit(f"{title} 失败，退出码: {proc.returncode}")
    return proc


def read_latest_create_result() -> Optional[Path]:
    return latest_file(WORKSHEET_CREATE_RESULT_DIR, "worksheet_create_result_*.json")


# 加载全局配置
try:
    _, GEN_MODEL = load_gemini_config()
except Exception:
    GEN_MODEL = "gemini-2.5-flash"

DEFAULT_MODEL = GEN_MODEL


def main() -> None:
    parser = argparse.ArgumentParser(description="交互式执行：规划工作表 + 创建工作表 + 修改工作表 icon")
    parser.add_argument("--app-index", type=int, default=0, help="可选，直接指定应用序号（免交互）")
    parser.add_argument("--business-context", default="", help="业务背景（不传则交互输入）")
    parser.add_argument("--requirements", default="", help="额外要求（不传则交互输入）")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini 模型名")
    parser.add_argument("--dry-run-create", action="store_true", help="建表步骤仅预览")
    parser.add_argument("--dry-run-icon", action="store_true", help="改 icon 步骤仅预览")
    parser.add_argument("--refresh-auth", action="store_true", help="改 icon 前刷新网页登录认证")
    parser.add_argument("--headless", action="store_true", help="配合 --refresh-auth 无头刷新")
    args = parser.parse_args()

    apps = discover_apps()
    if not apps:
        raise SystemExit(f"未发现可用应用授权文件，请先执行创建应用流程（目录: {APP_AUTH_DIR}）")

    print_apps(apps)
    if args.app_index > 0:
        if args.app_index > len(apps):
            raise SystemExit(f"--app-index 超出范围，当前最大序号为 {len(apps)}")
        picked = apps[args.app_index - 1]
    else:
        picked = apps[ask_app_index(len(apps)) - 1]

    app_name = picked["app_name"]
    app_id = picked["app_id"]
    auth_path = Path(picked["auth_path"]).resolve()

    business_context = args.business_context.strip() or input("请输入业务背景: ").strip()
    requirements = args.requirements.strip() or input("请输入额外要求: ").strip()
    if not business_context:
        business_context = "通用企业管理场景"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    plan_output = (WORKSHEET_PLAN_DIR / f"worksheet_plan_{app_id}_{ts}.json").resolve()

    cmd1 = [
        sys.executable,
        str(PLAN_SCRIPT),
        "--app-name",
        app_name,
        "--business-context",
        business_context,
        "--requirements",
        requirements,
        "--model",
        args.model,
        "--output",
        str(plan_output),
    ]
    proc1 = run_step(cmd1, "Step 1/3 规划工作表")
    if proc1.stdout.strip():
        print(proc1.stdout.strip())

    cmd2 = [
        sys.executable,
        str(CREATE_SCRIPT),
        "--plan-json",
        str(plan_output),
        "--app-auth-json",
        str(auth_path),
    ]
    if args.dry_run_create:
        cmd2.append("--dry-run")
    proc2 = run_step(cmd2, "Step 2/3 创建工作表")
    create_obj = extract_json_object(proc2.stdout)
    if create_obj and isinstance(create_obj, dict):
        created = create_obj.get("created_worksheets", [])
        rel = create_obj.get("relation_updates", [])
        print("建表完成（概览）")
        print(f"- 创建工作表数量: {len(created) if isinstance(created, list) else 0}")
        print(f"- 关联字段回填数量: {len(rel) if isinstance(rel, list) else 0}")
    elif args.dry_run_create and proc2.stdout.strip():
        dry_obj = extract_json_object(proc2.stdout)
        if dry_obj:
            plan = dry_obj.get("create_plan", [])
            print(f"建表预览（概览）: 计划创建 {len(plan) if isinstance(plan, list) else 0} 张表")
    else:
        print("建表完成（未解析到概览 JSON，请查看结果文件）")

    cmd3 = [
        sys.executable,
        str(PIPELINE_ICON_SCRIPT),
        "--app-auth-json",
        str(auth_path),
        "--app-id",
        app_id,
    ]
    if args.refresh_auth:
        cmd3.append("--refresh-auth")
    if args.headless:
        cmd3.append("--headless")
    if args.dry_run_icon:
        cmd3.append("--dry-run")
    proc3 = run_step(cmd3, "Step 3/3 匹配并更新工作表 icon")
    # pipeline_icon 输出已经是简版摘要，只打印末尾关键行
    out3 = proc3.stdout.strip()
    if out3:
        lines = [ln for ln in out3.splitlines() if ln.strip()]
        tail = lines[-4:] if len(lines) > 4 else lines
        print("\n".join(tail))

    latest_create = read_latest_create_result()
    print("\n流水线执行完成")
    print(f"- 应用: {app_name} ({app_id})")
    print(f"- 授权文件: {auth_path}")
    print(f"- 规划文件: {plan_output}")
    if latest_create and not args.dry_run_create:
        print(f"- 建表结果: {latest_create.resolve()}")


if __name__ == "__main__":
    main()
