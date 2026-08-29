"""Hybrid retrieval service combining dense vector search and BM25 lexical search via RRF.
Governing spec: BE-08, ADR-0005.
"""

from typing import List, Optional
from uuid import UUID
import asyncpg

from app.core.config import Settings
from app.db.queries import execute_hybrid_retrieval
from app.embedding.client import GeminiEmbeddingClient, format_halfvec_literal
from app.models.documents import Scope
from app.models.queries import RetrievedChunk, RetrievalResult


def resolve_owner_keys(scope: Scope, caller_owner_key: Optional[str]) -> List[str]:
    """Map search scope to eligible document owner keys (BE-08-R3)."""
    if scope == Scope.DEMO:
        return ["__demo__"]
    elif scope == Scope.MINE:
        return [caller_owner_key] if caller_owner_key else []
    else:  # Scope.ALL
        if caller_owner_key:
            return ["__demo__", caller_owner_key]
        return ["__demo__"]


async def retrieve_chunks(
    question: str,
    scope: Scope,
    caller_owner_key: Optional[str],
    document_ids: Optional[List[UUID]],
    pool: asyncpg.Pool,
    settings: Settings,
    embedding_client: Optional[GeminiEmbeddingClient] = None,
) -> RetrievalResult:
    """Execute hybrid retrieval over the indexed corpus."""
    owner_keys = resolve_owner_keys(scope, caller_owner_key)
    if not owner_keys:
        return RetrievalResult(chunks=[], candidate_count=0, vector_hits=0, keyword_hits=0)

    if embedding_client is None:
        embedding_client = GeminiEmbeddingClient(settings)

    # Embed search query with task_type="RETRIEVAL_QUERY" (BE-06-R4, BE-08-R7)
    query_vector = await embedding_client.embed_query(question)
    query_vector_literal = format_halfvec_literal(query_vector)

    retrieval_res = await execute_hybrid_retrieval(
        pool=pool,
        query_vector_literal=query_vector_literal,
        question=question,
        owner_keys=owner_keys,
        document_ids=document_ids,
        candidates=settings.RETRIEVAL_CANDIDATES,
        rrf_k=settings.RRF_K,
        top_k=settings.RETRIEVAL_TOP_K,
        ef_search=settings.HNSW_EF_SEARCH,
    )

    # Tag the top CONTEXT_CHUNKS as used_in_context (BE-08-R24, BE-09-R4)
    context_k = min(len(retrieval_res.chunks), settings.CONTEXT_CHUNKS)
    marked_chunks: List[RetrievedChunk] = []

    for idx, c in enumerate(retrieval_res.chunks):
        is_context = idx < context_k
        marked_chunks.append(
            RetrievedChunk(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title,
                document_filename=c.document_filename,
                content=c.content,
                page_from=c.page_from,
                page_to=c.page_to,
                section_path=c.section_path,
                char_start=c.char_start,
                char_end=c.char_end,
                similarity=c.similarity,
                vector_rank=c.vector_rank,
                keyword_rank=c.keyword_rank,
                rrf_score=c.rrf_score,
                used_in_context=is_context,
            )
        )

    return RetrievalResult(
        chunks=marked_chunks,
        candidate_count=retrieval_res.candidate_count,
        vector_hits=retrieval_res.vector_hits,
        keyword_hits=retrieval_res.keyword_hits,
    )
