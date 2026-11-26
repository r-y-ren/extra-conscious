# 子代理规范：Survey 侦察（阶段 1）

## 职责边界
将用户的日常语言需求转化为有独立出处支撑的**双语术语表（含显式 `facet` 分面）**与**技术路线图**，把 API 原始 JSON 与大量摘要噪声留在子代理上下文内，只向主线程返回 `.recon/01-terms.md` 与 `.recon/02-survey.md`。

## 执行步骤
1. **冷启动扩词**：拆解需求中的名词与动作，结合先验生成 2–3 个英文学术候选词。
2. **四源并发抓取**（必须调用 `recon fetch`，自动进 `.recon/cache.duckdb`）：
   - `recon fetch wiki --query "<词>" --workspace .`（口语实体消歧）
   - `recon fetch openalex --query "<词>" --workspace .`（获取 Domain → Field → Topic 层级）
   - `recon fetch s2 --query "<词>" --workspace .`（按 `influentialCitationCount` 排序）
   - `recon fetch github --query "awesome <词>" --workspace .`（工程生态与话题标签）
   - 若命中静态官网或 awesome-list，可用 `recon fetch web --query "<URL>"`（基于 `trafilatura`）抓正文。
3. **迭代查询扩展**：从已抓摘要、Introduction 与 Topic 抽取高频技术名词，补充新词再跑一轮 `recon fetch`，直到连续一轮无新术语加入（最多 3 轮；若全部失败则带已试词汇退出并请求人工澄清）。
4. **建 `.recon/01-terms.md`**：
   - 表格必须包含以下列：`| 分面 (facet) | 英文术语 | 中文对照 | 所属子领域 | 独立来源 | 状态 |`
   - **硬规则**：至少在 **2 个独立来源**（如 OpenAlex + GitHub，或 S2 + Wikipedia）出现过的词才标 `已确认`；单源词标 `待定`（阶段 2 自动跳过）。
5. **建 `.recon/02-survey.md`**：
   - 提炼 2–3 条主流技术路线，每条必须标注：核心思想、代表工作（arXiv id / 仓库 URL）、优劣权衡、与需求匹配点。
   - 末尾给出 **临时路线推荐 + 理由**，并注明“待唯一检查点最终确认”。

## 禁止事项
- 禁止编造未经 `recon fetch` 返回的论文标题、arXiv ID 或仓库链接。
- 禁止省略 `分面 (facet)` 列（阶段 2 纯脚本依赖该列分组）。
