#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HAP Web Auth 统一请求工具，支持 401 自动刷新认证后重试。

所有需要 Cookie/Authorization 的 HAP 接口都应通过此模块发送请求，
以保证在 token 过期时能自动刷新并重试，无需人工干预。

公开 API
--------
load_web_auth(path)          -> (account_id, authorization, cookie)
refresh_auth(path, headless) -> bool
hap_web_post(url, auth_config_path, *, referer, extra_headers, **kwargs) -> Response
hap_web_get(url, auth_config_path, *, referer, extra_headers, **kwargs)  -> Response
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
AUTH_CONFIG_PATH = BASE_DIR / "config" / "credentials" / "auth_config.py"
REFRESH_AUTH_SCRIPT = BASE_DIR / "scripts" / "auth" / "refresh_auth.py"


# ---------------------------------------------------------------------------
# 认证加载
# ---------------------------------------------------------------------------

def load_web_auth(path: Optional[Path] = None) -> tuple[str, str, str]:
    """从 auth_config.py 加载 (account_id, authorization, cookie)。"""
    auth_path = Path(path) if path else AUTH_CONFIG_PATH
    if not auth_path.exists():
        raise FileNotFoundError(f"缺少认证配置: {auth_path}")
    spec = importlib.util.spec_from_file_location("_auth_config_runtime", str(auth_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载认证文件: {auth_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    account_id = str(getattr(module, "ACCOUNT_ID", "")).strip()
    authorization = str(getattr(module, "AUTHORIZATION", "")).strip()
    cookie = str(getattr(module, "COOKIE", "")).strip()
    if not account_id or not authorization or not cookie:
        raise ValueError(f"auth_config.py 缺少 ACCOUNT_ID/AUTHORIZATION/COOKIE: {auth_path}")
    return account_id, authorization, cookie


# ---------------------------------------------------------------------------
# 认证刷新
# ---------------------------------------------------------------------------

def refresh_auth(auth_config_path: Optional[Path] = None, headless: bool = True) -> bool:
    """运行 refresh_auth.py 刷新 Cookie/Authorization，返回 True 表示成功。"""
    script = REFRESH_AUTH_SCRIPT
    if not script.exists():
        print(f"[auth_retry] 找不到 refresh_auth 脚本: {script}")
        return False
    cmd = [sys.executable, str(script)]
    if headless:
        cmd.append("--headless")
    try:
        proc = subprocess.run(cmd, timeout=120, cwd=str(BASE_DIR))
        if proc.returncode != 0:
            print(f"[auth_retry] refresh_auth 执行失败，退出码: {proc.returncode}")
            return False
        return True
    except Exception as exc:
        print(f"[auth_retry] 运行 refresh_auth 时异常: {exc}")
        return False


# ---------------------------------------------------------------------------
# 标准 HAP Web 请求头
# ---------------------------------------------------------------------------

def _build_headers(
    account_id: str,
    authorization: str,
    cookie: str,
    referer: str = "",
    extra_headers: Optional[dict] = None,
) -> dict:
    h: dict = {
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
    if extra_headers:
        h.update(extra_headers)
    return h


# ---------------------------------------------------------------------------
# 带 401 重试的请求函数
# ---------------------------------------------------------------------------

def hap_web_post(
    url: str,
    auth_config_path: Optional[Path] = None,
    *,
    referer: str = "",
    extra_headers: Optional[dict] = None,
    **kwargs,
) -> requests.Response:
    """POST 请求，遇到 401 时自动刷新认证后重试一次。"""
    auth_path = Path(auth_config_path) if auth_config_path else AUTH_CONFIG_PATH
    account_id, authorization, cookie = load_web_auth(auth_path)
    headers = _build_headers(account_id, authorization, cookie, referer, extra_headers)

    # proxies={} 绕过系统代理，避免 www.mingdao.com 连接超时
    kwargs.setdefault("proxies", {})
    resp = requests.post(url, headers=headers, **kwargs, timeout=10.0)
    if resp.status_code == 401:
        print(f"[auth_retry] 检测到 401（POST {url}），正在自动刷新认证后重试...")
        if refresh_auth(auth_path):
            account_id, authorization, cookie = load_web_auth(auth_path)
            headers = _build_headers(account_id, authorization, cookie, referer, extra_headers)
            resp = requests.post(url, headers=headers, **kwargs, timeout=10.0)
        else:
            print("[auth_retry] 认证刷新失败，返回原始 401 响应")

    return resp


def hap_web_get(
    url: str,
    auth_config_path: Optional[Path] = None,
    *,
    referer: str = "",
    extra_headers: Optional[dict] = None,
    **kwargs,
) -> requests.Response:
    """GET 请求，遇到 401 时自动刷新认证后重试一次。"""
    auth_path = Path(auth_config_path) if auth_config_path else AUTH_CONFIG_PATH
    account_id, authorization, cookie = load_web_auth(auth_path)
    headers = _build_headers(account_id, authorization, cookie, referer, extra_headers)

    # proxies={} 绕过系统代理，避免 www.mingdao.com 连接超时
    kwargs.setdefault("proxies", {})
    resp = requests.get(url, headers=headers, **kwargs, timeout=10.0)
    if resp.status_code == 401:
        print(f"[auth_retry] 检测到 401（GET {url}），正在自动刷新认证后重试...")
        if refresh_auth(auth_path):
            account_id, authorization, cookie = load_web_auth(auth_path)
            headers = _build_headers(account_id, authorization, cookie, referer, extra_headers)
            resp = requests.get(url, headers=headers, **kwargs, timeout=10.0)
        else:
            print("[auth_retry] 认证刷新失败，返回原始 401 响应")

    return resp
