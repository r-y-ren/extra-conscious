"""Stage 2 pure deterministic script: facet query construction -> RRF search -> tiered routing."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from recon.db.library import SearchHit, SkillLibrary
from recon.ingest.embedder import EmbeddingProvider


@dataclass
class TermEntry:
    """Single confirmed row parsed from 01-terms.md."""

    facet: str
    en_term: str
    zh_term: str
    status: str


def _col_index(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    for idx, h in enumerate(headers):
        norm = h.strip().lower()
        if any(c in norm for c in candidates):
            return idx
    return None


def parse_terms_markdown(terms_path: Path) -> list[TermEntry]:
    """Parse markdown tables in 01-terms.md into structured TermEntry rows."""
    lines = terms_path.read_text(encoding="utf-8").splitlines()
    entries: list[TermEntry] = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip()):
            headers = [c.strip() for c in line.strip("|").split("|")]
            facet_idx = _col_index(headers, ("分面", "facet", "子领域", "subfield"))
            en_idx = _col_index(headers, ("英文", "english", "en_term", "术语", "term"))
            zh_idx = _col_index(headers, ("中文", "日常", "chinese", "zh"))
            status_idx = _col_index(headers, ("状态", "status"))
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) >= max(idx for idx in (facet_idx, en_idx) if idx is not None) + 1 if (facet_idx is not None and en_idx is not None) else False:
                    facet = cells[facet_idx] or "general"
                    en_term = cells[en_idx]
                    zh_term = cells[zh_idx] if zh_idx is not None and zh_idx < len(cells) else ""
                    status = cells[status_idx] if status_idx is not None and status_idx < len(cells) else "confirmed"
                    if en_term and "待定" not in status and "pending" not in status.lower():
                        entries.append(TermEntry(facet=facet, en_term=en_term, zh_term=zh_term, status=status))
                i += 1
            continue
        i += 1

    return entries


def build_facet_queries(entries: list[TermEntry]) -> dict[str, str]:
    """Group confirmed terms by facet into bilingual query strings (EN primary, ZH secondary)."""
    grouped: dict[str, list[TermEntry]] = defaultdict(list)
    for item in entries:
        grouped[item.facet].append(item)

    queries: dict[str, str] = {}
    for facet, items in grouped.items():
        en_parts = list(dict.fromkeys(it.en_term for it in items if it.en_term))
        zh_parts = list(dict.fromkeys(it.zh_term for it in items if it.zh_term))
        # Put facet qualifier + English terms first, Chinese terms as secondary context
        parts = [facet] + en_parts + zh_parts
        queries[facet] = " ".join(parts)
    return queries


def tier_hits(
    hits: list[SearchHit],
    *,
    high_threshold: float = 0.028,
    med_threshold: float = 0.012,
    review_cap: int = 20,
) -> dict[str, list[SearchHit]]:
    """Partition ranked hits into high-confidence, medium-review, and low-gap buckets."""
    high: list[SearchHit] = []
    medium: list[SearchHit] = []
    low: list[SearchHit] = []
    for hit in hits:
        if hit.rrf_score >= high_threshold:
            high.append(hit)
        elif hit.rrf_score >= med_threshold and len(medium) < review_cap:
            medium.append(hit)
        else:
            low.append(hit)
    return {"high": high, "medium": medium, "low": low}


def run_stage2_search(
    *,
    library: SkillLibrary,
    terms_path: Path,
    out_path: Path,
    embedder: EmbeddingProvider | None = None,
    top_k: int = 30,
) -> dict[str, Any]:
    """Execute Stage 2 pure-script search and render 03-candidates.md."""
    entries = parse_terms_markdown(terms_path)
    queries = build_facet_queries(entries)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# 03-candidates · 阶段 2 Skill 混合检索候选清单",
        "",
        f"> 检索词来源：`{terms_path}` | 索引库：`{library.db_path}` | 本地与社区技能同权计分（无来源偏置）",
        "",
    ]
    summary: dict[str, dict[str, int]] = {}
    gaps: list[str] = []

    if not queries:
        lines.append("_未在 `01-terms.md` 解析到已确认术语行（请检查是否包含 `分面` 与 `英文术语` 列）。_")
    else:
        lines.extend(
            [
                "## 分面覆盖概览",
                "",
                "| 分面 (Facet) | 检索词 | 高置信 (`high`) | 终审池 (`medium`) | 建议 Stage 3 路径 |",
                "| :--- | :--- | :---: | :---: | :--- |",
            ]
        )

        facet_results: dict[str, dict[str, list[SearchHit]]] = {}
        for facet, qtext in queries.items():
            qvec = embedder.embed([qtext])[0] if embedder is not None else None
            hits = library.hybrid_search(qtext, query_embedding=qvec, top_k=top_k)
            tiered = tier_hits(hits)
            facet_results[facet] = tiered

            has_process_high = any(h.granularity in {"lifecycle", "process"} for h in tiered["high"])
            route_hint = "综合路径（含流程级高置信命中）" if has_process_high else "反推路径（缺流程级高置信命中）"
            if not tiered["high"] and not tiered["medium"]:
                gaps.append(facet)
            summary[facet] = {
                "high": len(tiered["high"]),
                "medium": len(tiered["medium"]),
                "low": len(tiered["low"]),
            }
            q_preview = qtext if len(qtext) <= 60 else qtext[:57] + "..."
            lines.append(
                f"| {facet} | `{q_preview}` | {len(tiered['high'])} | {len(tiered['medium'])} | {route_hint} |"
            )

        lines.append("")
        for facet, tiered in facet_results.items():
            lines.extend([f"## 分面：{facet}", ""])
            for tier_name, label in (("high", "高置信候选池 (`high`)"), ("medium", "终审池 (`medium`)")):
                bucket = tiered[tier_name]
                lines.append(f"### {label}")
                if not bucket:
                    lines.extend(["", "_无命中_", ""])
                    continue
                lines.extend(
                    [
                        "",
                        "| Skill | 粒度 | RRF 分数 | BM25排名 | 向量排名 | 信任状态 | 命中段落 | Hash | 出处 |",
                        "| :--- | :--- | :---: | :---: | :---: | :--- | :--- | :--- | :--- |",
                    ]
                )
                for h in bucket:
                    lines.append(
                        f"| {h.name} | {h.granularity} | {h.rrf_score:.4f} | "
                        f"{h.bm25_rank or '-'} | {h.vec_rank or '-'} | {h.trust_status} | "
                        f"{h.matched_section} | `{h.content_hash[:10]}` | {h.source_uri} |"
                    )
                lines.append("")

        lines.extend(["## 负结果 / 领域缺口记录", ""])
        if gaps:
            for g in gaps:
                lines.append(f"- `{g}`：无高/中档命中，阶段 3 需走多源反推并考虑补充社区源。")
        else:
            lines.append("- 所有分面均有候选命中（仍需在阶段 3 按流程级粒度核验是否覆盖核心过程）。")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"facets": len(queries), "summary": summary, "gaps": gaps, "out_path": str(out_path)}
