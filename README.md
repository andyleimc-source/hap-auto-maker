项目目标：
创建一个完整的 HAP 应用，并通过脚本自动化管理工作表视图（看板/画廊等）。


输出目录规范（`data/outputs`）：

- `app_authorizations/`：应用授权信息
  - 例如：`app_authorize_<appId>.json`
- `worksheet_plans/`：Gemini 生成的工作表规划
  - 例如：`worksheet_plan_<appName>_<timestamp>.json`
- `worksheet_create_results/`：按规划创建工作表的执行结果
  - 例如：`worksheet_create_result_<timestamp>.json`
- `gemini_models/`：Gemini 模型列表
  - 例如：`gemini_models_<timestamp>.json`

说明：

- 新脚本默认写入上述分类目录。
- 读取时对旧路径保留兼容（优先新目录）。

目录结构：

- `scripts/hap/`：HAP 业务脚本（创建应用、授权、删除、按规划建表）
- `scripts/gemini/`：Gemini 脚本（规划、模型列表）
- `scripts/auth/`：登录认证相关脚本
- `scripts/*.py`：兼容入口（保留旧命令路径）
- `data/api_docs/`：API 文档与 OpenAPI 资料
- `data/assets/icons/`：图标资产（`icon.json`）
- `config/credentials/`：密钥与账号配置


