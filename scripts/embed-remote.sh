#!/usr/bin/env bash
# 通过 remote-compute（ssh wsl 等算力机）全量/增量补算缺失的 bge-m3 向量
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
recon embed --backend remote --batch-size "${1:-64}"
