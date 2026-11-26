# Extra-Conscious 显式依赖与新设备自部署清单

本文件面向**新设备上的 Agent 与开发者**。任何新环境首次启用 `extra-conscious` 工作流时，Agent 必须先运行 `recon doctor` 检查以下全部依赖；存在缺失项时，按本清单自动完成安装与配置后再启动阶段 1。

---

## 1. 宿主插件 / 技能依赖

本工作流不重复造轮子，以下插件中的技能在六阶段中被直接编排调用：

| 插件 | 依赖级别 | 使用到的技能 / 能力 | 缺失时影响 |
| :--- | :--- | :--- | :--- |
| `my-plugin` | **核心推荐** | `mineru`（PDF→MD）、`trafilatura`（网页正文抽取）、`duckdb`（大表查询）、`ast-grep`（代码结构抽取）、`bwrap-run`（不可信仓沙箱）、`remote-compute`（远端 GPU 嵌入/训练） | 论文 PDF 解析、沙箱试跑、远端 GPU 加速将降级或受限 |
| `fn-ladder` | **可选增强** | `fn-grill` / `fn-divide` / `fn-implement` / `fn-review` | 阶段 6 回退为工作流内置的步级验证执行规范 |

> 插件目录兼容：支持通过 `~/.config/extra-conscious/config.toml` 配置多个插件扫描路径（默认自动探测 `~/.gemini/config/plugins/` 与 `~/.zcode/cli/plugins/cache/`）。

---

## 2. 系统与 CLI 二进制依赖

| 工具 | 级别 | 用途 | 新设备安装 / 自举方式 |
| :--- | :--- | :--- | :--- |
| `python3` (`>=3.11`) | **必装** | 运行 `recon` CLI | 系统包管理器或 `uv python install 3.12` |
| `uv` | **必装** | 管理独立虚拟环境与安装 `recon` 到 `~/.local/bin` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `git` | **必装** | 克隆社区技能仓与阶段 3/5 参考仓库浅克隆 | 系统包管理器 |
| `gh` | **必装** | GitHub API 搜索（`awesome-*`、topics、代码仓质量筛选） | 系统包管理器 + `gh auth login` |
| `duckdb` | **必装** | 技能混合检索库与项目 API 缓存（Python 包内嵌引擎；CLI 可选） | `scripts/bootstrap.sh` / `my-plugin` |
| `mineru` | **推荐** | 阶段 3 / 阶段 5 论文 PDF 高精度转 Markdown | 由 `my-plugin` 安装（国内模型：`mineru-models-download -s modelscope`） |
| `trafilatura` | **推荐** | 阶段 1 静态页面与 Wikipedia/文档降噪抽取 | 由 `my-plugin` 安装 |
| `ast-grep` | **推荐** | 阶段 5 开源仓库核心模块与函数结构抽取 | 由 `my-plugin` 安装 |
| `bwrap` | **推荐** | 阶段 6 首次运行第三方参考代码时的断网/只读沙箱隔离 | 发行版包管理器（`apt install bubblewrap`） |

---

## 3. DuckDB 扩展与向量嵌入依赖

1. **DuckDB 扩展**：需要 `fts`（BM25 全文检索）与 `vss`（HNSW 余弦向量检索）。
   - 安装命令：`INSTALL fts; INSTALL vss;`（`recon init` / `scripts/bootstrap.sh` 会自动执行）。
   - 离线注意：首次安装扩展需联网下载扩展二进制到 `~/.duckdb/extensions/`，之后离线可复用。
2. **嵌入模型（阶段 2 语义检索）**：默认推荐 `BAAI/bge-m3`（1024 维，中英跨语言稳健冗余）。
   - 支持三种后端（在 `config.toml` 的 `[embedding]` 中配置）：
     - `local`：使用 `fastembed` / `sentence-transformers`（支持 `HF_ENDPOINT=https://hf-mirror.com` 或 ModelScope 本地路径）。
     - `remote`：通过 `remote-compute`（如 `ssh wsl`）调用远端 GPU（如 4070）批量生成向量，全量千级技能重建仅需数分钟。
     - `openai_compat`：兼容任意本地/远端 `/v1/embeddings` 服务（如 Ollama / vLLM / API）。
   - 降级兜底：若新设备暂未配置向量模型，阶段 2 自动允许仅以 `fts`（BM25）先行运行，并在 `recon doctor` 中提示 `WARN`。

