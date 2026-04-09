#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图配置生成器 — 为单个视图生成完整的 advancedSetting 和 postCreateUpdates。

可独立运行：
  python view_configurator.py --recommendation rec.json --fields-json fields.json

也可被 pipeline_views.py 作为模块调用。
"""

from __future__ import annotations

import sys
from pathlib import Path

_HAP_DIR = Path(__file__).resolve().parents[1]
if str(_HAP_DIR) not in sys.path:
    sys.path.insert(0, str(_HAP_DIR))

import argparse
import json
import time
from typing import Any, Dict, List, Optional, Set

from views.view_types import VIEW_REGISTRY
from views.view_config_schema import VIEW_SCHEMA, COMMON_ADVANCED_KEYS
from ai_utils import load_ai_config, get_ai_client, create_generation_config, parse_ai_json


# ── Step 2.5: 配置校验 ───────────────────────────────────────────────────────

def _get_allowed_ad_keys(view_type: int) -> set[str]:
    """获取该视图类型允许的 advancedSetting key 集合。"""
    allowed = set(COMMON_ADVANCED_KEYS.keys())
    registry_entry = VIEW_REGISTRY.get(view_type, {})
    ad_keys = registry_entry.get("advancedSetting_keys", {})
    allowed.update(ad_keys.keys())
    return allowed


def _check_field_ref(value: str, field_ids: set[str]) -> bool:
    """检查一个值是否是合法的字段 ID 引用。"""
    if not value or not isinstance(value, str):
        return True  # 空值合法
    if value.startswith("[") or value.startswith("{"):
        return True  # JSON 字符串不在此检查
    if value.startswith("$") and value.endswith("$"):
        inner = value[1:-1]
        return inner in field_ids
    return value in field_ids


def _try_fix_field_ref(value: str, field_ids: set[str], fields: list[dict]) -> str | None:
    """尝试按字段名匹配修正不存在的字段 ID。返回 None 表示无法修正。"""
    if not value or value in field_ids:
        return value
    # 按名称匹配
    for f in fields:
        fname = str(f.get("name", f.get("controlName", ""))).strip()
        if fname == value:
            return str(f.get("id", f.get("controlId", ""))).strip()
    return None


def validate_view_config(
    config: dict,
    field_ids: set[str],
    fields: list[dict],
) -> dict | None:
    """校验单个视图配置。返回校验后的 config，或 None（丢弃该视图）。

    校验规则：
    1. viewControl 引用的字段 ID 必须存在（看板/资源/地图必需，否则丢弃）
    2. advancedSetting 中未知 key 静默移除
    3. postCreateUpdates 中引用不存在的字段 ID → 尝试修正，失败则移除该条目
    """
    vt = int(config.get("viewType", 0))

    # 1. viewControl 校验（看板/资源/地图必需）
    vc = config.get("viewControl", "")
    needs_vc = vt in (1, 7, 8)
    if needs_vc and vc:
        fixed = _try_fix_field_ref(vc, field_ids, fields)
        if fixed is None:
            print(f"  [validate_config] 丢弃 viewType={vt}（viewControl={vc!r} 不存在）")
            return None
        config["viewControl"] = fixed

    # 2. advancedSetting key 过滤
    ad = config.get("advancedSetting", {})
    if isinstance(ad, dict):
        allowed_keys = _get_allowed_ad_keys(vt)
        unknown = [k for k in ad if k not in allowed_keys]
        for k in unknown:
            print(f"  [validate_config] 移除未知 advancedSetting key: {k}")
            del ad[k]
        config["advancedSetting"] = ad

    # 3. postCreateUpdates 校验
    pcu_list = config.get("postCreateUpdates", [])
    if isinstance(pcu_list, list):
        valid_pcu = []
        for entry in pcu_list:
            if not isinstance(entry, dict):
                continue
            entry_ad = entry.get("advancedSetting", {})
            entry_fields = entry.get("fields", {})

            # 检查 advancedSetting 中的字段引用
            bad = False
            if isinstance(entry_ad, dict):
                for k, v in list(entry_ad.items()):
                    if isinstance(v, str) and v and not v.startswith("[") and not v.startswith("{"):
                        if not _check_field_ref(v, field_ids):
                            fixed = _try_fix_field_ref(v, field_ids, fields)
                            if fixed is None:
                                print(f"  [validate_config] postCreateUpdates 字段引用 {k}={v!r} 不存在，移除条目")
                                bad = True
                                break
                            entry_ad[k] = fixed

            # 检查 fields 中的字段引用
            if not bad and isinstance(entry_fields, dict):
                for k, v in list(entry_fields.items()):
                    if isinstance(v, str) and v:
                        if not _check_field_ref(v, field_ids):
                            fixed = _try_fix_field_ref(v, field_ids, fields)
                            if fixed is None:
                                print(f"  [validate_config] postCreateUpdates.fields {k}={v!r} 不存在，移除条目")
                                bad = True
                                break
                            entry_fields[k] = fixed

            if not bad:
                valid_pcu.append(entry)

        config["postCreateUpdates"] = valid_pcu

    return config


# ── Step 2: AI 配置生成 ──────────────────────────────────────────────────────

def build_config_prompt(
    view_recommendation: dict,
    worksheet_name: str,
    fields: list[dict],
) -> str:
    """为单个视图构建配置 prompt。"""
    vt = view_recommendation.get("viewType", 0)
    view_name = view_recommendation.get("name", "")
    reason = view_recommendation.get("reason", "")

    registry_entry = VIEW_REGISTRY.get(vt, {})
    type_name = registry_entry.get("name", f"视图类型{vt}")
    ad_keys = registry_entry.get("advancedSetting_keys", {})
    top_level_extra = registry_entry.get("top_level_extra", {})
    post_create = registry_entry.get("post_create")

    # advancedSetting key 说明
    ad_lines = []
    for k, desc in sorted(ad_keys.items()):
        ad_lines.append(f"    {k}: {desc}")
    ad_section = "\n".join(ad_lines) if ad_lines else "    （无特殊配置项）"

    # 字段列表
    field_lines = []
    for f in fields:
        fid = f.get("id", f.get("controlId", ""))
        fname = f.get("name", f.get("controlName", ""))
        ftype = f.get("type", "")
        opts = f.get("options", [])
        opt_str = ""
        if opts and isinstance(opts, list):
            vals = [str(o.get("value", "")) for o in opts[:6] if isinstance(o, dict)]
            if vals:
                opt_str = f" 选项: {', '.join(vals)}"
        field_lines.append(f"  {fid} | type={ftype} | {fname}{opt_str}")
    fields_section = "\n".join(field_lines)

    # postCreateUpdates 模板
    pcu_hint = ""
    if post_create:
        pcu_hint = f"""
