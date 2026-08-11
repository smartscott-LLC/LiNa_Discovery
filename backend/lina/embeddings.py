"""
embeddings.py — the semantic projection layer (MPS Phase F).

Turns her memories into points in embedding space — the *likeness* half of
recall. The ethical coordinates are the other half (the polytope mapping);
together they are the two-space retrieval of the MPS: semantic similarity
finds the text, ethical proximity finds the like moments.

An OpenAI-compatible /embeddings endpoint (default: OpenRouter), so any
embedding model behind that contract works. Failures degrade gracefully —
recall falls back to importance + ethical proximity. The vector space is
auxiliary; the polytope mapping is primary.
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("lina.embeddings")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/text-embedding-3-small"
DEFAULT_DIMENSIONS = 1536


class EmbeddingClient:
    """Async OpenAI-compatible embeddings client. Never raises to callers —
    a failed embed returns None, and recall degrades honestly."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        dimensions: int | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("EMBEDDING_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
        self.api_key = (
            api_key
            or os.getenv("EMBEDDING_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
            or ""
        )
        self.dimensions = int(
            dimensions or os.getenv("EMBEDDING_DIMENSIONS") or DEFAULT_DIMENSIONS
        )
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def embed(self, text: str) -> list[float] | None:
        """Embed text → vector. None on failure — degrade, never raise."""
        text = (text or "").strip()
        if not text or not self.available:
            return None
        try:
            client = self._get_client()
            resp = await client.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": text, "dimensions": self.dimensions},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return [float(x) for x in data["data"][0]["embedding"]]
        except Exception as exc:
            log.warning(
                f"[embeddings] embed failed ({exc}) — degrading to ethical proximity"
            )
            return None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
