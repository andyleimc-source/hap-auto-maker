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
        required = ("app_key", "secret_key", "project_id")
        for k in required:
            if not data.get(k) or str(data[k]).startswith("YOUR_"):
                raise ValueError(f"配置字段无效或缺失: {k}，请先运行 python3 setup.py")
        return data

    def _build_sign(self, timestamp_ms: int) -> str:
        app_key = self.auth["app_key"]
        secret_key = self.auth["secret_key"]
        raw = f"AppKey={app_key}&SecretKey={secret_key}&Timestamp={timestamp_ms}"
        digest_hex = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return base64.b64encode(digest_hex.encode("utf-8")).decode("utf-8")

    def request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
    ) -> Any:
        url = f"{self.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        method = method.upper()

        last_exc: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            ts = int(time.time() * 1000)
            payload = {
                "appKey": self.auth["app_key"],
                "sign": self._build_sign(ts),
                "timestamp": ts,
                "projectId": self.auth["project_id"],
            }
            if data:
                payload.update(data)

            try:
                if method == "GET":
                    response = requests.request(method, url, params=payload, headers=headers, timeout=30)
                else:
                    response = requests.request(method, url, json=payload, headers=headers, timeout=30)
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                last_exc = e
                if attempt < max_retries:
                    wait = (attempt + 1) * 5
                    import warnings
                    warnings.warn(f"HAP API HTTP错误，{wait}s 后重试 ({attempt + 1}/{max_retries}): {e}")
                    time.sleep(wait)
                    continue
                raise

            res_json = response.json()
            # 处理返回格式不同的情况（有的接口返回 code，有的返回 error_code）
            code = res_json.get("error_code") if "error_code" in res_json else res_json.get("code")
            if code != 1:
                msg = res_json.get("error_msg") or res_json.get("message") or "Unknown error"
                raise RuntimeError(f"HAP API Error: {msg} (code: {code})")
            return res_json.get("data")

        raise last_exc or RuntimeError("HAP API 请求失败")

if __name__ == "__main__":
    # 简单测试
    try:
        client = HapClient()
        print("Auth loaded successfully.")
    except Exception as e:
        print(f"Error: {e}")
