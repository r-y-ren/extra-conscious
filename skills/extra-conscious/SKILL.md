---
name: extra-conscious
description: 面向认知外任务的六阶段可验证侦察与执行工作流：冷启动环境自检 → Survey术语侦察 → 纯脚本Skill混合检索 → 分面综合/多源反推 → 骨架合成与Lint闸门（唯一人工检查点） → 论文/开源填充与锚点回填 → 三层验证执行与差异报告。仅在用户面对不熟悉流程或前沿认知外领域时启用；已知流程的任务由用户直接指导。
requires:
  bins: [recon, git, gh, uv]
  plugins: [my-plugin]
---

# Extra-Conscious：认知外任务侦察与可验证执行工作流

> **核心定位**：已知流程的任务不要走本工作流，由用户直接指导。只有当任务处于用户认知盲区、需要从领域调研建立可靠骨架并用论文/开源证据约束验收时，才启动本流程。

## 目录与资产隔离纪律（必须严格遵守）

1. **通用技能与检索库资产**（本技能目录、子代理规范、`recon` CLI、用户配置的 `skill_library_dir`）：只存跨项目复用的通用知识与索引，**绝不写入任何具体任务的论文、参考仓库或测试文件**。
2. **具体任务工作目录**（当前正在开发的目标项目根）：`.recon/`（API 缓存、论文、参考仓库、`01-terms.md`～`06-deviation-report.md`）以及阶段 4–5 生成的**验证测试文件（`tests/`）和项目源码**全部落盘在目标项目目录内。

---

## 阶段 0 · 冷启动自检与新设备自部署（必跑前置）

在任何设备首次启动本工作流前，先核验工具与依赖插件是否就绪：

```bash
recon doctor --json
```

- **若 `recon` 不在 PATH 或 `ok == false`**：
  1. 读取本仓库/插件根目录的 `DEPENDENCIES.md`（若在安装后的插件目录中，先定位源码仓或按 `DEPENDENCIES.md` 指南部署）；
  2. 执行 `./scripts/bootstrap.sh`（幂等安装 `~/.local/bin/recon`、生成 `~/.config/extra-conscious/config.toml`、初始化 DuckDB `fts`/`vss` 扩展）；
  3. 对缺失的外部插件（`my-plugin` 提供 `mineru` / `trafilatura` / `ast-grep` / `bwrap-run` / `remote-compute`，可选 `fn-ladder`）或系统包（`gh auth login`、`bwrap`），按 `DEPENDENCIES.md` 指引补齐；
  4. 若 `skill_library` 尚为空，先运行 `recon ingest local` 收录本机已有技能。
- **初始化当前目标项目工作区**：

```bash
recon init-workspace .
```

---

## 六阶段执行流

### 阶段 1 · Survey 侦察（子代理 + `recon fetch`）
1. 派发 `survey-recon` 子代理（规范见本技能目录 `agents/survey-recon.md`），传入用户原始需求。
2. 子代理通过 `recon fetch wiki|openalex|s2|github|all --query "..." --workspace .` 迭代扩词，产出：
   - `.recon/01-terms.md`（必须含显式 `分面 (facet)`、`英文术语`、`中文对照`、`独立来源`、`状态`，≥2 个独立来源才标为已确认）
   - `.recon/02-survey.md`（2–3 条技术路线对照 + **临时推荐路线 + 理由**）
3. 门 1 已取消：本阶段不设人工中断，直接带临时路线推荐进入阶段 2。

### 阶段 2 · Skill 检索（纯脚本，零代理）
直接运行确定性脚本（本地与社区技能完全同权，不加来源偏置）：

```bash
recon search --workspace .
```

产出 `.recon/03-candidates.md`（按 `facet` 分组，划分 `high` 候选池、`medium` 终审池 top 20、`low` 缺口记录）。