---

## 4. 环境变量与配置文件

所有机器级路径与偏好统一存放在 **`~/.config/extra-conscious/config.toml`**（禁止硬编码在 `SKILL.md` 中）：

```toml
# 示例模板，由 `recon init` 或 `scripts/bootstrap.sh` 自动生成
[paths]
# 跨项目通用 Skill 检索库目录（可修改为任意用户指定目录，亦可用环境变量 RECON_LIBRARY_DIR 覆盖）
skill_library_dir = "~/.local/share/extra-conscious/skill-library"
# 本地插件扫描根目录（自动过滤存在者）
plugin_scan_dirs = [
  "~/.gemini/config/plugins",
  "~/.zcode/cli/plugins/cache",
]

[embedding]
backend = "auto" # auto | sentence_transformers | openai_compat | remote | disabled
model = "BAAI/bge-m3"
dim = 1024
api_base = ""
api_key_env = "OPENAI_API_KEY"
remote_host = "wsl" # 配合 my-plugin:remote-compute

[api]
# 可选：Semantic Scholar API Key 环境变量名（无 key 亦可低频调用）
s2_api_key_env = "S2_API_KEY"
# 可选：GitHub Token（默认优先复用 `gh auth token`）
github_token_env = "GITHUB_TOKEN"
```

可选环境变量覆盖：
- `EXTRA_CONSCIOUS_CONFIG`：指定自定义 `config.toml` 路径。
- `RECON_LIBRARY_DIR`：直接覆盖通用 Skill 库存放目录。
- `HF_ENDPOINT`：国内网络拉取 `bge-m3` 时设为 `https://hf-mirror.com`。

---

## 5. 新设备一键部署与 Agent 自检 SOP

### 一键初始化
```bash
git clone <extra-conscious-repo-url>
cd extra-conscious
./scripts/bootstrap.sh
```

`scripts/bootstrap.sh` 幂等完成：
1. 通过 `uv` 创建/更新独立工具环境并将 `recon` 链接至 `~/.local/bin/recon`；
2. 生成 `~/.config/extra-conscious/config.toml`（不覆盖已有配置）；
3. 初始化通用 Skill 库目录与 `library.duckdb` Schema，尝试安装 DuckDB `fts` / `vss` 扩展；
4. 运行 `recon doctor` 输出完整健康报告。

### Agent 冷启动自检协议
当 Agent 在一台未曾初始化的新设备被唤醒并进入本工作流时：
1. 运行 `recon doctor --json`；
2. 若返回 `FAIL`（如缺少 `recon`、DuckDB 扩展未装、配置缺失），优先执行 `scripts/bootstrap.sh`；
3. 若返回 `MISSING_PLUGIN` 或 `WARN`（如缺少 `mineru`、`bwrap` 或 `gh` 未登录），读取本文件第 1–3 节提示用户或代为安装系统/插件依赖；
4. 确认关键项全部就绪后，再执行 `recon ingest local` 收录本机已有技能并启动阶段 1。

---

## 6. 收录技能的外部工具依赖追踪

社区或本地收录的技能往往依赖特定外部工具（如 `playwright`、`docker`、`ffmpeg` 或某 MCP Server）：
- `recon ingest` 解析每个 `SKILL.md` 时，自动提取其声明的依赖（frontmatter 中的 `requires` / `bins` / `env` / `mcp` 及正文工具声明），写入 `library.duckdb` 的 `skills.dependencies_json`。
- 阶段 4 合成骨架时，所有入选技能的外部依赖自动聚合到 `04-skeleton.md` 的「环境构建」前置段。
- 阶段 6 启动前运行 `recon check-deps .recon/04-skeleton.md`，预先检查目标运行环境是否满足全部入选技能的工具依赖，防止执行到一半才报错中断。
