"""Configuration loader and path resolution for Extra-Conscious."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("~/.config/extra-conscious/config.toml")
DEFAULT_LIBRARY_DIR = Path("~/.local/share/extra-conscious/skill-library")
DEFAULT_PLUGIN_DIRS = [
    "~/.gemini/config/plugins",
    "~/.zcode/cli/plugins/cache",
]

DEFAULT_CONFIG_TEMPLATE = """\
# Extra-Conscious configuration (machine-level facts and user preferences)

[paths]
# Cross-project reusable skill library directory (override with RECON_LIBRARY_DIR)
skill_library_dir = "~/.local/share/extra-conscious/skill-library"
plugin_scan_dirs = [
  "~/.gemini/config/plugins",
  "~/.zcode/cli/plugins/cache",
]

[embedding]
# auto | sentence_transformers | openai_compat | remote | disabled
backend = "auto"
model = "BAAI/bge-m3"
dim = 1024
api_base = ""
api_key_env = "OPENAI_API_KEY"
remote_host = "wsl"

[api]
s2_api_key_env = "S2_API_KEY"
github_token_env = "GITHUB_TOKEN"
"""


@dataclass
class EmbeddingConfig:
    """Embedding backend settings for cross-lingual skill indexing."""

    backend: str = "auto"
    model: str = "BAAI/bge-m3"
    dim: int = 1024
    api_base: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    remote_host: str = "wsl"


@dataclass
class ApiConfig:
    """External academic and code API settings."""

    s2_api_key_env: str = "S2_API_KEY"
    github_token_env: str = "GITHUB_TOKEN"


@dataclass
class ReconConfig:
    """Resolved runtime configuration."""

    config_path: Path
    skill_library_dir: Path
    plugin_scan_dirs: list[Path] = field(default_factory=list)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    api: ApiConfig = field(default_factory=ApiConfig)


def expand_path(raw: str | Path) -> Path:
    """Expand user home and environment variables into an absolute Path."""
    return Path(os.path.expandvars(str(raw))).expanduser().resolve()


def resolve_config_path() -> Path:
    """Return the active config file path."""
    override = os.environ.get("EXTRA_CONSCIOUS_CONFIG")
    return expand_path(override) if override else expand_path(DEFAULT_CONFIG_PATH)


def write_default_config(config_path: Path | None = None) -> tuple[Path, bool]:
    """Create default config.toml if absent. Returns (path, created)."""
    target = config_path or resolve_config_path()
    if target.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    return target, True


def load_config(lib_dir_override: str | Path | None = None) -> ReconConfig:
    """Load configuration from TOML file and apply environment/CLI overrides."""
    config_path = resolve_config_path()
    raw: dict = {}
    if config_path.exists():
        with config_path.open("rb") as fh:
            raw = tomllib.load(fh)

    paths_cfg = raw.get("paths", {})
    embed_cfg = raw.get("embedding", {})
    api_cfg = raw.get("api", {})

    lib_raw = (
        lib_dir_override
        or os.environ.get("RECON_LIBRARY_DIR")
        or paths_cfg.get("skill_library_dir")
        or DEFAULT_LIBRARY_DIR
    )
    scan_raw = paths_cfg.get("plugin_scan_dirs", DEFAULT_PLUGIN_DIRS)

    return ReconConfig(
        config_path=config_path,
        skill_library_dir=expand_path(lib_raw),
        plugin_scan_dirs=[expand_path(p) for p in scan_raw],
        embedding=EmbeddingConfig(
            backend=str(embed_cfg.get("backend", "auto")),
            model=str(embed_cfg.get("model", "BAAI/bge-m3")),
            dim=int(embed_cfg.get("dim", 1024)),
            api_base=str(embed_cfg.get("api_base", "")),
            api_key_env=str(embed_cfg.get("api_key_env", "OPENAI_API_KEY")),
            remote_host=str(embed_cfg.get("remote_host", "wsl")),
        ),
        api=ApiConfig(
            s2_api_key_env=str(api_cfg.get("s2_api_key_env", "S2_API_KEY")),
            github_token_env=str(api_cfg.get("github_token_env", "GITHUB_TOKEN")),
        ),
    )
