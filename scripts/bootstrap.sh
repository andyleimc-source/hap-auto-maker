#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"

if [ ! -d "$VENV_DIR" ]; then
  echo "[bootstrap] 创建虚拟环境: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[bootstrap] 升级 pip"
python -m pip install --upgrade pip

echo "[bootstrap] 安装依赖 requirements.txt"
pip install -r requirements.txt

echo "[bootstrap] 安装 Playwright Chromium"
python -m playwright install chromium >/dev/null 2>&1 || true

echo "[bootstrap] 运行健康检查"
python - <<'PY'
import importlib.util
mods = [
    "requests", "openai", "google.genai", "playwright", "json_repair", "faker"
]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
if missing:
    raise SystemExit(f"缺少模块: {missing}")
print("依赖检查通过")
PY

python make_app.py --help >/dev/null

echo "[bootstrap] 完成。请执行：source $VENV_DIR/bin/activate"
