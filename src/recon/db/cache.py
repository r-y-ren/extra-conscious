"""Per-workspace DuckDB cache for Stage 1 and Stage 5 API responses."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb


class CacheDB:
    """Caches external API calls keyed by (provider, query_text, query_date)."""

    def __init__(self, workspace_dir: Path | str) -> None:
        self.recon_dir = Path(workspace_dir).resolve() / ".recon"
        self.raw_dir = self.recon_dir / "raw"
        self.db_path = self.recon_dir / "cache.duckdb"
        self.recon_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.db_path))

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key VARCHAR PRIMARY KEY,
                    provider VARCHAR NOT NULL,
                    query_text VARCHAR NOT NULL,
                    query_date DATE NOT NULL,
                    status_code INTEGER NOT NULL,
                    payload_json VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )

    @staticmethod
    def make_key(provider: str, query_text: str, query_date: date | None = None) -> str:
        day = (query_date or date.today()).isoformat()
        digest = hashlib.sha256(f"{provider}\n{day}\n{query_text}".encode("utf-8")).hexdigest()
        return digest

    def get(
        self,
        provider: str,
        query_text: str,
        query_date: date | None = None,
    ) -> Any | None:
        """Fetch cached JSON payload if present for the given date."""
        key = self.make_key(provider, query_text, query_date)
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM api_cache WHERE cache_key = ?",
                [key],
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def put(
        self,
        provider: str,
        query_text: str,
        status_code: int,
        payload: Any,
        query_date: date | None = None,
    ) -> Path:
        """Persist API response to DuckDB cache and raw JSON dump."""
        day = query_date or date.today()
        key = self.make_key(provider, query_text, day)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self._connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO api_cache
                    (cache_key, provider, query_text, query_date, status_code, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [key, provider, query_text, day, status_code, serialized, now],
            )
        raw_path = self.raw_dir / f"{provider}-{day.isoformat()}-{key[:12]}.json"
        raw_path.write_text(serialized, encoding="utf-8")
        return raw_path
