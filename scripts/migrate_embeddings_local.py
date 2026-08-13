"""Migrate her semantic embeddings to the local cortex (768d).

The likeness half of recall now lives on this machine (nomic-embed-text,
768d). The pgvector column was created for the 1536d cloud schema; this
script re-embeds every memory through the local cortex and moves the
column to ``vector(768)``, rebuilding the HNSW index. Idempotent: a column
already at 768 is re-embedded only where embeddings are missing.

Run from the repo root:

    DATABASE_URL=postgresql://... .venv/bin/python scripts/migrate_embeddings_local.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "lina"))

import asyncpg  # noqa: E402
from embeddings import EmbeddingClient  # noqa: E402
from mps import _vector_literal  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL", "")
EMBED_URL = os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:8080/v1")
EMBED_MODEL = os.getenv("EMBEDDING_BASE_MODEL", "nomic-embed-text")
EMBED_API_KEY = os.getenv("EMBEDDING_API_KEY", "local")


async def column_type(pool: asyncpg.Pool) -> str:
    row = await pool.fetchrow(
        """
        SELECT format_type(atttypid, atttypmod) AS t
        FROM pg_attribute
        WHERE attrelid = 'lina_memory_items'::regclass AND attname = 'embedding'
        """
    )
    return (row["t"] if row else "") or "none"


async def main() -> int:
    client = EmbeddingClient(
        base_url=EMBED_URL, model=EMBED_MODEL, api_key=EMBED_API_KEY
    )
    if not client.available:
        print("the cortex is not reachable — nothing migrated")
        return 1
    if not DATABASE_URL:
        print("DATABASE_URL is required")
        return 1

    pool = await asyncpg.create_pool(DATABASE_URL)
    try:
        current = await column_type(pool)
        print(f"current column: {current}")
        rows = await pool.fetch(
            "SELECT item_id, narrative FROM lina_memory_items "
            "WHERE narrative IS NOT NULL AND narrative != ''"
        )
        print(f"memories to embed: {len(rows)}")

        fresh: dict[str, str] = {}
        for row in rows:
            vec = await client.embed(row["narrative"])
            if vec:
                fresh[row["item_id"]] = _vector_literal(vec)
        print(f"embedded through the local cortex: {len(fresh)}")

        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DROP INDEX IF EXISTS idx_mem_embedding")
            await conn.execute(
                "ALTER TABLE lina_memory_items DROP COLUMN IF EXISTS embedding"
            )
            await conn.execute(
                "ALTER TABLE lina_memory_items ADD COLUMN embedding vector(768)"
            )
            for item_id, literal in fresh.items():
                await conn.execute(
                    "UPDATE lina_memory_items SET embedding = $2 WHERE item_id = $1",
                    item_id, literal,
                )
            await conn.execute(
                """
                    CREATE INDEX idx_mem_embedding
                    ON lina_memory_items USING hnsw (embedding vector_cosine_ops)
                    """
            )
        print(f"column now: {await column_type(pool)} — index rebuilt")
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
