#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
彻底从 HAP 组织中删除应用分组
"""

import sys
from pathlib import Path

# 确保能导入同目录下的脚本
sys.path.append(str(Path(__file__).resolve().parent))
from hap_api_client import HapClient
from list_groups import get_groups
from local_config import save_local_group_id, load_local_group_id

def delete_group():
    """展示分组列表并确认删除"""
    try:
        groups = get_groups()
        if not groups:
            print("❌ 组织下暂无应用分组。")
            return
        
        current_gid = load_local_group_id()
        
        print("\n🗑️ 请选择要删除的分组 (警告：该操作将从 HAP 彻底删除！)：")
        print(f"{'#':<4} {'名称':<20} {'ID':<40} {'状态'}")
        print("-" * 75)
        for i, g in enumerate(groups, 1):
            name = g.get("name", "Unknown")
            gid = g.get("groupId", "Unknown")
            is_current = gid == current_gid
            status = "⭐ (当前默认)" if is_current else ""
            print(f"{i:<4} {name:<20} {gid:<40} {status}")
        
        choice = input("\n请输入编号进行删除 (或直接回车取消): ").strip()
        if not choice:
            print("操作已取消。")
            return
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(groups):
                selected = groups[idx]
                target_gid = selected["groupId"]
                
                confirm = input(f"❗ 确定要删除分组 '{selected['name']}' ({target_gid}) 吗？(y/n): ").strip().lower()
                if confirm != 'y':
                    print("操作已取消。")
                    return
                
                client = HapClient()
                client.request("POST", "/v1/open/App/DeleteGroup", data={
                    "groupId": target_gid
                })
                
                print(f"✅ 已成功删除分组: {selected['name']}")
                
                # 若删除的是当前默认分组，清空本地存储
                if target_gid == current_gid:
                    save_local_group_id("")
                    print("🧹 已清空本地默认分组配置。")
                    
            else:
                print("❌ 编号超出范围。")
        except ValueError:
            print("❌ 无效的输入。")
            
    except Exception as e:
        print(f"❌ 删除分组失败: {e}")

if __name__ == "__main__":
    delete_group()
