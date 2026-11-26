"""Cross-project skill library backed by DuckDB (fts + vss + RRF)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

VALID_TRUST_STATUSES = {"reference", "adopted", "generated"}
VALID_GRANULARITIES = {"lifecycle", "process", "tool"}


@dataclass
class SearchHit:
    """Single skill hit returned by hybrid RRF search."""

    content_hash: str
    name: str
    description: str
    source_type: str
    source_uri: str
    trust_status: str
    granularity: str
    rrf_score: float
    bm25_rank: int | None
    vec_rank: int | None
    matched_section: str
    dependencies: dict[str, Any]


def chunk_skill_markdown(
    name: str,
    description: str,
    body_md: str,
) -> list[tuple[str, str]]:
    """Split SKILL.md into frontmatter + ## section chunks for balanced retrieval."""
    chunks: list[tuple[str, str]] = []
    header_text = f"{name}\n{description}".strip()
    if header_text:
        chunks.append(("frontmatter", header_text))

    sections = re.split(r"(?m)^(?=##\s+)", body_md.strip())
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        lines = sec.splitlines()
        title = lines[0].lstrip("#").strip() if lines[0].startswith("##") else "overview"
        # Sub-split very long sections while preserving heading context
        if len(sec) <= 1800:
            chunks.append((title, sec))
        else:
            paragraphs = sec.split("\n\n")
            buf: list[str] = []
            buf_len = 0
            part = 1
            for para in paragraphs:
                if buf and buf_len + len(para) > 1500:
                    chunks.append((f"{title} (part {part})", "\n\n".join(buf)))
                    buf = [para]
                    buf_len = len(para)
                    part += 1
                else:
                    buf.append(para)
                    buf_len += len(para)
            if buf:
                suffix = f" (part {part})" if part > 1 else ""
                chunks.append((f"{title}{suffix}", "\n\n".join(buf)))
    return chunks or [("overview", name)]


