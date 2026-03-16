# HAP Auto

## 一键运行

```bash
python3 scripts/run_app_to_video.py --skip-recording
```

完整流程：需求对话 → 创建应用 → 工作表/视图/布局 → 造数 → 机器人 → 工作流。

去掉 `--skip-recording` 则在最后额外录制演示视频。

# 交互式批量删除（列出所有已记录应用，选择后删除）
python3 scripts/hap/delete_app.py --delete-all

## 目录结构

```
hap_auto/
├── scripts/         # 顶层仅保留少数公开入口；主要实现位于 scripts/hap、scripts/gemini、scripts/auth
├── workflow/        # 工作流相关脚本
├── config/
│   └── credentials/ # 认证配置（gemini_auth.json、auth_config.py 等）
├── data/            # 应用授权 JSON、输出产物
└── record/          # 浏览器录制 Agent
```
