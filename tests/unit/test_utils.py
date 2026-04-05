"""
tests/unit/test_utils.py

now_ts, load_json, write_json, latest_file, write_json_with_latest 的单元测试。
不需要网络，不需要真实 API key。
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))
from utils import latest_file, load_json, now_iso, now_ts, write_json, write_json_with_latest


class TestNowTs:
    def test_format(self):
        ts = now_ts()
        assert len(ts) == 15  # YYYYmmdd_HHMMSS
        assert ts[8] == "_"

    def test_returns_string(self):
        assert isinstance(now_ts(), str)

    def test_digits_only_except_underscore(self):
        ts = now_ts()
        assert ts[:8].isdigit()
        assert ts[9:].isdigit()


class TestNowIso:
    def test_returns_string_with_timezone(self):
        iso = now_iso()
        assert isinstance(iso, str)
        assert "T" in iso
        # 包含时区偏移 (+HH:MM 或 Z)
        assert "+" in iso or iso.endswith("Z")


class TestLoadJson:
    def test_loads_valid_file(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        assert load_json(f) == {"key": "value"}

    def test_raises_if_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_json(tmp_path / "nope.json")

    def test_chinese_content(self, tmp_path):
        f = tmp_path / "cn.json"
        f.write_text('{"名称": "测试"}', encoding="utf-8")
        assert load_json(f)["名称"] == "测试"


class TestWriteJson:
    def test_writes_and_creates_dir(self, tmp_path):
        p = tmp_path / "sub" / "out.json"
        write_json(p, {"a": 1})
        assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}

    def test_ensure_ascii_false(self, tmp_path):
        p = tmp_path / "out.json"
        write_json(p, {"名称": "测试"})
        assert "测试" in p.read_text(encoding="utf-8")

    def test_returns_path(self, tmp_path):
        p = tmp_path / "out.json"
        result = write_json(p, {})
        assert result == p

    def test_overwrites_existing(self, tmp_path):
        p = tmp_path / "out.json"
        write_json(p, {"v": 1})
        write_json(p, {"v": 2})
        assert load_json(p)["v"] == 2


class TestLatestFile:
    def test_returns_none_on_empty_dir(self, tmp_path):
        assert latest_file(tmp_path, "*.json") is None

    def test_returns_most_recent(self, tmp_path):
        a = tmp_path / "a.json"
        a.write_text("{}")
        time.sleep(0.02)
        b = tmp_path / "b.json"
        b.write_text("{}")
        result = latest_file(tmp_path, "*.json")
        assert result.name == "b.json"

    def test_pattern_filtering(self, tmp_path):
        (tmp_path / "x.json").write_text("{}")
        (tmp_path / "y.txt").write_text("hello")
        result = latest_file(tmp_path, "*.json")
        assert result.name == "x.json"


class TestWriteJsonWithLatest:
    def test_writes_both_files(self, tmp_path):
        out_path = tmp_path / "run_20260405.json"
        write_json_with_latest(tmp_path, out_path, "latest.json", {"x": 1})
        assert (tmp_path / "run_20260405.json").exists()
        assert (tmp_path / "latest.json").exists()

    def test_latest_has_correct_content(self, tmp_path):
        out_path = tmp_path / "run_001.json"
        write_json_with_latest(tmp_path, out_path, "latest.json", {"val": 42})
        content = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
        assert content == {"val": 42}

    def test_creates_output_dir(self, tmp_path):
        sub = tmp_path / "new_sub"
        out_path = sub / "run.json"
        write_json_with_latest(sub, out_path, "latest.json", {})
        assert sub.exists()
