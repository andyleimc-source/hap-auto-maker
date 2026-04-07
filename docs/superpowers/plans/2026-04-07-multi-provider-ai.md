# Multi-Provider AI Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Gemini + DeepSeek 基础上，新增 MiniMax、Kimi、智谱 GLM、豆包、千问共 5 个 OpenAI 兼容供应商。

**Architecture:** 所有新供应商均兼容 OpenAI SDK，复用现有 `GeminiCompatibilityClient`。在 `ai_utils.py` 中引入 `PROVIDER_BASE_URLS` 注册表统一管理，扩展 `normalize_provider`、`list_models`、`get_ai_client`。`setup.py` 的 `step_ai()` 扩展选单为 7 个供应商，真实拉取模型列表供用户选择，不预设任何模型名。

**Tech Stack:** Python 3.12, openai SDK (已安装), pytest

---

## 文件改动清单

| 文件 | 操作 |
|------|------|
| `scripts/hap/ai_utils.py` | 修改：新增注册表常量、扩展 4 个函数 |
| `setup.py` | 修改：`step_ai()` 供应商选单从 2 个扩展到 7 个 |
| `tests/unit/test_ai_utils.py` | 修改：新增新供应商的 normalize / base_url 测试 |

---

## Task 1: 扩展 `normalize_provider()` 和 `PROVIDER_BASE_URLS`

**Files:**
- Modify: `scripts/hap/ai_utils.py:20-23, 88-104, 145-146`
- Test: `tests/unit/test_ai_utils.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_ai_utils.py` 的 `TestNormalizeProvider` 类末尾追加：

```python
    def test_minimax_variants(self):
        assert normalize_provider("minimax") == "minimax"
        assert normalize_provider("MiniMax") == "minimax"

    def test_kimi_variants(self):
        assert normalize_provider("kimi") == "kimi"
        assert normalize_provider("moonshot") == "kimi"

    def test_zhipu_variants(self):
        assert normalize_provider("zhipu") == "zhipu"
        assert normalize_provider("glm") == "zhipu"
        assert normalize_provider("bigmodel") == "zhipu"

    def test_doubao_variants(self):
        assert normalize_provider("doubao") == "doubao"
        assert normalize_provider("ark") == "doubao"
        assert normalize_provider("volcengine") == "doubao"

    def test_qwen_variants(self):
        assert normalize_provider("qwen") == "qwen"
        assert normalize_provider("qianwen") == "qwen"
        assert normalize_provider("dashscope") == "qwen"
```

新增测试类（在文件末尾追加）：

```python
class TestDefaultBaseUrl:
    def test_gemini_has_no_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("gemini") == ""

    def test_deepseek_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("deepseek") == "https://api.deepseek.com"

    def test_minimax_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("minimax") == "https://api.minimaxi.com/v1"

    def test_kimi_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("kimi") == "https://api.moonshot.cn/v1"

    def test_zhipu_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("zhipu") == "https://open.bigmodel.cn/api/paas/v4"

    def test_doubao_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("doubao") == "https://ark.cn-beijing.volces.com/api/v3"

    def test_qwen_base_url(self):
        from ai_utils import default_base_url_for_provider
        assert default_base_url_for_provider("qwen") == "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /Users/andy/Documents/coding/hap-auto-maker
python -m pytest tests/unit/test_ai_utils.py::TestNormalizeProvider::test_minimax_variants tests/unit/test_ai_utils.py::TestDefaultBaseUrl -v 2>&1 | tail -20
```

期望：`FAILED` 或 `ERROR`（normalize_provider 未知供应商抛 ValueError）

- [ ] **Step 3: 修改 `ai_utils.py` — 常量部分**

将文件开头（第 20-23 行附近）的常量块**整体替换**为：

```python
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"  # 向后兼容别名

# 所有 OpenAI 兼容供应商的默认 base_url（Gemini 不在此表，使用 google-genai SDK）
PROVIDER_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "minimax":  "https://api.minimaxi.com/v1",
    "kimi":     "https://api.moonshot.cn/v1",
    "zhipu":    "https://open.bigmodel.cn/api/paas/v4",
    "doubao":   "https://ark.cn-beijing.volces.com/api/v3",
    "qwen":     "https://dashscope.aliyuncs.com/compatible-mode/v1",
}
```

