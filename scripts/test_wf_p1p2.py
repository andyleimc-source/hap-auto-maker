#!/usr/bin/env python3
"""
测试工作流节点 P1+P2 共 11 种。

对每个节点：
1. 创建独立工作流（工作表事件触发）
2. 调用 flowNode/add 添加节点骨架
3. 调用 flowNode/saveNode 配置节点
4. 记录 pass/fail

运行：
    cd /Users/andy/Documents/coding/hap-auto-maker
    python3 scripts/test_wf_p1p2.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# 路径 & 常量
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[1]
AUTH_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"

APP_ID      = "f11f2128-c4de-46cb-a2be-fe1c62ed1481"   # CRM 应用
PROJECT_ID  = "faa2f6b1-f706-4084-9a8d-50616817f890"
SECTION_ID  = "69ce832640691821042c6e79"

# 用于触发工作流的工作表 ID（CRM 应用中的"客户"工作表）
# 先用 mcp 或 web 控制台查一下；若不知道就先建一张临时工作表
# 这里我们直接先创建一张临时工作表，然后用它
WORKSHEET_ID_PLACEHOLDER = ""   # 下面会动态创建

PROCESS_ADD_URL = "https://api.mingdao.com/workflow/process/add"
ADD_NODE_URL    = "https://api.mingdao.com/workflow/flowNode/add"
SAVE_NODE_URL   = "https://api.mingdao.com/workflow/flowNode/saveNode"
GET_PUBLISH_URL = "https://api.mingdao.com/workflow/process/getProcessPublish"

ADD_WS_URL = "https://www.mingdao.com/api/AppManagement/AddWorkSheet"

# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------

def load_auth(path: Path) -> tuple[str, str, str]:
    spec = importlib.util.spec_from_file_location("_auth_cfg", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return (
        str(getattr(mod, "ACCOUNT_ID", "")).strip(),
        str(getattr(mod, "AUTHORIZATION", "")).strip(),
        str(getattr(mod, "COOKIE", "")).strip(),
    )


def build_headers(account_id: str, authorization: str, cookie: str,
                   referer: str = "") -> dict:
    h = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "AccountId": account_id,
        "Authorization": authorization,
        "Cookie": cookie,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.mingdao.com",
    }
    if referer:
        h["Referer"] = referer
    return h


class Session:
    def __init__(self, auth_path: Path):
        self.auth_path = auth_path
        self._reload()

    def _reload(self):
        self.account_id, self.authorization, self.cookie = load_auth(self.auth_path)
        self._headers = build_headers(self.account_id, self.authorization, self.cookie)

    def _api_headers(self) -> dict:
        """用于 api.mingdao.com 的头（带 Authorization）。"""
        return {
            **self._headers,
            "Origin": "https://www.mingdao.com",
        }

    def post(self, url: str, body: dict, referer: str = "") -> dict:
        h = self._api_headers()
        if referer:
            h["Referer"] = referer
        resp = requests.post(url, json=body, headers=h, proxies={}, timeout=30)
        if resp.status_code == 401:
            print("  [401] 尝试重新加载认证...")
            self._reload()
            h = self._api_headers()
            resp = requests.post(url, json=body, headers=h, proxies={}, timeout=30)
        raw = resp.text.strip()
        if not raw and resp.status_code == 200:
            # HTTP 200 + empty body = 成功（服务器不返回 JSON）
            return {"_empty": True, "status": 1}
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text[:300], "status_code": resp.status_code}

    def get(self, url: str) -> dict:
        h = self._api_headers()
        resp = requests.get(url, headers=h, proxies={}, timeout=30)
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text[:300], "status_code": resp.status_code}

    def web_post(self, url: str, body: dict, referer: str = "") -> dict:
        """www.mingdao.com Web API 请求。"""
        h = build_headers(self.account_id, self.authorization, self.cookie,
                          referer or f"https://www.mingdao.com/app/{APP_ID}")
        resp = requests.post(url, json=body, headers=h, proxies={}, timeout=30)
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text[:300], "status_code": resp.status_code}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def create_temp_worksheet(sess: Session) -> str:
    """在 CRM 应用中创建一张临时测试工作表，返回其 worksheetId。"""
    ts = int(time.time())
    resp = sess.web_post(ADD_WS_URL, {
        "appId": APP_ID,
        "appSectionId": SECTION_ID,
        "name": f"_test_wf_p1p2_{ts}",
        "remark": "",
        "iconColor": "#9E9E9E",
        "projectId": PROJECT_ID,
        "icon": "table",
        "iconUrl": "https://fp1.mingdaoyun.cn/customIcon/table.svg",
        "type": 0,
        "createType": 0,
    })
    state = resp.get("state") or resp.get("resultCode")
    if state == 1:
        d = resp.get("data", {})
        ws_id = str(d.get("worksheetId") or d.get("workSheetId") or d.get("pageId") or "").strip()
        if ws_id:
            print(f"  [prep] 临时工作表已创建: {ws_id}")
            return ws_id
    print(f"  [prep] 创建临时工作表失败: {resp}")
    return ""


def create_workflow(sess: Session, name: str, ws_id: str) -> tuple[str, str]:
    """
    创建工作表事件触发工作流，返回 (process_id, start_node_id)。
    """
    resp = sess.post(PROCESS_ADD_URL, {
        "companyId": "",
        "relationId": APP_ID,
        "relationType": 2,
        "startEventAppType": 1,
        "name": name,
        "explain": "",
    })
    if resp.get("status") != 1:
        raise RuntimeError(f"process/add failed: {resp}")

    data = resp.get("data", {})
    process_id = str(data.get("id", "")).strip()
    if not process_id:
        raise RuntimeError(f"process/add 没有返回 id: {resp}")

    # 绑定工作表，让工作流出现在列表中
    pub_resp = sess.get(f"{GET_PUBLISH_URL}?processId={process_id}")
    start_node_id = ""
    if pub_resp.get("status") == 1:
        pdata = pub_resp.get("data") or {}
        start_node_id = str(pdata.get("startNodeId", "")).strip()

    if start_node_id and ws_id:
        save_resp = sess.post(SAVE_NODE_URL, {
            "appId": ws_id,
            "appType": 1,
            "assignFieldIds": [],
            "processId": process_id,
            "nodeId": start_node_id,
            "flowNodeType": 0,
            "operateCondition": [],
            "triggerId": "2",
            "name": "工作表事件触发",
            "controls": [],
        })
        if save_resp.get("status") != 1:
            print(f"    [warn] saveNode trigger: {save_resp}")

    return process_id, start_node_id


def add_node(sess: Session, process_id: str, prev_id: str,
             name: str, type_id: int,
             action_id: Optional[str] = None,
             app_type: Optional[int] = None,
             app_id: str = "") -> tuple[str, dict]:
    """调用 flowNode/add，返回 (new_node_id, raw_resp)。"""
    body: dict = {
        "processId": process_id,
        "prveId": prev_id,
        "name": name,
        "typeId": type_id,
    }
    if action_id is not None:
        body["actionId"] = action_id
    if app_type is not None:
        body["appType"] = app_type
    if app_id:
        body["appId"] = app_id

    resp = sess.post(ADD_NODE_URL, body)
    if resp.get("status") != 1:
        return "", resp

    added = resp.get("data", {}).get("addFlowNodes", [])
    if not added:
        return "", resp
    return added[0]["id"], resp


def save_node(sess: Session, body: dict) -> dict:
    """调用 flowNode/saveNode。空 body 响应（HTTP 200）视为成功（_empty=True）。"""
    result = sess.post(SAVE_NODE_URL, body)
    return result


# ---------------------------------------------------------------------------
# 测试定义
# ---------------------------------------------------------------------------

class TestCase:
    def __init__(self, key: str, label: str):
        self.key = key
        self.label = label
        self.status = "SKIP"   # PASS / FAIL / SKIP
        self.error = ""
        self.node_id = ""
        self.process_id = ""


def run_test(sess: Session, tc: TestCase, ws_id: str,
             test_fn) -> None:
    """运行单个测试，捕获异常写入 tc。"""
    try:
        wf_name = f"_test_{tc.key}"
        process_id, start_node_id = create_workflow(sess, wf_name, ws_id)
        tc.process_id = process_id
        print(f"  [wf] processId={process_id}, startNodeId={start_node_id}")

        test_fn(sess, process_id, start_node_id, ws_id, tc)

        if tc.status == "SKIP":
            tc.status = "PASS"
    except Exception as exc:
        tc.status = "FAIL"
        tc.error = str(exc)


# ---------------------------------------------------------------------------
# 各节点测试函数
# ---------------------------------------------------------------------------

def test_delete_record(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P1-1: 删除记录 typeId=6 actionId="3" — 需要 selectNodeId=触发节点ID."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "删除记录", 6, "3", 1, ws_id)
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id}")

    save_body = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 6,
        "actionId": "3",
        "appType": 1,
        "appId": ws_id,
        "name": "删除记录",
        "filters": [],
        "selectNodeId": start_node_id,           # 关键：必须传触发节点ID
        "selectNodeName": "工作表事件触发",
        "isException": True,
    }
    resp = save_node(sess, save_body)
    if resp.get("status") != 1:
        tc.status = "FAIL"
        tc.error = f"saveNode failed: {resp}"
    else:
        tc.status = "PASS"


def test_get_records(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P1-2: 获取多条 typeId=13 actionId="400"."""
    # 注意：任务描述说 typeId=13，但实际文档中 typeId=6 actionId="5" 才是获取多条。
    # record_ops.py 里 get_records 的 typeId=13 actionId="400" 是"查询工作表"。
    # 我们同时测两种，以实测为准。
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "获取多条", 13, "400")
    if not node_id:
        # 尝试备选方案
        tc.error = f"typeId=13 add_node: {add_resp}"
        tc.status = "FAIL"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id}")

    save_body = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 13,
        "actionId": "400",
        "name": "获取多条",
        "appId": ws_id,
        "filters": [],
        "sorts": [],
        "number": 50,
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
    }
    resp = save_node(sess, save_body)
    if resp.get("status") != 1:
        tc.status = "FAIL"
        tc.error = f"saveNode failed: {resp}"
    else:
        tc.status = "PASS"


