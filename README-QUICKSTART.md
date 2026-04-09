# HAP Auto Maker Quickstart

这个文件给 Claude Code / Codex / 新同学快速启动，避免先读全仓代码。

## 1) 环境准备

```bash
cd /path/to/hap-auto-maker
bash scripts/bootstrap.sh
source .venv/bin/activate
```

## 2) 首次配置（交互向导）

```bash
python3 setup.py
```

会写入：

- `config/credentials/ai_auth.json`
- `config/credentials/organization_auth.json`
- `config/credentials/login_credentials.py`

## 3) 最小可运行命令

先只生成 spec（不执行创建）：

```bash
python3 make_app.py --requirements "$(cat examples/minimal_requirements.txt)" --no-execute
```

完整执行（创建应用/工作表/视图等）：

```bash
python3 make_app.py --requirements "$(cat examples/minimal_requirements.txt)"
```

英文应用：

```bash
python3 make_app.py --requirements "$(cat examples/minimal_requirements.txt)" --language en
```

依赖策略（防环境不一致）：

```bash
python3 make_app.py --requirements "..." --deps-mode auto   # 默认：安全自动策略
python3 make_app.py --requirements "..." --deps-mode check  # 仅检查，不自动安装
```

## 4) 只用已有 spec 执行

```bash
python3 make_app.py --spec-json requirement_spec_latest.json
```

## 5) 结果与日志位置

- 执行总报告：`data/outputs/execution_runs/execution_run_*.json`
- 技术日志：`data/outputs/app_runs/{run_id}/tech_log.json`
- 视图创建结果：`data/outputs/view_create_results/view_create_result_*.json`

更多排障细节见 `RUNBOOK.md`。