- [ ] **Step 4: 修改 `ai_utils.py` — `normalize_provider()`**

将现有函数（第 94-100 行）完整替换为：

```python
def normalize_provider(provider: str) -> str:
    raw = str(provider or "").strip().lower()
    if raw in {"", "gemini", "google", "google-genai"}:
        return "gemini"
    if raw in {"deepseek", "deepseek-chat", "deepseek-reasoner"}:
        return "deepseek"
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
    supported = "gemini / deepseek / minimax / kimi / zhipu / doubao / qwen"
    raise ValueError(f"不支持的 AI 供应商: {provider}。支持的供应商: {supported}")
```

- [ ] **Step 5: 修改 `ai_utils.py` — `default_base_url_for_provider()`**

将现有函数（第 145-146 行）完整替换为：

```python
def default_base_url_for_provider(provider: str) -> str:
    return PROVIDER_BASE_URLS.get(normalize_provider(provider), "")
```

- [ ] **Step 6: 修改 `ai_utils.py` — `DEFAULT_MODELS` 和 `default_model_for_provider()`**

将现有 `DEFAULT_MODELS` dict（第 88-91 行）和 `default_model_for_provider` 函数（第 103-104 行）替换为：

```python
# Gemini/DeepSeek 保留 fallback；新供应商无预设模型，必须由用户选择
DEFAULT_MODELS = {
    "gemini":   DEFAULT_GEMINI_MODEL,
    "deepseek": DEFAULT_DEEPSEEK_MODEL,
}


def default_model_for_provider(provider: str) -> str:
    """返回供应商的 fallback 模型名。新供应商无默认，返回空字符串。"""
    return DEFAULT_MODELS.get(normalize_provider(provider), "")
```

- [ ] **Step 7: 运行测试，确认通过**

```bash
python -m pytest tests/unit/test_ai_utils.py::TestNormalizeProvider tests/unit/test_ai_utils.py::TestDefaultBaseUrl -v 2>&1 | tail -20
```

期望：全部 `PASSED`

- [ ] **Step 8: 提交**

```bash
git add scripts/hap/ai_utils.py tests/unit/test_ai_utils.py
git commit -m "feat: 新增 5 个 OpenAI 兼容供应商注册表 (MiniMax/Kimi/智谱/豆包/千问)"
```

---

## Task 2: 扩展 `list_models()` 和 `get_ai_client()`

**Files:**
- Modify: `scripts/hap/ai_utils.py:107-142, 368-384`

- [ ] **Step 1: 修改 `ai_utils.py` — `list_models()`**

将现有函数（第 107-142 行）完整替换为：

```python
def list_models(provider: str, api_key: str, base_url: str = "") -> list:
    """
    从厂商 API 拉取可用模型列表。失败时返回空列表。
    Gemini 使用 google-genai SDK；其余供应商均 OpenAI 兼容，统一使用 openai SDK。
    """
    p = normalize_provider(provider)
    try:
        if p == "gemini":
            from google import genai
            client = genai.Client(api_key=api_key)
            models = []
            for m in client.models.list():
                name = m.name or ""
                short = name.replace("models/", "") if name.startswith("models/") else name
                if not short:
                    continue
                actions = [a.value if hasattr(a, "value") else str(a) for a in (m.supported_actions or [])]
                if "generateContent" not in actions:
                    continue
                if not short.startswith("gemini-"):
                    continue
                skip_keywords = ("-tts", "-audio", "-robotics", "-image", "-live", "-computer-use")
                if any(kw in short for kw in skip_keywords):
                    continue
                models.append(short)
            return sorted(models)

        # 所有 OpenAI 兼容供应商（deepseek / minimax / kimi / zhipu / doubao / qwen）
        if p in PROVIDER_BASE_URLS:
            from openai import OpenAI
            url = base_url or PROVIDER_BASE_URLS[p]
            client = OpenAI(api_key=api_key, base_url=url, timeout=15.0)
            resp = client.models.list()
            return sorted(m.id for m in resp.data if m.id)

    except Exception as e:
        print(f"  ⚠️  拉取 {p} 模型列表失败: {e}")
    return []
```

- [ ] **Step 2: 修改 `ai_utils.py` — `get_ai_client()`**

