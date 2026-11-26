# Extra-Conscious

> 通过 **Skill 混合检索库**、**结构化学术检索** 与 **可验证骨架闭环**，使 AI Agent 可靠完成处于用户认知盲区之外的复杂工程与科研复现任务。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](./pyproject.toml)

---

## 为什么需要 Extra-Conscious

当用户熟悉某个领域时，可以作为中途验收者不断拦截 Agent 的误差；而当任务处于用户的**认知之外**时，人无法判断分解是否正确、术语是否准确，模型容易退回过时先验并产生复利式幻觉。

**Extra-Conscious** 通过**把验收权外包给客观机制**来解决这一问题：
1. **三线分离**：检索相关性由确定性脚本算纯分数（本地与社区技能完全同权，无来源偏置）；骨架适配度由子代理精读终审；信任治理仅以元数据记录并交由唯一人工检查点裁决。
2. **先立术语与骨架，再填技术细节**：先通过学术 API 多源侦察建立双语术语表与分面地图，再按分面检索已有技能或从「论文 + 官方仓 + 复现仓」反推骨架，通过硬闸门 `recon lint` 后仅保留一道人工检查点。
3. **两段式验证锚点与复利沉淀**：阶段 4 锁定验证类型与出处规格，阶段 5 锁定论文后回填精确指标数值；每反推并确认一个新领域技能，自动回流本地检索库，越用认知外越少。

---

## 六阶段端到端工作流

```text
日常语言需求（无术语、无流程知识）
 │
 ├─ 阶段 1 · Survey 侦察         [recon fetch + survey-recon 子代理]
 │    Wikipedia / OpenAlex / S2 / GitHub 迭代扩词（≥2 独立来源进表）
 │    → .recon/01-terms.md（含显式 facet 分面） + .recon/02-survey.md（流派图 + 临时路线推荐）
 │
 ├─ 阶段 2 · Skill 检索          [纯脚本 recon search，零代理]
 │    按 facet 构造双语查询 → DuckDB fts(BM25) + vss(bge-m3 HNSW) + RRF 融合（同权计分）
 │    → .recon/03-candidates.md（high 候选池 / medium 终审池 / low 缺口记录）
 │
 ├─ 阶段 3 · 分面综合 / 多源反推   [skill-synth 子代理]（按 facet 并行）
 │    ├─ 命中流程级高置信 → 综合装配（领域专用 > 通用 > 维护活跃 > 陈旧）+ recon feedback
 │    └─ 缺失 / 仅工具级   → 论文(mineru) + 官方仓 + 复现仓 六步融合 → 新 SKILL.md 草案
 │    → .recon/03-skills.md
 │
 ├─ 阶段 4 · 骨架合成与 Lint 闸门 [skeleton-builder 子代理 + recon lint / check-deps]
 │    宏观段装配 + DAG 拓扑嵌入 + 外部工具依赖聚合 + 两段式验证锚点
 │    → .recon/04-skeleton.md（单文件双视图：人审视图 + 执行视图 YAML 卡片）
 │
 ▼ 【唯一人工检查点】裁决路线、决策点、红旗清单、人工抽查排期、generated 技能入库
 │
 ├─ 阶段 5 · 论文/开源精准填充    [recon fill + paper-filler 子代理]
 │    Semantic Scholar / arXiv / HF Papers / GitHub 检索 + mineru/ast-grep 深度解析
 │    → .recon/05-references.md + 回填 04-skeleton.md 锚点数值 + 目标项目 tests/ 测试桩
 │
 └─ 阶段 6 · 可验证执行与终验     [执行引擎 + fn-ladder / remote-compute / bwrap-run]
      步级（失败步内修复 ≤3 次后上抛）→ 段级 → 项目级端到端验收
      → .recon/06-deviation-report.md + 反馈/新技能写回 library.duckdb
```

---

## 目录与资产隔离设计

严格区分**跨项目通用资产**与**单次目标任务工作区**：

| 层级 | 位置 | 存放内容 | 绝对禁止存放 |
| :--- | :--- | :--- | :--- |
| **通用技能与工具资产** | 插件技能目录 + 用户指定的 `skill_library_dir`（默认 `~/.local/share/extra-conscious/skill-library/`） | `SKILL.md`、子代理规范、`~/.local/bin/recon`、`library.duckdb`、收录技能快照 | 任何具体任务的论文、参考仓库或业务/验证测试文件 |
| **目标项目工作目录** | 运行工作流开发具体项目的目录 | 目标项目代码、`tests/`（阶段 4–5 生成的验证测试桩）及 `.recon/`（`cache.duckdb`、`papers/`、`repos/`、`01`–`06` 报告） | 修改通用技能源码 |
| **本工程源码仓** | `extra-conscious/` | `src/recon/` CLI、`skills/extra-conscious/`、自举脚本与 `recon` 自身单元测试 `tests/` | `tests/` 不会打包进技能目录 |

---

## 安装与新设备自部署

本工作流的所有依赖均在 [DEPENDENCIES.md](./DEPENDENCIES.md) 显式声明。新设备上的 Agent 可按以下流程一键完成自举配置：