### 阶段 3 · 按分面分流：综合 vs 多源反推（子代理）
派发 `skill-synth` 子代理（规范见 `agents/skill-synth.md`），对每个 `facet` 独立判定并行处理：
- **综合路径**（该分面存在 `high` 命中且粒度为 `lifecycle`/`process`）：精读终审池全文 → 三类归位（领域流程/工程纪律/工具能力）→ 同槽裁决（领域专用 > 通用 > 有维护 > 陈旧，平手进决策点）→ 误召回/漏召回用 `recon feedback` 写回库。
- **反推路径**（无命中、仅 `medium` 或仅 `tool` 级命中）：选 2–3 个异构源（首选 `1 篇代表论文 + 官方实现仓 + 1 个独立复现仓`），调用 `recon fill paper`（`mineru` 解析）与 `recon fill repo`（浅克隆），按六步融合法生成新的分面 `SKILL.md` 草案（含双语触发词）。
- 产出 `.recon/03-skills.md` 与 `generated` 技能草案。

### 阶段 4 · 全局骨架合成、验证设计与唯一人工检查点
1. 派发 `skeleton-builder` 子代理（规范见 `agents/skeleton-builder.md`），将宏观生命周期段（命中 `fn-ladder` 则复用，否则默认五段）、各分面 DAG 步骤、外挂依赖聚合（所有入选技能的依赖汇总至环境构建段）与四分类可执行验证（采用**两段式锚点**：阶段 4 定类型与锚点出处，数值留待阶段 5 回填）合成为单文件双视图 `.recon/04-skeleton.md`。
2. 运行硬闸门校验（不过不放行）：

```bash
recon lint .recon/04-skeleton.md
recon check-deps .recon/04-skeleton.md
```

3. **【唯一人工检查点】**：向用户呈交 `.recon/04-skeleton.md` 的「人审视图」，逐项裁决：
   - 阶段 1 的临时路线推荐；
   - 同槽平手与反推分歧构成的**决策点清单**；
   - 无机器验证的**红旗清单**与人工抽查排期；
   - 入选技能所需外部工具清单及阶段 3 产出的 `generated` 技能是否确认入库（确认后调用 `recon ingest dir ... --trust-status generated` 或 `recon trust`）。

### 阶段 5 · 论文/开源精准填充与锚点回填
1. 对检查点通过的 `.recon/04-skeleton.md` 运行批抓取：

```bash
recon fill fetch .recon/04-skeleton.md --workspace .
```

2. 派发 `paper-filler` 子代理（规范见 `agents/paper-filler.md`），按步骤 `待填` 需求拉取高引有码工作（`recon fill paper` 用 `mineru` 解析 PDF 至 `.recon/papers/`；`recon fill repo` 浅克隆至 `.recon/repos/` 并用 `ast-grep` 提取核心实现），产出：
   - `.recon/05-references.md`
   - **回填 `.recon/04-skeleton.md` 中预留的复现型锚点具体数值**
   - 在**目标项目工作目录的 `tests/` 下**生成对应测试文件与验证桩
3. 再次运行严格锚点校验：

```bash
recon lint .recon/04-skeleton.md --strict-anchors
```

### 阶段 6 · 可验证执行、三层验收与差异报告
1. 执行前再次确认 `recon check-deps .recon/04-skeleton.md` 全绿。
2. 按 `recon lint` 输出的 DAG 拓扑序逐段推进：
   - 复杂实现段优先调用 `fn-ladder`（divide → implement → review）；
   - 重计算/GPU 复现路由至 `remote-compute`；
   - 首次试跑未充分审计的第三方仓库代码时，强制套 `bwrap-run` 沙箱。
3. **三层门禁**：每步执行完立刻运行 `验证.命令`（步内失败最多修复 3 次，超限立刻暂停上抛，禁止静默跳过）→ 宏观段末集成验证 → 端到端项目级终验。
4. 全程偏离实时记录，终验后输出 `.recon/06-deviation-report.md`（预期 vs 实测指标 + 逐项偏差归因），并用 `recon feedback` / `recon trust` 将验证成果反哺通用 Skill 库。
