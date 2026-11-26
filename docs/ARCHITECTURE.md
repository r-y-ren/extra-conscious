# Extra-Conscious 架构规范

> 通过 **Skill 检索库**、**结构化学术检索** 与 **可验证骨架闭环**，使 AI Agent 可靠完成处于用户认知盲区之外的复杂工程与科研复现任务。

---

## 1. 核心设计哲学

1. **为什么认知外任务容易失败**：差别不在模型智商，而在**谁掌握验收权**。认知内任务由人逐段拦截误差；认知外任务中，模型只能依赖过时训练先验且毫无中间验收信号，误差会指数级复利。
2. **三线分离原则**：
   - **相关性（Retrieval）**：由确定性脚本计算纯文本/向量分数，**本地与社区技能完全同权，不加来源偏置**。
   - **适配度（Assembly）**：由子代理精读少数候选全文，按“领域专用 > 通用、有维护 > 陈旧”装配到骨架对应槽位。
   - **信任治理（Governance）**：出处与可信状态（`reference` / `adopted` / `generated`）仅作为元数据，由人在唯一检查点拍板。
3. **严格的三层目录边界**：
   - **通用技能与工具资产**（插件目录或用户指定目录）：`SKILL.md`、`agents/*.md`、`scripts/`、`~/.local/bin/recon`、`skill-library/`。**不含任何任务级论文、业务代码或测试文件。**
   - **目标项目工作目录**（每次运行工作流开发具体项目时所在目录）：项目源码、阶段 4–5 生成的验证 `tests/`、以及 `.recon/`（`cache.duckdb`、`papers/`、`repos/`、`01-terms.md`～`06-deviation-report.md`）。
   - **本研发仓库**（`extra-conscious/`）：开发 `recon` CLI 与工作流规范的源码仓，根目录 `tests/` 仅测试 `recon` 自身。

---

## 2. 六阶段端到端工作流

### 阶段 1 · Survey 侦察（`recon fetch` + `survey-recon` 子代理）
- **输入**：一句日常语言需求（无领域术语、无流程知识）。
- **机制**：
  1. 模型先验冷启动生成 2–3 个英文候选学术词；
  2. `recon fetch` 四源并发检索：**Wikipedia**（口语实体消歧）、**OpenAlex**（Domain→Field→Topic 分层归属）、**Semantic Scholar**（`influentialCitationCount` 加权）、**GitHub**（topics 与 `awesome-*`）；网页正文通过 `trafilatura` 抽取，原始响应按 `(provider, query_hash, date)` 写入 `.recon/cache.duckdb`；
  3. 从返回摘要/引言提取高频术语，迭代扩展重搜直到收敛；
  4. **跨源门槛**：术语需在 **≥2 个独立来源** 出现方可正式收录（单源标 `待定`）。
- **退出条件**：需求核心成分全部映射到术语条目；技术流派 ≥2 条且有出处；连续一轮扩展无新增术语。
- **产物**：
  - `.recon/01-terms.md`：显式包含 `facet`（分面）列、英文术语、中文对照、子领域、独立来源列表。
  - `.recon/02-survey.md`：领域概览、2–3 条技术路线权衡图、**临时路线推荐 + 理由**（带入检查点）。

### 阶段 2 · Skill 检索（纯脚本 `recon search`，零代理）
- **输入**：`.recon/01-terms.md`（按 `facet` 分面分组）+ 通用 `library.duckdb`。
- **机制**：
  1. **机械构造查询**：按 `facet` 提取英文术语为主、中文为辅，拼接领域限定词。
  2. **混合索引检索**：DuckDB `fts`（BM25）与 `vss`（`bge-m3` 余弦 HNSW）并行查询 → **RRF 融合** → 单一相关性排名（无来源加权）。
  3. **三档路由**：
     - `high`（高置信候选池）
     - `medium`（终审池，每分面 top ~20）
     - `low`（负结果，记录领域缺口）
- **产物**：`.recon/03-candidates.md`（分面 × 档位命中清单）。

### 阶段 3 · 按分面分流：综合 vs 多源反推（`skill-synth` 子代理）
现实任务通常是**混合态**（工程纪律分面有命中，核心领域分面全空），因此**按 `facet` 独立分流、并行处理**：

- **分流判据**：某分面存在 `high` 置信命中 **且** 命中技能粒度为 `lifecycle` 或 `process`（流程级，非单个 CLI 工具封装）→ **综合路径**；否则 → **反推路径**。
- **综合路径**：
  1. 精读终审池全文，将技能归为三类：**领域流程** / **工程纪律** / **工具能力**；
  2. 角色分派至骨架槽位；同槽冲突按 **领域专用 > 通用 > 有维护 > 陈旧** 裁决，平手进检查点决策清单；
  3. 发现的误召回/漏召回通过 `recon feedback` 写回 `library.duckdb`。
- **反推路径**：
  1. **异构选源（默认上限 3，复杂分面可扩至 4）**：首选 `1 篇代表论文 + 官方实现仓 + 1 个独立复现仓`；
  2. 论文经 `mineru` 转 Markdown，仓库抽取 `README`、目录树、`Makefile/CI`、`tests`、`Issues/PR`（工程暗知识）、`Dockerfile/environment.yml`；
  3. **六步融合**：独立抽取各源步骤与 I/O → 以论文 Method 粒度对齐（仓库为子步骤）→ 交集标必选、分歧进决策点 → 消融实验标承重权重 → 挂四分类验证 → 生成带双语 `frontmatter` 触发词的新 `SKILL.md` 草案。
