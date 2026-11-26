"""Stage 3 / Stage 5 helpers for paper download + mineru parsing and repo inspection."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import yaml

from recon.db.cache import CacheDB
from recon.fetch.survey import fetch_arxiv, fetch_github, fetch_hf_papers, fetch_semantic_scholar


def download_and_parse_paper(
    pdf_url: str,
    paper_id: str,
    workspace_dir: Path | str,
) -> dict[str, Any]:
    """Download a paper PDF into .recon/papers/ and convert via mineru if available."""
    papers_dir = Path(workspace_dir).resolve() / ".recon" / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in paper_id)
    pdf_path = papers_dir / f"{safe_id}.pdf"

    if not pdf_path.exists():
        with httpx.stream("GET", pdf_url, follow_redirects=True, timeout=120) as resp:
            resp.raise_for_status()
            with pdf_path.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)

    helper = shutil.which("mineru-to-markdown")
    mineru_bin = shutil.which("mineru")
    md_path = papers_dir / f"{safe_id}.md"

    if helper:
        proc = subprocess.run([helper, str(pdf_path)], capture_output=True, text=True, check=False)
        return {
            "pdf_path": str(pdf_path),
            "parsed": proc.returncode == 0,
            "tool": "mineru-to-markdown",
            "output_dir": str(papers_dir),
            "stderr": proc.stderr.strip(),
        }
    if mineru_bin:
        out_dir = papers_dir / safe_id
        out_dir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [mineru_bin, "-p", str(pdf_path), "-o", str(out_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "pdf_path": str(pdf_path),
            "parsed": proc.returncode == 0,
            "tool": "mineru",
            "output_dir": str(out_dir),
            "stderr": proc.stderr.strip(),
        }
    return {
        "pdf_path": str(pdf_path),
        "parsed": False,
        "tool": "none",
        "expected_md": str(md_path),
        "stderr": "mineru not found in PATH",
    }


def shallow_clone_repo(repo_url: str, workspace_dir: Path | str) -> dict[str, Any]:
    """Shallow-clone a reference OSS repository into .recon/repos/ and summarize key files."""
    repos_dir = Path(workspace_dir).resolve() / ".recon" / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)
    repo_name = repo_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    target = repos_dir / repo_name

    if not target.exists():
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(target)],
            check=True,
            capture_output=True,
            text=True,
        )

    interesting: list[str] = []
    for candidate in ("README.md", "pyproject.toml", "setup.py", "Makefile", "Dockerfile", "environment.yml"):
        if (target / candidate).exists():
            interesting.append(candidate)
    for folder in (".github/workflows", "tests", "src"):
        if (target / folder).exists():
            interesting.append(f"{folder}/")

    return {"repo_dir": str(target), "key_entries": interesting}


def collect_fill_targets(skeleton_path: Path) -> list[dict[str, Any]]:
    """Extract steps with non-empty `挂载.待填` targets from 04-skeleton.md."""
    text = skeleton_path.read_text(encoding="utf-8")
    targets: list[dict[str, Any]] = []
    for block in text.split("```yaml"):
        if "```" not in block:
            continue
        yaml_part = block.split("```", 1)[0]
        try:
            card = yaml.safe_load(yaml_part)
        except yaml.YAMLError:
            continue
        if not isinstance(card, dict) or "step_id" not in card:
            continue
        mount = card.get("挂载") or {}
        to_fill = mount.get("待填") or []
        if to_fill:
            targets.append(
                {
                    "step_id": card["step_id"],
                    "intent": card.get("意图", ""),
                    "facet": card.get("分面", ""),
                    "to_fill": to_fill,
                }
            )
    return targets


def fetch_for_skeleton_fills(
    skeleton_path: Path,
    workspace_dir: Path | str,
    *,
    limit_per_source: int = 5,
    s2_api_key_env: str = "S2_API_KEY",
    github_token_env: str = "GITHUB_TOKEN",
) -> list[dict[str, Any]]:
    """Run Stage 5 cached retrieval across S2, arXiv, HF Papers, and GitHub per step."""
    cache = CacheDB(workspace_dir)
    targets = collect_fill_targets(skeleton_path)
    results: list[dict[str, Any]] = []
    for item in targets:
        query = f"{item['facet']} {item['intent']}".strip()
        step_bundle: dict[str, Any] = {**item, "query": query, "sources": {}}
        for name, fn in (
            ("s2", lambda q=query: fetch_semantic_scholar(q, cache, limit_per_source, s2_api_key_env)),
            ("arxiv", lambda q=query: fetch_arxiv(q, cache, limit_per_source)),
            ("hf", lambda q=query: fetch_hf_papers(q, cache, limit_per_source)),
            ("github", lambda q=query: fetch_github(q, cache, limit_per_source, github_token_env)),
        ):
            try:
                step_bundle["sources"][name] = fn()
            except Exception as exc:  # noqa: BLE001 - report per-source error without aborting other sources
                step_bundle["sources"][name] = {"error": str(exc)}
        results.append(step_bundle)
    return results
