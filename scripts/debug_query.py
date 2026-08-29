import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
from app.core.config import get_settings
from app.retrieval.hybrid import retrieve_chunks
from app.retrieval.gate import evaluate_gate
from app.generation.generate import execute_generation_pipeline
from app.models.documents import Scope

async def debug_query():
    settings = get_settings()
    pool = await asyncpg.create_pool(settings.DATABASE_URL)
    
    question = "Who is the Open Book Contract Management guidance intended for?"
    scope = Scope.MINE
    caller_owner_key = "session:cf87f34d-b882-4c0e-90a9-04b67e6bdb72"
    
    retrieval_res = await retrieve_chunks(
        question=question,
        scope=scope,
        caller_owner_key=caller_owner_key,
        document_ids=None,
        pool=pool,
        settings=settings,
    )
    
    gate_passed, refusal_reason = evaluate_gate(retrieval_res, settings)
    
    outcome, answer_prose, enriched_claims, refusal_reason, attempts, errors = await execute_generation_pipeline(
        question=question,
        context_chunks=[c for c in retrieval_res.chunks if c.used_in_context],
        settings=settings,
    )
    
    with open("debug_output.txt", "w", encoding="utf-8") as f:
        f.write(f"Gate passed: {gate_passed} | Refusal: {refusal_reason}\n")
        f.write(f"Outcome: {outcome}\n")
        f.write(f"Answer Prose: {answer_prose}\n")
        f.write(f"Enriched Claims: {enriched_claims}\n")
        f.write(f"Validation Attempts: {attempts}\n")
        f.write(f"Validation Errors: {errors}\n")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(debug_query())
