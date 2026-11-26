"""Stage 4 `recon lint` gate and `recon check-deps` environment validator."""

from __future__ import annotations

import os
import re
import shutil
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from recon.config import ReconConfig
from recon.db.library import SkillLibrary

VALID_VERIFY_TYPES = {"复现型", "规约型", "回归型", "人工抽查型"}
# Use ASCII boundaries because Chinese characters (e.g. "S01的输出") count as \w in Python regex
STEP_REF_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])(S\d+[A-Za-z0-9_-]*)")


@dataclass
class LintResult:
    """Validation result returned by `lint_skeleton`."""

    ok: bool
    step_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    topo_order: list[str] = field(default_factory=list)


def extract_step_cards(skeleton_path: Path) -> list[dict[str, Any]]:
    """Parse all YAML step cards containing `step_id` from 04-skeleton.md."""
    text = skeleton_path.read_text(encoding="utf-8")
    cards: list[dict[str, Any]] = []
    for chunk in text.split("```yaml")[1:]:
        if "```" not in chunk:
            continue
        raw_yaml = chunk.split("```", 1)[0]
        try:
            obj = yaml.safe_load(raw_yaml)
        except yaml.YAMLError:
            continue
        if isinstance(obj, dict) and "step_id" in obj:
            cards.append(obj)
    return cards


def lint_skeleton(skeleton_path: Path, *, strict_anchors: bool = False) -> LintResult:
    """Enforce the four Stage 4 invariants: provenance, verification, no dangling inputs, DAG acyclic."""
    cards = extract_step_cards(skeleton_path)
    errors: list[str] = []
    warnings: list[str] = []

    if not cards:
        return LintResult(ok=False, step_count=0, errors=["No YAML step cards with `step_id` found."])

    step_ids = [str(c["step_id"]) for c in cards]
    if len(step_ids) != len(set(step_ids)):
        errors.append("Duplicate step_id detected in skeleton.")
    known_ids = set(step_ids)

    adj: dict[str, list[str]] = {sid: [] for sid in step_ids}
    indegree: dict[str, int] = {sid: 0 for sid in step_ids}

    for card in cards:
        sid = str(card["step_id"])

        # 1. Provenance check
        provenance = card.get("出处")
        if not provenance or (isinstance(provenance, list) and len(provenance) == 0):
            errors.append(f"[{sid}] Missing provenance (`出处`): hallucination gate forbids ungrounded steps.")

        # 2. Verification check
        verify = card.get("验证")
        if not isinstance(verify, dict):
            errors.append(f"[{sid}] Missing verification block (`验证`).")
        else:
            vtype = str(verify.get("类型", "")).strip()
            if vtype not in VALID_VERIFY_TYPES:
                errors.append(f"[{sid}] Invalid `验证.类型`: {vtype!r}. Must be one of {sorted(VALID_VERIFY_TYPES)}.")
            cmd = str(verify.get("命令", "")).strip()
            if vtype != "人工抽查型" and not cmd:
                errors.append(f"[{sid}] Executable `验证.命令` is required for verification type `{vtype}`.")
            anchor = str(verify.get("锚点", "")).strip()
            if strict_anchors and vtype == "复现型" and (not anchor or "待阶段5回填" in anchor or "TBD" in anchor.upper()):
                errors.append(f"[{sid}] Strict anchor check failed: `验证.锚点` still pending Stage 5 backfill.")

        # 3. Dangling input check + DAG edges
        inputs = card.get("输入") or []
        if not isinstance(inputs, list):
            errors.append(f"[{sid}] `输入` must be a list.")
            inputs = []

        for raw_in in inputs:
            item = str(raw_in).strip()
            if item.startswith("外部:") or item.startswith("external:"):
                continue
            ref_match = STEP_REF_PATTERN.search(item)
            if ref_match:
                dep_id = ref_match.group(1)
                if dep_id not in known_ids:
                    errors.append(f"[{sid}] Dangling input `{item}` references unknown step `{dep_id}`.")
                elif dep_id == sid:
                    errors.append(f"[{sid}] Self-dependency detected in `输入`.")
                else:
                    adj[dep_id].append(sid)
                    indegree[sid] += 1
            elif item not in known_ids:
                errors.append(
                    f"[{sid}] Dangling input `{item}`: must start with `外部:` or reference an existing step_id."
                )

    # 4. Cycle check via Kahn's algorithm
    queue = deque(sid for sid in step_ids if indegree[sid] == 0)
    topo_order: list[str] = []
    while queue:
        cur = queue.popleft()
        topo_order.append(cur)
        for nxt in adj[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(topo_order) != len(step_ids):
        cyclic = sorted(sid for sid, deg in indegree.items() if deg > 0)
        errors.append(f"Cycle detected in skeleton DAG involving steps: {', '.join(cyclic)}.")

    return LintResult(
        ok=len(errors) == 0,
        step_count=len(cards),
        errors=errors,
        warnings=warnings,
        topo_order=topo_order if len(topo_order) == len(step_ids) else [],
    )


def check_skeleton_deps(
    skeleton_path: Path,
    library: SkillLibrary,
    config: ReconConfig,
) -> dict[str, Any]:
    """Aggregate external dependencies of all skills mounted in 04-skeleton.md and verify host readiness."""
    cards = extract_step_cards(skeleton_path)
    skill_names: list[str] = []
    for card in cards:
        mount = card.get("挂载") or {}
        for s in mount.get("技能", []) or []:
            name = str(s).strip()
            if name and name not in skill_names:
                skill_names.append(name)

    meta_map = library.lookup_skills_by_name(skill_names)
    required_bins: set[str] = set()
    inferred_bins: set[str] = set()
    required_envs: set[str] = set()
    required_plugins: set[str] = set()
    required_mcp: set[str] = set()
    unknown_skills: list[str] = []

    for name in skill_names:
        info = meta_map.get(name)
        if not info:
            unknown_skills.append(name)
            continue
        deps = info.get("dependencies") or {}
        required_bins.update(deps.get("bins", []))
        inferred_bins.update(deps.get("inferred_bins", []))
        required_envs.update(deps.get("env", []))
        required_plugins.update(deps.get("plugins", []))
        required_mcp.update(deps.get("mcp", []))

    missing_bins = sorted(b for b in required_bins if shutil.which(b) is None)
    missing_inferred_bins = sorted(b for b in (inferred_bins - required_bins) if shutil.which(b) is None)
    missing_envs = sorted(e for e in required_envs if not os.environ.get(e))

    installed_plugins: set[str] = set()
    for pdir in config.plugin_scan_dirs:
        if pdir.exists():
            for child in pdir.iterdir():
                if child.is_dir():
                    installed_plugins.add(child.name)
    missing_plugins = sorted(p for p in required_plugins if p not in installed_plugins)

    ok = not missing_bins and not missing_envs and not missing_plugins
    return {
        "ok": ok,
        "skills_referenced": skill_names,
        "unknown_skills": unknown_skills,
        "missing_bins": missing_bins,
        "missing_inferred_bins": missing_inferred_bins,
        "missing_envs": missing_envs,
        "missing_plugins": missing_plugins,
        "required_mcp": sorted(required_mcp),
    }
