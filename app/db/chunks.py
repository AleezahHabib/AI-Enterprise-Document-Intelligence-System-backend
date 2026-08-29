"""Database queries for chunk storage, embeddings, and retrieval.
Governing spec: BE-02, BE-07.
"""

from typing import List, Optional, Tuple
from uuid import UUID
import asyncpg
from app.models.chunking import PreparedChunk
from app.models.documents import ChunkWithDocument


async def insert_chunks(
    pool: asyncpg.Pool,
    document_id: UUID,
    owner_key: str,
    chunks: List[PreparedChunk],
) -> List[int]:
    """Phase 1: Insert all chunks for a document in a single statement (BE-07-R1)."""
    if not chunks:
        return []

    # Build multi-row VALUES query
    # (document_id, owner_key, ordinal, page_from, page_to, section_path, char_start, char_end, content, token_count)
    query = """
    INSERT INTO chunk (
        document_id, owner_key, ordinal, page_from, page_to, section_path,
        char_start, char_end, content, token_count
    )
    SELECT
        x.document_id, x.owner_key, x.ordinal, x.page_from, x.page_to, x.section_path,
        x.char_start, x.char_end, x.content, x.token_count
    FROM jsonb_to_recordset($1::jsonb) AS x(
        document_id uuid,
        owner_key text,
        ordinal int,
        page_from int,
        page_to int,
        section_path text,
        char_start int,
        char_end int,
        content text,
        token_count int
    )
    ORDER BY x.ordinal ASC
    RETURNING id
    """

    import json
    payload = json.dumps([
        {
            "document_id": str(document_id),
            "owner_key": owner_key,
            "ordinal": c.ordinal,
            "page_from": c.page_from,
            "page_to": c.page_to,
            "section_path": c.section_path,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "content": c.content,
            "token_count": c.token_count,
        }
        for c in chunks
    ])

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, payload)
        return [row["id"] for row in rows]


async def set_embeddings(
    pool: asyncpg.Pool,
    rows: List[Tuple[int, str, str]],  # (chunk_id, vector_literal, model)
    dimension: int = 768,
) -> None:
    """Phase 2: Update embeddings in batches (BE-07-R2, BE-07-R5)."""
    if not rows:
        return

    # Check if vector extension is present
    async with pool.acquire() as conn:
        has_vector = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )

        val_placeholders = []
        params = []
        for idx, (chunk_id, vec_literal, model) in enumerate(rows):
            p1 = idx * 3 + 1
            p2 = idx * 3 + 2
            p3 = idx * 3 + 3
            val_placeholders.append(f"(${p1}::bigint, ${p2}::text, ${p3}::text)")
            params.extend([chunk_id, vec_literal, model])

        values_clause = ", ".join(val_placeholders)
        cast_expr = f"v.emb::halfvec({dimension})" if has_vector else "v.emb"
        query = f"""
        UPDATE chunk AS c
        SET embedding = {cast_expr},
            embedding_model = v.model
        FROM (VALUES {values_clause}) AS v(id, emb, model)
        WHERE c.id = v.id
        """

        await conn.execute(query, *params)


async def count_unembedded(pool: asyncpg.Pool, document_id: UUID) -> int:
    """Verification for BE-07-R8: Count chunks where embedding IS NULL."""
    query = "SELECT COUNT(*) FROM chunk WHERE document_id = $1 AND embedding IS NULL"
    async with pool.acquire() as conn:
        count = await conn.fetchval(query, document_id)
        return count or 0


async def delete_chunks(pool: asyncpg.Pool, document_id: UUID) -> int:
    """Cleanup all chunks on document ingestion failure (BE-07-R9)."""
    query = "DELETE FROM chunk WHERE document_id = $1"
    async with pool.acquire() as conn:
        result = await conn.execute(query, document_id)
        # Parse deleted count from result tag e.g. "DELETE 42"
        try:
            return int(result.split()[-1])
        except Exception:
            return 0


async def fetch_chunks_by_id(
    pool: asyncpg.Pool,
    ids: List[int],
) -> List[ChunkWithDocument]:
    """Citation resolution: fetch chunks by ID with parent document metadata (BE-07 §7)."""
    if not ids:
        return []

    query = """
    SELECT c.id, c.document_id, d.title AS document_title, c.ordinal,
           c.page_from, c.page_to, c.section_path, c.char_start, c.char_end,
           c.content, c.token_count, c.embedding_model
    FROM chunk c
    JOIN document d ON c.document_id = d.id
    WHERE c.id = ANY($1::bigint[])
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, ids)
        return [
            ChunkWithDocument(
                id=row["id"],
                document_id=row["document_id"],
                document_title=row["document_title"],
                ordinal=row["ordinal"],
                page_from=row["page_from"],
                page_to=row["page_to"],
                section_path=row["section_path"],
                char_start=row["char_start"],
                char_end=row["char_end"],
                content=row["content"],
                token_count=row["token_count"],
                embedding_model=row["embedding_model"],
            )
            for row in rows
        ]