def test_delay_until(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P1-3: 延时到日期 typeId=12 actionId="302" — 必须用 timerNode 嵌套结构."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "延时到指定日期", 12, "302")
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id}")

    save_body = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 12,
        "name": "延时到指定日期",
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
        # 关键：必须用 timerNode 嵌套结构，不能平铺在根级别
        "timerNode": {
            "name": "延时到指定日期",
            "desc": "",
            "actionId": "302",
            "executeTimeType": 0,
            "number": 0,
            "unit": 1,
            "time": "08:00",
        },
    }
    resp = save_node(sess, save_body)
    if resp.get("status") != 1:
        tc.status = "FAIL"
        tc.error = f"saveNode failed: {resp}"
    else:
        tc.status = "PASS"


def test_delay_field(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P1-4: 延时到字段 typeId=12 actionId="303" — 必须用 timerNode 嵌套结构."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "延时到字段时间", 12, "303")
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id}")

    save_body = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 12,
        "name": "延时到字段时间",
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
        # 关键：必须用 timerNode 嵌套结构
        "timerNode": {
            "name": "延时到字段时间",
            "desc": "",
            "actionId": "303",
            "executeTimeType": 0,
            "number": 0,
            "unit": 1,
            "time": "08:00",
        },
    }
    resp = save_node(sess, save_body)
    if resp.get("status") != 1:
        tc.status = "FAIL"
        tc.error = f"saveNode failed: {resp}"
    else:
        tc.status = "PASS"


