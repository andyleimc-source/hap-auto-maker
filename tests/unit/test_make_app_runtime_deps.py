"""
tests/unit/test_make_app_runtime_deps.py

覆盖 make_app 运行依赖检查逻辑：
1) 可选依赖缺失不阻断
2) 必需依赖缺失在 PEP 668 + auto 模式下仍阻断
"""

from __future__ import annotations

import importlib.util

import pytest

import make_app


def test_optional_json_repair_missing_does_not_block(monkeypatch, capsys):
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(module_name: str):
        if module_name == "json_repair":
            return None
        return original_find_spec(module_name)

    monkeypatch.setattr(make_app.importlib.util, "find_spec", fake_find_spec)

    make_app.ensure_runtime_dependencies(auto_install=True, deps_mode="auto")
    out = capsys.readouterr().out
    assert "可选依赖缺失" in out
    assert "json-repair" in out


def test_required_dependency_missing_still_raises_in_pep668(monkeypatch):
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(module_name: str):
        if module_name == "requests":
            return None
        return original_find_spec(module_name)

    monkeypatch.setattr(make_app.importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(make_app, "_in_virtualenv", lambda: False)
    monkeypatch.setattr(make_app, "_is_externally_managed_environment", lambda: True)

    with pytest.raises(RuntimeError, match="PEP 668"):
        make_app.ensure_runtime_dependencies(auto_install=True, deps_mode="auto")
