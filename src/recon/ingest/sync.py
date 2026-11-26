"""Incremental community skill repository synchronization."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx

from recon.db.library import SkillLibrary
from recon.ingest.scanner import ingest_directory

DEFAULT_COMMUNITY_REPOS = [
    "anthropics/skills",
    "obra/superpowers",
]


def fetch_repo_metadata(repo_slug: str, github_token: str = "") -> dict[str, Any]:
    """Query GitHub repo metadata (pushed_at, stargazers_count, license) via gh or REST."""
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{repo_slug}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass

    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    resp = httpx.get(f"https://api.github.com/repos/{repo_slug}", headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def sync_github_repo(
    library: SkillLibrary,
    repo_slug: str,
    *,
    github_token: str = "",
) -> dict[str, Any]:
    """Clone or fast-forward a GitHub skill repository and ingest SKILL.md files."""
    sources_dir = library.library_dir / ".sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    safe_name = repo_slug.replace("/", "__")
    repo_dir = sources_dir / safe_name
    state_file = sources_dir / f"{safe_name}.meta.json"

    meta = fetch_repo_metadata(repo_slug, github_token=github_token)
    pushed_at = str(meta.get("pushed_at", ""))
    stars = int(meta.get("stargazers_count", 0) or 0)

    if state_file.exists() and repo_dir.exists():
        prev = json.loads(state_file.read_text(encoding="utf-8"))
        if prev.get("pushed_at") == pushed_at and pushed_at:
            return {"repo": repo_slug, "skipped": True, "reason": "pushed_at unchanged"}

    clone_url = f"https://github.com/{repo_slug}.git"
    if repo_dir.exists():
        subprocess.run(["git", "-C", str(repo_dir), "pull", "--ff-only"], check=True)
    else:
        subprocess.run(["git", "clone", "--depth", "1", clone_url, str(repo_dir)], check=True)

    res = ingest_directory(
        library,
        repo_dir,
        source_type="github",
        trust_status="reference",
        source_uri_prefix=f"https://github.com/{repo_slug}/blob/HEAD",
        stars=stars,
        pushed_at=pushed_at,
    )
    state_file.write_text(
        json.dumps({"repo": repo_slug, "pushed_at": pushed_at, "stars": stars}, indent=2),
        encoding="utf-8",
    )
    return {"repo": repo_slug, "skipped": False, **res}
