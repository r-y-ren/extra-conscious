"""Cached academic and open-source search providers for Stage 1 & Stage 5."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from recon.db.cache import CacheDB

USER_AGENT = "extra-conscious/0.1 (research-recon)"


def _reconstruct_openalex_abstract(inv_index: dict[str, list[int]] | None) -> str:
    if not inv_index:
        return ""
    words: dict[int, str] = {}
    for token, positions in inv_index.items():
        for pos in positions:
            words[pos] = token
    return " ".join(words[i] for i in sorted(words))


def fetch_wikipedia(query: str, cache: CacheDB | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """Query Wikipedia search API for plain-language entity disambiguation."""
    if cache is not None:
        cached = cache.get("wiki", f"{query}|{limit}")
        if cached is not None:
            return cached

    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
        "utf8": 1,
    }
    resp = httpx.get(
        "https://en.wikipedia.org/w/api.php",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    items = [
        {
            "title": hit.get("title", ""),
            "pageid": hit.get("pageid"),
            "snippet": hit.get("snippet", ""),
            "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(hit.get('title', '').replace(' ', '_'))}",
        }
        for hit in resp.json().get("query", {}).get("search", [])
    ]
    if cache is not None:
        cache.put("wiki", f"{query}|{limit}", resp.status_code, items)
    return items


def fetch_openalex(query: str, cache: CacheDB | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Query OpenAlex Works API for Domain -> Field -> Topic taxonomy & citation counts."""
    if cache is not None:
        cached = cache.get("openalex", f"{query}|{limit}")
        if cached is not None:
            return cached

    params = {
        "search": query,
        "per-page": limit,
        "sort": "cited_by_count:desc",
    }
    resp = httpx.get(
        "https://api.openalex.org/works",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    resp.raise_for_status()
    items: list[dict[str, Any]] = []
    for work in resp.json().get("results", []):
        primary = work.get("primary_topic") or {}
        items.append(
            {
                "id": work.get("id", ""),
                "title": work.get("title", ""),
                "year": work.get("publication_year"),
                "cited_by_count": work.get("cited_by_count", 0),
                "doi": work.get("doi"),
                "domain": (primary.get("domain") or {}).get("display_name", ""),
                "field": (primary.get("field") or {}).get("display_name", ""),
                "topic": primary.get("display_name", ""),
                "abstract": _reconstruct_openalex_abstract(work.get("abstract_inverted_index"))[:1200],
            }
        )
    if cache is not None:
        cache.put("openalex", f"{query}|{limit}", resp.status_code, items)
    return items


def fetch_semantic_scholar(
    query: str,
    cache: CacheDB | None = None,
    limit: int = 10,
    api_key_env: str = "S2_API_KEY",
) -> list[dict[str, Any]]:
    """Query Semantic Scholar Graph API ranked by influential citations."""
    if cache is not None:
        cached = cache.get("s2", f"{query}|{limit}")
        if cached is not None:
            return cached

    headers = {"User-Agent": USER_AGENT}
    api_key = os.environ.get(api_key_env, "")
    if api_key:
        headers["x-api-key"] = api_key

    params = {
        "query": query,
        "limit": limit,
        "fields": "title,year,citationCount,influentialCitationCount,fieldsOfStudy,externalIds,openAccessPdf,abstract",
    }
    resp = httpx.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params=params,
        headers=headers,
        timeout=25,
    )
    resp.raise_for_status()
    raw = resp.json().get("data", [])
    raw.sort(
        key=lambda x: (x.get("influentialCitationCount") or 0, x.get("citationCount") or 0),
        reverse=True,
    )
    items = [
        {
            "paperId": p.get("paperId", ""),
            "title": p.get("title", ""),
            "year": p.get("year"),
            "citationCount": p.get("citationCount", 0),
            "influentialCitationCount": p.get("influentialCitationCount", 0),
            "fieldsOfStudy": p.get("fieldsOfStudy") or [],
            "arxivId": (p.get("externalIds") or {}).get("ArXiv"),
            "pdfUrl": (p.get("openAccessPdf") or {}).get("url"),
            "abstract": (p.get("abstract") or "")[:1200],
        }
        for p in raw
    ]
    if cache is not None:
        cache.put("s2", f"{query}|{limit}", resp.status_code, items)
    return items


