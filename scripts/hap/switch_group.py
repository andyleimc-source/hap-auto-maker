#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
切换本地默认 HAP 应用分组
"""

import sys
from pathlib import Path

# 确保能导入同目录下的脚本
sys.path.append(str(Path(__file__).resolve().parent))
from list_groups import get_groups
from local_config import save_local_group_id, load_local_group_id

def switch_group():
    """展示分组列表并允许用户选择切换"""
    try:
        groups = get_groups()
        if not groups:
            print("❌ 组织下暂无应用分组。")
            return
        
        current_gid = load_local_group_id()
        
        print("\n📂 请选择要设为默认的分组：")
        print(f"{'#':<4} {'名称':<20} {'ID':<40} {'状态'}")
        print("-" * 75)
        for i, g in enumerate(groups, 1):
            name = g.get("name", "Unknown")
            gid = g.get("groupId", "Unknown")
            is_current = gid == current_gid
            status = "⭐ (当前)" if is_current else ""
            print(f"{i:<4} {name:<20} {gid:<40} {status}")
        
        choice = input("\n请输入编号进行切换 (直接回车保留当前): ").strip()
        if not choice:
            print("已保留当前配置。")
            return
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(groups):
                selected = groups[idx]
                save_local_group_id(selected["groupId"])
                print(f"✅ 已切换默认分组为: {selected['name']} ({selected['groupId']})")
            else:
                print("❌ 编号超出范围。")
        except ValueError:
            print("❌ 无效的输入。")
            
    except Exception as e:
        print(f"❌ 切换分组失败: {e}")

if __name__ == "__main__":
    switch_group()