将现有函数（第 368-384 行）完整替换为：

```python
def get_ai_client(config: Optional[Dict[str, str]] = None):
    """根据配置获取相应的 AI 客户端。"""
    if config is None:
        config = load_ai_config()

    provider = normalize_provider(config.get("provider", "gemini"))
    api_key = config.get("api_key", "")
    model = config.get("model", "") or default_model_for_provider(provider)

    if provider == "gemini":
        from google import genai
        raw_client = genai.Client(api_key=api_key)
        return _GeminiRpdWrapper(raw_client, model)

    # 所有 OpenAI 兼容供应商
    if provider in PROVIDER_BASE_URLS:
        return GeminiCompatibilityClient(provider, api_key, model, config.get("base_url"))

    raise ValueError(f"不支持的 AI 供应商: {provider}")
```

- [ ] **Step 3: 运行全量 ai_utils 测试**

```bash
python -m pytest tests/unit/test_ai_utils.py -v 2>&1 | tail -30
```

期望：全部 `PASSED`（无网络测试不涉及 `list_models` 和 `get_ai_client` 的实际 API 调用）

- [ ] **Step 4: 快速冒烟测试 — 检查 normalize 和 base_url 对所有供应商工作**

```bash
cd /Users/andy/Documents/coding/hap-auto-maker
python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
from ai_utils import normalize_provider, default_base_url_for_provider, PROVIDER_BASE_URLS
providers = ['gemini', 'deepseek', 'minimax', 'kimi', 'zhipu', 'doubao', 'qwen',
             'moonshot', 'glm', 'ark', 'qianwen']
for p in providers:
    n = normalize_provider(p)
    url = default_base_url_for_provider(p)
    print(f'{p:12} -> {n:10} | {url}')
"
```

期望输出示例（无报错）：
```
gemini       -> gemini     |
deepseek     -> deepseek   | https://api.deepseek.com
minimax      -> minimax    | https://api.minimaxi.com/v1
kimi         -> kimi       | https://api.moonshot.cn/v1
zhipu        -> zhipu      | https://open.bigmodel.cn/api/paas/v4
doubao       -> doubao     | https://ark.cn-beijing.volces.com/api/v3
qwen         -> qwen       | https://dashscope.aliyuncs.com/compatible-mode/v1
moonshot     -> kimi       | https://api.moonshot.cn/v1
glm          -> zhipu      | https://open.bigmodel.cn/api/paas/v4
ark          -> doubao     | https://ark.cn-beijing.volces.com/api/v3
qianwen      -> qwen       | https://dashscope.aliyuncs.com/compatible-mode/v1
```

- [ ] **Step 5: 提交**

```bash
git add scripts/hap/ai_utils.py
git commit -m "feat: 扩展 list_models 和 get_ai_client 支持 5 个新供应商"
```

---

## Task 3: 扩展 `setup.py` — 供应商选单

**Files:**
- Modify: `setup.py:210-279`

- [ ] **Step 1: 替换 `step_ai()` 函数**

将 `setup.py` 中整个 `step_ai()` 函数（第 210-279 行）完整替换为：

