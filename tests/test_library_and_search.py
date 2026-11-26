"""Tests for SkillLibrary, hybrid RRF search, dependency extraction, and Stage 2."""

from __future__ import annotations

from pathlib import Path

from recon.db.library import SkillLibrary
from recon.ingest.scanner import ingest_directory, parse_skill_file
from recon.search.stage2 import run_stage2_search


def test_parse_skill_dependencies_and_granularity(tmp_path: Path) -> None:
    skill_dir = tmp_path / "gaussian-splat"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: gaussian-splat
description: Train 3D Gaussian Splatting models
requires:
  bins: [ffmpeg]
  env: [CUDA_VISIBLE_DEVICES]
  plugins: [my-plugin]
---

## Setup
Prepare dataset.

```bash
mineru -p paper.pdf -o out/
```

## Training
Run training loop.

## Evaluation
Compute PSNR and SSIM.
""",
        encoding="utf-8",
    )
    parsed = parse_skill_file(skill_md)
    assert parsed.name == "gaussian-splat"
    assert parsed.granularity == "process"
    assert parsed.dependencies["bins"] == ["ffmpeg"]
    assert "mineru" in parsed.dependencies["inferred_bins"]
    assert parsed.dependencies["env"] == ["CUDA_VISIBLE_DEVICES"]
    assert parsed.dependencies["plugins"] == ["my-plugin"]


def test_equal_weight_hybrid_search_and_stage2(tmp_path: Path) -> None:
    lib = SkillLibrary(tmp_path / "lib", embed_dim=4)

    # Ingest two skills with identical relevance from different sources (plugin vs github)
    body = "## Pipeline\nNeural radiance field training and camera pose estimation with COLMAP."
    h1, new1 = lib.upsert_skill(
        name="local-nerf",
        description="Neural radiance field training",
        raw_skill_md=f"---\nname: local-nerf\n---\n{body}",
        body_md=body,
        source_type="plugin",
        source_uri="local://local-nerf",
        trust_status="adopted",
        granularity="process",
    )
    h2, new2 = lib.upsert_skill(
        name="community-nerf",
        description="Neural radiance field training",
        raw_skill_md=f"---\nname: community-nerf\n---\n{body}",
        body_md=body,
        source_type="github",
        source_uri="https://github.com/example/community-nerf",
        trust_status="reference",
        granularity="process",
    )
    assert new1 and new2 and h1 != h2

    # Assign identical unit vectors to chunks so RRF score parity is verified
    pending = lib.unembedded_chunks()
    lib.write_embeddings([(cid, [1.0, 0.0, 0.0, 0.0]) for cid, _ in pending])

    hits = lib.hybrid_search("neural radiance field COLMAP", query_embedding=[1.0, 0.0, 0.0, 0.0], top_k=10)
    assert len(hits) == 2
    assert abs(hits[0].rrf_score - hits[1].rrf_score) < 1e-6

    # Stage 2 markdown integration
    terms_path = tmp_path / "01-terms.md"
    terms_path.write_text(
        """# 01-terms
| 分面 (facet) | 英文术语 | 中文对照 | 所属子领域 | 独立来源 | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| reconstruction | neural radiance field | 神经辐射场 | 3D Vision | OpenAlex, GitHub | 已确认 |
| reconstruction | hallucinated term | 幻觉词 | 3D Vision | single | 待定 |
""",
        encoding="utf-8",
    )
    out_path = tmp_path / "03-candidates.md"
    res = run_stage2_search(library=lib, terms_path=terms_path, out_path=out_path)
    assert res["facets"] == 1
    rendered = out_path.read_text(encoding="utf-8")
    assert "reconstruction" in rendered
    assert "local-nerf" in rendered
    assert "community-nerf" in rendered
    assert "hallucinated term" not in rendered


def test_ingest_directory_dedup_and_feedback(tmp_path: Path) -> None:
    skills_src = tmp_path / "src_skills" / "demo"
    skills_src.mkdir(parents=True)
    (skills_src / "SKILL.md").write_text("---\nname: demo\ndescription: demo tool\n---\n## Run\nhello", encoding="utf-8")

    lib = SkillLibrary(tmp_path / "lib", embed_dim=4)
    first = ingest_directory(lib, tmp_path / "src_skills", source_type="github")
    second = ingest_directory(lib, tmp_path / "src_skills", source_type="github")
    assert first["added"] == 1
    assert second["added"] == 0
    assert second["unchanged"] == 1

    h = next(iter((tmp_path / "lib" / "skills").iterdir())).name
    assert lib.update_trust_status(h, "generated")
    fid = lib.add_feedback(query_text="demo", facet="core", content_hash=h, label="good", note="exact match")
    assert len(fid) == 16
    assert lib.stats()["feedback_count"] == 1