- **入库闭环**：新生成的技能经唯一人工检查点确认后，以 `trust_status = generated` 自动写入 `library.duckdb`，实现知识复利。
- **产物**：`.recon/03-skills.md` + 待确认的 `generated` 技能草案。

### 阶段 4 · 全局骨架合成、验证设计与唯一人工检查点（`skeleton-builder` 子代理 + `recon lint`）
- **四步合成**：
  1. **宏观段装配**：命中 `fn-ladder` 等生命周期技能时直接复用其宏观段，否则默认五段：`环境构建 → 数据准备 → 核心实现 → 评估验证 → 交付归档`。
  2. **DAG 拓扑嵌入**：按各分面步骤的 `输入 / 输出` 匹配排序（`recon` 给候选边，子代理定最终顺序）。
  3. **跨分面去重与外部依赖聚合**：合并同意图步骤；聚合所有入选技能的 `dependencies_json` 至「环境构建」段。
  4. **待填标注**：为缺失实现细节的步骤标注 `待填: [方法/代码/参数/数据]`。
- **验证方式与两段式锚点**：
  - 按 ground truth 可得性指派四类：**复现型** / **规约型** / **回归型** / **人工抽查型 + 红旗**。
  - **两段式锚点**：阶段 4 确定验证类型、命令模板与锚点出处规格（如“对应论文表 2 指标 ±2%”）；具体数值留待阶段 5 锁定论文后回填。
- **产物形态（单文件双视图）**：`.recon/04-skeleton.md` 上半部分为**人审视图**（路线推荐确认、外部工具依赖总览、决策点清单、红旗清单、人工抽查排期、DAG 总图），下半部分为**执行视图**（标准 YAML 步骤卡片）。
- **自动闸门 `recon lint`**：强制检查四项——① 无出处禁止写入 ② 无验证禁止通过 ③ 无悬空输入 ④ DAG 无环。通过后才进入**唯一人工检查点**。

### 阶段 5 · 论文/开源索引、精准填充与锚点回填（`recon fill-fetch` + `paper-filler` 子代理）
采用 **“结构化学术 API 引文去偏 + `.recon/cache.duckdb` 缓存 + 按需深度解析”** 策略，避免维护膨胀的全局论文向量库：

1. **按步骤构造填充查询**：针对 `04-skeleton.md` 中每条带 `待填` 标记的步骤检索：
   - 学术源：OpenAlex + Semantic Scholar（`influentialCitationCount` 加权，前沿内容优先近 2–3 年）+ arXiv API + Hugging Face Papers。
   - 代码源：GitHub（star、近 6 个月提交、CI 状态、license、技术路线一致性）。
   - 选材优先级：`有代码实现 > 纯论文`、`活跃维护 > 归档`、`同路线 > 跨路线`。
2. **按需深度解析**：
   - 核心论文 PDF 经 `mineru` 转 Markdown 落盘 `.recon/papers/`；
   - 参考仓库浅克隆至 `.recon/repos/`，使用 `ast-grep` 与结构扫描提取关键模块、超参与数据逻辑。
3. **回填与产物**：
   - 产出 `.recon/05-references.md`；
   - **回填 `.recon/04-skeleton.md` 中的两段式锚点具体数值**（如基准指标、消融差值）；
   - 在**目标项目工作目录的 `tests/` 下**生成可执行验证脚本与测试桩（不污染技能目录）。

### 阶段 6 · 可验证执行、三层验收与差异报告
1. **执行与工具路由**：
   - 先运行 `recon check-deps .recon/04-skeleton.md` 确认目标运行环境满足所有入选技能的外挂工具依赖；
   - 复杂实现段可挂接 `fn-ladder`；GPU 重任务路由至 `remote-compute`；未审计第三方代码的首次试跑强制套 `bwrap-run` 沙箱。
2. **三层验证门禁**：
   - **步级**：每步完成即跑 `验证.命令`；失败步内诊断修复最多 3 次，超限立刻暂停并上抛给用户。
   - **段级**：每完成一个宏观段跑集成验证；到排期的人工抽查点暂停确认。
   - **项目级**：端到端全量验收。
3. **差异报告与复利反馈**：
   - 全程偏离实时记录，终验后输出 `.recon/06-deviation-report.md`（预期 vs 实测指标 + 逐项偏差归因）。
   - 将有效检索关联与 `generated` 技能验证结果回写 `library.duckdb`。

---

## 3. DuckDB Schema 设计

### 通用技能库 `library.duckdb`
- `skills(content_hash PK, name, description, source_type, source_uri, trust_status, granularity, license, stars, pushed_at, dependencies_json, body_md, created_at, updated_at)`
- `skill_chunks(chunk_id PK, content_hash, section_title, chunk_order, chunk_text, embedding FLOAT[1024])`
- `retrieval_feedback(feedback_id PK, query_text, facet, content_hash, label, note, created_at)`

### 项目缓存库 `.recon/cache.duckdb`
- `api_cache(cache_key PK, provider, query_text, query_date, status_code, payload_json, created_at)`
