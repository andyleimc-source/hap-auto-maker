#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP 组织授权接口通用客户端
"""

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config" / "credentials" / "organization_auth.json"
DEFAULT_BASE_URL = "https://api.mingdao.com"

class HapClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.auth = self._load_auth()

    def _load_auth(self) -> dict:
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"缺少配置文件: {CONFIG_PATH}")
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        required = ("app_key", "secret_key")
        for k in required:
            if not data.get(k) or str(data[k]).startswith("YOUR_"):
                raise ValueError(f"配置字段无效或缺失: {k}，请先运行 python3 setup.py")
        
        # project_id 设为可选
        pid = data.get("project_id", "")
        if not pid or str(pid).startswith("YOUR_"):
            data["project_id"] = None
        return data

    def _save_auth(self):
        """将当前内存中的 auth 配置持久化到文件"""
        CONFIG_PATH.write_text(json.dumps(self.auth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _discover_project_id(self) -> str:
        """调用 GET /v3/app 自动获取 organizationId (projectId)"""
        url = f"{self.base_url}/v3/app"
        app_key = self.auth["app_key"]
        secret_key = self.auth["secret_key"]
        
        # V3 接口签名逻辑：md5(appKey + secretKey + ts)
        ts = int(time.time())
        raw = f"{app_key}{secret_key}{ts}"
        sign = hashlib.md5(raw.encode("utf-8")).hexdigest()
        
        headers = {
            "HAP-Appkey": app_key,
            "HAP-Sign": sign,
            "Accept": "application/json"
        }
        
        # 注意：V3 接口可能需要 timestamp 在参数或 header 中，
        # 根据经验，这类友好型接口通常通过 Header 传 appkey/sign，timestamp 可能作为参数
        resp = requests.get(url, headers=headers, params={"timestamp": ts}, timeout=20)
        try:
            data = resp.json()
        except Exception:
            raise RuntimeError(f"获取应用元数据失败，返回不是 JSON: {resp.text}")

        if not isinstance(data, dict):
            raise RuntimeError(f"获取应用元数据失败，返回格式错误: {data}")
            
        if not data.get("success"):
            msg = data.get("error_msg") or data.get("message") or str(data)
            raise RuntimeError(f"自动获取 projectId 失败: {msg}")
            
        org_id = data.get("data", {}).get("organizationId")
        if not org_id:
            raise RuntimeError(f"应用元数据中未找到 organizationId (projectId): {data}")
            
        return str(org_id).strip()

    def _build_sign(self, timestamp_ms: int) -> str:
        app_key = self.auth["app_key"]
        secret_key = self.auth["secret_key"]
        raw = f"AppKey={app_key}&SecretKey={secret_key}&Timestamp={timestamp_ms}"
        digest_hex = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return base64.b64encode(digest_hex.encode("utf-8")).decode("utf-8")

    def request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Any:
        # 自动发现 projectId
        if not self.auth.get("project_id"):
            print("🔍 配置文件缺少 project_id，正在尝试自动获取...")
            pid = self._discover_project_id()
            self.auth["project_id"] = pid
            self._save_auth()
            print(f"✅ 自动获取并保存 projectId: {pid}")

        url = f"{self.base_url}{endpoint}"
        ts = int(time.time() * 1000)
        
        payload = {
            "appKey": self.auth["app_key"],
            "sign": self._build_sign(ts),
            "timestamp": ts,
            "projectId": self.auth["project_id"]
        }
        if data:
            payload.update(data)

        headers = {"Content-Type": "application/json"}
        method = method.upper()
        
        if method == "GET":
            response = requests.request(method, url, params=payload, headers=headers)
        else:
            response = requests.request(method, url, json=payload, headers=headers)
            
        response.raise_for_status()
        res_json = response.json()
        
        # 处理返回格式不同的情况（有的接口返回 code，有的返回 error_code）
        code = res_json.get("error_code") if "error_code" in res_json else res_json.get("code")
        
        if code != 1:
            msg = res_json.get("error_msg") or res_json.get("message") or "Unknown error"
            raise RuntimeError(f"HAP API Error: {msg} (code: {code})")
            
        return res_json.get("data")

if __name__ == "__main__":
    # 简单测试
    try:
        client = HapClient()
        print("Auth loaded successfully.")
    except Exception as e:
        print(f"Error: {e}")
