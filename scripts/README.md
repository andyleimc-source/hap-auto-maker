# Scripts Layout

顶层 `scripts/` 现在只保留少数公开入口，供 README、文档和人工执行使用：

- `run_app_to_video.py`
- `fill_task_placeholders.py`
- `pipeline_app_roles.py`
- `plan_role_recommendations_gemini.py`
- `create_roles_from_recommendation.py`
- `refresh_auth.py`

实现代码按职责放在：

- `scripts/hap/`：HAP 业务与编排实现
- `scripts/gemini/`：Gemini 相关实现
- `scripts/auth/`：认证与登录辅助

约定：

- 新增业务脚本时，默认放在对应实现目录，不再在顶层创建镜像 wrapper。
- `scripts/hap` 内部编排器应通过 `script_locator.py` 解析下游脚本，不直接依赖顶层入口。
