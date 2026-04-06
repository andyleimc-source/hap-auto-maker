#!/usr/bin/env python3
"""
分析 HAP 应用结构，调用 Gemini 为每个工作表规划工作流，生成 workflow_plan.json。

每个工作表规划 5 个工作流：
  - 3 个自定义动作（按钮触发）
  - 1 个工作表事件触发
  - 1 个定时触发

应用结构获取方式（二选一）：
  方式 A：--app-structure-file  提供手动编写的 JSON 文件（推荐）
  方式 B：--app-key + --app-secret  通过明道云 Open API v1 自动拉取

Gemini 认证：
  环境变量 GEMINI_API_KEY  或  --gemini-key 参数

用法：
  # 方式 A（手动结构文件）
  python3 scripts/generate_workflow_plan.py \\
    --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \\
    --app-structure-file docs/app_structure.json

  # 方式 B（Open API 自动拉取）
  python3 scripts/generate_workflow_plan.py \\
    --relation-id 'c2259f27-8b27-4ecb-8def-10fdff5911d9' \\
    --app-key $MINGDAO_APP_KEY \\
    --app-secret $MINGDAO_APP_SECRET

app_structure.json 格式：
  {
    "app_name": "家具生产订单管理",
    "worksheets": [
      {
        "id": "69aead6f952cd046bb57e3f2",
        "name": "产品信息",
        "fields": [
          {"id": "...", "name": "产品SKU", "type": 2},
          {"id": "...", "name": "产品类别", "type": 9,
           "options": [{"key": "...", "value": "沙发"}]}
        ]
      }
    ]
  }

字段 type 对照：
  2=文本, 6=数字, 9=单选, 10=多选, 11=下拉, 14=附件,
  15=日期, 16=日期时间, 26=成员, 28=部门, 29=关联记录
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "hap"))
from ai_utils import (
    AI_CONFIG_PATH,
    create_generation_config,
    get_ai_client,
    load_ai_config,
    parse_ai_json,
)

sys.path.insert(0, str(Path(__file__).parent))
from workflow_io import persist


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    default_auth_config = project_root / "config" / "credentials" / "auth_config.py"
    parser = argparse.ArgumentParser(
        description="分析应用结构，使用 AI 规划工作流，输出 workflow_plan_latest.json。"
    )
    parser.add_argument("--relation-id", required=True, help="App relationId（应用 ID）。")
    parser.add_argument(
        "--app-structure-file",
        default="",
        help="应用结构 JSON 文件路径（与 --app-key/--app-secret 二选一）。",
    )
    parser.add_argument("--app-key", default="", help="明道云 Open API appKey（用于自动拉取结构）。")
    parser.add_argument("--app-secret", default="", help="明道云 Open API appSecret（用于自动拉取结构）。")
    parser.add_argument(
        "--output",
        default="",
        help="输出文件路径（默认：output/workflow_plan_latest.json）。",
    )
    parser.add_argument(
        "--auth-config",
        default=str(default_auth_config),
        help="auth_config.py 路径（用于加载 Open API key，可选）。",
    )
    parser.add_argument(
        "--config",
        default=str(AI_CONFIG_PATH),
        help="AI 配置 JSON 路径",
    )
    return parser.parse_args()


# ── Open API 拉取应用结构 ─────────────────────────────────────────────────────

def _mingdao_sign(app_key: str, app_secret: str) -> tuple[str, str]:
    """返回 (timestamp_seconds, sign)。sign = md5(appKey + appSecret + timestamp)"""
    ts = str(int(time.time()))
    sign = hashlib.md5(f"{app_key}{app_secret}{ts}".encode()).hexdigest()
    return ts, sign


def fetch_app_structure(relation_id: str, app_key: str, app_secret: str) -> dict:
    """通过明道云 Open API v1 拉取应用下所有工作表及字段信息。"""
    ts, sign = _mingdao_sign(app_key, app_secret)
    base_params = f"appKey={app_key}&sign={sign}&timestamp={ts}"

    # 1. 获取工作表列表
    ws_url = (
        f"https://api.mingdao.com/v1/open/app/getworksheets"
        f"?{base_params}&appId={relation_id}"
    )
    ws_resp = requests.get(ws_url, timeout=20).json()
    if ws_resp.get("error_code", 1) != 1 and not ws_resp.get("data"):
        raise RuntimeError(f"获取工作表列表失败：{ws_resp}")

    worksheets = []
    for ws in ws_resp.get("data", []):
        ws_id = ws.get("worksheetId") or ws.get("id", "")
        ws_name = ws.get("name", "")
        if not ws_id:
            continue

        # 2. 获取每个工作表的字段信息
        ts2, sign2 = _mingdao_sign(app_key, app_secret)
        info_resp = requests.post(
            "https://api.mingdao.com/v1/open/worksheet/getworksheetinfo",
            json={"appKey": app_key, "sign": sign2, "timestamp": ts2, "worksheetId": ws_id},
            timeout=20,
        ).json()

        fields = []
        for ctrl in (info_resp.get("data") or {}).get("controls", []):
            field: dict = {
                "id": ctrl.get("controlId", ""),
                "name": ctrl.get("controlName", ""),
                "type": ctrl.get("type", 0),
            }
            if ctrl.get("options"):
                field["options"] = [
                    {"key": o.get("key", ""), "value": o.get("value", "")}
                    for o in ctrl["options"]
                ]
            fields.append(field)

        worksheets.append({"id": ws_id, "name": ws_name, "fields": fields})

    return {"app_name": relation_id, "worksheets": worksheets}


# ── Gemini 调用 ────────────────────────────────────────────────────────────────

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
    "3" = 删除记录时触发（极少使用）
    "4" = 仅更新记录时触发
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


def _describe_app(app_structure: dict) -> str:
    """将应用结构转换为 Gemini 可理解的自然语言描述。"""
    lines = [f"应用名称：{app_structure.get('app_name', '未知应用')}", ""]
    for ws in app_structure.get("worksheets", []):
        lines.append(f"【工作表：{ws['name']}（ID: {ws['id']}）】")
        for f in ws.get("fields", []):
            type_name = _FIELD_TYPE_MAP.get(f["type"], f"type={f['type']}")
            line = f"  - {f['name']}（{type_name}）"
            if f.get("options"):
                opts = "、".join(o["value"] for o in f["options"][:8])
                if len(f["options"]) > 8:
                    opts += "…"
                line += f"  可选值：[{opts}]"
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

    example_execute_time = _future_date(1, 9)
    example_end_time = _end_date(18, 9)

    return f"""你是一位资深的企业数字化顾问，正在为「{app_name}」这个 HAP 明道云应用规划工作流自动化。

