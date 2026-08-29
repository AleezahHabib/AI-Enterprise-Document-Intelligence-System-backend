import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
from app.core.config import get_settings
from app.retrieval.hybrid import retrieve_chunks
from app.retrieval.gate import evaluate_gate
from app.models.documents import Scope

async def trace_retrieval():
    settings = get_settings()
    pool = await asyncpg.create_pool(settings.DATABASE_URL)
    
    question = "Who is the Open Book Contract Management guidance intended for?"
    caller_owner_key = "session:cf87f34d-b882-4c0e-90a9-04b67e6bdb72"
    
    for sc in [Scope.ALL, Scope.MINE, Scope.DEMO]:
        print(f"\n=================== RETRIEVAL FOR SCOPE: {sc} ===================")
        res = await retrieve_chunks(
            question=question,
            scope=sc,
            caller_owner_key=caller_owner_key,
            document_ids=None,
            pool=pool,
            settings=settings,
        )
        gate_passed, reason = evaluate_gate(res, settings)
        print(f"Total chunks retrieved: {len(res.chunks)} | Gate passed: {gate_passed} | Refusal reason: {reason}")
        for idx, c in enumerate(res.chunks):
            used = " [USED IN CONTEXT]" if c.used_in_context else ""
            print(f"  #{idx+1} Doc: '{c.document_title}' | Chunk ID: {c.chunk_id} | Sim: {c.similarity:.4f} | RRF: {c.rrf_score:.4f} | VRank: {c.vector_rank} | KRank: {c.keyword_rank}{used}")
            print(f"      Text: {c.content[:120].strip()!r}")
            
    await pool.close()

if __name__ == "__main__":
    asyncio.run(trace_retrieval())
