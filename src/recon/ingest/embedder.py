"""Pluggable embedding backends for bge-m3 vector indexing."""

from __future__ import annotations

import json
import os
import subprocess
from abc import ABC, abstractmethod
from typing import Sequence

import httpx

from recon.config import EmbeddingConfig
from recon.db.library import SkillLibrary


class EmbeddingProvider(ABC):
    """Abstract batch text embedder."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return dense vectors matching configured dimension."""


class OpenAICompatEmbedder(EmbeddingProvider):
    """Calls any /v1/embeddings endpoint (Ollama, vLLM, OpenAI-compatible)."""

    def __init__(self, model: str, api_base: str, api_key: str = "") -> None:
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = httpx.post(
            f"{self.api_base}/embeddings",
            headers=headers,
            json={"model": self.model, "input": list(texts)},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        data.sort(key=lambda item: item["index"])
        return [item["embedding"] for item in data]


class SentenceTransformersEmbedder(EmbeddingProvider):
    """Local sentence-transformers embedder (lazy import)."""

    def __init__(self, model: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._model.encode(list(texts), normalize_embeddings=True)
        return [v.tolist() for v in vecs]


class RemoteComputeEmbedder(EmbeddingProvider):
    """Dispatches batch embedding to a remote GPU machine over SSH (remote-compute)."""

    def __init__(self, model: str, remote_host: str = "wsl") -> None:
        self.model = model
        self.remote_host = remote_host

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        remote_py = (
            "import json, sys; "
            "from sentence_transformers import SentenceTransformer; "
            f"m = SentenceTransformer({self.model!r}); "
            "texts = json.load(sys.stdin); "
            "vecs = m.encode(texts, normalize_embeddings=True); "
            "json.dump([v.tolist() for v in vecs], sys.stdout)"
        )
        proc = subprocess.run(
            ["ssh", self.remote_host, f"python3 -c {remote_py!r}"],
            input=json.dumps(list(texts), ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Remote embed failed on {self.remote_host}: {proc.stderr.strip()}")
        return json.loads(proc.stdout)


def resolve_embedder(cfg: EmbeddingConfig, backend_override: str | None = None) -> EmbeddingProvider | None:
    """Resolve the active embedding provider or return None if disabled/unavailable."""
    backend = (backend_override or cfg.backend or "auto").lower()
    if backend == "disabled":
        return None

    api_key = os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else ""

    if backend == "openai_compat":
        if not cfg.api_base:
            raise ValueError("embedding.api_base must be set for openai_compat backend")
        return OpenAICompatEmbedder(cfg.model, cfg.api_base, api_key)

    if backend == "remote":
        return RemoteComputeEmbedder(cfg.model, cfg.remote_host)

    if backend == "sentence_transformers":
        return SentenceTransformersEmbedder(cfg.model)

    # auto resolution
    if cfg.api_base:
        return OpenAICompatEmbedder(cfg.model, cfg.api_base, api_key)
    try:
        import sentence_transformers  # noqa: F401

        return SentenceTransformersEmbedder(cfg.model)
    except ImportError:
        return None


def embed_missing_chunks(
    library: SkillLibrary,
    embedder: EmbeddingProvider,
    *,
    batch_size: int = 32,
) -> int:
    """Incrementally embed only chunks with NULL embedding."""
    pending = library.unembedded_chunks()
    if not pending:
        return 0
    total = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        ids = [c[0] for c in batch]
        texts = [c[1] for c in batch]
        vecs = embedder.embed(texts)
        total += library.write_embeddings(list(zip(ids, vecs)))
    return total