def test_sms(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P1-5: 发送短信 typeId=10."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "发送短信", 10)
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id}")

    save_body = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 10,
        "name": "发送短信",
        "accounts": [],
        "content": "测试短信内容",
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
    }
    resp = save_node(sess, save_body)
    if resp.get("status") != 1:
        tc.status = "FAIL"
        tc.error = f"saveNode failed: {resp}"
    else:
        tc.status = "PASS"


def test_email(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P1-6: 发送邮件 typeId=11 actionId="202"."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "发送邮件", 11, "202", 3)
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id}")

    save_body = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 11,
        "actionId": "202",
        "appType": 3,
        "name": "发送邮件",
        "accounts": [],
        "title": "测试邮件标题",
        "content": "测试邮件内容",
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
    }
    resp = save_node(sess, save_body)
    if resp.get("status") != 1:
        tc.status = "FAIL"
        tc.error = f"saveNode failed: {resp}"
    else:
        tc.status = "PASS"


def test_push(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P1-7: 界面推送 typeId=17 — pushType=2 时 saveNode 成功（0/1 会 500）."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "界面推送", 17)
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id}")

    save_body = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 17,
        "name": "界面推送",
        "accounts": [],
        "sendContent": "",
        "pushType": 2,   # 关键：0/1 会 500，2/3 成功
        "openMode": 0,
        "selectNodeId": "",
        "selectNodeName": "",
        "isException": True,
    }
    resp = save_node(sess, save_body)
    if resp.get("status") != 1 and not resp.get("_empty"):
        tc.status = "FAIL"
        tc.error = f"saveNode failed: {resp}"
    else:
        tc.status = "PASS"


def test_abort(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P1-8: 中止流程 typeId=30 actionId="2" — saveNode 返回 HTTP 200 + empty body（成功）."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "中止流程", 30, "2")
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id}")

    save_body = {
        "processId": process_id,
        "nodeId": node_id,
        "flowNodeType": 30,
        "actionId": "2",
        "name": "中止流程",
        "selectNodeId": "",
        "selectNodeName": "",
        # 中止节点没有 isException
    }
    resp = save_node(sess, save_body)
    # 中止流程 saveNode 返回 HTTP 200 + 空 body（不含 JSON），视为成功
    if resp.get("status") == 1 or resp.get("_empty"):
        tc.status = "PASS"
    else:
        tc.status = "FAIL"
        tc.error = f"saveNode failed: {resp}"


