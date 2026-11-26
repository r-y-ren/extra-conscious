#!/usr/bin/env bash
# 周期性增量更新 Skill 检索库（供 cron / systemd timer 调用）
# 默认先收录本地插件技能，再增量同步社区源（按 pushed_at 跳过无变更仓库），最后补算缺失向量。
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

recon ingest local
recon ingest sync "$@"
recon embed
