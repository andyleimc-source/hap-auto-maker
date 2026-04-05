"""
tests/unit/test_hap_api_client.py

HapClient 核心逻辑的单元测试。
使用 unittest.mock 拦截 HTTP 请求和文件读取，不需要真实 API。
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))


# ---------------------------------------------------------------------------
# 辅助：伪造一个合法的 organization_auth.json 内容
# ---------------------------------------------------------------------------

VALID_AUTH = {
    "app_key": "test_app_key_abc",
    "secret_key": "test_secret_key_xyz",
    "project_id": "test-project-id-001",
    "owner_id": "test-owner-id-001",
}


def _mock_config(data: dict = None):
    """返回一个 patch，让 CONFIG_PATH.exists() = True 且读到指定 data。"""
    content = json.dumps(data or VALID_AUTH)
    return content


# ---------------------------------------------------------------------------
# _build_sign
# ---------------------------------------------------------------------------


class TestBuildSign:
    def test_sign_is_base64_string(self):
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=_mock_config()),
        ):
            from hap_api_client import HapClient

            client = HapClient()
            sign = client._build_sign(int(time.time() * 1000))
            # base64 字符集验证
            import base64

            decoded = base64.b64decode(sign.encode())
            assert len(decoded) == 64  # sha256 hex = 64 chars

    def test_sign_changes_with_timestamp(self):
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=_mock_config()),
        ):
            from hap_api_client import HapClient

            client = HapClient()
            sign1 = client._build_sign(1000)
            sign2 = client._build_sign(2000)
            assert sign1 != sign2


# ---------------------------------------------------------------------------
# _load_auth — 配置验证
# ---------------------------------------------------------------------------


class TestLoadAuth:
    def test_missing_file_raises(self):
        with patch("pathlib.Path.exists", return_value=False):
            from hap_api_client import HapClient

            with pytest.raises(FileNotFoundError, match="缺少配置文件"):
                HapClient()

    def test_placeholder_value_raises(self):
        bad_auth = {**VALID_AUTH, "app_key": "YOUR_HAP_APP_KEY"}
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=json.dumps(bad_auth)),
        ):
            from hap_api_client import HapClient

            with pytest.raises(ValueError, match="app_key"):
                HapClient()

    def test_missing_required_field_raises(self):
        bad_auth = {k: v for k, v in VALID_AUTH.items() if k != "secret_key"}
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=json.dumps(bad_auth)),
        ):
            from hap_api_client import HapClient

            with pytest.raises((ValueError, KeyError)):
                HapClient()

    def test_valid_auth_loads(self):
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=_mock_config()),
        ):
            from hap_api_client import HapClient

            client = HapClient()
            assert client.auth["app_key"] == "test_app_key_abc"


# ---------------------------------------------------------------------------
# request — 成功响应
# ---------------------------------------------------------------------------


class TestRequest:
    def _make_client(self):
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=_mock_config()),
        ):
            from hap_api_client import HapClient

            return HapClient()

    def _mock_response(self, body: dict, status_code: int = 200):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = body
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_success_with_error_code_1(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error_code": 1, "data": {"id": "abc"}})
        with patch("requests.request", return_value=mock_resp):
            result = client.request("POST", "/api/test")
        assert result == {"id": "abc"}

    def test_success_with_code_1(self):
        client = self._make_client()
        mock_resp = self._mock_response({"code": 1, "data": {"name": "foo"}})
        with patch("requests.request", return_value=mock_resp):
            result = client.request("GET", "/api/test")
        assert result == {"name": "foo"}

    def test_api_error_raises_runtime_error(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error_code": 0, "error_msg": "权限不足"})
        with patch("requests.request", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="权限不足"):
                client.request("POST", "/api/test")

    def test_unknown_error_code_raises(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error_code": -1, "error_msg": "内部错误"})
        with patch("requests.request", return_value=mock_resp):
            with pytest.raises(RuntimeError):
                client.request("POST", "/api/test")

    def test_get_uses_params_not_body(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error_code": 1, "data": {}})
        with patch("requests.request", return_value=mock_resp) as mock_req:
            client.request("GET", "/api/test")
            call_kwargs = mock_req.call_args
            # GET 请求应使用 params，不应有 json body
            assert call_kwargs.kwargs.get("params") is not None
            assert call_kwargs.kwargs.get("json") is None

    def test_post_uses_json_body(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error_code": 1, "data": {}})
        with patch("requests.request", return_value=mock_resp) as mock_req:
            client.request("POST", "/api/test", data={"worksheetId": "ws001"})
            call_kwargs = mock_req.call_args
            assert call_kwargs.kwargs.get("json") is not None
            assert call_kwargs.kwargs.get("params") is None

    def test_payload_includes_project_id(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error_code": 1, "data": {}})
        with patch("requests.request", return_value=mock_resp) as mock_req:
            client.request("POST", "/api/test")
            payload = mock_req.call_args.kwargs["json"]
            assert payload["projectId"] == "test-project-id-001"

    def test_payload_includes_app_key(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error_code": 1, "data": {}})
        with patch("requests.request", return_value=mock_resp) as mock_req:
            client.request("POST", "/api/test")
            payload = mock_req.call_args.kwargs["json"]
            assert payload["appKey"] == "test_app_key_abc"

    def test_data_merged_into_payload(self):
        client = self._make_client()
        mock_resp = self._mock_response({"error_code": 1, "data": {}})
        with patch("requests.request", return_value=mock_resp) as mock_req:
            client.request("POST", "/api/test", data={"customField": "hello"})
            payload = mock_req.call_args.kwargs["json"]
            assert payload["customField"] == "hello"
