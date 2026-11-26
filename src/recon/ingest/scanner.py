"""SKILL.md parser, dependency extractor, and local/directory ingestion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from recon.db.library import SkillLibrary

KNOWN_TOOL_PATTERNS = (
    "duckdb",
    "mineru",
    "trafilatura",
    "ast-grep",
    "bwrap",
    "playwright",
    "ffmpeg",
    "docker",
    "kubectl",
    "pdftotext",
    "uv",
    "npm",
    "npx",
    "gh",
)


@dataclass
class ParsedSkill:
    """Structured representation of a SKILL.md file."""

    name: str
    description: str
    body_md: str
    raw_text: str
    granularity: str
    dependencies: dict[str, Any]
    assets: list[str]


def parse_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
    """Split optional YAML frontmatter from markdown body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw_text, flags=re.DOTALL)
    if not match:
        return {}, raw_text
    meta_raw, body = match.group(1), match.group(2)
    try:
        meta = yaml.safe_load(meta_raw) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


def extract_dependencies(meta: dict[str, Any], body_md: str) -> dict[str, Any]:
    """Extract declared binary, env, plugin, and MCP dependencies from SKILL.md."""
    bins: set[str] = set()
    envs: set[str] = set()
    plugins: set[str] = set()
    mcp: set[str] = set()

    requires = meta.get("requires") or {}
    if isinstance(requires, dict):
        for b in requires.get("bins", []) or []:
            bins.add(str(b))
        for e in requires.get("env", []) or []:
            envs.add(str(e))
        for p in requires.get("plugins", []) or []:
            plugins.add(str(p))
        for m in requires.get("mcp", []) or []:
            mcp.add(str(m))

    for key in ("bins", "tools", "dependencies"):
        val = meta.get(key)
        if isinstance(val, list):
            for item in val:
                bins.add(str(item))

    # Scan bash/sh fenced code blocks for known CLI dependencies
    inferred_bins: set[str] = set()
    for block in re.findall(r"```(?:bash|sh|zsh)?\n(.*?)```", body_md, flags=re.DOTALL):
        for tool in KNOWN_TOOL_PATTERNS:
            if re.search(rf"(?<![\w-]){re.escape(tool)}(?![\w-])", block):
                inferred_bins.add(tool)

    return {
        "bins": sorted(bins),
        "inferred_bins": sorted(inferred_bins - bins),
        "env": sorted(envs),
        "plugins": sorted(plugins),
        "mcp": sorted(mcp),
    }


def infer_granularity(name: str, meta: dict[str, Any], body_md: str) -> str:
    """Classify skill granularity into lifecycle, process, or tool."""
    explicit = str(meta.get("granularity", "")).strip().lower()
    if explicit in {"lifecycle", "process", "tool"}:
        return explicit

    lowered = f"{name} {meta.get('description', '')}".lower()
    if any(k in lowered for k in ("ladder", "lifecycle", "end-to-end", "阶段", "全流程")):
        return "lifecycle"
    headings = re.findall(r"(?m)^##\s+", body_md)
    if len(headings) >= 3 or len(body_md) >= 2200:
        return "process"
    return "tool"


def list_skill_assets(skill_dir: Path) -> list[str]:
    """List relative paths of supporting files alongside SKILL.md."""
    assets: list[str] = []
    for p in sorted(skill_dir.rglob("*")):
        if p.is_file() and p.name != "SKILL.md":
            assets.append(str(p.relative_to(skill_dir)))
    return assets


def parse_skill_file(skill_md_path: Path) -> ParsedSkill:
    """Parse a SKILL.md file and its neighboring assets."""
    raw_text = skill_md_path.read_text(encoding="utf-8", errors="replace")
    meta, body_md = parse_frontmatter(raw_text)
    name = str(meta.get("name") or skill_md_path.parent.name).strip()
    description = str(meta.get("description") or "").strip()
    deps = extract_dependencies(meta, body_md)
    granularity = infer_granularity(name, meta, body_md)
    assets = list_skill_assets(skill_md_path.parent)
    return ParsedSkill(
        name=name,
        description=description,
        body_md=body_md,
        raw_text=raw_text,
        granularity=granularity,
        dependencies=deps,
        assets=assets,
    )


def discover_skill_files(root: Path) -> list[Path]:
    """Find all SKILL.md files recursively under a directory."""
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("SKILL.md") if p.is_file())


def ingest_directory(
    library: SkillLibrary,
    root: Path,
    *,
    source_type: str,
    trust_status: str = "reference",
    source_uri_prefix: str = "",
    stars: int = 0,
    pushed_at: str = "",
) -> dict[str, int]:
    """Scan a directory for SKILL.md files and ingest them into SkillLibrary."""
    files = discover_skill_files(root)
    added = 0
    unchanged = 0
    for path in files:
        parsed = parse_skill_file(path)
        rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        uri = f"{source_uri_prefix}/{rel}".strip("/") if source_uri_prefix else str(path)
        _, is_new = library.upsert_skill(
            name=parsed.name,
            description=parsed.description,
            raw_skill_md=parsed.raw_text,
            body_md=parsed.body_md,
            source_type=source_type,
            source_uri=uri,
            trust_status=trust_status,
            granularity=parsed.granularity,
            stars=stars,
            pushed_at=pushed_at,
            dependencies=parsed.dependencies,
            assets=parsed.assets,
            rebuild_indexes=False,
        )
        if is_new:
            added += 1
        else:
            unchanged += 1
    if added > 0:
        library.rebuild_fts_index()
    return {"found": len(files), "added": added, "unchanged": unchanged}


def ingest_local_plugins(library: SkillLibrary, scan_dirs: list[Path]) -> dict[str, Any]:
    """Ingest skills from configured local plugin directories (equal search weight)."""
    totals = {"dirs_scanned": 0, "found": 0, "added": 0, "unchanged": 0}
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        totals["dirs_scanned"] += 1
        res = ingest_directory(
            library,
            scan_dir,
            source_type="plugin",
            trust_status="adopted",
        )
        totals["found"] += res["found"]
        totals["added"] += res["added"]
        totals["unchanged"] += res["unchanged"]
    return totals
