import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "hap"))


class TestBuildPageWorksheetsInfo:
    """build_page_worksheets_info(page_entry, ws_fields_map) 返回该 Page 的工作表字段列表"""

    def test_filters_to_page_worksheets(self):
        from executors.create_page_charts import build_page_worksheets_info

        page_entry = {
            "name": "财务页",
            "pageId": "page1",
            "worksheetNames": ["合同表", "发票表"],
            "components": [],
        }
        ws_fields_map = {
            "合同表": {
                "worksheetId": "ws_contract",
                "worksheetName": "合同表",
                "fields": [{"controlId": "f1", "controlName": "金额", "controlType": 6}],
                "views": [],
            },
            "发票表": {
                "worksheetId": "ws_invoice",
                "worksheetName": "发票表",
                "fields": [{"controlId": "f2", "controlName": "税率", "controlType": 6}],
                "views": [],
            },
            "其他表": {
                "worksheetId": "ws_other",
                "worksheetName": "其他表",
                "fields": [{"controlId": "f3", "controlName": "备注", "controlType": 2}],
                "views": [],
            },
        }

        result = build_page_worksheets_info(page_entry, ws_fields_map)

        assert len(result) == 2
        ws_names = [r["worksheetName"] for r in result]
        assert "合同表" in ws_names
        assert "发票表" in ws_names
        assert "其他表" not in ws_names

    def test_empty_page_returns_empty(self):
        from executors.create_page_charts import build_page_worksheets_info

        page_entry = {"name": "空页", "pageId": "p2", "worksheetNames": [], "components": []}
        result = build_page_worksheets_info(page_entry, {"合同表": {}})
        assert result == []

    def test_missing_ws_in_map_is_skipped(self):
        from executors.create_page_charts import build_page_worksheets_info

        page_entry = {
            "name": "页面",
            "pageId": "p3",
            "worksheetNames": ["存在表", "不存在表"],
            "components": [],
        }
        ws_fields_map = {
            "存在表": {
                "worksheetId": "ws1",
                "worksheetName": "存在表",
                "fields": [{"controlId": "f1", "controlName": "字段", "controlType": 6}],
                "views": [],
            }
        }
        result = build_page_worksheets_info(page_entry, ws_fields_map)
        assert len(result) == 1
        assert result[0]["worksheetName"] == "存在表"
