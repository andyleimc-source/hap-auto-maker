#!/usr/bin/env python3
"""
一键生成工作流规划 JSON（pipeline_workflows.py）

功能：
  1. 从 data/outputs/app_authorizations/app_authorize_{appId}.json 自动读取
     appKey + sign，通过 HAP v3 API 拉取应用结构
     （应用名称 / 工作表名称 / 字段名称及下拉选项）
  2. 将结构描述提交给 Gemini，为每个工作表规划 5 个工作流：
       - 3 个自定义动作（按钮触发）
       - 1 个工作表事件触发
       - 1 个定时触发
  3. 生成 output/workflow_plan_latest.json，供 execute_workflow_plan.py 执行

认证（自动读取，无需任何参数）：
  appKey + sign 来源优先级：
    1. --app-auth-json 指定的文件
    2. data/outputs/app_authorizations/app_authorize_{relation_id}.json（精确匹配 appId）
    3. data/outputs/app_authorizations/ 下最新的 app_authorize_*.json

Gemini Key 优先级：
  1. --gemini-key 参数
  2. 环境变量 GEMINI_API_KEY

用法示例：
  cd /Users/andy/Desktop/hap_auto/workflow

  # 推荐：全自动，自动从 app_authorize_xxx.json 读取认证
  python3 scripts/pipeline_workflows.py \\
    --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9'

  # 指定授权文件
  python3 scripts/pipeline_workflows.py \\
    --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \\
    --app-auth-json /path/to/app_authorize_xxx.json

  # 指定 Gemini 模型 + 输出路径
  python3 scripts/pipeline_workflows.py \\
    --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \\
    --model gemini-1.5-pro \\
    --output output/my_plan.json
"""

from __future__ import annotations

import json
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time

import requests


# ── 常量 ───────────────────────────────────────────────────────────────────────

# 相对于本脚本的项目根（workflow/../ = hap_auto/）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_APP_AUTH_DIR = _PROJECT_ROOT / "data" / "outputs" / "app_authorizations"

_APP_INFO_URL     = "https://api.mingdao.com/v3/app"
_GEMINI_AUTH_JSON = _PROJECT_ROOT / "config" / "credentials" / "gemini_auth.json"
_WS_LIST_URL      = "https://api.mingdao.com/v3/app"         # GET，sections 里遍历
_WS_DETAIL_URL    = "https://api.mingdao.com/v3/app/worksheets/{ws_id}"


# ── 字段类型映射 ────────────────────────────────────────────────────────────────

_FIELD_TYPE_MAP = {
    2: "文本", 3: "电话", 4: "证件号", 5: "Email", 6: "数字",
    7: "金额", 8: "大写金额", 9: "单选", 10: "多选", 11: "下拉单选",
    14: "附件", 15: "日期", 16: "日期时间", 19: "地区", 21: "自由关联",
    24: "备注", 26: "成员", 27: "部门", 28: "成员(多)", 29: "关联记录",
    30: "查找引用", 31: "公式", 32: "文本公式", 35: "子表",
    36: "检查框", 37: "评分", 40: "定位", 41: "富文本",
    42: "签名", 43: "条形码", 45: "嵌入",
}

_TRIGGER_ID_HINT = """
  trigger_id 可选值：
    "1" = 仅新增记录时触发
    "2" = 新增或更新记录时触发（最常用）
    "3" = 仅更新记录时触发
    "4" = 删除记录时触发
"""

_FREQUENCY_HINT = """
  time_trigger.frequency（周期单位）：
    1  = 每天
    7  = 每周
    30 = 每月
  time_trigger.repeat_type：
    "1" = 重复执行
    "0" = 仅执行一次（忽略 interval/frequency/week_days）
"""


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="自动读取 app_authorize 文件，调用 Gemini 规划工作流，生成 workflow_plan_latest.json。"
    )
    parser.add_argument(
        "--relation-id",
        required=True,
        help="应用 ID（relationId），示例：c2259f27-8b27-4ecb-8def-10fdff5911d9。",
    )
    parser.add_argument(
        "--app-auth-json",
        default="",
        help=("应用授权 JSON 文件路径。留空则自动在 "
              "data/outputs/app_authorizations/ 下按 appId 匹配。"),
    )
    parser.add_argument(
        "--gemini-key",
        default="",
        help="Gemini API Key（也可通过 GEMINI_API_KEY 环境变量提供）。",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.0-flash",
        help="Gemini 模型名称（默认：gemini-2.0-flash）。",
    )
    parser.add_argument(
        "--output",
        default="",
        help="输出文件路径（默认：output/pipeline_workflows_latest.json）。",
    )
    return parser.parse_args()


