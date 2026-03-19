# HAP Auto Maker

基于 Gemini + HAP自动化应用搭建助手。
通过自然语言对话，全自动完成：**创建应用 → 建立工作表及字段 → 配置视图 → 构造测试数据 → 生成智能机器人** 的完整开发工作流。

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

## 🚀 快速开始

## 🪟 Windows 用户使用方法（最稳方案）

如果你使用的是 **Windows**，最推荐、也最省心的方式是：

> **在 Windows 里安装 WSL2，然后在 Ubuntu 终端中运行本项目。**

这样做的原因很简单：
- 本项目当前 README 主要按 **macOS** 编写。
- 项目运行依赖 `Python + Playwright + Chromium`，在 **类 Linux 环境** 下更稳定，踩坑更少。
- 对 Windows 新手来说，**WSL2 比原生 PowerShell 更稳、更接近作者的开发环境**。

### 1. 你需要先安装的工具

请按下面顺序安装：

1. **WSL2**
   - 微软官方安装说明：
   - [https://learn.microsoft.com/windows/wsl/install](https://learn.microsoft.com/windows/wsl/install)

2. **Ubuntu（在 WSL 中使用）**
   - Microsoft Store 下载页：
   - [https://apps.microsoft.com/store/detail/ubuntu/9PDXGNCFSCZV](https://apps.microsoft.com/store/detail/ubuntu/9PDXGNCFSCZV)

3. **Git for Windows**
   - 官方下载：
   - [https://git-scm.com/download/win](https://git-scm.com/download/win)

4. **Python 3.12**
   - 官方下载页：
   - [https://www.python.org/downloads/windows/](https://www.python.org/downloads/windows/)
   - 推荐直接下载 **Python 3.12.x Windows installer (64-bit)**。

### 2. 安装顺序（小白版）

#### 第一步：安装 WSL2

用管理员身份打开 **PowerShell**，执行：

```powershell
wsl --install
```

执行完成后，**重启电脑**。

> 如果系统提示你已经安装过 WSL，可以跳过这一步。

#### 第二步：安装 Ubuntu

重启后，打开 **Microsoft Store**，搜索并安装 **Ubuntu**。

安装完成后，打开 Ubuntu，系统会提示你创建：
- 一个 Linux 用户名
- 一个 Linux 密码

这个用户名和密码是 **WSL 里的 Ubuntu 账号**，不是 GitHub 账号，也不是明道云账号。

#### 第三步：确认 Ubuntu 能正常打开

安装完成后，打开 **Ubuntu**，你应该能看到类似这样的命令行：

```bash
yourname@DESKTOP-XXXX:~$
```

后面所有命令，都建议在这个 **Ubuntu 窗口**里执行，不要在 Windows 的 CMD 里执行。

### 3. 在 Ubuntu 里安装运行环境

打开 Ubuntu，按顺序执行下面这些命令：

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv
python3 --version
git --version
```

如果你看到 Python 版本是 `3.11` 或 `3.12`，就可以继续。

### 4. 拉取项目代码

继续在 Ubuntu 里执行：

```bash
git clone https://github.com/andyleimc-source/hap-auto-maker.git
cd hap-auto-maker
```

如果你想确认自己已经进入项目目录，可以执行：

```bash
pwd
ls
```

### 5. 初始化项目

在项目目录里执行：

```bash
python3 setup.py
```

这个命令会自动帮你做几件事：
- 安装 Python 依赖
- 安装 Playwright
- 安装 Chromium 浏览器
- 引导你填写项目运行所需的密钥和账号信息

初始化时，终端会让你输入这些内容：
- `Gemini API Key`
- `app_key`
- `secret_key`
- `project_id`
- `owner_id`
- `group_ids`（可选）
- 明道云管理员登录账号
- 明道云管理员登录密码

### 6. 初始化完成后启动项目

执行：

```bash
python3 scripts/run_app_pipeline.py
```

然后按终端提示输入你的应用需求，最后输入：

```text
开始运行
```

程序就会开始自动创建应用、工作表、视图、Mock 数据和相关配置。

### 7. Windows 用户完整命令清单

如果你已经完成了 WSL2 和 Ubuntu 安装，那么从打开 Ubuntu 到启动项目，完整命令如下：

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv
git clone https://github.com/andyleimc-source/hap-auto-maker.git
cd hap-auto-maker
python3 setup.py
python3 scripts/run_app_pipeline.py
```

### 8. 常见问题

#### Q1：为什么不推荐直接在 Windows PowerShell 里运行？

可以尝试，但**不作为最稳方案推荐**。原因是这个项目当前主要按 macOS/类 Unix 环境组织和测试，Windows 原生命令行下更容易遇到：
- Playwright 浏览器安装问题
- Python 版本和路径问题
- 浏览器自动登录认证问题

#### Q2：`python3 setup.py` 卡住了怎么办？

先看终端卡在哪一步：
- 如果卡在依赖安装，通常是网络问题，重新执行一次即可。
- 如果卡在浏览器登录，可能是明道云登录需要验证码、二次确认，或者网络访问异常。

这时可以单独执行认证脚本：

```bash
python3 scripts/auth/refresh_auth.py
```

它会打开浏览器帮助你完成登录认证。

#### Q3：以后更新项目怎么做？

进入项目目录后执行：

```bash
cd ~/hap-auto-maker
git pull
python3 setup.py --force
```

#### Q4：如果我输错了密钥或者想换账号怎么办？

重新执行：

```bash
python3 setup.py --force
```

这个命令会重新引导你填写配置。

### 1. 前置检查
- 操作系统：**macOS**
- Python 环境：**Python 3.11 或 3.12**（低于 3.11 将导致运行失败！[点此下载 3.12 官方安装包](https://www.python.org/ftp/python/3.12.9/python-3.12.9-macos11.pkg)）
- 权限说明：需提供一个具有**明道云组织管理员**权限的账号。

### 2. 克隆与初始化
```bash
git clone https://github.com/andyleimc-source/hap-auto-maker.git
cd hap-auto-maker

# 运行一键初始化（自动安装依赖、引导配置密钥）
python3 setup.py
```
> 💡 **小贴士**：未来如果需要更换账号或更新了项目，随时可以运行 `python3 setup.py --force` 重新初始化。

### 3. 一键构建应用 ✨
所有配置完成后，直接通过以下命令与 HAP Auto 对话并自动创建应用：
```bash
python3 scripts/run_app_pipeline.py
```
> 根据终端提示输入你的应用需求，最后输入「**开始运行**」，剩下的交给 AI 去完成！

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

