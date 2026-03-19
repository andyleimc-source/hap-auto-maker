# HAP Auto Maker

基于 Gemini + HAP自动化应用搭建助手。
通过自然语言对话，全自动完成：**创建应用 → 建立工作表及字段 → 配置视图 → 构造测试数据 → 生成智能机器人** 的完整开发工作流。

## 🚀 快速开始

### macOS

- 操作系统：**macOS**
- Python 环境：**Python 3.11 或 3.12**（低于 3.11 将导致运行失败！[点此下载 3.12 官方安装包](https://www.python.org/ftp/python/3.12.9/python-3.12.9-macos11.pkg)）
- 权限说明：需提供一个具有**明道云组织管理员**权限的账号。

```bash
git clone https://github.com/andyleimc-source/hap-auto-maker.git
cd hap-auto-maker
python3 setup.py
python3 scripts/run_app_pipeline.py
```

> 如需重新初始化配置，可执行 `python3 setup.py --force`。

### Windows

Windows 用户最稳的方案是：**安装 WSL2，并在 Ubuntu 终端中运行本项目**。这个项目当前主要按 macOS / 类 Unix 环境组织，`Python + Playwright + Chromium` 在 WSL2 里通常比原生 PowerShell 更稳定，也更接近作者的开发环境。

先安装这些工具：
- [WSL2 安装说明](https://learn.microsoft.com/windows/wsl/install)
- [Ubuntu（Microsoft Store）](https://apps.microsoft.com/store/detail/ubuntu/9PDXGNCFSCZV)
- [Git for Windows](https://git-scm.com/download/win)
- [Python 3.12 for Windows](https://www.python.org/downloads/windows/)

安装完成后，在 **管理员 PowerShell** 里先执行一次：

```powershell
wsl --install
```

重启电脑，打开 **Ubuntu**，然后执行下面这组完整命令：

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv
git clone https://github.com/andyleimc-source/hap-auto-maker.git
cd hap-auto-maker
python3 setup.py
python3 scripts/run_app_pipeline.py
```

初始化时按提示填写 `Gemini API Key`、明道云 OpenAPI 密钥、组织信息和管理员登录账号即可。如果登录认证卡住，可单独执行 `python3 scripts/auth/refresh_auth.py`。

## 🎬 核心特性
- **对话即开发**：描述需求即可，AI 自动转换为明道云的建表结构与字段关联。
- **真实数据生成**：根据表结构自动生成符合业务逻辑的测试数据。
- **完全自动化**：一键调用 Gemini 与内部接口，无需人工干预。

---

## 🛠️ 自动化搭建能力矩阵

目前 HAP Auto Maker 拥有针对 HAP 应用搭建周期内的全阶段支持，能够全自动构建以下核心组件：

- **📦 基础应用创建**：根据需求自动生成应用实例，并包含主色调定制。
- **📋 工作表与字段编排**：支持文本、数值、日期、人员、单选多选及关联记录等几十种复杂字段的识别与创建。

  ![工作表](intro/image/1.工作表.png)
  ![字段与关联](intro/image/2.字段与关联.png)

- **🎨 智能图标 (Icon) 匹配**：针对应用整体及下属每一张工作表，通过大模型语义分析自动挑选并匹配最符合业务场景的矢量图标。
- **🖼️ 视图个性化配置**：自动识别应用场景并配置列表视图、看版视图、画廊视图等，自动植入筛选与排序规则。

  ![视图](intro/image/3.视图.png)

- **📊 统计图表**：自动围绕业务数据生成饼图、柱状图、折线图等数据分析界面，直观展示业务指标。

  ![自定义看板](intro/image/5.自定义看板.png)

- **⚙️ 自动化工作流**：无需手动画布，自动判断业务需求创建工作表记录触发、定时触发引擎，甚至一键追加更新字段、发送通知等执行动作节点。

  ![工作流](intro/image/7.工作流.png)

- **🤖 智能问答机器人**：一键绑定相关业务库并快速部署智能 AI 客服通道。

  ![对话机器人](intro/image/4.对话机器人.png)

- **🎭 角色与权限**：规划并建立“管理员”、“普通员工”、“审批人”等角色权限体系。

  ![应用角色](intro/image/6.应用角色.png)

- **🎲 Mock 数据自动化**：打破空应用没法体验的窘境，依据当前字段条件智能注入带有真实语境的测试数据集。

---

## 🔑 密钥获取指南

在运行 `setup.py` 时，需要填写以下信息。为了顺畅体验，建议提前准备：

| 参数名称 | 用途 | 获取方式 |
|---|---|---|
| **Gemini API Key** | AI 大脑，负责需求理解、架构规划和数据生成 | 前往 [Google AI Studio](https://aistudio.google.com/apikey) 申请 |
| **app_key** / **secret_key** | 用于调用明道云 OpenAPI | 组织管理 → 集成 → 其他 → 开放接口 → 密钥<br> （`https://www.mingdao.com/admin/integrationothers/你的组织ID`） |
| **project_id** (组织 ID) | 指定应用所属组织 | 组织管理 → 组织 → 组织信息 → 编号（ID） |
| **owner_id** (拥有者) | 指定应用拥有者 | 进入明道云，点击群聊中的个人头像，浏览器地址栏中 `user_xxx` 的 `xxx` 部分 |
| **group_ids** (分组 ID) | [*可选*] 应用创建后的所在分组 | 点击某个应用分组，地址栏中 `groupId=xxx` 的 `xxx` 即是 |
| **登录账号/密码** | 自动登录并获取网页端凭证 | 提供你有明道云**组织管理员**权限的登录账号 |

---

## ⚠️ 声明

本项目基于作者个人兴趣开发。所有功能实现依赖于 HAP 的公开 API 以及部分浏览器接口抓包分析。
> **注意**：如果未来前端内部接口发生变动，可能会导致项目中部分自动化功能无法运行。遇到此情况时，可能需要重新调试或等待作者更新代码。

**如有任何问题或交流需求，欢迎联系作者微信：`houbaole`**
