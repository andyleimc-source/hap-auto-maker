#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理本地私有配置 (.env.local)
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_LOCAL_PATH = BASE_DIR / ".env.local"

def load_local_group_id() -> str:
    """从 .env.local 加载 DEFAULT_GROUP_ID"""
    if not ENV_LOCAL_PATH.exists():
        return ""
    
    with open(ENV_LOCAL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("DEFAULT_GROUP_ID="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

def save_local_group_id(group_id: str):
    """保存 DEFAULT_GROUP_ID 到 .env.local"""
    lines = []
    found = False
    
    if ENV_LOCAL_PATH.exists():
        with open(ENV_LOCAL_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("DEFAULT_GROUP_ID="):
                    lines.append(f'DEFAULT_GROUP_ID="{group_id}"\n')
                    found = True
                else:
                    lines.append(line)
    
    if not found:
        lines.append(f'DEFAULT_GROUP_ID="{group_id}"\n')
        
    with open(ENV_LOCAL_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

if __name__ == "__main__":
    # 测试
    gid = load_local_group_id()
    print(f"Current Local Group ID: {gid or '(None)'}")