以下是该应用的完整结构：

{app_desc}

请为每个工作表规划 **6 个工作流**，内容要专业、贴合业务，像真实企业管理系统中的工作流命名：
  1. custom_actions：3 个自定义动作按钮（name 要体现业务动作，如"审批通过""标记发货""结案处理"）
  2. worksheet_event：1 个工作表事件触发（监听数据变化，触发相关业务流程）
  3. time_trigger：1 个定时触发（定期执行数据维护、状态归档、统计汇总等任务）
  4. date_trigger：1 个日期字段触发（按工作表中的日期字段到期时自动触发，如合同到期提醒、任务截止日通知）

规划要求：
- 充分利用字段含义（尤其是下拉选项），让工作流反映字段的业务状态流转
- confirm_msg 要清晰说明操作影响（用户能理解这个操作会做什么）
- worksheet_event 的 trigger_id 要根据业务场景合理选择
- time_trigger 执行时间设为近期（参考：首次执行 {example_execute_time}，结束时间 {example_end_time}）
- date_trigger 的 assign_field_id 应选择工作表中的日期/日期时间字段ID（type=15 或 16），也可用系统字段 ctime（创建时间）或 mtime（更新时间）
- 不同工作表的工作流不能雷同，要体现各表的业务特点

{_TRIGGER_ID_HINT}
{_FREQUENCY_HINT}