### 1. 克隆并一键初始化

```bash
git clone https://github.com/r-y-ren/extra-conscious.git
cd extra-conscious
./scripts/bootstrap.sh
```

`bootstrap.sh` 会幂等完成：
- 通过 `uv tool install --editable` 将 `recon` 安装至 `~/.local/bin/recon`；
- 生成默认配置文件 `~/.config/extra-conscious/config.toml`（不覆盖已有配置）；
- 初始化 `library.duckdb` 并尝试安装 DuckDB `fts` 与 `vss` 扩展；
- 运行 `recon doctor` 输出完整环境诊断报告。

### 2. 作为插件安装（ZCode / Antigravity / Claude Code）

本仓库根目录已提供 [marketplace.json](./marketplace.json)、[.zcode-plugin/plugin.json](./.zcode-plugin/plugin.json) 与 [plugin.json](./plugin.json)：
- **ZCode**：设置 → 插件管理 → 发现 → `+` 添加市场，填入 `https://github.com/r-y-ren/extra-conscious.git` 后安装启用；
- **配合插件**：强烈建议同时安装 [my-plugin](https://github.com/r-y-ren/my-plugin)（提供 `mineru`、`trafilatura`、`duckdb`、`ast-grep`、`bwrap-run`、`remote-compute`）与可选的 [fn-ladder](https://github.com/r-y-ren/fn-ladder)。

### 3. 收录本地技能与可选向量配置

```bash
# 扫描配置的所有本地插件技能入库（自动按内容哈希去重）
recon ingest local

# （可选）同步公开社区技能仓
recon ingest sync --repo anthropics/skills --repo obra/superpowers

# （可选）配置本地/远端/API 向量后端后补算 bge-m3 向量
recon embed
```

> 若暂未配置向量模型，阶段 2 会无缝以 DuckDB `fts`（BM25）词法混合通道工作，`recon doctor` 会标注提示而不阻断流程。

---

## CLI 命令速查

| 命令 | 用途 |
| :--- | :--- |
| `recon doctor [--json]` | 检查 Python、CLI 工具、插件、`gh` 登录态、DuckDB `fts`/`vss` 与嵌入后端 |
| `recon init [--lib-dir PATH]` | 生成默认配置、初始化技能库与 DuckDB 扩展 |
| `recon init-workspace [PATH]` | 在目标项目目录创建 `.recon/` 与 `cache.duckdb` |
| `recon ingest local \| dir \| sync` | 收录本地插件、任意目录或增量同步 GitHub 技能仓 |
| `recon embed [--backend ...] [--batch-size N]` | 为未嵌入段落增量计算向量（支持 `sentence_transformers` / `openai_compat` / `remote`） |
| `recon fetch <provider> --query "..."` | 阶段 1/5 缓存抓取（`wiki` / `openalex` / `s2` / `arxiv` / `hf` / `github` / `web` / `all`） |
| `recon search [--workspace .]` | 阶段 2 纯脚本混合检索并生成 `.recon/03-candidates.md` |
| `recon lint <04-skeleton.md> [--strict-anchors]` | 阶段 4/5 硬闸门：校验出处、验证命令、无悬空输入、DAG 无环与锚点回填 |
| `recon check-deps <04-skeleton.md>` | 汇总并核验骨架中所有入选技能的外挂工具/环境变量/插件依赖 |
| `recon feedback ...` / `recon trust ...` | 写回检索反馈或更新技能治理状态（`reference` / `adopted` / `generated`） |
| `recon fill fetch \| paper \| repo ...` | 阶段 5 按步骤待填项批抓、PDF `mineru` 解析与参考仓浅克隆 |

---

## 仓库结构

```text
extra-conscious/
├── marketplace.json                 # 插件市场清单
├── plugin.json                      # 插件元数据（Antigravity 兼容）
├── .zcode-plugin/plugin.json        # 插件元数据（ZCode / Claude Code 兼容）
├── pyproject.toml                   # uv / Python 项目配置（CLI: recon）
├── DEPENDENCIES.md                  # 显式依赖表与新设备 Agent 冷启动部署协议
├── docs/
│   └── ARCHITECTURE.md              # 详细六阶段架构与 DuckDB Schema
├── skills/extra-conscious/          # 纯净通用工作流技能资产（不含任何测试文件）
│   ├── SKILL.md                     # 六阶段编排与冷启动自检入口
│   └── agents/                      # 四阶段子代理规范（survey / skill-synth / skeleton / paper-filler）
├── scripts/
│   ├── bootstrap.sh                 # 新设备一键安装与自检（支持 --check）
│   ├── sync-library.sh              # 定期增量同步与索引刷新（cron / systemd timer）
│   └── embed-remote.sh              # 通过 remote-compute 远端 GPU 批计算向量
├── src/recon/                       # 确定性 CLI 工具实现
└── tests/                           # recon CLI 自身单元测试（不进入技能包）
```

---

## 开发与测试

```bash
uv sync --extra dev
uv run pytest -v
./scripts/bootstrap.sh --check
```

更多设计细节见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) 与 [DEPENDENCIES.md](./DEPENDENCIES.md)。
