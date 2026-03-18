#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取并列出 HAP 组织下的所有应用分组
"""

import sys
from pathlib import Path
from typing import List, Dict, Any

# 确保能导入同目录下的 client
sys.path.append(str(Path(__file__).resolve().parent))
from hap_api_client import HapClient

def get_groups() -> List[Dict[str, Any]]:
    """调用 API 获取所有组织级别应用分组列表"""
    client = HapClient()
    return client.request("GET", "/v1/open/App/ProjectGroups")

def list_groups():
    """打印分组列表"""
    try:
        groups = get_groups()
        if not groups:
            print("❌ 组织下暂无应用分组。")
            return []
        
        print("\n📂 组织应用分组列表：")
        print(f"{'#':<4} {'名称':<20} {'ID':<40} {'应用数':<6}")
        print("-" * 75)
        for i, g in enumerate(groups, 1):
            name = g.get("name", "Unknown")
            gid = g.get("groupId", "Unknown")
            count = g.get("count", 0)
            print(f"{i:<4} {name:<20} {gid:<40} {count:<6}")
        return groups
    except Exception as e:
        print(f"❌ 获取分组列表失败: {e}")
        return []

if __name__ == "__main__":
    list_groups()
