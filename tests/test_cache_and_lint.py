"""Tests for CacheDB, Stage 4 skeleton lint invariants, and dependency checks."""

from __future__ import annotations

from pathlib import Path

from recon.config import ReconConfig
from recon.db.cache import CacheDB
from recon.db.library import SkillLibrary
from recon.validate.lint import check_skeleton_deps, lint_skeleton


def test_cache_db_roundtrip(tmp_path: Path) -> None:
    cache = CacheDB(tmp_path)
    assert cache.get("openalex", "gaussian splatting") is None
    raw_file = cache.put("openalex", "gaussian splatting", 200, [{"title": "3DGS"}])
    assert raw_file.exists()
    loaded = cache.get("openalex", "gaussian splatting")
    assert loaded == [{"title": "3DGS"}]


def test_lint_skeleton_valid_and_strict_anchors(tmp_path: Path) -> None:
    skel = tmp_path / "04-skeleton.md"
    skel.write_text(
        """# 04-skeleton

## 执行视图

```yaml
step_id: S01
阶段: 数据准备
分面: data
意图: 准备数据集
输入: [外部:数据集X]
输出: data/processed
挂载:
  技能: [demo-skill]
  待填: []
验证:
  类型: 规约型
  命令: pytest tests/test_s01.py
  锚点: "schema valid"
出处: [repoA/README.md]
```

```yaml
step_id: S02
阶段: 评估验证
分面: eval
意图: 复现指标
输入: [S01的输出]
输出: metrics.json
挂载:
  技能: []
  待填: [参数:lr]
验证:
  类型: 复现型
  命令: python eval.py
  锚点: "对应论文表2（待阶段5回填）"
出处: [paper#exp]
```
""",
        encoding="utf-8",
    )

    res_stage4 = lint_skeleton(skel, strict_anchors=False)
    assert res_stage4.ok
    assert res_stage4.topo_order == ["S01", "S02"]

    res_stage5 = lint_skeleton(skel, strict_anchors=True)
    assert not res_stage5.ok
    assert any("S02" in e for e in res_stage5.errors)


def test_lint_skeleton_catches_all_four_failures(tmp_path: Path) -> None:
    skel = tmp_path / "bad.md"
    skel.write_text(
        """```yaml
step_id: S01
输入: [S02的输出, unknown_input]
输出: out1
验证:
  类型: 规约型
  命令: ""
```

```yaml
step_id: S02
输入: [S01的输出]
输出: out2
出处: [doc]
验证:
  类型: 规约型
  命令: echo ok
```
""",
        encoding="utf-8",
    )
    res = lint_skeleton(skel)
    assert not res.ok
    joined = "\n".join(res.errors)
    assert "Missing provenance" in joined
    assert "Executable `验证.命令` is required" in joined
    assert "Dangling input `unknown_input`" in joined
    assert "Cycle detected" in joined


def test_check_skeleton_deps_detects_missing_tool(tmp_path: Path) -> None:
    lib = SkillLibrary(tmp_path / "lib", embed_dim=4)
    lib.upsert_skill(
        name="custom-tool-skill",
        description="needs imaginary binary",
        raw_skill_md="---\nname: custom-tool-skill\n---\n## Run",
        body_md="## Run",
        source_type="github",
        source_uri="https://example.com",
        dependencies={"bins": ["nonexistent_binary_xyz_123"], "env": ["NONEXISTENT_ENV_XYZ"]},
    )
    skel = tmp_path / "04-skeleton.md"
    skel.write_text(
        """```yaml
step_id: S01
输入: [外部:raw]
挂载:
  技能: [custom-tool-skill]
验证:
  类型: 规约型
  命令: echo ok
出处: [skill:custom-tool-skill]
```
""",
        encoding="utf-8",
    )
    cfg = ReconConfig(
        config_path=tmp_path / "config.toml",
        skill_library_dir=tmp_path / "lib",
        plugin_scan_dirs=[],
    )
    deps = check_skeleton_deps(skel, lib, cfg)
    assert not deps["ok"]
    assert "nonexistent_binary_xyz_123" in deps["missing_bins"]
    assert "NONEXISTENT_ENV_XYZ" in deps["missing_envs"]
