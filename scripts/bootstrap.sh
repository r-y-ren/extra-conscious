#!/usr/bin/env bash
# Extra-Conscious 新设备幂等自举脚本
# 用法: ./scripts/bootstrap.sh [--check]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
export PATH="$BIN_DIR:$PATH"

if [ "$CHECK_ONLY" -eq 0 ]; then
  echo "== Extra-Conscious 本机初始化 =="
  if ! command -v uv >/dev/null 2>&1; then
    echo "[ERROR] uv is required. Install via: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
  fi

  # 使用 uv tool 安装/升级可编辑 CLI，确保 ~/.local/bin/recon 始终走 PATH
  uv tool install --force --editable "$REPO_ROOT"

  echo "== 初始化默认配置与 DuckDB 扩展 =="
  recon init >/dev/null
fi

echo "== 运行环境自检 (recon doctor) =="
recon doctor
