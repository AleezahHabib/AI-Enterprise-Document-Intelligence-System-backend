"""Database queries for hybrid retrieval and query audit logging.
Governing specs: BE-02 §4, BE-08 §9.
"""

import json
from typing import Any, Dict, List, Optional
from uuid import UUID
import asyncpg

from app.models.queries import RetrievedChunk, RetrievalResult


HYBRID_RETRIEVAL_SQL = """
WITH vector_leg AS (
    SELECT c.id,
           1 - (c.embedding <=> $1::halfvec(768))                       AS similarity,
           ROW_NUMBER() OVER (ORDER BY c.embedding <=> $1::halfvec(768)) AS rank
    FROM chunk c
    WHERE c.embedding IS NOT NULL
      AND c.owner_key = ANY($3::text[])
      AND ($4::uuid[] IS NULL OR c.document_id = ANY($4::uuid[]))
    ORDER BY c.embedding <=> $1::halfvec(768)
    LIMIT $5
),
keyword_leg AS (
    SELECT c.id,
           ts_rank_cd(c.content_tsv, q.query)                                  AS ts_score,
           ROW_NUMBER() OVER (ORDER BY ts_rank_cd(c.content_tsv, q.query) DESC) AS rank
    FROM chunk c,
         websearch_to_tsquery('english', $2::text) AS q(query)
    WHERE c.content_tsv @@ q.query
      AND c.owner_key = ANY($3::text[])
      AND ($4::uuid[] IS NULL OR c.document_id = ANY($4::uuid[]))
    ORDER BY ts_score DESC
    LIMIT $5
),
fused AS (
    SELECT COALESCE(v.id, k.id)                                AS chunk_id,
           v.rank                                              AS vector_rank,
           k.rank                                              AS keyword_rank,
           v.similarity                                        AS vector_similarity,
           COALESCE(1.0 / ($6 + v.rank), 0.0)
         + COALESCE(1.0 / ($6 + k.rank), 0.0)                  AS rrf_score
    FROM vector_leg v
    FULL OUTER JOIN keyword_leg k ON v.id = k.id
)
SELECT f.chunk_id,
       f.vector_rank,
       f.keyword_rank,
       f.rrf_score,
       COALESCE(f.vector_similarity,
                1 - (c.embedding <=> $1::halfvec(768)))         AS similarity,
       c.content,
       c.page_from, c.page_to, c.section_path,
       c.char_start, c.char_end,
       c.document_id,
       d.title    AS document_title,
       d.filename AS document_filename
FROM fused f
JOIN chunk    c ON c.id = f.chunk_id
JOIN document d ON d.id = c.document_id
ORDER BY f.rrf_score DESC
LIMIT $7;
"""


import math


def parse_vector_literal(lit: Optional[str]) -> Optional[List[float]]:
    if not lit:
        return None
    try:
        if isinstance(lit, list):
            return lit
        s = str(lit).strip().strip("[]()")
        return [float(x.strip()) for x in s.split(",") if x.strip()]
    except Exception:
        return None


def compute_cosine_similarity(v1: Optional[List[float]], v2: Optional[List[float]]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (n1 * n2)))


FETCH_CHUNKS_FOR_RETRIEVAL_SQL = """
SELECT c.id AS chunk_id,
       c.content,
       c.page_from, c.page_to, c.section_path,
       c.char_start, c.char_end,
       c.document_id,
       c.embedding::text AS embedding_str,
       ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', $1::text)) AS ts_score,
       (c.content_tsv @@ websearch_to_tsquery('english', $1::text)) AS keyword_matched,
       d.title AS document_title,
       d.filename AS document_filename
FROM chunk c
JOIN document d ON d.id = c.document_id
WHERE c.owner_key = ANY($2::text[])
  AND ($3::uuid[] IS NULL OR c.document_id = ANY($3::uuid[]));
"""


