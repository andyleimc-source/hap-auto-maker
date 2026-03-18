#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建 HAP 应用分组
用法: python3 create_group.py [分组名称]
"""

import sys
from pathlib import Path
from typing import Optional

# 确保能导入同目录下的 client 和 local_config
sys.path.append(str(Path(__file__).resolve().parent))
from hap_api_client import HapClient
from local_config import save_local_group_id

def create_group(name: Optional[str] = None) -> str:
    """调用 API 创建应用分组，并保存到本地配置"""
    if not name:
        name = input("请输入新分组名称: ").strip()
        if not name:
            raise ValueError("分组名称不能为空。")
    
    icon = "0_lego" # 默认图标
    
    client = HapClient()
    print(f"🚀 正在创建分组: {name}...")
    
    # 接口路径确认：/v1/open/app/AddGroup
    new_group_id = client.request("POST", "/v1/open/app/AddGroup", data={
        "name": name,
        "icon": icon
    })
    
    if new_group_id:
        print(f"✅ 分组创建成功！ID: {new_group_id}")
        save_local_group_id(new_group_id)
        print(f"✔ 已将 {name} ({new_group_id}) 设为本地默认分组。")
        return new_group_id
    else:
        raise RuntimeError("创建分组失败，返回的 ID 为空。")

if __name__ == "__main__":
    try:
        name_arg = sys.argv[1] if len(sys.argv) > 1 else None
        create_group(name_arg)
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        sys.exit(1)