```python
def step_ai(force=True):
    from ai_utils import (AI_CONFIG_PATH, PROVIDER_BASE_URLS,
                          load_ai_config, list_models, normalize_provider,
                          default_base_url_for_provider)
    existing = {}
    try:
        existing = load_ai_config()
    except Exception:
        pass

    print_box("第 1 步：配置 AI 平台 (AI Provider)")

    # 供应商菜单
    PROVIDERS = [
        ("gemini",   "Gemini (Google)"),
        ("deepseek", "DeepSeek"),
        ("minimax",  "MiniMax"),
        ("kimi",     "Kimi (Moonshot)"),
        ("zhipu",    "智谱 GLM"),
        ("doubao",   "豆包 (Doubao/Volcengine)"),
        ("qwen",     "千问 (Qwen/Alibaba)"),
    ]
    old_p = existing.get("provider", "")
    print("\n   可用 AI 供应商：")
    for i, (key, label) in enumerate(PROVIDERS, 1):
        marker = " [当前]" if key == old_p else ""
        print(f"      {i}. {label}{marker}")

    valid_choices = [str(i) for i in range(1, len(PROVIDERS) + 1)]
    default_choice = next(
        (str(i) for i, (key, _) in enumerate(PROVIDERS, 1) if key == old_p),
        "1"
    )
    p_choice = ask(
        "选择 AI 平台 (输入编号)",
        default=default_choice,
        required=True,
        choices=valid_choices,
    )
    provider, provider_label = PROVIDERS[int(p_choice) - 1]
    provider_changed = provider != old_p

    # API Key
    existing_key = existing.get("api_key", "")
    # 仅对 Gemini/DeepSeek 做 key 格式校验
    key_mismatch = (
        (provider == "gemini" and existing_key.startswith("sk-")) or
        (provider == "deepseek" and existing_key.startswith("AIza"))
    )
    key = ask(
        f"{provider_label} API Key",
        default="" if (provider_changed or key_mismatch) else existing_key,
        required=True,
    )

    # 确定 base_url
    base_url = default_base_url_for_provider(provider)

    # 拉取可用模型列表
    print(f"\n   正在从 {provider_label} API 拉取可用模型列表...")
    models = list_models(provider, key, base_url)

    if models:
        print(f"\n   可用模型 ({len(models)} 个):")
        for i, m in enumerate(models, 1):
            print(f"      {i}. {m}")
        model_input = ask(
            "选择模型 (输入编号或模型名)",
            default="1",
            required=True,
        )
        if model_input.isdigit():
            idx = int(model_input) - 1
            if 0 <= idx < len(models):
                selected_model = models[idx]
            else:
                print(f"   ⚠️  编号超出范围，请手动输入模型名。")
                selected_model = ask("模型名称", default="", required=True)
        else:
            selected_model = model_input.strip()
    else:
        print("   ⚠️  无法拉取模型列表，请手动输入模型名称。")
        old_model = existing.get("model", "") if not provider_changed else ""
        selected_model = ask("模型名称", default=old_model, required=True)

    data = {
        "provider": provider,
        "api_key": key,
        "model": selected_model,
        "base_url": base_url,
    }

    AI_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # 向后兼容：Gemini 同步写入 gemini_auth.json
    if provider == "gemini":
        (CRED_DIR / "gemini_auth.json").write_text(
            json.dumps({"api_key": key, "model": selected_model}, indent=2),
            encoding="utf-8",
        )
    print(f"\n   ✔ AI 平台配置已完成 (供应商: {provider_label}, 模型: {selected_model})。")
```

- [ ] **Step 2: 更新 `setup.py` 中的 `get_status_ai()` 函数**

确认 `get_status_ai()` 函数（第 181-188 行）显示逻辑无需改动（它只读 `provider` 和 `model`，已兼容新供应商）。用以下命令检查：

```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
# 模拟新供应商配置
import json; from pathlib import Path
Path('config/credentials/ai_auth.json').write_text(json.dumps({
    'provider': 'kimi', 'api_key': 'sk-test', 'model': 'moonshot-v1-32k', 'base_url': ''
}))
" 2>/dev/null || true
python3 -c "
import sys; sys.path.insert(0, 'scripts/hap')
sys.path.insert(0, '.')
# 直接测试 get_status_ai 函数逻辑
from ai_utils import AI_CONFIG_PATH
import json
data = json.loads(AI_CONFIG_PATH.read_text())
print('provider:', data.get('provider'))
print('model:', data.get('model'))
"
```

期望：打印出 `provider: kimi` 和 `model: moonshot-v1-32k`

- [ ] **Step 3: 运行全量单元测试，确认无回归**

```bash
python -m pytest tests/unit/test_ai_utils.py -v 2>&1 | tail -20
```

期望：全部 `PASSED`

- [ ] **Step 4: 冒烟测试 `setup.py` 语法**

```bash
python3 -c "import ast; ast.parse(open('setup.py').read()); print('setup.py 语法正确')"
```

期望：`setup.py 语法正确`

- [ ] **Step 5: 还原测试时写入的 ai_auth.json（如有需要）**

```bash
python3 -c "
import json
from pathlib import Path
# 还原为当前真实配置（如果已有备份则手动还原，否则跳过）
p = Path('config/credentials/ai_auth.json')
data = json.loads(p.read_text())
print('当前配置:', json.dumps(data, ensure_ascii=False))
"
```

