# HAP Auto Maker

基于多模型 AI（Gemini / DeepSeek / MiniMax / Kimi / 智谱 GLM / 豆包 / 千问）+ HAP 的自动化应用搭建引擎。
通过自然语言描述需求，全自动完成从建表到上线的完整链路：**创建应用 → 工作表与字段 → 视图与筛选 → 统计图表页 → 智能机器人 → Mock 数据**，多步骤流水线并行执行，零人工干预。

---

## 📦 安装

**环境要求**
- 操作系统：**macOS / Linux**
- Python 版本：**3.11 或 3.12**（低于 3.11 将导致运行失败）
- 权限要求：需提供具有**明道云组织管理员**权限的账号

**第一步：克隆仓库并安装依赖**

```bash
git clone https://github.com/andyleimc-source/hap-auto-maker.git
cd hap-auto-maker
bash scripts/bootstrap.sh
source .venv/bin/activate
```

**第二步：初始化配置（首次使用）**

```bash
python3 setup.py
```

执行后进入引导向导，按提示填写 AI 密钥、HAP 密钥和登录账号。配置保存在 `config/credentials/`，后续启动无需重复执行。

**其他 setup 选项**

| 命令 | 说明 |
|------|------|
| `python3 setup.py` | 引导式全量安装（首次使用） |
| `python3 setup.py --menu` | 管理模式，增量修改 AI 平台、HAP 密钥或登录账号 |
| `python3 setup.py --init` | 彻底重置，清空所有配置并重新引导 |

---

## 🚀 启动

### 方式一：make_app.py 命令行（推荐）

```bash
# 从需求文本全自动生成并执行
python3 make_app.py --requirements "CRM客户关系管理系统，包含客户、联系人、商机、跟进记录、合同五张表"

# 生成英文应用
python3 make_app.py --requirements "Create an invoice app with customers, invoices and payments" --language en

# 只生成 spec，不执行（预览用）
python3 make_app.py --requirements "..." --no-execute

# 使用已有 spec 文件跳过 AI 生成直接执行
python3 make_app.py --spec-json path/to/spec.json

# 依赖策略（默认 auto，建议保持）
python3 make_app.py --requirements "..." --deps-mode auto
```

## 🎬 核心特性

- **Wave 并行引擎**：多步流水线分 Wave 并行调度，相互独立的步骤同时执行，大幅缩短总耗时。
- **全流程覆盖**：从创建应用到统计图表，一次命令跑完所有环节，无需人工介入。
- **注册中心驱动**：38 种字段类型、11 种视图类型、17 种图表类型均有完整 Schema，AI 规划基于精确约束生成，减少错误。
- **动态复杂度计算**：统计图表数量、Page 数量可根据应用规模自动调整，不过度也不不足。
- **增量操作支持**：对已有应用可单独添加工作表、字段、视图，无需重建整个应用。

---

## 🛠️ 自动化搭建能力矩阵

| 模块 | 能力 |
|------|------|
| **应用创建** | 自动命名、主色调、图标语义匹配 |
| **工作表与字段** | 38 种字段类型、表间关联、分组布局、自动图标 |
| **视图** | 11 种视图类型（列表/看板/画廊/层级/日历等），含筛选与排序规则 |
| **统计图表页** | 17 种图表类型，每页图表数量按关联工作表数动态计算 |
| **智能机器人** | 绑定业务工作表，一键部署 AI 问答助手 |
| **角色权限** | 自动规划管理员/员工/审批人等角色体系 |
| **Mock 数据** | 根据字段类型智能生成带真实语境的测试数据 |

---

## 🔑 密钥获取指南

运行 `setup.py` 时需要填写以下信息：

| 参数 | 用途 | 获取方式 |
|------|------|------|
| **AI API Key** | AI 规划引擎（支持 Gemini / DeepSeek / MiniMax / Kimi / 智谱 GLM / 豆包 / 千问） | 对应厂商开放平台控制台获取 |
| **app_key / secret_key** | 调用明道云 OpenAPI | 组织管理 → 集成 → 其他 → 开放接口 → 密钥 |
| **project_id** | 指定应用所属组织 | 组织管理 → 组织信息 → 编号 |
| **owner_id** | 指定应用拥有者 | 个人头像 → 地址栏 `user_xxx` 的 `xxx` 部分 |
| **group_ids** | （可选）应用分组 | 点击分组 → 地址栏 `groupId=xxx` |
| **登录账号/密码** | 获取网页端凭证 | 具有组织管理员权限的账号 |

---

## ⚠️ 声明

本项目基于作者个人兴趣开发，依赖 HAP 公开 API 及部分浏览器接口抓包分析。前端内部接口如发生变动，部分功能可能需要重新调试。

**如有问题或交流需求，欢迎联系作者微信：`houbaole`**

---

## 关注我

<img src="./雷码工坊微信公众号.jpg" alt="雷码工坊笔记微信公众号" width="200" />

**雷码工坊笔记** — 微信扫码关注