class SkillLibrary:
    """Manages library.duckdb and content-addressed skill snapshots."""

    def __init__(self, library_dir: Path | str, embed_dim: int = 1024) -> None:
        self.library_dir = Path(library_dir).resolve()
        self.skills_dir = self.library_dir / "skills"
        self.db_path = self.library_dir / "library.duckdb"
        self.embed_dim = embed_dim
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._fts_ready = False
        self._vss_ready = False
        self._init_schema()

    def _connect(self, install_extensions: bool = False) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self.db_path))
        self._fts_ready = self._try_extension(con, "fts", install=install_extensions)
        self._vss_ready = self._try_extension(con, "vss", install=install_extensions)
        if self._vss_ready:
            con.execute("SET hnsw_enable_experimental_persistence = true")
        return con

    @staticmethod
    def _try_extension(
        con: duckdb.DuckDBPyConnection,
        ext_name: str,
        install: bool = False,
    ) -> bool:
        try:
            con.execute(f"LOAD {ext_name}")
            return True
        except duckdb.Error:
            if not install:
                return False
            try:
                con.execute(f"INSTALL {ext_name}")
                con.execute(f"LOAD {ext_name}")
                return True
            except duckdb.Error:
                return False

    def ensure_extensions(self) -> dict[str, bool]:
        """Attempt to install and load fts and vss extensions."""
        with self._connect(install_extensions=True):
            return {"fts": self._fts_ready, "vss": self._vss_ready}

    def _init_schema(self) -> None:
        with self._connect(install_extensions=False) as con:
            con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS skills (
                    content_hash VARCHAR PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    description VARCHAR NOT NULL,
                    source_type VARCHAR NOT NULL,
                    source_uri VARCHAR NOT NULL,
                    trust_status VARCHAR NOT NULL,
                    granularity VARCHAR NOT NULL,
                    license VARCHAR,
                    stars INTEGER DEFAULT 0,
                    pushed_at VARCHAR,
                    dependencies_json VARCHAR NOT NULL,
                    body_md VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_chunks (
                    chunk_id VARCHAR PRIMARY KEY,
                    content_hash VARCHAR NOT NULL,
                    section_title VARCHAR NOT NULL,
                    chunk_order INTEGER NOT NULL,
                    chunk_text VARCHAR NOT NULL,
                    embedding FLOAT[{self.embed_dim}]
                );
                CREATE TABLE IF NOT EXISTS retrieval_feedback (
                    feedback_id VARCHAR PRIMARY KEY,
                    query_text VARCHAR NOT NULL,
                    facet VARCHAR NOT NULL,
                    content_hash VARCHAR NOT NULL,
                    label VARCHAR NOT NULL,
                    note VARCHAR,
                    created_at TIMESTAMP NOT NULL
                );
                """
            )

    @staticmethod
    def compute_hash(raw_skill_md: str) -> str:
        return hashlib.sha256(raw_skill_md.encode("utf-8")).hexdigest()

    def upsert_skill(
        self,
        *,
        name: str,
        description: str,
        raw_skill_md: str,
        body_md: str,
        source_type: str,
        source_uri: str,
        trust_status: str = "reference",
        granularity: str = "process",
        license_name: str = "",
        stars: int = 0,
        pushed_at: str = "",
        dependencies: dict[str, Any] | None = None,
        assets: list[str] | None = None,
        rebuild_indexes: bool = True,
    ) -> tuple[str, bool]:
        """Insert or update a skill by content hash. Returns (content_hash, is_new_or_changed)."""
        if trust_status not in VALID_TRUST_STATUSES:
            raise ValueError(f"Invalid trust_status: {trust_status}")
        if granularity not in VALID_GRANULARITIES:
            raise ValueError(f"Invalid granularity: {granularity}")

        content_hash = self.compute_hash(raw_skill_md)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        deps_json = json.dumps(dependencies or {}, ensure_ascii=False)

        snap_dir = self.skills_dir / content_hash
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / "SKILL.md").write_text(raw_skill_md, encoding="utf-8")
        (snap_dir / "assets.json").write_text(
            json.dumps(assets or [], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self._connect() as con:
            existing = con.execute(
                "SELECT created_at, trust_status FROM skills WHERE content_hash = ?",
                [content_hash],
            ).fetchone()
            created_at = existing[0] if existing else now
            # Preserve elevated trust status when re-scanning identical content
            effective_trust = existing[1] if existing and existing[1] != "reference" else trust_status

            con.execute(
                """
                INSERT OR REPLACE INTO skills (
                    content_hash, name, description, source_type, source_uri,
                    trust_status, granularity, license, stars, pushed_at,
                    dependencies_json, body_md, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    content_hash,
                    name,
                    description,
                    source_type,
                    source_uri,
                    effective_trust,
                    granularity,
                    license_name,
                    stars,
                    pushed_at,
                    deps_json,
                    body_md,
                    created_at,
                    now,
                ],
            )

            if existing is None:
                chunks = chunk_skill_markdown(name, description, body_md)
                for idx, (sec_title, text) in enumerate(chunks):
                    chunk_id = f"{content_hash}:{idx}"
                    con.execute(
                        """
                        INSERT INTO skill_chunks
                            (chunk_id, content_hash, section_title, chunk_order, chunk_text, embedding)
                        VALUES (?, ?, ?, ?, ?, NULL)
                        """,
                        [chunk_id, content_hash, sec_title, idx, text],
                    )
        if rebuild_indexes and existing is None:
            self.rebuild_fts_index()
        return content_hash, existing is None

    def rebuild_fts_index(self) -> bool:
        """Rebuild DuckDB BM25 full-text index over skill_chunks."""
        with self._connect() as con:
            if not self._fts_ready:
                return False
            count = con.execute("SELECT COUNT(*) FROM skill_chunks").fetchone()[0]
            if count == 0:
                return False
            con.execute(
                """
                PRAGMA create_fts_index(
                    'skill_chunks', 'chunk_id', 'chunk_text', 'section_title',
                    stemmer = 'porter', stopwords = 'english', overwrite = 1
                )
                """
            )
            return True

    def rebuild_vss_index(self) -> bool:
        """Rebuild HNSW cosine index if vss extension is loaded and vectors exist."""
        with self._connect() as con:
            if not self._vss_ready:
                return False
            count = con.execute(
                "SELECT COUNT(*) FROM skill_chunks WHERE embedding IS NOT NULL"
            ).fetchone()[0]
            if count == 0:
                return False
            con.execute("DROP INDEX IF EXISTS idx_skill_chunks_vec")
            con.execute(
                """
                CREATE INDEX idx_skill_chunks_vec
                ON skill_chunks USING HNSW (embedding)
                WITH (metric = 'cosine')
                """
            )
            return True

    def unembedded_chunks(self, limit: int | None = None) -> list[tuple[str, str]]:
        """Return (chunk_id, chunk_text) pairs missing embeddings."""
        sql = "SELECT chunk_id, chunk_text FROM skill_chunks WHERE embedding IS NULL ORDER BY chunk_id"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self._connect() as con:
            return con.execute(sql).fetchall()

    def write_embeddings(self, items: list[tuple[str, list[float]]]) -> int:
        """Persist generated embeddings in batch."""
        if not items:
            return 0
        with self._connect() as con:
            for chunk_id, vec in items:
                if len(vec) != self.embed_dim:
                    raise ValueError(f"Expected dim {self.embed_dim}, got {len(vec)} for {chunk_id}")
                con.execute(
                    f"UPDATE skill_chunks SET embedding = ?::FLOAT[{self.embed_dim}] WHERE chunk_id = ?",
                    [vec, chunk_id],
                )
        self.rebuild_vss_index()
        return len(items)

    def hybrid_search(
        self,
        query_text: str,
        query_embedding: list[float] | None = None,
        top_k: int = 20,
        rrf_k: int = 60,
    ) -> list[SearchHit]:
        """Run BM25 + Cosine Vector search and merge via RRF with zero source bias."""
        candidate_limit = max(top_k * 4, 60)
        bm25_ranks: dict[str, tuple[int, str]] = {}
        vec_ranks: dict[str, tuple[int, str]] = {}

        with self._connect() as con:
            if self._fts_ready:
                try:
                    rows = con.execute(
                        """
                        SELECT c.content_hash, c.section_title,
                               fts_main_skill_chunks.match_bm25(c.chunk_id, ?) AS score
                        FROM skill_chunks c
                        WHERE score IS NOT NULL
                        ORDER BY score DESC
                        LIMIT ?
                        """,
                        [query_text, candidate_limit],
                    ).fetchall()
                    rank = 1
                    for content_hash, sec_title, _ in rows:
                        if content_hash not in bm25_ranks:
                            bm25_ranks[content_hash] = (rank, sec_title)
                            rank += 1
                except duckdb.Error:
                    pass

            # Lexical fallback when fts extension is unavailable
            if not bm25_ranks and query_text.strip():
                tokens = [t.strip() for t in re.split(r"[\s,;/]+", query_text) if len(t.strip()) >= 2]
                if tokens:
                    clauses = " OR ".join("lower(chunk_text) LIKE ?" for _ in tokens)
                    params = [f"%{t.lower()}%" for t in tokens] + [candidate_limit]
                    rows = con.execute(
                        f"""
                        SELECT content_hash, section_title,
                               SUM(1) AS hits
                        FROM skill_chunks
                        WHERE {clauses}
                        GROUP BY content_hash, section_title
                        ORDER BY hits DESC
                        LIMIT ?
                        """,
                        params,
                    ).fetchall()
                    rank = 1
                    for content_hash, sec_title, _ in rows:
                        if content_hash not in bm25_ranks:
                            bm25_ranks[content_hash] = (rank, sec_title)
                            rank += 1

            if query_embedding is not None and len(query_embedding) == self.embed_dim:
                vec_rows = con.execute(
                    f"""
                    SELECT content_hash, section_title,
                           array_cosine_similarity(embedding, ?::FLOAT[{self.embed_dim}]) AS sim
                    FROM skill_chunks
                    WHERE embedding IS NOT NULL
                    ORDER BY sim DESC
                    LIMIT ?
                    """,
                    [query_embedding, candidate_limit],
                ).fetchall()
                rank = 1
                for content_hash, sec_title, sim in vec_rows:
                    if sim is not None and content_hash not in vec_ranks:
                        vec_ranks[content_hash] = (rank, sec_title)
                        rank += 1

            all_hashes = set(bm25_ranks) | set(vec_ranks)
            if not all_hashes:
                return []

            scored: list[tuple[str, float, int | None, int | None, str]] = []
            for h in all_hashes:
                b_rank, b_sec = bm25_ranks.get(h, (None, ""))
                v_rank, v_sec = vec_ranks.get(h, (None, ""))
                score = 0.0
                if b_rank is not None:
                    score += 1.0 / (rrf_k + b_rank)
                if v_rank is not None:
                    score += 1.0 / (rrf_k + v_rank)
                section = b_sec or v_sec
                scored.append((h, score, b_rank, v_rank, section))

            scored.sort(key=lambda x: x[1], reverse=True)
            top_items = scored[:top_k]

            placeholders = ", ".join("?" for _ in top_items)
            meta_rows = con.execute(
                f"""
                SELECT content_hash, name, description, source_type, source_uri,
                       trust_status, granularity, dependencies_json
                FROM skills
                WHERE content_hash IN ({placeholders})
                """,
                [x[0] for x in top_items],
            ).fetchall()
            meta_map = {r[0]: r for r in meta_rows}

        hits: list[SearchHit] = []
        for h, score, b_rank, v_rank, sec in top_items:
            row = meta_map.get(h)
            if not row:
                continue
            hits.append(
                SearchHit(
                    content_hash=h,
                    name=row[1],
                    description=row[2],
                    source_type=row[3],
                    source_uri=row[4],
                    trust_status=row[5],
                    granularity=row[6],
                    rrf_score=score,
                    bm25_rank=b_rank,
                    vec_rank=v_rank,
                    matched_section=sec,
                    dependencies=json.loads(row[7] or "{}"),
                )
            )
        return hits

    def lookup_skills_by_name(self, names: list[str]) -> dict[str, dict[str, Any]]:
        """Look up metadata and parsed dependencies for skill names referenced in a skeleton."""
        if not names:
            return {}
        placeholders = ", ".join("?" for _ in names)
        with self._connect() as con:
            rows = con.execute(
                f"""
                SELECT name, content_hash, trust_status, granularity, source_uri, dependencies_json
                FROM skills
                WHERE name IN ({placeholders})
                """,
                names,
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for name, h, trust, gran, uri, deps_json in rows:
            result[name] = {
                "content_hash": h,
                "trust_status": trust,
                "granularity": gran,
                "source_uri": uri,
                "dependencies": json.loads(deps_json or "{}"),
            }
        return result

    def add_feedback(
        self,
        *,
        query_text: str,
        facet: str,
        content_hash: str,
        label: str,
        note: str = "",
    ) -> str:
        """Record retrieval quality feedback from Stage 3 or Stage 6."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        fid = hashlib.sha256(f"{query_text}:{facet}:{content_hash}:{now.isoformat()}".encode()).hexdigest()[:16]
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO retrieval_feedback
                    (feedback_id, query_text, facet, content_hash, label, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [fid, query_text, facet, content_hash, label, note, now],
            )
        return fid

    def update_trust_status(self, content_hash: str, trust_status: str) -> bool:
        """Promote or update a skill's governance status after checkpoint review."""
        if trust_status not in VALID_TRUST_STATUSES:
            raise ValueError(f"Invalid trust_status: {trust_status}")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self._connect() as con:
            cur = con.execute(
                "UPDATE skills SET trust_status = ?, updated_at = ? WHERE content_hash = ? RETURNING content_hash",
                [trust_status, now, content_hash],
            ).fetchone()
        return cur is not None

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the skill library."""
        with self._connect() as con:
            total_skills = con.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            total_chunks = con.execute("SELECT COUNT(*) FROM skill_chunks").fetchone()[0]
            embedded_chunks = con.execute(
                "SELECT COUNT(*) FROM skill_chunks WHERE embedding IS NOT NULL"
            ).fetchone()[0]
            by_trust = dict(
                con.execute("SELECT trust_status, COUNT(*) FROM skills GROUP BY trust_status").fetchall()
            )
            by_source = dict(
                con.execute("SELECT source_type, COUNT(*) FROM skills GROUP BY source_type").fetchall()
            )
            feedback_count = con.execute("SELECT COUNT(*) FROM retrieval_feedback").fetchone()[0]
        return {
            "db_path": str(self.db_path),
            "total_skills": total_skills,
            "total_chunks": total_chunks,
            "embedded_chunks": embedded_chunks,
            "fts_ready": self._fts_ready,
            "vss_ready": self._vss_ready,
            "by_trust": by_trust,
            "by_source": by_source,
            "feedback_count": feedback_count,
        }