def fetch_arxiv(query: str, cache: CacheDB | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Query arXiv Atom API and parse normalized entries."""
    if cache is not None:
        cached = cache.get("arxiv", f"{query}|{limit}")
        if cached is not None:
            return cached

    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
    }
    resp = httpx.get(
        "https://export.arxiv.org/api/query",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    resp.raise_for_status()
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.text)
    items: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        entry_id = (entry.findtext("atom:id", "", ns) or "").strip()
        arxiv_id = entry_id.rsplit("/", 1)[-1]
        title = " ".join((entry.findtext("atom:title", "", ns) or "").split())
        summary = " ".join((entry.findtext("atom:summary", "", ns) or "").split())
        published = (entry.findtext("atom:published", "", ns) or "")[:10]
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""
        items.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "published": published,
                "pdf_url": pdf_url,
                "summary": summary[:1200],
            }
        )
    if cache is not None:
        cache.put("arxiv", f"{query}|{limit}", resp.status_code, items)
    return items


def fetch_hf_papers(query: str, cache: CacheDB | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Query Hugging Face Papers search API (replaces Papers with Code)."""
    if cache is not None:
        cached = cache.get("hf", f"{query}|{limit}")
        if cached is not None:
            return cached

    resp = httpx.get(
        "https://huggingface.co/api/papers",
        params={"q": query},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    resp.raise_for_status()
    raw = resp.json() if isinstance(resp.json(), list) else []
    items: list[dict[str, Any]] = []
    for row in raw[:limit]:
        paper = row.get("paper") if isinstance(row, dict) and "paper" in row else row
        if not isinstance(paper, dict):
            continue
        pid = paper.get("id", "")
        items.append(
            {
                "id": pid,
                "title": paper.get("title", ""),
                "upvotes": paper.get("upvotes", 0),
                "githubRepo": paper.get("githubRepo"),
                "githubStars": paper.get("githubStars"),
                "url": f"https://huggingface.co/papers/{pid}" if pid else "",
                "summary": (paper.get("summary") or "")[:1000],
            }
        )
    if cache is not None:
        cache.put("hf", f"{query}|{limit}", resp.status_code, items)
    return items


def fetch_github(
    query: str,
    cache: CacheDB | None = None,
    limit: int = 10,
    github_token_env: str = "GITHUB_TOKEN",
) -> list[dict[str, Any]]:
    """Query GitHub repositories ranked by stars via gh CLI or REST API."""
    if cache is not None:
        cached = cache.get("github", f"{query}|{limit}")
        if cached is not None:
            return cached

    encoded = urllib.parse.quote(query)
    endpoint = f"search/repositories?q={encoded}&sort=stars&order=desc&per_page={limit}"
    raw_items: list[dict[str, Any]] = []
    status_code = 200

    used_gh = False
    try:
        proc = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            raw_items = json.loads(proc.stdout).get("items", [])
            used_gh = True
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass

    if not used_gh:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
        token = os.environ.get(github_token_env, "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = httpx.get(f"https://api.github.com/{endpoint}", headers=headers, timeout=20)
        resp.raise_for_status()
        status_code = resp.status_code
        raw_items = resp.json().get("items", [])

    items = [
        {
            "full_name": r.get("full_name", ""),
            "html_url": r.get("html_url", ""),
            "stars": r.get("stargazers_count", 0),
            "pushed_at": r.get("pushed_at", ""),
            "license": (r.get("license") or {}).get("spdx_id", ""),
            "topics": r.get("topics") or [],
            "description": (r.get("description") or "")[:400],
        }
        for r in raw_items[:limit]
    ]
    if cache is not None:
        cache.put("github", f"{query}|{limit}", status_code, items)
    return items


def fetch_web_markdown(url: str) -> str:
    """Extract clean markdown from a static webpage using trafilatura CLI."""
    proc = subprocess.run(
        ["trafilatura", "-u", url, "--markdown", "--links"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"trafilatura failed for {url}: {proc.stderr.strip()}")
    return proc.stdout
