"""Unified CLI entrypoint for Extra-Conscious (`recon`)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from recon.config import load_config, write_default_config
from recon.db.cache import CacheDB
from recon.db.library import SkillLibrary
from recon.doctor import run_doctor
from recon.fetch.papers import download_and_parse_paper, fetch_for_skeleton_fills, shallow_clone_repo
from recon.fetch.survey import (
    fetch_arxiv,
    fetch_github,
    fetch_hf_papers,
    fetch_openalex,
    fetch_semantic_scholar,
    fetch_web_markdown,
    fetch_wikipedia,
)
from recon.ingest.embedder import embed_missing_chunks, resolve_embedder
from recon.ingest.scanner import ingest_directory, ingest_local_plugins
from recon.ingest.sync import DEFAULT_COMMUNITY_REPOS, sync_github_repo
from recon.search.stage2 import run_stage2_search
from recon.validate.lint import check_skeleton_deps, lint_skeleton


def _emit(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    report = run_doctor(cfg)
    if args.json:
        _emit(report, True)
    else:
        for item in report["checks"]:
            print(f"[{item['status']:<4}] {item['name']:<22} {item['detail']}")
            if item["remediation"]:
                print(f"       -> {item['remediation']}")
        print(f"\nSummary: fail={report['fail_count']}, warn={report['warn_count']}")
    return 0 if report["ok"] else 1


def cmd_init(args: argparse.Namespace) -> int:
    cfg_path, created = write_default_config()
    cfg = load_config(args.lib_dir)
    lib = SkillLibrary(cfg.skill_library_dir, embed_dim=cfg.embedding.dim)
    exts = lib.ensure_extensions()
    _emit(
        {
            "config_path": str(cfg_path),
            "config_created": created,
            "skill_library_dir": str(cfg.skill_library_dir),
            "extensions": exts,
            "stats": lib.stats(),
        },
        True,
    )
    return 0


def cmd_init_workspace(args: argparse.Namespace) -> int:
    ws = Path(args.workspace).resolve()
    recon_dir = ws / ".recon"
    for sub in ("raw", "papers", "repos"):
        (recon_dir / sub).mkdir(parents=True, exist_ok=True)
    cache = CacheDB(ws)
    _emit({"workspace": str(ws), "recon_dir": str(recon_dir), "cache_db": str(cache.db_path)}, True)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    lib = SkillLibrary(cfg.skill_library_dir, embed_dim=cfg.embedding.dim)

    if args.ingest_cmd == "local":
        res = ingest_local_plugins(lib, cfg.plugin_scan_dirs)
        _emit({"action": "ingest_local", **res, "stats": lib.stats()}, True)
        return 0
    if args.ingest_cmd == "dir":
        res = ingest_directory(
            lib,
            Path(args.path).resolve(),
            source_type=args.source_type,
            trust_status=args.trust_status,
        )
        _emit({"action": "ingest_dir", "path": args.path, **res}, True)
        return 0
    if args.ingest_cmd == "sync":
        repos = args.repo or DEFAULT_COMMUNITY_REPOS
        token = os.environ.get(cfg.api.github_token_env, "")
        results = [sync_github_repo(lib, r, github_token=token) for r in repos]
        _emit({"action": "sync", "results": results, "stats": lib.stats()}, True)
        return 0
    return 2


def cmd_embed(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    lib = SkillLibrary(cfg.skill_library_dir, embed_dim=cfg.embedding.dim)
    embedder = resolve_embedder(cfg.embedding, backend_override=args.backend)
    if embedder is None:
        _emit(
            {
                "embedded": 0,
                "reason": "No embedding backend available; running in BM25-only mode.",
            },
            True,
        )
        return 0
    count = embed_missing_chunks(lib, embedder, batch_size=args.batch_size)
    _emit({"embedded": count, "stats": lib.stats()}, True)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    cache = CacheDB(args.workspace)
    provider = args.provider
    q = args.query
    limit = args.limit

    dispatch = {
        "wiki": lambda: fetch_wikipedia(q, cache, limit),
        "openalex": lambda: fetch_openalex(q, cache, limit),
        "s2": lambda: fetch_semantic_scholar(q, cache, limit, cfg.api.s2_api_key_env),
        "arxiv": lambda: fetch_arxiv(q, cache, limit),
        "hf": lambda: fetch_hf_papers(q, cache, limit),
        "github": lambda: fetch_github(q, cache, limit, cfg.api.github_token_env),
        "web": lambda: {"url": q, "markdown": fetch_web_markdown(q)},
    }
    if provider == "all":
        out = {}
        for name in ("wiki", "openalex", "s2", "arxiv", "github"):
            try:
                out[name] = dispatch[name]()
            except Exception as exc:  # noqa: BLE001
                out[name] = {"error": str(exc)}
        _emit(out, True)
        return 0

    _emit(dispatch[provider](), True)
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    lib = SkillLibrary(cfg.skill_library_dir, embed_dim=cfg.embedding.dim)
    ws = Path(args.workspace).resolve()
    terms_path = Path(args.terms) if args.terms else ws / ".recon" / "01-terms.md"
    out_path = Path(args.out) if args.out else ws / ".recon" / "03-candidates.md"

    embedder = None if args.no_embed else resolve_embedder(cfg.embedding)
    res = run_stage2_search(
        library=lib,
        terms_path=terms_path,
        out_path=out_path,
        embedder=embedder,
        top_k=args.top_k,
    )
    _emit(res, True)
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    res = lint_skeleton(Path(args.skeleton), strict_anchors=args.strict_anchors)
    payload = {
        "ok": res.ok,
        "step_count": res.step_count,
        "topo_order": res.topo_order,
        "errors": res.errors,
        "warnings": res.warnings,
    }
    if args.json:
        _emit(payload, True)
    else:
        status = "PASS" if res.ok else "FAIL"
        print(f"Skeleton lint: {status} ({res.step_count} steps)")
        for err in res.errors:
            print(f"  [ERR] {err}")
        if res.topo_order:
            print(f"  DAG order: {' -> '.join(res.topo_order)}")
    return 0 if res.ok else 1


def cmd_check_deps(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    lib = SkillLibrary(cfg.skill_library_dir, embed_dim=cfg.embedding.dim)
    res = check_skeleton_deps(Path(args.skeleton), lib, cfg)
    _emit(res, True)
    return 0 if res["ok"] else 1


def cmd_feedback(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    lib = SkillLibrary(cfg.skill_library_dir, embed_dim=cfg.embedding.dim)
    fid = lib.add_feedback(
        query_text=args.query,
        facet=args.facet,
        content_hash=args.hash,
        label=args.label,
        note=args.note,
    )
    _emit({"feedback_id": fid, "label": args.label}, True)
    return 0


def cmd_trust(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    lib = SkillLibrary(cfg.skill_library_dir, embed_dim=cfg.embedding.dim)
    updated = lib.update_trust_status(args.hash, args.status)
    _emit({"updated": updated, "content_hash": args.hash, "trust_status": args.status}, True)
    return 0 if updated else 1


def cmd_fill(args: argparse.Namespace) -> int:
    cfg = load_config(args.lib_dir)
    if args.fill_cmd == "fetch":
        res = fetch_for_skeleton_fills(
            Path(args.skeleton),
            args.workspace,
            limit_per_source=args.limit,
            s2_api_key_env=cfg.api.s2_api_key_env,
            github_token_env=cfg.api.github_token_env,
        )
        _emit(res, True)
        return 0
    if args.fill_cmd == "paper":
        res = download_and_parse_paper(args.pdf_url, args.paper_id, args.workspace)
        _emit(res, True)
        return 0 if res.get("parsed") or Path(res["pdf_path"]).exists() else 1
    if args.fill_cmd == "repo":
        res = shallow_clone_repo(args.repo_url, args.workspace)
        _emit(res, True)
        return 0
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recon", description="Extra-Conscious reconnaissance CLI")
    parser.add_argument("--lib-dir", default=None, help="Override skill_library_dir")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("doctor", help="Inspect tools, plugins, DuckDB extensions, and embedder")
    p_doc.add_argument("--json", action="store_true")
    p_doc.set_defaults(func=cmd_doctor)

    p_init = sub.add_parser("init", help="Initialize config.toml, skill library, and DuckDB extensions")
    p_init.set_defaults(func=cmd_init)

    p_ws = sub.add_parser("init-workspace", help="Initialize .recon/ directory inside a target project")
    p_ws.add_argument("workspace", nargs="?", default=".")
    p_ws.set_defaults(func=cmd_init_workspace)

    p_ing = sub.add_parser("ingest", help="Ingest local or community SKILL.md assets")
    ing_sub = p_ing.add_subparsers(dest="ingest_cmd", required=True)
    ing_sub.add_parser("local", help="Scan configured local plugin directories")
    p_ing_dir = ing_sub.add_parser("dir", help="Scan an arbitrary directory for SKILL.md")
    p_ing_dir.add_argument("path")
    p_ing_dir.add_argument("--source-type", default="local")
    p_ing_dir.add_argument("--trust-status", default="reference", choices=["reference", "adopted", "generated"])
    p_ing_sync = ing_sub.add_parser("sync", help="Incremental sync from GitHub skill repositories")
    p_ing_sync.add_argument("--repo", action="append", help="owner/repo (repeatable)")
    p_ing.set_defaults(func=cmd_ingest)

    p_emb = sub.add_parser("embed", help="Embed unindexed skill chunks using configured backend")
    p_emb.add_argument("--backend", default=None)
    p_emb.add_argument("--batch-size", type=int, default=32)
    p_emb.set_defaults(func=cmd_embed)

    p_fetch = sub.add_parser("fetch", help="Cached Stage 1 / Stage 5 academic and OSS search")
    p_fetch.add_argument("provider", choices=["wiki", "openalex", "s2", "arxiv", "hf", "github", "web", "all"])
    p_fetch.add_argument("--query", required=True)
    p_fetch.add_argument("--limit", type=int, default=10)
    p_fetch.add_argument("--workspace", default=".")
    p_fetch.set_defaults(func=cmd_fetch)

    p_search = sub.add_parser("search", help="Stage 2 pure-script hybrid search -> 03-candidates.md")
    p_search.add_argument("--workspace", default=".")
    p_search.add_argument("--terms", default=None)
    p_search.add_argument("--out", default=None)
    p_search.add_argument("--top-k", type=int, default=30)
    p_search.add_argument("--no-embed", action="store_true")
    p_search.set_defaults(func=cmd_search)

    p_lint = sub.add_parser("lint", help="Stage 4 skeleton validation gate")
    p_lint.add_argument("skeleton")
    p_lint.add_argument("--strict-anchors", action="store_true")
    p_lint.add_argument("--json", action="store_true")
    p_lint.set_defaults(func=cmd_lint)

    p_deps = sub.add_parser("check-deps", help="Verify external dependencies of skills mounted in skeleton")
    p_deps.add_argument("skeleton")
    p_deps.set_defaults(func=cmd_check_deps)

    p_fb = sub.add_parser("feedback", help="Record Stage 3 / Stage 6 retrieval feedback")
    p_fb.add_argument("--query", required=True)
    p_fb.add_argument("--facet", required=True)
    p_fb.add_argument("--hash", required=True)
    p_fb.add_argument("--label", required=True, choices=["good", "false_positive", "missed"])
    p_fb.add_argument("--note", default="")
    p_fb.set_defaults(func=cmd_feedback)

    p_tr = sub.add_parser("trust", help="Update skill governance trust_status")
    p_tr.add_argument("--hash", required=True)
    p_tr.add_argument("--status", required=True, choices=["reference", "adopted", "generated"])
    p_tr.set_defaults(func=cmd_trust)

    p_fill = sub.add_parser("fill", help="Stage 5 paper/repo fetch and download helpers")
    fill_sub = p_fill.add_subparsers(dest="fill_cmd", required=True)
    p_ff = fill_sub.add_parser("fetch", help="Fetch candidates for all `待填` steps in 04-skeleton.md")
    p_ff.add_argument("skeleton")
    p_ff.add_argument("--workspace", default=".")
    p_ff.add_argument("--limit", type=int, default=5)
    p_fp = fill_sub.add_parser("paper", help="Download PDF to .recon/papers/ and parse with mineru")
    p_fp.add_argument("--pdf-url", required=True)
    p_fp.add_argument("--paper-id", required=True)
    p_fp.add_argument("--workspace", default=".")
    p_fr = fill_sub.add_parser("repo", help="Shallow clone reference repo into .recon/repos/")
    p_fr.add_argument("--repo-url", required=True)
    p_fr.add_argument("--workspace", default=".")
    p_fill.set_defaults(func=cmd_fill)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