postCreateUpdates 模板（此视图类型需要二次保存）:
  editAttrs: {post_create.get('editAttrs', [])}
  editAdKeys: {post_create.get('editAdKeys', [])}
  请根据字段列表填入真实字段 ID。"""

    return f"""你是明道云视图配置专家。请为以下视图生成完整配置参数。

## 视图信息
- 类型: {vt} ({type_name})
- 名称: {view_name}
- 推荐理由: {reason}

## 工作表「{worksheet_name}」字段列表
{fields_section}

## 该视图可用的 advancedSetting 配置项
{ad_section}

## 顶层额外参数
{json.dumps(top_level_extra, ensure_ascii=False, indent=2) if top_level_extra else "无"}
{pcu_hint}

## 任务

根据视图类型和字段，输出完整配置。要求：
1. displayControls: 选 5-8 个最重要的字段 ID
2. viewControl: 看板(1)/资源(7)/地图(8) 必须填字段 ID；其他留空
3. advancedSetting: 只填有意义的配置，enablerules 默认 "1"
4. postCreateUpdates: 需要二次保存的视图必须填写，字段 ID 必须来自上方字段列表
5. 所有 JSON 字符串值用紧凑格式（无空格）
6. coverCid: 画廊(3) 填附件字段 ID；其他留空

## 输出格式（严格 JSON）

{{
  "viewType": {vt},
  "name": "{view_name}",
  "displayControls": ["字段ID1", "字段ID2"],
  "viewControl": "",
  "coverCid": "",
  "advancedSetting": {{}},
  "postCreateUpdates": []
}}"""


def configure_single_view(
    view_recommendation: dict,
    worksheet_name: str,
    fields: list[dict],
    field_ids: set[str] | None = None,
    ai_config: dict | None = None,
) -> dict | None:
    """为单个视图生成配置。返回完整配置 dict 或 None（失败）。"""
    start = time.time()
    if field_ids is None:
        field_ids = {
            str(f.get("id", f.get("controlId", ""))).strip()
            for f in fields
        }

    prompt = build_config_prompt(view_recommendation, worksheet_name, fields)

    config = ai_config or load_ai_config()
    client = get_ai_client(config)
    gen_config = create_generation_config(config, temperature=0.2)

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=config.get("model", ""),
                contents=prompt,
                config=gen_config,
            )
            raw_text = response.text if hasattr(response, "text") else str(response)
            raw_json = parse_ai_json(raw_text)
            break
        except Exception as e:
            if attempt < max_retries:
                print(f"  [configure] AI 失败（第{attempt+1}次），重试: {e}")
                time.sleep(1)
            else:
                print(f"  [configure] AI 失败（已重试{max_retries}次）: {e}")
                return None

    # Step 2.5: 校验
    validated = validate_view_config(raw_json, field_ids, fields)
    if validated:
        validated["_stats"] = {"elapsed_s": round(time.time() - start, 2)}
    return validated


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="视图配置生成器（可独立运行）")
    parser.add_argument("--recommendation", required=True, help="推荐结果 JSON 文件（单个视图）")
    parser.add_argument("--fields-json", required=True, help="字段 JSON 文件路径")
    parser.add_argument("--worksheet-name", default="测试表", help="工作表名称")
    parser.add_argument("--output", default="", help="输出 JSON 路径")
    args = parser.parse_args()

    rec = json.loads(Path(args.recommendation).read_text(encoding="utf-8"))
    fields = json.loads(Path(args.fields_json).read_text(encoding="utf-8"))

    result = configure_single_view(rec, args.worksheet_name, fields)

    output_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"配置结果已写入: {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
