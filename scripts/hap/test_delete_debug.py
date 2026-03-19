#!/usr/bin/env python3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

from mock_data_common import (
    DEFAULT_BASE_URL,
    delete_rows_batch,
    discover_authorized_apps,
    fetch_rows,
)

def test_delete():
    base_url = DEFAULT_BASE_URL
    apps = discover_authorized_apps(base_url=base_url)
    if not apps:
        print("No apps found.")
        return
    
    app = apps[0]
    print(f"Testing app: {app['appName']} ({app['appId']})")
    
    worksheet_id = "69bc24a83d5a03ae8d780db8"
    # 1. List some rows
    rows = fetch_rows(base_url, app["appKey"], app["sign"], worksheet_id, fields=["rowid"], include_system_fields=True)
    if not rows:
        print("No rows found to test delete.")
        return
    
    row_ids = [str(r.get("rowid", "")) for r in rows[:2]]
    print(f"Attempting to delete rows: {row_ids}")
    
    try:
        # Use a non-existent rowid
        row_ids = ["00000000-0000-0000-0000-000000000000"]
        print(f"\nTesting delete_rows_batch with non-existent {row_ids}")
        resp = delete_rows_batch(base_url, app["appKey"], app["sign"], worksheet_id, row_ids, permanent=False, trigger_workflow=False)
        print(f"Response: {resp}")
    except Exception as e:
        print(f"Expected error occurred: {e}")

if __name__ == "__main__":
    test_delete()
