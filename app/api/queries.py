"""Query API router.
Governing specs: BE-08, BE-09, BE-10, BE-11, BE-12 §4, BE-12 §6.
"""

from datetime import datetime, timezone
import time
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
import asyncpg

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.api.deps import Identity, get_identity
from app.db.pool import get_pool
from app.db.queries import insert_query_log, fetch_query_log
from app.models.queries import (
    EnrichedClaimOut,
    NearestDocumentOut,
    QueryIn,
    QueryOutcome,
    QueryResponseOut,
    RefusalPayloadOut,
    RefusalReason,
    RetrievalChunkOut,
    RetrievalInspectorOut,
    RetrievalResult,
)
from app.retrieval.hybrid import retrieve_chunks
from app.retrieval.gate import evaluate_gate, build_refusal_payload
from app.generation.generate import execute_generation_pipeline

router = APIRouter(prefix="/query", tags=["query"])
queries_router = APIRouter(prefix="/queries", tags=["queries"])


def _build_retrieval_inspector(retrieval_res: RetrievalResult) -> RetrievalInspectorOut:
    """Build retrieval inspector diagnostic block for frontend."""
    return RetrievalInspectorOut(
        candidate_count=retrieval_res.candidate_count,
        vector_hits=retrieval_res.vector_hits,
        keyword_hits=retrieval_res.keyword_hits,
        chunks=[
            RetrievalChunkOut(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title,
                similarity=c.similarity,
                vector_rank=c.vector_rank,
                keyword_rank=c.keyword_rank,
                rrf_score=c.rrf_score,
                used_in_context=c.used_in_context,
                section_path=c.section_path,
                page_from=c.page_from,
                page_to=c.page_to,
                char_start=c.char_start,
                char_end=c.char_end,
                content=c.content,
            )
            for c in retrieval_res.chunks
        ],
    )


@router.post("", response_model=QueryResponseOut)
async def ask_question(
    query_in: QueryIn,
    identity: Identity = Depends(get_identity),
    pool: asyncpg.Pool = Depends(get_pool),
    settings: Settings = Depends(get_settings),
) -> QueryResponseOut:
    """Answer a question over indexed documents or return an honest refusal (BE-12-R13: returns 200)."""
    t0 = time.perf_counter()
    query_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)

    # Step 1: Hybrid Retrieval (BE-08)
    retrieval_res = await retrieve_chunks(
        question=query_in.question,
        scope=query_in.scope,
        caller_owner_key=identity.owner_key,
        document_ids=query_in.document_ids,
        pool=pool,
        settings=settings,
    )

    # Step 2: Confidence Gate (BE-11 §5)
    gate_passed, refusal_reason = evaluate_gate(retrieval_res, settings)

    outcome: QueryOutcome
    answer_text = None
    enriched_claims = None
    refusal_payload = None
    validation_attempts = 0
    validation_errors_log = None

    if not gate_passed:
        # Refused before generation (BE-11-R1: zero LLM cost)
        outcome = QueryOutcome.INSUFFICIENT_CONTEXT
        refusal_payload = build_refusal_payload(refusal_reason, retrieval_res)
    else:
        # Step 3: Generation & Citation Validation (BE-09, BE-10)
        context_chunks = [c for c in retrieval_res.chunks if c.used_in_context]
        outcome, answer_text, enriched_claims, gen_refusal_reason, validation_attempts, validation_errors_log = (
            await execute_generation_pipeline(
                question=query_in.question,
                context_chunks=context_chunks,
                settings=settings,
            )
        )

        if outcome == QueryOutcome.INSUFFICIENT_CONTEXT:
            refusal_payload = build_refusal_payload(gen_refusal_reason, retrieval_res)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    retrieval_inspector = _build_retrieval_inspector(retrieval_res) if query_in.include_retrieval else None

    # Step 4: Audit Logging in query_log (BE-02-R13)
    claims_dict_list = [c.model_dump() for c in enriched_claims] if enriched_claims else None
    retrieval_log_dict = _build_retrieval_inspector(retrieval_res).model_dump()

    try:
        await insert_query_log(
            pool=pool,
            query_id=query_id,
            owner_key=identity.owner_key,
            question=query_in.question,
            scope=query_in.scope.value,
            outcome=outcome.value,
            refusal_reason=refusal_payload.reason.value if refusal_payload else None,
            answer_text=answer_text,
            claims_payload=claims_dict_list,
            retrieval_payload=retrieval_log_dict,
            validation_attempts=validation_attempts,
            validation_errors=validation_errors_log,
            latency_ms=latency_ms,
        )
    except Exception:
        # Logging error should not fail the user's query response
        pass

    return QueryResponseOut(
        id=query_id,
        question=query_in.question,
        status=outcome,
        answer=answer_text,
        claims=enriched_claims,
        refusal=refusal_payload,
        latency_ms=latency_ms,
        retrieval=retrieval_inspector,
        created_at=created_at,
    )


@queries_router.get("/{query_id}")
async def get_logged_query(
    query_id: UUID,
    identity: Identity = Depends(get_identity),
    pool: asyncpg.Pool = Depends(get_pool),
):
    """Retrieve historical query log replay."""
    row = await fetch_query_log(pool, query_id, identity.owner_key)
    if not row:
        raise NotFoundError()
    return row
