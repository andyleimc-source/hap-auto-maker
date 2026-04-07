# 多供应商 AI 支持设计文档

**日期：** 2026-04-07  
**状态：** 已确认  
**方案：** A（最小改动，注册表扩展）

---

## 背景

项目当前支持 Gemini 和 DeepSeek 两个 AI 供应商。需新增 MiniMax、Kimi、智谱 GLM、豆包、千问共 5 个供应商。

所有新供应商均兼容 OpenAI SDK，与 DeepSeek 接口形式完全一致，可复用现有 `GeminiCompatibilityClient`。

---

## 核心原则

**不得预设默认模型名。** 配置文件中的 model 字段必须来自用户在 setup.py 中从真实 API 拉取的模型列表中选择的结果。若 `/models` 端点不可用，则提示用户手动输入。

---

## 供应商注册表

| 供应商 key | 别名 | base_url |
|-----------|------|----------|
| `gemini` | `google`, `google-genai` | （使用 google-genai SDK）|
| `deepseek` | `deepseek-chat`, `deepseek-reasoner` | `https://api.deepseek.com` |
| `minimax` | — | `https://api.minimaxi.com/v1` |
| `kimi` | `moonshot` | `https://api.moonshot.cn/v1` |
| `zhipu` | `glm`, `bigmodel` | `https://open.bigmodel.cn/api/paas/v4` |
| `doubao` | `ark`, `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` |
| `qwen` | `qianwen`, `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

---

## 改动文件

### 1. `scripts/hap/ai_utils.py`

#### 新增常量 `PROVIDER_BASE_URLS`

替换现有的 `DEFAULT_DEEPSEEK_BASE_URL` 常量：

```python
PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "minimax":  "https://api.minimaxi.com/v1",
    "kimi":     "https://api.moonshot.cn/v1",
    "zhipu":    "https://open.bigmodel.cn/api/paas/v4",
    "doubao":   "https://ark.cn-beijing.volces.com/api/v3",
    "qwen":     "https://dashscope.aliyuncs.com/compatible-mode/v1",
}
```

保留 `DEFAULT_DEEPSEEK_BASE_URL = PROVIDER_BASE_URLS["deepseek"]` 作为向后兼容别名。

移除 `DEFAULT_MODELS` 中新供应商的条目（不预设模型名），保留 Gemini / DeepSeek 的默认模型供 fallback。

#### `normalize_provider()` 扩展

```python
if raw in {"minimax"}:
    return "minimax"
if raw in {"kimi", "moonshot"}:
    return "kimi"
if raw in {"zhipu", "glm", "bigmodel"}:
    return "zhipu"
if raw in {"doubao", "ark", "volcengine"}:
    return "doubao"
if raw in {"qwen", "qianwen", "dashscope"}:
    return "qwen"
```

#### `list_models()` 扩展

所有新供应商使用 OpenAI SDK 拉取：

```python
if p in {"deepseek", "minimax", "kimi", "zhipu", "doubao", "qwen"}:
    url = base_url or PROVIDER_BASE_URLS.get(p, "")
    client = OpenAI(api_key=api_key, base_url=url, timeout=15.0)
    resp = client.models.list()
    return sorted(m.id for m in resp.data if m.id)
```

若 API 不支持 `/models` 端点，捕获异常返回 `[]`，由 `setup.py` 提示用户手动输入。

#### `default_base_url_for_provider()` 改为查表

```python
def default_base_url_for_provider(provider: str) -> str:
    p = normalize_provider(provider)
    return PROVIDER_BASE_URLS.get(p, "")
```

#### `get_ai_client()` 路由扩展

```python
if provider in PROVIDER_BASE_URLS:  # 所有 OpenAI 兼容供应商
    return GeminiCompatibilityClient(provider, api_key, model, base_url)
```

---

### 2. `setup.py`

#### `step_ai()` 供应商选择菜单扩展

从现有的 `(1=Gemini, 2=DeepSeek)` 扩展为展示全部 7 个供应商的编号列表。

**流程：**
1. 展示编号菜单，用户输入 1-7
2. 根据选择获取对应 provider key 和 base_url
3. 提示输入 API Key
4. 调用 `list_models(provider, key, base_url)` 拉取真实模型列表
5. 若列表非空：展示编号列表 → 用户选择编号或直接输入模型名
6. 若列表为空：提示手动输入模型名
7. 保存 `{provider, api_key, model, base_url}` 到 `ai_auth.json`

**key_mismatch 检测扩展：** 由于新供应商 key 格式各异，仅保留 Gemini（`AIza`）和 DeepSeek（`sk-`）的格式检测，其他供应商跳过格式校验。

---

## 数据流

```
用户运行 setup.py
    → 选择供应商编号 (1-7)
    → 输入 API Key
    → list_models() 调用供应商 /models API
    → 用户从真实列表选择模型
    → 写入 ai_auth.json {provider, api_key, model, base_url}

运行时 make_app.py
    → load_ai_config() 读取 ai_auth.json
    → normalize_provider() 标准化
    → get_ai_client() 路由到对应客户端
    → GeminiCompatibilityClient (OpenAI SDK) 或 _GeminiRpdWrapper (Gemini SDK)
```

---

## 错误处理

- `list_models()` 超时或 API 不支持 `/models`：捕获所有异常，返回 `[]`，由 setup.py 降级为手动输入
- `normalize_provider()` 遇到未知供应商：抛出 `ValueError`，提示支持的供应商列表
- `get_ai_client()` 遇到未知 provider：抛出 `ValueError`

---

## 不在本次范围内

- RPD 追踪（目前仅 Gemini，新供应商不追踪）
- 多账号 / 轮换 API Key
- 供应商特定参数（如 MiniMax 的 `reasoning_split`）
