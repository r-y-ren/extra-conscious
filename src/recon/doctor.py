"""Self-diagnostic command (`recon doctor`) for new devices and cold-start agents."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

from recon.config import ReconConfig
from recon.db.library import SkillLibrary
from recon.ingest.embedder import resolve_embedder


@dataclass
class CheckItem:
    """Single diagnostic result."""

    name: str
    status: str  # OK | WARN | FAIL
    detail: str
    remediation: str = ""


def _check_gh_auth() -> tuple[bool, str]:
    if shutil.which("gh") is None:
        return False, "gh binary missing"
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=8, check=False)
    if proc.returncode == 0:
        return True, "authenticated"
    return False, (proc.stderr or proc.stdout or "not logged in").strip().splitlines()[0]


def run_doctor(config: ReconConfig) -> dict[str, Any]:
    """Run all host, plugin, DuckDB, and embedding checks."""
    checks: list[CheckItem] = []

    py_ver = sys.version_info
    checks.append(
        CheckItem(
            name="python",
            status="OK" if py_ver >= (3, 11) else "FAIL",
            detail=f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}",
            remediation="" if py_ver >= (3, 11) else "Install Python >= 3.11 via uv python install 3.12",
        )
    )

    for tool, required, hint in (
        ("uv", True, "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"),
        ("git", True, "Install git via system package manager"),
        ("gh", True, "Install GitHub CLI (gh) and run: gh auth login"),
        ("duckdb", False, "Optional standalone CLI; installed via my-plugin bootstrap"),
        ("mineru", False, "Recommended PDF parser from my-plugin (for Stage 3 & Stage 5)"),
        ("trafilatura", False, "Recommended static web extractor from my-plugin (for Stage 1)"),
        ("ast-grep", False, "Recommended AST extractor from my-plugin (for Stage 5)"),
        ("bwrap", False, "Recommended sandbox (apt install bubblewrap) for Stage 6 untrusted code"),
    ):
        found = shutil.which(tool)
        checks.append(
            CheckItem(
                name=f"bin:{tool}",
                status="OK" if found else ("FAIL" if required else "WARN"),
                detail=found or "not in PATH",
                remediation="" if found else hint,
            )
        )

    gh_ok, gh_msg = _check_gh_auth()
    checks.append(
        CheckItem(
            name="gh_auth",
            status="OK" if gh_ok else "WARN",
            detail=gh_msg,
            remediation="" if gh_ok else "Run `gh auth login` or set GITHUB_TOKEN",
        )
    )

    installed_plugins: dict[str, str] = {}
    for pdir in config.plugin_scan_dirs:
        if pdir.exists():
            for child in pdir.iterdir():
                if child.is_dir():
                    installed_plugins[child.name] = str(child)

    for plugin_name, required_level, hint in (
        ("my-plugin", "WARN", "Install my-plugin for mineru/trafilatura/duckdb/ast-grep/bwrap-run/remote-compute"),
        ("fn-ladder", "WARN", "Optional: install fn-ladder for Stage 6 disciplined implementation"),
    ):
        loc = installed_plugins.get(plugin_name)
        checks.append(
            CheckItem(
                name=f"plugin:{plugin_name}",
                status="OK" if loc else required_level,
                detail=loc or "not found in plugin_scan_dirs",
                remediation="" if loc else hint,
            )
        )

    checks.append(
        CheckItem(
            name="config",
            status="OK" if config.config_path.exists() else "WARN",
            detail=str(config.config_path) if config.config_path.exists() else f"missing ({config.config_path})",
            remediation="" if config.config_path.exists() else "Run `recon init` or `./scripts/bootstrap.sh`",
        )
    )

    lib = SkillLibrary(config.skill_library_dir, embed_dim=config.embedding.dim)
    stats = lib.stats()
    checks.append(
        CheckItem(
            name="duckdb_fts",
            status="OK" if stats["fts_ready"] else "WARN",
            detail="loaded" if stats["fts_ready"] else "fts extension not installed",
            remediation="" if stats["fts_ready"] else "Run `recon init` to install DuckDB fts extension",
        )
    )
    checks.append(
        CheckItem(
            name="duckdb_vss",
            status="OK" if stats["vss_ready"] else "WARN",
            detail="loaded" if stats["vss_ready"] else "vss extension not installed",
            remediation="" if stats["vss_ready"] else "Run `recon init` to install DuckDB vss extension",
        )
    )
    checks.append(
        CheckItem(
            name="skill_library",
            status="OK" if stats["total_skills"] > 0 else "WARN",
            detail=f"{stats['total_skills']} skills, {stats['embedded_chunks']}/{stats['total_chunks']} chunks embedded",
            remediation="" if stats["total_skills"] > 0 else "Run `recon ingest local` to populate library",
        )
    )

    try:
        embedder = resolve_embedder(config.embedding)
        checks.append(
            CheckItem(
                name="embedding_backend",
                status="OK" if embedder is not None else "WARN",
                detail=f"{type(embedder).__name__} ({config.embedding.model})"
                if embedder is not None
                else "BM25-only mode (no local/remote embedder configured)",
                remediation=""
                if embedder is not None
                else "Install `extra-conscious[embed]`, set embedding.api_base, or configure remote-compute",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            CheckItem(
                name="embedding_backend",
                status="WARN",
                detail=f"backend error: {exc}",
                remediation="Check [embedding] section in config.toml",
            )
        )

    fail_count = sum(1 for c in checks if c.status == "FAIL")
    warn_count = sum(1 for c in checks if c.status == "WARN")
    return {
        "ok": fail_count == 0,
        "fail_count": fail_count,
        "warn_count": warn_count,
        "checks": [asdict(c) for c in checks],
    }
