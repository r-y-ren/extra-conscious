# 子代理规范：论文/开源精准填充与锚点回填（阶段 5）

## 职责边界
在唯一人工检查点通过后，针对 `.recon/04-skeleton.md` 中所有含 `挂载.待填` 的步骤及预留的两段式验证锚点，结合 `recon fill` 检索与本地深度解析结果，产出 `.recon/05-references.md`、回填 `04-skeleton.md` 锚点数值，并在**目标项目目录的 `tests/`** 下生成验证测试桩。

## 执行流程
1. **消费缓存检索结果**：先运行 `recon fill fetch .recon/04-skeleton.md --workspace .`（聚合 Semantic Scholar、arXiv、HF Papers、GitHub）。
2. **选材优先级**：
   - `有可运行官方/高星复现代码 > 纯论文`；
   - `近 6 个月活跃维护 > 弃坑仓`；
   - `符合阶段 1 已选定技术路线 > 跨路线`。
3. **按需深度解析（只下载真正入选的条目）**：
   - 论文下载并经 `mineru` 转 Markdown：`recon fill paper --pdf-url "<URL>" --paper-id "<ID>" --workspace .`，重点阅读 `Method`、`Implementation Details`、`Experiments` 表格与 `Appendix`；
   - 参考代码浅克隆：`recon fill repo --repo-url "<URL>" --workspace .`，用 `ast-grep`（来自 `my-plugin`）精确定位算法模块、默认超参与单元测试逻辑。
4. **回填两段式锚点与产出测试文件**：
   - 更新 `.recon/04-skeleton.md` 中所有 `待阶段5回填` 的 `验证.锚点`，写入真实论文指标数值与硬件容差（如 `"CIFAR-10 Top-1 = 94.2% ± 0.5% (论文Table 2)"`）；
   - 在**目标项目目录 `tests/`**（而非技能目录）编写可执行测试/验证脚本；
   - 输出 `.recon/05-references.md` 完整引用映射表：`step_id → 论文/章节 → 仓库/文件路径 → 借用方法/代码/超参 → 回填锚点值`。
5. **闸门校验**：完成后执行 `recon lint .recon/04-skeleton.md --strict-anchors`，确认全部复现型锚点已回填且无语法/依赖破坏。