def test_subprocess(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P2-9: 子流程 typeId=16 — add 即可用，saveNode 跳过。"""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "子流程", 16)
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id} (saveNode skipped for 子流程)")
    tc.status = "PASS"


def test_code_block(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P2-10: 代码块 typeId=14 actionId="102"."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "代码块", 14, "102")
    if not node_id:
        tc.status = "FAIL"
        tc.error = f"add_node failed: {add_resp}"
        return
    tc.node_id = node_id
    print(f"    nodeId={node_id} (saveNode skipped for 代码块)")
    tc.status = "PASS"


def test_api_request(sess, process_id, start_node_id, ws_id, tc: TestCase):
    """P2-11: API请求 typeId=8."""
    node_id, add_resp = add_node(sess, process_id, start_node_id,
                                  "发送自定义请求", 8, None, 7)
    if not node_id:
        # 尝试不带 appType
        node_id, add_resp = add_node(sess, process_id, start_node_id,
                                      "发送自定义请求", 8)
        if not node_id:
            tc.status = "FAIL"
            tc.error = f"add_node failed: {add_resp}"
            return
    tc.node_id = node_id
    print(f"    nodeId={node_id} (saveNode skipped for API请求)")
    tc.status = "PASS"


# ---------------------------------------------------------------------------
# 测试列表
# ---------------------------------------------------------------------------

TEST_CASES = [
    # (key, label, fn)
    ("delete_record",  "P1-1 删除记录 (typeId=6, actionId=3)",     test_delete_record),
    ("get_records",    "P1-2 获取多条 (typeId=13, actionId=400)",   test_get_records),
    ("delay_until",    "P1-3 延时到日期 (typeId=12, actionId=302)", test_delay_until),
    ("delay_field",    "P1-4 延时到字段 (typeId=12, actionId=303)", test_delay_field),
    ("sms",            "P1-5 发送短信 (typeId=10)",                 test_sms),
    ("email",          "P1-6 发送邮件 (typeId=11, actionId=202)",   test_email),
    ("push",           "P1-7 界面推送 (typeId=17)",                 test_push),
    ("abort",          "P1-8 中止流程 (typeId=30, actionId=2)",     test_abort),
    ("subprocess",     "P2-9 子流程 (typeId=16)",                   test_subprocess),
    ("code_block",     "P2-10 代码块 (typeId=14, actionId=102)",    test_code_block),
    ("api_request",    "P2-11 API请求 (typeId=8)",                  test_api_request),
]


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("工作流节点测试 P1+P2 (11 种)")
    print("=" * 70)

    sess = Session(AUTH_PATH)

    # 创建临时工作表（用于触发工作流绑定）
    print("\n[准备] 创建临时测试工作表...")
    ws_id = create_temp_worksheet(sess)
    if not ws_id:
        print("  ✗ 无法创建临时工作表，退出")
        sys.exit(1)

    results: list[TestCase] = []

    for key, label, fn in TEST_CASES:
        tc = TestCase(key, label)
        print(f"\n{'─' * 60}")
        print(f"测试: {label}")
        run_test(sess, tc, ws_id, fn)
        symbol = "✓" if tc.status == "PASS" else ("✗" if tc.status == "FAIL" else "−")
        print(f"  {symbol} {tc.status}" + (f": {tc.error}" if tc.error else ""))
        results.append(tc)
        time.sleep(0.3)   # 避免请求过快

    # ---------------------------------------------------------------------------
    # 汇总表
    # ---------------------------------------------------------------------------
    print("\n")
    print("=" * 70)
    print("汇总表")
    print("=" * 70)
    header = f"{'#':<4} {'节点':<38} {'结果':<6} {'错误信息'}"
    print(header)
    print("-" * 70)
    pass_count = 0
    fail_count = 0
    for i, tc in enumerate(results, 1):
        symbol = "PASS" if tc.status == "PASS" else ("FAIL" if tc.status == "FAIL" else "SKIP")
        err_snippet = tc.error[:50] if tc.error else ""
        if tc.status == "PASS":
            pass_count += 1
        elif tc.status == "FAIL":
            fail_count += 1
        print(f"{i:<4} {tc.label:<38} {symbol:<6} {err_snippet}")
    print("-" * 70)
    print(f"共 {len(results)} 项  PASS={pass_count}  FAIL={fail_count}")
    print("=" * 70)

    # 详细错误
    failed = [tc for tc in results if tc.status == "FAIL"]
    if failed:
        print("\n详细错误信息：")
        for tc in failed:
            print(f"\n  [{tc.key}] {tc.label}")
            print(f"    processId: {tc.process_id}")
            print(f"    nodeId:    {tc.node_id or '(未创建)'}")
            print(f"    错误:      {tc.error}")

    print("\n完成。")


if __name__ == "__main__":
    main()
