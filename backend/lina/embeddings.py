"""
embeddings.py — the semantic projection layer (MPS Phase F).

Turns her memories into points in embedding space — the *likeness* half of
recall. The ethical coordinates are the other half (the polytope mapping);
together they are the two-space retrieval of the MPS: semantic similarity
finds the text, ethical proximity finds the like moments.

An OpenAI-compatible /embeddings endpoint (default: the local cortex —
her own nomic engine on the carve), so any embedding model behind that
contract works. Failures degrade gracefully — recall falls back to
importance + ethical proximity. The vector space is auxiliary; the
polytope mapping is primary.

Environment:
    EMBEDDING_BASE_URL    — embeddings endpoint (default: http://127.0.0.1:8080/v1)
    EMBEDDING_BASE_MODEL  — embedding model (default: nomic-embed-text)
    EMBEDDING_API_KEY     — embeddings key (default: local — the cortex does not authenticate)
"""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("lina.embeddings")

DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = "nomic-embed-text"


class EmbeddingClient:
    """Async OpenAI-compatible embeddings client. Never raises to callers —
    a failed embed returns None, and recall degrades honestly."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        referer: str | None = None,
        title: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("EMBEDDING_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        # Accept either the API root (…/v1) or the full endpoint (…/v1/embeddings).
        if self.base_url.endswith("/embeddings"):
            self.base_url = self.base_url[: -len("/embeddings")]
        self.model = model or os.getenv("EMBEDDING_BASE_MODEL") or DEFAULT_MODEL
        self.api_key = (
            api_key
            or os.getenv("EMBEDDING_API_KEY")
            or "local"  # her cortex does not authenticate
        )
        self.referer = referer or os.getenv("EMBEDDING_REFERER") or ""
        self.title = title or os.getenv("EMBEDDING_TITLE") or ""
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def embed(self, text: str) -> list[float] | None:
        """Embed text → vector. None on failure — degrade, never raise.

        The payload matches the documented OpenRouter embeddings contract:
        model, input, encoding_format=float. The ranking headers are sent
        only when configured.
        """
        text = (text or "").strip()
        if not text or not self.available:
            return None
        try:
            client = self._get_client()
            headers = {"Authorization": f"Bearer {self.api_key}"}
            if self.referer:
                headers["HTTP-Referer"] = self.referer
            if self.title:
                headers["X-OpenRouter-Title"] = self.title
            resp = await client.post(
                f"{self.base_url}/embeddings",
                json={
                    "model": self.model,
                    "input": text,
                    "encoding_format": "float",
                },
                headers=headers,
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