# ── 读取 app_authorize 文件 ────────────────────────────────────────────────────

def load_app_auth(relation_id: str, app_auth_json: str) -> tuple[str, str, str]:
    """
    返回 (app_id, app_key, sign)。
    优先查找精确匹配 relation_id 的 JSON 文件，否则取最新文件。
    """
    # 如果用户指定了文件
    if app_auth_json:
        p = Path(app_auth_json).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"指定的授权文件不存在：{p}")
    else:
        # 先精确匹配
        exact = _APP_AUTH_DIR / f"app_authorize_{relation_id}.json"
        if exact.exists():
            p = exact
        else:
            # 取最新
            candidates = sorted(
                _APP_AUTH_DIR.glob("app_authorize_*.json"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                raise FileNotFoundError(
                    f"未找到授权文件，请先创建应用或手动指定 --app-auth-json。\n"
                    f"（目录：{_APP_AUTH_DIR}）"
                )
            p = candidates[0]

    print(f"[auth] 使用授权文件：{p.name}", file=sys.stderr)
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = data.get("data") or []

    # 先精确匹配 appId
    for row in rows:
        if isinstance(row, dict) and str(row.get("appId", "")).strip() == relation_id:
            app_key = str(row.get("appKey", "")).strip()
            sign = str(row.get("sign", "")).strip()
            if app_key and sign:
                return relation_id, app_key, sign

    # 如果没有精确匹配，用第一条
    if rows and isinstance(rows[0], dict):
        row = rows[0]
        app_id  = str(row.get("appId", relation_id)).strip()
        app_key = str(row.get("appKey", "")).strip()
        sign    = str(row.get("sign", "")).strip()
        if app_key and sign:
            return app_id, app_key, sign

    raise ValueError(f"授权文件中未找到有效的 appKey/sign：{p}")


# ── 拉取应用结构（HAP v3 API，HAP-Appkey + HAP-Sign Header）─────────────────

def _hap_headers(app_key: str, sign: str) -> dict:
    return {
        "HAP-Appkey": app_key,
        "HAP-Sign": sign,
        "Accept": "application/json, text/plain, */*",
    }


def _walk_sections(sections: list, worksheets: list) -> None:
    """递归遍历 sections，收集 type==0（工作表）的 item。"""
    for sec in sections or []:
        for item in sec.get("items") or []:
            if item.get("type") == 0:
                worksheets.append({
                    "id": str(item.get("id", "")),
                    "name": str(item.get("name", "")),
                })
        _walk_sections(sec.get("childSections") or [], worksheets)


def fetch_app_structure(relation_id: str, app_key: str, sign: str) -> dict:
    """
    通过 HAP v3 API 拉取完整应用结构：
      GET https://api.mingdao.com/v3/app  →  应用名称 + 工作表列表
      GET https://api.mingdao.com/v3/app/worksheets/{ws_id}  →  字段（含选项）
    """
    headers = _hap_headers(app_key, sign)

    # ── Step 1: 拉取应用信息（含工作表列表） ────────────────────────────────────
    print("[fetch] 正在拉取应用信息...", file=sys.stderr)
    resp = requests.get(_APP_INFO_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    app_data = resp.json()

    if not app_data.get("success"):
        raise RuntimeError(
            f"获取应用信息失败（success=false）：{app_data.get('error_msg', app_data)}"
        )

    info = app_data.get("data") or {}
    app_name = str(info.get("name", relation_id)).strip() or relation_id

    # 从 sections 中遍历所有工作表
    raw_worksheets: list[dict] = []
    _walk_sections(info.get("sections") or [], raw_worksheets)
    print(f"[fetch] 应用：{app_name}，发现 {len(raw_worksheets)} 个工作表", file=sys.stderr)

    # ── Step 2: 拉取每个工作表的字段 ────────────────────────────────────────────
    worksheets: list[dict] = []
    for ws in raw_worksheets:
        ws_id   = ws["id"]
        ws_name = ws["name"]
        if not ws_id:
            continue

        print(f"[fetch]   ├─ {ws_name}（{ws_id}）拉取字段...", file=sys.stderr)
        ws_resp = requests.get(
            f"https://api.mingdao.com/v3/app/worksheets/{ws_id}",
            headers=headers,
            timeout=30,
        )
        ws_resp.raise_for_status()
        ws_data = ws_resp.json()

        fields: list[dict] = []
        if ws_data.get("success"):
            controls = (ws_data.get("data") or {}).get("controls") or []
            for ctrl in controls:
                field: dict = {
                    "id":   ctrl.get("controlId") or ctrl.get("id", ""),
                    "name": ctrl.get("controlName") or ctrl.get("name", ""),
                    "type": ctrl.get("type", 0),
                }
                opts = ctrl.get("options") or []
                if opts:
                    field["options"] = [
                        {"key": o.get("key", ""), "value": o.get("value", "")}
                        for o in opts if o.get("value")
                    ]
                fields.append(field)

        print(f"[fetch]      └─ {len(fields)} 个字段", file=sys.stderr)
        worksheets.append({"id": ws_id, "name": ws_name, "fields": fields})

    return {
        "app_name": app_name,
        "app_id": relation_id,
        "worksheets": worksheets,
    }


# ── Gemini 调用 ────────────────────────────────────────────────────────────────

def _describe_app(app_structure: dict) -> str:
    lines = [f"应用名称：{app_structure.get('app_name', '未知应用')}", ""]
    for ws in app_structure.get("worksheets", []):
        lines.append(f"【工作表：{ws['name']}（ID: {ws['id']}）】")
        for f in ws.get("fields", []):
            type_name = _FIELD_TYPE_MAP.get(f["type"], f"type={f['type']}")
            line = f"  - {f['name']}（{type_name}）"
            opts = f.get("options") or []
            if opts:
                opt_str = "、".join(o["value"] for o in opts[:8])
                if len(opts) > 8:
                    opt_str += "…"
                line += f"  可选值：[{opt_str}]"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def _future_date(days_ahead: int = 1, hour: int = 9) -> str:
    dt = datetime.now() + timedelta(days=days_ahead)
    return dt.strftime(f"%Y-%m-%d {hour:02d}:00")


def _end_date(months_ahead: int = 18, hour: int = 9) -> str:
    dt = datetime.now() + timedelta(days=30 * months_ahead)
    return dt.strftime(f"%Y-%m-%d {hour:02d}:00")


def build_prompt(app_structure: dict) -> str:
    app_desc = _describe_app(app_structure)
    app_name = app_structure.get("app_name", "该应用")
    worksheet_ids = [
        {"id": ws["id"], "name": ws["name"]}
        for ws in app_structure.get("worksheets", [])
    ]
    ws_list_json = json.dumps(worksheet_ids, ensure_ascii=False, indent=2)
    ex_time = _future_date(1, 9)
    ex_end  = _end_date(18, 9)

    return f"""你是一位资深的企业数字化顾问，正在为「{app_name}」这个 HAP 明道云应用规划工作流自动化。

以下是该应用的完整结构：

{app_desc}

请为每个工作表规划 **5 个工作流**，内容要专业、贴合业务，像真实企业管理系统中的工作流命名：
  1. custom_actions：3 个自定义动作按钮（name 要体现业务动作，如"审批通过""标记发货""结案处理"）
  2. worksheet_event：1 个工作表事件触发（监听数据变化，触发相关业务流程）
  3. time_trigger：1 个定时触发（定期执行数据维护、状态归档、统计汇总等任务）

规划要求：
- 充分利用字段含义（尤其是下拉选项），让工作流反映字段的业务状态流转
- confirm_msg 要清晰说明操作影响（用户能理解这个操作会做什么）
- worksheet_event 的 trigger_id 要根据业务场景合理选择
- time_trigger 执行时间设为近期（参考：首次执行 {ex_time}，结束时间 {ex_end}）
- 不同工作表的工作流不能雷同，要体现各表的业务特点

{_TRIGGER_ID_HINT}
{_FREQUENCY_HINT}

当前工作表列表（请严格使用这些 worksheet_id，不要编造）：
{ws_list_json}

请严格按以下 JSON 格式返回，不要添加任何解释文字：

{{
  "worksheets": [
    {{
      "worksheet_id": "（来自上方列表）",
      "worksheet_name": "（工作表名称）",
      "custom_actions": [
        {{"name": "...", "confirm_msg": "...", "sure_name": "确认", "cancel_name": "取消"}},
        {{"name": "...", "confirm_msg": "...", "sure_name": "确认", "cancel_name": "取消"}},
        {{"name": "...", "confirm_msg": "...", "sure_name": "确认", "cancel_name": "取消"}}
      ],
      "worksheet_event": {{
        "name": "...",
        "trigger_id": "2"
      }},
      "time_trigger": {{
        "name": "...",
        "execute_time": "{ex_time}",
        "execute_end_time": "{ex_end}",
        "repeat_type": "1",
        "interval": 1,
        "frequency": 7,
        "week_days": []
      }}
    }}
  ]
}}"""


def call_gemini(prompt: str, api_key: str, model: str) -> dict:
    try:
        import google.generativeai as genai  # type: ignore
    except ImportError:
        raise RuntimeError(
            "缺少依赖：请先安装 google-generativeai\n"
            "  pip install google-generativeai"
        )
    genai.configure(api_key=api_key)
    gm = genai.GenerativeModel(
        model,
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )
    print("[gemini] 正在生成工作流规划...", file=sys.stderr)
    response = gm.generate_content(prompt)
    raw = response.text
    print(f"[gemini] 响应长度 {len(raw)} 字符", file=sys.stderr)
    return json.loads(raw)


# ── 输出落盘 ───────────────────────────────────────────────────────────────────

def _write_output(plan: dict, output_arg: str, script_name: str) -> None:
    workflow_dir = Path(__file__).parent.parent
    output_dir = workflow_dir / "output"
    logs_dir   = workflow_dir / "logs"

    if output_arg:
        out_path = Path(output_arg).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[output] {out_path}", file=sys.stderr)
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        latest = output_dir / f"{script_name}_latest.json"
        latest.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[output] output/{script_name}_latest.json", file=sys.stderr)

    # 写日志
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{script_name}_{ts}.json"
    log_path.write_text(
        json.dumps({"script": script_name, "timestamp": datetime.now().isoformat(timespec="seconds"), "output": plan},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[log]    logs/{script_name}_{ts}.json", file=sys.stderr)


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    args = parse_args()
    script_name = Path(__file__).stem

    # 1. 读取 appKey + sign
    print(f"\n[step 1/3] 读取应用授权（relation_id={args.relation_id}）", file=sys.stderr)
    try:
        _, app_key, sign = load_app_auth(args.relation_id, args.app_auth_json)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    # 2. 拉取应用结构
    try:
        app_structure = fetch_app_structure(args.relation_id, app_key, sign)
    except Exception as exc:
        print(f"Error: 拉取应用结构失败：{exc}", file=sys.stderr)
        return 1

    ws_count = len(app_structure.get("worksheets", []))
    if ws_count == 0:
        print("Warning: 未获取到任何工作表。请检查 appKey/sign 是否有效。", file=sys.stderr)
        return 1

    print(
        f"[step 1/3] ✓ 应用：{app_structure['app_name']}，共 {ws_count} 个工作表",
        file=sys.stderr,
    )

    # 3. 获取 Gemini Key（CLI → 环境变量 → gemini_auth.json）
    gemini_key = args.gemini_key or os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key and _GEMINI_AUTH_JSON.exists():
        try:
            gemini_key = json.loads(_GEMINI_AUTH_JSON.read_text(encoding="utf-8")).get("api_key", "").strip()
            if gemini_key:
                print(f"[auth] Gemini Key 来源：{_GEMINI_AUTH_JSON.name}", file=sys.stderr)
        except Exception:
            pass
    if not gemini_key:
        print(
            "Error: 缺少 Gemini API Key。\n"
            "  方式1：export GEMINI_API_KEY=your_key\n"
            "  方式2：--gemini-key your_key\n"
            f"  方式3：在 {_GEMINI_AUTH_JSON} 中设置 api_key 字段",
            file=sys.stderr,
        )
        return 2

    # 4. 调用 Gemini
    print(f"\n[step 2/3] 调用 Gemini（model={args.model}）...", file=sys.stderr)
    try:
        gemini_result = call_gemini(build_prompt(app_structure), gemini_key, args.model)
    except Exception as exc:
        print(f"Error: Gemini 调用失败：{exc}", file=sys.stderr)
        return 1

    planned_worksheets = gemini_result.get("worksheets", [])
    print(f"[step 2/3] ✓ Gemini 规划完成，共 {len(planned_worksheets)} 个工作表", file=sys.stderr)

    # 5. 组装计划
    plan: dict = {
        "app_id": args.relation_id,
        "app_name": app_structure.get("app_name", ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "worksheets": planned_worksheets,
    }

    # 6. 输出
    print(f"\n[step 3/3] 写入规划文件...", file=sys.stderr)
    _write_output(plan, args.output, script_name)

    # 摘要
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"✅ 工作流规划生成完成！", file=sys.stderr)
    print(f"   应用：{plan['app_name']}", file=sys.stderr)
    print(f"   工作表数：{len(plan['worksheets'])}", file=sys.stderr)
    print(f"   预计创建工作流总数：{len(plan['worksheets']) * 5}", file=sys.stderr)
    print(f"   规划文件：output/pipeline_workflows_latest.json", file=sys.stderr)
    print(f"\n   下一步执行：python3 scripts/execute_workflow_plan.py", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
