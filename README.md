# HAP Auto

基于 Gemini + 明道云 OpenAPI 的自动化应用搭建工具。通过自然语言描述需求，自动完成从建应用、建表、配视图、造数据到生成机器人的全流程。

---

## 常用 Git 命令

```bash
# 保存所有改动并推送到 GitHub
git add -A && git commit -m "20260318" && git push origin main

# 拉取最新代码
git pull origin main
```

---

## 快速开始

### 0. 安装 Git (如已安装请跳过)

- **macOS**: 打开终端执行 `xcode-select --install`，或下载 [Git for macOS](https://git-scm.com/download/mac)

### 1. 下载并初始化项目

```bash
git clone https://github.com/andyleimc-source/auto_hap.git
cd auto_hap
python3 setup.py
```

`setup.py` 会交互式引导你完成全部配置（安装依赖、填写密钥、自动登录），完成后即可使用。
> 💡 **提示**：如果你未来需要更换账号、或修改配置密钥，随时可以执行 `python3 setup.py --force` 强制重新初始化。

## 前置条件

- Python 3.11 或 3.12（**请勿使用低于 3.11 的版本**）
- macOS
- 一个明道云账号（有组织管理员权限）
- 一个 Google Gemini API Key

### 🚀 安装 Python（如版本符合请跳过）
如果你没有安装 Python 或版本低于 3.11，请通过以下官方链接直接下载 macOS 安装包：
- [Python 3.12 官方图形安装包下载](https://www.python.org/ftp/python/3.12.9/python-3.12.9-macos11.pkg)
- 下载后双击安装，一路“下一步”即可。
- 安装完成后，请**完全关闭并重新打开终端**，以使新环境生效。

## 密钥获取说明

运行 `setup.py` 时需要填写以下 6 项：

### 1. Gemini API Key

用于 AI 规划（工作表设计、造数、视图匹配等）。

获取地址：https://aistudio.google.com/apikey

### 2. HAP 组织级密钥（app_key / secret_key）

用于调用明道云 OpenAPI 创建应用、工作表等。

获取路径：**组织管理 → 集成 → 其他 → 开放接口 → 查看密钥**

快捷地址：`https://www.mingdao.com/admin/integrationothers/<你的组织ID>`

### 3. 组织 ID（project_id）

用于指定在哪个组织下创建应用。

获取路径：**组织管理 → 组织 → 组织信息 → 编号（ID）**

### 4. 拥有者 ID（owner_id）

用于指定应用的拥有者。

获取方式：在明道云中点击群聊中个人的头像，浏览器地址栏会显示 `https://www.mingdao.com/user_xxx`，其中 `xxx` 即为 owner_id。

### 5. 应用分组 ID（group_ids）（可选）

用于指定新创建的应用放入哪个分组。

获取方式：在明道云中点击某个应用分组，浏览器地址栏会显示 `groupId=xxx`，其中 `xxx` 即为 group_ids。留空则创建应用时不指定分组。

### 6. 明道云登录账号

用于自动登录获取网页端 Cookie / Authorization（部分接口需要）。

`setup.py` 会自动调用 Playwright 无头浏览器登录，登录成功后自动写入 `auth_config.py`，无需手动抓包。

## 更新到最新版本

如果你之前已经克隆过项目，进入项目目录后拉取最新代码即可：

```bash
cd auto_hap
git pull
```

如果有新增配置项，建议重新运行初始化（已有配置会被覆盖）：

```bash
python3 setup.py --force
```

> 💡 **提示**：忘了项目在哪？运行 `find ~ -name "auto_hap" -type d` 找一下。

## 使用方式

### 对话式一键创建应用 (推荐)

```bash
# 默认运行（不录屏）
python3 scripts/run_app_pipeline.py

# 开启录屏
python3 scripts/run_app_pipeline.py --add-recording
```

在终端与 Gemini 多轮对话，描述你想要的应用，输入「开始运行」后自动生成需求规格并开始搭建全流程（创建应用、建表、视图、造数、机器人、工作流）。

### 分步对话 (进阶)

```bash
python3 scripts/hap/agent_collect_requirements.py
```

在终端与 Gemini 对话，输入「开始运行」后自动生成需求规格并开始执行。

### 单独执行某步骤：

```bash
python3 scripts/hap/execute_requirements.py \
  --spec-json data/outputs/requirement_specs/requirement_spec_latest.json \
  --only-steps mock_data
```

### 其他常用命令

```bash
# 已有应用：一键造数
python3 scripts/hap/pipeline_mock_data.py

# 已有应用：清空记录（先 dry-run 确认）
python3 scripts/hap/clear_app_records.py --dry-run
python3 scripts/hap/clear_app_records.py

# 交互式批量删除应用
python3 scripts/hap/delete_app.py --delete-all

# 认证过期时重新登录
python3 scripts/refresh_auth.py
```

## 目录结构

```
hap_auto/
├── setup.py             # 一键初始化脚本
├── scripts/
│   ├── hap/             # 核心实现（应用创建、工作表、视图、造数等）
│   ├── gemini/          # Gemini AI 规划脚本
│   └── auth/            # 认证相关
├── config/
│   └── credentials/     # 本地密钥文件（.gitignore 已忽略，不会提交）
├── data/
│   └── outputs/         # 所有运行产物（规划 JSON、执行结果等）
└── workflow/            # 工作流相关脚本
```

## 认证刷新

网页登录态会过期（通常 Cookie 有效期几天到几周不等）。遇到 `401 / 403` 错误时，运行：

```bash
python3 scripts/refresh_auth.py            # 有头模式（可看到浏览器）
python3 scripts/refresh_auth.py --headless # 无头模式
```

会自动重新登录并更新 `config/credentials/auth_config.py`。

## 排障

| 问题 | 解决方案 |
|------|----------|
| Gemini 调用失败 | 检查 `config/credentials/gemini_auth.json` 中的 API Key 是否有效 |
| 页面接口 401/403 | 运行 `python3 scripts/refresh_auth.py` 刷新登录态 |
| OpenAPI "签名不合法" | 检查 `organization_auth.json` 中的 `app_key`、`secret_key`、`project_id`、`owner_id` 是否都已正确填写（不能是占位符），运行 `python3 setup.py --force` 重新配置 |
| OpenAPI 调用失败 | 检查 `config/credentials/organization_auth.json` 中的密钥 |
| 选择不到应用 | 先运行创建应用流程，生成 `data/outputs/app_authorizations/` 下的授权文件 |
| 造数后还有空关联 | 查看 `data/outputs/mock_relation_repair_plans/` 下的修复计划 |

## 已知限制

- 关联字段造数：支持 `1-1` 和 `1-N` 单选端，不保证自动回填 `1-N` 多选端
- 不是所有脚本都支持断点续跑
- 部分历史产物可能残留在 `data/outputs/`，注意区分最新结果
