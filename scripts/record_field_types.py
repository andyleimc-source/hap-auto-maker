#!/usr/bin/env python3
"""
录制 HAP 所有字段类型。

方法：
1. 获取目标工作表当前字段列表和 version
2. 逐个尝试添加 type=1~55 的测试字段
3. 记录哪些 type 可以成功创建
4. 创建后立即删除测试字段（恢复原状）
5. 输出完整的字段类型枚举
"""

from __future__ import annotations
import sys, json, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts" / "hap"))
import auth_retry

AUTH_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
APP_ID = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"
WS_ID = "69ce8328b33e84f2778ba787"  # 市场活动表
REFERER = f"https://www.mingdao.com/worksheet/field/edit?sourceId={WS_ID}"

GET_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/GetWorksheetControls"
SAVE_CONTROLS_URL = "https://www.mingdao.com/api/Worksheet/SaveWorksheetControls"


def get_controls() -> tuple[int, list[dict]]:
    """获取当前字段列表和 version。"""
    resp = auth_retry.hap_web_post(
        GET_CONTROLS_URL, AUTH_PATH, referer=REFERER,
        json={"worksheetId": WS_ID, "appId": APP_ID}, timeout=30
    ).json()
    data = resp.get("data", {}).get("data", resp.get("data", {}))
    version = int(data.get("version", 0))
    controls = data.get("controls", [])
    return version, controls


def try_add_field(field_type: int, version: int, controls: list[dict]) -> tuple[bool, str, int, list[dict]]:
    """尝试添加一个指定 type 的测试字段。返回 (success, name_or_error, new_version, new_controls)。"""
    test_field = {
        "controlId": "",
        "controlName": f"_test_type_{field_type}",
        "type": field_type,
        "attribute": 0,
        "row": 99,
        "col": 0,
        "hint": "",
        "default": "",
        "required": False,
        "unique": False,
        "encryId": "",
        "showControls": [],
        "advancedSetting": {},
    }
    # 某些类型需要额外参数
    if field_type in (9, 10, 11):  # 单选/多选/下拉
        test_field["options"] = [
            {"key": "opt1", "value": "选项A", "index": 0, "isDeleted": False, "color": "#2196F3"},
            {"key": "opt2", "value": "选项B", "index": 1, "isDeleted": False, "color": "#4CAF50"},
        ]

    new_controls = list(controls) + [test_field]
    resp = auth_retry.hap_web_post(
        SAVE_CONTROLS_URL, AUTH_PATH, referer=REFERER,
        json={"version": version, "sourceId": WS_ID, "controls": new_controls}, timeout=30
    ).json()

    state = resp.get("state", 0)
    data = resp.get("data", {})
    if isinstance(data, dict):
        inner = data.get("data", data)
        if isinstance(inner, dict):
            new_version = int(inner.get("version", version))
            new_controls_list = inner.get("controls", controls)
            code = inner.get("code", data.get("code", 0))
            if code == 1 or state == 1:
                # 找到新添加的字段名
                added = [c for c in new_controls_list if c.get("controlName", "").startswith("_test_type_")]
                if added:
                    return True, "", new_version, new_controls_list
                return True, "", new_version, new_controls_list
            return False, str(inner.get("msg", "")), version, controls
    return False, str(resp)[:200], version, controls


def remove_test_field(version: int, controls: list[dict]) -> tuple[int, list[dict]]:
    """移除测试字段。"""
    clean = [c for c in controls if not str(c.get("controlName", "")).startswith("_test_type_")]
    if len(clean) == len(controls):
        return version, controls
    resp = auth_retry.hap_web_post(
        SAVE_CONTROLS_URL, AUTH_PATH, referer=REFERER,
        json={"version": version, "sourceId": WS_ID, "controls": clean}, timeout=30
    ).json()
    data = resp.get("data", {}).get("data", resp.get("data", {}))
    if isinstance(data, dict):
        return int(data.get("version", version)), data.get("controls", clean)
    return version, clean


def main():
    print("=" * 60)
    print("HAP 字段类型录制脚本")
    print(f"工作表: {WS_ID}")
    print("=" * 60)

    version, controls = get_controls()
    print(f"\n当前 version={version}, 字段数={len(controls)}")

    # 保存原始字段 ID 列表
    original_ids = {c.get("controlId") for c in controls}

    valid_types = {}
    invalid_types = []

    for t in range(1, 56):
        ok, err, version, controls = try_add_field(t, version, controls)
        if ok:
            # 找到新字段的实际 type（可能被服务端修正）
            new_fields = [c for c in controls if c.get("controlId") not in original_ids]
            actual_type = t
            actual_name = ""
            for nf in new_fields:
                if str(nf.get("controlName", "")).startswith("_test_type_"):
                    actual_type = nf.get("type", t)
                    actual_name = nf.get("controlName", "")
                    break
            valid_types[t] = {"actual_type": actual_type}
            print(f"  ✓ type={t:2d} → 创建成功 (actual={actual_type})")

            # 立即删除测试字段
            version, controls = remove_test_field(version, controls)
            time.sleep(0.3)
        else:
            invalid_types.append(t)
            if err:
                print(f"  ✗ type={t:2d} → {err[:60]}")
            else:
                print(f"  ✗ type={t:2d}")
            time.sleep(0.2)

    print(f"\n{'=' * 60}")
    print(f"有效字段类型: {len(valid_types)} 种")
    print(f"无效: {len(invalid_types)} 种")
    print(f"\n有效 type 值: {sorted(valid_types.keys())}")

    # 输出到文件
    output = {
        "recorded_at": __import__("datetime").datetime.now().isoformat(),
        "worksheet_id": WS_ID,
        "valid_types": {str(k): v for k, v in sorted(valid_types.items())},
        "invalid_types": invalid_types,
    }
    out_path = BASE_DIR / "data" / "api_docs" / "field_types_recorded.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入: {out_path}")


if __name__ == "__main__":
    main()