async def execute_hybrid_retrieval(
    pool: asyncpg.Pool,
    query_vector_literal: str,
    question: str,
    owner_keys: List[str],
    document_ids: Optional[List[UUID]],
    candidates: int = 50,
    rrf_k: int = 60,
    top_k: int = 12,
    ef_search: int = 40,
) -> RetrievalResult:
    """Execute hybrid retrieval with HNSW vector search or fallback true cosine similarity."""
    async with pool.acquire() as conn:
        has_vector = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        doc_id_param = [str(d) for d in document_ids] if document_ids else None

        if has_vector:
            async with conn.transaction():
                # BE-08-R9: SET LOCAL hnsw.ef_search in the same transaction
                await conn.execute(f"SET LOCAL hnsw.ef_search = {int(ef_search)};")

                rows = await conn.fetch(
                    HYBRID_RETRIEVAL_SQL,
                    query_vector_literal,
                    question,
                    owner_keys,
                    doc_id_param,
                    candidates,
                    rrf_k,
                    top_k,
                )

            retrieved_chunks: List[RetrievedChunk] = []
            vector_hits = 0
            keyword_hits = 0

            for r in rows:
                v_rank = r["vector_rank"]
                k_rank = r["keyword_rank"]
                if v_rank is not None:
                    vector_hits += 1
                if k_rank is not None:
                    keyword_hits += 1

                retrieved_chunks.append(
                    RetrievedChunk(
                        chunk_id=r["chunk_id"],
                        document_id=r["document_id"],
                        document_title=r["document_title"],
                        document_filename=r["document_filename"],
                        content=r["content"],
                        page_from=r["page_from"],
                        page_to=r["page_to"],
                        section_path=r["section_path"],
                        char_start=r["char_start"],
                        char_end=r["char_end"],
                        similarity=float(r["similarity"]),
                        vector_rank=v_rank,
                        keyword_rank=k_rank,
                        rrf_score=float(r["rrf_score"]),
                        used_in_context=False,
                    )
                )

            return RetrievalResult(
                chunks=retrieved_chunks,
                candidate_count=len(retrieved_chunks),
                vector_hits=vector_hits,
                keyword_hits=keyword_hits,
            )

        else:
            # Native fallback: compute genuine vector cosine similarities and BM25 ranks
            raw_rows = await conn.fetch(
                FETCH_CHUNKS_FOR_RETRIEVAL_SQL,
                question,
                owner_keys,
                doc_id_param,
            )

            if not raw_rows:
                return RetrievalResult(chunks=[], candidate_count=0, vector_hits=0, keyword_hits=0)

            query_vec = parse_vector_literal(query_vector_literal)

            # Vector leg ranking
            scored_vector = []
            for r in raw_rows:
                chunk_vec = parse_vector_literal(r["embedding_str"])
                sim = compute_cosine_similarity(query_vec, chunk_vec) if query_vec and chunk_vec else 0.0
                scored_vector.append((r["chunk_id"], sim))

            # Sort vector leg by similarity descending
            scored_vector.sort(key=lambda x: x[1], reverse=True)
            vector_rank_map = {}
            for rank_idx, (cid, sim) in enumerate(scored_vector[:candidates], start=1):
                if sim > 0.0:
                    vector_rank_map[cid] = (rank_idx, sim)

            # Keyword leg ranking
            scored_keyword = []
            for r in raw_rows:
                if r["keyword_matched"] and (r["ts_score"] or 0) > 0:
                    scored_keyword.append((r["chunk_id"], float(r["ts_score"])))

            scored_keyword.sort(key=lambda x: x[1], reverse=True)
            keyword_rank_map = {}
            for rank_idx, (cid, score) in enumerate(scored_keyword[:candidates], start=1):
                keyword_rank_map[cid] = rank_idx

            # RRF Fusion
            row_map = {r["chunk_id"]: r for r in raw_rows}
            all_candidate_ids = set(vector_rank_map.keys()) | set(keyword_rank_map.keys())

            if not all_candidate_ids:
                return RetrievalResult(chunks=[], candidate_count=0, vector_hits=0, keyword_hits=0)

            fused = []
            for cid in all_candidate_ids:
                v_info = vector_rank_map.get(cid)
                v_rank = v_info[0] if v_info else None
                sim = v_info[1] if v_info else 0.0

                k_rank = keyword_rank_map.get(cid)

                score = 0.0
                if v_rank:
                    score += 1.0 / (rrf_k + v_rank)
                if k_rank:
                    score += 1.0 / (rrf_k + k_rank)

                fused.append((cid, score, v_rank, k_rank, sim))

            # Sort by RRF score descending
            fused.sort(key=lambda x: x[1], reverse=True)
            top_fused = fused[:top_k]

            retrieved_chunks = []
            vector_hits = 0
            keyword_hits = 0

            for cid, rrf_score, v_rank, k_rank, sim in top_fused:
                if v_rank is not None:
                    vector_hits += 1
                if k_rank is not None:
                    keyword_hits += 1

                r = row_map[cid]
                retrieved_chunks.append(
                    RetrievedChunk(
                        chunk_id=r["chunk_id"],
                        document_id=r["document_id"],
                        document_title=r["document_title"],
                        document_filename=r["document_filename"],
                        content=r["content"],
                        page_from=r["page_from"],
                        page_to=r["page_to"],
                        section_path=r["section_path"],
                        char_start=r["char_start"],
                        char_end=r["char_end"],
                        similarity=float(sim),
                        vector_rank=v_rank,
                        keyword_rank=k_rank,
                        rrf_score=float(rrf_score),
                        used_in_context=False,
                    )
                )

            return RetrievalResult(
                chunks=retrieved_chunks,
                candidate_count=len(retrieved_chunks),
                vector_hits=vector_hits,
                keyword_hits=keyword_hits,
            )


async def insert_query_log(
    pool: asyncpg.Pool,
    query_id: UUID,
    owner_key: Optional[str],
    question: str,
    scope: str,
    outcome: str,
    refusal_reason: Optional[str],
    answer_text: Optional[str],
    claims_payload: Optional[List[Dict[str, Any]]],
    retrieval_payload: Dict[str, Any],
    validation_attempts: int,
    validation_errors: Optional[List[Dict[str, Any]]],
    latency_ms: int,
) -> None:
    """Record query execution trace in query_log table (BE-02-R13)."""
    query = """
    INSERT INTO query_log (
        id, owner_key, question, scope, outcome, refusal_reason,
        answer_text, claims, retrieval, validation_attempts,
        validation_errors, latency_ms
    ) VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11::jsonb, $12
    )
    """
    async with pool.acquire() as conn:
        await conn.execute(
            query,
            query_id,
            owner_key,
            question,
            scope,
            outcome,
            refusal_reason,
            answer_text,
            json.dumps(claims_payload) if claims_payload else None,
            json.dumps(retrieval_payload),
            validation_attempts,
            json.dumps(validation_errors) if validation_errors else None,
            latency_ms,
        )


async def fetch_query_log(
    pool: asyncpg.Pool,
    query_id: UUID,
    owner_key: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Retrieve logged query trace by query_id."""
    query = """
    SELECT id, owner_key, question, scope, outcome, refusal_reason,
           answer_text, claims, retrieval, validation_attempts,
           validation_errors, latency_ms, created_at
    FROM query_log
    WHERE id = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, query_id)
        if not row:
            return None
        if row["owner_key"] and row["owner_key"] != owner_key:
            return None
        return dict(row)
