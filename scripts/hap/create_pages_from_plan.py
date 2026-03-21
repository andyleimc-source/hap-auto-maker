#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据 page_plan JSON 创建自定义页面，并在每个页面中生成统计图。

对每个 Page 执行：
  1. AddWorkSheet   — 创建 Page，获得 pageId
  2. savePage       — 初始化空白 Page（version=0）
  3. pipeline_charts.py — 为该 Page 规划并创建统计图
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List

import auth_retry

BASE_DIR = Path(__file__).resolve().parents[2]
CURRENT_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = BASE_DIR / "data" / "outputs"
PAGE_PLAN_DIR = OUTPUT_ROOT / "page_plans"
PAGE_CREATE_DIR = OUTPUT_ROOT / "page_create_results"
LOG_DIR = BASE_DIR / "data" / "logs"
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

ADD_WORKSHEET_URL = "https://www.mingdao.com/api/AppManagement/AddWorkSheet"
SAVE_PAGE_URL = "https://api.mingdao.com/report/custom/savePage"
GET_PAGE_URL = "https://api.mingdao.com/report/custom/getPage"


# ---------------------------------------------------------------------------
# 日志工具
# ---------------------------------------------------------------------------

class Logger:
    def __init__(self, log_path: Path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._f = log_path.open("a", encoding="utf-8")
        self._path = log_path
        self._print(f"=== create_pages_from_plan 启动 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")

    def log(self, msg: str) -> None:
        self._print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _print(self, msg: str) -> None:
        print(msg)
        self._f.write(msg + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()

    @property
    def path(self) -> Path:
        return self._path


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_plan_path(value: str) -> Path:
    if value:
        p = Path(value).expanduser()
        if p.is_absolute() and p.exists():
            return p.resolve()
        if p.exists():
            return p.resolve()
        candidate = (PAGE_PLAN_DIR / value).resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"找不到规划文件: {value}")
    latest = PAGE_PLAN_DIR / "page_plan_latest.json"
    if latest.exists():
        return latest.resolve()
    files = sorted(PAGE_PLAN_DIR.glob("page_plan_*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if files:
        return files[0].resolve()
    raise FileNotFoundError(f"未找到规划文件（目录: {PAGE_PLAN_DIR}）")


# ---------------------------------------------------------------------------
# API 调用
# ---------------------------------------------------------------------------

def create_page(app_id: str, app_section_id: str, project_id: str,
                page_name: str, icon: str, icon_color: str,
                auth_config_path: Path) -> str:
    """调用 AddWorkSheet 创建自定义 Page，返回 pageId。"""
    icon_url = f"https://fp1.mingdaoyun.cn/customIcon/{icon}.svg"
    body = {
        "appId": app_id,
        "appSectionId": app_section_id,
        "name": page_name,
        "remark": "",
        "iconColor": icon_color,
        "projectId": project_id,
        "icon": icon,
        "iconUrl": icon_url,
        "type": 1,        # 1 = 自定义页
        "createType": 0,
    }
    resp = auth_retry.hap_web_post(ADD_WORKSHEET_URL, auth_config_path, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # 响应格式: {"data": {"pageId": "..."}, "state": 1}
    is_ok = data.get("state") == 1 or data.get("status") == 1
    if not is_ok:
        raise RuntimeError(f"AddWorkSheet 失败: {data}")
    page_id = str(data.get("data", {}).get("pageId", "")).strip()
    if not page_id:
        raise RuntimeError(f"AddWorkSheet 未返回 pageId: {data}")
    return page_id


def initialize_page(page_id: str, auth_config_path: Path) -> None:
    """用 savePage（version=0, components=[]）初始化空白 Page。"""
    body = {
        "appId": page_id,
        "version": 0,
        "components": [],
        "adjustScreen": False,
        "urlParams": [],
        "config": {
            "pageStyleType": "light",
            "pageBgColor": "#f5f6f7",
            "chartColor": "",
            "chartColorIndex": 1,
            "numberChartColor": "",
            "numberChartColorIndex": 1,
            "pivoTableColor": "",
            "refresh": 0,
            "headerVisible": True,
            "shareVisible": True,
            "chartShare": True,
            "chartExportExcel": True,
            "downloadVisible": True,
            "fullScreenVisible": True,
            "customColors": [],
            "webNewCols": 48,
        },
    }
    resp = auth_retry.hap_web_post(SAVE_PAGE_URL, auth_config_path, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    is_ok = data.get("status") == 1 or data.get("success") is True
    if not is_ok:
        raise RuntimeError(f"初始化 Page 失败: {data}")


# ---------------------------------------------------------------------------
# 子进程调用 pipeline_charts.py
# ---------------------------------------------------------------------------

def run_pipeline_charts(
    app_id: str,
    app_name: str,
    worksheet_ids: List[str],
    page_id: str,
    auth_config: str,
    chart_plan_output: str,
    chart_create_output: str,
    log: Logger,
) -> dict:
    """调用 pipeline_charts.py 为指定 page 规划并创建统计图。"""
    script = CURRENT_DIR / "pipeline_charts.py"
    cmd = [
        sys.executable, str(script),
        "--app-id", app_id,
        "--app-name", app_name,
        "--worksheet-ids", ",".join(worksheet_ids),
        "--page-id", page_id,
        "--auth-config", auth_config,
        "--plan-output", chart_plan_output,
        "--create-output", chart_create_output,
    ]
    log.log(f"    CMD: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

    # 写子进程输出到日志
    if proc.stdout:
        for line in proc.stdout.splitlines():
            log.log(f"    | {line}")
    if proc.stderr:
        for line in proc.stderr.splitlines():
            log.log(f"    ERR | {line}")

    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="根据 page_plan 创建自定义页面并生成统计图")
    parser.add_argument("--plan-json", default="", help="page_plan JSON 文件路径（默认取最新）")
    parser.add_argument("--auth-config", default=str(AUTH_CONFIG_PATH), help="auth_config.py 路径")
    parser.add_argument("--output", default="", help="结果 JSON 输出路径（可选）")
    parser.add_argument("--dry-run", action="store_true", help="仅演练，不实际创建 Page 和图表")
    args = parser.parse_args()

    plan_path = resolve_plan_path(args.plan_json)
    plan = load_json(plan_path)
    pages: List[dict] = plan.get("pages", [])
    app_id: str = str(plan.get("appId", "")).strip()
    app_name: str = str(plan.get("appName", "")).strip()
    project_id: str = str(plan.get("projectId", "")).strip()
    app_section_id: str = str(plan.get("appSectionId", "")).strip()

    if not pages:
        raise ValueError("规划文件中没有 pages")
    if not app_id:
        raise ValueError("规划文件缺少 appId")
    if not project_id or not app_section_id:
        raise ValueError("规划文件缺少 projectId 或 appSectionId（请重新运行 plan_pages_gemini.py）")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = Logger(LOG_DIR / f"create_pages_{app_id}_{ts}.log")

    auth_config_path = Path(args.auth_config).expanduser().resolve()
    auth_config = str(auth_config_path)

    log.log(f"应用: {app_name} ({app_id})")
    log.log(f"规划文件: {plan_path}")
    log.log(f"准备创建 {len(pages)} 个 Page，dry-run={args.dry_run}\n")

    results = []
    success_count = 0

    for i, page in enumerate(pages, 1):
        page_name = str(page.get("name", f"Page{i}")).strip()
        icon = str(page.get("icon", "dashboard")).strip()
        icon_color = str(page.get("iconColor", "#2196F3")).strip()
        ws_ids: List[str] = [str(wid).strip() for wid in page.get("worksheetIds", []) if str(wid).strip()]
        ws_names = "、".join(page.get("worksheetNames", ws_ids))
        desc = str(page.get("desc", "")).strip()

        log.log(f"{'='*60}")
        log.log(f"[{i}/{len(pages)}] Page: {page_name}")
        log.log(f"  图标: {icon}  颜色: {icon_color}")
        log.log(f"  描述: {desc}")
        log.log(f"  工作表: {ws_names}")

        page_result: dict = {
            "pageName": page_name,
            "icon": icon,
            "iconColor": icon_color,
            "desc": desc,
            "worksheetIds": ws_ids,
        }

        if args.dry_run:
            log.log(f"  [dry-run] 跳过 Page 创建和图表生成")
            page_result["status"] = "dry-run"
            results.append(page_result)
            continue

        # Step A: 创建 Page
        try:
            log.log(f"  [A] 创建 Page...")
            page_id = create_page(app_id, app_section_id, project_id,
                                  page_name, icon, icon_color, auth_config_path)
            log.log(f"  [A] OK  pageId={page_id}")
            page_result["pageId"] = page_id
        except Exception as exc:
            log.log(f"  [A] 失败: {exc}")
            page_result["status"] = "error_create_page"
            page_result["error"] = str(exc)
            results.append(page_result)
            continue

        # Step B: 初始化空白 Page
        try:
            log.log(f"  [B] 初始化 Page...")
            initialize_page(page_id, auth_config_path)
            log.log(f"  [B] OK")
        except Exception as exc:
            log.log(f"  [B] 警告（初始化失败，继续创建图表）: {exc}")
            # 初始化失败不是致命错误，继续

        # Step C: 创建统计图
        chart_plan_path = str((OUTPUT_ROOT / "chart_plans" /
                               f"chart_plan_{app_id}_page_{page_id}.json").resolve())
        chart_create_path = str((PAGE_CREATE_DIR /
                                 f"chart_create_{app_id}_page_{page_id}.json").resolve())
        PAGE_CREATE_DIR.mkdir(parents=True, exist_ok=True)

        log.log(f"  [C] 调用 pipeline_charts.py 创建统计图...")
        chart_result = run_pipeline_charts(
            app_id=app_id,
            app_name=f"{app_name}-{page_name}",
            worksheet_ids=ws_ids,
            page_id=page_id,
            auth_config=auth_config,
            chart_plan_output=chart_plan_path,
            chart_create_output=chart_create_path,
            log=log,
        )

        if chart_result["returncode"] == 0:
            log.log(f"  [C] OK  图表创建成功")
            page_result["status"] = "success"
            page_result["chartPlanFile"] = chart_plan_path
            page_result["chartCreateFile"] = chart_create_path
            success_count += 1
        else:
            log.log(f"  [C] 图表创建失败（returncode={chart_result['returncode']}）")
            page_result["status"] = "error_charts"
            page_result["chartReturncode"] = chart_result["returncode"]

        results.append(page_result)

    # 汇总结果
    summary = {
        "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "appId": app_id,
        "appName": app_name,
        "planFile": str(plan_path),
        "totalPages": len(pages),
        "successCount": success_count,
        "logFile": str(log.path),
        "results": results,
    }

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        PAGE_CREATE_DIR.mkdir(parents=True, exist_ok=True)
        output_path = (PAGE_CREATE_DIR / f"page_create_{app_id}_{ts}.json").resolve()
        write_json(PAGE_CREATE_DIR / "page_create_latest.json", summary)

    write_json(output_path, summary)

    log.log(f"\n{'='*60}")
    log.log(f"全部完成：{success_count}/{len(pages)} 个 Page 成功")
    for r in results:
        status_icon = "✓" if r.get("status") == "success" else ("~" if r.get("status") == "dry-run" else "✗")
        pid = r.get("pageId", "-")
        log.log(f"  {status_icon} {r['pageName']}  pageId={pid}  status={r.get('status','?')}")
    log.log(f"\n结果文件: {output_path}")
    log.log(f"日志文件: {log.path}")
    log.close()

    print(f"\n完成：{success_count}/{len(pages)} 个 Page 成功")
    print(f"结果文件: {output_path}")

    if success_count == 0 and len(pages) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