若配置被测试步骤污染，手动将 `config/credentials/ai_auth.json` 内容还原为实际 Gemini 配置：

```json
{
  "provider": "gemini",
  "api_key": "REDACTED_GOOGLE_API_KEY",
  "base_url": "",
  "model": "gemini-2.5-flash"
}
```

- [ ] **Step 6: 提交**

```bash
git add setup.py
git commit -m "feat: setup.py 供应商选单扩展到 7 个 (MiniMax/Kimi/智谱/豆包/千问)"
```

---

## Task 4: 端到端验证

**Files:** 只读，无修改

- [ ] **Step 1: 运行全量单元测试**

```bash
python -m pytest tests/unit/ -v 2>&1 | tail -30
```

期望：全部 `PASSED`，无新增失败

- [ ] **Step 2: 验证 `ai_utils.py` 自检脚本**

```bash
cd /Users/andy/Documents/coding/hap-auto-maker
python3 scripts/hap/ai_utils.py
```

期望：打印当前 provider/model 信息，无报错

- [ ] **Step 3: 验证 load_ai_config 对所有供应商配置格式正常工作**

```bash
python3 -c "
import sys, json
sys.path.insert(0, 'scripts/hap')
from ai_utils import load_ai_config, normalize_provider, default_base_url_for_provider
from pathlib import Path

configs = [
    {'provider': 'minimax',  'api_key': 'sk-test', 'model': 'MiniMax-M2.7',         'base_url': ''},
    {'provider': 'kimi',     'api_key': 'sk-test', 'model': 'moonshot-v1-auto',      'base_url': ''},
    {'provider': 'zhipu',    'api_key': 'sk-test', 'model': 'glm-4-flash',           'base_url': ''},
    {'provider': 'doubao',   'api_key': 'sk-test', 'model': 'doubao-pro-32k',        'base_url': ''},
    {'provider': 'qwen',     'api_key': 'sk-test', 'model': 'qwen-plus',             'base_url': ''},
]
p = Path('config/credentials/ai_auth.json')
original = p.read_text()

for cfg in configs:
    p.write_text(json.dumps(cfg))
    loaded = load_ai_config()
    base = default_base_url_for_provider(loaded['provider'])
    print(f\"{loaded['provider']:10} model={loaded['model']:25} base_url={base}\")

p.write_text(original)
print('--- 配置已还原 ---')
"
```

期望：5 行输出，各供应商 provider/model/base_url 均正确，最后打印 `--- 配置已还原 ---`

- [ ] **Step 4: 验证 setup.py 供应商菜单展示（非交互式语法检查）**

```bash
python3 -c "
import ast
src = open('setup.py').read()
ast.parse(src)

# 检查关键字符串存在
checks = ['MiniMax', 'Kimi', '智谱 GLM', '豆包', '千问', 'PROVIDER_BASE_URLS']
for c in checks:
    assert c in src, f'缺失关键字: {c}'
    print(f'  ✔ {c}')
print('setup.py 验证通过')
"
```

期望：6 行 `✔` + `setup.py 验证通过`

- [ ] **Step 5: 最终提交（如 Task 3 的提交漏掉了什么）**

```bash
git status
# 若有未提交内容：
git add -p
git commit -m "chore: 多供应商 AI 支持收尾"
```

---

## 自检结果

**Spec 覆盖：**
- ✅ PROVIDER_BASE_URLS 注册表 → Task 1 Step 3
- ✅ normalize_provider 新供应商别名 → Task 1 Step 4
- ✅ default_base_url_for_provider 查表 → Task 1 Step 5
- ✅ DEFAULT_MODELS 不预设新供应商模型 → Task 1 Step 6
- ✅ list_models OpenAI 兼容扩展 → Task 2 Step 1
- ✅ get_ai_client 路由扩展 → Task 2 Step 2
- ✅ setup.py 7 供应商选单 → Task 3 Step 1
- ✅ key_mismatch 只校验 Gemini/DeepSeek → Task 3 Step 1
- ✅ 模型列表为空时手动输入 → Task 3 Step 1
- ✅ Gemini gemini_auth.json 向后兼容 → Task 3 Step 1
- ✅ 端到端验证 → Task 4