_DATE_TRIGGER_HINT:
  assign_field_id: 日期字段 ID（工作表中的字段 ID，或系统字段 ctime/mtime）
  execute_time_type: 0=当天指定时刻触发, 1=日期前N单位, 2=日期后N单位
  number: 偏移数量（execute_time_type=1/2 时有效）
  unit: 1=分钟, 2=小时, 3=天
  end_time: 当天执行时刻（HH:MM 格式，execute_time_type=2 时为空字符串）
  frequency: 0=不重复, 1=每年, 2=每月, 3=每周

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
        "execute_time": "{example_execute_time}",
        "execute_end_time": "{example_end_time}",
        "repeat_type": "1",
        "interval": 1,
        "frequency": 7,
        "week_days": []
      }},
      "date_trigger": {{
        "name": "...",
        "assign_field_id": "日期字段ID或ctime/mtime",
        "execute_time_type": 0,
        "number": 0,
        "unit": 3,
        "end_time": "08:00",
        "frequency": 1
      }}
    }}
  ]
}}"""


def call_ai(prompt: str, config_path: str) -> dict:
    ai_config = load_ai_config(Path(config_path).expanduser().resolve())
    client = get_ai_client(ai_config)
    model_name = ai_config["model"]

    print(f"[ai] 正在生成工作流规划（provider={ai_config['provider']}，model={model_name}，thinking=none）...", file=sys.stderr)

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=create_generation_config(
            ai_config,
            response_mime_type="application/json",
            temperature=0.7,
        ),
    )
    raw = response.text
    print(f"[ai] 响应长度 {len(raw)} 字符", file=sys.stderr)
    return parse_ai_json(raw)


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    started_at = time.time()
    args = parse_args()
    script_name = Path(__file__).stem
    log_args = vars(args).copy()
    log_args.pop("app_secret", None)
    log_args.pop("gemini_key", None)

    # 1. 获取应用结构
    app_structure: dict
    if args.app_structure_file:
        p = Path(args.app_structure_file).expanduser().resolve()
        if not p.exists():
            print(f"Error: 文件不存在：{p}", file=sys.stderr)
            persist(script_name, None, args=log_args, error="structure file not found", started_at=started_at)
            return 2
        app_structure = json.loads(p.read_text(encoding="utf-8"))
        print(f"[structure] 从文件加载：{p}", file=sys.stderr)
    elif args.app_key and args.app_secret:
        print("[structure] 通过 Open API 自动拉取...", file=sys.stderr)
        try:
            app_structure = fetch_app_structure(args.relation_id, args.app_key, args.app_secret)
        except Exception as exc:
            print(f"Error: 拉取应用结构失败：{exc}", file=sys.stderr)
            persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
            return 1
    else:
        print(
            "Error: 必须提供 --app-structure-file，或同时提供 --app-key 和 --app-secret。\n"
            "\n"
            "手动创建 app_structure.json 示例（用你的真实 ID 替换）：\n"
            '  {\n'
            '    "app_name": "你的应用名",\n'
            '    "worksheets": [\n'
            '      {\n'
            '        "id": "工作表ID",\n'
            '        "name": "工作表名",\n'
            '        "fields": [\n'
            '          {"id": "字段ID", "name": "字段名", "type": 2}\n'
            '        ]\n'
            '      }\n'
            '    ]\n'
            '  }',
            file=sys.stderr,
        )
        persist(script_name, None, args=log_args, error="missing app structure source", started_at=started_at)
        return 2

    ws_count = len(app_structure.get("worksheets", []))
    print(f"[structure] 应用：{app_structure.get('app_name')}，共 {ws_count} 个工作表", file=sys.stderr)

    # 2. 构建 Prompt 并调用 AI
    prompt = build_prompt(app_structure)
    try:
        ai_result = call_ai(prompt, args.config)
    except Exception as exc:
        print(f"Error: AI 调用失败：{exc}", file=sys.stderr)
        persist(script_name, None, args=log_args, error=str(exc), started_at=started_at)
        return 1

    # 3. 组装最终计划（注入 app_id、generated_at）
    plan: dict = {
        "app_id": args.relation_id,
        "app_name": app_structure.get("app_name", ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": ai_result.get("model", ""),
        "worksheets": ai_result.get("worksheets", []),
    }

    # 5. 输出
    output_path = Path(args.output) if args.output else None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[output] {output_path}", file=sys.stderr)
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2))

    persist(script_name, plan, args=log_args, started_at=started_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
